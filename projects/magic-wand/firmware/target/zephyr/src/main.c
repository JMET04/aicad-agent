#include "mw_board_pins.h"
#include "mw_gesture.h"
#include "mw_gesture_event_v2.h"
#include "mw_target_math.h"

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/haptics.h>
#include <zephyr/drivers/haptics/drv2605.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>

LOG_MODULE_REGISTER(magic_wand_target, LOG_LEVEL_INF);

#define MW_GYRO_CALIBRATION_SAMPLES UINT16_C(480)
#define MW_WATCHDOG_TIMEOUT_MS UINT32_C(1000)

#define MW_ARM_NODE DT_ALIAS(mw_arm)
#define MW_CHG_STAT1_NODE DT_ALIAS(mw_chg_stat1)
#define MW_CHG_STAT2_NODE DT_ALIAS(mw_chg_stat2)
#define MW_IMU_NODE DT_ALIAS(mw_imu)
#define MW_HAPTIC_NODE DT_ALIAS(mw_haptic)

BUILD_ASSERT(DT_SAME_NODE(DT_GPIO_CTLR(MW_ARM_NODE, gpios), DT_NODELABEL(gpio0)));
BUILD_ASSERT(DT_GPIO_PIN(MW_ARM_NODE, gpios) == MW_ARM_N_GPIO_PIN);
BUILD_ASSERT(DT_SAME_NODE(DT_GPIO_CTLR(MW_CHG_STAT1_NODE, gpios), DT_NODELABEL(gpio0)));
BUILD_ASSERT(DT_GPIO_PIN(MW_CHG_STAT1_NODE, gpios) == MW_CHG_STAT1_N_GPIO_PIN);
BUILD_ASSERT(DT_SAME_NODE(DT_GPIO_CTLR(MW_CHG_STAT2_NODE, gpios), DT_NODELABEL(gpio0)));
BUILD_ASSERT(DT_GPIO_PIN(MW_CHG_STAT2_NODE, gpios) == MW_CHG_STAT2_N_GPIO_PIN);
BUILD_ASSERT(DT_SAME_NODE(DT_GPIO_CTLR(MW_IMU_NODE, int1_gpios), DT_NODELABEL(gpio0)));
BUILD_ASSERT(DT_GPIO_PIN(MW_IMU_NODE, int1_gpios) == MW_IMU_INT1_GPIO_PIN);

static const struct gpio_dt_spec arm_input = GPIO_DT_SPEC_GET(MW_ARM_NODE, gpios);
static const struct gpio_dt_spec chg_stat1_input = GPIO_DT_SPEC_GET(MW_CHG_STAT1_NODE, gpios);
static const struct gpio_dt_spec chg_stat2_input = GPIO_DT_SPEC_GET(MW_CHG_STAT2_NODE, gpios);
static const struct device *const imu = DEVICE_DT_GET(MW_IMU_NODE);
static const struct device *const watchdog = DEVICE_DT_GET(DT_ALIAS(watchdog0));

K_SEM_DEFINE(imu_data_ready, 0, 1);

/*
 * A security/radio integration must provide a strong implementation that
 * queues exactly this versioned event inside the authenticated protocol path.
 * The hardware target deliberately has no raw BLE/802.15.4 fallback.
 */
__weak int mw_target_get_authenticated_identity(
    uint32_t *device_id,
    uint32_t *session_id,
    uint8_t *logical_channel)
{
    if (device_id != NULL) {
        *device_id = 0U;
    }
    if (session_id != NULL) {
        *session_id = 0U;
    }
    if (logical_channel != NULL) {
        *logical_channel = MW_LOGICAL_CHANNEL_COUNT;
    }
    return -ENOTSUP;
}

__weak int mw_target_read_battery_percent(uint8_t *battery_percent)
{
    if (battery_percent != NULL) {
        *battery_percent = MW_BATTERY_PERCENT_UNKNOWN;
    }
    return -ENOTSUP;
}

