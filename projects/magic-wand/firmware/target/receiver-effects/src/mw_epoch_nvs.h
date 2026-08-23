#ifndef MW_EPOCH_NVS_H
#define MW_EPOCH_NVS_H

#include "mw_epoch_store.h"

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/kernel.h>
#include <zephyr/kvss/nvs.h>

typedef struct mw_epoch_nvs_adapter mw_epoch_nvs_adapter_t;

typedef struct {
    mw_epoch_nvs_adapter_t *adapter;
    uint8_t logical_channel;
    uint32_t ram_session_id;
    uint32_t ram_sequence_ceiling;
    uint32_t ram_receive_high_water;
    bool ram_window_bound;
} mw_epoch_nvs_channel_context_t;

struct mw_epoch_nvs_adapter {
    struct nvs_fs fs;
    struct k_mutex mutex;
    mw_epoch_store_t store;
    mw_epoch_nvs_channel_context_t channels[MW_EPOCH_LOGICAL_CHANNEL_COUNT];
    bool mounted;
};

/*
 * Mounts only DT_NODELABEL(mw_epoch_partition). The implementation refuses an
 * overlap with storage_partition and requires CONFIG_NVS_DATA_CRC=y. No caller
 * may use the adapter after a non-zero result.
 */
int mw_epoch_nvs_mount(mw_epoch_nvs_adapter_t *adapter);

mw_epoch_store_result_t mw_epoch_nvs_load_channel(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel,
    uint32_t receiver_id,
    uint32_t wand_id,
    uint32_t configured_sequence_ceiling,
    mw_epoch_provisioning_policy_t provisioning_policy
);

mw_epoch_store_result_t mw_epoch_nvs_provision_channel(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel
);

bool mw_epoch_nvs_snapshot(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel,
    mw_epoch_record_t *record_out
);

mw_epoch_nvs_channel_context_t *mw_epoch_nvs_channel_context(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel
);

/*
 * Pass this to mw_receiver_*_complete_handshake. It returns true only after the
 * pure-C transaction has accepted nvs_write=32 or 0, fully read both slots,
 * verified exact candidate bytes, reselected the candidate and updated current.
 * An authenticated ACK is forbidden before this callback returns true.
 */
bool mw_epoch_nvs_commit_session_epoch(
    void *context,
    uint32_t next_session_id
);

/*
 * Call only after portable runtime durable-window bind succeeds and before ACK.
 * The resulting high-water callback is session-local RAM only; the committed
 * epoch makes same-session reset recovery fail closed.
 */
bool mw_epoch_nvs_bind_ram_window(
    mw_epoch_nvs_channel_context_t *context,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling
);

bool mw_epoch_nvs_commit_ram_high_water(
    void *context,
    uint32_t sequence
);

void mw_epoch_nvs_clear_ram_window(
    mw_epoch_nvs_channel_context_t *context
);

void mw_epoch_nvs_invalidate_channel(
    mw_epoch_nvs_adapter_t *adapter,
    uint8_t logical_channel
);

#endif
