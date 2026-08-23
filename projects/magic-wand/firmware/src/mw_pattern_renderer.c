#include "mw_pattern_renderer.h"

#include <string.h>

static const mw_rgb8_t channel_accents[MW_PATTERN_LOGICAL_CHANNELS] = {
    {UINT8_C(0), UINT8_C(220), UINT8_C(255)},
    {UINT8_C(100), UINT8_C(255), UINT8_C(120)},
    {UINT8_C(255), UINT8_C(210), UINT8_C(0)},
    {UINT8_C(255), UINT8_C(90), UINT8_C(180)},
    {UINT8_C(140), UINT8_C(110), UINT8_C(255)},
    {UINT8_C(255), UINT8_C(120), UINT8_C(30)},
    {UINT8_C(40), UINT8_C(150), UINT8_C(255)},
    {UINT8_C(230), UINT8_C(255), UINT8_C(255)}
};

static const mw_rgb8_t gesture_primary[8] = {
    {UINT8_C(255), UINT8_C(245), UINT8_C(190)},
    {UINT8_C(255), UINT8_C(55), UINT8_C(5)},
    {UINT8_C(70), UINT8_C(170), UINT8_C(255)},
    {UINT8_C(75), UINT8_C(210), UINT8_C(255)},
    {UINT8_C(40), UINT8_C(245), UINT8_C(210)},
    {UINT8_C(210), UINT8_C(60), UINT8_C(255)},
    {UINT8_C(45), UINT8_C(255), UINT8_C(120)},
    {UINT8_C(150), UINT8_C(70), UINT8_C(255)}
};

static const mw_rgb8_t gesture_accent[8] = {
    {UINT8_C(255), UINT8_C(205), UINT8_C(20)},
    {UINT8_C(255), UINT8_C(145), UINT8_C(15)},
    {UINT8_C(245), UINT8_C(255), UINT8_C(255)},
    {UINT8_C(255), UINT8_C(255), UINT8_C(255)},
    {UINT8_C(220), UINT8_C(255), UINT8_C(255)},
    {UINT8_C(255), UINT8_C(205), UINT8_C(40)},
    {UINT8_C(235), UINT8_C(255), UINT8_C(245)},
    {UINT8_C(60), UINT8_C(235), UINT8_C(255)}
};

static int32_t abs_i32(int32_t value)
{
    return value < 0 ? -value : value;
}

static uint16_t rgb565(mw_rgb8_t color)
{
    return (uint16_t)((((uint16_t)color.red & UINT16_C(0xF8)) << 8) |
                      (((uint16_t)color.green & UINT16_C(0xFC)) << 3) |
                      ((uint16_t)color.blue >> 3));
}

static bool valid_channel(uint8_t channel_id)
{
    return channel_id < MW_PATTERN_LOGICAL_CHANNELS;
}

static void set_palette(
    mw_pattern_scene_t *scene,
    mw_rgb8_t primary,
    mw_rgb8_t accent,
    mw_rgb8_t background,
    mw_rgb8_t status_led)
{
    scene->primary = primary;
    scene->accent = accent;
    scene->background = background;
    scene->status_led = status_led;
}

void mw_pattern_scene_init(mw_pattern_scene_t *scene)
{
    if (scene == NULL) {
        return;
    }
    (void)memset(scene, 0, sizeof(*scene));
    scene->state = MW_PATTERN_STATE_BOOT;
    scene->pattern = MW_PATTERN_NEUTRAL;
    scene->battery_percent = UINT8_C(100);
    set_palette(scene,
                (mw_rgb8_t){UINT8_C(60), UINT8_C(100), UINT8_C(180)},
                channel_accents[0],
                (mw_rgb8_t){UINT8_C(2), UINT8_C(5), UINT8_C(14)},
                (mw_rgb8_t){UINT8_C(0), UINT8_C(0), UINT8_C(20)});
}

bool mw_pattern_show_pairing(mw_pattern_scene_t *scene, uint8_t channel_id)
{
    if ((scene == NULL) || !valid_channel(channel_id)) {
        return false;
    }
    scene->state = MW_PATTERN_STATE_PAIRING;
    scene->pattern = MW_PATTERN_PAIRING_ORBIT;
    scene->active_channel = channel_id;
    scene->gesture_id = MW_GESTURE_NONE;
    set_palette(scene,
                (mw_rgb8_t){UINT8_C(60), UINT8_C(130), UINT8_C(255)},
                channel_accents[channel_id],
                (mw_rgb8_t){UINT8_C(2), UINT8_C(5), UINT8_C(14)},
                (mw_rgb8_t){UINT8_C(0), UINT8_C(80), UINT8_C(255)});
    return true;
}

