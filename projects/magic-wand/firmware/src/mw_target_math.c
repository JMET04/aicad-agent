#include "mw_target_math.h"

#include <float.h>
#include <stddef.h>

const mw_axis_map_t MW_SENSOR_TO_WAND_DRAWING_CANDIDATE = {
    .row = {
        {0, 1, 0},
        {-1, 0, 0},
        {0, 0, 1},
    },
};

static bool finite_float(float value)
{
    return (value <= FLT_MAX) && (value >= -FLT_MAX);
}

static int determinant(const mw_axis_map_t *map)
{
    const int a = (int)map->row[0][0];
    const int b = (int)map->row[0][1];
    const int c = (int)map->row[0][2];
    const int d = (int)map->row[1][0];
    const int e = (int)map->row[1][1];
    const int f = (int)map->row[1][2];
    const int g = (int)map->row[2][0];
    const int h = (int)map->row[2][1];
    const int i = (int)map->row[2][2];

    return (a * ((e * i) - (f * h))) -
        (b * ((d * i) - (f * g))) +
        (c * ((d * h) - (e * g)));
}

bool mw_axis_map_is_proper_rotation(const mw_axis_map_t *map)
{
    size_t row;
    size_t column;

    if (map == NULL) {
        return false;
    }

    for (row = 0U; row < 3U; ++row) {
        unsigned int nonzero = 0U;
        for (column = 0U; column < 3U; ++column) {
            const int value = (int)map->row[row][column];
            if ((value < -1) || (value > 1)) {
                return false;
            }
            if (value != 0) {
                nonzero++;
            }
        }
        if (nonzero != 1U) {
            return false;
        }
    }

    for (column = 0U; column < 3U; ++column) {
        unsigned int nonzero = 0U;
        for (row = 0U; row < 3U; ++row) {
            if (map->row[row][column] != 0) {
                nonzero++;
            }
        }
        if (nonzero != 1U) {
            return false;
        }
    }

    return determinant(map) == 1;
}

static void apply_map(
    const mw_axis_map_t *map,
    const float input[3],
    float output[3])
{
    size_t row;
    size_t column;

    for (row = 0U; row < 3U; ++row) {
        output[row] = 0.0F;
        for (column = 0U; column < 3U; ++column) {
            output[row] += (float)map->row[row][column] * input[column];
        }
    }
}

bool mw_target_make_gesture_sample(
    const float accel_mps2[3],
    const float gyro_rad_s[3],
    uint16_t delta_time_ms,
    const mw_target_calibration_t *calibration,
    mw_imu_sample_t *sample_out)
{
    float corrected_accel[3];
    float corrected_gyro[3];
    float wand_accel[3];
    float wand_gyro[3];
    size_t axis;

    if ((accel_mps2 == NULL) || (gyro_rad_s == NULL) ||
        (calibration == NULL) || (sample_out == NULL) ||
        !calibration->axis_map_approved ||
        !mw_axis_map_is_proper_rotation(&calibration->sensor_to_wand) ||
        (delta_time_ms < MW_TARGET_MIN_SAMPLE_DT_MS) ||
        (delta_time_ms > MW_TARGET_MAX_SAMPLE_DT_MS)) {
        return false;
    }

    for (axis = 0U; axis < 3U; ++axis) {
        if (!finite_float(accel_mps2[axis]) ||
            !finite_float(gyro_rad_s[axis]) ||
            !finite_float(calibration->accel_bias_mps2[axis]) ||
            !finite_float(calibration->gyro_bias_rad_s[axis])) {
            return false;
        }
        corrected_accel[axis] =
            accel_mps2[axis] - calibration->accel_bias_mps2[axis];
        corrected_gyro[axis] =
            gyro_rad_s[axis] - calibration->gyro_bias_rad_s[axis];
    }

    apply_map(&calibration->sensor_to_wand, corrected_accel, wand_accel);
    apply_map(&calibration->sensor_to_wand, corrected_gyro, wand_gyro);

    sample_out->accel_x_g = wand_accel[0] / MW_STANDARD_GRAVITY_MPS2;
    sample_out->accel_y_g = wand_accel[1] / MW_STANDARD_GRAVITY_MPS2;
    sample_out->accel_z_g = wand_accel[2] / MW_STANDARD_GRAVITY_MPS2;
    sample_out->gyro_x_dps = wand_gyro[0] * MW_RADIANS_TO_DEGREES;
    sample_out->gyro_y_dps = wand_gyro[1] * MW_RADIANS_TO_DEGREES;
    sample_out->gyro_z_dps = wand_gyro[2] * MW_RADIANS_TO_DEGREES;
    sample_out->delta_time_ms = delta_time_ms;
    return true;
}
