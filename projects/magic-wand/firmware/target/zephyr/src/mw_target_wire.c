#include "mw_target_wire.h"

#include <string.h>

static void put_u32_be(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)(value >> 24U);
    output[1] = (uint8_t)(value >> 16U);
    output[2] = (uint8_t)(value >> 8U);
    output[3] = (uint8_t)value;
}

static uint16_t get_u16_be(const uint8_t *input)
{
    return (uint16_t)(((uint16_t)input[0] << 8U) | (uint16_t)input[1]);
}

static uint32_t get_u32_be(const uint8_t *input)
{
    return ((uint32_t)input[0] << 24U) |
        ((uint32_t)input[1] << 16U) |
        ((uint32_t)input[2] << 8U) |
        (uint32_t)input[3];
}

static bool valid_profile_and_channel(
    mw_gesture_payload_profile_t profile,
    uint8_t logical_channel)
{
    return (profile == MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2) &&
        (logical_channel < MW_LOGICAL_CHANNEL_COUNT);
}

static bool valid_wire_header(const mw_frame_header_t *header)
{
    return (header != NULL) &&
        (header->version == MW_PROTOCOL_VERSION) &&
        ((header->direction == (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER) ||
         (header->direction == (uint8_t)MW_DIRECTION_RECEIVER_TO_WAND)) &&
        (header->flags == UINT8_C(0)) &&
        (header->device_id != UINT32_C(0)) &&
        (header->session_id != UINT32_C(0)) &&
        (header->sequence != UINT32_C(0)) &&
        (header->sequence != UINT32_MAX) &&
        ((size_t)header->payload_length <= MW_MAX_PAYLOAD_BYTES);
}

static size_t frame_wire_length(uint16_t payload_length)
{
    return MW_AAD_BYTES + (size_t)payload_length + MW_TAG_BYTES;
}

static bool valid_wand_tx_command_and_length(
    const mw_frame_header_t *header)
{
    switch ((mw_command_t)header->command) {
    case MW_CMD_DISARM:
    case MW_CMD_HEARTBEAT:
    case MW_CMD_ARM_LEASE:
        return header->payload_length == UINT16_C(0);
    case MW_CMD_GESTURE_EVENT:
        return header->payload_length ==
            (uint16_t)MW_GESTURE_EVENT_V2_BYTES;
    case MW_CMD_SET_AUX:
    case MW_CMD_PULSE_ISOLATED_OC:
    case MW_CMD_PULSE_LOW_SIDE:
    case MW_CMD_FEEDBACK:
    default:
        return false;
    }
}

void mw_target_session_gate_init(
    mw_target_session_gate_t *gate,
    uint32_t persisted_session_id)
{
    if (gate == NULL) {
        return;
    }
    (void)memset(gate, 0, sizeof(*gate));
    gate->persisted_session_id = persisted_session_id;
    gate->gesture_profile = MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED;
}

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
    bool direction_key_ready)
{
    if ((gate == NULL) || gate->active ||
        (wand_device_id == UINT32_C(0)) ||
        (receiver_device_id == UINT32_C(0)) ||
        (wand_device_id == receiver_device_id) ||
        (session_id == UINT32_C(0)) ||
        (session_id <= gate->persisted_session_id) ||
        !valid_profile_and_channel(gesture_profile, logical_channel) ||
        !secure_link_level4 || !secure_connections || !oob_authenticated ||
        !application_handshake_authenticated || !direction_key_ready) {
        return false;
    }

    gate->wand_device_id = wand_device_id;
    gate->receiver_device_id = receiver_device_id;
    gate->session_id = session_id;
    gate->persisted_session_id = session_id;
    gate->sequence_high_water = UINT32_C(0);
    gate->logical_channel = logical_channel;
    gate->gesture_profile = gesture_profile;
    gate->active = true;
    return true;
}

void mw_target_session_gate_close(mw_target_session_gate_t *gate)
{
    uint32_t persisted_session_id;

    if (gate == NULL) {
        return;
    }
    persisted_session_id = gate->persisted_session_id;
    (void)memset(gate, 0, sizeof(*gate));
    gate->persisted_session_id = persisted_session_id;
    gate->gesture_profile = MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED;
}

bool mw_target_session_identity(
    const mw_target_session_gate_t *gate,
    uint32_t *wand_device_id,
    uint32_t *session_id,
    uint8_t *logical_channel)
{
    if ((gate == NULL) || !gate->active ||
        (gate->gesture_profile !=
         MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2) ||
        (wand_device_id == NULL) || (session_id == NULL) ||
        (logical_channel == NULL)) {
        return false;
    }
    *wand_device_id = gate->wand_device_id;
    *session_id = gate->session_id;
    *logical_channel = gate->logical_channel;
    return true;
}