bool mw_pattern_show_connected(mw_pattern_scene_t *scene, uint8_t channel_id)
{
    if ((scene == NULL) || !valid_channel(channel_id)) {
        return false;
    }
    scene->state = MW_PATTERN_STATE_CONNECTED;
    scene->pattern = MW_PATTERN_CONNECTED_GLYPH;
    scene->active_channel = channel_id;
    scene->gesture_id = MW_GESTURE_NONE;
    set_palette(scene,
                (mw_rgb8_t){UINT8_C(50), UINT8_C(235), UINT8_C(120)},
                channel_accents[channel_id],
                (mw_rgb8_t){UINT8_C(2), UINT8_C(10), UINT8_C(8)},
                (mw_rgb8_t){UINT8_C(0), UINT8_C(180), UINT8_C(40)});
    return true;
}

void mw_pattern_show_disconnected(mw_pattern_scene_t *scene)
{
    if (scene == NULL) {
        return;
    }
    scene->state = MW_PATTERN_STATE_DISCONNECTED;
    scene->pattern = MW_PATTERN_DISCONNECTED_LINK;
    scene->gesture_id = MW_GESTURE_NONE;
    set_palette(scene,
                (mw_rgb8_t){UINT8_C(245), UINT8_C(55), UINT8_C(65)},
                (mw_rgb8_t){UINT8_C(115), UINT8_C(125), UINT8_C(145)},
                (mw_rgb8_t){UINT8_C(12), UINT8_C(4), UINT8_C(6)},
                (mw_rgb8_t){UINT8_C(220), UINT8_C(0), UINT8_C(0)});
}

bool mw_pattern_set_battery(
    mw_pattern_scene_t *scene,
    uint8_t battery_percent)
{
    if ((scene == NULL) || (battery_percent > UINT8_C(100))) {
        return false;
    }
    scene->battery_percent = battery_percent;
    if (battery_percent <= MW_PATTERN_LOW_BATTERY_PERCENT) {
        scene->state = MW_PATTERN_STATE_LOW_BATTERY;
        scene->pattern = MW_PATTERN_LOW_BATTERY;
        scene->gesture_id = MW_GESTURE_NONE;
        set_palette(scene,
                    (mw_rgb8_t){UINT8_C(255), UINT8_C(165), UINT8_C(30)},
                    (mw_rgb8_t){UINT8_C(255), UINT8_C(45), UINT8_C(35)},
                    (mw_rgb8_t){UINT8_C(14), UINT8_C(6), UINT8_C(2)},
                    (mw_rgb8_t){UINT8_C(255), UINT8_C(70), UINT8_C(0)});
    }
    return true;
}

static mw_pattern_id_t pattern_for_gesture(mw_gesture_id_t gesture_id)
{
    switch (gesture_id) {
    case MW_GESTURE_TAP:
        return MW_PATTERN_TAP_STAR;
    case MW_GESTURE_TWIST_CW:
        return MW_PATTERN_TWIST_CW_SPIRAL;
    case MW_GESTURE_TWIST_CCW:
        return MW_PATTERN_TWIST_CCW_SPIRAL;
    case MW_GESTURE_SWISH_LEFT:
        return MW_PATTERN_SWISH_LEFT_COMET;
    case MW_GESTURE_SWISH_RIGHT:
        return MW_PATTERN_SWISH_RIGHT_COMET;
    case MW_GESTURE_THRUST:
        return MW_PATTERN_THRUST_BURST;
    case MW_GESTURE_CIRCLE_CW:
        return MW_PATTERN_CIRCLE_CW_ORBIT;
    case MW_GESTURE_CIRCLE_CCW:
        return MW_PATTERN_CIRCLE_CCW_ORBIT;
    case MW_GESTURE_NONE:
    default:
        return MW_PATTERN_UNKNOWN_GLYPH;
    }
}

