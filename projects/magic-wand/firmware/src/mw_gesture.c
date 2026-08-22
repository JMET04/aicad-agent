#include "mw_gesture.h"

#include <stdbool.h>
#include <string.h>

typedef struct {
    float integrated_x_deg;
    float integrated_y_deg;
    float integrated_z_deg;
    float span_y_deg;
    float span_z_deg;
    float path_yz_deg;
    float signed_area_yz_deg2;
    float mean_accel_x_g;
    float peak_norm_squared_delta;
    float end_gyro_l1_mean_dps;
    float end_norm_squared_delta_mean;
    uint32_t duration_ms;
} mw_gesture_features_t;

static float abs_float(float value)
{
    return (value < 0.0F) ? -value : value;
}

static float min_float(float left, float right)
{
    return (left < right) ? left : right;
}

static uint8_t confidence_from_margin(float normalized_margin)
{
    float confidence;

    if (normalized_margin < 0.0F) {
        normalized_margin = 0.0F;
    }
    if (normalized_margin > 1.0F) {
        normalized_margin = 1.0F;
    }
    confidence = 70.0F + (normalized_margin * 25.0F);
    return (uint8_t)confidence;
}

static bool sample_timing_valid(const mw_imu_sample_t *sample)
{
    return (sample != NULL) &&
        (sample->delta_time_ms >= UINT16_C(2)) &&
        (sample->delta_time_ms <= UINT16_C(25));
}

static float norm_squared_delta(const mw_imu_sample_t *sample)
{
    const float norm_squared =
        (sample->accel_x_g * sample->accel_x_g) +
        (sample->accel_y_g * sample->accel_y_g) +
        (sample->accel_z_g * sample->accel_z_g);
    return abs_float(norm_squared - 1.0F);
}

static float gyro_l1(const mw_imu_sample_t *sample)
{
    return abs_float(sample->gyro_x_dps) +
        abs_float(sample->gyro_y_dps) +
        abs_float(sample->gyro_z_dps);
}

static bool extract_features(
    const mw_imu_sample_t *samples,
    size_t sample_count,
    mw_gesture_features_t *features)
{
    float cumulative_y_deg = 0.0F;
    float cumulative_z_deg = 0.0F;
    float previous_y_deg = 0.0F;
    float previous_z_deg = 0.0F;
    float minimum_y_deg = 0.0F;
    float maximum_y_deg = 0.0F;
    float minimum_z_deg = 0.0F;
    float maximum_z_deg = 0.0F;
    float sum_accel_x = 0.0F;
    float end_gyro_sum = 0.0F;
    float end_norm_delta_sum = 0.0F;
    const size_t stationary_start =
        sample_count - MW_GESTURE_END_STATIONARY_SAMPLES;
    size_t index;

    if ((samples == NULL) || (features == NULL) ||
        (sample_count < MW_GESTURE_WINDOW_MIN_SAMPLES) ||
        (sample_count > MW_GESTURE_WINDOW_MAX_SAMPLES)) {
        return false;
    }

    (void)memset(features, 0, sizeof(*features));
    for (index = 0U; index < sample_count; ++index) {
        float delta_y_deg;
        float delta_z_deg;
        float current_norm_delta;
        float dt_s;

        if (!sample_timing_valid(&samples[index])) {
            return false;
        }
        dt_s = (float)samples[index].delta_time_ms / 1000.0F;
        delta_y_deg = samples[index].gyro_y_dps * dt_s;
        delta_z_deg = samples[index].gyro_z_dps * dt_s;
        previous_y_deg = cumulative_y_deg;
        previous_z_deg = cumulative_z_deg;
        cumulative_y_deg += delta_y_deg;
        cumulative_z_deg += delta_z_deg;

        features->duration_ms += (uint32_t)samples[index].delta_time_ms;
        features->integrated_x_deg += samples[index].gyro_x_dps * dt_s;
        features->path_yz_deg += abs_float(delta_y_deg) + abs_float(delta_z_deg);
        features->signed_area_yz_deg2 += 0.5F * (
            (previous_y_deg * cumulative_z_deg) -
            (cumulative_y_deg * previous_z_deg));
        sum_accel_x += samples[index].accel_x_g;
        current_norm_delta = norm_squared_delta(&samples[index]);
        if (current_norm_delta > features->peak_norm_squared_delta) {
            features->peak_norm_squared_delta = current_norm_delta;
        }

        if (cumulative_y_deg < minimum_y_deg) {
            minimum_y_deg = cumulative_y_deg;
        }
        if (cumulative_y_deg > maximum_y_deg) {
            maximum_y_deg = cumulative_y_deg;
        }
        if (cumulative_z_deg < minimum_z_deg) {
            minimum_z_deg = cumulative_z_deg;
        }
        if (cumulative_z_deg > maximum_z_deg) {
            maximum_z_deg = cumulative_z_deg;
        }
        if (index >= stationary_start) {
            end_gyro_sum += gyro_l1(&samples[index]);
            end_norm_delta_sum += current_norm_delta;
        }
    }

    features->integrated_y_deg = cumulative_y_deg;
    features->integrated_z_deg = cumulative_z_deg;
    features->span_y_deg = maximum_y_deg - minimum_y_deg;
    features->span_z_deg = maximum_z_deg - minimum_z_deg;
    features->mean_accel_x_g = sum_accel_x / (float)sample_count;
    features->end_gyro_l1_mean_dps =
        end_gyro_sum / (float)MW_GESTURE_END_STATIONARY_SAMPLES;
    features->end_norm_squared_delta_mean =
        end_norm_delta_sum / (float)MW_GESTURE_END_STATIONARY_SAMPLES;
    return true;
}

