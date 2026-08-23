#ifndef MW_EFFECT_SCHEDULER_H
#define MW_EFFECT_SCHEDULER_H

#include "mw_effect_audio.h"
#include "mw_pattern_renderer.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_EFFECT_DEFAULT_VOLUME_PERCENT UINT8_C(35)
#define MW_EFFECT_DURATION_MS UINT32_C(900)
#define MW_EFFECT_DISCONNECT_PROMPT_MS UINT32_C(400)

typedef enum {
    MW_EFFECT_NONE = 0,
    MW_EFFECT_FIRE,
    MW_EFFECT_ICE,
    MW_EFFECT_EXPLOSION,
    MW_EFFECT_LIGHTNING,
    MW_EFFECT_SHIELD,
    MW_EFFECT_HEAL,
    MW_EFFECT_PORTAL,
    MW_EFFECT_ARCANE,
    MW_EFFECT_UNKNOWN,
    MW_EFFECT_PAIRING,
    MW_EFFECT_DISCONNECTED,
    MW_EFFECT_LOW_BATTERY,
    MW_EFFECT_FAULT
} mw_effect_id_t;

typedef enum {
    MW_EFFECT_SCHEDULER_IDLE = 0,
    MW_EFFECT_SCHEDULER_ACTIVE,
    MW_EFFECT_SCHEDULER_FAULT
} mw_effect_scheduler_state_t;

typedef struct {
    mw_effect_scheduler_state_t state;
    mw_effect_id_t active_effect;
    uint8_t active_channel;
    uint8_t connected_channels_mask;
    uint32_t effect_deadline_ms;
    bool display_ready;
    bool audio_ready;
    bool effect_timed;
    bool restore_connected_pending;
    mw_pattern_scene_t pattern;
    mw_audio_synth_t audio;
} mw_effect_scheduler_t;

mw_effect_id_t mw_effect_for_gesture(mw_gesture_id_t gesture_id);
mw_audio_cue_t mw_audio_cue_for_effect(mw_effect_id_t effect);
void mw_effect_scheduler_init(
    mw_effect_scheduler_t *scheduler,
    bool display_ready,
    bool audio_ready);
bool mw_effect_scheduler_pairing(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id);
bool mw_effect_scheduler_connected(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id);
void mw_effect_scheduler_disconnected(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id);
/* Remove a rejected channel without starting any display/audio effect. */
void mw_effect_scheduler_forget_channel_silent(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id);
bool mw_effect_scheduler_low_battery(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id,
    uint8_t battery_percent);
bool mw_effect_scheduler_gesture(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id,
    mw_gesture_id_t gesture_id,
    uint8_t confidence_percent,
    uint8_t battery_percent,
    bool battery_known,
    uint32_t now_ms);
void mw_effect_scheduler_unknown(
    mw_effect_scheduler_t *scheduler,
    uint8_t channel_id,
    uint32_t now_ms);
void mw_effect_scheduler_fault(mw_effect_scheduler_t *scheduler);
void mw_effect_scheduler_tick(
    mw_effect_scheduler_t *scheduler,
    uint32_t now_ms);

#ifdef __cplusplus
}
#endif

#endif
