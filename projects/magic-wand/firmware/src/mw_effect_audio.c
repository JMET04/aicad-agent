#include "mw_effect_audio.h"

#include <string.h>

static int32_t clamp_i32(int32_t value, int32_t minimum, int32_t maximum)
{
    if (value < minimum) {
        return minimum;
    }
    if (value > maximum) {
        return maximum;
    }
    return value;
}

static int32_t triangle(uint32_t index, uint32_t period)
{
    uint32_t phase;
    int64_t ramp;
    if (period < UINT32_C(4)) {
        return 0;
    }
    phase = index % period;
    ramp = ((int64_t)phase * INT64_C(131068)) / (int64_t)period;
    if (phase < (period / UINT32_C(2))) {
        return (int32_t)(-INT64_C(32767) + ramp);
    }
    return (int32_t)(INT64_C(98301) - ramp);
}

static int32_t next_noise(mw_audio_synth_t *synth)
{
    synth->noise_state =
        synth->noise_state * UINT32_C(1664525) + UINT32_C(1013904223);
    return (int32_t)((synth->noise_state >> 16U) & UINT32_C(0x7fff)) -
        INT32_C(16384);
}

uint32_t mw_audio_cue_duration_ms(mw_audio_cue_t cue)
{
    switch (cue) {
    case MW_AUDIO_CUE_FIRE_WHOOSH_CRACKLE:
        return UINT32_C(650);
    case MW_AUDIO_CUE_ICE_CHIME_CRACK:
        return UINT32_C(750);
    case MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM:
        return UINT32_C(420);
    case MW_AUDIO_CUE_LIGHTNING_ZAP:
        return UINT32_C(360);
    case MW_AUDIO_CUE_SHIELD_SHIMMER:
        return UINT32_C(520);
    case MW_AUDIO_CUE_HEAL_CHIME:
        return UINT32_C(760);
    case MW_AUDIO_CUE_PORTAL_WARP:
        return UINT32_C(820);
    case MW_AUDIO_CUE_ARCANE_PULSE:
        return UINT32_C(480);
    case MW_AUDIO_CUE_PAIRING:
        return UINT32_C(220);
    case MW_AUDIO_CUE_DISCONNECTED:
        return UINT32_C(260);
    case MW_AUDIO_CUE_LOW_BATTERY:
        return UINT32_C(300);
    case MW_AUDIO_CUE_UNKNOWN:
        return UINT32_C(260);
    case MW_AUDIO_CUE_NONE:
    default:
        return 0U;
    }
}

void mw_audio_synth_init(mw_audio_synth_t *synth)
{
    if (synth == NULL) {
        return;
    }
    (void)memset(synth, 0, sizeof(*synth));
    synth->noise_state = UINT32_C(0x4d575241);
    synth->mute_required = true;
}

bool mw_audio_synth_start(
    mw_audio_synth_t *synth,
    mw_audio_cue_t cue,
    uint8_t requested_volume_percent)
{
    uint32_t duration_ms;
    uint8_t limit = MW_AUDIO_MASTER_VOLUME_LIMIT_PERCENT;

    if ((synth == NULL) || (requested_volume_percent > UINT8_C(100))) {
        return false;
    }
    duration_ms = mw_audio_cue_duration_ms(cue);
    if (duration_ms == 0U) {
        mw_audio_synth_stop(synth);
        return false;
    }
    if (cue == MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM) {
        limit = MW_AUDIO_BOOM_VOLUME_LIMIT_PERCENT;
    }
    synth->cue = cue;
    synth->sample_index = 0U;
    synth->total_samples =
        (MW_AUDIO_SAMPLE_RATE_HZ * duration_ms) / UINT32_C(1000);
    synth->noise_state =
        UINT32_C(0x4d575241) ^ ((uint32_t)cue * UINT32_C(0x1020304));
    synth->requested_volume_percent = requested_volume_percent;
    synth->applied_volume_percent =
        requested_volume_percent < limit ? requested_volume_percent : limit;
    synth->active = true;
    synth->mute_required = false;
    return true;
}

void mw_audio_synth_stop(mw_audio_synth_t *synth)
{
    if (synth == NULL) {
        return;
    }
    synth->cue = MW_AUDIO_CUE_NONE;
    synth->sample_index = 0U;
    synth->total_samples = 0U;
    synth->active = false;
    synth->mute_required = true;
}