static bool features_return_to_stationary(const mw_gesture_features_t *features)
{
    return (features->end_gyro_l1_mean_dps < 60.0F) &&
        (features->end_norm_squared_delta_mean < 0.25F);
}

mw_gesture_result_t mw_gesture_classify_relative_window(
    const mw_imu_sample_t *samples,
    size_t sample_count)
{
    mw_gesture_result_t result = {MW_GESTURE_NONE, 0U, true};
    mw_gesture_features_t f;
    float quality;
    float closure_yz;
    float total_rotation;

    if (!extract_features(samples, sample_count, &f) ||
        !features_return_to_stationary(&f)) {
        return result;
    }

    closure_yz = abs_float(f.integrated_y_deg) +
        abs_float(f.integrated_z_deg);
    total_rotation = abs_float(f.integrated_x_deg) +
        abs_float(f.integrated_y_deg) +
        abs_float(f.integrated_z_deg);

    /*
     * A circle is a closed, high-area path in integrated Y/Z angular space.
     * Positive signed area maps to clockwise as viewed by the user from grip
     * toward the tip because +Y points to the user's left.
     */
    if ((f.duration_ms >= UINT32_C(180)) &&
        (f.duration_ms <= UINT32_C(450)) &&
        (f.span_y_deg > 35.0F) &&
        (f.span_z_deg > 35.0F) &&
        (f.path_yz_deg > 150.0F) &&
        (abs_float(f.signed_area_yz_deg2) > 1200.0F) &&
        (closure_yz < 35.0F) &&
        (abs_float(f.integrated_x_deg) < 35.0F)) {
        quality = (f.span_y_deg - 35.0F) / 35.0F;
        quality = min_float(quality, (f.span_z_deg - 35.0F) / 35.0F);
        quality = min_float(
            quality,
            (abs_float(f.signed_area_yz_deg2) - 1200.0F) / 1200.0F);
        quality = min_float(quality, (f.path_yz_deg - 150.0F) / 150.0F);
        quality = min_float(quality, (35.0F - closure_yz) / 35.0F);
        result.id = (f.signed_area_yz_deg2 > 0.0F) ?
            MW_GESTURE_CIRCLE_CW : MW_GESTURE_CIRCLE_CCW;
        result.confidence_percent = confidence_from_margin(quality);
        result.rejected = false;
        return result;
    }

    if ((f.duration_ms >= UINT32_C(40)) &&
        (f.duration_ms <= UINT32_C(250)) &&
        (f.peak_norm_squared_delta > 1.25F) &&
        (total_rotation < 28.0F)) {
        result.id = MW_GESTURE_TAP;
        result.confidence_percent = confidence_from_margin(
            (f.peak_norm_squared_delta - 1.25F) / 1.25F);
        result.rejected = false;
        return result;
    }

    if ((abs_float(f.integrated_x_deg) > 55.0F) &&
        (abs_float(f.integrated_y_deg) < 35.0F) &&
        (abs_float(f.integrated_z_deg) < 30.0F)) {
        result.id = (f.integrated_x_deg > 0.0F) ?
            MW_GESTURE_TWIST_CW : MW_GESTURE_TWIST_CCW;
        result.confidence_percent = confidence_from_margin(
            (abs_float(f.integrated_x_deg) - 55.0F) / 55.0F);
        result.rejected = false;
        return result;
    }

    if ((abs_float(f.integrated_z_deg) > 40.0F) &&
        (abs_float(f.integrated_x_deg) < 35.0F) &&
        (abs_float(f.integrated_y_deg) < 35.0F)) {
        result.id = (f.integrated_z_deg > 0.0F) ?
            MW_GESTURE_SWISH_LEFT : MW_GESTURE_SWISH_RIGHT;
        result.confidence_percent = confidence_from_margin(
            (abs_float(f.integrated_z_deg) - 40.0F) / 40.0F);
        result.rejected = false;
        return result;
    }

    if ((f.mean_accel_x_g > 0.60F) &&
        (f.peak_norm_squared_delta > 0.25F) &&
        (total_rotation < 35.0F)) {
        result.id = MW_GESTURE_THRUST;
        result.confidence_percent = confidence_from_margin(
            (f.mean_accel_x_g - 0.60F) / 0.60F);
        result.rejected = false;
        return result;
    }

    return result;
}

