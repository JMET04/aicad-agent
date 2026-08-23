#include "mw_gesture_event_v2.h"
#include "mw_receiver_multichannel.h"

#include <stdio.h>
#include <string.h>

#define LOCAL_DEVICE_ID UINT32_C(0x51515151)
#define PEER_BASE UINT32_C(0x10000000)

#define CHECK(condition) do { \
    if (!(condition)) { \
        (void)fprintf(stderr, "check failed at %s:%d: %s\n", \
                      __FILE__, __LINE__, #condition); \
        return 1; \
    } \
} while (0)

typedef struct {
    uint32_t session_epoch;
    uint32_t sequence_high_water;
    bool writes_allowed;
} host_store_t;

static uint32_t peer_id(uint8_t channel)
{
    return PEER_BASE + (uint32_t)channel + UINT32_C(1);
}

static bool commit_session(void *context, uint32_t session_id)
{
    host_store_t *store = (host_store_t *)context;
    if ((store == NULL) || !store->writes_allowed ||
        (session_id <= store->session_epoch)) {
        return false;
    }
    store->session_epoch = session_id;
    store->sequence_high_water = 0U;
    return true;
}

static bool commit_sequence(void *context, uint32_t sequence)
{
    host_store_t *store = (host_store_t *)context;
    if ((store == NULL) || !store->writes_allowed ||
        (sequence <= store->sequence_high_water)) {
        return false;
    }
    store->sequence_high_water = sequence;
    return true;
}

static bool checked_copy_decrypt(
    void *context,
    const uint8_t nonce[MW_NONCE_BYTES],
    const uint8_t *aad,
    size_t aad_length,
    const uint8_t *ciphertext,
    size_t ciphertext_length,
    const uint8_t tag[MW_TAG_BYTES],
    uint8_t *plaintext_out)
{
    (void)context;
    if ((nonce == NULL) || (aad == NULL) ||
        (aad_length != MW_AAD_BYTES) || (ciphertext == NULL) ||
        (ciphertext_length > MW_MAX_PAYLOAD_BYTES) ||
        (tag == NULL) || (tag[0] != UINT8_C(0xa5)) ||
        (plaintext_out == NULL)) {
        return false;
    }
    (void)memcpy(plaintext_out, ciphertext, ciphertext_length);
    return true;
}

static void make_frame(
    mw_encrypted_frame_t *frame,
    uint8_t channel,
    uint32_t session_id,
    uint32_t sequence,
    uint32_t issued_ms,
    mw_command_t command,
    const uint8_t *payload,
    uint16_t payload_length)
{
    (void)memset(frame, 0, sizeof(*frame));
    frame->header.version = MW_PROTOCOL_VERSION;
    frame->header.direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER;
    frame->header.command = (uint8_t)command;
    frame->header.device_id = peer_id(channel);
    frame->header.session_id = session_id;
    frame->header.sequence = sequence;
    frame->header.issued_ms = issued_ms;
    frame->header.payload_length = payload_length;
    if ((payload != NULL) &&
        ((size_t)payload_length <= MW_MAX_PAYLOAD_BYTES)) {
        (void)memcpy(frame->ciphertext, payload, (size_t)payload_length);
    }
    frame->tag[0] = UINT8_C(0xa5);
}

static bool make_v2_event_frame(
    mw_encrypted_frame_t *frame,
    uint8_t route_channel,
    uint8_t payload_channel,
    uint32_t embedded_device_id,
    uint32_t session_id,
    uint32_t sequence,
    uint32_t issued_ms,
    mw_gesture_id_t gesture_id)
{
    mw_gesture_event_v2_t event;
    uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];

    event.device_id = embedded_device_id;
    event.session_id = session_id;
    event.logical_channel = payload_channel;
    event.gesture_id = gesture_id;
    event.confidence_percent = UINT8_C(90);
    event.battery_percent = UINT8_C(75);
    event.status_flags = (uint8_t)(MW_EVENT_STATUS_ARM_ACTIVE |
                                   MW_EVENT_STATUS_BATTERY_KNOWN);
    if (!mw_gesture_event_v2_encode(&event, payload)) {
        return false;
    }
    make_frame(frame, route_channel, session_id, sequence, issued_ms,
               MW_CMD_GESTURE_EVENT, payload,
               (uint16_t)MW_GESTURE_EVENT_V2_BYTES);
    return true;
}

