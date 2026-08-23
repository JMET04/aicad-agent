#ifndef MW_GESTURE_EVENT_V2_H
#define MW_GESTURE_EVENT_V2_H

#include "mw_gesture.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_GESTURE_EVENT_V2_SCHEMA UINT8_C(2)
#define MW_GESTURE_EVENT_V2_BYTES ((size_t)14)
#define MW_LOGICAL_CHANNEL_COUNT UINT8_C(8)
#define MW_BATTERY_PERCENT_UNKNOWN UINT8_C(255)

#define MW_EVENT_STATUS_ARM_ACTIVE UINT8_C(0x01)
#define MW_EVENT_STATUS_CHG_STAT1_ASSERTED UINT8_C(0x02)
#define MW_EVENT_STATUS_CHG_STAT2_ASSERTED UINT8_C(0x04)
#define MW_EVENT_STATUS_BATTERY_KNOWN UINT8_C(0x08)
#define MW_EVENT_STATUS_ALLOWED_MASK UINT8_C(0x0f)

/*
 * Version-2 authenticated gesture payload. logical_channel is zero-based
 * (0..7). Integers are encoded big-endian to match mw_protocol nonce/AAD.
 * The device/session duplication lets a receiver verify that the decrypted
 * payload is bound to the authenticated frame header before channel routing.
 */
typedef struct {
    uint32_t device_id;
    uint32_t session_id;
    uint8_t logical_channel;
    mw_gesture_id_t gesture_id;
    uint8_t confidence_percent;
    uint8_t battery_percent;
    uint8_t status_flags;
} mw_gesture_event_v2_t;

bool mw_gesture_event_v2_encode(
    const mw_gesture_event_v2_t *event,
    uint8_t payload_out[MW_GESTURE_EVENT_V2_BYTES]);

bool mw_gesture_event_v2_decode(
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES],
    mw_gesture_event_v2_t *event_out);

#ifdef __cplusplus
}
#endif

#endif
