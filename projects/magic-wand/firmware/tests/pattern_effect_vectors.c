#include "mw_effect_scheduler.h"
#include "mw_receiver_rev_b_pins.h"

#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        (void)fprintf(stderr, "check failed at %s:%d: %s\n", \
                      __FILE__, __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static uint32_t hash_u16(uint32_t hash, uint16_t value)
{
    hash ^= (uint32_t)(value & UINT16_C(0xff));
    hash *= UINT32_C(16777619);
    hash ^= (uint32_t)(value >> 8U);
    hash *= UINT32_C(16777619);
    return hash;
}

static uint32_t scene_hash(const mw_pattern_scene_t *scene)
{
    uint16_t row[MW_PATTERN_DISPLAY_WIDTH];
    uint16_t y;
    uint16_t x;
    uint32_t hash = UINT32_C(2166136261);

    for (y = 0U; y < MW_PATTERN_DISPLAY_HEIGHT; ++y) {
        if (!mw_pattern_render_row_rgb565(scene, y, row)) {
            return 0U;
        }
        for (x = 0U; x < MW_PATTERN_DISPLAY_WIDTH; ++x) {
            hash = hash_u16(hash, row[x]);
        }
    }
    return hash;
}

static uint32_t audio_hash(mw_audio_cue_t cue, int16_t *peak_out)
{
    mw_audio_synth_t synth;
    int16_t block[128];
    uint32_t hash = UINT32_C(2166136261);
    size_t block_index;
    size_t sample_index;
    int16_t peak = 0;

    mw_audio_synth_init(&synth);
    if (!mw_audio_synth_start(&synth, cue, UINT8_C(100))) {
        return 0U;
    }
    for (block_index = 0U; block_index < 16U; ++block_index) {
        if (!mw_audio_synth_render(&synth, block, 128U)) {
            return 0U;
        }
        for (sample_index = 0U; sample_index < 128U; ++sample_index) {
            const int32_t absolute = block[sample_index] < 0 ?
                -(int32_t)block[sample_index] : (int32_t)block[sample_index];
            if (absolute > (int32_t)peak) {
                peak = (int16_t)absolute;
            }
            hash = hash_u16(hash, (uint16_t)block[sample_index]);
        }
    }
    *peak_out = peak;
    return hash;
}

static int check_pin_budget(void)
{
    CHECK(MW_RXFX_TFT_SCK_MODULE_PAD == 52U);
    CHECK(MW_RXFX_TFT_MOSI_MODULE_PAD == 50U);
    CHECK(MW_RXFX_TFT_CS_MODULE_PAD == 51U);
    CHECK(MW_RXFX_I2S_BCLK_MODULE_PAD == 1U);
    CHECK(MW_RXFX_I2S_LRCLK_MODULE_PAD == 2U);
    CHECK(MW_RXFX_I2S_DOUT_MODULE_PAD == 3U);
    CHECK(MW_RXFX_AUDIO_SD_CTRL_MODULE_PAD == 4U);
    CHECK(MW_RXFX_AUDIO_SD_SERIES_OHMS == 2200U);
    CHECK(MW_RXFX_AUDIO_SD_PULLDOWN_OHMS == 100000U);
    CHECK(MW_RXFX_RGB_R_MODULE_PAD == 5U);
    CHECK(MW_RXFX_RGB_G_MODULE_PAD == 7U);
    CHECK(MW_RXFX_RGB_B_MODULE_PAD == 8U);
    CHECK(MW_RXFX_RGB_COMMON_ANODE == 1U);
    CHECK(MW_RXFX_RGB_ACTIVE_LOW == 1U);
    CHECK(MW_RXFX_TFT_J2_PIN_3_MOSI == 3U);
    CHECK(MW_RXFX_TFT_J2_PIN_4_SCK == 4U);
    CHECK(MW_RXFX_TFT_J2_PIN_8_BL == 8U);
    CHECK(MW_RXFX_REQUIRED_USB_SUPPLY_MA == 2000U);
    return 0;
}

