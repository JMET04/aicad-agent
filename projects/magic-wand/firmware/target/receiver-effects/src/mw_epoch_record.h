#ifndef MW_EPOCH_RECORD_H
#define MW_EPOCH_RECORD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MW_EPOCH_RECORD_ENCODED_SIZE 32U
#define MW_EPOCH_RECORD_SCHEMA_V1 1U
#define MW_EPOCH_LOGICAL_CHANNEL_COUNT 8U
#define MW_EPOCH_SLOT_COUNT 2U

typedef struct {
    uint8_t logical_channel;
    uint8_t copy_index;
    uint32_t generation;
    uint32_t receiver_id;
    uint32_t wand_id;
    uint32_t session_id;
    uint32_t sequence_ceiling;
} mw_epoch_record_t;

typedef enum {
    MW_EPOCH_SLOT_PRESENT = 0,
    MW_EPOCH_SLOT_ENOENT = 1,
    MW_EPOCH_SLOT_IO_ERROR = 2
} mw_epoch_slot_state_t;

typedef struct {
    mw_epoch_slot_state_t state;
    const uint8_t *data;
    size_t length;
} mw_epoch_slot_view_t;

typedef enum {
    MW_EPOCH_REQUIRE_EXISTING = 0,
    MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING = 1
} mw_epoch_provisioning_policy_t;

typedef enum {
    MW_EPOCH_SELECT_OK = 0,
    MW_EPOCH_SELECT_PROVISIONING_REQUIRED,
    MW_EPOCH_SELECT_NOT_FOUND,
    MW_EPOCH_SELECT_IO_ERROR,
    MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT,
    MW_EPOCH_SELECT_INVALID_ARGUMENT
} mw_epoch_select_result_t;

/*
 * Canonical 32-byte big-endian encoding:
 *   [0..3]   magic "MWEP"
 *   [4]      schema (1)
 *   [5]      logical channel (0..7)
 *   [6]      copy index (0=A, 1=B)
 *   [7]      reserved, canonical zero
 *   [8..11]  generation
 *   [12..15] receiver identity
 *   [16..19] wand identity
 *   [20..23] durable session epoch
 *   [24..27] sequence ceiling
 *   [28..31] CRC-32/ISO-HDLC over bytes [0..27]
 *
 * A persisted factory baseline is explicit and canonical:
 * generation=1, session_id=0, sequence_ceiling=0. Active records use
 * non-zero counters and reserve UINT32_MAX as the no-wrap sentinel.
 */
bool mw_epoch_record_encode(
    const mw_epoch_record_t *record,
    uint8_t encoded[MW_EPOCH_RECORD_ENCODED_SIZE]
);

bool mw_epoch_record_decode(
    const uint8_t *encoded,
    size_t encoded_length,
    mw_epoch_record_t *record
);

/* This constructor must only be called by an explicit provisioning flow. */
bool mw_epoch_record_make_factory_baseline(
    uint8_t logical_channel,
    uint8_t copy_index,
    uint32_t receiver_id,
    uint32_t wand_id,
    mw_epoch_record_t *record
);

/* Prepares the inactive A/B slot and rejects generation/session wrap. */
bool mw_epoch_record_prepare_next(
    const mw_epoch_record_t *current,
    uint32_t next_session_id,
    uint32_t sequence_ceiling,
    mw_epoch_record_t *next
);

/*
 * Selects only canonical records matching the expected channel and identities.
 * Equal generations, skipped generations, non-increasing sessions, malformed
 * present slots and any I/O error fail closed. The output is zero on failure.
 * Two ENOENT slots never manufacture state: explicit provisioning policy only
 * changes NOT_FOUND into PROVISIONING_REQUIRED.
 */
mw_epoch_select_result_t mw_epoch_record_select(
    const mw_epoch_slot_view_t slots[MW_EPOCH_SLOT_COUNT],
    uint8_t expected_logical_channel,
    uint32_t expected_receiver_id,
    uint32_t expected_wand_id,
    mw_epoch_provisioning_policy_t provisioning_policy,
    mw_epoch_record_t *selected
);

#endif
