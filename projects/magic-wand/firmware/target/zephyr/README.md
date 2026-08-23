# NINA-B302 Zephyr target integration

This directory is the auditable target boundary for the custom magic-wand
controller. It is pinned to **nRF Connect SDK v3.4.0 / Zephyr v4.4.0** and the
maintained `ubx_evkninab3/nrf52840` board definition. The custom overlay first
disables EVK LEDs, buttons and peripherals that conflict with the wand, then
applies the GPIO/I2C authority from
`electronics/wand/wand-factory-design.json`.

Official baseline references:

- [NCS v3.4.0 release notes](https://github.com/nrfconnect/sdk-nrf/blob/v3.4.0/doc/nrf/releases_and_maturity/releases/release-notes-3.4.0.rst)
- [Zephyr EVK NINA-B3 board](https://docs.zephyrproject.org/4.4.0/boards/u-blox/ubx_evkninab3/doc/index.html)
- [ST LSM6DSV16X datasheet](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [Zephyr DRV2605 binding](https://github.com/zephyrproject-rtos/zephyr/blob/v4.4.0/dts/bindings/haptics/ti%2Cdrv2605.yaml)
- [C08-005 candidate datasheet](https://precisionmicrodrives.com/cdn/datasheets/C08-005%20-%20datasheet-004/c08-005-datasheet-004.pdf)

## Implemented target boundary

- LSM6DSV16X at I2C address `0x6A`, INT1 on P0.26, 240 Hz, ±4 g and
  ±2000 dps. Zephyr SI values are converted to the portable core's g/dps.
- Physical press-to-arm on P0.06 active-low, with capture reset immediately on
  release. Charger STAT1/STAT2 are retained as raw active-low status bits; the
  firmware does not guess an undocumented charger state.
- A 480-sample stationary gyro-bias gate, data-ready timing bounds and watchdog.
- A drawing-derived proper-rotation axis candidate. Classification remains
  disabled by default until six-face and positive-axis HIL evidence approves it.
- Versioned 14-byte gesture V2 payload with zero-based logical channel 0..7,
  gesture/confidence, battery/unknown, raw status, device ID and session ID.
  Device/session integers are big-endian like the existing authenticated frame.
- The old 2-byte gesture encode/decode API remains available for single-channel
  legacy review. Multi-channel routing must use V2 and cross-check payload
  identity/session/channel against the authenticated frame and assigned slot.
- Weak identity, battery and secure-queue hooks fail closed with `-ENOTSUP`.
  There is deliberately no raw BLE/802.15.4 send path in this target gate.

`mw_target_get_authenticated_identity()` must be replaced by the reviewed
pairing/session layer. `mw_target_secure_queue_gesture_event_v2()` must queue the
exact V2 bytes as an authenticated `MW_CMD_GESTURE_EVENT` payload. A measured
battery provider may replace `mw_target_read_battery_percent()`; otherwise the
wire value remains `0xFF` with `BATTERY_KNOWN` clear.

## Reproducible build commands (not run on this workstation)

Install the pinned NCS v3.4.0 toolchain and activate its environment, then run
from the repository root:

```powershell
west build -p always -b "ubx_evkninab3/nrf52840" projects/magic-wand/firmware/target/zephyr -d build/magic-wand-nina-base
```

The base build keeps both release gates off: gesture classification is disabled
until axis HIL approval and the DRV2605 node is disabled.

Only after the exact mounted C08-005 has independent approval, reproduce the
optional actuator-candidate build:

```powershell
west build -p always -b "ubx_evkninab3/nrf52840" projects/magic-wand/firmware/target/zephyr -d build/magic-wand-nina-c08 -- -DDTC_OVERLAY_FILE=boards/c08-005.overlay -DEXTRA_CONF_FILE=boards/c08-005.conf
```

This optional configuration clamps both DRV2605 rated and overdrive values to
1.85 V and has a compile-time actuator approval assertion. It is not a substitute
for resonance, current, temperature, acoustic and installed-clearance testing.

Run the offline authority check independently of NCS:

```powershell
python projects/magic-wand/firmware/target/zephyr/verify_target_contract.py --check-only
```

## Evidence boundary on 2026-08-22

This workstation had CMake, Ninja and host Python, but no `west`, NCS/Zephyr
environment, `arm-none-eabi-gcc` or `nrfjprog`. Therefore no target ELF/HEX was
compiled and nothing was flashed. `target-integration-evidence.json` records
only the offline factory-design/header/overlay/source contract and the missing
toolchain. A release still requires both target builds, archived `.config`,
devicetree, ELF/HEX/map hashes, SWD log and the axis/actuator HIL records.

The hardware power reservation remains unchanged: USB VBUS enters BQ25185, J2
reserves BAT+/NTC/GND, and both charger status inputs reach the NINA. No PCB or
mechanical file is modified by this target integration.
