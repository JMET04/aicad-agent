#include "mw_effect_scheduler.h"

#include <string.h>

static bool valid_channel(uint8_t channel_id)
{
    return channel_id < MW_PATTERN_LOGICAL_CHANNELS;
}

static bool deadline_reached(uint32_t now_ms, uint32_t deadline_ms)
{
    return (int32_t)(now_ms - deadline_ms) >= 0;
}

static uint8_t first_connected_channel(uint8_t mask)
{
    uint8_t channel;
    for (channel = 0U; channel < MW_PATTERN_LOGICAL_CHANNELS; ++channel) {
        if ((mask & (uint8_t)(UINT8_C(1) << channel)) != 0U) {
            return channel;
        }
    }
    return 0U;
}

mw_effect_id_t mw_effect_for_gesture(mw_gesture_id_t gesture_id)
{
    switch (gesture_id) {
    case MW_GESTURE_TAP:
        return MW_EFFECT_EXPLOSION;
    case MW_GESTURE_TWIST_CW:
        return MW_EFFECT_FIRE;
    case MW_GESTURE_TWIST_CCW:
        return MW_EFFECT_ICE;
    case MW_GESTURE_SWISH_LEFT:
        return MW_EFFECT_LIGHTNING;
    case MW_GESTURE_SWISH_RIGHT:
        return MW_EFFECT_SHIELD;
    case MW_GESTURE_THRUST:
        return MW_EFFECT_ARCANE;
    case MW_GESTURE_CIRCLE_CW:
        return MW_EFFECT_HEAL;
    case MW_GESTURE_CIRCLE_CCW:
        return MW_EFFECT_PORTAL;
    case MW_GESTURE_NONE:
    default:
        return MW_EFFECT_UNKNOWN;
    }
}

mw_audio_cue_t mw_audio_cue_for_effect(mw_effect_id_t effect)
{
    switch (effect) {
    case MW_EFFECT_FIRE:
        return MW_AUDIO_CUE_FIRE_WHOOSH_CRACKLE;
    case MW_EFFECT_ICE:
        return MW_AUDIO_CUE_ICE_CHIME_CRACK;
    case MW_EFFECT_EXPLOSION:
        return MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM;
    case MW_EFFECT_LIGHTNING:
        return MW_AUDIO_CUE_LIGHTNING_ZAP;
    case MW_EFFECT_SHIELD:
        return MW_AUDIO_CUE_SHIELD_SHIMMER;
    case MW_EFFECT_HEAL:
        return MW_AUDIO_CUE_HEAL_CHIME;
    case MW_EFFECT_PORTAL:
        return MW_AUDIO_CUE_PORTAL_WARP;
    case MW_EFFECT_ARCANE:
        return MW_AUDIO_CUE_ARCANE_PULSE;
    case MW_EFFECT_PAIRING:
        return MW_AUDIO_CUE_PAIRING;
    case MW_EFFECT_DISCONNECTED:
        return MW_AUDIO_CUE_DISCONNECTED;
    case MW_EFFECT_LOW_BATTERY:
        return MW_AUDIO_CUE_LOW_BATTERY;
    case MW_EFFECT_UNKNOWN:
        return MW_AUDIO_CUE_UNKNOWN;
    case MW_EFFECT_NONE:
    case MW_EFFECT_FAULT:
    default:
        return MW_AUDIO_CUE_NONE;
    }
}

static void maybe_start_audio(
    mw_effect_scheduler_t *scheduler,
    mw_effect_id_t effect)
{
    if (scheduler->audio_ready) {
        (void)mw_audio_synth_start(
            &scheduler->audio,
            mw_audio_cue_for_effect(effect),
            MW_EFFECT_DEFAULT_VOLUME_PERCENT);
    } else {
        mw_audio_synth_stop(&scheduler->audio);
    }
}

void mw_effect_scheduler_init(
    mw_effect_scheduler_t *scheduler,
    bool display_ready,
    bool audio_ready)
{
    if (scheduler == NULL) {
        return;
    }
    (void)memset(scheduler, 0, sizeof(*scheduler));
    scheduler->display_ready = display_ready;
    scheduler->audio_ready = audio_ready;
    scheduler->state = MW_EFFECT_SCHEDULER_IDLE;
    mw_pattern_scene_init(&scheduler->pattern);
    mw_audio_synth_init(&scheduler->audio);
}

