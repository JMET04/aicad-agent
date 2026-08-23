#include "mw_target_wire.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void assert_frame_fields_equal(
    const mw_encrypted_frame_t *expected,
    const mw_encrypted_frame_t *actual)
{
    size_t index;

    assert(expected->header.version == actual->header.version);
    assert(expected->header.direction == actual->header.direction);
    assert(expected->header.command == actual->header.command);
    assert(expected->header.flags == actual->header.flags);
    assert(expected->header.device_id == actual->header.device_id);
    assert(expected->header.session_id == actual->header.session_id);
    assert(expected->header.sequence == actual->header.sequence);
    assert(expected->header.issued_ms == actual->header.issued_ms);
    assert(expected->header.payload_length == actual->header.payload_length);
    for (index = 0U;
         index < (size_t)expected->header.payload_length; ++index) {
        assert(expected->ciphertext[index] == actual->ciphertext[index]);
    }
    for (index = 0U; index < MW_TAG_BYTES; ++index) {
        assert(expected->tag[index] == actual->tag[index]);
    }
}

static void test_channel_and_gesture_matrix(void)
{
    uint8_t channel;
    uint8_t gesture;

    for (channel = 0U; channel < MW_LOGICAL_CHANNEL_COUNT; ++channel) {
        for (gesture = (uint8_t)MW_GESTURE_TAP;
             gesture <= (uint8_t)MW_GESTURE_CIRCLE_CCW; ++gesture) {
            mw_target_session_gate_t gate;
            mw_gesture_event_v2_t event = {
                .device_id = UINT32_C(0x10203040) + channel,
                .session_id = UINT32_C(0x50607080) + channel,
                .logical_channel = channel,
                .gesture_id = (mw_gesture_id_t)gesture,
                .confidence_percent = UINT8_C(90),
                .battery_percent = MW_BATTERY_PERCENT_UNKNOWN,
                .status_flags = MW_EVENT_STATUS_ARM_ACTIVE,
            };
            mw_frame_header_t header = {
                .version = MW_PROTOCOL_VERSION,
                .direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER,
                .command = (uint8_t)MW_CMD_GESTURE_EVENT,
                .device_id = event.device_id,
                .session_id = event.session_id,
                .sequence = UINT32_C(1),
                .issued_ms = UINT32_C(50),
                .payload_length = (uint16_t)MW_GESTURE_EVENT_V2_BYTES,
            };
            uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];

            mw_target_session_gate_init(
                &gate, event.session_id - UINT32_C(1));
            assert(mw_target_session_gate_activate(
                &gate, event.device_id, UINT32_C(0xa0b0c0d0),
                event.session_id, channel,
                MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
                true, true, true, true, true));
            assert(mw_gesture_event_v2_encode(&event, payload));
            assert(mw_target_session_reserve_v2_tx(
                &gate, &header, payload));
            assert(!mw_target_session_reserve_v2_tx(
                &gate, &header, payload));

            header.sequence = UINT32_C(2);
            payload[5] &= (uint8_t)~MW_EVENT_STATUS_ARM_ACTIVE;
            assert(!mw_target_session_reserve_v2_tx(
                &gate, &header, payload));
            assert(gate.sequence_high_water == UINT32_C(1));

            payload[5] |= MW_EVENT_STATUS_ARM_ACTIVE;
            assert(mw_target_session_reserve_v2_tx(
                &gate, &header, payload));
            assert(gate.sequence_high_water == UINT32_C(2));

            gate.sequence_high_water = UINT32_MAX - UINT32_C(1);
            header.sequence = UINT32_MAX;
            assert(!mw_target_session_reserve_v2_tx(
                &gate, &header, payload));
            assert(gate.sequence_high_water ==
                   UINT32_MAX - UINT32_C(1));
        }
    }
}

