#include "mw_protocol.h"

#include "mw_gesture.h"
#include "mw_gesture_event_v2.h"

#include <string.h>

static void put_u16_be(uint8_t *output, uint16_t value)
{
    output[0] = (uint8_t)(value >> 8);
    output[1] = (uint8_t)value;
}

static void put_u32_be(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)(value >> 24);
    output[1] = (uint8_t)(value >> 16);
    output[2] = (uint8_t)(value >> 8);
    output[3] = (uint8_t)value;
}

static bool command_is_known(uint8_t command)
{
    switch ((mw_command_t)command) {
    case MW_CMD_DISARM:
    case MW_CMD_HEARTBEAT:
    case MW_CMD_ARM_LEASE:
    case MW_CMD_SET_AUX:
    case MW_CMD_PULSE_ISOLATED_OC:
    case MW_CMD_PULSE_LOW_SIDE:
    case MW_CMD_FEEDBACK:
    case MW_CMD_GESTURE_EVENT:
        return true;
    default:
        return false;
    }
}

static bool command_direction_is_valid(uint8_t command, uint8_t direction)
{
    if (direction == (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER) {
        return command != (uint8_t)MW_CMD_FEEDBACK;
    }
    if (direction == (uint8_t)MW_DIRECTION_RECEIVER_TO_WAND) {
        return command == (uint8_t)MW_CMD_FEEDBACK;
    }
    return false;
}

static bool payload_length_is_valid(
    uint8_t command,
    uint16_t payload_length,
    mw_gesture_payload_profile_t gesture_profile)
{
    switch ((mw_command_t)command) {
    case MW_CMD_DISARM:
    case MW_CMD_HEARTBEAT:
    case MW_CMD_ARM_LEASE:
        return (payload_length == 0U);
    case MW_CMD_SET_AUX:
        return (payload_length == 1U);
    case MW_CMD_PULSE_ISOLATED_OC:
    case MW_CMD_PULSE_LOW_SIDE:
        return (payload_length == 2U);
    case MW_CMD_FEEDBACK:
        return ((size_t)payload_length <= MW_MAX_PAYLOAD_BYTES);
    case MW_CMD_GESTURE_EVENT:
        if (gesture_profile == MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1) {
            return (size_t)payload_length ==
                MW_GESTURE_EVENT_PAYLOAD_BYTES;
        }
        if (gesture_profile ==
            MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2) {
            return (size_t)payload_length == MW_GESTURE_EVENT_V2_BYTES;
        }
        return false;
    default:
        return false;
    }
}


void mw_replay_guard_init(
    mw_replay_guard_t *guard,
    uint32_t expected_device_id,
    uint32_t expected_session_id,
    uint32_t persisted_receive_high_water,
    bool persistence_ready)
{
    if (guard == NULL) {
        return;
    }

    guard->expected_device_id = expected_device_id;
    guard->expected_session_id = expected_session_id;
    guard->receive_high_water = persisted_receive_high_water;
    guard->durable_session_id = UINT32_C(0);
    guard->reserved_sequence_ceiling = UINT32_C(0);
    guard->gesture_payload_profile =
        MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED;
    guard->persistence_ready = persistence_ready;
    guard->durable_session_window_bound = false;
}

bool mw_replay_guard_set_gesture_profile(
    mw_replay_guard_t *guard,
    mw_gesture_payload_profile_t profile)
{
    if (guard == NULL) {
        return false;
    }
    if (guard->durable_session_window_bound) {
        return profile == guard->gesture_payload_profile;
    }
    if ((profile != MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1) &&
        (profile != MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2)) {
        guard->gesture_payload_profile =
            MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED;
        return false;
    }
    guard->gesture_payload_profile = profile;
    return true;
}

bool mw_replay_guard_bind_durable_session_window(
    mw_replay_guard_t *guard,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling)
{
    if ((guard == NULL) || !guard->persistence_ready ||
        guard->durable_session_window_bound ||
        (guard->expected_device_id == UINT32_C(0)) ||
        (guard->expected_session_id == UINT32_C(0)) ||
        (guard->expected_session_id == UINT32_MAX) ||
        (durable_session_id != guard->expected_session_id) ||
        (guard->receive_high_water != UINT32_C(0)) ||
        (reserved_sequence_ceiling == UINT32_C(0)) ||
        (reserved_sequence_ceiling == UINT32_MAX) ||
        ((guard->gesture_payload_profile !=
          MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1) &&
         (guard->gesture_payload_profile !=
          MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2))) {
        return false;
    }

    guard->durable_session_id = durable_session_id;
    guard->reserved_sequence_ceiling = reserved_sequence_ceiling;
    guard->durable_session_window_bound = true;
    return true;
}

void mw_protocol_build_nonce(
    const mw_frame_header_t *header,
    uint8_t nonce_out[MW_NONCE_BYTES])
{
    if ((header == NULL) || (nonce_out == NULL)) {
        return;
    }

    nonce_out[0] = header->direction;
    put_u32_be(&nonce_out[1], header->device_id);
    put_u32_be(&nonce_out[5], header->session_id);
    put_u32_be(&nonce_out[9], header->sequence);
}

size_t mw_protocol_encode_aad(
    const mw_frame_header_t *header,
    uint8_t aad_out[MW_AAD_BYTES])
{
    if ((header == NULL) || (aad_out == NULL)) {
        return 0U;
    }

    aad_out[0] = header->version;
    aad_out[1] = header->direction;
    aad_out[2] = header->command;
    aad_out[3] = header->flags;
    put_u32_be(&aad_out[4], header->device_id);
    put_u32_be(&aad_out[8], header->session_id);
    put_u32_be(&aad_out[12], header->sequence);
    put_u32_be(&aad_out[16], header->issued_ms);
    put_u16_be(&aad_out[20], header->payload_length);
    return MW_AAD_BYTES;
}

bool mw_protocol_accept_and_decrypt(
    mw_replay_guard_t *guard,
    const mw_encrypted_frame_t *frame,
    mw_direction_t expected_direction,
    uint32_t now_ms,
    mw_ccm_decrypt_fn decrypt,
    void *decrypt_context,
    mw_commit_high_water_fn commit_high_water,
    void *persistence_context,
    uint8_t plaintext_out[MW_MAX_PAYLOAD_BYTES])
{
    uint8_t nonce[MW_NONCE_BYTES] = {0};
    uint8_t aad[MW_AAD_BYTES] = {0};
    int32_t age_ms;

    if (plaintext_out != NULL) {
        (void)memset(plaintext_out, 0, MW_MAX_PAYLOAD_BYTES);
    }

    if ((guard == NULL) || (frame == NULL) || (plaintext_out == NULL) ||
        (decrypt == NULL) || (commit_high_water == NULL) ||
        !guard->persistence_ready) {
        return false;
    }

    if ((frame->header.version != MW_PROTOCOL_VERSION) ||
        (frame->header.direction != (uint8_t)expected_direction) ||
        !command_is_known(frame->header.command) ||
        !command_direction_is_valid(frame->header.command,
                                    frame->header.direction) ||
        (frame->header.device_id != guard->expected_device_id) ||
        (frame->header.flags != 0U) ||
        (frame->header.session_id != guard->expected_session_id) ||
        !payload_length_is_valid(
            frame->header.command,
            frame->header.payload_length,
            guard->gesture_payload_profile) ||
        (frame->header.sequence == 0U) ||
        (frame->header.sequence == UINT32_MAX) ||
        (frame->header.sequence <= guard->receive_high_water) ||
        (guard->durable_session_window_bound &&
         ((guard->durable_session_id == UINT32_C(0)) ||
          (guard->durable_session_id == UINT32_MAX) ||
          (guard->durable_session_id != guard->expected_session_id) ||
          (frame->header.session_id != guard->durable_session_id) ||
          (guard->reserved_sequence_ceiling == UINT32_C(0)) ||
          (guard->reserved_sequence_ceiling == UINT32_MAX) ||
          (frame->header.sequence >
           guard->reserved_sequence_ceiling))) ||
        ((size_t)frame->header.payload_length > MW_MAX_PAYLOAD_BYTES)) {
        return false;
    }

    age_ms = (int32_t)(now_ms - frame->header.issued_ms);
    if ((age_ms < 0) || ((uint32_t)age_ms > MW_COMMAND_FRESHNESS_MS)) {
        return false;
    }

    mw_protocol_build_nonce(&frame->header, nonce);
    if (mw_protocol_encode_aad(&frame->header, aad) != MW_AAD_BYTES) {
        return false;
    }

    if (!decrypt(
            decrypt_context,
            nonce,
            aad,
            MW_AAD_BYTES,
            frame->ciphertext,
            (size_t)frame->header.payload_length,
            frame->tag,
            plaintext_out)) {
        (void)memset(plaintext_out, 0, MW_MAX_PAYLOAD_BYTES);
        return false;
    }

    /* Commit replay state before exposing plaintext to an output policy. */
    if (!commit_high_water(persistence_context, frame->header.sequence)) {
        (void)memset(plaintext_out, 0, MW_MAX_PAYLOAD_BYTES);
        guard->persistence_ready = false;
        return false;
    }

    guard->receive_high_water = frame->header.sequence;
    return true;
}
