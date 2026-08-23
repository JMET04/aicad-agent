#include "mw_effect_scheduler.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#define MW_PREVIEW_PATH_CAPACITY ((size_t)1024)
#define MW_PREVIEW_AUDIO_BLOCK_SAMPLES ((size_t)256)
#define MW_PREVIEW_FRAME_COUNT \
    (MW_EFFECT_DURATION_MS / MW_PATTERN_FRAME_PERIOD_MS)

typedef struct {
    const char *name;
    mw_gesture_id_t gesture;
    mw_effect_id_t effect;
} mw_preview_effect_t;

static const mw_preview_effect_t effects[] = {
    {"fire", MW_GESTURE_TWIST_CW, MW_EFFECT_FIRE},
    {"ice", MW_GESTURE_TWIST_CCW, MW_EFFECT_ICE},
    {"explosion", MW_GESTURE_TAP, MW_EFFECT_EXPLOSION},
    {"lightning", MW_GESTURE_SWISH_LEFT, MW_EFFECT_LIGHTNING},
    {"shield", MW_GESTURE_SWISH_RIGHT, MW_EFFECT_SHIELD},
    {"arcane", MW_GESTURE_THRUST, MW_EFFECT_ARCANE},
    {"heal", MW_GESTURE_CIRCLE_CW, MW_EFFECT_HEAL},
    {"portal", MW_GESTURE_CIRCLE_CCW, MW_EFFECT_PORTAL}
};

static bool write_u16_le(FILE *file, uint16_t value)
{
    return (fputc((int)(value & UINT16_C(0xff)), file) != EOF) &&
        (fputc((int)((value >> 8U) & UINT16_C(0xff)), file) != EOF);
}

static bool write_u32_le(FILE *file, uint32_t value)
{
    return (fputc((int)(value & UINT32_C(0xff)), file) != EOF) &&
        (fputc((int)((value >> 8U) & UINT32_C(0xff)), file) != EOF) &&
        (fputc((int)((value >> 16U) & UINT32_C(0xff)), file) != EOF) &&
        (fputc((int)((value >> 24U) & UINT32_C(0xff)), file) != EOF);
}

static bool make_frame_path(
    char path[MW_PREVIEW_PATH_CAPACITY],
    const char *root,
    const char *effect_name,
    uint32_t frame_index)
{
    const int written = snprintf(
        path,
        MW_PREVIEW_PATH_CAPACITY,
        "%s/%s/frame_%03" PRIu32 ".ppm",
        root,
        effect_name,
        frame_index);
    return (written >= 0) && ((size_t)written < MW_PREVIEW_PATH_CAPACITY);
}

static bool make_wav_path(
    char path[MW_PREVIEW_PATH_CAPACITY],
    const char *root,
    const char *effect_name)
{
    const int written = snprintf(
        path,
        MW_PREVIEW_PATH_CAPACITY,
        "%s/%s.wav",
        root,
        effect_name);
    return (written >= 0) && ((size_t)written < MW_PREVIEW_PATH_CAPACITY);
}

static uint8_t scale_five_bits(uint16_t value)
{
    return (uint8_t)((((uint32_t)value * UINT32_C(255)) +
                       UINT32_C(15)) /
                      UINT32_C(31));
}

static uint8_t scale_six_bits(uint16_t value)
{
    return (uint8_t)((((uint32_t)value * UINT32_C(255)) +
                       UINT32_C(31)) /
                      UINT32_C(63));
}