void mw_pattern_show_unknown(mw_pattern_scene_t *scene, uint8_t channel_id)
{
    if (scene == NULL) {
        return;
    }
    scene->state = MW_PATTERN_STATE_UNKNOWN_GESTURE;
    scene->pattern = MW_PATTERN_UNKNOWN_GLYPH;
    scene->gesture_id = MW_GESTURE_NONE;
    scene->active_channel = valid_channel(channel_id) ? channel_id : 0U;
    set_palette(scene,
                (mw_rgb8_t){UINT8_C(220), UINT8_C(85), UINT8_C(255)},
                (mw_rgb8_t){UINT8_C(255), UINT8_C(220), UINT8_C(75)},
                (mw_rgb8_t){UINT8_C(10), UINT8_C(3), UINT8_C(14)},
                (mw_rgb8_t){UINT8_C(130), UINT8_C(0), UINT8_C(200)});
}

bool mw_pattern_show_gesture(
    mw_pattern_scene_t *scene,
    uint8_t channel_id,
    mw_gesture_id_t gesture_id,
    uint8_t confidence_percent)
{
    if (scene == NULL) {
        return false;
    }
    if (!valid_channel(channel_id) ||
        (gesture_id <= MW_GESTURE_NONE) ||
        (gesture_id > MW_GESTURE_CIRCLE_CCW) ||
        (confidence_percent < MW_GESTURE_MIN_CONFIDENCE_PERCENT) ||
        (confidence_percent > UINT8_C(100))) {
        mw_pattern_show_unknown(scene, channel_id);
        return false;
    }
    scene->state = MW_PATTERN_STATE_GESTURE;
    scene->pattern = pattern_for_gesture(gesture_id);
    scene->gesture_id = gesture_id;
    scene->active_channel = channel_id;
    scene->confidence_percent = confidence_percent;
    set_palette(scene,
                gesture_primary[(uint8_t)gesture_id - UINT8_C(1)],
                gesture_accent[(uint8_t)gesture_id - UINT8_C(1)],
                (mw_rgb8_t){UINT8_C(3), UINT8_C(3), UINT8_C(12)},
                channel_accents[channel_id]);
    return true;
}

void mw_pattern_show_fault(mw_pattern_scene_t *scene)
{
    if (scene == NULL) {
        return;
    }
    scene->state = MW_PATTERN_STATE_FAULT;
    scene->pattern = MW_PATTERN_FAULT_CROSS;
    scene->gesture_id = MW_GESTURE_NONE;
    set_palette(scene,
                (mw_rgb8_t){UINT8_C(255), UINT8_C(25), UINT8_C(25)},
                (mw_rgb8_t){UINT8_C(255), UINT8_C(255), UINT8_C(255)},
                (mw_rgb8_t){UINT8_C(15), UINT8_C(0), UINT8_C(0)},
                (mw_rgb8_t){UINT8_C(255), UINT8_C(0), UINT8_C(0)});
}

void mw_pattern_tick(mw_pattern_scene_t *scene, uint32_t now_ms)
{
    if (scene == NULL) {
        return;
    }
    scene->animation_tick = now_ms / MW_PATTERN_FRAME_PERIOD_MS;
}

static bool near_ring(uint32_t radius_squared, int32_t radius)
{
    const int32_t target = radius * radius;
    const int32_t tolerance = radius * 12;
    return abs_i32((int32_t)radius_squared - target) <= tolerance;
}

static bool near_point(
    int32_t dx,
    int32_t dy,
    int32_t point_x,
    int32_t point_y,
    int32_t radius)
{
    const int32_t px = dx - point_x;
    const int32_t py = dy - point_y;
    return ((px * px) + (py * py)) <= (radius * radius);
}

static void orbit_point(
    uint32_t animation_tick,
    bool clockwise,
    int32_t radius,
    int32_t *point_x,
    int32_t *point_y)
{
    static const int16_t unit_x[8] = {
        0, 90, 127, 90, 0, -90, -127, -90};
    static const int16_t unit_y[8] = {
        -127, -90, 0, 90, 127, 90, 0, -90};
    uint32_t index = (animation_tick / UINT32_C(2)) % UINT32_C(8);
    if (!clockwise) {
        index = (UINT32_C(8) - index) % UINT32_C(8);
    }
    *point_x = ((int32_t)unit_x[index] * radius) / INT32_C(127);
    *point_y = ((int32_t)unit_y[index] * radius) / INT32_C(127);
}