__weak int mw_target_secure_queue_gesture_event_v2(
    const uint8_t payload[MW_GESTURE_EVENT_V2_BYTES])
{
    ARG_UNUSED(payload);
    return -ENOTSUP;
}

static void imu_trigger_handler(
    const struct device *device,
    const struct sensor_trigger *trigger)
{
    ARG_UNUSED(device);
    ARG_UNUSED(trigger);
    k_sem_give(&imu_data_ready);
}

static int configure_input(const struct gpio_dt_spec *input)
{
    if (!gpio_is_ready_dt(input)) {
        return -ENODEV;
    }
    return gpio_pin_configure_dt(input, GPIO_INPUT);
}

static int read_input(const struct gpio_dt_spec *input, bool *active)
{
    const int value = gpio_pin_get_dt(input);

    if (value < 0) {
        return value;
    }
    *active = value != 0;
    return 0;
}

static int configure_watchdog(void)
{
    const struct wdt_timeout_cfg timeout = {
        .window = {
            .min = 0U,
            .max = MW_WATCHDOG_TIMEOUT_MS,
        },
        .callback = NULL,
        .flags = WDT_FLAG_RESET_SOC,
    };
    int channel;
    int result;

    if (!device_is_ready(watchdog)) {
        return -ENODEV;
    }
    channel = wdt_install_timeout(watchdog, &timeout);
    if (channel < 0) {
        return channel;
    }
    result = wdt_setup(watchdog, WDT_OPT_PAUSE_HALTED_BY_DBG);
    if (result < 0) {
        return result;
    }
    return channel;
}

static int fetch_imu(float accel_mps2[3], float gyro_rad_s[3])
{
    struct sensor_value accel[3];
    struct sensor_value gyro[3];
    size_t axis;
    int result;

    result = sensor_sample_fetch(imu);
    if (result < 0) {
        return result;
    }
    result = sensor_channel_get(imu, SENSOR_CHAN_ACCEL_XYZ, accel);
    if (result < 0) {
        return result;
    }
    result = sensor_channel_get(imu, SENSOR_CHAN_GYRO_XYZ, gyro);
    if (result < 0) {
        return result;
    }
    for (axis = 0U; axis < 3U; ++axis) {
        accel_mps2[axis] = (float)sensor_value_to_double(&accel[axis]);
        gyro_rad_s[axis] = (float)sensor_value_to_double(&gyro[axis]);
    }
    return 0;
}

static bool stationary_for_gyro_calibration(
    const float accel_mps2[3],
    const float gyro_rad_s[3])
{
    const float gravity_squared =
        MW_STANDARD_GRAVITY_MPS2 * MW_STANDARD_GRAVITY_MPS2;
    const float accel_squared =
        (accel_mps2[0] * accel_mps2[0]) +
        (accel_mps2[1] * accel_mps2[1]) +
        (accel_mps2[2] * accel_mps2[2]);
    const float gyro_l1 =
        ((gyro_rad_s[0] < 0.0F) ? -gyro_rad_s[0] : gyro_rad_s[0]) +
        ((gyro_rad_s[1] < 0.0F) ? -gyro_rad_s[1] : gyro_rad_s[1]) +
        ((gyro_rad_s[2] < 0.0F) ? -gyro_rad_s[2] : gyro_rad_s[2]);

    return (accel_squared > (0.64F * gravity_squared)) &&
        (accel_squared < (1.44F * gravity_squared)) &&
        (gyro_l1 < 0.35F);
}

