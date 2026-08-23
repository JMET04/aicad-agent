#include "mw_receiver_board_pins.h"
#include "mw_receiver_runtime.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            (void)fprintf(stderr, "receiver runtime check failed at line %d\n", \
                          __LINE__); \
            return 1; \
        } \
    } while (false)

#define LOCAL_DEVICE_ID UINT32_C(0xA0A1A2A3)
#define WAND_DEVICE_ID UINT32_C(0x01020304)

typedef struct {
    uint32_t committed_session;
    uint32_t committed_high_water;
    uint32_t decrypt_calls;
    uint32_t sequence_commit_calls;
    bool session_commit_allowed;
    bool sequence_commit_allowed;
    bool decrypt_allowed;
} host_security_t;

static bool host_commit_session(void *context, uint32_t session_id)
{
    host_security_t *host = (host_security_t *)context;
    if ((host == NULL) || !host->session_commit_allowed ||
        (session_id <= host->committed_session)) {
        return false;
    }
    host->committed_session = session_id;
    host->committed_high_water = 0U;
    return true;
}

static bool host_commit_sequence(void *context, uint32_t sequence)
{
    host_security_t *host = (host_security_t *)context;
    if (host == NULL) {
        return false;
    }
    host->sequence_commit_calls++;
    if (!host->sequence_commit_allowed ||
        (sequence <= host->committed_high_water)) {
        return false;
    }
    host->committed_high_water = sequence;
    return true;
}

/* Host plumbing adapter only. The tag sentinel is not cryptography. */
static bool host_checked_noncrypto_decrypt(
    void *context,
    const uint8_t nonce[MW_NONCE_BYTES],
    const uint8_t *aad,
    size_t aad_length,
    const uint8_t *ciphertext,
    size_t ciphertext_length,
    const uint8_t tag[MW_TAG_BYTES],
    uint8_t *plaintext_out)
{
    host_security_t *host = (host_security_t *)context;
    if (host != NULL) {
        host->decrypt_calls++;
    }
    if ((host == NULL) || !host->decrypt_allowed ||
        (nonce == NULL) || (aad == NULL) ||
        (aad_length != MW_AAD_BYTES) ||
        (ciphertext == NULL) || (plaintext_out == NULL) ||
        (tag == NULL) || (tag[0] != UINT8_C(0xA5))) {
        return false;
    }
    (void)memcpy(plaintext_out, ciphertext, ciphertext_length);
    return true;
}

static void make_frame(
    mw_encrypted_frame_t *frame,
    mw_command_t command,
    uint32_t session_id,
    uint32_t sequence,
    uint32_t issued_ms,
    const uint8_t *payload,
    uint16_t payload_length)
{
    (void)memset(frame, 0, sizeof(*frame));
    frame->header.version = MW_PROTOCOL_VERSION;
    frame->header.direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER;
    frame->header.command = (uint8_t)command;
    frame->header.device_id = WAND_DEVICE_ID;
    frame->header.session_id = session_id;
    frame->header.sequence = sequence;
    frame->header.issued_ms = issued_ms;
    frame->header.payload_length = payload_length;
    if ((payload != NULL) &&
        ((size_t)payload_length <= MW_MAX_PAYLOAD_BYTES)) {
        (void)memcpy(frame->ciphertext, payload, (size_t)payload_length);
    }
    frame->tag[0] = UINT8_C(0xA5);
}

static void init_ready_runtime(
    mw_receiver_runtime_t *runtime,
    uint32_t persisted_session)
{
    mw_receiver_runtime_init(runtime, LOCAL_DEVICE_ID, WAND_DEVICE_ID,
                             persisted_session, true);
    mw_receiver_runtime_boot_complete(runtime, true, true, true);
}

static bool open_session(
    mw_receiver_runtime_t *runtime,
    host_security_t *host,
    uint32_t session_id,
    uint32_t now_ms)
{
    const mw_receiver_handshake_security_t security = {
        true, true, true, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1};
    return mw_receiver_runtime_begin_handshake(
               runtime, WAND_DEVICE_ID, session_id, now_ms) &&
        mw_receiver_runtime_complete_handshake(
            runtime, &security, now_ms, host_commit_session, host);
}

