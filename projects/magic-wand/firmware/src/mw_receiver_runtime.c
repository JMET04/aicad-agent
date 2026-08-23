#include "mw_receiver_runtime.h"

#include <string.h>

static bool deadline_reached(uint32_t now_ms, uint32_t deadline_ms)
{
    return ((int32_t)(now_ms - deadline_ms) >= 0);
}

static void clear_session_fields(mw_receiver_runtime_t *runtime)
{
    runtime->pending_session_id = 0U;
    runtime->active_session_id = 0U;
    runtime->handshake_deadline_ms = 0U;
    runtime->heartbeat_deadline_ms = 0U;
    runtime->negotiated_gesture_profile =
        MW_GESTURE_PAYLOAD_PROFILE_UNSUPPORTED;
    runtime->last_gesture_valid = false;
    runtime->last_gesture_v2_valid = false;
    (void)memset(&runtime->last_gesture_event, 0,
                 sizeof(runtime->last_gesture_event));
    (void)memset(&runtime->last_gesture_event_v2, 0,
                 sizeof(runtime->last_gesture_event_v2));
    (void)memset(&runtime->replay_guard, 0, sizeof(runtime->replay_guard));
}

static void close_session_safe(
    mw_receiver_runtime_t *runtime,
    mw_receiver_runtime_state_t next_state)
{
    mw_state_machine_link_lost(&runtime->output_policy);
    clear_session_fields(runtime);
    runtime->state = next_state;
}

void mw_receiver_runtime_init(
    mw_receiver_runtime_t *runtime,
    uint32_t local_device_id,
    uint32_t paired_wand_device_id,
    uint32_t persisted_session_id,
    bool session_storage_ready)
{
    if (runtime == NULL) {
        return;
    }

    (void)memset(runtime, 0, sizeof(*runtime));
    mw_state_machine_init(&runtime->output_policy, MW_ROLE_RECEIVER);
    runtime->state = MW_RECEIVER_BOOT_SAFE;
    runtime->local_device_id = local_device_id;
    runtime->paired_wand_device_id = paired_wand_device_id;
    runtime->last_committed_session_id = persisted_session_id;
    runtime->session_storage_ready = session_storage_ready;

    if ((local_device_id == 0U) || (paired_wand_device_id == 0U) ||
        (local_device_id == paired_wand_device_id) ||
        !session_storage_ready) {
        mw_receiver_runtime_fault(runtime);
    }
}

void mw_receiver_runtime_boot_complete(
    mw_receiver_runtime_t *runtime,
    bool target_self_test_passed,
    bool power_good,
    bool credentials_ready)
{
    if ((runtime == NULL) || (runtime->state == MW_RECEIVER_FAULT)) {
        return;
    }

    runtime->power_good = power_good;
    runtime->credentials_ready = credentials_ready;
    if (!target_self_test_passed || !power_good ||
        !runtime->session_storage_ready) {
        mw_receiver_runtime_fault(runtime);
        return;
    }

    mw_state_machine_boot_complete(&runtime->output_policy,
                                   credentials_ready);
    clear_session_fields(runtime);
    runtime->state = credentials_ready ? MW_RECEIVER_WAIT_HANDSHAKE :
        MW_RECEIVER_UNPROVISIONED;
}

bool mw_receiver_runtime_begin_handshake(
    mw_receiver_runtime_t *runtime,
    uint32_t peer_device_id,
    uint32_t session_id,
    uint32_t now_ms)
{
    if ((runtime == NULL) ||
        (runtime->state != MW_RECEIVER_WAIT_HANDSHAKE) ||
        !runtime->power_good || !runtime->session_storage_ready ||
        (peer_device_id != runtime->paired_wand_device_id) ||
        !runtime->credentials_ready ||
        (session_id == 0U) || (session_id == UINT32_MAX) ||
        (session_id <= runtime->last_committed_session_id)) {
        return false;
    }

    mw_state_machine_link_lost(&runtime->output_policy);
    runtime->pending_session_id = session_id;
    runtime->handshake_deadline_ms =
        now_ms + MW_RECEIVER_HANDSHAKE_TIMEOUT_MS;
    runtime->state = MW_RECEIVER_HANDSHAKE_PENDING;
    return true;
}

