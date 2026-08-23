#ifndef MW_TARGET_MATH_H
#define MW_TARGET_MATH_H

#include "mw_gesture.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_STANDARD_GRAVITY_MPS2 9.80665F
#define MW_RADIANS_TO_DEGREES 57.29577951308232F
#define MW_TARGET_MIN_SAMPLE_DT_MS UINT16_C(2)
#define MW_TARGET_MAX_SAMPLE_DT_MS UINT16_C(25)

typedef struct {
    int8_t row[3][3];
} mw_axis_map_t;

typedef struct {
    mw_axis_map_t sensor_to_wand;
    float accel_bias_mps2[3];
    float gyro_bias_rad_s[3];
    bool axis_map_approved;
} mw_target_calibration_t;

/*
 * Drawing-derived candidate only: sensor +X/+Y/+Z -> wand -Y/+X/+Z.
 * It is a proper rotation, but target firmware must keep axis_map_approved
 * false until six-face and positive-axis rotation tests pass on a first unit.
 */
extern const mw_axis_map_t MW_SENSOR_TO_WAND_DRAWING_CANDIDATE;

bool mw_axis_map_is_proper_rotation(const mw_axis_map_t *map);

/*
 * Converts Zephyr sensor SI units (m/s^2 and rad/s) into the portable gesture
 * core's units (g and degree/s), subtracts measured bias, and applies the
 * approved signed-permutation map. Returns false without touching output when
 * timing, values, calibration, or the axis map are unsafe.
 */
bool mw_target_make_gesture_sample(
    const float accel_mps2[3],
    const float gyro_rad_s[3],
    uint16_t delta_time_ms,
    const mw_target_calibration_t *calibration,
    mw_imu_sample_t *sample_out);

#ifdef __cplusplus
}
#endif

#endif
