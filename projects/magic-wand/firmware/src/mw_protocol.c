#include "mw_protocol.h"

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
        return true;
    default:
        return false;
    }
}
static bool payload_length_is_valid(uint8_t command, uint16_t payload_length)
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
    guard->persistence_ready = persistence_ready;
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
    uint32_t age_ms;

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
        (frame->header.device_id != guard->expected_device_id) ||
        (frame->header.flags != 0U) ||
        (frame->header.session_id != guard->expected_session_id) ||
        !payload_length_is_valid(frame->header.command, frame->header.payload_length) ||
        (frame->header.sequence == 0U) ||
        (frame->header.sequence <= guard->receive_high_water) ||
        ((size_t)frame->header.payload_length > MW_MAX_PAYLOAD_BYTES)) {
        return false;
    }

    age_ms = now_ms - frame->header.issued_ms;
    if (age_ms > MW_COMMAND_FRESHNESS_MS) {
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

    /* Persist before exposing acceptance to an output state machine. */
    if (!commit_high_water(persistence_context, frame->header.sequence)) {
        (void)memset(plaintext_out, 0, MW_MAX_PAYLOAD_BYTES);
        return false;
    }

    guard->receive_high_water = frame->header.sequence;
    return true;
}