bool mw_receiver_runtime_complete_handshake(
    mw_receiver_runtime_t *runtime,
    const mw_receiver_handshake_security_t *security,
    uint32_t now_ms,
    mw_commit_session_epoch_fn commit_session_epoch,
    void *session_persistence_context)
{
    if ((runtime == NULL) ||
        (runtime->state != MW_RECEIVER_HANDSHAKE_PENDING) ||
        (security == NULL)) {
        return false;
    }

    if (deadline_reached(now_ms, runtime->handshake_deadline_ms) ||
        !security->secure_link_authenticated ||
        !security->application_handshake_authenticated ||
        !security->direction_specific_traffic_key_ready ||
        ((security->gesture_profile !=
          MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1) &&
         (security->gesture_profile !=
          MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2))) {
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return false;
    }

    if ((commit_session_epoch == NULL) ||
        !commit_session_epoch(session_persistence_context,
                              runtime->pending_session_id)) {
        runtime->session_storage_ready = false;
        mw_receiver_runtime_fault(runtime);
        return false;
    }

    runtime->last_committed_session_id = runtime->pending_session_id;
    runtime->active_session_id = runtime->pending_session_id;
    runtime->negotiated_gesture_profile = security->gesture_profile;
    runtime->pending_session_id = 0U;
    runtime->handshake_deadline_ms = 0U;
    runtime->heartbeat_deadline_ms = now_ms + MW_LINK_LOSS_MS;
    runtime->last_gesture_valid = false;
    runtime->last_gesture_v2_valid = false;
    mw_replay_guard_init(
        &runtime->replay_guard,
        runtime->paired_wand_device_id,
        runtime->active_session_id,
        0U,
        true);
    if (!mw_replay_guard_set_gesture_profile(
            &runtime->replay_guard, security->gesture_profile)) {
        runtime->session_storage_ready = false;
        mw_receiver_runtime_fault(runtime);
        return false;
    }
    mw_state_machine_link_lost(&runtime->output_policy);
    runtime->state = MW_RECEIVER_SESSION_ACTIVE;
    return true;
}

bool mw_receiver_runtime_bind_durable_session_window(
    mw_receiver_runtime_t *runtime,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling)
{
    if (runtime == NULL) {
        return false;
    }
    if (runtime->state != MW_RECEIVER_SESSION_ACTIVE) {
        return false;
    }

    if (!runtime->session_storage_ready || !runtime->power_good ||
        !runtime->credentials_ready ||
        (runtime->active_session_id != durable_session_id) ||
        (runtime->last_committed_session_id != durable_session_id) ||
        (runtime->replay_guard.expected_device_id !=
         runtime->paired_wand_device_id) ||
        (runtime->replay_guard.expected_session_id !=
         durable_session_id) ||
        (runtime->replay_guard.gesture_payload_profile !=
         runtime->negotiated_gesture_profile) ||
        !mw_replay_guard_bind_durable_session_window(
            &runtime->replay_guard,
            durable_session_id,
            reserved_sequence_ceiling)) {
        mw_receiver_runtime_fault(runtime);
        return false;
    }
    return true;
}

static uint16_t get_u16_be(const uint8_t input[2])
{
    return (uint16_t)(((uint16_t)input[0] << 8) | (uint16_t)input[1]);
}

