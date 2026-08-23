#ifndef MW_PATTERN_RENDERER_H
#define MW_PATTERN_RENDERER_H

#include "mw_gesture.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_PATTERN_DISPLAY_WIDTH ((uint16_t)240)
#define MW_PATTERN_DISPLAY_HEIGHT ((uint16_t)240)
#define MW_PATTERN_LOGICAL_CHANNELS ((uint8_t)8)
#define MW_PATTERN_LOW_BATTERY_PERCENT ((uint8_t)15)
#define MW_PATTERN_FRAME_PERIOD_MS UINT32_C(50)

typedef enum {
    MW_PATTERN_STATE_BOOT = 0,
    MW_PATTERN_STATE_PAIRING,
    MW_PATTERN_STATE_CONNECTED,
    MW_PATTERN_STATE_GESTURE,
    MW_PATTERN_STATE_DISCONNECTED,
    MW_PATTERN_STATE_LOW_BATTERY,
    MW_PATTERN_STATE_UNKNOWN_GESTURE,
    MW_PATTERN_STATE_FAULT
} mw_pattern_state_t;

typedef enum {
    MW_PATTERN_NEUTRAL = 0,
    MW_PATTERN_PAIRING_ORBIT,
    MW_PATTERN_CONNECTED_GLYPH,
    MW_PATTERN_TAP_STAR,
    MW_PATTERN_TWIST_CW_SPIRAL,
    MW_PATTERN_TWIST_CCW_SPIRAL,
    MW_PATTERN_SWISH_LEFT_COMET,
    MW_PATTERN_SWISH_RIGHT_COMET,
    MW_PATTERN_THRUST_BURST,
    MW_PATTERN_CIRCLE_CW_ORBIT,
    MW_PATTERN_CIRCLE_CCW_ORBIT,
    MW_PATTERN_DISCONNECTED_LINK,
    MW_PATTERN_LOW_BATTERY,
    MW_PATTERN_UNKNOWN_GLYPH,
    MW_PATTERN_FAULT_CROSS
} mw_pattern_id_t;

typedef struct {
    uint8_t red;
    uint8_t green;
    uint8_t blue;
} mw_rgb8_t;

typedef struct {
    mw_pattern_state_t state;
    mw_pattern_id_t pattern;
    mw_gesture_id_t gesture_id;
    uint8_t active_channel;
    uint8_t confidence_percent;
    uint8_t battery_percent;
    uint32_t animation_tick;
    mw_rgb8_t primary;
    mw_rgb8_t accent;
    mw_rgb8_t background;
    mw_rgb8_t status_led;
} mw_pattern_scene_t;

void mw_pattern_scene_init(mw_pattern_scene_t *scene);
bool mw_pattern_show_pairing(mw_pattern_scene_t *scene, uint8_t channel_id);
bool mw_pattern_show_connected(mw_pattern_scene_t *scene, uint8_t channel_id);
void mw_pattern_show_disconnected(mw_pattern_scene_t *scene);
bool mw_pattern_set_battery(
    mw_pattern_scene_t *scene,
    uint8_t battery_percent);
bool mw_pattern_show_gesture(
    mw_pattern_scene_t *scene,
    uint8_t channel_id,
    mw_gesture_id_t gesture_id,
    uint8_t confidence_percent);
void mw_pattern_show_unknown(mw_pattern_scene_t *scene, uint8_t channel_id);
void mw_pattern_show_fault(mw_pattern_scene_t *scene);
void mw_pattern_tick(mw_pattern_scene_t *scene, uint32_t now_ms);

/*
 * Render in RGB565, most-significant color bits in the conventional
 * RRRRRGGGGGGBBBBB layout. A target GC9A01A adapter owns byte order, SPI DMA,
 * address windows and display reset/backlight sequencing.
 */
uint16_t mw_pattern_render_pixel_rgb565(
    const mw_pattern_scene_t *scene,
    uint16_t x,
    uint16_t y);
bool mw_pattern_render_row_rgb565(
    const mw_pattern_scene_t *scene,
    uint16_t y,
    uint16_t row_out[MW_PATTERN_DISPLAY_WIDTH]);

#ifdef __cplusplus
}
#endif

#endif
