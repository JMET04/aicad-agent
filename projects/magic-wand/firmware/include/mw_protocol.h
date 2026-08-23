#ifndef MW_PROTOCOL_H
#define MW_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_PROTOCOL_VERSION UINT8_C(1)
#define MW_NONCE_BYTES ((size_t)13)
#define MW_AAD_BYTES ((size_t)22)
#define MW_TAG_BYTES ((size_t)16)
#define MW_MAX_PAYLOAD_BYTES ((size_t)32)
#define MW_COMMAND_FRESHNESS_MS UINT32_C(150)

typedef enum {
    MW_DIRECTION_WAND_TO_RECEIVER = 1,
    MW_DIRECTION_RECEIVER_TO_WAND = 2
} mw_direction_t;

typedef enum {
    MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED = 0,
    MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1 = 1,
    MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2 = 2
} mw_gesture_payload_profile_t;

typedef enum {
    MW_CMD_DISARM = 1,
    MW_CMD_HEARTBEAT = 2,
    MW_CMD_ARM_LEASE = 3,
    MW_CMD_SET_AUX = 16,
    MW_CMD_PULSE_ISOLATED_OC = 17,
    MW_CMD_PULSE_LOW_SIDE = 18,
    MW_CMD_FEEDBACK = 32,
    MW_CMD_GESTURE_EVENT = 33
} mw_command_t;

typedef struct {
    uint8_t version;
    uint8_t direction;
    uint8_t command;
    uint8_t flags;
    uint32_t device_id;
    uint32_t session_id;
    uint32_t sequence;
    uint32_t issued_ms;
    uint16_t payload_length;
} mw_frame_header_t;

typedef struct {
    mw_frame_header_t header;
    uint8_t ciphertext[MW_MAX_PAYLOAD_BYTES];
    uint8_t tag[MW_TAG_BYTES];
} mw_encrypted_frame_t;

typedef struct {
    uint32_t expected_device_id;
    uint32_t expected_session_id;
    uint32_t receive_high_water;
    uint32_t durable_session_id;
    uint32_t reserved_sequence_ceiling;
    mw_gesture_payload_profile_t gesture_payload_profile;
    bool persistence_ready;
    bool durable_session_window_bound;
} mw_replay_guard_t;

/*
 * The platform callback must perform authenticated AES-128-CCM decryption with
 * the 16-byte tag. It returns true only after constant-time tag verification.
 * The skeleton deliberately provides no cipher fallback.
 */
typedef bool (*mw_ccm_decrypt_fn)(
    void *context,
    const uint8_t nonce[MW_NONCE_BYTES],
    const uint8_t *aad,
    size_t aad_length,
    const uint8_t *ciphertext,
    size_t ciphertext_length,
    const uint8_t tag[MW_TAG_BYTES],
    uint8_t *plaintext_out);

/*
 * Commit a strictly greater receive high-water mark before plaintext is
 * exposed. In the default, unbound mode this callback must atomically persist
 * every accepted sequence. Only after a durable session window is explicitly
 * bound may the callback atomically update session-local RAM instead: reset
 * recovery is then provided by the already-persisted session epoch, and the
 * same session must never be activated again after reset.
 */
typedef bool (*mw_commit_high_water_fn)(
    void *context,
    uint32_t sequence);

void mw_replay_guard_init(
    mw_replay_guard_t *guard,
    uint32_t expected_device_id,
    uint32_t expected_session_id,
    uint32_t persisted_receive_high_water,
    bool persistence_ready);

/*
 * Select the exact authenticated GESTURE_EVENT payload profile for this
 * session. Init defaults to UNSUPPORTED; both legacy V1 and multichannel V2
 * must be explicitly installed. Unsupported values fail closed.
 */
bool mw_replay_guard_set_gesture_profile(
    mw_replay_guard_t *guard,
    mw_gesture_payload_profile_t profile);

/*
 * Opt into one durable session-epoch commit plus an in-session RAM replay
 * high-water mark. Binding is one-shot, requires a fresh guard with high-water
 * zero and an explicitly selected gesture profile, and reserves only sequence
 * values 1..reserved_sequence_ceiling. Init leaves this mode disabled so old
 * callers retain exact per-frame persistence semantics.
 */
bool mw_replay_guard_bind_durable_session_window(
    mw_replay_guard_t *guard,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling);

void mw_protocol_build_nonce(
    const mw_frame_header_t *header,
    uint8_t nonce_out[MW_NONCE_BYTES]);

size_t mw_protocol_encode_aad(
    const mw_frame_header_t *header,
    uint8_t aad_out[MW_AAD_BYTES]);

bool mw_protocol_accept_and_decrypt(
    mw_replay_guard_t *guard,
    const mw_encrypted_frame_t *frame,
    mw_direction_t expected_direction,
    uint32_t now_ms,
    mw_ccm_decrypt_fn decrypt,
    void *decrypt_context,
    mw_commit_high_water_fn commit_high_water,
    void *persistence_context,
    uint8_t plaintext_out[MW_MAX_PAYLOAD_BYTES]);

#ifdef __cplusplus
}
#endif

#endif
