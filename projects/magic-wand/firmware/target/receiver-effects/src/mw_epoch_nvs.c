#include "mw_epoch_nvs.h"

#include <errno.h>
#include <limits.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/util.h>

#define MW_EPOCH_PARTITION_NODE DT_NODELABEL(mw_epoch_partition)
#define MW_EPOCH_NVS_ID_BASE UINT16_C(0x4D00)
#define MW_EPOCH_NVS_LAST_ID \
    (MW_EPOCH_NVS_ID_BASE + \
     (MW_EPOCH_LOGICAL_CHANNEL_COUNT * MW_EPOCH_SLOT_COUNT) - 1U)

#if !DT_NODE_HAS_STATUS(MW_EPOCH_PARTITION_NODE, okay)
#error "An enabled dedicated mw_epoch_partition devicetree node is required"
#endif

#if !defined(CONFIG_NVS_DATA_CRC)
#error "CONFIG_NVS_DATA_CRC=y is mandatory for the epoch NVS adapter"
#endif

BUILD_ASSERT(MW_EPOCH_SLOT_COUNT == 2U,
             "The epoch journal requires exactly two A/B slots");
BUILD_ASSERT(MW_EPOCH_NVS_LAST_ID <= UINT16_MAX,
             "The epoch NVS ID range must fit uint16_t");

static uint16_t slot_id(uint8_t logical_channel, uint8_t copy_index)
{
    const uint16_t offset = (uint16_t)(
        ((uint16_t)logical_channel * (uint16_t)MW_EPOCH_SLOT_COUNT)
        + (uint16_t)copy_index);
    return (uint16_t)(MW_EPOCH_NVS_ID_BASE + offset);
}

static bool partition_overlaps_settings(void)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(storage_partition), okay)
    const struct device *epoch_device =
        PARTITION_NODE_DEVICE(MW_EPOCH_PARTITION_NODE);
    const struct device *settings_device =
        PARTITION_NODE_DEVICE(DT_NODELABEL(storage_partition));
    const uint64_t epoch_start =
        (uint64_t)PARTITION_NODE_OFFSET(MW_EPOCH_PARTITION_NODE);
    const uint64_t epoch_end = epoch_start
        + (uint64_t)PARTITION_NODE_SIZE(MW_EPOCH_PARTITION_NODE);
    const uint64_t settings_start =
        (uint64_t)PARTITION_NODE_OFFSET(DT_NODELABEL(storage_partition));
    const uint64_t settings_end = settings_start
        + (uint64_t)PARTITION_NODE_SIZE(DT_NODELABEL(storage_partition));

    return (epoch_device == settings_device)
        && (epoch_start < settings_end)
        && (settings_start < epoch_end);
#else
    return false;
#endif
}

static mw_epoch_slot_state_t nvs_read_slot(
    void *context,
    uint8_t logical_channel,
    uint8_t copy_index,
    uint8_t data_out[MW_EPOCH_RECORD_ENCODED_SIZE],
    size_t *stored_length_out
)
{
    mw_epoch_nvs_adapter_t *adapter = (mw_epoch_nvs_adapter_t *)context;
    ssize_t result;

    if (stored_length_out != NULL) {
        *stored_length_out = 0U;
    }
    if ((adapter == NULL)
        || !adapter->mounted
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (copy_index >= MW_EPOCH_SLOT_COUNT)
        || (data_out == NULL)
        || (stored_length_out == NULL)) {
        return MW_EPOCH_SLOT_IO_ERROR;
    }

    result = nvs_read(
        &adapter->fs,
        slot_id(logical_channel, copy_index),
        data_out,
        MW_EPOCH_RECORD_ENCODED_SIZE);
    if (result == -ENOENT) {
        return MW_EPOCH_SLOT_ENOENT;
    }
    if (result < 0) {
        return MW_EPOCH_SLOT_IO_ERROR;
    }

    *stored_length_out = (size_t)result;
    return MW_EPOCH_SLOT_PRESENT;
}

static int32_t nvs_write_slot(
    void *context,
    uint8_t logical_channel,
    uint8_t copy_index,
    const uint8_t *data,
    size_t data_length
)
{
    mw_epoch_nvs_adapter_t *adapter = (mw_epoch_nvs_adapter_t *)context;
    ssize_t result;

    if ((adapter == NULL)
        || !adapter->mounted
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (copy_index >= MW_EPOCH_SLOT_COUNT)
        || (data == NULL)
        || (data_length != MW_EPOCH_RECORD_ENCODED_SIZE)) {
        return -EINVAL;
    }

    result = nvs_write(
        &adapter->fs,
        slot_id(logical_channel, copy_index),
        data,
        data_length);
    if ((result > (ssize_t)INT32_MAX) || (result < (ssize_t)INT32_MIN)) {
        return -EOVERFLOW;
    }
    return (int32_t)result;
}