static bool render_pattern_shape(
    const mw_pattern_scene_t *scene,
    int32_t dx,
    int32_t dy,
    uint32_t radius_squared,
    bool *use_accent)
{
    const int32_t ax = abs_i32(dx);
    const int32_t ay = abs_i32(dy);
    const uint32_t phase = scene->animation_tick % UINT32_C(60);
    int32_t point_x = 0;
    int32_t point_y = 0;
    int32_t tip;

    *use_accent = false;
    switch (scene->pattern) {
    case MW_PATTERN_NEUTRAL:
        return near_ring(radius_squared, INT32_C(72));
    case MW_PATTERN_PAIRING_ORBIT:
        orbit_point(scene->animation_tick, true, INT32_C(165),
                    &point_x, &point_y);
        *use_accent = near_point(dx, dy, point_x, point_y, INT32_C(20));
        return near_ring(radius_squared, INT32_C(165)) || *use_accent;
    case MW_PATTERN_CONNECTED_GLYPH:
        *use_accent = near_ring(radius_squared, INT32_C(150));
        return *use_accent ||
            ((dx < -INT32_C(10)) && (dy > -INT32_C(10)) &&
             (abs_i32(dy - (dx / INT32_C(2))) < INT32_C(14))) ||
            ((dx >= -INT32_C(10)) &&
             (abs_i32(dy + dx) < INT32_C(14)));
    case MW_PATTERN_TAP_STAR:
        *use_accent = near_ring(
            radius_squared,
            INT32_C(55) + (int32_t)(phase % UINT32_C(16)) * INT32_C(5));
        return *use_accent ||
            (((ax < INT32_C(8)) || (ay < INT32_C(8)) ||
              (abs_i32(ax - ay) < INT32_C(8))) &&
             (radius_squared < UINT32_C(25000)));
    case MW_PATTERN_TWIST_CW_SPIRAL:
        orbit_point(scene->animation_tick, true, INT32_C(95),
                    &point_x, &point_y);
        *use_accent = near_point(dx, dy, point_x, point_y, INT32_C(22)) ||
            near_point(dx, dy, -point_y / INT32_C(2),
                       point_x / INT32_C(2), INT32_C(10));
        return *use_accent || near_ring(radius_squared, INT32_C(95)) ||
            (near_ring(radius_squared, INT32_C(48)) && (dx * dy >= 0));
    case MW_PATTERN_TWIST_CCW_SPIRAL:
        *use_accent = near_ring(
            radius_squared,
            INT32_C(55) + (int32_t)(phase % UINT32_C(18)) * INT32_C(5));
        return *use_accent ||
            ((((ax < INT32_C(7)) || (ay < INT32_C(7)) ||
               (abs_i32(ax - ay) < INT32_C(7))) &&
              (radius_squared < UINT32_C(26000))) ||
             ((abs_i32(ax - (ay / INT32_C(2))) < INT32_C(6)) &&
              (radius_squared < UINT32_C(15000))));
    case MW_PATTERN_SWISH_LEFT_COMET:
    case MW_PATTERN_SWISH_RIGHT_COMET:
        tip = -INT32_C(190) + (int32_t)(phase * UINT32_C(7));
        if (scene->pattern == MW_PATTERN_SWISH_LEFT_COMET) {
            tip = -tip;
        }
        *use_accent = near_point(dx, dy, tip, 0, INT32_C(24));
        return *use_accent ||
            ((ay < INT32_C(13)) &&
             ((scene->pattern == MW_PATTERN_SWISH_RIGHT_COMET) ?
              ((dx < tip) && (dx > tip - INT32_C(150))) :
              ((dx > tip) && (dx < tip + INT32_C(150))))) ||
            ((abs_i32(dy - (dx / INT32_C(4))) < INT32_C(8)) &&
             (ax < INT32_C(130)));
    case MW_PATTERN_THRUST_BURST:
        *use_accent = near_ring(
            radius_squared,
            INT32_C(45) + (int32_t)(phase % UINT32_C(20)) * INT32_C(6));
        return *use_accent ||
            ((ax < INT32_C(9)) && (dy > -INT32_C(145)) &&
             (dy < INT32_C(80))) ||
            ((dy < -INT32_C(100)) &&
             (abs_i32(ax + dy + INT32_C(100)) < INT32_C(14)));
    case MW_PATTERN_CIRCLE_CW_ORBIT:
    case MW_PATTERN_CIRCLE_CCW_ORBIT:
        orbit_point(scene->animation_tick,
                    scene->pattern == MW_PATTERN_CIRCLE_CW_ORBIT,
                    INT32_C(175), &point_x, &point_y);
        *use_accent = near_point(dx, dy, point_x, point_y, INT32_C(24));
        return near_ring(radius_squared, INT32_C(175)) || *use_accent ||
            near_point(dx, dy, -point_x, -point_y, INT32_C(12));
    case MW_PATTERN_DISCONNECTED_LINK:
        *use_accent = near_ring(radius_squared, INT32_C(145));
        return *use_accent ||
            ((abs_i32(dx - dy) < INT32_C(13)) &&
             (ax < INT32_C(120))) ||
            ((abs_i32(dx + dy) < INT32_C(13)) &&
             (ax < INT32_C(120)));
    case MW_PATTERN_LOW_BATTERY:
        *use_accent = (dx > -INT32_C(120)) &&
            (dx < -INT32_C(100)) && (ay < INT32_C(65));
        return *use_accent ||
            (((ax > INT32_C(55)) && (ax < INT32_C(115)) &&
              (ay < INT32_C(75))) ||
             ((ay > INT32_C(55)) && (ay < INT32_C(75)) &&
              (ax < INT32_C(115)))) ||
            ((dx > -INT32_C(90)) &&
             (dx < (-INT32_C(90) +
                    ((int32_t)scene->battery_percent * INT32_C(180)) /
                        INT32_C(100))) &&
             (ay < INT32_C(48)));
    case MW_PATTERN_UNKNOWN_GLYPH:
        *use_accent = near_ring(radius_squared, INT32_C(150));
        return *use_accent ||
            ((near_ring(radius_squared, INT32_C(75)) &&
              (dy < INT32_C(20))) ||
             ((ax < INT32_C(10)) && (dy > 0) &&
              (dy < INT32_C(90))) ||
             near_point(dx, dy, 0, INT32_C(125), INT32_C(14)));
    case MW_PATTERN_FAULT_CROSS:
        *use_accent = ((scene->animation_tick & UINT32_C(1)) == 0U);
        return ((abs_i32(dx - dy) < INT32_C(18)) ||
                (abs_i32(dx + dy) < INT32_C(18))) &&
            (ax < INT32_C(145));
    default:
        return false;
    }
}