bool mw_target_session_reserve_tx(
    mw_target_session_gate_t *gate,
    const mw_frame_header_t *header)
{
    if ((gate == NULL) || !gate->active ||
        (gate->gesture_profile !=
         MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2) ||
        !valid_wire_header(header) ||
        (header->direction !=
         (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER) ||
        (header->device_id != gate->wand_device_id) ||
        (header->session_id != gate->session_id) ||
        !valid_wand_tx_command_and_length(header) ||
        (gate->sequence_high_water >=
         (UINT32_MAX - UINT32_C(1))) ||
        (header->sequence !=
         (gate->sequence_high_water + UINT32_C(1)))) {
        return false;
    }

    gate->sequence_high_water = header->sequence;
    return true;
}

bool mw_target_session_reserve_v2_tx(
    mw_target_session_gate_t *gate,
    const mw_frame_header_t *header,
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES])
{
    mw_gesture_event_v2_t event;

    if ((gate == NULL) || (header == NULL) || (payload == NULL) ||
        !mw_gesture_event_v2_decode(payload, &event) ||
        (event.device_id != gate->wand_device_id) ||
        (event.session_id != gate->session_id) ||
        (event.device_id != header->device_id) ||
        (event.session_id != header->session_id) ||
        (event.logical_channel != gate->logical_channel) ||
        ((event.status_flags & MW_EVENT_STATUS_ARM_ACTIVE) == 0U)) {
        return false;
    }
    return mw_target_session_reserve_tx(gate, header);
}