static void clear_ram_window_unlocked(
    mw_epoch_nvs_channel_context_t *context
)
{
    context->ram_session_id = 0U;
    context->ram_sequence_ceiling = 0U;
    context->ram_receive_high_water = 0U;
    context->ram_window_bound = false;
}

static bool lock_mounted(mw_epoch_nvs_adapter_t *adapter)
{
    return (adapter != NULL)
        && adapter->mounted
        && (k_mutex_lock(&adapter->mutex, K_FOREVER) == 0);
}

int mw_epoch_nvs_mount(mw_epoch_nvs_adapter_t *adapter)
{
    const struct device *flash_device;
    struct flash_pages_info page_info;
    mw_epoch_store_backend_t backend;
    size_t partition_size;
    size_t page_size;
    size_t sector_count;
    unsigned int channel;
    int result;

    if (adapter == NULL) {
        return -EINVAL;
    }
    (void)memset(adapter, 0, sizeof(*adapter));
    k_mutex_init(&adapter->mutex);

    if (partition_overlaps_settings()) {
        return -EINVAL;
    }
    flash_device = PARTITION_NODE_DEVICE(MW_EPOCH_PARTITION_NODE);
    if (!device_is_ready(flash_device)) {
        return -ENODEV;
    }

    adapter->fs.flash_device = flash_device;
    adapter->fs.offset = PARTITION_NODE_OFFSET(MW_EPOCH_PARTITION_NODE);
    result = flash_get_page_info_by_offs(
        flash_device, adapter->fs.offset, &page_info);
    if (result != 0) {
        return result;
    }

    partition_size = (size_t)PARTITION_NODE_SIZE(MW_EPOCH_PARTITION_NODE);
    page_size = page_info.size;
    if ((page_size == 0U)
        || (page_size > UINT16_MAX)
        || ((page_size & (page_size - 1U)) != 0U)
        || (page_info.start_offset != adapter->fs.offset)
        || (partition_size < (2U * page_size))
        || ((partition_size % page_size) != 0U)) {
        return -EINVAL;
    }
    sector_count = partition_size / page_size;
    if ((sector_count < 2U) || (sector_count > UINT16_MAX)) {
        return -EINVAL;
    }

    adapter->fs.sector_size = (uint32_t)page_size;
    adapter->fs.sector_count = (uint16_t)sector_count;
    result = nvs_mount(&adapter->fs);
    if (result != 0) {
        return result;
    }

    backend.read_slot = nvs_read_slot;
    backend.write_slot = nvs_write_slot;
    backend.context = adapter;
    if (!mw_epoch_store_init(&adapter->store, &backend)) {
        return -EINVAL;
    }
    for (channel = 0U; channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT; ++channel) {
        adapter->channels[channel].adapter = adapter;
        adapter->channels[channel].logical_channel = (uint8_t)channel;
        clear_ram_window_unlocked(&adapter->channels[channel]);
    }
    adapter->mounted = true;
    return 0;
}