uint16_t mw_pattern_render_pixel_rgb565(
    const mw_pattern_scene_t *scene,
    uint16_t x,
    uint16_t y)
{
    int32_t dx;
    int32_t dy;
    uint32_t radius_squared;
    bool use_accent = false;
    bool foreground;

    if ((scene == NULL) || (x >= MW_PATTERN_DISPLAY_WIDTH) ||
        (y >= MW_PATTERN_DISPLAY_HEIGHT)) {
        return 0U;
    }
    dx = ((int32_t)x * INT32_C(2)) - INT32_C(239);
    dy = ((int32_t)y * INT32_C(2)) - INT32_C(239);
    radius_squared = (uint32_t)((dx * dx) + (dy * dy));
    if (radius_squared > UINT32_C(56644)) {
        return 0U;
    }
    foreground = render_pattern_shape(scene, dx, dy, radius_squared,
                                      &use_accent);
    if (!foreground) {
        return rgb565(scene->background);
    }
    return rgb565(use_accent ? scene->accent : scene->primary);
}

bool mw_pattern_render_row_rgb565(
    const mw_pattern_scene_t *scene,
    uint16_t y,
    uint16_t row_out[MW_PATTERN_DISPLAY_WIDTH])
{
    uint16_t x;
    if ((scene == NULL) || (row_out == NULL) ||
        (y >= MW_PATTERN_DISPLAY_HEIGHT)) {
        return false;
    }
    for (x = 0U; x < MW_PATTERN_DISPLAY_WIDTH; ++x) {
        row_out[x] = mw_pattern_render_pixel_rgb565(scene, x, y);
    }
    return true;
}
