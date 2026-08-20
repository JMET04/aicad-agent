#ifndef MW_GESTURE_H
#define MW_GESTURE_H

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_GESTURE_WINDOW_MIN_SAMPLES ((size_t)16)
#define MW_GESTURE_WINDOW_MAX_SAMPLES ((size_t)64)

typedef enum {
    MW_GESTURE_NONE = 0,
    MW_GESTURE_TAP,
    MW_GESTURE_TWIST_CW,
    MW_GESTURE_TWIST_CCW,
    MW_GESTURE_SWISH_LEFT,
    MW_GESTURE_SWISH_RIGHT,
    MW_GESTURE_THRUST,
    MW_GESTURE_CIRCLE_CW,
    MW_GESTURE_CIRCLE_CCW
} mw_gesture_id_t;

typedef struct {
    float accel_x_g;
    float accel_y_g;
    float accel_z_g;
    float gyro_x_dps;
    float gyro_y_dps;
    float gyro_z_dps;
    uint16_t delta_time_ms;
} mw_imu_sample_t;

typedef struct {
    mw_gesture_id_t id;
    uint8_t confidence_percent;
    bool rejected;
} mw_gesture_result_t;

mw_gesture_result_t mw_gesture_classify_relative_window(
    const mw_imu_sample_t *samples,
    size_t sample_count);

#ifdef __cplusplus
}
#endif

#endif