static bool write_frame(
    const char *root,
    const char *effect_name,
    uint32_t frame_index,
    const mw_pattern_scene_t *scene)
{
    char path[MW_PREVIEW_PATH_CAPACITY];
    FILE *file;
    uint16_t row[MW_PATTERN_DISPLAY_WIDTH];
    uint16_t y;

    if (!make_frame_path(path, root, effect_name, frame_index)) {
        return false;
    }
    file = fopen(path, "wb");
    if (file == NULL) {
        return false;
    }
    if (fprintf(
            file,
            "P6\n%u %u\n255\n",
            (unsigned int)MW_PATTERN_DISPLAY_WIDTH,
            (unsigned int)MW_PATTERN_DISPLAY_HEIGHT) < 0) {
        (void)fclose(file);
        return false;
    }

    for (y = 0U; y < MW_PATTERN_DISPLAY_HEIGHT; ++y) {
        uint16_t x;
        if (!mw_pattern_render_row_rgb565(scene, y, row)) {
            (void)fclose(file);
            return false;
        }
        for (x = 0U; x < MW_PATTERN_DISPLAY_WIDTH; ++x) {
            const uint16_t pixel = row[x];
            const uint8_t rgb[3] = {
                scale_five_bits((uint16_t)((pixel >> 11U) & UINT16_C(31))),
                scale_six_bits((uint16_t)((pixel >> 5U) & UINT16_C(63))),
                scale_five_bits((uint16_t)(pixel & UINT16_C(31)))
            };
            if (fwrite(rgb, sizeof(rgb[0]), 3U, file) != 3U) {
                (void)fclose(file);
                return false;
            }
        }
    }
    return fclose(file) == 0;
}

static bool write_wav_header(FILE *file, uint32_t sample_count)
{
    const uint32_t data_bytes = sample_count * UINT32_C(2);
    const uint32_t byte_rate = MW_AUDIO_SAMPLE_RATE_HZ * UINT32_C(2);

    return (fwrite("RIFF", 1U, 4U, file) == 4U) &&
        write_u32_le(file, UINT32_C(36) + data_bytes) &&
        (fwrite("WAVEfmt ", 1U, 8U, file) == 8U) &&
        write_u32_le(file, UINT32_C(16)) &&
        write_u16_le(file, UINT16_C(1)) &&
        write_u16_le(file, UINT16_C(1)) &&
        write_u32_le(file, MW_AUDIO_SAMPLE_RATE_HZ) &&
        write_u32_le(file, byte_rate) &&
        write_u16_le(file, UINT16_C(2)) &&
        write_u16_le(file, UINT16_C(16)) &&
        (fwrite("data", 1U, 4U, file) == 4U) &&
        write_u32_le(file, data_bytes);
}

static bool write_wav_samples(
    FILE *file,
    const int16_t *samples,
    size_t sample_count)
{
    size_t index;
    for (index = 0U; index < sample_count; ++index) {
        if (!write_u16_le(file, (uint16_t)samples[index])) {
            return false;
        }
    }
    return true;
}

static bool write_audio_preview(
    const char *root,
    const char *effect_name,
    mw_audio_cue_t cue)
{
    char path[MW_PREVIEW_PATH_CAPACITY];
    FILE *file;
    mw_audio_synth_t synth;
    int16_t samples[MW_PREVIEW_AUDIO_BLOCK_SAMPLES];
    const uint32_t preview_samples =
        (MW_AUDIO_SAMPLE_RATE_HZ * MW_EFFECT_DURATION_MS) /
        UINT32_C(1000);
    uint32_t remaining = preview_samples;

    if (!make_wav_path(path, root, effect_name)) {
        return false;
    }
    mw_audio_synth_init(&synth);
    if (!mw_audio_synth_start(
            &synth, cue, MW_EFFECT_DEFAULT_VOLUME_PERCENT)) {
        return false;
    }
    file = fopen(path, "wb");
    if (file == NULL) {
        return false;
    }
    if (!write_wav_header(file, preview_samples)) {
        (void)fclose(file);
        return false;
    }

    while (remaining != 0U) {
        const size_t block_count =
            remaining > (uint32_t)MW_PREVIEW_AUDIO_BLOCK_SAMPLES ?
                MW_PREVIEW_AUDIO_BLOCK_SAMPLES : (size_t)remaining;
        if (!mw_audio_synth_render(&synth, samples, block_count) ||
            !write_wav_samples(file, samples, block_count)) {
            (void)fclose(file);
            return false;
        }
        remaining -= (uint32_t)block_count;
    }
    return fclose(file) == 0;
}