static void test_shared_control_and_gesture_sequence(void)
{
    mw_target_session_gate_t gate;
    mw_gesture_event_v2_t event = {
        .device_id = UINT32_C(0x10203040),
        .session_id = UINT32_C(42),
        .logical_channel = UINT8_C(3),
        .gesture_id = MW_GESTURE_TWIST_CW,
        .confidence_percent = UINT8_C(95),
        .battery_percent = MW_BATTERY_PERCENT_UNKNOWN,
        .status_flags = MW_EVENT_STATUS_ARM_ACTIVE,
    };
    mw_frame_header_t header = {
        .version = MW_PROTOCOL_VERSION,
        .direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER,
        .command = (uint8_t)MW_CMD_HEARTBEAT,
        .device_id = UINT32_C(0x10203040),
        .session_id = UINT32_C(42),
        .sequence = UINT32_C(1),
        .issued_ms = UINT32_C(100),
        .payload_length = UINT16_C(0),
    };
    uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];

    mw_target_session_gate_init(&gate, UINT32_C(41));
    assert(mw_target_session_gate_activate(
        &gate, header.device_id, UINT32_C(0xa0b0c0d0),
        header.session_id, event.logical_channel,
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
        true, true, true, true, true));

    assert(mw_target_session_reserve_tx(&gate, &header));
    header.command = (uint8_t)MW_CMD_ARM_LEASE;
    header.sequence = UINT32_C(2);
    header.issued_ms = UINT32_C(125);
    assert(mw_target_session_reserve_tx(&gate, &header));

    assert(mw_gesture_event_v2_encode(&event, payload));
    header.command = (uint8_t)MW_CMD_GESTURE_EVENT;
    header.sequence = UINT32_C(3);
    header.issued_ms = UINT32_C(150);
    header.payload_length = (uint16_t)MW_GESTURE_EVENT_V2_BYTES;
    assert(mw_target_session_reserve_v2_tx(&gate, &header, payload));

    header.command = (uint8_t)MW_CMD_DISARM;
    header.sequence = UINT32_C(4);
    header.issued_ms = UINT32_C(175);
    header.payload_length = UINT16_C(0);
    assert(mw_target_session_reserve_tx(&gate, &header));
    assert(!mw_target_session_reserve_tx(&gate, &header));
    header.sequence = UINT32_C(6);
    assert(!mw_target_session_reserve_tx(&gate, &header));
    assert(gate.sequence_high_water == UINT32_C(4));

    header.sequence = UINT32_C(5);
    header.direction = (uint8_t)MW_DIRECTION_RECEIVER_TO_WAND;
    assert(!mw_target_session_reserve_tx(&gate, &header));
    header.direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER;
    header.command = (uint8_t)MW_CMD_FEEDBACK;
    assert(!mw_target_session_reserve_tx(&gate, &header));
    header.command = (uint8_t)MW_CMD_DISARM;
    assert(mw_target_session_reserve_tx(&gate, &header));
}