static mw_receiver_frame_result_t receive(
    mw_receiver_runtime_t *runtime,
    host_security_t *host,
    const mw_encrypted_frame_t *frame,
    uint32_t now_ms)
{
    return mw_receiver_runtime_receive_frame(
        runtime, frame, now_ms,
        host_checked_noncrypto_decrypt, host,
        host_commit_sequence, host);
}

static int check_durable_session_window_contract(void)
{
    mw_replay_guard_t guard;
    mw_receiver_runtime_t runtime;
    mw_encrypted_frame_t frame;
    host_security_t host = {
        50U, 0U, 0U, 0U, true, true, true};
    uint32_t decrypt_calls;

    mw_replay_guard_init(
        &guard, WAND_DEVICE_ID, UINT32_C(51), 0U, true);
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_C(10)));
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        NULL, UINT32_C(51), UINT32_C(10)));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(0), UINT32_C(10)));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(52), UINT32_C(10)));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_C(0)));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_MAX));

    mw_replay_guard_init(
        &guard, WAND_DEVICE_ID, UINT32_C(51), 0U, false);
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_C(10)));

    mw_replay_guard_init(
        &guard, UINT32_C(0), UINT32_C(51), 0U, true);
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_C(10)));

    mw_replay_guard_init(
        &guard, WAND_DEVICE_ID, UINT32_MAX, 0U, true);
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_MAX, UINT32_C(10)));

    mw_replay_guard_init(
        &guard, WAND_DEVICE_ID, UINT32_C(51), UINT32_C(1), true);
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_C(10)));

    mw_replay_guard_init(
        &guard, WAND_DEVICE_ID, UINT32_C(51), 0U, true);
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_MAX - UINT32_C(1)));
    CHECK(guard.durable_session_window_bound);
    CHECK(guard.durable_session_id == UINT32_C(51));
    CHECK(guard.reserved_sequence_ceiling ==
          UINT32_MAX - UINT32_C(1));
    CHECK(mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1));
    CHECK(!mw_replay_guard_set_gesture_profile(
        &guard, MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2));
    CHECK(guard.gesture_payload_profile ==
          MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1);
    CHECK(!mw_replay_guard_bind_durable_session_window(
        &guard, UINT32_C(51), UINT32_MAX - UINT32_C(1)));

    init_ready_runtime(&runtime, UINT32_C(50));
    CHECK(open_session(&runtime, &host, UINT32_C(51), UINT32_C(1000)));
    CHECK(mw_receiver_runtime_bind_durable_session_window(
        &runtime, UINT32_C(51), UINT32_C(2)));
    make_frame(&frame, MW_CMD_HEARTBEAT, UINT32_C(51), UINT32_C(1),
               UINT32_C(1000), NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, UINT32_C(1000)) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    CHECK(host.sequence_commit_calls == UINT32_C(1));
    CHECK(host.committed_high_water == UINT32_C(1));

    decrypt_calls = host.decrypt_calls;
    make_frame(&frame, MW_CMD_HEARTBEAT, UINT32_C(51), UINT32_C(3),
               UINT32_C(1010), NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, UINT32_C(1010)) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);
    CHECK(host.decrypt_calls == decrypt_calls);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);

    /* Epoch 52 is durable, then power is lost before ACK/window binding. */
    CHECK(open_session(&runtime, &host, UINT32_C(52), UINT32_C(1100)));
    CHECK(host.committed_session == UINT32_C(52));
    init_ready_runtime(&runtime, host.committed_session);
    CHECK(!mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, UINT32_C(52), UINT32_C(1200)));

    CHECK(open_session(&runtime, &host, UINT32_C(53), UINT32_C(1200)));
    CHECK(mw_receiver_runtime_bind_durable_session_window(
        &runtime, UINT32_C(53), UINT32_C(2)));
    decrypt_calls = host.decrypt_calls;
    make_frame(&frame, MW_CMD_HEARTBEAT, UINT32_C(52), UINT32_C(1),
               UINT32_C(1200), NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, UINT32_C(1200)) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);
    CHECK(host.decrypt_calls == decrypt_calls);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    return 0;
}