mw_receiver_frame_result_t mw_receiver_runtime_receive_frame(
    mw_receiver_runtime_t *runtime,
    const mw_encrypted_frame_t *frame,
    uint32_t now_ms,
    mw_ccm_decrypt_fn decrypt,
    void *decrypt_context,
    mw_commit_high_water_fn commit_high_water,
    void *sequence_persistence_context)
{
    uint8_t plaintext[MW_MAX_PAYLOAD_BYTES] = {0};
    mw_command_t command;
    uint16_t argument = 0U;
    bool accepted;

    if (runtime == NULL) {
        return MW_RECEIVER_FRAME_REJECTED_FAULT;
    }
    if (runtime->state == MW_RECEIVER_FAULT) {
        return MW_RECEIVER_FRAME_REJECTED_FAULT;
    }

    mw_receiver_runtime_tick(runtime, now_ms);
    if (runtime->state != MW_RECEIVER_SESSION_ACTIVE) {
        return MW_RECEIVER_FRAME_REJECTED_NO_SESSION;
    }
    if (frame == NULL) {
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return MW_RECEIVER_FRAME_REJECTED_PROTOCOL;
    }

    accepted = mw_protocol_accept_and_decrypt(
        &runtime->replay_guard,
        frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        now_ms,
        decrypt,
        decrypt_context,
        commit_high_water,
        sequence_persistence_context,
        plaintext);
    if (!accepted) {
        if (!runtime->replay_guard.persistence_ready) {
            runtime->session_storage_ready = false;
            mw_receiver_runtime_fault(runtime);
            return MW_RECEIVER_FRAME_REJECTED_FAULT;
        }
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return MW_RECEIVER_FRAME_REJECTED_PROTOCOL;
    }

    command = (mw_command_t)frame->header.command;
    if (command == MW_CMD_GESTURE_EVENT) {
        mw_gesture_result_t event;
        mw_gesture_event_v2_t event_v2;
        bool event_valid = false;

        runtime->last_gesture_valid = false;
        runtime->last_gesture_v2_valid = false;
        if ((runtime->negotiated_gesture_profile ==
             MW_GESTURE_PAYLOAD_PROFILE_LEGACY_V1) &&
            ((size_t)frame->header.payload_length ==
             MW_GESTURE_EVENT_PAYLOAD_BYTES)) {
            event_valid = mw_gesture_decode_event(plaintext, &event);
        } else if ((runtime->negotiated_gesture_profile ==
                    MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2) &&
                   ((size_t)frame->header.payload_length ==
                    MW_GESTURE_EVENT_V2_BYTES)) {
            event_valid = mw_gesture_event_v2_decode(plaintext, &event_v2) &&
                (event_v2.device_id == frame->header.device_id) &&
                (event_v2.session_id == frame->header.session_id);
            if (event_valid) {
                event.id = event_v2.gesture_id;
                event.confidence_percent = event_v2.confidence_percent;
                event.rejected = false;
                runtime->last_gesture_event_v2 = event_v2;
                runtime->last_gesture_v2_valid = true;
            }
        }
        if (!event_valid) {
            (void)memset(plaintext, 0, sizeof(plaintext));
            close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
            return MW_RECEIVER_FRAME_REJECTED_APPLICATION;
        }
        runtime->last_gesture_event = event;
        runtime->last_gesture_valid = true;
        (void)memset(plaintext, 0, sizeof(plaintext));
        return MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION;
    }

    switch (command) {
    case MW_CMD_DISARM:
    case MW_CMD_HEARTBEAT:
    case MW_CMD_ARM_LEASE:
        argument = 0U;
        break;
    case MW_CMD_SET_AUX:
        argument = (uint16_t)plaintext[0];
        break;
    case MW_CMD_PULSE_ISOLATED_OC:
    case MW_CMD_PULSE_LOW_SIDE:
        argument = get_u16_be(plaintext);
        break;
    case MW_CMD_FEEDBACK:
    case MW_CMD_GESTURE_EVENT:
    default:
        (void)memset(plaintext, 0, sizeof(plaintext));
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return MW_RECEIVER_FRAME_REJECTED_APPLICATION;
    }

    accepted = mw_state_machine_receiver_command(
        &runtime->output_policy,
        command,
        argument,
        now_ms);
    (void)memset(plaintext, 0, sizeof(plaintext));
    if (!accepted) {
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return MW_RECEIVER_FRAME_REJECTED_APPLICATION;
    }

    if ((command == MW_CMD_HEARTBEAT) ||
        (command == MW_CMD_ARM_LEASE)) {
        runtime->heartbeat_deadline_ms = now_ms + MW_LINK_LOSS_MS;
    }
    if ((command == MW_CMD_DISARM) ||
        (command == MW_CMD_HEARTBEAT) ||
        (command == MW_CMD_ARM_LEASE)) {
        return MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION;
    }
    return MW_RECEIVER_FRAME_ACCEPTED_OUTPUT_POLICY;
}

void mw_receiver_runtime_tick(
    mw_receiver_runtime_t *runtime,
    uint32_t now_ms)
{
    if ((runtime == NULL) || (runtime->state == MW_RECEIVER_FAULT)) {
        return;
    }

    if ((runtime->state == MW_RECEIVER_HANDSHAKE_PENDING) &&
        deadline_reached(now_ms, runtime->handshake_deadline_ms)) {
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return;
    }
    if ((runtime->state == MW_RECEIVER_SESSION_ACTIVE) &&
        deadline_reached(now_ms, runtime->heartbeat_deadline_ms)) {
        close_session_safe(runtime, MW_RECEIVER_WAIT_HANDSHAKE);
        return;
    }

    mw_state_machine_tick(&runtime->output_policy, now_ms);
}

void mw_receiver_runtime_link_lost(mw_receiver_runtime_t *runtime)
{
    if ((runtime == NULL) || (runtime->state == MW_RECEIVER_FAULT)) {
        return;
    }
    close_session_safe(runtime, runtime->credentials_ready ?
        MW_RECEIVER_WAIT_HANDSHAKE : MW_RECEIVER_UNPROVISIONED);
}

void mw_receiver_runtime_power_good_changed(
    mw_receiver_runtime_t *runtime,
    bool power_good)
{
    if (runtime == NULL) {
        return;
    }
    runtime->power_good = power_good;
    if (!power_good) {
        mw_receiver_runtime_fault(runtime);
    }
}

void mw_receiver_runtime_fault(mw_receiver_runtime_t *runtime)
{
    if (runtime == NULL) {
        return;
    }
    mw_state_machine_fault(&runtime->output_policy);
    clear_session_fields(runtime);
    runtime->state = MW_RECEIVER_FAULT;
}

bool mw_receiver_runtime_outputs_safe(const mw_receiver_runtime_t *runtime)
{
    if (runtime == NULL) {
        return true;
    }
    return mw_state_machine_outputs_safe(&runtime->output_policy);
}

const mw_output_state_t *mw_receiver_runtime_outputs(
    const mw_receiver_runtime_t *runtime)
{
    static const mw_output_state_t safe_outputs = {false, false, false};
    if (runtime == NULL) {
        return &safe_outputs;
    }
    return &runtime->output_policy.outputs;
}