static void test_handshake_and_fail_closed_security(void)
{
    mw_target_session_gate_t gate;
    mw_target_handshake_t input = {
        .message_type = MW_TARGET_HANDSHAKE_OPEN,
        .gesture_profile = MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
        .logical_channel = UINT8_C(7),
        .wand_device_id = UINT32_C(0x01020304),
        .receiver_device_id = UINT32_C(0x11223344),
        .session_id = UINT32_C(0x55667788),
        .clock_ms = UINT32_C(0x99aabbcc),
    };
    mw_target_handshake_t decoded;
    uint8_t prefix[MW_TARGET_HANDSHAKE_PREFIX_BYTES];

    assert(mw_target_handshake_encode_prefix(&input, prefix));
    assert(prefix[4] == UINT8_C(0x01));
    assert(prefix[15] == UINT8_C(0x88));
    assert(prefix[16] == UINT8_C(0x99));
    assert(prefix[19] == UINT8_C(0xcc));
    assert(mw_target_handshake_decode_prefix(prefix, &decoded));
    assert(decoded.message_type == input.message_type);
    assert(decoded.gesture_profile == input.gesture_profile);
    assert(decoded.logical_channel == input.logical_channel);
    assert(decoded.wand_device_id == input.wand_device_id);
    assert(decoded.receiver_device_id == input.receiver_device_id);
    assert(decoded.session_id == input.session_id);
    assert(decoded.clock_ms == input.clock_ms);

    mw_target_session_gate_init(&gate, input.session_id - UINT32_C(1));
    assert(!mw_target_session_gate_activate(
        &gate, input.wand_device_id, input.receiver_device_id,
        input.session_id, input.logical_channel,
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
        false, true, true, true, true));
    assert(!mw_target_session_gate_activate(
        &gate, input.wand_device_id, input.receiver_device_id,
        input.session_id, input.logical_channel,
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
        true, false, true, true, true));
    assert(!mw_target_session_gate_activate(
        &gate, input.wand_device_id, input.receiver_device_id,
        input.session_id, input.logical_channel,
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
        true, true, false, true, true));
    assert(!mw_target_session_gate_activate(
        &gate, input.wand_device_id, input.receiver_device_id,
        input.session_id, input.logical_channel,
        MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1,
        true, true, true, true, true));
    assert(mw_target_session_gate_activate(
        &gate, input.wand_device_id, input.receiver_device_id,
        input.session_id, input.logical_channel,
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
        true, true, true, true, true));
}

static void test_encrypted_frame_wire_contract(void)
{
    mw_encrypted_frame_t frame = {0};
    mw_encrypted_frame_t decoded;
    uint8_t wire[MW_TARGET_ENCRYPTED_GESTURE_BYTES];
    size_t index;

    frame.header.version = MW_PROTOCOL_VERSION;
    frame.header.direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER;
    frame.header.command = (uint8_t)MW_CMD_GESTURE_EVENT;
    frame.header.device_id = UINT32_C(0x01020304);
    frame.header.session_id = UINT32_C(0x11223344);
    frame.header.sequence = UINT32_C(1);
    frame.header.issued_ms = UINT32_C(50);
    frame.header.payload_length = (uint16_t)MW_GESTURE_EVENT_V2_BYTES;
    for (index = 0U; index < MW_GESTURE_EVENT_V2_BYTES; ++index) {
        frame.ciphertext[index] = (uint8_t)(index + UINT8_C(1));
    }
    for (index = 0U; index < MW_TAG_BYTES; ++index) {
        frame.tag[index] = (uint8_t)(UINT8_C(0xf0) + (uint8_t)index);
    }

    assert(MW_TARGET_ENCRYPTED_GESTURE_BYTES == (size_t)52);
    assert(mw_target_encrypted_frame_serialize(&frame, wire));
    assert(mw_target_encrypted_frame_parse(wire, sizeof(wire), &decoded));
    assert_frame_fields_equal(&frame, &decoded);
    assert(!mw_target_encrypted_frame_parse(
        wire, sizeof(wire) - (size_t)1, &decoded));

    frame.header.sequence = UINT32_MAX;
    assert(!mw_target_encrypted_frame_serialize(&frame, wire));
    frame.header.sequence = UINT32_C(1);
    assert(mw_target_encrypted_frame_serialize(&frame, wire));
    wire[12] = UINT8_C(0xff);
    wire[13] = UINT8_C(0xff);
    wire[14] = UINT8_C(0xff);
    wire[15] = UINT8_C(0xff);
    assert(!mw_target_encrypted_frame_parse(wire, sizeof(wire), &decoded));
}

