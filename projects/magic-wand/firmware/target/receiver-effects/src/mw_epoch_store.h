#ifndef MW_EPOCH_STORE_H
#define MW_EPOCH_STORE_H

#include "mw_epoch_record.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef mw_epoch_slot_state_t (*mw_epoch_backend_read_slot_fn)(
    void *context,
    uint8_t logical_channel,
    uint8_t copy_index,
    uint8_t data_out[MW_EPOCH_RECORD_ENCODED_SIZE],
    size_t *stored_length_out
);

/*
 * Mirrors nvs_write semantics without depending on ssize_t or Zephyr:
 * encoded length means written, zero means identical data already existed,
 * a negative value means I/O failure, and any other positive value is a
 * forbidden short write.
 */
typedef int32_t (*mw_epoch_backend_write_slot_fn)(
    void *context,
    uint8_t logical_channel,
    uint8_t copy_index,
    const uint8_t *data,
    size_t data_length
);

typedef struct {
    mw_epoch_backend_read_slot_fn read_slot;
    mw_epoch_backend_write_slot_fn write_slot;
    void *context;
} mw_epoch_store_backend_t;

typedef enum {
    MW_EPOCH_STORE_OK = 0,
    MW_EPOCH_STORE_PROVISIONING_REQUIRED,
    MW_EPOCH_STORE_NOT_FOUND,
    MW_EPOCH_STORE_CORRUPT_OR_CONFLICT,
    MW_EPOCH_STORE_IO_ERROR,
    MW_EPOCH_STORE_BACKEND_CONTRACT_ERROR,
    MW_EPOCH_STORE_INVALID_ARGUMENT,
    MW_EPOCH_STORE_NOT_READY
} mw_epoch_store_result_t;

typedef struct {
    mw_epoch_record_t current;
    uint32_t receiver_id;
    uint32_t wand_id;
    uint32_t configured_sequence_ceiling;
    bool identity_configured;
    bool ready;
    bool provisioning_pending;
} mw_epoch_store_channel_t;

typedef struct {
    mw_epoch_store_backend_t backend;
    mw_epoch_store_channel_t channels[MW_EPOCH_LOGICAL_CHANNEL_COUNT];
    bool initialized;
} mw_epoch_store_t;

typedef struct {
    mw_epoch_store_t *store;
    uint8_t logical_channel;
} mw_epoch_store_channel_context_t;

bool mw_epoch_store_init(
    mw_epoch_store_t *store,
    const mw_epoch_store_backend_t *backend
);

/*
 * Loads and selects A/B state. Double ENOENT returns NOT_FOUND unless the
 * caller explicitly supplies ALLOW_EXPLICIT_PROVISIONING, in which case it
 * returns PROVISIONING_REQUIRED without writing anything.
 */
mw_epoch_store_result_t mw_epoch_store_load_channel(
    mw_epoch_store_t *store,
    uint8_t logical_channel,
    uint32_t receiver_id,
    uint32_t wand_id,
    uint32_t configured_sequence_ceiling,
    mw_epoch_provisioning_policy_t provisioning_policy
);

/* Writes the canonical factory baseline only after the explicit load result. */
mw_epoch_store_result_t mw_epoch_store_provision_channel(
    mw_epoch_store_t *store,
    uint8_t logical_channel
);

/*
 * Transaction: prepare inactive slot -> encode -> write -> full read of both
 * slots -> exact candidate readback -> canonical reselect -> current update.
 * Current is never updated before every step succeeds. Any ambiguous storage
 * failure invalidates only this logical channel and requires a fresh load.
 */
mw_epoch_store_result_t mw_epoch_store_commit_session(
    mw_epoch_store_t *store,
    uint8_t logical_channel,
    uint32_t next_session_id
);

bool mw_epoch_store_snapshot(
    const mw_epoch_store_t *store,
    uint8_t logical_channel,
    mw_epoch_record_t *record_out
);

bool mw_epoch_store_channel_ready(
    const mw_epoch_store_t *store,
    uint8_t logical_channel
);

void mw_epoch_store_invalidate_channel(
    mw_epoch_store_t *store,
    uint8_t logical_channel
);

bool mw_epoch_store_channel_context_init(
    mw_epoch_store_channel_context_t *context,
    mw_epoch_store_t *store,
    uint8_t logical_channel
);

/* Portable runtime callback: ACK is forbidden unless this returns true. */
bool mw_epoch_store_commit_session_epoch(
    void *context,
    uint32_t next_session_id
);

#endif
