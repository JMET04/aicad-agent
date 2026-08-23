#include "mw_target_math.h"

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            (void)fprintf(stderr, "target math check failed at line %d\n", __LINE__); \
            return 1; \
        } \
    } while (false)

static bool close_float(float actual, float expected, float tolerance)
{
    return fabsf(actual - expected) <= tolerance;
}

int main(void)
{
    const float pi = 3.14159265358979323846F;
    const float accel[3] = {0.0F, MW_STANDARD_GRAVITY_MPS2, 0.0F};
    const float gyro[3] = {0.0F, pi, 0.0F};
    mw_target_calibration_t calibration = {
        .sensor_to_wand = MW_SENSOR_TO_WAND_DRAWING_CANDIDATE,
        .accel_bias_mps2 = {0.0F, 0.0F, 0.0F},
        .gyro_bias_rad_s = {0.0F, 0.0F, 0.0F},
        .axis_map_approved = true,
    };
    mw_axis_map_t reflection = {
        .row = {{1, 0, 0}, {0, 1, 0}, {0, 0, -1}},
    };
    mw_imu_sample_t sample = {0};

    CHECK(mw_axis_map_is_proper_rotation(
        &MW_SENSOR_TO_WAND_DRAWING_CANDIDATE));
    CHECK(!mw_axis_map_is_proper_rotation(&reflection));
    CHECK(mw_target_make_gesture_sample(
        accel, gyro, UINT16_C(4), &calibration, &sample));
    CHECK(close_float(sample.accel_x_g, 1.0F, 0.0001F));
    CHECK(close_float(sample.accel_y_g, 0.0F, 0.0001F));
    CHECK(close_float(sample.gyro_x_dps, 180.0F, 0.001F));
    CHECK(sample.delta_time_ms == UINT16_C(4));

    calibration.axis_map_approved = false;
    CHECK(!mw_target_make_gesture_sample(
        accel, gyro, UINT16_C(4), &calibration, &sample));
    calibration.axis_map_approved = true;
    CHECK(!mw_target_make_gesture_sample(
        accel, gyro, UINT16_C(1), &calibration, &sample));
    CHECK(!mw_target_make_gesture_sample(
        accel, gyro, UINT16_C(26), &calibration, &sample));

    return 0;
}
