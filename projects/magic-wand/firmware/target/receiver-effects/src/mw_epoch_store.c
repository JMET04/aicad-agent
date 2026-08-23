#include "mw_epoch_store.h"

#include <string.h>

static void clear_channel(mw_epoch_store_channel_t *channel)
{
    const mw_epoch_store_channel_t zero = {0};
    *channel = zero;
}

static bool active_counter(uint32_t value)
{
    return (value != 0U) && (value != UINT32_MAX);
}

static bool identities_valid(uint32_t receiver_id, uint32_t wand_id)
{
    return (receiver_id != 0U)
        && (wand_id != 0U)
        && (receiver_id != wand_id);
}

static bool records_equal(
    const mw_epoch_record_t *left,
    const mw_epoch_record_t *right
)
{
    return (left->logical_channel == right->logical_channel)
        && (left->copy_index == right->copy_index)
        && (left->generation == right->generation)
        && (left->receiver_id == right->receiver_id)
        && (left->wand_id == right->wand_id)
        && (left->session_id == right->session_id)
        && (left->sequence_ceiling == right->sequence_ceiling);
}

static mw_epoch_store_result_t map_select_result(
    mw_epoch_select_result_t result
)
{
    switch (result) {
    case MW_EPOCH_SELECT_OK:
        return MW_EPOCH_STORE_OK;
    case MW_EPOCH_SELECT_PROVISIONING_REQUIRED:
        return MW_EPOCH_STORE_PROVISIONING_REQUIRED;
    case MW_EPOCH_SELECT_NOT_FOUND:
        return MW_EPOCH_STORE_NOT_FOUND;
    case MW_EPOCH_SELECT_IO_ERROR:
        return MW_EPOCH_STORE_IO_ERROR;
    case MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT:
        return MW_EPOCH_STORE_CORRUPT_OR_CONFLICT;
    case MW_EPOCH_SELECT_INVALID_ARGUMENT:
    default:
        return MW_EPOCH_STORE_BACKEND_CONTRACT_ERROR;
    }
}

static mw_epoch_store_result_t read_views(
    mw_epoch_store_t *store,
    uint8_t logical_channel,
    uint8_t buffers[MW_EPOCH_SLOT_COUNT][MW_EPOCH_RECORD_ENCODED_SIZE],
    mw_epoch_slot_view_t views[MW_EPOCH_SLOT_COUNT]
)
{
    mw_epoch_slot_state_t states[MW_EPOCH_SLOT_COUNT];
    size_t lengths[MW_EPOCH_SLOT_COUNT] = {0U, 0U};
    unsigned int copy_index;

    for (copy_index = 0U; copy_index < MW_EPOCH_SLOT_COUNT; ++copy_index) {
        (void)memset(buffers[copy_index], 0, MW_EPOCH_RECORD_ENCODED_SIZE);
        states[copy_index] = store->backend.read_slot(
            store->backend.context,
            logical_channel,
            (uint8_t)copy_index,
            buffers[copy_index],
            &lengths[copy_index]);
    }

    /* A known backend I/O error has global precedence over format diagnosis. */
    for (copy_index = 0U; copy_index < MW_EPOCH_SLOT_COUNT; ++copy_index) {
        if (states[copy_index] == MW_EPOCH_SLOT_IO_ERROR) {
            return MW_EPOCH_STORE_IO_ERROR;
        }
    }

    for (copy_index = 0U; copy_index < MW_EPOCH_SLOT_COUNT; ++copy_index) {
        views[copy_index].state = states[copy_index];
        if (states[copy_index] == MW_EPOCH_SLOT_PRESENT) {
            views[copy_index].data = buffers[copy_index];
            views[copy_index].length = lengths[copy_index];
        } else if (states[copy_index] == MW_EPOCH_SLOT_ENOENT) {
            if (lengths[copy_index] != 0U) {
                return MW_EPOCH_STORE_BACKEND_CONTRACT_ERROR;
            }
            views[copy_index].data = NULL;
            views[copy_index].length = 0U;
        } else {
            return MW_EPOCH_STORE_BACKEND_CONTRACT_ERROR;
        }
    }
    return MW_EPOCH_STORE_OK;
}

static mw_epoch_store_result_t read_and_select(
    mw_epoch_store_t *store,
    uint8_t logical_channel,
    uint32_t receiver_id,
    uint32_t wand_id,
    mw_epoch_provisioning_policy_t provisioning_policy,
    uint8_t buffers[MW_EPOCH_SLOT_COUNT][MW_EPOCH_RECORD_ENCODED_SIZE],
    mw_epoch_slot_view_t views[MW_EPOCH_SLOT_COUNT],
    mw_epoch_record_t *selected
)
{
    mw_epoch_store_result_t read_result = read_views(
        store, logical_channel, buffers, views);
    if (read_result != MW_EPOCH_STORE_OK) {
        return read_result;
    }
    return map_select_result(mw_epoch_record_select(
        views,
        logical_channel,
        receiver_id,
        wand_id,
        provisioning_policy,
        selected));
}