static bool make_v2_unknown_battery_frame(
    mw_encrypted_frame_t *frame,
    uint8_t channel,
    uint32_t session_id,
    uint32_t sequence,
    uint32_t issued_ms,
    mw_gesture_id_t gesture_id)
{
    mw_gesture_event_v2_t event;
    uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];

    event.device_id = peer_id(channel);
    event.session_id = session_id;
    event.logical_channel = channel;
    event.gesture_id = gesture_id;
    event.confidence_percent = UINT8_C(90);
    event.battery_percent = MW_BATTERY_PERCENT_UNKNOWN;
    event.status_flags = MW_EVENT_STATUS_ARM_ACTIVE;
    if (!mw_gesture_event_v2_encode(&event, payload)) {
        return false;
    }
    make_frame(frame, channel, session_id, sequence, issued_ms,
               MW_CMD_GESTURE_EVENT, payload,
               (uint16_t)MW_GESTURE_EVENT_V2_BYTES);
    return true;
}

static bool make_v2_unarmed_frame(
    mw_encrypted_frame_t *frame,
    uint8_t channel,
    uint32_t session_id,
    uint32_t sequence,
    uint32_t issued_ms,
    mw_gesture_id_t gesture_id)
{
    mw_gesture_event_v2_t event;
    uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];

    event.device_id = peer_id(channel);
    event.session_id = session_id;
    event.logical_channel = channel;
    event.gesture_id = gesture_id;
    event.confidence_percent = UINT8_C(90);
    event.battery_percent = UINT8_C(75);
    event.status_flags = MW_EVENT_STATUS_BATTERY_KNOWN;
    if (!mw_gesture_event_v2_encode(&event, payload)) {
        return false;
    }
    make_frame(frame, channel, session_id, sequence, issued_ms,
               MW_CMD_GESTURE_EVENT, payload,
               (uint16_t)MW_GESTURE_EVENT_V2_BYTES);
    return true;
}

static bool open_channel(
    mw_receiver_multichannel_t *manager,
    host_store_t *store,
    uint8_t channel,
    uint32_t session_id,
    mw_gesture_payload_profile_t gesture_profile,
    uint32_t now_ms)
{
    const mw_receiver_handshake_security_t security = {
        true, true, true, gesture_profile};
    return mw_receiver_multichannel_begin_handshake(
               manager, channel, peer_id(channel), session_id, now_ms) &&
        mw_receiver_multichannel_complete_handshake(
            manager, channel, &security, now_ms,
            commit_session, store);
}

static mw_receiver_channel_result_t receive(
    mw_receiver_multichannel_t *manager,
    host_store_t *store,
    uint8_t channel,
    const mw_encrypted_frame_t *frame,
    uint32_t now_ms)
{
    return mw_receiver_multichannel_receive(
        manager, channel, frame, now_ms,
        checked_copy_decrypt, store, commit_sequence, store);
}

static int check_durable_window_binding_isolation(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t stores[2] = {
        {10U, 0U, true},
        {10U, 0U, true}
    };
    uint8_t channel;

    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(mw_receiver_multichannel_set_effect_readiness(
        &manager, true, true));
    for (channel = 0U; channel < UINT8_C(2); ++channel) {
        CHECK(mw_receiver_multichannel_configure(
            &manager, channel, peer_id(channel), UINT32_C(10), true));
        CHECK(mw_receiver_multichannel_boot_channel(
            &manager, channel, true, true, true));
        CHECK(open_channel(
            &manager, &stores[channel], channel,
            UINT32_C(100) + (uint32_t)channel,
            MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
            UINT32_C(1000)));
    }

    CHECK(!mw_receiver_multichannel_bind_durable_session_window(
        &manager, MW_RECEIVER_LOGICAL_CHANNELS,
        UINT32_C(100), UINT32_MAX - UINT32_C(1)));
    CHECK(mw_receiver_multichannel_bind_durable_session_window(
        &manager, UINT8_C(0), UINT32_C(100),
        UINT32_MAX - UINT32_C(1)));
    CHECK(!mw_receiver_multichannel_bind_durable_session_window(
        &manager, UINT8_C(1), UINT32_C(100),
        UINT32_MAX - UINT32_C(1)));
    CHECK(manager.channels[0].runtime.state ==
          MW_RECEIVER_SESSION_ACTIVE);
    CHECK(manager.channels[1].runtime.state == MW_RECEIVER_FAULT);
    CHECK(mw_receiver_multichannel_active_sessions(&manager) == 1U);
    return 0;
}