static int check_pattern_renderer(void)
{
    mw_pattern_scene_t scene;
    uint32_t first_frame[8];
    uint32_t second_frame[8];
    uint8_t gesture;
    uint8_t other;
    mw_rgb8_t status_zero;
    mw_rgb8_t status_seven;

    mw_pattern_scene_init(&scene);
    CHECK(mw_pattern_render_pixel_rgb565(&scene, 0U, 0U) == 0U);
    CHECK(!mw_pattern_render_row_rgb565(&scene, 240U, NULL));

    for (gesture = 1U; gesture <= 8U; ++gesture) {
        CHECK(mw_pattern_show_gesture(
            &scene, (uint8_t)(gesture - 1U),
            (mw_gesture_id_t)gesture, UINT8_C(90)));
        mw_pattern_tick(&scene, 0U);
        first_frame[gesture - 1U] = scene_hash(&scene);
        mw_pattern_tick(&scene, 150U);
        second_frame[gesture - 1U] = scene_hash(&scene);
        CHECK(first_frame[gesture - 1U] != 0U);
        CHECK(first_frame[gesture - 1U] != second_frame[gesture - 1U]);
    }
    for (gesture = 0U; gesture < 8U; ++gesture) {
        for (other = (uint8_t)(gesture + 1U); other < 8U; ++other) {
            CHECK(first_frame[gesture] != first_frame[other]);
        }
    }

    CHECK(mw_pattern_show_gesture(
        &scene, 0U, MW_GESTURE_TWIST_CW, UINT8_C(90)));
    status_zero = scene.status_led;
    CHECK(mw_pattern_show_gesture(
        &scene, 7U, MW_GESTURE_TWIST_CW, UINT8_C(90)));
    status_seven = scene.status_led;
    CHECK((status_zero.red != status_seven.red) ||
          (status_zero.green != status_seven.green) ||
          (status_zero.blue != status_seven.blue));

    CHECK(mw_pattern_show_pairing(&scene, 3U));
    CHECK(scene.state == MW_PATTERN_STATE_PAIRING);
    CHECK(mw_pattern_show_connected(&scene, 3U));
    CHECK(scene.state == MW_PATTERN_STATE_CONNECTED);
    mw_pattern_show_disconnected(&scene);
    CHECK(scene.state == MW_PATTERN_STATE_DISCONNECTED);
    CHECK(mw_pattern_set_battery(&scene, UINT8_C(15)));
    CHECK(scene.state == MW_PATTERN_STATE_LOW_BATTERY);
    mw_pattern_show_unknown(&scene, 2U);
    CHECK(scene.state == MW_PATTERN_STATE_UNKNOWN_GESTURE);
    mw_pattern_show_fault(&scene);
    CHECK(scene.state == MW_PATTERN_STATE_FAULT);
    return 0;
}

static int check_audio_synth(void)
{
    static const mw_audio_cue_t cues[8] = {
        MW_AUDIO_CUE_FIRE_WHOOSH_CRACKLE,
        MW_AUDIO_CUE_ICE_CHIME_CRACK,
        MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM,
        MW_AUDIO_CUE_LIGHTNING_ZAP,
        MW_AUDIO_CUE_SHIELD_SHIMMER,
        MW_AUDIO_CUE_HEAL_CHIME,
        MW_AUDIO_CUE_PORTAL_WARP,
        MW_AUDIO_CUE_ARCANE_PULSE
    };
    uint32_t hashes[8];
    int16_t peaks[8];
    uint8_t cue;
    uint8_t other;
    mw_audio_synth_t synth;
    int16_t block[256];

    for (cue = 0U; cue < 8U; ++cue) {
        hashes[cue] = audio_hash(cues[cue], &peaks[cue]);
        CHECK(hashes[cue] != 0U);
        CHECK(peaks[cue] <= MW_AUDIO_OUTPUT_ABS_LIMIT);
    }
    CHECK(peaks[2] <= MW_AUDIO_BOOM_ABS_LIMIT);
    for (cue = 0U; cue < 8U; ++cue) {
        for (other = (uint8_t)(cue + 1U); other < 8U; ++other) {
            CHECK(hashes[cue] != hashes[other]);
        }
    }

    mw_audio_synth_init(&synth);
    CHECK(mw_audio_synth_is_muted(&synth));
    CHECK(mw_audio_synth_start(
        &synth, MW_AUDIO_CUE_EXPLOSION_LIMITED_BOOM, UINT8_C(100)));
    CHECK(synth.applied_volume_percent ==
          MW_AUDIO_BOOM_VOLUME_LIMIT_PERCENT);
    while (synth.active) {
        CHECK(mw_audio_synth_render(&synth, block, 256U));
    }
    CHECK(mw_audio_synth_is_muted(&synth));
    return 0;
}