static mw_epoch_store_result_t write_candidate(
    mw_epoch_store_t *store,
    mw_epoch_store_channel_t *channel,
    const mw_epoch_record_t *candidate
)
{
    uint8_t encoded[MW_EPOCH_RECORD_ENCODED_SIZE];
    uint8_t buffers[MW_EPOCH_SLOT_COUNT][MW_EPOCH_RECORD_ENCODED_SIZE];
    mw_epoch_slot_view_t views[MW_EPOCH_SLOT_COUNT];
    mw_epoch_record_t selected;
    mw_epoch_store_result_t result;
    int32_t write_result;
    size_t byte_index;

    if (!mw_epoch_record_encode(candidate, encoded)) {
        return MW_EPOCH_STORE_INVALID_ARGUMENT;
    }
    write_result = store->backend.write_slot(
        store->backend.context,
        candidate->logical_channel,
        candidate->copy_index,
        encoded,
        sizeof(encoded));
    if (write_result < 0) {
        return MW_EPOCH_STORE_IO_ERROR;
    }
    if ((write_result != 0)
        && (write_result != (int32_t)MW_EPOCH_RECORD_ENCODED_SIZE)) {
        return MW_EPOCH_STORE_BACKEND_CONTRACT_ERROR;
    }

    /* Both successful write forms (32 and unchanged=0) require full readback. */
    result = read_and_select(
        store,
        candidate->logical_channel,
        candidate->receiver_id,
        candidate->wand_id,
        MW_EPOCH_REQUIRE_EXISTING,
        buffers,
        views,
        &selected);
    if (result != MW_EPOCH_STORE_OK) {
        return result;
    }
    if ((views[candidate->copy_index].state != MW_EPOCH_SLOT_PRESENT)
        || (views[candidate->copy_index].length != sizeof(encoded))) {
        return MW_EPOCH_STORE_CORRUPT_OR_CONFLICT;
    }
    for (byte_index = 0U; byte_index < sizeof(encoded); ++byte_index) {
        if (views[candidate->copy_index].data[byte_index]
            != encoded[byte_index]) {
            return MW_EPOCH_STORE_CORRUPT_OR_CONFLICT;
        }
    }
    if (!records_equal(&selected, candidate)) {
        return MW_EPOCH_STORE_CORRUPT_OR_CONFLICT;
    }

    channel->current = selected;
    channel->ready = true;
    channel->provisioning_pending = false;
    return MW_EPOCH_STORE_OK;
}

bool mw_epoch_store_init(
    mw_epoch_store_t *store,
    const mw_epoch_store_backend_t *backend
)
{
    mw_epoch_store_backend_t configured;

    if (store == NULL) {
        return false;
    }
    if (backend == NULL) {
        (void)memset(store, 0, sizeof(*store));
        return false;
    }
    configured = *backend;
    (void)memset(store, 0, sizeof(*store));
    if ((configured.read_slot == NULL)
        || (configured.write_slot == NULL)) {
        return false;
    }
    store->backend = configured;
    store->initialized = true;
    return true;
}

mw_epoch_store_result_t mw_epoch_store_load_channel(
    mw_epoch_store_t *store,
    uint8_t logical_channel,
    uint32_t receiver_id,
    uint32_t wand_id,
    uint32_t configured_sequence_ceiling,
    mw_epoch_provisioning_policy_t provisioning_policy
)
{
    mw_epoch_store_channel_t configured = {0};
    uint8_t buffers[MW_EPOCH_SLOT_COUNT][MW_EPOCH_RECORD_ENCODED_SIZE];
    mw_epoch_slot_view_t views[MW_EPOCH_SLOT_COUNT];
    mw_epoch_record_t selected;
    mw_epoch_store_result_t result;

    if ((store != NULL)
        && store->initialized
        && (logical_channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT)) {
        clear_channel(&store->channels[logical_channel]);
    }
    if ((store == NULL)
        || !store->initialized
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !identities_valid(receiver_id, wand_id)
        || !active_counter(configured_sequence_ceiling)
        || ((provisioning_policy != MW_EPOCH_REQUIRE_EXISTING)
            && (provisioning_policy != MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING))) {
        return MW_EPOCH_STORE_INVALID_ARGUMENT;
    }

    configured.receiver_id = receiver_id;
    configured.wand_id = wand_id;
    configured.configured_sequence_ceiling = configured_sequence_ceiling;
    configured.identity_configured = true;
    result = read_and_select(
        store,
        logical_channel,
        receiver_id,
        wand_id,
        provisioning_policy,
        buffers,
        views,
        &selected);
    if (result == MW_EPOCH_STORE_OK) {
        configured.current = selected;
        configured.ready = true;
        store->channels[logical_channel] = configured;
    } else if (result == MW_EPOCH_STORE_PROVISIONING_REQUIRED) {
        configured.provisioning_pending = true;
        store->channels[logical_channel] = configured;
    } else {
        /* Channel was already cleared before any backend read. */
    }
    return result;
}