bool mw_effect_scheduler_pairing(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id)
{
    if ((scheduler == NULL) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT) ||
        !mw_pattern_show_pairing(&scheduler->pattern, channel_id)) {
        return false;
    }
    scheduler->active_channel = channel_id;
    scheduler->active_effect = MW_EFFECT_PAIRING;
    scheduler->effect_timed = false;
    scheduler->restore_connected_pending = false;
    scheduler->state = MW_EFFECT_SCHEDULER_ACTIVE;
    scheduler->effect_deadline_ms = 0U;
    maybe_start_audio(scheduler, MW_EFFECT_PAIRING);
    return true;
}

bool mw_effect_scheduler_connected(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id)
{
    if ((scheduler == NULL) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT) ||
        !valid_channel(channel_id) ||
        !mw_pattern_show_connected(&scheduler->pattern, channel_id)) {
        return false;
    }
    scheduler->connected_channels_mask |=
        (uint8_t)(UINT8_C(1) << channel_id);
    scheduler->active_channel = channel_id;
    scheduler->active_effect = MW_EFFECT_NONE;
    scheduler->effect_timed = false;
    scheduler->restore_connected_pending = false;
    scheduler->state = MW_EFFECT_SCHEDULER_IDLE;
    scheduler->effect_deadline_ms = 0U;
    mw_audio_synth_stop(&scheduler->audio);
    return true;
}

void mw_effect_scheduler_disconnected(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id)
{
    if ((scheduler == NULL) || !valid_channel(channel_id) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT)) {
        return;
    }
    scheduler->connected_channels_mask &=
        (uint8_t)~(uint8_t)(UINT8_C(1) << channel_id);
    if ((scheduler->active_channel == channel_id) ||
        (scheduler->connected_channels_mask == 0U)) {
        scheduler->active_channel = channel_id;
        scheduler->active_effect = MW_EFFECT_DISCONNECTED;
        scheduler->effect_timed = false;
        scheduler->restore_connected_pending =
            scheduler->connected_channels_mask != 0U;
        scheduler->state = MW_EFFECT_SCHEDULER_ACTIVE;
        scheduler->effect_deadline_ms = 0U;
        mw_pattern_show_disconnected(&scheduler->pattern);
        maybe_start_audio(scheduler, MW_EFFECT_DISCONNECTED);
    }
}

void mw_effect_scheduler_forget_channel_silent(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id)
{
    if ((scheduler == NULL) || !valid_channel(channel_id) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT)) {
        return;
    }
    scheduler->connected_channels_mask &=
        (uint8_t)~(uint8_t)(UINT8_C(1) << channel_id);
    if ((scheduler->active_channel != channel_id) &&
        (scheduler->connected_channels_mask != 0U)) {
        return;
    }

    scheduler->active_effect = MW_EFFECT_NONE;
    scheduler->effect_timed = false;
    scheduler->restore_connected_pending = false;
    scheduler->state = MW_EFFECT_SCHEDULER_IDLE;
    scheduler->effect_deadline_ms = 0U;
    mw_audio_synth_stop(&scheduler->audio);
    if (scheduler->connected_channels_mask != 0U) {
        scheduler->active_channel =
            first_connected_channel(scheduler->connected_channels_mask);
        (void)mw_pattern_show_connected(
            &scheduler->pattern, scheduler->active_channel);
    } else {
        scheduler->active_channel = channel_id;
        mw_pattern_show_disconnected(&scheduler->pattern);
    }
}

bool mw_effect_scheduler_low_battery(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id,
    uint8_t battery_percent)
{
    if ((scheduler == NULL) || !valid_channel(channel_id) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT) ||
        (battery_percent > MW_PATTERN_LOW_BATTERY_PERCENT)) {
        return false;
    }
    scheduler->active_channel = channel_id;
    scheduler->active_effect = MW_EFFECT_LOW_BATTERY;
    scheduler->effect_timed = false;
    scheduler->restore_connected_pending = false;
    scheduler->state = MW_EFFECT_SCHEDULER_ACTIVE;
    scheduler->effect_deadline_ms = 0U;
    (void)mw_pattern_set_battery(&scheduler->pattern, battery_percent);
    maybe_start_audio(scheduler, MW_EFFECT_LOW_BATTERY);
    return true;
}