static FILE *open_manifest(const char *root)
{
    char path[MW_PREVIEW_PATH_CAPACITY];
    const int written = snprintf(
        path, MW_PREVIEW_PATH_CAPACITY, "%s/manifest.csv", root);
    FILE *manifest;

    if ((written < 0) || ((size_t)written >= MW_PREVIEW_PATH_CAPACITY)) {
        return NULL;
    }
    manifest = fopen(path, "wb");
    if (manifest == NULL) {
        return NULL;
    }
    if (fputs(
            "effect,gesture_id,effect_id,audio_cue_id,frames,fps,"
            "preview_ms,cue_ms,requested_volume_percent,"
            "applied_volume_percent\n",
            manifest) == EOF) {
        (void)fclose(manifest);
        return NULL;
    }
    return manifest;
}

static bool export_effect(
    const char *root,
    const mw_preview_effect_t *definition,
    FILE *manifest)
{
    mw_effect_scheduler_t scheduler;
    const mw_audio_cue_t cue = mw_audio_cue_for_effect(definition->effect);
    uint32_t frame_index;

    mw_effect_scheduler_init(&scheduler, true, true);
    if (!mw_effect_scheduler_connected(&scheduler, UINT8_C(0)) ||
        !mw_effect_scheduler_gesture(
            &scheduler,
            UINT8_C(0),
            definition->gesture,
            UINT8_C(95),
            UINT8_C(80),
            true,
            UINT32_C(0)) ||
        (scheduler.active_effect != definition->effect)) {
        return false;
    }

    for (frame_index = 0U;
         frame_index < MW_PREVIEW_FRAME_COUNT;
         ++frame_index) {
        mw_effect_scheduler_tick(
            &scheduler, frame_index * MW_PATTERN_FRAME_PERIOD_MS);
        if (!write_frame(
                root,
                definition->name,
                frame_index,
                &scheduler.pattern)) {
            return false;
        }
    }
    if (!write_audio_preview(root, definition->name, cue)) {
        return false;
    }
    return fprintf(
               manifest,
               "%s,%u,%u,%u,%" PRIu32 ",20,%" PRIu32 ",%" PRIu32
               ",%u,%u\n",
               definition->name,
               (unsigned int)definition->gesture,
               (unsigned int)definition->effect,
               (unsigned int)cue,
               MW_PREVIEW_FRAME_COUNT,
               MW_EFFECT_DURATION_MS,
               mw_audio_cue_duration_ms(cue),
               (unsigned int)MW_EFFECT_DEFAULT_VOLUME_PERCENT,
               (unsigned int)scheduler.audio.applied_volume_percent) >= 0;
}

int main(int argc, char **argv)
{
    FILE *manifest;
    size_t index;

    if (argc != 2) {
        (void)fprintf(
            stderr,
            "usage: %s <existing-output-directory>\n",
            argv[0]);
        return 2;
    }
    manifest = open_manifest(argv[1]);
    if (manifest == NULL) {
        (void)fprintf(stderr, "failed to create preview manifest\n");
        return 1;
    }

    for (index = 0U; index < (sizeof(effects) / sizeof(effects[0])); ++index) {
        if (!export_effect(argv[1], &effects[index], manifest)) {
            (void)fprintf(
                stderr, "failed to export effect: %s\n", effects[index].name);
            (void)fclose(manifest);
            return 1;
        }
        (void)printf("exported %s\n", effects[index].name);
    }
    if (fclose(manifest) != 0) {
        (void)fprintf(stderr, "failed to finalize preview manifest\n");
        return 1;
    }
    return 0;
}