static int play_haptic(mw_gesture_id_t gesture)
{
#if DT_NODE_HAS_STATUS(MW_HAPTIC_NODE, okay)
    static const uint8_t effect_by_gesture[] = {
        0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U,
    };
    const struct device *const haptic = DEVICE_DT_GET(MW_HAPTIC_NODE);
    struct drv2605_rom_data rom = {0};
    const union drv2605_config_data config = {.rom_data = &rom};
    int result;

    BUILD_ASSERT(IS_ENABLED(CONFIG_MW_C08_005_ACTUATOR_APPROVED));
    BUILD_ASSERT(DT_PROP(MW_HAPTIC_NODE, vib_rated_mv) == 1850);
    BUILD_ASSERT(DT_PROP(MW_HAPTIC_NODE, vib_overdrive_mv) == 1850);

    if (!device_is_ready(haptic) ||
        (gesture <= MW_GESTURE_NONE) ||
        ((size_t)gesture >= ARRAY_SIZE(effect_by_gesture))) {
        return -ENODEV;
    }
    rom.trigger = DRV2605_MODE_INTERNAL_TRIGGER;
    rom.library = DRV2605_LIBRARY_LRA;
    rom.seq_regs[0] = effect_by_gesture[(size_t)gesture];
    result = drv2605_haptic_config(
        haptic, DRV2605_HAPTICS_SOURCE_ROM, &config);
    if (result < 0) {
        return result;
    }
    return haptics_start_output(haptic);
#else
    ARG_UNUSED(gesture);
    return -ENODEV;
#endif
}