bool mw_target_session_validate_v2_rx(
    const mw_target_session_gate_t *gate,
    const mw_frame_header_t *header,
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES])
{
    mw_gesture_event_v2_t event;

    return (gate != NULL) && gate->active && (header != NULL) &&
        (payload != NULL) &&
        (gate->gesture_profile ==
         MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2) &&
        (header->version == MW_PROTOCOL_VERSION) &&
        (header->direction == (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER) &&
        (header->command == (uint8_t)MW_CMD_GESTURE_EVENT) &&
        (header->flags == UINT8_C(0)) &&
        (header->device_id == gate->wand_device_id) &&
        (header->session_id == gate->session_id) &&
        (header->payload_length == (uint16_t)MW_GESTURE_EVENT_V2_BYTES) &&
        mw_gesture_event_v2_decode(payload, &event) &&
        (event.device_id == header->device_id) &&
        (event.session_id == header->session_id) &&
        (event.logical_channel == gate->logical_channel) &&
        ((event.status_flags & MW_EVENT_STATUS_ARM_ACTIVE) != 0U);
}

bool mw_target_handshake_encode_prefix(
    const mw_target_handshake_t *handshake,
    uint8_t prefix_out[MW_TARGET_HANDSHAKE_PREFIX_BYTES])
{
    if (prefix_out != NULL) {
        (void)memset(prefix_out, 0, MW_TARGET_HANDSHAKE_PREFIX_BYTES);
    }
    if ((handshake == NULL) || (prefix_out == NULL) ||
        ((handshake->message_type != MW_TARGET_HANDSHAKE_OPEN) &&
         (handshake->message_type != MW_TARGET_HANDSHAKE_ACK)) ||
        !valid_profile_and_channel(
            (mw_gesture_payload_profile_t)handshake->gesture_profile,
            handshake->logical_channel) ||
        (handshake->wand_device_id == UINT32_C(0)) ||
        (handshake->receiver_device_id == UINT32_C(0)) ||
        (handshake->wand_device_id == handshake->receiver_device_id) ||
        (handshake->session_id == UINT32_C(0))) {
        return false;
    }

    prefix_out[0] = MW_TARGET_HANDSHAKE_SCHEMA;
    prefix_out[1] = handshake->message_type;
    prefix_out[2] = handshake->gesture_profile;
    prefix_out[3] = handshake->logical_channel;
    put_u32_be(&prefix_out[4], handshake->wand_device_id);
    put_u32_be(&prefix_out[8], handshake->receiver_device_id);
    put_u32_be(&prefix_out[12], handshake->session_id);
    put_u32_be(&prefix_out[16], handshake->clock_ms);
    return true;
}

bool mw_target_handshake_decode_prefix(
    const uint8_t prefix[MW_TARGET_HANDSHAKE_PREFIX_BYTES],
    mw_target_handshake_t *handshake_out)
{
    mw_target_handshake_t candidate;

    if (handshake_out != NULL) {
        (void)memset(handshake_out, 0, sizeof(*handshake_out));
    }
    if ((prefix == NULL) || (handshake_out == NULL) ||
        (prefix[0] != MW_TARGET_HANDSHAKE_SCHEMA)) {
        return false;
    }

    candidate.message_type = prefix[1];
    candidate.gesture_profile = prefix[2];
    candidate.logical_channel = prefix[3];
    candidate.wand_device_id = get_u32_be(&prefix[4]);
    candidate.receiver_device_id = get_u32_be(&prefix[8]);
    candidate.session_id = get_u32_be(&prefix[12]);
    candidate.clock_ms = get_u32_be(&prefix[16]);
    if (!mw_target_handshake_encode_prefix(
            &candidate,
            (uint8_t[MW_TARGET_HANDSHAKE_PREFIX_BYTES]){0})) {
        return false;
    }
    *handshake_out = candidate;
    return true;
}

bool mw_target_frame_serialize(
    const mw_encrypted_frame_t *frame,
    uint8_t wire_out[MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES],
    size_t *wire_length_out)
{
    size_t aad_length;
    size_t payload_length;
    size_t wire_length;

    if (wire_out != NULL) {
        (void)memset(wire_out, 0, MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES);
    }
    if (wire_length_out != NULL) {
        *wire_length_out = 0U;
    }
    if ((frame == NULL) || (wire_out == NULL) ||
        (wire_length_out == NULL) || !valid_wire_header(&frame->header)) {
        return false;
    }

    payload_length = (size_t)frame->header.payload_length;
    wire_length = frame_wire_length(frame->header.payload_length);
    aad_length = mw_protocol_encode_aad(&frame->header, wire_out);
    if (aad_length != MW_AAD_BYTES) {
        (void)memset(wire_out, 0, MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES);
        return false;
    }
    (void)memcpy(&wire_out[MW_AAD_BYTES], frame->ciphertext,
                 payload_length);
    (void)memcpy(&wire_out[MW_AAD_BYTES + payload_length],
                 frame->tag, MW_TAG_BYTES);
    *wire_length_out = wire_length;
    return true;
}

bool mw_target_frame_parse(
    const uint8_t *wire,
    size_t wire_length,
    mw_encrypted_frame_t *frame_out)
{
    mw_encrypted_frame_t candidate;
    size_t payload_length;

    if (frame_out != NULL) {
        (void)memset(frame_out, 0, sizeof(*frame_out));
    }
    if ((wire == NULL) || (frame_out == NULL) ||
        (wire_length < MW_TARGET_ENCRYPTED_FRAME_MIN_BYTES) ||
        (wire_length > MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES)) {
        return false;
    }

    (void)memset(&candidate, 0, sizeof(candidate));
    candidate.header.version = wire[0];
    candidate.header.direction = wire[1];
    candidate.header.command = wire[2];
    candidate.header.flags = wire[3];
    candidate.header.device_id = get_u32_be(&wire[4]);
    candidate.header.session_id = get_u32_be(&wire[8]);
    candidate.header.sequence = get_u32_be(&wire[12]);
    candidate.header.issued_ms = get_u32_be(&wire[16]);
    candidate.header.payload_length = get_u16_be(&wire[20]);
    if (!valid_wire_header(&candidate.header) ||
        (wire_length != frame_wire_length(candidate.header.payload_length))) {
        return false;
    }
    payload_length = (size_t)candidate.header.payload_length;
    (void)memcpy(candidate.ciphertext, &wire[MW_AAD_BYTES],
                 payload_length);
    (void)memcpy(candidate.tag,
                 &wire[MW_AAD_BYTES + payload_length],
                 MW_TAG_BYTES);
    *frame_out = candidate;
    return true;
}

bool mw_target_encrypted_frame_serialize(
    const mw_encrypted_frame_t *frame,
    uint8_t wire_out[MW_TARGET_ENCRYPTED_GESTURE_BYTES])
{
    uint8_t generic_wire[MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES];
    size_t wire_length = 0U;

    if (wire_out != NULL) {
        (void)memset(wire_out, 0, MW_TARGET_ENCRYPTED_GESTURE_BYTES);
    }
    if ((frame == NULL) || (wire_out == NULL) ||
        (frame->header.direction !=
         (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER) ||
        (frame->header.command != (uint8_t)MW_CMD_GESTURE_EVENT) ||
        (frame->header.payload_length !=
         (uint16_t)MW_GESTURE_EVENT_V2_BYTES) ||
        !mw_target_frame_serialize(frame, generic_wire, &wire_length) ||
        (wire_length != MW_TARGET_ENCRYPTED_GESTURE_BYTES)) {
        return false;
    }
    (void)memcpy(wire_out, generic_wire, MW_TARGET_ENCRYPTED_GESTURE_BYTES);
    return true;
}

bool mw_target_encrypted_frame_parse(
    const uint8_t *wire,
    size_t wire_length,
    mw_encrypted_frame_t *frame_out)
{
    mw_encrypted_frame_t candidate;

    if (frame_out != NULL) {
        (void)memset(frame_out, 0, sizeof(*frame_out));
    }
    if ((wire == NULL) || (frame_out == NULL) ||
        (wire_length != MW_TARGET_ENCRYPTED_GESTURE_BYTES) ||
        !mw_target_frame_parse(wire, wire_length, &candidate) ||
        (candidate.header.direction !=
         (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER) ||
        (candidate.header.command != (uint8_t)MW_CMD_GESTURE_EVENT) ||
        (candidate.header.payload_length !=
         (uint16_t)MW_GESTURE_EVENT_V2_BYTES)) {
        return false;
    }
    *frame_out = candidate;
    return true;
}
