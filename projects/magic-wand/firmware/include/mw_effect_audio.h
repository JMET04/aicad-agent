#ifndef MW_EFFECT_AUDIO_H
#define MW_EFFECT_AUDIO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_AUDIO_SAMPLE_RATE_HZ UINT32_C(16000)
#define MW_AUDIO_MASTER_VOLUME_LIMIT_PERCENT UINT8_C(40)
#define MW_AUDIO_BOOM_VOLUME_LIMIT_PERCENT UINT8_C(25)
#define MW_AUDIO_OUTPUT_ABS_LIMIT INT16_C(12000)
#define MW_AUDIO_BOOM_ABS_LIMIT INT16_C(7000)

typedef enum {
    MW_AUDIO_CUE_NONE = 0,
    MW_AUDIO_CUE_FIRE_WHOOSH_CRACKLE,
    MW_AUDIO_CUE_ICE_CHIME_CRACK,
    MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM,
    MW_AUDIO_CUE_LIGHTNING_ZAP,
    MW_AUDIO_CUE_SHIELD_SHIMMER,
    MW_AUDIO_CUE_HEAL_CHIME,
    MW_AUDIO_CUE_PORTAL_WARP,
    MW_AUDIO_CUE_ARCANE_PULSE,
    MW_AUDIO_CUE_PAIRING,
    MW_AUDIO_CUE_DISCONNECTED,
    MW_AUDIO_CUE_LOW_BATTERY,
    MW_AUDIO_CUE_UNKNOWN
} mw_audio_cue_t;

typedef struct {
    mw_audio_cue_t cue;
    uint32_t sample_index;
    uint32_t total_samples;
    uint32_t noise_state;
    uint8_t requested_volume_percent;
    uint8_t applied_volume_percent;
    bool active;
    bool mute_required;
} mw_audio_synth_t;

void mw_audio_synth_init(mw_audio_synth_t *synth);
bool mw_audio_synth_start(
    mw_audio_synth_t *synth,
    mw_audio_cue_t cue,
    uint8_t requested_volume_percent);
void mw_audio_synth_stop(mw_audio_synth_t *synth);
bool mw_audio_synth_render(
    mw_audio_synth_t *synth,
    int16_t *samples_out,
    size_t sample_count);
bool mw_audio_synth_is_muted(const mw_audio_synth_t *synth);
uint32_t mw_audio_cue_duration_ms(mw_audio_cue_t cue);

#ifdef __cplusplus
}
#endif

#endif