static void test_generic_frame_wire_contract(void)
{
    mw_encrypted_frame_t frame = {0};
    mw_encrypted_frame_t decoded;
    uint8_t wire[MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES + (size_t)1];
    size_t index;
    size_t wire_length = 0U;

    assert(MW_TARGET_ENCRYPTED_FRAME_MIN_BYTES == (size_t)38);
    assert(MW_TARGET_ENCRYPTED_GESTURE_BYTES == (size_t)52);
    assert(MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES == (size_t)70);
    assert(MW_TARGET_ATT_MTU_MIN_BYTES == (size_t)73);

    frame.header.version = MW_PROTOCOL_VERSION;
    frame.header.direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER;
    frame.header.command = (uint8_t)MW_CMD_HEARTBEAT;
    frame.header.device_id = UINT32_C(0x01020304);
    frame.header.session_id = UINT32_C(0x11223344);
    frame.header.sequence = UINT32_C(1);
    frame.header.issued_ms = UINT32_C(50);
    frame.header.payload_length = UINT16_C(0);
    for (index = 0U; index < MW_TAG_BYTES; ++index) {
        frame.tag[index] = (uint8_t)(UINT8_C(0xa0) + (uint8_t)index);
    }

    assert(mw_target_frame_serialize(&frame, wire, &wire_length));
    assert(wire_length == MW_TARGET_ENCRYPTED_FRAME_MIN_BYTES);
    assert(mw_target_frame_parse(wire, wire_length, &decoded));
    assert_frame_fields_equal(&frame, &decoded);
    assert(!mw_target_frame_parse(
        wire, MW_TARGET_ENCRYPTED_FRAME_MIN_BYTES - (size_t)1, &decoded));
    assert(!mw_target_frame_parse(
        wire, MW_TARGET_ENCRYPTED_FRAME_MIN_BYTES + (size_t)1, &decoded));
    wire[21] = UINT8_C(1);
    assert(!mw_target_frame_parse(wire, wire_length, &decoded));
    wire[21] = UINT8_C(0);

    frame = (mw_encrypted_frame_t){0};
    frame.header.version = MW_PROTOCOL_VERSION;
    frame.header.direction = (uint8_t)MW_DIRECTION_RECEIVER_TO_WAND;
    frame.header.command = (uint8_t)MW_CMD_FEEDBACK;
    frame.header.device_id = UINT32_C(0x11223344);
    frame.header.session_id = UINT32_C(0x55667788);
    frame.header.sequence = UINT32_C(2);
    frame.header.issued_ms = UINT32_C(75);
    frame.header.payload_length = (uint16_t)MW_MAX_PAYLOAD_BYTES;
    for (index = 0U; index < MW_MAX_PAYLOAD_BYTES; ++index) {
        frame.ciphertext[index] = (uint8_t)(index + (size_t)1);
    }
    for (index = 0U; index < MW_TAG_BYTES; ++index) {
        frame.tag[index] = (uint8_t)(UINT8_C(0xc0) + (uint8_t)index);
    }

    assert(mw_target_frame_serialize(&frame, wire, &wire_length));
    assert(wire_length == MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES);
    assert(mw_target_frame_parse(wire, wire_length, &decoded));
    assert_frame_fields_equal(&frame, &decoded);
    assert(!mw_target_frame_parse(
        wire, MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES - (size_t)1, &decoded));
    assert(!mw_target_frame_parse(
        wire, MW_TARGET_ENCRYPTED_FRAME_MAX_BYTES + (size_t)1, &decoded));

    frame.header.sequence = UINT32_MAX;
    assert(!mw_target_frame_serialize(&frame, wire, &wire_length));
    frame.header.sequence = UINT32_C(2);
    assert(mw_target_frame_serialize(&frame, wire, &wire_length));
    wire[12] = UINT8_C(0xff);
    wire[13] = UINT8_C(0xff);
    wire[14] = UINT8_C(0xff);
    wire[15] = UINT8_C(0xff);
    assert(!mw_target_frame_parse(wire, wire_length, &decoded));
}

int main(void)
{
    test_channel_and_gesture_matrix();
    test_shared_control_and_gesture_sequence();
    test_handshake_and_fail_closed_security();
    test_encrypted_frame_wire_contract();
    test_generic_frame_wire_contract();
    (void)puts("target wire contract: PASS (8 channels x 8 gestures)");
    return 0;
}
