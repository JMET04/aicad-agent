#ifndef MW_GESTURE_H
#define MW_GESTURE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_GESTURE_WINDOW_MIN_SAMPLES ((size_t)16)
#define MW_GESTURE_WINDOW_MAX_SAMPLES ((size_t)64)
#define MW_GESTURE_END_STATIONARY_SAMPLES ((size_t)6)
#define MW_GESTURE_REFRACTORY_MS UINT32_C(250)
#define MW_GESTURE_EVENT_PAYLOAD_BYTES ((size_t)2)
#define MW_GESTURE_MIN_CONFIDENCE_PERCENT UINT8_C(70)

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

typedef struct {
    mw_imu_sample_t samples[MW_GESTURE_WINDOW_MAX_SAMPLES];
    size_t sample_count;
    uint32_t last_emit_ms;
    bool capturing;
    bool has_emitted;
} mw_gesture_stream_t;

/*
 * Classifies short relative-motion windows only. It does not estimate
 * absolute position or an exact free-space trajectory.
 */
mw_gesture_result_t mw_gesture_classify_relative_window(
    const mw_imu_sample_t *samples,
    size_t sample_count);

/*
 * Streaming segmenter. Samples are accepted only while physical_arm_active is
 * true. A true return value means result_out contains one accepted gesture.
 */
void mw_gesture_stream_init(mw_gesture_stream_t *stream);
bool mw_gesture_stream_push(
    mw_gesture_stream_t *stream,
    const mw_imu_sample_t *sample,
    bool physical_arm_active,
    uint32_t now_ms,
    mw_gesture_result_t *result_out);

bool mw_gesture_encode_event(
    const mw_gesture_result_t *result,
    uint8_t payload_out[MW_GESTURE_EVENT_PAYLOAD_BYTES]);
bool mw_gesture_decode_event(
    const uint8_t payload[MW_GESTURE_EVENT_PAYLOAD_BYTES],
    mw_gesture_result_t *result_out);

#ifdef __cplusplus
}
#endif

#endif