static int check_eight_channel_isolation(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t stores[MW_RECEIVER_LOGICAL_CHANNELS];
    mw_encrypted_frame_t frames[MW_RECEIVER_LOGICAL_CHANNELS];
    uint8_t channel;

    (void)memset(stores, 0, sizeof(stores));
    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(mw_receiver_multichannel_set_effect_readiness(
        &manager, true, true));
    CHECK(!mw_receiver_multichannel_configure(
        &manager, MW_RECEIVER_LOGICAL_CHANNELS, peer_id(0U),
        10U, true));

    for (channel = 0U; channel < MW_RECEIVER_LOGICAL_CHANNELS; ++channel) {
        stores[channel].session_epoch = 10U;
        stores[channel].writes_allowed = true;
        CHECK(mw_receiver_multichannel_configure(
            &manager, channel, peer_id(channel), 10U, true));
        CHECK(mw_receiver_multichannel_boot_channel(
            &manager, channel, true, true, true));
        CHECK(open_channel(
            &manager, &stores[channel], channel,
            UINT32_C(100) + (uint32_t)channel,
            MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
            UINT32_C(1000)));
    }
    CHECK(!mw_receiver_multichannel_configure(
        &manager, 0U, peer_id(7U), 10U, true));
    CHECK(mw_receiver_multichannel_active_sessions(&manager) == 8U);

    for (channel = 0U; channel < MW_RECEIVER_LOGICAL_CHANNELS; ++channel) {
        CHECK(make_v2_event_frame(
            &frames[channel], channel, channel, peer_id(channel),
            UINT32_C(100) + (uint32_t)channel, 1U,
            UINT32_C(1000) + (uint32_t)channel,
            (mw_gesture_id_t)((uint8_t)MW_GESTURE_TAP + channel)));
        CHECK(receive(
            &manager, &stores[channel], channel, &frames[channel],
            UINT32_C(1000) + (uint32_t)channel) ==
            MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
        CHECK(mw_receiver_runtime_outputs_safe(
            &manager.channels[channel].runtime));
        CHECK(manager.effects.active_channel == channel);
        CHECK(manager.effects.active_effect ==
              mw_effect_for_gesture(
                  (mw_gesture_id_t)((uint8_t)MW_GESTURE_TAP + channel)));
    }

    CHECK(make_v2_unknown_battery_frame(
        &frames[7], 7U, UINT32_C(107), 2U, UINT32_C(1015),
        MW_GESTURE_TWIST_CCW));
    CHECK(receive(&manager, &stores[7], 7U, &frames[7],
                  UINT32_C(1015)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    CHECK(manager.effects.active_effect == MW_EFFECT_ICE);
    CHECK(manager.effects.pattern.state == MW_PATTERN_STATE_GESTURE);
    CHECK(!mw_audio_synth_is_muted(&manager.effects.audio));

    CHECK(receive(&manager, &stores[0], 0U, &frames[0], UINT32_C(1010)) ==
          MW_RECEIVER_CHANNEL_REJECTED_RUNTIME);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.channels[1].runtime.state == MW_RECEIVER_SESSION_ACTIVE);

    CHECK(make_v2_event_frame(
        &frames[2], 2U, 3U, peer_id(2U), UINT32_C(102), 2U,
        UINT32_C(1020), MW_GESTURE_TWIST_CW));
    CHECK(receive(&manager, &stores[2], 2U, &frames[2], UINT32_C(1020)) ==
          MW_RECEIVER_CHANNEL_REJECTED_BINDING);
    CHECK(manager.channels[2].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.channels[3].runtime.state == MW_RECEIVER_SESSION_ACTIVE);

    CHECK(make_v2_event_frame(
        &frames[3], 3U, 3U, peer_id(4U), UINT32_C(103), 2U,
        UINT32_C(1030), MW_GESTURE_TWIST_CCW));
    CHECK(receive(&manager, &stores[3], 3U, &frames[3], UINT32_C(1030)) ==
          MW_RECEIVER_CHANNEL_REJECTED_RUNTIME);
    CHECK(manager.channels[3].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.channels[4].runtime.state == MW_RECEIVER_SESSION_ACTIVE);

    {
        const uint8_t legacy[MW_GESTURE_EVENT_PAYLOAD_BYTES] = {
            (uint8_t)MW_GESTURE_TAP, UINT8_C(90)};
        make_frame(&frames[1], 1U, UINT32_C(101), 2U,
                   UINT32_C(1040), MW_CMD_GESTURE_EVENT, legacy,
                   (uint16_t)MW_GESTURE_EVENT_PAYLOAD_BYTES);
        CHECK(receive(&manager, &stores[1], 1U, &frames[1],
                      UINT32_C(1040)) ==
              MW_RECEIVER_CHANNEL_REJECTED_RUNTIME);
        CHECK(manager.channels[1].runtime.state ==
              MW_RECEIVER_WAIT_HANDSHAKE);
    }

    make_frame(&frames[4], 4U, UINT32_C(104), 2U,
               UINT32_C(1240), MW_CMD_HEARTBEAT, NULL, 0U);
    CHECK(receive(&manager, &stores[4], 4U, &frames[4],
                  UINT32_C(1240)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    mw_receiver_multichannel_tick(&manager, UINT32_C(1251));
    CHECK(manager.channels[4].runtime.state == MW_RECEIVER_SESSION_ACTIVE);
    CHECK(manager.channels[5].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_multichannel_active_sessions(&manager) == 1U);
    return 0;
}

static int check_handshake_media_cleanup(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t stores[2] = {
        {10U, 0U, true},
        {10U, 0U, true}
    };
    const mw_receiver_handshake_security_t wrong_profile = {
        true, true, true, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1};
    mw_encrypted_frame_t frame;
    uint32_t heartbeat_ms;
    uint32_t sequence = 1U;

    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(mw_receiver_multichannel_set_effect_readiness(
        &manager, true, true));
    CHECK(mw_receiver_multichannel_configure(
        &manager, 0U, peer_id(0U), 10U, true));
    CHECK(mw_receiver_multichannel_configure(
        &manager, 1U, peer_id(1U), 10U, true));
    CHECK(mw_receiver_multichannel_boot_channel(
        &manager, 0U, true, true, true));
    CHECK(mw_receiver_multichannel_boot_channel(
        &manager, 1U, true, true, true));
    CHECK(open_channel(
        &manager, &stores[0], 0U, UINT32_C(100),
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2, UINT32_C(1000)));

    CHECK(mw_receiver_multichannel_begin_handshake(
        &manager, 1U, peer_id(1U), UINT32_C(101), UINT32_C(1100)));
    CHECK(manager.effects.active_effect == MW_EFFECT_PAIRING);
    for (heartbeat_ms = UINT32_C(1200);
         heartbeat_ms <= UINT32_C(2000);
         heartbeat_ms += UINT32_C(200)) {
        make_frame(&frame, 0U, UINT32_C(100), sequence++,
                   heartbeat_ms, MW_CMD_HEARTBEAT, NULL, 0U);
        CHECK(receive(
            &manager, &stores[0], 0U, &frame, heartbeat_ms) ==
              MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    }
    mw_receiver_multichannel_tick(
        &manager, UINT32_C(1100) + MW_RECEIVER_HANDSHAKE_TIMEOUT_MS);
    CHECK(manager.channels[1].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_SESSION_ACTIVE);
    CHECK(manager.effects.active_effect == MW_EFFECT_DISCONNECTED);
    CHECK(manager.effects.effect_timed);
    for (heartbeat_ms = UINT32_C(2200);
         heartbeat_ms <= UINT32_C(2400);
         heartbeat_ms += UINT32_C(200)) {
        make_frame(&frame, 0U, UINT32_C(100), sequence++,
                   heartbeat_ms, MW_CMD_HEARTBEAT, NULL, 0U);
        CHECK(receive(
            &manager, &stores[0], 0U, &frame, heartbeat_ms) ==
              MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    }
    mw_receiver_multichannel_tick(
        &manager, UINT32_C(1100) + MW_RECEIVER_HANDSHAKE_TIMEOUT_MS +
                  MW_EFFECT_DISCONNECT_PROMPT_MS);
    CHECK(manager.effects.active_channel == 0U);
    CHECK(manager.effects.pattern.state == MW_PATTERN_STATE_CONNECTED);

    CHECK(mw_receiver_multichannel_begin_handshake(
        &manager, 1U, peer_id(1U), UINT32_C(101), UINT32_C(2600)));
    CHECK(!mw_receiver_multichannel_complete_handshake(
        &manager, 1U, &wrong_profile, UINT32_C(2600),
        commit_session, &stores[1]));
    CHECK(manager.channels[1].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_SESSION_ACTIVE);
    CHECK(manager.effects.active_effect == MW_EFFECT_DISCONNECTED);
    CHECK(manager.effects.restore_connected_pending);
    return 0;
}

static int check_media_only_default(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t store = {10U, 0U, true};
    mw_encrypted_frame_t frame;
    const uint8_t pulse_10_ms[2] = {0U, UINT8_C(10)};

    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(!manager.dangerous_output_authority_enabled);
    CHECK(mw_receiver_multichannel_configure(
        &manager, 0U, peer_id(0U), 10U, true));
    CHECK(mw_receiver_multichannel_boot_channel(
        &manager, 0U, true, true, true));
    CHECK(open_channel(
        &manager, &store, 0U, UINT32_C(50),
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2, UINT32_C(500)));

    make_frame(&frame, 0U, UINT32_C(50), 1U, UINT32_C(500),
               MW_CMD_ARM_LEASE, NULL, 0U);
    CHECK(receive(&manager, &store, 0U, &frame, UINT32_C(500)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, 0U, UINT32_C(50), 2U, UINT32_C(510),
               MW_CMD_PULSE_LOW_SIDE, pulse_10_ms, 2U);
    CHECK(receive(&manager, &store, 0U, &frame, UINT32_C(510)) ==
          MW_RECEIVER_CHANNEL_REJECTED_OUTPUT_DISABLED);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_multichannel_outputs(&manager)->low_side_active ==
          false);
    return 0;
}

static int check_unarmed_v2_rejected_silently(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t store = {10U, 0U, true};
    mw_encrypted_frame_t frame;

    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(mw_receiver_multichannel_set_effect_readiness(
        &manager, true, true));
    CHECK(mw_receiver_multichannel_configure(
        &manager, 0U, peer_id(0U), 10U, true));
    CHECK(mw_receiver_multichannel_boot_channel(
        &manager, 0U, true, true, true));
    CHECK(open_channel(
        &manager, &store, 0U, UINT32_C(60),
        MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2, UINT32_C(600)));
    CHECK(manager.effects.active_effect == MW_EFFECT_NONE);
    CHECK(mw_audio_synth_is_muted(&manager.effects.audio));

    CHECK(make_v2_unarmed_frame(
        &frame, 0U, UINT32_C(60), 1U, UINT32_C(600),
        MW_GESTURE_TWIST_CW));
    CHECK(receive(&manager, &store, 0U, &frame, UINT32_C(600)) ==
          MW_RECEIVER_CHANNEL_REJECTED_ARM_INACTIVE);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.effects.connected_channels_mask == 0U);
    CHECK(manager.effects.active_effect == MW_EFFECT_NONE);
    CHECK(manager.effects.pattern.state == MW_PATTERN_STATE_DISCONNECTED);
    CHECK(mw_audio_synth_is_muted(&manager.effects.audio));
    CHECK(mw_receiver_multichannel_outputs(&manager)->low_side_active ==
          false);
    return 0;
}

static int check_owner_release_without_tick(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t stores[2] = {
        {10U, 0U, true},
        {10U, 0U, true}
    };
    mw_encrypted_frame_t frame;
    const uint8_t aux_on[1] = {UINT8_C(1)};
    const uint8_t aux_off[1] = {UINT8_C(0)};
    const uint8_t pulse_10_ms[2] = {0U, UINT8_C(10)};
    uint8_t channel;

    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(mw_receiver_multichannel_set_output_authority(&manager, true));
    for (channel = 0U; channel < 2U; ++channel) {
        CHECK(mw_receiver_multichannel_configure(
            &manager, channel, peer_id(channel), 10U, true));
        CHECK(mw_receiver_multichannel_boot_channel(
            &manager, channel, true, true, true));
        CHECK(open_channel(
            &manager, &stores[channel], channel,
            UINT32_C(400) + (uint32_t)channel,
            MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
            UINT32_C(4000)));
    }

    make_frame(&frame, 0U, UINT32_C(400), 1U, UINT32_C(4000),
               MW_CMD_ARM_LEASE, NULL, 0U);
    CHECK(receive(&manager, &stores[0], 0U, &frame, UINT32_C(4000)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, 0U, UINT32_C(400), 2U, UINT32_C(4010),
               MW_CMD_SET_AUX, aux_on, 1U);
    CHECK(receive(&manager, &stores[0], 0U, &frame, UINT32_C(4010)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_OUTPUT_POLICY);
    CHECK(manager.output_owner == INT8_C(0));
    CHECK(mw_receiver_multichannel_outputs(&manager)->aux_active);

    make_frame(&frame, 0U, UINT32_C(400), 3U, UINT32_C(4020),
               MW_CMD_SET_AUX, aux_off, 1U);
    CHECK(receive(&manager, &stores[0], 0U, &frame, UINT32_C(4020)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_OUTPUT_POLICY);
    CHECK(manager.output_owner == MW_RECEIVER_NO_OUTPUT_OWNER);
    CHECK(mw_receiver_multichannel_outputs(&manager)->aux_active == false);

    make_frame(&frame, 1U, UINT32_C(401), 1U, UINT32_C(4020),
               MW_CMD_ARM_LEASE, NULL, 0U);
    CHECK(receive(&manager, &stores[1], 1U, &frame, UINT32_C(4020)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, 1U, UINT32_C(401), 2U, UINT32_C(4030),
               MW_CMD_PULSE_LOW_SIDE, pulse_10_ms, 2U);
    CHECK(receive(&manager, &stores[1], 1U, &frame, UINT32_C(4030)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_OUTPUT_POLICY);
    CHECK(manager.output_owner == INT8_C(1));
    CHECK(mw_receiver_multichannel_outputs(&manager)->low_side_active);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_SESSION_ACTIVE);
    CHECK(manager.channels[1].runtime.state == MW_RECEIVER_SESSION_ACTIVE);
    return 0;
}

static int check_output_owner_and_legacy(void)
{
    mw_receiver_multichannel_t manager;
    host_store_t stores[MW_RECEIVER_LOGICAL_CHANNELS];
    mw_encrypted_frame_t frame;
    uint8_t channel;
    const uint8_t pulse_200_ms[2] = {0U, UINT8_C(200)};
    const uint8_t legacy[MW_GESTURE_EVENT_PAYLOAD_BYTES] = {
        (uint8_t)MW_GESTURE_TAP, UINT8_C(90)};

    (void)memset(stores, 0, sizeof(stores));
    mw_receiver_multichannel_init(&manager, LOCAL_DEVICE_ID);
    CHECK(!manager.dangerous_output_authority_enabled);
    CHECK(mw_receiver_multichannel_set_output_authority(
        &manager, true));
    for (channel = 0U; channel < MW_RECEIVER_LOGICAL_CHANNELS; ++channel) {
        stores[channel].session_epoch = 10U;
        stores[channel].writes_allowed = true;
        CHECK(mw_receiver_multichannel_configure(
            &manager, channel, peer_id(channel), 10U, true));
        CHECK(mw_receiver_multichannel_boot_channel(
            &manager, channel, true, true, true));
    }
    CHECK(open_channel(&manager, &stores[5], 5U, UINT32_C(205),
                       MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
                       UINT32_C(1300)));
    CHECK(open_channel(&manager, &stores[6], 6U, UINT32_C(206),
                       MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2,
                       UINT32_C(1300)));

    make_frame(&frame, 5U, UINT32_C(205), 1U, UINT32_C(1300),
               MW_CMD_ARM_LEASE, NULL, 0U);
    CHECK(receive(&manager, &stores[5], 5U, &frame, UINT32_C(1300)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, 5U, UINT32_C(205), 2U, UINT32_C(1310),
               MW_CMD_PULSE_LOW_SIDE, pulse_200_ms, 2U);
    CHECK(receive(&manager, &stores[5], 5U, &frame, UINT32_C(1310)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_OUTPUT_POLICY);
    CHECK(manager.output_owner == INT8_C(5));
    CHECK(mw_receiver_multichannel_outputs(&manager)->low_side_active);

    make_frame(&frame, 6U, UINT32_C(206), 1U, UINT32_C(1300),
               MW_CMD_ARM_LEASE, NULL, 0U);
    CHECK(receive(&manager, &stores[6], 6U, &frame, UINT32_C(1300)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, 6U, UINT32_C(206), 2U, UINT32_C(1310),
               MW_CMD_PULSE_LOW_SIDE, pulse_200_ms, 2U);
    CHECK(receive(&manager, &stores[6], 6U, &frame, UINT32_C(1310)) ==
          MW_RECEIVER_CHANNEL_REJECTED_OUTPUT_CONFLICT);
    CHECK(manager.channels[6].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(manager.output_owner == INT8_C(5));
    CHECK(mw_receiver_multichannel_outputs(&manager)->low_side_active);

    mw_receiver_multichannel_tick(&manager, UINT32_C(1410));
    CHECK(manager.output_owner == MW_RECEIVER_NO_OUTPUT_OWNER);
    CHECK(!mw_receiver_multichannel_outputs(&manager)->low_side_active);

    CHECK(open_channel(&manager, &stores[0], 0U, UINT32_C(300),
                       MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1,
                       UINT32_C(1500)));
    make_frame(&frame, 0U, UINT32_C(300), 1U, UINT32_C(1500),
               MW_CMD_GESTURE_EVENT, legacy,
               (uint16_t)MW_GESTURE_EVENT_PAYLOAD_BYTES);
    CHECK(receive(&manager, &stores[0], 0U, &frame, UINT32_C(1500)) ==
          MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION);
    CHECK(manager.channels[0].runtime.last_gesture_valid);
    CHECK(!manager.channels[0].runtime.last_gesture_v2_valid);
    CHECK(mw_receiver_multichannel_outputs(&manager)->low_side_active ==
          false);

    CHECK(make_v2_event_frame(
        &frame, 0U, 0U, peer_id(0U), UINT32_C(300), 2U,
        UINT32_C(1510), MW_GESTURE_TAP));
    CHECK(receive(&manager, &stores[0], 0U, &frame, UINT32_C(1510)) ==
          MW_RECEIVER_CHANNEL_REJECTED_RUNTIME);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);

    CHECK(open_channel(&manager, &stores[0], 0U, UINT32_C(301),
                       MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1,
                       UINT32_C(1520)));
    CHECK(!mw_replay_guard_set_gesture_profile(
        &manager.channels[0].runtime.replay_guard,
        MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED));
    make_frame(&frame, 0U, UINT32_C(301), 1U, UINT32_C(1520),
               MW_CMD_GESTURE_EVENT, legacy,
               (uint16_t)MW_GESTURE_EVENT_PAYLOAD_BYTES);
    CHECK(receive(&manager, &stores[0], 0U, &frame, UINT32_C(1520)) ==
          MW_RECEIVER_CHANNEL_REJECTED_RUNTIME);
    CHECK(manager.channels[0].runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    return 0;
}

int main(void)
{
    CHECK(check_durable_window_binding_isolation() == 0);
    CHECK(check_eight_channel_isolation() == 0);
    CHECK(check_handshake_media_cleanup() == 0);
    CHECK(check_media_only_default() == 0);
    CHECK(check_unarmed_v2_rejected_silently() == 0);
    CHECK(check_owner_release_without_tick() == 0);
    CHECK(check_output_owner_and_legacy() == 0);
    (void)puts("receiver 8-channel isolation vectors passed");
    return 0;
}
