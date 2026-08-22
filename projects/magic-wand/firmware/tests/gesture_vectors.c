#include "mw_gesture.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            (void)fprintf(stderr, "gesture vector check failed at line %d\n", __LINE__); \
            return 1; \
        } \
    } while (false)

static void initialize_window(mw_imu_sample_t *samples, size_t sample_count)
{
    size_t index;

    (void)memset(samples, 0, sizeof(*samples) * sample_count);
    for (index = 0U; index < sample_count; ++index) {
        samples[index].accel_z_g = 1.0F;
        samples[index].delta_time_ms = UINT16_C(5);
    }
}

static int expect_gesture(
    const mw_imu_sample_t *samples,
    size_t sample_count,
    mw_gesture_id_t expected)
{
    const mw_gesture_result_t result =
        mw_gesture_classify_relative_window(samples, sample_count);
    CHECK(!result.rejected);
    CHECK(result.id == expected);
    CHECK(result.confidence_percent >= UINT8_C(70));
    return 0;
}

static void make_twist(
    mw_imu_sample_t *samples,
    float sign)
{
    size_t index;

    initialize_window(samples, 32U);
    for (index = 0U; index < 24U; ++index) {
        samples[index].gyro_x_dps = sign * 500.0F;
    }
}

static void make_swish(
    mw_imu_sample_t *samples,
    float sign)
{
    size_t index;

    initialize_window(samples, 32U);
    for (index = 0U; index < 24U; ++index) {
        samples[index].gyro_z_dps = sign * 400.0F;
    }
}

static void make_circle(
    mw_imu_sample_t *samples,
    float direction)
{
    size_t index;

    initialize_window(samples, 48U);
    for (index = 0U; index < 8U; ++index) {
        samples[index].gyro_y_dps = 1200.0F;
    }
    for (index = 8U; index < 16U; ++index) {
        samples[index].gyro_z_dps = direction * 1200.0F;
    }
    for (index = 16U; index < 24U; ++index) {
        samples[index].gyro_y_dps = -1200.0F;
    }
    for (index = 24U; index < 32U; ++index) {
        samples[index].gyro_z_dps = direction * -1200.0F;
    }
}

static int check_direct_vectors(void)
{
    mw_imu_sample_t samples[MW_GESTURE_WINDOW_MAX_SAMPLES];
    mw_gesture_result_t result;
    size_t index;

    initialize_window(samples, 32U);
    samples[8].accel_z_g = 2.0F;
    CHECK(expect_gesture(samples, 32U, MW_GESTURE_TAP) == 0);

    make_twist(samples, 1.0F);
    CHECK(expect_gesture(samples, 32U, MW_GESTURE_TWIST_CW) == 0);
    make_twist(samples, -1.0F);
    CHECK(expect_gesture(samples, 32U, MW_GESTURE_TWIST_CCW) == 0);

    make_swish(samples, 1.0F);
    CHECK(expect_gesture(samples, 32U, MW_GESTURE_SWISH_LEFT) == 0);
    make_swish(samples, -1.0F);
    CHECK(expect_gesture(samples, 32U, MW_GESTURE_SWISH_RIGHT) == 0);

    initialize_window(samples, 32U);
    for (index = 0U; index < 24U; ++index) {
        samples[index].accel_x_g = 1.0F;
    }
    CHECK(expect_gesture(samples, 32U, MW_GESTURE_THRUST) == 0);

    make_circle(samples, 1.0F);
    CHECK(expect_gesture(samples, 48U, MW_GESTURE_CIRCLE_CW) == 0);
    make_circle(samples, -1.0F);
    CHECK(expect_gesture(samples, 48U, MW_GESTURE_CIRCLE_CCW) == 0);
    result = mw_gesture_classify_relative_window(samples, 48U);
    {
        uint8_t payload[MW_GESTURE_EVENT_PAYLOAD_BYTES] = {0U};
        mw_gesture_result_t decoded = {MW_GESTURE_NONE, 0U, true};
        CHECK(mw_gesture_encode_event(&result, payload));
        CHECK(payload[0] == (uint8_t)MW_GESTURE_CIRCLE_CCW);
        CHECK(mw_gesture_decode_event(payload, &decoded));
        CHECK(decoded.id == MW_GESTURE_CIRCLE_CCW);
        CHECK(decoded.confidence_percent == result.confidence_percent);
        payload[1] = UINT8_C(69);
        CHECK(!mw_gesture_decode_event(payload, &decoded));
    }

    initialize_window(samples, 32U);
    result = mw_gesture_classify_relative_window(samples, 32U);
    CHECK(result.rejected);
    CHECK(result.id == MW_GESTURE_NONE);

    initialize_window(samples, 32U);
    for (index = 0U; index < 24U; ++index) {
        samples[index].gyro_x_dps = 500.0F;
        samples[index].gyro_z_dps = 500.0F;
    }
    result = mw_gesture_classify_relative_window(samples, 32U);
    CHECK(result.rejected);
    CHECK(result.id == MW_GESTURE_NONE);
    return 0;
}

static int check_stream_gate_and_refractory(void)
{
    mw_imu_sample_t samples[32];
    mw_gesture_stream_t stream;
    mw_gesture_result_t result = {MW_GESTURE_NONE, 0U, true};
    mw_gesture_result_t accepted = {MW_GESTURE_NONE, 0U, true};
    uint32_t now_ms = 0U;
    bool emitted = false;
    size_t index;

    make_twist(samples, 1.0F);
    mw_gesture_stream_init(&stream);
    for (index = 0U; index < 32U; ++index) {
        now_ms += UINT32_C(5);
        CHECK(!mw_gesture_stream_push(
            &stream, &samples[index], false, now_ms, &result));
    }

    for (index = 0U; index < 32U; ++index) {
        now_ms += UINT32_C(5);
        if (mw_gesture_stream_push(
                &stream, &samples[index], true, now_ms, &result)) {
            emitted = true;
            accepted = result;
        }
    }
    CHECK(emitted);
    CHECK(accepted.id == MW_GESTURE_TWIST_CW);

    emitted = false;
    for (index = 0U; index < 32U; ++index) {
        now_ms += UINT32_C(5);
        if (mw_gesture_stream_push(
                &stream, &samples[index], true, now_ms, &result)) {
            emitted = true;
        }
    }
    CHECK(!emitted);

    now_ms += UINT32_C(300);
    for (index = 0U; index < 32U; ++index) {
        now_ms += UINT32_C(5);
        if (mw_gesture_stream_push(
                &stream, &samples[index], true, now_ms, &result)) {
            emitted = true;
            accepted = result;
        }
    }
    CHECK(emitted);
    CHECK(accepted.id == MW_GESTURE_TWIST_CW);
    return 0;
}

int main(void)
{
    CHECK(check_direct_vectors() == 0);
    CHECK(check_stream_gate_and_refractory() == 0);
    (void)puts("8 gesture vectors, rejection, arm gate and refractory passed");
    return 0;
}
