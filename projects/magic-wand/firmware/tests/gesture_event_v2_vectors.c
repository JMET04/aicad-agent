#include "mw_gesture_event_v2.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            (void)fprintf(stderr, "gesture event v2 check failed at line %d\n", __LINE__); \
            return 1; \
        } \
    } while (false)

int main(void)
{
    static const uint8_t expected[MW_GESTURE_EVENT_V2_BYTES] = {
        0x02U, 0x07U, 0x08U, 0x5fU, 0x49U, 0x0fU, 0x12U,
        0x34U, 0x56U, 0x78U, 0x90U, 0xabU, 0xcdU, 0xefU,
    };
    mw_gesture_event_v2_t event = {
        .device_id = UINT32_C(0x12345678),
        .session_id = UINT32_C(0x90abcdef),
        .logical_channel = UINT8_C(7),
        .gesture_id = MW_GESTURE_CIRCLE_CCW,
        .confidence_percent = UINT8_C(95),
        .battery_percent = UINT8_C(73),
        .status_flags = MW_EVENT_STATUS_ARM_ACTIVE |
            MW_EVENT_STATUS_CHG_STAT1_ASSERTED |
            MW_EVENT_STATUS_CHG_STAT2_ASSERTED |
            MW_EVENT_STATUS_BATTERY_KNOWN,
    };
    mw_gesture_event_v2_t decoded;
    uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];

    CHECK(mw_gesture_event_v2_encode(&event, payload));
    CHECK(memcmp(payload, expected, sizeof(expected)) == 0);
    CHECK(mw_gesture_event_v2_decode(payload, &decoded));
    CHECK(decoded.device_id == event.device_id);
    CHECK(decoded.session_id == event.session_id);
    CHECK(decoded.logical_channel == event.logical_channel);
    CHECK(decoded.gesture_id == event.gesture_id);
    CHECK(decoded.confidence_percent == event.confidence_percent);
    CHECK(decoded.battery_percent == event.battery_percent);
    CHECK(decoded.status_flags == event.status_flags);

    event.logical_channel = MW_LOGICAL_CHANNEL_COUNT;
    CHECK(!mw_gesture_event_v2_encode(&event, payload));
    event.logical_channel = UINT8_C(0);
    event.status_flags = UINT8_C(0x80);
    CHECK(!mw_gesture_event_v2_encode(&event, payload));
    event.status_flags = MW_EVENT_STATUS_BATTERY_KNOWN;
    event.battery_percent = MW_BATTERY_PERCENT_UNKNOWN;
    CHECK(!mw_gesture_event_v2_encode(&event, payload));
    event.status_flags = 0U;
    CHECK(mw_gesture_event_v2_encode(&event, payload));
    payload[0] = UINT8_C(1);
    CHECK(!mw_gesture_event_v2_decode(payload, &decoded));

    return 0;
}