static int32_t cue_sample(mw_audio_synth_t *synth)
{
    const uint32_t i = synth->sample_index;
    int32_t value = 0;
    uint32_t period;

    switch (synth->cue) {
    case MW_AUDIO_CUE_FIRE_WHOOSH_CRACKLE:
        value = (triangle(i, UINT32_C(200)) / INT32_C(2)) +
            (triangle(i, UINT32_C(67)) / INT32_C(4));
        if ((i % UINT32_C(53)) < UINT32_C(9)) {
            value += next_noise(synth);
        }
        break;
    case MW_AUDIO_CUE_ICE_CHIME_CRACK:
        value = (triangle(i, UINT32_C(20)) / INT32_C(2)) +
            (triangle(i, UINT32_C(13)) / INT32_C(3));
        if ((i % UINT32_C(2400)) < UINT32_C(24)) {
            value += next_noise(synth) * INT32_C(2);
        }
        break;
    case MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM:
        value = triangle(i, UINT32_C(228)) +
            (next_noise(synth) / INT32_C(2));
        break;
    case MW_AUDIO_CUE_LIGHTNING_ZAP:
        value = next_noise(synth) +
            (triangle(i, UINT32_C(36)) / INT32_C(2));
        break;
    case MW_AUDIO_CUE_SHIELD_SHIMMER:
        value = (triangle(i, UINT32_C(31)) / INT32_C(2)) +
            (triangle(i, UINT32_C(37)) / INT32_C(2));
        break;
    case MW_AUDIO_CUE_HEAL_CHIME:
        period = (i < UINT32_C(4000)) ? UINT32_C(32) :
            ((i < UINT32_C(8000)) ? UINT32_C(27) : UINT32_C(22));
        value = triangle(i, period);
        break;
    case MW_AUDIO_CUE_PORTAL_WARP:
        period = UINT32_C(86) - ((i / UINT32_C(256)) % UINT32_C(50));
        value = triangle(i, period) +
            (triangle(i, period + UINT32_C(7)) / INT32_C(2));
        break;
    case MW_AUDIO_CUE_ARCANE_PULSE:
        value = triangle(i, UINT32_C(50)) +
            (triangle(i, UINT32_C(37)) / INT32_C(2));
        break;
    case MW_AUDIO_CUE_PAIRING:
        value = triangle(i, UINT32_C(40));
        break;
    case MW_AUDIO_CUE_DISCONNECTED:
        period = (i < UINT32_C(2000)) ? UINT32_C(44) : UINT32_C(70);
        value = triangle(i, period);
        break;
    case MW_AUDIO_CUE_LOW_BATTERY:
        value = ((i / UINT32_C(1200)) % UINT32_C(2) == 0U) ?
            triangle(i, UINT32_C(64)) : 0;
        break;
    case MW_AUDIO_CUE_UNKNOWN:
        value = triangle(i, UINT32_C(55)) -
            (triangle(i, UINT32_C(73)) / INT32_C(2));
        break;
    case MW_AUDIO_CUE_NONE:
    default:
        break;
    }
    return clamp_i32(value, -INT32_C(32767), INT32_C(32767));
}

bool mw_audio_synth_render(
    mw_audio_synth_t *synth,
    int16_t *samples_out,
    size_t sample_count)
{
    size_t index;

    if ((synth == NULL) || ((samples_out == NULL) && (sample_count != 0U))) {
        return false;
    }
    for (index = 0U; index < sample_count; ++index) {
        int32_t sample = 0;
        if (synth->active &&
            (synth->sample_index < synth->total_samples)) {
            const int32_t raw = cue_sample(synth);
            const uint32_t remaining =
                synth->total_samples - synth->sample_index;
            int64_t scaled =
                (int64_t)raw * (int64_t)remaining;
            scaled /= (int64_t)synth->total_samples;
            scaled *= (int64_t)synth->applied_volume_percent;
            scaled /= INT64_C(100);
            sample = clamp_i32(
                (int32_t)scaled,
                (synth->cue == MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM) ?
                    -(int32_t)MW_AUDIO_BOOM_ABS_LIMIT :
                    -(int32_t)MW_AUDIO_OUTPUT_ABS_LIMIT,
                (synth->cue == MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM) ?
                    (int32_t)MW_AUDIO_BOOM_ABS_LIMIT :
                    (int32_t)MW_AUDIO_OUTPUT_ABS_LIMIT);
            ++synth->sample_index;
        }
        if (synth->active &&
            (synth->sample_index >= synth->total_samples)) {
            synth->active = false;
            synth->mute_required = true;
        }
        samples_out[index] = (int16_t)sample;
    }
    return true;
}

bool mw_audio_synth_is_muted(const mw_audio_synth_t *synth)
{
    return (synth == NULL) || synth->mute_required || !synth->active;
}
