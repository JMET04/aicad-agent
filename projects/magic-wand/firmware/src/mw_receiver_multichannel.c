#include "mw_receiver_multichannel.h"

#include <string.h>

static bool valid_channel(uint8_t logical_channel)
{
    return logical_channel < MW_RECEIVER_LOGICAL_CHANNELS;
}

static mw_receiver_channel_slot_t *configured_slot(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel)
{
    if ((manager == NULL) || !valid_channel(logical_channel) ||
        !manager->channels[logical_channel].configured) {
        return NULL;
    }
    return &manager->channels[logical_channel];
}

static void release_owner_if_safe(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel)
{
    if ((manager != NULL) &&
        (manager->output_owner == (int8_t)logical_channel) &&
        mw_receiver_runtime_outputs_safe(
            &manager->channels[logical_channel].runtime)) {
        manager->output_owner = MW_RECEIVER_NO_OUTPUT_OWNER;
    }
}

void mw_receiver_multichannel_init(
    mw_receiver_multichannel_t *manager,
    uint32_t local_device_id)
{
    if (manager == NULL) {
        return;
    }
    (void)memset(manager, 0, sizeof(*manager));
    manager->local_device_id = local_device_id;
    manager->output_owner = MW_RECEIVER_NO_OUTPUT_OWNER;
    mw_effect_scheduler_init(&manager->effects, false, false);
}

bool mw_receiver_multichannel_set_effect_readiness(
    mw_receiver_multichannel_t *manager,
    bool display_ready,
    bool audio_ready)
{
    if ((manager == NULL) ||
        (mw_receiver_multichannel_active_sessions(manager) != 0U)) {
        return false;
    }
    mw_effect_scheduler_init(&manager->effects, display_ready, audio_ready);
    return true;
}

bool mw_receiver_multichannel_set_output_authority(
    mw_receiver_multichannel_t *manager,
    bool enabled)
{
    if ((manager == NULL) ||
        (mw_receiver_multichannel_active_sessions(manager) != 0U)) {
        return false;
    }
    manager->dangerous_output_authority_enabled = enabled;
    return true;
}

bool mw_receiver_multichannel_configure(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    uint32_t peer_device_id,
    uint32_t persisted_session_id,
    bool session_storage_ready)
{
    uint8_t index;
    mw_receiver_channel_slot_t *slot;

    if ((manager == NULL) || (manager->local_device_id == 0U) ||
        !valid_channel(logical_channel) || (peer_device_id == 0U) ||
        (peer_device_id == manager->local_device_id) ||
        manager->channels[logical_channel].configured) {
        return false;
    }
    for (index = 0U; index < MW_RECEIVER_LOGICAL_CHANNELS; ++index) {
        if (manager->channels[index].configured &&
            (manager->channels[index].peer_device_id == peer_device_id)) {
            return false;
        }
    }

    slot = &manager->channels[logical_channel];
    slot->configured = true;
    slot->logical_channel = logical_channel;
    slot->peer_device_id = peer_device_id;
    mw_receiver_runtime_init(
        &slot->runtime, manager->local_device_id, peer_device_id,
        persisted_session_id, session_storage_ready);
    if (slot->runtime.state == MW_RECEIVER_FAULT) {
        (void)memset(slot, 0, sizeof(*slot));
        return false;
    }
    return true;
}

bool mw_receiver_multichannel_boot_channel(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    bool target_self_test_passed,
    bool power_good,
    bool credentials_ready)
{
    mw_receiver_channel_slot_t *slot =
        configured_slot(manager, logical_channel);
    if (slot == NULL) {
        return false;
    }
    mw_receiver_runtime_boot_complete(
        &slot->runtime, target_self_test_passed, power_good,
        credentials_ready);
    return slot->runtime.state == MW_RECEIVER_WAIT_HANDSHAKE;
}

bool mw_receiver_multichannel_begin_handshake(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    uint32_t peer_device_id,
    uint32_t session_id,
    uint32_t now_ms)
{
    mw_receiver_channel_slot_t *slot =
        configured_slot(manager, logical_channel);
    if ((slot != NULL) &&
        mw_receiver_runtime_begin_handshake(
            &slot->runtime, peer_device_id, session_id, now_ms)) {
        (void)mw_effect_scheduler_pairing(
            &manager->effects, logical_channel);
        return true;
    }
    return false;
}