bool mw_effect_scheduler_gesture(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id,
    mw_gesture_id_t gesture_id,
    uint8_t confidence_percent,
    uint8_t battery_percent,
    bool battery_known,
    uint32_t now_ms)
{
    mw_effect_id_t effect;

    if ((scheduler == NULL) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT) ||
        !valid_channel(channel_id) ||
        (battery_known && (battery_percent > UINT8_C(100)))) {
        return false;
    }
    if (battery_known &&
        (battery_percent <= MW_PATTERN_LOW_BATTERY_PERCENT)) {
        return mw_effect_scheduler_low_battery(
            scheduler, channel_id, battery_percent);
    }
    effect = mw_effect_for_gesture(gesture_id);
    if ((effect == MW_EFFECT_UNKNOWN) ||
        !mw_pattern_show_gesture(
            &scheduler->pattern, channel_id, gesture_id,
            confidence_percent)) {
        mw_effect_scheduler_unknown(scheduler, channel_id, now_ms);
        return false;
    }

    scheduler->active_channel = channel_id;
    scheduler->active_effect = effect;
    scheduler->effect_timed = true;
    scheduler->restore_connected_pending = false;
    scheduler->state = MW_EFFECT_SCHEDULER_ACTIVE;
    scheduler->effect_deadline_ms = now_ms + MW_EFFECT_DURATION_MS;
    maybe_start_audio(scheduler, effect);
    return true;
}

void mw_effect_scheduler_unknown(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id,
    uint32_t now_ms)
{
    if ((scheduler == NULL) ||
        (scheduler->state == MW_EFFECT_SCHEDULER_FAULT)) {
        return;
    }
    scheduler->active_channel = valid_channel(channel_id) ? channel_id : 0U;
    scheduler->active_effect = MW_EFFECT_UNKNOWN;
    scheduler->effect_timed = true;
    scheduler->restore_connected_pending = false;
    scheduler->state = MW_EFFECT_SCHEDULER_ACTIVE;
    scheduler->effect_deadline_ms = now_ms + MW_EFFECT_DURATION_MS;
    mw_pattern_show_unknown(&scheduler->pattern, channel_id);
    maybe_start_audio(scheduler, MW_EFFECT_UNKNOWN);
}

void mw_effect_scheduler_fault(mw_effect_scheduler_t *scheduler)
{
    if (scheduler == NULL) {
        return;
    }
    scheduler->state = MW_EFFECT_SCHEDULER_FAULT;
    scheduler->active_effect = MW_EFFECT_FAULT;
    scheduler->connected_channels_mask = 0U;
    scheduler->effect_timed = false;
    scheduler->restore_connected_pending = false;
    scheduler->effect_deadline_ms = 0U;
    mw_pattern_show_fault(&scheduler->pattern);
    mw_audio_synth_stop(&scheduler->audio);
}

void mw_effect_scheduler_tick(
    mw_effect_scheduler_t *scheduler,
    uint32_t now_ms)
{
    if (scheduler == NULL) {
        return;
    }
    mw_pattern_tick(&scheduler->pattern, now_ms);
    if ((scheduler->state == MW_EFFECT_SCHEDULER_ACTIVE) &&
        (scheduler->active_effect == MW_EFFECT_DISCONNECTED) &&
        scheduler->restore_connected_pending) {
        scheduler->restore_connected_pending = false;
        scheduler->effect_timed = true;
        scheduler->effect_deadline_ms =
            now_ms + MW_EFFECT_DISCONNECT_PROMPT_MS;
    }
    if ((scheduler->state == MW_EFFECT_SCHEDULER_ACTIVE) &&
        scheduler->effect_timed &&
        deadline_reached(now_ms, scheduler->effect_deadline_ms)) {
        scheduler->effect_deadline_ms = 0U;
        scheduler->active_effect = MW_EFFECT_NONE;
        scheduler->effect_timed = false;
        scheduler->restore_connected_pending = false;
        scheduler->state = MW_EFFECT_SCHEDULER_IDLE;
        mw_audio_synth_stop(&scheduler->audio);
        if (scheduler->connected_channels_mask != 0U) {
            scheduler->active_channel =
                first_connected_channel(scheduler->connected_channels_mask);
            (void)mw_pattern_show_connected(
                &scheduler->pattern, scheduler->active_channel);
        } else {
            mw_pattern_show_disconnected(&scheduler->pattern);
        }
    }
}