mw_epoch_store_result_t mw_epoch_nvs_load_channel(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel,
    uint32_t receiver_id,
    uint32_t wand_id,
    uint32_t configured_sequence_ceiling,
    mw_epoch_provisioning_policy_t provisioning_policy
)
{
    mw_epoch_store_result_t result;

    if ((logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !lock_mounted(adapter)) {
        return MW_EPOCH_STORE_NOT_READY;
    }
    clear_ram_window_unlocked(&adapter->channels[logical_channel]);
    result = mw_epoch_store_load_channel(
        &adapter->store,
        logical_channel,
        receiver_id,
        wand_id,
        configured_sequence_ceiling,
        provisioning_policy);
    k_mutex_unlock(&adapter->mutex);
    return result;
}

mw_epoch_store_result_t mw_epoch_nvs_provision_channel(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel
)
{
    mw_epoch_store_result_t result;

    if ((logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !lock_mounted(adapter)) {
        return MW_EPOCH_STORE_NOT_READY;
    }
    clear_ram_window_unlocked(&adapter->channels[logical_channel]);
    result = mw_epoch_store_provision_channel(
        &adapter->store, logical_channel);
    k_mutex_unlock(&adapter->mutex);
    return result;
}

bool mw_epoch_nvs_snapshot(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel,
    mw_epoch_record_t *record_out
)
{
    bool result;

    if ((logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !lock_mounted(adapter)) {
        if (record_out != NULL) {
            const mw_epoch_record_t zero = {0};
            *record_out = zero;
        }
        return false;
    }
    result = mw_epoch_store_snapshot(
        &adapter->store, logical_channel, record_out);
    k_mutex_unlock(&adapter->mutex);
    return result;
}

mw_epoch_nvs_channel_context_t *mw_epoch_nvs_channel_context(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel
)
{
    if ((adapter == NULL)
        || !adapter->mounted
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)) {
        return NULL;
    }
    return &adapter->channels[logical_channel];
}

bool mw_epoch_nvs_commit_session_epoch(
    void *context,
    uint32_t next_session_id
)
{
    mw_epoch_nvs_channel_context_t *channel =
        (mw_epoch_nvs_channel_context_t *)context;
    mw_epoch_nvs_adapter_t *adapter;
    mw_epoch_store_result_t result;

    if ((channel == NULL) || (channel->adapter == NULL)) {
        return false;
    }
    adapter = channel->adapter;
    if ((channel->logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (&adapter->channels[channel->logical_channel] != channel)
        || !lock_mounted(adapter)) {
        return false;
    }

    clear_ram_window_unlocked(channel);
    result = mw_epoch_store_commit_session(
        &adapter->store, channel->logical_channel, next_session_id);
    k_mutex_unlock(&adapter->mutex);
    return result == MW_EPOCH_STORE_OK;
}

bool mw_epoch_nvs_bind_ram_window(
    mw_epoch_nvs_channel_context_t *context,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling
)
{
    mw_epoch_nvs_adapter_t *adapter;
    mw_epoch_record_t current;
    bool valid;

    if ((context == NULL) || (context->adapter == NULL)) {
        return false;
    }
    adapter = context->adapter;
    if ((context->logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (&adapter->channels[context->logical_channel] != context)
        || !lock_mounted(adapter)) {
        return false;
    }

    clear_ram_window_unlocked(context);
    valid = mw_epoch_store_snapshot(
        &adapter->store, context->logical_channel, &current)
        && (durable_session_id != 0U)
        && (durable_session_id != UINT32_MAX)
        && (reserved_sequence_ceiling != 0U)
        && (reserved_sequence_ceiling != UINT32_MAX)
        && (current.session_id == durable_session_id)
        && (current.sequence_ceiling == reserved_sequence_ceiling);
    if (valid) {
        context->ram_session_id = durable_session_id;
        context->ram_sequence_ceiling = reserved_sequence_ceiling;
        context->ram_receive_high_water = 0U;
        context->ram_window_bound = true;
    }
    k_mutex_unlock(&adapter->mutex);
    return valid;
}

bool mw_epoch_nvs_commit_ram_high_water(
    void *context,
    uint32_t sequence
)
{
    mw_epoch_nvs_channel_context_t *channel =
        (mw_epoch_nvs_channel_context_t *)context;
    mw_epoch_nvs_adapter_t *adapter;
    mw_epoch_record_t current;
    bool valid;

    if ((channel == NULL) || (channel->adapter == NULL)) {
        return false;
    }
    adapter = channel->adapter;
    if ((channel->logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (&adapter->channels[channel->logical_channel] != channel)
        || !lock_mounted(adapter)) {
        return false;
    }

    valid = channel->ram_window_bound
        && mw_epoch_store_snapshot(
            &adapter->store, channel->logical_channel, &current)
        && (current.session_id == channel->ram_session_id)
        && (current.sequence_ceiling == channel->ram_sequence_ceiling)
        && (sequence != 0U)
        && (sequence != UINT32_MAX)
        && (sequence > channel->ram_receive_high_water)
        && (sequence <= channel->ram_sequence_ceiling);
    if (valid) {
        channel->ram_receive_high_water = sequence;
    } else {
        clear_ram_window_unlocked(channel);
    }
    k_mutex_unlock(&adapter->mutex);
    return valid;
}

void mw_epoch_nvs_clear_ram_window(
    mw_epoch_nvs_channel_context_t *context
)
{
    mw_epoch_nvs_adapter_t *adapter;

    if ((context == NULL) || (context->adapter == NULL)) {
        return;
    }
    adapter = context->adapter;
    if ((context->logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (&adapter->channels[context->logical_channel] != context)
        || !lock_mounted(adapter)) {
        return;
    }
    clear_ram_window_unlocked(context);
    k_mutex_unlock(&adapter->mutex);
}

void mw_epoch_nvs_invalidate_channel(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel
)
{
    if ((logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !lock_mounted(adapter)) {
        return;
    }
    mw_epoch_store_invalidate_channel(&adapter->store, logical_channel);
    clear_ram_window_unlocked(&adapter->channels[logical_channel]);
    k_mutex_unlock(&adapter->mutex);
}
