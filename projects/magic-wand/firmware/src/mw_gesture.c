#include "mw_gesture.h"

#include <stdbool.h>

static float abs_float(float value)
{
    return (value < 0.0F) ? -value : value;
}

static uint8_t confidence_from_margin(float margin, float full_scale)
{
    float confidence = 60.0F + ((margin / full_scale) * 35.0F);
    if (confidence < 0.0F) {
        confidence = 0.0F;
    }
    if (confidence > 95.0F) {
        confidence = 95.0F;
    }
    return (uint8_t)confidence;
}

mw_gesture_result_t mw_gesture_classify_relative_window(
    const mw_imu_sample_t *samples,
    size_t sample_count)
{
    mw_gesture_result_t result = {MW_GESTURE_NONE, 0U, true};
    float integrated_x_deg = 0.0F;
    float integrated_z_deg = 0.0F;
    float sum_accel_x = 0.0F;
    float peak_norm_delta = 0.0F;
    uint32_t duration_ms = 0U;
    size_t index;

    if ((samples == NULL) || (sample_count < MW_GESTURE_WINDOW_MIN_SAMPLES) ||
        (sample_count > MW_GESTURE_WINDOW_MAX_SAMPLES)) {
        return result;
    }

    for (index = 0U; index < sample_count; ++index) {
        const float dt_s = (float)samples[index].delta_time_ms / 1000.0F;
        const float norm_squared =
            (samples[index].accel_x_g * samples[index].accel_x_g) +
            (samples[index].accel_y_g * samples[index].accel_y_g) +
            (samples[index].accel_z_g * samples[index].accel_z_g);
        const float norm_delta = abs_float(norm_squared - 1.0F);

        duration_ms += (uint32_t)samples[index].delta_time_ms;
        integrated_x_deg += samples[index].gyro_x_dps * dt_s;
        integrated_z_deg += samples[index].gyro_z_dps * dt_s;
        sum_accel_x += samples[index].accel_x_g;
        if (norm_delta > peak_norm_delta) {
            peak_norm_delta = norm_delta;
        }
    }

    if ((duration_ms >= 40U) && (duration_ms <= 250U) &&
        (peak_norm_delta > 1.25F)) {
        result.id = MW_GESTURE_TAP;
        result.confidence_percent = confidence_from_margin(
            peak_norm_delta - 1.25F, 1.25F);
        result.rejected = false;
        return result;
    }

    if ((abs_float(integrated_x_deg) > 55.0F) &&
        (abs_float(integrated_z_deg) < 30.0F)) {
        result.id = (integrated_x_deg > 0.0F) ?
            MW_GESTURE_TWIST_CW : MW_GESTURE_TWIST_CCW;
        result.confidence_percent = confidence_from_margin(
            abs_float(integrated_x_deg) - 55.0F, 55.0F);
        result.rejected = false;
        return result;
    }

    if ((abs_float(integrated_z_deg) > 40.0F) &&
        (abs_float(integrated_x_deg) < 35.0F)) {
        result.id = (integrated_z_deg > 0.0F) ?
            MW_GESTURE_SWISH_LEFT : MW_GESTURE_SWISH_RIGHT;
        result.confidence_percent = confidence_from_margin(
            abs_float(integrated_z_deg) - 40.0F, 40.0F);
        result.rejected = false;
        return result;
    }

    if ((sum_accel_x / (float)sample_count) > 0.60F) {
        result.id = MW_GESTURE_THRUST;
        result.confidence_percent = confidence_from_margin(
            (sum_accel_x / (float)sample_count) - 0.60F, 0.60F);
        result.rejected = false;
        return result;
    }

    /* Circle classes require a validated temporal model and remain disabled. */
    return result;
}
