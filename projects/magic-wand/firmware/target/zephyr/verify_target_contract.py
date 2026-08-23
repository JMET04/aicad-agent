#!/usr/bin/env python3
"""Offline authority-to-target contract check; never builds or flashes hardware."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone


SCRIPT = Path(__file__).resolve()
ZEPHYR_APP = SCRIPT.parent
FIRMWARE = ZEPHYR_APP.parents[1]
REPO = FIRMWARE.parents[2]
FACTORY_JSON = FIRMWARE.parent / "electronics" / "wand" / "wand-factory-design.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pin_map(component: dict) -> dict[str, tuple[str, str]]:
    return {
        str(pin["number"]): (pin["name"], pin["net"])
        for pin in component["pins"]
    }


def display_path(value: str | None) -> str | None:
    if value is None:
        return None
    home = str(Path.home())
    return value.replace(home, "<USER_HOME>")


def discover_toolchain() -> dict:
    roots = [
        Path(r"C:\ncs"),
        Path(r"C:\Nordic"),
        Path.home() / "ncs",
        Path.home() / "AppData" / "Local" / "Programs" / "nrfconnect",
        Path(r"D:\ncs"),
        Path(r"D:\Nordic"),
    ]
    env_roots = {
        name: os.environ.get(name, "")
        for name in ("ZEPHYR_BASE", "ZEPHYR_SDK_INSTALL_DIR", "NRF_CONNECT_SDK")
    }
    raw_tools = {
        name: shutil.which(name)
        for name in (
            "west",
            "cmake",
            "ninja",
            "arm-none-eabi-gcc",
            "nrfjprog",
            "python",
        )
    }
    west_module = importlib.util.find_spec("west") is not None
    zephyr_base = Path(env_roots["ZEPHYR_BASE"]) if env_roots["ZEPHYR_BASE"] else None
    ncs_root_found = any(root.exists() for root in roots) or any(
        value and Path(value).exists() for value in env_roots.values()
    )
    target_build_available = bool(
        (raw_tools["west"] or west_module)
        and raw_tools["arm-none-eabi-gcc"]
        and zephyr_base
        and zephyr_base.exists()
        and ncs_root_found
    )
    return {
        "tools": {name: display_path(path) for name, path in raw_tools.items()},
        "west_python_module": west_module,
        "environment": {
            name: display_path(value) for name, value in env_roots.items()
        },
        "common_ncs_roots": {display_path(str(root)): root.exists() for root in roots},
        "ncs_or_zephyr_root_found": ncs_root_found,
        "target_build_available": target_build_available,
    }


def verify() -> tuple[dict, bool]:
    design = json.loads(read(FACTORY_JSON))
    components = {component["ref"]: component for component in design["components"]}
    header = read(FIRMWARE / "include" / "mw_board_pins.h")
    event_header = read(FIRMWARE / "include" / "mw_gesture_event_v2.h")
    event_source = read(FIRMWARE / "src" / "mw_gesture_event_v2.c")
    math_source = read(FIRMWARE / "src" / "mw_target_math.c")
    overlay = read(ZEPHYR_APP / "boards" / "ubx_evkninab3_nrf52840.overlay")
    c08_overlay = read(ZEPHYR_APP / "boards" / "c08-005.overlay")
    c08_conf = read(ZEPHYR_APP / "boards" / "c08-005.conf")
    prj_conf = read(ZEPHYR_APP / "prj.conf")
    kconfig = read(ZEPHYR_APP / "Kconfig")
    target_source = read(ZEPHYR_APP / "src" / "main.c")
    checks: list[dict] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(condition), "detail": detail})

    expected_u1 = {
        "1": ("P0.13", "HAPTIC_EN"),
        "5": ("P0.24", "CHG_STAT1_N"),
        "7": ("P0.25", "CHG_STAT2_N"),
        "31": ("VBUS", "USB_VBUS_5V"),
        "32": ("P0.11", "I2C_SCL"),
        "33": ("P1.09", "I2C_SDA"),
        "42": ("P0.26", "IMU_INT1"),
        "43": ("P0.06", "ARM_N"),
        "54": ("USB_DP", "USB_DP_PROT"),
        "55": ("USB_DM", "USB_DM_PROT"),
    }
    check(
        "factory_nina_b302_pin_authority",
        components.get("U1", {}).get("value") == "NINA-B302-00B-00"
        and all(pin_map(components["U1"]).get(pin) == value for pin, value in expected_u1.items()),
        "U1 exact module GPIO, VBUS and protected USB nets",
    )

    expected_header = {
        "MW_HAPTIC_EN_GPIO_PORT": 0,
        "MW_HAPTIC_EN_GPIO_PIN": 13,
        "MW_CHG_STAT1_N_GPIO_PORT": 0,
        "MW_CHG_STAT1_N_GPIO_PIN": 24,
        "MW_CHG_STAT2_N_GPIO_PORT": 0,
        "MW_CHG_STAT2_N_GPIO_PIN": 25,
        "MW_I2C_SCL_GPIO_PORT": 0,
        "MW_I2C_SCL_GPIO_PIN": 11,
        "MW_I2C_SDA_GPIO_PORT": 1,
        "MW_I2C_SDA_GPIO_PIN": 9,
        "MW_IMU_INT1_GPIO_PORT": 0,
        "MW_IMU_INT1_GPIO_PIN": 26,
        "MW_ARM_N_GPIO_PORT": 0,
        "MW_ARM_N_GPIO_PIN": 6,
    }
    parsed_header = {
        name: int(value)
        for name, value in re.findall(r"#define\s+(MW_[A-Z0-9_]+)\s+(\d+)u", header)
    }
    check(
        "portable_pin_header_matches_factory",
        all(parsed_header.get(name) == value for name, value in expected_header.items()),
        "mw_board_pins.h exact P0/P1 assignments",
    )

    u2 = pin_map(components["U2"])
    check(
        "lsm6dsv16x_factory_mode",
        components["U2"]["value"] == "LSM6DSV16XTR"
        and u2.get("1") == ("SDO/SA0", "GND")
        and u2.get("4") == ("INT1", "IMU_INT1")
        and u2.get("5") == ("VDD_IO", "3V3")
        and u2.get("8") == ("VDD", "3V3")
        and u2.get("12") == ("CS", "3V3")
        and u2.get("13") == ("SCL", "I2C_SCL")
        and u2.get("14") == ("SDA", "I2C_SDA"),
        "SA0=GND selects 0x6A; CS high selects I2C; INT1 is routed",
    )
    check(
        "lsm6dsv16x_overlay_binding",
        all(
            token in overlay
            for token in (
                'compatible = "st,lsm6dsv16x"',
                "reg = <0x6a>",
                "int1-gpios = <&gpio0 26 GPIO_ACTIVE_HIGH>",
                "drdy-pin = <1>",
                "LSM6DSV16X_DT_FS_4G",
                "LSM6DSV16X_DT_FS_2000DPS",
                "LSM6DSVXXX_DT_ODR_AT_240Hz",
            )
        ),
        "Zephyr binding address/range/ODR/INT1 contract",
    )
    check(
        "i2c_pinmux_matches_factory",
        "NRF_PSEL(TWIM_SCL, 0, 11)" in overlay
        and "NRF_PSEL(TWIM_SDA, 1, 9)" in overlay,
        "P0.11 SCL and P1.09 SDA",
    )

    sw1 = pin_map(components["SW1"])
    r_arm = pin_map(components["R_ARM"])
    r_arm_ser = pin_map(components["R_ARM_SER"])
    check(
        "physical_arm_chain",
        sw1.get("1") == ("ARM_SWITCH", "ARM_SW")
        and sw1.get("2") == ("GND", "GND")
        and set(r_arm.values()) == {("1", "3V3"), ("2", "ARM_N")}
        and set(r_arm_ser.values()) == {("1", "ARM_SW"), ("2", "ARM_N")}
        and "gpios = <&gpio0 6 GPIO_ACTIVE_LOW>" in overlay,
        "press-to-ground via 1k, external 100k pull-up, active-low P0.06",
    )

    u5 = pin_map(components["U5"])
    check(
        "drv2605_factory_connectivity",
        u5.get("2") == ("SCL", "I2C_SCL")
        and u5.get("3") == ("SDA", "I2C_SDA")
        and u5.get("4") == ("IN/TRIG", "GND")
        and u5.get("5") == ("EN", "HAPTIC_EN")
        and u5.get("7") == ("OUT+", "HAPTIC_P")
        and u5.get("9") == ("OUT-", "HAPTIC_N"),
        "DRV2605 I2C, enable and differential actuator nets",
    )
    check(
        "haptic_base_fail_closed",
        'haptic: drv2605@5a' in overlay
        and 'status = "disabled"' in overlay.split('haptic: drv2605@5a', 1)[1]
        and 'actuator-mode = "LRA"' in overlay
        and "vib-rated-mv = <1850>" in overlay
        and "vib-overdrive-mv = <1850>" in overlay
        and "en-gpios = <&gpio0 13 GPIO_ACTIVE_HIGH>" in overlay
        and 'status = "okay"' in c08_overlay
        and "CONFIG_MW_C08_005_ACTUATOR_APPROVED=y" in c08_conf
        and "BUILD_ASSERT(IS_ENABLED(CONFIG_MW_C08_005_ACTUATOR_APPROVED))" in target_source,
        "base node disabled; exact C08 candidate needs paired overlay/config/build assert",
    )

    u3 = pin_map(components["U3"])
    j2 = pin_map(components["J2"])
    check(
        "power_and_battery_reserve",
        u3.get("10") == ("IN", "USB_VBUS_5V")
        and u3.get("2") == ("BAT", "BAT_POS")
        and u3.get("6") == ("TS/MR", "BAT_NTC")
        and u3.get("9") == ("STAT1", "CHG_STAT1_N")
        and u3.get("3") == ("STAT2", "CHG_STAT2_N")
        and j2.get("1") == ("BAT+", "BAT_POS")
        and j2.get("2") == ("NTC", "BAT_NTC")
        and "mw-chg-stat1" in overlay
        and "mw-chg-stat2" in overlay
        and "no undocumented charger-state guess" in target_source,
        "USB input, battery/NTC connector and both raw charger status inputs reserved",
    )

    check(
        "evk_conflicts_disabled",
        all(
            f"&{label} {{ status = \"disabled\"; }};" in overlay
            for label in (
                "led0", "led1", "led2", "red_pwm_led", "green_pwm_led",
                "blue_pwm_led", "button0", "button1", "uart0", "spi1",
                "pwm0", "adc", "ieee802154", "usbd",
            )
        ),
        "EVK P0.13/P0.25 LEDs/buttons and unused peripherals disabled",
    )

    check(
        "axis_and_units_fail_closed",
        "{0, 1, 0}" in math_source
        and "{-1, 0, 0}" in math_source
        and "{0, 0, 1}" in math_source
        and "return determinant(map) == 1" in math_source
        and "MW_RADIANS_TO_DEGREES" in math_source
        and "default n" in kconfig
        and "CONFIG_MW_AXIS_MAP_APPROVED=n" in prj_conf
        and "axis map is unapproved; gesture classification disabled" in target_source,
        "proper-rotation check, SI conversion, HIL approval off by default",
    )

    check(
        "gesture_event_v2_contract",
        "MW_GESTURE_EVENT_V2_BYTES ((size_t)14)" in event_header
        and "MW_LOGICAL_CHANNEL_COUNT UINT8_C(8)" in event_header
        and "uint32_t device_id" in event_header
        and "uint32_t session_id" in event_header
        and "uint8_t logical_channel" in event_header
        and "uint8_t battery_percent" in event_header
        and "uint8_t status_flags" in event_header
        and "put_u32_be(&payload_out[6], event->device_id)" in event_source
        and "put_u32_be(&payload_out[10], event->session_id)" in event_source,
        "14-byte big-endian V2 payload supports eight isolated logical channels",
    )
    check(
        "secure_sink_fail_closed",
        "mw_target_get_authenticated_identity" in target_source
        and "mw_target_secure_queue_gesture_event_v2" in target_source
        and target_source.count("return -ENOTSUP;") >= 3
        and not any(
            forbidden in target_source
            for forbidden in ("bt_gatt_notify", "bt_le_adv_start", "ieee802154_tx", "radio_tx")
        ),
        "no identity/session or secure queue implementation means no event leaves target",
    )

    check(
        "target_runtime_safety",
        all(
            token in target_source
            for token in (
                "sensor_trigger_set",
                "MW_GYRO_CALIBRATION_SAMPLES",
                "stationary_for_gyro_calibration",
                "wdt_install_timeout",
                "mw_gesture_stream_init",
                "MW_EVENT_STATUS_ARM_ACTIVE",
            )
        ),
        "DRDY sampling, stationary gyro bias, watchdog and physical arm gate",
    )

    tracked_files = [
        FIRMWARE / "include" / "mw_board_pins.h",
        FIRMWARE / "include" / "mw_gesture_event_v2.h",
        FIRMWARE / "include" / "mw_target_math.h",
        FIRMWARE / "src" / "mw_gesture_event_v2.c",
        FIRMWARE / "src" / "mw_target_math.c",
        ZEPHYR_APP / "CMakeLists.txt",
        ZEPHYR_APP / "Kconfig",
        ZEPHYR_APP / "prj.conf",
        ZEPHYR_APP / "boards" / "ubx_evkninab3_nrf52840.overlay",
        ZEPHYR_APP / "boards" / "c08-005.overlay",
        ZEPHYR_APP / "boards" / "c08-005.conf",
        ZEPHYR_APP / "src" / "main.c",
        FACTORY_JSON,
    ]
    toolchain = discover_toolchain()
    passed = all(item["pass"] for item in checks)
    status = (
        "STATIC_TARGET_INTEGRATION_VERIFIED_TARGET_BUILD_NOT_RUN"
        if passed and toolchain["target_build_available"]
        else "STATIC_TARGET_INTEGRATION_VERIFIED_TARGET_BUILD_BLOCKED_TOOLCHAIN_MISSING"
        if passed
        else "STATIC_TARGET_INTEGRATION_FAILED"
    )
    evidence = {
        "schema": "magic-wand.target-integration-evidence.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "authority": str(FACTORY_JSON.relative_to(REPO)).replace("\\", "/"),
        "target_baseline": {
            "nrf_connect_sdk": "v3.4.0",
            "zephyr": "v4.4.0",
            "board": "ubx_evkninab3/nrf52840",
        },
        "checks": checks,
        "summary": {"passed": sum(item["pass"] for item in checks), "total": len(checks)},
        "toolchain_discovery": toolchain,
        "file_sha256": {
            str(path.relative_to(REPO)).replace("\\", "/"): sha256(path)
            for path in tracked_files
        },
        "claims": {
            "static_contract_verified": passed,
            "host_tests_recorded_here": False,
            "target_compiled": False,
            "target_flashed": False,
            "hardware_in_loop_run": False,
        },
        "remaining_gates": [
            "Install pinned NCS v3.4.0 toolchain and reproduce both base and optional overlay builds.",
            "Approve sensor axes only after signed six-face and positive-axis HIL evidence.",
            "Approve C08-005 only after mounted resonance/current/thermal/mechanical HIL.",
            "Provide authenticated identity/session and secure queue strong overrides.",
            "Provide measured battery percentage or retain the explicit 0xFF unknown value.",
            "Flash only a reviewed build and archive ELF/HEX/map/config hashes plus SWD log.",
        ],
    }
    return evidence, passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence, passed = verify()
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.check_only or not args.output:
        print(rendered)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