static int check_board_authority_and_boot(void)
{
    mw_receiver_runtime_t runtime;

    CHECK(MW_RECEIVER_UART_TX_MODULE_PAD == 32U);
    CHECK(MW_RECEIVER_UART_TX_GPIO_PORT == 0U);
    CHECK(MW_RECEIVER_UART_TX_GPIO_PIN == 11U);
    CHECK(MW_RECEIVER_UART_RX_MODULE_PAD == 33U);
    CHECK(MW_RECEIVER_UART_RX_GPIO_PORT == 1U);
    CHECK(MW_RECEIVER_UART_RX_GPIO_PIN == 9U);
    CHECK(MW_RECEIVER_PWM_AUX_MODULE_PAD == 42U);
    CHECK(MW_RECEIVER_OPTO_DRV_MODULE_PAD == 43U);
    CHECK(MW_RECEIVER_LOAD_GATE_MODULE_PAD == 44U);
    CHECK(MW_RECEIVER_PWR_GOOD_MODULE_PAD == 46U);

    mw_receiver_runtime_init(&runtime, 0U, WAND_DEVICE_ID, 0U, true);
    CHECK(runtime.state == MW_RECEIVER_FAULT);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    mw_receiver_runtime_init(&runtime, LOCAL_DEVICE_ID, WAND_DEVICE_ID,
                             0U, false);
    CHECK(runtime.state == MW_RECEIVER_FAULT);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    mw_receiver_runtime_init(&runtime, LOCAL_DEVICE_ID, WAND_DEVICE_ID,
                             10U, true);
    mw_receiver_runtime_boot_complete(&runtime, true, true, false);
    CHECK(runtime.state == MW_RECEIVER_UNPROVISIONED);
    mw_receiver_runtime_link_lost(&runtime);
    CHECK(runtime.state == MW_RECEIVER_UNPROVISIONED);
    CHECK(!mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, 11U, 100U));

    init_ready_runtime(&runtime, 10U);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    mw_receiver_runtime_power_good_changed(&runtime, false);
    CHECK(runtime.state == MW_RECEIVER_FAULT);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    return 0;
}

static int check_handshake_gate(void)
{
    mw_receiver_runtime_t runtime;
    host_security_t host = {10U, 0U, 0U, 0U, true, true, true};
    mw_receiver_handshake_security_t security = {
        true, true, true, MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1};

    init_ready_runtime(&runtime, 10U);
    CHECK(!mw_receiver_runtime_begin_handshake(
        &runtime, UINT32_C(0x99999999), 11U, 100U));
    CHECK(!mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, 10U, 100U));
    CHECK(!mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, UINT32_MAX, 100U));
    CHECK(mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, 11U, 100U));
    CHECK(runtime.state == MW_RECEIVER_HANDSHAKE_PENDING);

    security.application_handshake_authenticated = false;
    CHECK(!mw_receiver_runtime_complete_handshake(
        &runtime, &security, 101U, host_commit_session, &host));
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    CHECK(mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, 11U, 200U));
    mw_receiver_runtime_tick(
        &runtime, 200U + MW_RECEIVER_HANDSHAKE_TIMEOUT_MS);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);

    CHECK(mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, 11U, 2000U));
    security.application_handshake_authenticated = true;
    host.session_commit_allowed = false;
    CHECK(!mw_receiver_runtime_complete_handshake(
        &runtime, &security, 2001U, host_commit_session, &host));
    CHECK(runtime.state == MW_RECEIVER_FAULT);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    return 0;
}

