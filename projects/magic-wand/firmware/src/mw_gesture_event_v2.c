#include "mw_gesture_event_v2.h"

#include <string.h>

static void put_u32_be(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)(value >> 24U);
    output[1] = (uint8_t)(value >> 16U);
    output[2] = (uint8_t)(value >> 8U);
    output[3] = (uint8_t)value;
}

static uint32_t get_u32_be(const uint8_t *input)
{
    return ((uint32_t)input[0] << 24U) |
        ((uint32_t)input[1] << 16U) |
        ((uint32_t)input[2] << 8U) |
        (uint32_t)input[3];
}

static bool event_is_valid(const mw_gesture_event_v2_t *event)
{
    const bool battery_known =
        (event != NULL) &&
        ((event->status_flags & MW_EVENT_STATUS_BATTERY_KNOWN) != 0U);

    return (event != NULL) &&
        (event->device_id != UINT32_C(0)) &&
        (event->session_id != UINT32_C(0)) &&
        (event->logical_channel < MW_LOGICAL_CHANNEL_COUNT) &&
        (event->gesture_id > MW_GESTURE_NONE) &&
        (event->gesture_id <= MW_GESTURE_CIRCLE_CCW) &&
        (event->confidence_percent >= MW_GESTURE_MIN_CONFIDENCE_PERCENT) &&
        (event->confidence_percent <= UINT8_C(100)) &&
        ((event->status_flags & (uint8_t)~MW_EVENT_STATUS_ALLOWED_MASK) == 0U) &&
        ((battery_known && event->battery_percent <= UINT8_C(100)) ||
         (!battery_known &&
          event->battery_percent == MW_BATTERY_PERCENT_UNKNOWN));
}

bool mw_gesture_event_v2_encode(
    const mw_gesture_event_v2_t *event,
    uint8_t payload_out[MW_GESTURE_EVENT_V2_BYTES])
{
    if (payload_out != NULL) {
        (void)memset(payload_out, 0, MW_GESTURE_EVENT_V2_BYTES);
    }
    if (!event_is_valid(event) || payload_out == NULL) {
        return false;
    }

    payload_out[0] = MW_GESTURE_EVENT_V2_SCHEMA;
    payload_out[1] = event->logical_channel;
    payload_out[2] = (uint8_t)event->gesture_id;
    payload_out[3] = event->confidence_percent;
    payload_out[4] = event->battery_percent;
    payload_out[5] = event->status_flags;
    put_u32_be(&payload_out[6], event->device_id);
    put_u32_be(&payload_out[10], event->session_id);
    return true;
}

bool mw_gesture_event_v2_decode(
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES],
    mw_gesture_event_v2_t *event_out)
{
    mw_gesture_event_v2_t candidate;

    if (event_out != NULL) {
        (void)memset(event_out, 0, sizeof(*event_out));
    }
    if (payload == NULL || event_out == NULL ||
        payload[0] != MW_GESTURE_EVENT_V2_SCHEMA) {
        return false;
    }

    candidate.device_id = get_u32_be(&payload[6]);
    candidate.session_id = get_u32_be(&payload[10]);
    candidate.logical_channel = payload[1];
    candidate.gesture_id = (mw_gesture_id_t)payload[2];
    candidate.confidence_percent = payload[3];
    candidate.battery_percent = payload[4];
    candidate.status_flags = payload[5];
    if (!event_is_valid(&candidate)) {
        return false;
    }
    *event_out = candidate;
    return true;
}