mw_epoch_store_result_t mw_epoch_store_provision_channel(
    mw_epoch_store_t *store,
    uint8_t logical_channel
)
{
    mw_epoch_store_channel_t *channel;
    mw_epoch_record_t baseline;
    mw_epoch_store_result_t result;

    if ((store == NULL)
        || !store->initialized
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)) {
        return MW_EPOCH_STORE_INVALID_ARGUMENT;
    }
    channel = &store->channels[logical_channel];
    if (!channel->identity_configured
        || !channel->provisioning_pending
        || channel->ready) {
        return MW_EPOCH_STORE_NOT_READY;
    }
    if (!mw_epoch_record_make_factory_baseline(
            logical_channel,
            0U,
            channel->receiver_id,
            channel->wand_id,
            &baseline)) {
        clear_channel(channel);
        return MW_EPOCH_STORE_INVALID_ARGUMENT;
    }

    result = write_candidate(store, channel, &baseline);
    if (result != MW_EPOCH_STORE_OK) {
        clear_channel(channel);
    }
    return result;
}

mw_epoch_store_result_t mw_epoch_store_commit_session(
    mw_epoch_store_t *store,
    uint8_t logical_channel,
    uint32_t next_session_id
)
{
    mw_epoch_store_channel_t *channel;
    mw_epoch_record_t candidate;
    mw_epoch_store_result_t result;

    if ((store == NULL)
        || !store->initialized
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)) {
        return MW_EPOCH_STORE_INVALID_ARGUMENT;
    }
    channel = &store->channels[logical_channel];
    if (!channel->ready || !channel->identity_configured) {
        return MW_EPOCH_STORE_NOT_READY;
    }
    if (!mw_epoch_record_prepare_next(
            &channel->current,
            next_session_id,
            channel->configured_sequence_ceiling,
            &candidate)) {
        return MW_EPOCH_STORE_INVALID_ARGUMENT;
    }

    result = write_candidate(store, channel, &candidate);
    if (result != MW_EPOCH_STORE_OK) {
        clear_channel(channel);
    }
    return result;
}

bool mw_epoch_store_snapshot(
    const mw_epoch_store_t *store,
    uint8_t logical_channel,
    mw_epoch_record_t *record_out
)
{
    if (record_out != NULL) {
        const mw_epoch_record_t zero = {0};
        *record_out = zero;
    }
    if ((store == NULL)
        || !store->initialized
        || (record_out == NULL)
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !store->channels[logical_channel].ready) {
        return false;
    }
    *record_out = store->channels[logical_channel].current;
    return true;
}

bool mw_epoch_store_channel_ready(
    const mw_epoch_store_t *store,
    uint8_t logical_channel
)
{
    return (store != NULL)
        && store->initialized
        && (logical_channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        && store->channels[logical_channel].ready;
}

void mw_epoch_store_invalidate_channel(
    mw_epoch_store_t *store,
    uint8_t logical_channel
)
{
    if ((store != NULL)
        && store->initialized
        && (logical_channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT)) {
        clear_channel(&store->channels[logical_channel]);
    }
}

bool mw_epoch_store_channel_context_init(
    mw_epoch_store_channel_context_t *context,
    mw_epoch_store_t *store,
    uint8_t logical_channel
)
{
    if (context != NULL) {
        context->store = NULL;
        context->logical_channel = 0U;
    }
    if ((context == NULL)
        || (store == NULL)
        || !store->initialized
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)) {
        return false;
    }
    context->store = store;
    context->logical_channel = logical_channel;
    return true;
}

bool mw_epoch_store_commit_session_epoch(
    void *context,
    uint32_t next_session_id
)
{
    mw_epoch_store_channel_context_t *channel_context =
        (mw_epoch_store_channel_context_t *)context;
    if (channel_context == NULL) {
        return false;
    }
    return mw_epoch_store_commit_session(
        channel_context->store,
        channel_context->logical_channel,
        next_session_id) == MW_EPOCH_STORE_OK;
}