bool mw_receiver_multichannel_complete_handshake(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    const mw_receiver_handshake_security_t *security,
    uint32_t now_ms,
    mw_commit_session_epoch_fn commit_session_epoch,
    void *session_persistence_context)
{
    mw_receiver_channel_slot_t *slot =
        configured_slot(manager, logical_channel);
    if (slot == NULL) {
        return false;
    }
    if ((security == NULL) ||
        ((logical_channel != 0U) &&
         (security->gesture_profile !=
          MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2))) {
        if (slot->runtime.state == MW_RECEIVER_HANDSHAKE_PENDING) {
            mw_receiver_runtime_link_lost(&slot->runtime);
            mw_effect_scheduler_disconnected(
                &manager->effects, logical_channel);
        }
        return false;
    }
    if (mw_receiver_runtime_complete_handshake(
            &slot->runtime, security, now_ms, commit_session_epoch,
            session_persistence_context)) {
        (void)mw_effect_scheduler_connected(
            &manager->effects, logical_channel);
        return true;
    }
    mw_effect_scheduler_disconnected(&manager->effects, logical_channel);
    return false;
}

bool mw_receiver_multichannel_bind_durable_session_window(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling)
{
    mw_receiver_channel_slot_t *slot =
        configured_slot(manager, logical_channel);
    bool was_active;

    if (slot == NULL) {
        return false;
    }
    was_active = slot->runtime.state == MW_RECEIVER_SESSION_ACTIVE;
    if (mw_receiver_runtime_bind_durable_session_window(
            &slot->runtime,
            durable_session_id,
            reserved_sequence_ceiling)) {
        return true;
    }
    if (was_active) {
        mw_effect_scheduler_disconnected(
            &manager->effects, logical_channel);
        release_owner_if_safe(manager, logical_channel);
    }
    return false;
}

mw_receiver_channel_result_t mw_receiver_multichannel_receive(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    const mw_encrypted_frame_t *frame,
    uint32_t now_ms,
    mw_ccm_decrypt_fn decrypt,
    void *decrypt_context,
    mw_commit_high_water_fn commit_high_water,
    void *sequence_persistence_context)
{
    mw_receiver_channel_slot_t *slot =
        configured_slot(manager, logical_channel);
    mw_receiver_frame_result_t runtime_result;

    if (slot == NULL) {
        return MW_RECEIVER_CHANNEL_REJECTED_NOT_CONFIGURED;
    }
    runtime_result = mw_receiver_runtime_receive_frame(
        &slot->runtime, frame, now_ms, decrypt, decrypt_context,
        commit_high_water, sequence_persistence_context);

    if ((runtime_result == MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION) &&
        (frame != NULL) &&
        (frame->header.command == (uint8_t)MW_CMD_GESTURE_EVENT)) {
        bool binding_valid = false;
        if (slot->runtime.last_gesture_v2_valid) {
            binding_valid =
                slot->runtime.last_gesture_event_v2.logical_channel ==
                    logical_channel;
        } else if (slot->runtime.last_gesture_valid) {
            /* Legacy events are compatibility-only on logical channel zero. */
            binding_valid = logical_channel == 0U;
        }
        if (!binding_valid) {
            mw_receiver_runtime_link_lost(&slot->runtime);
            mw_effect_scheduler_disconnected(
                &manager->effects, logical_channel);
            release_owner_if_safe(manager, logical_channel);
            return MW_RECEIVER_CHANNEL_REJECTED_BINDING;
        }

        if (slot->runtime.last_gesture_v2_valid &&
            ((slot->runtime.last_gesture_event_v2.status_flags &
              MW_EVENT_STATUS_ARM_ACTIVE) == 0U)) {
            /*
             * V2 media requires the authenticated physical-arm assertion.
             * Revoke the slot silently: an unauthorised gesture must not
             * replace an effect already owned by another valid channel or
             * start a disconnect cue of its own.
             */
            mw_receiver_runtime_link_lost(&slot->runtime);
            mw_effect_scheduler_forget_channel_silent(
                &manager->effects, logical_channel);
            release_owner_if_safe(manager, logical_channel);
            return MW_RECEIVER_CHANNEL_REJECTED_ARM_INACTIVE;
        }

        if (slot->runtime.last_gesture_v2_valid) {
            const mw_gesture_event_v2_t *event =
                &slot->runtime.last_gesture_event_v2;
            const bool battery_known =
                (event->status_flags &
                 MW_EVENT_STATUS_BATTERY_KNOWN) != 0U;
            (void)mw_effect_scheduler_gesture(
                &manager->effects,
                logical_channel,
                event->gesture_id,
                event->confidence_percent,
                event->battery_percent,
                battery_known,
                now_ms);
        } else {
            (void)mw_effect_scheduler_gesture(
                &manager->effects,
                logical_channel,
                slot->runtime.last_gesture_event.id,
                slot->runtime.last_gesture_event.confidence_percent,
                MW_BATTERY_PERCENT_UNKNOWN,
                false,
                now_ms);
        }
    }

    if (runtime_result == MW_RECEIVER_FRAME_ACCEPTED_OUTPUT_POLICY) {
        if (!manager->dangerous_output_authority_enabled) {
            mw_receiver_runtime_link_lost(&slot->runtime);
            mw_effect_scheduler_disconnected(
                &manager->effects, logical_channel);
            release_owner_if_safe(manager, logical_channel);
            return MW_RECEIVER_CHANNEL_REJECTED_OUTPUT_DISABLED;
        }
        if (!mw_receiver_runtime_outputs_safe(&slot->runtime)) {
            if (manager->output_owner == MW_RECEIVER_NO_OUTPUT_OWNER) {
                manager->output_owner = (int8_t)logical_channel;
            } else if (manager->output_owner != (int8_t)logical_channel) {
                mw_receiver_runtime_link_lost(&slot->runtime);
                mw_effect_scheduler_disconnected(
                    &manager->effects, logical_channel);
                return MW_RECEIVER_CHANNEL_REJECTED_OUTPUT_CONFLICT;
            }
        }
        release_owner_if_safe(manager, logical_channel);
        return MW_RECEIVER_CHANNEL_ACCEPTED_OUTPUT_POLICY;
    }

    release_owner_if_safe(manager, logical_channel);
    if ((runtime_result != MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION) &&
        (slot->runtime.state != MW_RECEIVER_SESSION_ACTIVE)) {
        mw_effect_scheduler_disconnected(
            &manager->effects, logical_channel);
    }
    if (runtime_result == MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION) {
        return MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION;
    }
    return MW_RECEIVER_CHANNEL_REJECTED_RUNTIME;
}