static int check_effect_scheduler(void)
{
    static const mw_effect_id_t expected[8] = {
        MW_EFFECT_EXPLOSION,
        MW_EFFECT_FIRE,
        MW_EFFECT_ICE,
        MW_EFFECT_LIGHTNING,
        MW_EFFECT_SHIELD,
        MW_EFFECT_ARCANE,
        MW_EFFECT_HEAL,
        MW_EFFECT_PORTAL
    };
    mw_effect_scheduler_t scheduler;
    uint8_t gesture;

    mw_effect_scheduler_init(&scheduler, true, true);
    CHECK(mw_effect_scheduler_pairing(&scheduler, 0U));
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_PAIRING);
    CHECK(mw_effect_scheduler_connected(&scheduler, 0U));

    for (gesture = 1U; gesture <= 8U; ++gesture) {
        CHECK(mw_effect_for_gesture((mw_gesture_id_t)gesture) ==
              expected[gesture - 1U]);
        CHECK(mw_effect_scheduler_gesture(
            &scheduler, 0U, (mw_gesture_id_t)gesture,
            UINT8_C(90), UINT8_C(80), true, UINT32_C(1000)));
        CHECK(scheduler.active_effect == expected[gesture - 1U]);
        CHECK(scheduler.pattern.state == MW_PATTERN_STATE_GESTURE);
        CHECK(!mw_audio_synth_is_muted(&scheduler.audio));
    }

    mw_effect_scheduler_tick(
        &scheduler, UINT32_C(1000) + MW_EFFECT_DURATION_MS);
    CHECK(scheduler.state == MW_EFFECT_SCHEDULER_IDLE);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_CONNECTED);
    CHECK(mw_audio_synth_is_muted(&scheduler.audio));

    mw_effect_scheduler_unknown(&scheduler, 0U, UINT32_C(2000));
    CHECK(scheduler.active_effect == MW_EFFECT_UNKNOWN);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_UNKNOWN_GESTURE);
    CHECK(mw_effect_scheduler_low_battery(&scheduler, 0U, UINT8_C(10)));
    CHECK(scheduler.active_effect == MW_EFFECT_LOW_BATTERY);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_LOW_BATTERY);

    CHECK(mw_effect_scheduler_connected(&scheduler, 1U));
    CHECK(mw_effect_scheduler_gesture(
        &scheduler, 1U, MW_GESTURE_TWIST_CW,
        UINT8_C(90), UINT8_C(80), true, UINT32_C(2100)));
    mw_effect_scheduler_disconnected(&scheduler, 1U);
    CHECK(scheduler.connected_channels_mask == UINT8_C(1));
    CHECK(scheduler.active_effect == MW_EFFECT_DISCONNECTED);
    CHECK(scheduler.restore_connected_pending);
    mw_effect_scheduler_tick(&scheduler, UINT32_C(2200));
    CHECK(!scheduler.restore_connected_pending);
    CHECK(scheduler.effect_deadline_ms ==
          UINT32_C(2200) + MW_EFFECT_DISCONNECT_PROMPT_MS);
    mw_effect_scheduler_tick(
        &scheduler, UINT32_C(2200) + MW_EFFECT_DISCONNECT_PROMPT_MS - 1U);
    CHECK(scheduler.active_effect == MW_EFFECT_DISCONNECTED);
    mw_effect_scheduler_tick(
        &scheduler, UINT32_C(2200) + MW_EFFECT_DISCONNECT_PROMPT_MS);
    CHECK(scheduler.state == MW_EFFECT_SCHEDULER_IDLE);
    CHECK(scheduler.active_channel == 0U);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_CONNECTED);
    CHECK(mw_audio_synth_is_muted(&scheduler.audio));

    mw_effect_scheduler_disconnected(&scheduler, 0U);
    CHECK(scheduler.active_effect == MW_EFFECT_DISCONNECTED);
    CHECK(!scheduler.restore_connected_pending);

    mw_effect_scheduler_fault(&scheduler);
    CHECK(scheduler.state == MW_EFFECT_SCHEDULER_FAULT);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_FAULT);
    CHECK(mw_audio_synth_is_muted(&scheduler.audio));
    CHECK(!mw_effect_scheduler_gesture(
        &scheduler, 0U, MW_GESTURE_TAP,
        UINT8_C(90), UINT8_C(80), true, UINT32_C(3000)));

    mw_effect_scheduler_init(&scheduler, false, false);
    CHECK(mw_effect_scheduler_gesture(
        &scheduler, 7U, MW_GESTURE_TWIST_CW,
        UINT8_C(90), UINT8_C(80), true, UINT32_C(0)));
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_GESTURE);
    CHECK(mw_audio_synth_is_muted(&scheduler.audio));

    mw_effect_scheduler_init(&scheduler, true, true);
    CHECK(mw_effect_scheduler_gesture(
        &scheduler, 2U, MW_GESTURE_TWIST_CCW,
        UINT8_C(90), UINT8_C(255), false, UINT32_C(50)));
    CHECK(scheduler.active_effect == MW_EFFECT_ICE);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_GESTURE);
    CHECK(!mw_audio_synth_is_muted(&scheduler.audio));

    mw_effect_scheduler_init(&scheduler, true, true);
    CHECK(mw_effect_scheduler_connected(&scheduler, 0U));
    CHECK(mw_effect_scheduler_gesture(
        &scheduler, 0U, MW_GESTURE_TAP,
        UINT8_C(90), UINT8_C(80), true,
        UINT32_MAX - (MW_EFFECT_DURATION_MS - 1U)));
    CHECK(scheduler.effect_timed);
    CHECK(scheduler.effect_deadline_ms == 0U);
    mw_effect_scheduler_tick(&scheduler, UINT32_MAX);
    CHECK(scheduler.active_effect == MW_EFFECT_EXPLOSION);
    mw_effect_scheduler_tick(&scheduler, 0U);
    CHECK(!scheduler.effect_timed);
    CHECK(scheduler.state == MW_EFFECT_SCHEDULER_IDLE);
    CHECK(scheduler.pattern.state == MW_PATTERN_STATE_CONNECTED);

    mw_effect_scheduler_init(&scheduler, true, true);
    CHECK(mw_effect_scheduler_connected(&scheduler, 0U));
    mw_effect_scheduler_unknown(
        &scheduler, 0U,
        UINT32_MAX - (MW_EFFECT_DURATION_MS - 1U));
    CHECK(scheduler.effect_timed);
    CHECK(scheduler.effect_deadline_ms == 0U);
    mw_effect_scheduler_tick(&scheduler, UINT32_MAX);
    CHECK(scheduler.active_effect == MW_EFFECT_UNKNOWN);
    mw_effect_scheduler_tick(&scheduler, 0U);
    CHECK(!scheduler.effect_timed);
    CHECK(scheduler.state == MW_EFFECT_SCHEDULER_IDLE);
    return 0;
}

int main(void)
{
    CHECK(check_pin_budget() == 0);
    CHECK(check_pattern_renderer() == 0);
    CHECK(check_audio_synth() == 0);
    CHECK(check_effect_scheduler() == 0);
    (void)puts("pattern/effect/audio vectors passed; display/audio HIL gates remain open");
    return 0;
}