int main(void)
{
    const struct sensor_trigger trigger = {
        .type = SENSOR_TRIG_DATA_READY,
        .chan = SENSOR_CHAN_ACCEL_XYZ,
    };
    mw_target_calibration_t calibration = {0};
    mw_gesture_stream_t stream;
    float gyro_bias_sum[3] = {0.0F, 0.0F, 0.0F};
    uint16_t calibration_count = 0U;
    uint32_t previous_sample_ms = 0U;
    bool axis_gate_reported = false;
    bool previous_stat1 = false;
    bool previous_stat2 = false;
    bool have_charge_state = false;
    int watchdog_channel;
    int result;

    calibration.sensor_to_wand = MW_SENSOR_TO_WAND_DRAWING_CANDIDATE;
    calibration.axis_map_approved = IS_ENABLED(CONFIG_MW_AXIS_MAP_APPROVED);
    mw_gesture_stream_init(&stream);

    result = configure_input(&arm_input);
    result = (result < 0) ? result : configure_input(&chg_stat1_input);
    result = (result < 0) ? result : configure_input(&chg_stat2_input);
    if (result < 0 || !device_is_ready(imu)) {
        LOG_ERR("GPIO/IMU target binding is not ready (%d)", result);
        return -ENODEV;
    }

    watchdog_channel = configure_watchdog();
    if (watchdog_channel < 0) {
        LOG_ERR("watchdog setup failed (%d)", watchdog_channel);
        return watchdog_channel;
    }
    result = sensor_trigger_set(imu, &trigger, imu_trigger_handler);
    if (result < 0) {
        LOG_ERR("IMU data-ready trigger setup failed (%d)", result);
        return result;
    }

    LOG_INF("target ready; secure sink, axis map, and actuator gates fail closed");
    for (;;) {
        float accel_mps2[3];
        float gyro_rad_s[3];
        mw_imu_sample_t sample;
        mw_gesture_result_t gesture;
        bool arm_active;
        bool stat1_active;
        bool stat2_active;
        uint32_t now_ms;
        uint32_t elapsed_ms;
        mw_gesture_event_v2_t event = {0};
        uint8_t payload[MW_GESTURE_EVENT_V2_BYTES];
        size_t axis;

        result = k_sem_take(&imu_data_ready, K_MSEC(100));
        (void)wdt_feed(watchdog, watchdog_channel);
        if (result < 0) {
            mw_gesture_stream_init(&stream);
            previous_sample_ms = 0U;
            LOG_WRN("IMU data-ready timeout");
            continue;
        }
        if (fetch_imu(accel_mps2, gyro_rad_s) < 0 ||
            read_input(&arm_input, &arm_active) < 0 ||
            read_input(&chg_stat1_input, &stat1_active) < 0 ||
            read_input(&chg_stat2_input, &stat2_active) < 0) {
            mw_gesture_stream_init(&stream);
            previous_sample_ms = 0U;
            LOG_ERR("sensor/input sample failed");
            continue;
        }

        if (!have_charge_state ||
            stat1_active != previous_stat1 || stat2_active != previous_stat2) {
            /* Raw active-low status only; no undocumented charger-state guess. */
            LOG_INF("charger STAT1_N asserted=%d STAT2_N asserted=%d",
                stat1_active, stat2_active);
            previous_stat1 = stat1_active;
            previous_stat2 = stat2_active;
            have_charge_state = true;
        }

        if (calibration_count < MW_GYRO_CALIBRATION_SAMPLES) {
            if (arm_active ||
                !stationary_for_gyro_calibration(accel_mps2, gyro_rad_s)) {
                calibration_count = 0U;
                gyro_bias_sum[0] = 0.0F;
                gyro_bias_sum[1] = 0.0F;
                gyro_bias_sum[2] = 0.0F;
                continue;
            }
            for (axis = 0U; axis < 3U; ++axis) {
                gyro_bias_sum[axis] += gyro_rad_s[axis];
            }
            calibration_count++;
            if (calibration_count == MW_GYRO_CALIBRATION_SAMPLES) {
                for (axis = 0U; axis < 3U; ++axis) {
                    calibration.gyro_bias_rad_s[axis] =
                        gyro_bias_sum[axis] /
                        (float)MW_GYRO_CALIBRATION_SAMPLES;
                }
                LOG_INF("stationary gyro bias captured; axis HIL gate=%d",
                    calibration.axis_map_approved);
            }
            continue;
        }

        if (!arm_active) {
            mw_gesture_stream_init(&stream);
            previous_sample_ms = 0U;
            continue;
        }
        if (!calibration.axis_map_approved) {
            if (!axis_gate_reported) {
                LOG_ERR("axis map is unapproved; gesture classification disabled");
                axis_gate_reported = true;
            }
            mw_gesture_stream_init(&stream);
            continue;
        }

        now_ms = k_uptime_get_32();
        if (previous_sample_ms == 0U) {
            previous_sample_ms = now_ms;
            continue;
        }
        elapsed_ms = now_ms - previous_sample_ms;
        previous_sample_ms = now_ms;
        if (elapsed_ms > UINT16_MAX ||
            !mw_target_make_gesture_sample(
                accel_mps2,
                gyro_rad_s,
                (uint16_t)elapsed_ms,
                &calibration,
                &sample)) {
            mw_gesture_stream_init(&stream);
            continue;
        }

        if (!mw_gesture_stream_push(
                &stream, &sample, true, now_ms, &gesture)) {
            continue;
        }
        event.gesture_id = gesture.id;
        event.confidence_percent = gesture.confidence_percent;
        event.battery_percent = MW_BATTERY_PERCENT_UNKNOWN;
        event.status_flags = MW_EVENT_STATUS_ARM_ACTIVE;
        if (stat1_active) {
            event.status_flags |= MW_EVENT_STATUS_CHG_STAT1_ASSERTED;
        }
        if (stat2_active) {
            event.status_flags |= MW_EVENT_STATUS_CHG_STAT2_ASSERTED;
        }
        result = mw_target_get_authenticated_identity(
            &event.device_id, &event.session_id, &event.logical_channel);
        if (result < 0) {
            LOG_WRN("authenticated identity unavailable (%d)", result);
            continue;
        }
        result = mw_target_read_battery_percent(&event.battery_percent);
        if (result == 0 && event.battery_percent <= UINT8_C(100)) {
            event.status_flags |= MW_EVENT_STATUS_BATTERY_KNOWN;
        } else {
            event.battery_percent = MW_BATTERY_PERCENT_UNKNOWN;
        }
        if (!mw_gesture_event_v2_encode(&event, payload)) {
            LOG_ERR("V2 event metadata rejected");
            continue;
        }
        result = mw_target_secure_queue_gesture_event_v2(payload);
        if (result == 0) {
            const int haptic_result = play_haptic(gesture.id);
            if (haptic_result < 0 && haptic_result != -ENODEV) {
                LOG_WRN("local haptic feedback failed (%d)", haptic_result);
            }
        } else {
            LOG_WRN("secure gesture sink rejected event (%d)", result);
        }
    }
}