void mw_receiver_multichannel_tick(
    mw_receiver_multichannel_t *manager,
    uint32_t now_ms)
{
    uint8_t index;
    if (manager == NULL) {
        return;
    }
    for (index = 0U; index < MW_RECEIVER_LOGICAL_CHANNELS; ++index) {
        if (manager->channels[index].configured) {
            const mw_receiver_runtime_state_t previous_state =
                manager->channels[index].runtime.state;
            const bool was_link_tracked =
                (previous_state == MW_RECEIVER_SESSION_ACTIVE) ||
                (previous_state == MW_RECEIVER_HANDSHAKE_PENDING);
            mw_receiver_runtime_tick(
                &manager->channels[index].runtime, now_ms);
            if (was_link_tracked &&
                (manager->channels[index].runtime.state !=
                 MW_RECEIVER_SESSION_ACTIVE) &&
                (manager->channels[index].runtime.state !=
                 MW_RECEIVER_HANDSHAKE_PENDING)) {
                mw_effect_scheduler_disconnected(
                    &manager->effects, index);
            }
            release_owner_if_safe(manager, index);
        }
    }
    mw_effect_scheduler_tick(&manager->effects, now_ms);
}

void mw_receiver_multichannel_link_lost(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel)
{
    mw_receiver_channel_slot_t *slot =
        configured_slot(manager, logical_channel);
    if (slot == NULL) {
        return;
    }
    mw_receiver_runtime_link_lost(&slot->runtime);
    mw_effect_scheduler_disconnected(&manager->effects, logical_channel);
    release_owner_if_safe(manager, logical_channel);
}

const mw_output_state_t *mw_receiver_multichannel_outputs(
    const mw_receiver_multichannel_t *manager)
{
    static const mw_output_state_t safe_outputs = {false, false, false};
    uint8_t owner;

    if ((manager == NULL) ||
        (manager->output_owner == MW_RECEIVER_NO_OUTPUT_OWNER)) {
        return &safe_outputs;
    }
    owner = (uint8_t)manager->output_owner;
    if (!valid_channel(owner) || !manager->channels[owner].configured ||
        mw_receiver_runtime_outputs_safe(
            &manager->channels[owner].runtime)) {
        return &safe_outputs;
    }
    return mw_receiver_runtime_outputs(&manager->channels[owner].runtime);
}

size_t mw_receiver_multichannel_active_sessions(
    const mw_receiver_multichannel_t *manager)
{
    uint8_t index;
    size_t count = 0U;
    if (manager == NULL) {
        return 0U;
    }
    for (index = 0U; index < MW_RECEIVER_LOGICAL_CHANNELS; ++index) {
        if (manager->channels[index].configured &&
            (manager->channels[index].runtime.state ==
             MW_RECEIVER_SESSION_ACTIVE)) {
            ++count;
        }
    }
    return count;
}
