#ifndef MW_TARGET_WIRE_H
#define MW_TARGET_WIRE_H

#include "mw_gesture_event_v2.h"
#include "mw_protocol.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_TARGET_HANDSHAKE_SCHEMA UINT8_C(1)
#define MW_TARGET_HANDSHAKE_OPEN UINT8_C(1)
#define MW_TARGET_HANDSHAKE_ACK UINT8_C(2)
#define MW_TARGET_HANDSHAKE_PREFIX_BYTES ((size_t)20)
#define MW_TARGET_HANDSHAKE_TAG_BYTES ((size_t)16)
#define MW_TARGET_HANDSHAKE_BYTES \
    (MW_TARGET_HANDSHAKE_PREFIX_BYTES + MW_TARGET_HANDSHAKE_TAG_BYTES)
#define MW_TARGET_ENCRYPTED_FRAME_MIN_BYTES \
    (MW_AAD_BYTES + MW_TAG_BYTES)
#define MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES \
    (MW_AAD_BYTES + MW_MAX_PAYLOAD_BYTES + MW_TAG_BYTES)
#define MW_TARGET_ATT_MTU_MIN_BYTES \
    (MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES + (size_t)3)
#define MW_TARGET_ENCRYPTED_GESTURE_BYTES \
    (MW_AAD_BYTES + MW_GESTURE_EVENT_V2_BYTES + MW_TAG_BYTES)

typedef struct {
    uint8_t message_type;
    uint8_t gesture_profile;
    uint8_t logical_channel;
    uint32_t wand_device_id;
    uint32_t receiver_device_id;
    uint32_t session_id;
    uint32_t clock_ms;
} mw_target_handshake_t;

typedef struct {
    uint32_t wand_device_id;
    uint32_t receiver_device_id;
    uint32_t session_id;
    uint32_t persisted_session_id;
    uint32_t sequence_high_water;
    uint8_t logical_channel;
    mw_gesture_payload_profile_t gesture_profile;
    bool active;
} mw_target_session_gate_t;

void mw_target_session_gate_init(
    mw_target_session_gate_t *gate,
    uint32_t persisted_session_id);

bool mw_target_session_gate_activate(
    mw_target_session_gate_t *gate,
    uint32_t wand_device_id,
    uint32_t receiver_device_id,
    uint32_t session_id,
    uint8_t logical_channel,
    mw_gesture_payload_profile_t gesture_profile,
    bool secure_link_level4,
    bool secure_connections,
    bool oob_authenticated,
    bool application_handshake_authenticated,
    bool direction_key_ready);

void mw_target_session_gate_close(mw_target_session_gate_t *gate);

bool mw_target_session_identity(
    const mw_target_session_gate_t *gate,
    uint32_t *wand_device_id,
    uint32_t *session_id,
    uint8_t *logical_channel);

/*
 * Reserve a nonce/sequence before encryption. Success advances the in-memory
 * high-water mark and must never be rolled back, even if the subsequent GATT
 * write fails. This prevents a changed plaintext from reusing a CCM nonce.
 * The target adapter may use this low-level function for authenticated control
 * frames. GESTURE_EVENT callers must use the V2 wrapper below so plaintext
 * binding and ARM_ACTIVE are checked before the sequence is consumed.
 */
bool mw_target_session_reserve_tx(
    mw_target_session_gate_t *gate,
    const mw_frame_header_t *header);

bool mw_target_session_reserve_v2_tx(
    mw_target_session_gate_t *gate,
    const mw_frame_header_t *header,
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES]);

/* Validate decrypted receiver binding without changing portable replay state. */
bool mw_target_session_validate_v2_rx(
    const mw_target_session_gate_t *gate,
    const mw_frame_header_t *header,
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES]);

bool mw_target_handshake_encode_prefix(
    const mw_target_handshake_t *handshake,
    uint8_t prefix_out[MW_TARGET_HANDSHAKE_PREFIX_BYTES]);

bool mw_target_handshake_decode_prefix(
    const uint8_t prefix[MW_TARGET_HANDSHAKE_PREFIX_BYTES],
    mw_target_handshake_t *handshake_out);

bool mw_target_frame_serialize(
    const mw_encrypted_frame_t *frame,
    uint8_t wire_out[MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES],
    size_t *wire_length_out);

bool mw_target_frame_parse(
    const uint8_t *wire,
    size_t wire_length,
    mw_encrypted_frame_t *frame_out);

/* Exact-52-byte V2 GESTURE_EVENT compatibility wrappers. */
bool mw_target_encrypted_frame_serialize(
    const mw_encrypted_frame_t *frame,
    uint8_t wire_out[MW_TARGET_ENCRYPTED_GESTURE_BYTES]);

bool mw_target_encrypted_frame_parse(
    const uint8_t *wire,
    size_t wire_length,
    mw_encrypted_frame_t *frame_out);

#ifdef __cplusplus
}
#endif

#endif