bool mw_gesture_encode_event(
    const mw_gesture_result_t *result,
    uint8_t payload_out[MW_GESTURE_EVENT_PAYLOAD_BYTES])
{
    if ((result == NULL) || (payload_out == NULL) || result->rejected ||
        (result->id <= MW_GESTURE_NONE) ||
        (result->id > MW_GESTURE_CIRCLE_CCW) ||
        (result->confidence_percent < MW_GESTURE_MIN_CONFIDENCE_PERCENT) ||
        (result->confidence_percent > UINT8_C(100))) {
        return false;
    }
    payload_out[0] = (uint8_t)result->id;
    payload_out[1] = result->confidence_percent;
    return true;
}

bool mw_gesture_decode_event(
    const uint8_t payload[MW_GESTURE_EVENT_PAYLOAD_BYTES],
    mw_gesture_result_t *result_out)
{
    if (result_out != NULL) {
        result_out->id = MW_GESTURE_NONE;
        result_out->confidence_percent = 0U;
        result_out->rejected = true;
    }
    if ((payload == NULL) || (result_out == NULL) ||
        (payload[0] <= (uint8_t)MW_GESTURE_NONE) ||
        (payload[0] > (uint8_t)MW_GESTURE_CIRCLE_CCW) ||
        (payload[1] < MW_GESTURE_MIN_CONFIDENCE_PERCENT) ||
        (payload[1] > UINT8_C(100))) {
        return false;
    }
    result_out->id = (mw_gesture_id_t)payload[0];
    result_out->confidence_percent = payload[1];
    result_out->rejected = false;
    return true;
}

static bool sample_is_motion(const mw_imu_sample_t *sample)
{
    return (gyro_l1(sample) > 100.0F) ||
        (norm_squared_delta(sample) > 0.30F) ||
        (abs_float(sample->accel_x_g) > 0.45F);
}

static bool ending_is_stationary(const mw_gesture_stream_t *stream)
{
    float gyro_sum = 0.0F;
    float norm_delta_sum = 0.0F;
    size_t index;
    const size_t start =
        stream->sample_count - MW_GESTURE_END_STATIONARY_SAMPLES;

    for (index = start; index < stream->sample_count; ++index) {
        gyro_sum += gyro_l1(&stream->samples[index]);
        norm_delta_sum += norm_squared_delta(&stream->samples[index]);
    }
    return (gyro_sum / (float)MW_GESTURE_END_STATIONARY_SAMPLES < 60.0F) &&
        (norm_delta_sum / (float)MW_GESTURE_END_STATIONARY_SAMPLES < 0.25F);
}

static void reset_capture(mw_gesture_stream_t *stream)
{
    stream->sample_count = 0U;
    stream->capturing = false;
}

void mw_gesture_stream_init(mw_gesture_stream_t *stream)
{
    if (stream != NULL) {
        (void)memset(stream, 0, sizeof(*stream));
    }
}

bool mw_gesture_stream_push(
    mw_gesture_stream_t *stream,
    const mw_imu_sample_t *sample,
    bool physical_arm_active,
    uint32_t now_ms,
    mw_gesture_result_t *result_out)
{
    bool should_finish;
    bool outside_refractory;

    if (result_out != NULL) {
        result_out->id = MW_GESTURE_NONE;
        result_out->confidence_percent = 0U;
        result_out->rejected = true;
    }
    if ((stream == NULL) || (sample == NULL) || (result_out == NULL) ||
        !sample_timing_valid(sample)) {
        return false;
    }
    if (!physical_arm_active) {
        reset_capture(stream);
        return false;
    }

    if (!stream->capturing) {
        if (!sample_is_motion(sample)) {
            return false;
        }
        stream->capturing = true;
        stream->sample_count = 0U;
    }

    stream->samples[stream->sample_count] = *sample;
    stream->sample_count++;
    should_finish =
        (stream->sample_count == MW_GESTURE_WINDOW_MAX_SAMPLES) ||
        ((stream->sample_count >= MW_GESTURE_WINDOW_MIN_SAMPLES) &&
         ending_is_stationary(stream));
    if (!should_finish) {
        return false;
    }

    *result_out = mw_gesture_classify_relative_window(
        stream->samples,
        stream->sample_count);
    reset_capture(stream);
    outside_refractory = !stream->has_emitted ||
        ((uint32_t)(now_ms - stream->last_emit_ms) >=
         MW_GESTURE_REFRACTORY_MS);
    if (result_out->rejected || !outside_refractory) {
        result_out->id = MW_GESTURE_NONE;
        result_out->confidence_percent = 0U;
        result_out->rejected = true;
        return false;
    }

    stream->last_emit_ms = now_ms;
    stream->has_emitted = true;
    return true;
}