static int check_protocol_negative_and_replay(void)
{
    mw_receiver_runtime_t runtime;
    mw_encrypted_frame_t frame;
    host_security_t host = {10U, 0U, 0U, 0U, true, true, true};
    uint32_t decrypt_calls;

    init_ready_runtime(&runtime, 10U);
    CHECK(open_session(&runtime, &host, 11U, 1000U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 11U, 1U, 1000U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1000U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    CHECK(runtime.replay_guard.receive_high_water == 1U);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    decrypt_calls = host.decrypt_calls;
    CHECK(receive(&runtime, &host, &frame, 1001U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);
    CHECK(host.decrypt_calls == decrypt_calls);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    CHECK(!mw_receiver_runtime_begin_handshake(
        &runtime, WAND_DEVICE_ID, 11U, 1002U));

    CHECK(open_session(&runtime, &host, 12U, 1100U));
    make_frame(&frame, MW_CMD_FEEDBACK, 12U, 1U, 1100U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1100U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);

    CHECK(open_session(&runtime, &host, 13U, 1200U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 13U, UINT32_MAX, 1200U,
               NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1200U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 14U, 1300U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 14U, 1U, 1301U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1300U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 15U, 1400U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 15U, 1U,
               1400U - MW_COMMAND_FRESHNESS_MS - 1U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1400U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 16U, 1500U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 16U, 1U, 1500U, NULL, 0U);
    frame.header.device_id = UINT32_C(0x88888888);
    CHECK(receive(&runtime, &host, &frame, 1500U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 17U, 1600U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 17U, 0U, 1600U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1600U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 18U, 1700U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 18U, 1U, 1700U, NULL, 0U);
    frame.tag[0] ^= UINT8_C(0x01);
    CHECK(receive(&runtime, &host, &frame, 1700U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 19U, 1800U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 18U, 1U, 1800U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 1800U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 20U, 1900U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 20U, 1U, 1900U, NULL, 0U);
    frame.header.flags = 1U;
    CHECK(receive(&runtime, &host, &frame, 1900U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 21U, 2000U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 21U, 1U, 2000U, NULL, 1U);
    CHECK(receive(&runtime, &host, &frame, 2000U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 22U, 2100U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 22U, 1U, 2100U, NULL, 0U);
    frame.header.command = UINT8_C(0x7F);
    CHECK(receive(&runtime, &host, &frame, 2100U) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);

    CHECK(open_session(&runtime, &host, 23U, 2200U));
    CHECK(mw_receiver_runtime_receive_frame(
              &runtime, NULL, 2200U, host_checked_noncrypto_decrypt, &host,
              host_commit_sequence, &host) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    CHECK(open_session(&runtime, &host, 24U, 2300U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 24U, 1U, 2300U, NULL, 0U);
    CHECK(mw_receiver_runtime_receive_frame(
              &runtime, &frame, 2300U, NULL, &host,
              host_commit_sequence, &host) ==
          MW_RECEIVER_FRAME_REJECTED_PROTOCOL);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    return 0;
}

static int check_non_actuating_gesture_and_release(void)
{
    mw_receiver_runtime_t runtime;
    mw_encrypted_frame_t frame;
    host_security_t host = {20U, 0U, 0U, 0U, true, true, true};
    const uint8_t gesture[2] = {
        (uint8_t)MW_GESTURE_CIRCLE_CW, UINT8_C(82)};
    const uint8_t pulse_200_ms[2] = {0U, UINT8_C(200)};

    init_ready_runtime(&runtime, 20U);
    CHECK(open_session(&runtime, &host, 21U, 2000U));

    make_frame(&frame, MW_CMD_GESTURE_EVENT, 21U, 1U, 2000U,
               gesture, 2U);
    CHECK(receive(&runtime, &host, &frame, 2000U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    CHECK(runtime.last_gesture_valid);
    CHECK(runtime.last_gesture_event.id == MW_GESTURE_CIRCLE_CW);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    make_frame(&frame, MW_CMD_ARM_LEASE, 21U, 2U, 2010U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 2010U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, MW_CMD_PULSE_LOW_SIDE, 21U, 3U, 2020U,
               pulse_200_ms, 2U);
    CHECK(receive(&runtime, &host, &frame, 2020U) ==
          MW_RECEIVER_FRAME_ACCEPTED_OUTPUT_POLICY);
    CHECK(mw_receiver_runtime_outputs(&runtime)->low_side_active);

    make_frame(&frame, MW_CMD_GESTURE_EVENT, 21U, 4U, 2030U,
               gesture, 2U);
    CHECK(receive(&runtime, &host, &frame, 2030U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    CHECK(mw_receiver_runtime_outputs(&runtime)->low_side_active);

    make_frame(&frame, MW_CMD_DISARM, 21U, 5U, 2040U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 2040U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    make_frame(&frame, MW_CMD_ARM_LEASE, 21U, 6U, 2050U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 2050U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, MW_CMD_PULSE_ISOLATED_OC, 21U, 7U, 2060U,
               pulse_200_ms, 2U);
    CHECK(receive(&runtime, &host, &frame, 2060U) ==
          MW_RECEIVER_FRAME_ACCEPTED_OUTPUT_POLICY);
    CHECK(mw_receiver_runtime_outputs(&runtime)->isolated_oc_active);
    mw_receiver_runtime_tick(&runtime, 2149U);
    CHECK(mw_receiver_runtime_outputs(&runtime)->isolated_oc_active);
    mw_receiver_runtime_tick(&runtime, 2150U);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    CHECK(runtime.state == MW_RECEIVER_SESSION_ACTIVE);

    mw_receiver_runtime_tick(&runtime, 2299U);
    CHECK(runtime.state == MW_RECEIVER_SESSION_ACTIVE);
    mw_receiver_runtime_tick(&runtime, 2300U);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    return 0;
}

static int check_fail_safe_fault_paths(void)
{
    mw_receiver_runtime_t runtime;
    mw_encrypted_frame_t frame;
    host_security_t host = {30U, 0U, 0U, 0U, true, true, true};
    const uint8_t pulse_10_ms[2] = {0U, UINT8_C(10)};

    init_ready_runtime(&runtime, 30U);
    CHECK(open_session(&runtime, &host, 31U, 3000U));
    make_frame(&frame, MW_CMD_PULSE_LOW_SIDE, 31U, 1U, 3000U,
               pulse_10_ms, 2U);
    CHECK(receive(&runtime, &host, &frame, 3000U) ==
          MW_RECEIVER_FRAME_REJECTED_APPLICATION);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    CHECK(open_session(&runtime, &host, 32U, 3100U));
    make_frame(&frame, MW_CMD_ARM_LEASE, 32U, 1U, 3100U, NULL, 0U);
    CHECK(receive(&runtime, &host, &frame, 3100U) ==
          MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION);
    make_frame(&frame, MW_CMD_PULSE_LOW_SIDE, 32U, 2U, 3110U,
               pulse_10_ms, 2U);
    CHECK(receive(&runtime, &host, &frame, 3110U) ==
          MW_RECEIVER_FRAME_ACCEPTED_OUTPUT_POLICY);
    CHECK(mw_receiver_runtime_outputs(&runtime)->low_side_active);
    mw_receiver_runtime_link_lost(&runtime);
    CHECK(runtime.state == MW_RECEIVER_WAIT_HANDSHAKE);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));

    CHECK(open_session(&runtime, &host, 33U, 3200U));
    make_frame(&frame, MW_CMD_HEARTBEAT, 33U, 1U, 3200U, NULL, 0U);
    host.sequence_commit_allowed = false;
    CHECK(receive(&runtime, &host, &frame, 3200U) ==
          MW_RECEIVER_FRAME_REJECTED_FAULT);
    CHECK(runtime.state == MW_RECEIVER_FAULT);
    CHECK(!runtime.session_storage_ready);
    CHECK(mw_receiver_runtime_outputs_safe(&runtime));
    return 0;
}

int main(void)
{
    CHECK(check_durable_session_window_contract() == 0);
    CHECK(check_board_authority_and_boot() == 0);
    CHECK(check_handshake_gate() == 0);
    CHECK(check_protocol_negative_and_replay() == 0);
    CHECK(check_non_actuating_gesture_and_release() == 0);
    CHECK(check_fail_safe_fault_paths() == 0);
    (void)puts("receiver runtime vectors passed; target crypto/HIL gates remain open");
    return 0;
}
