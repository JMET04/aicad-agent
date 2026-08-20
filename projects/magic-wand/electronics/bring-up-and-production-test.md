# Bring-up, Qualification and Proposed Production Test

Status: EVT review-only. None of the following tests has been executed on hardware. Work requires an approved schematic/PCB, calibrated instruments, current-limited supplies, exact battery/load data and a competent electronics engineer.

## Preconditions

- Close G0/G1/G2 in `review-report.md`; archive zero-violation ERC/DRC evidence and independent symbol/footprint/polarity review.
- Inspect bare boards in a CAM viewer and against fabrication/assembly reports. Confirm the NINA variant is B302, no copper/metal violates its antenna zone, and optocoupler isolation sides are not bridged.
- Use a battery simulator first. Do not attach a LiPo until charger voltage/current/NTC behavior is measured.
- Use a protected low-voltage dummy load first. No mains conductor, motor/propeller, ESC power path or flight-critical input is permitted during board bring-up.
- Record board serial, BOM lot, firmware hash, fixture version, instrument IDs, calibration dates, operator and ambient temperature.

## Wand staged bring-up

1. **Unpowered inspection:** AOI/microscope check for pin one, polarity, exposed-pad solder, USB shorts, antenna keepout, connector keying and passive values. Measure resistance from USB VBUS, BAT and 3V3 to GND; investigate anomalous low resistance before power.
2. **Regulator-only injection:** with battery/USB absent, inject a current-limited 3.3 V into the approved rail fixture only if back-power analysis permits. Confirm reset-state currents and no haptic output. Otherwise skip rather than improvise.
3. **Battery-simulator start:** set 3.7 V with 20 mA limit, then raise the limit while observing SYS and 3V3. Confirm no overshoot beyond component ratings; log idle/current modes. Exercise RESET_N and brownout.
4. **USB sink/charger:** emulate the specified 10 kΩ beta3435 NTC at 25 °C. Apply current-limited 5.0 V USB through a Type-C source fixture; confirm CC terminations, no source role, input limit, 4.2 V regulation target and 300 mA nominal fast-charge setting. Repeat with battery simulator at 3.0/3.7/4.1 V.
5. **Temperature faults:** substitute resistor values corresponding to cold/hot/open/short NTC cases. Charging must suspend as specified. Record BQ25185 STAT pins, SYS behavior and recovery. The exact battery defines acceptable thresholds.
6. **Thermal:** at worst allowed input/battery/system load, measure BQ25185 exposed-pad/case, PCB copper, TPS63900, inductor and connector temperatures until stable. Include blocked-airflow enclosure case and thermal regulation behavior.
7. **Digital:** attach SWD, flash a review image, validate reset/watchdog, I²C pull-up/rise time and device IDs. Confirm LSM6DSV16X axes against the marked board axes and DRV2605L with the exact actuator.
8. **Physical arm:** measure ARM_N debounce and release. A stuck-low at boot produces fault. Releasing the switch requests local disarm immediately; under a healthy link receiver output inactive target is ≤100 ms. Lost disarm packets fall back to link-loss safe state ≤250 ms.
9. **Haptic/user feedback:** validate paired, armed, accepted, rejected and fault patterns without enabling a receiver load. Run a blinded recognition study before freezing patterns.

## Receiver staged bring-up

1. Perform unpowered inspection/resistance checks including the isolation moat and separation of `ISO_OC_EMIT` from GND.
2. Power USB through a current-limited source. Confirm TPS62162 startup, PWR_GOOD, 3.3 V ripple and no pulse on UART_TX, PWM, OPTO or LOAD_GATE during power-up, reset, brownout and watchdog cycling.
3. Test J2 first with VREF_IO = 3.3 V, then 5.0 V. Confirm no back-power when either side is absent, correct fixed translator directions, logic thresholds/timing, and safe receiver-driven levels through reset. VREF_IO must not source external loads.
4. With a floating isolated fixture, test J3 at external pull-ups of 3.3/5/12/24 V and sink currents up to the validated CTR/saturation limit, never exceeding 10 mA interface design ceiling. Verify creepage is not bridged by probes/fixture.
5. Test J4 using 5 V then 12 V protected supplies and resistive loads stepped to 1 A while measuring MOSFET VDS, connector/trace/MOSFET temperature and ground disturbance. Test a representative inductive load with flyback fitted and capture the drain transient using a suitably rated differential/isolated probe. The 2 A/100 ms pulse is allowed only after the 1 A thermal test passes.
6. Inject BLE loss, stale/duplicate/foreign/authentication-failed packets, sequence rollback, watchdog, reset and power droop while monitoring every output on an oscilloscope/logic analyzer. Any unintended pulse is a blocker.

## Security and protocol qualification

- Verify LE Secure Connections pairing requires physical authorization and per-device OOB material; dump checks must show no compiled default/fleet key.
- Run known-answer AES-CCM tests using the selected crypto library, then negative tests for changed header/ciphertext/tag.
- Prove nonce uniqueness across normal operation, reconnect, receiver reboot, counter persistence and interrupted flash write.
- Reject duplicate, out-of-window, stale, cross-device and wrong-direction frames without any output state change.
- Fuzz lengths, command IDs, flags and sequence boundaries under ASan/UBSan in a host harness where available, then repeat critical cases on target/HIL.
- Confirm signed update, anti-rollback, debug policy and key-erasure/reprovisioning procedures before field exposure.

## Gesture qualification

Collect labelled sessions from representative users and mounting orientations. Split training/test sets by user rather than by window to avoid leakage. Report per-class precision/recall, confusion matrix, rejection rate, false activations per hour, latency and performance under haptic vibration. Low-confidence or out-of-distribution windows always map to `GESTURE_NONE`; never infer an exact absolute 3D path.

## Proposed manufacturing tests (not yet implemented)

| Stage | Test | Proposed acceptance |
|---|---|---|
| incoming | Exact MPN/revision, moisture/polarity, battery/NTC paperwork | Matches released AVL and ordered-part records; no unapproved substitution. |
| paste/AOI/X-ray | Fine-pitch/exposed-pad assembly, connector shell, polarity | No bridge/open/void beyond approved workmanship criteria; thermal pads assessed with process capability. |
| ICT/flying probe | shorts/opens, rail resistance, key passives, isolation moat | Golden-board limits with guard bands; isolated field side remains floating. |
| programming | SWD identity, signed image, unique credentials, lock policy | Unique serialized record and read-back verification; no default key. |
| powered functional | rail/current, USB, I²C IDs, IMU axes, arm switch, haptic | Within characterized golden-unit limits. |
| receiver functional | VREF 3.3/5 V, UART/PWM, opto, MOSFET dummy load | Correct direction/levels; outputs inactive through reset; no isolation bridge. |
| radio | conducted/radiated proxy/RSSI fixture at fixed spacing | Within statistically derived golden-unit bounds; failures quarantined, not retuned blindly. |
| safety timing | release, watchdog, link loss, replay/foreign packet | ≤100 ms normal arm release target; ≤250 ms link-loss target; zero unintended pulse. |
| final | visual, label, connector keying, firmware/BOM/serial trace | Complete digital traveller and review-only marking for EVT units. |

Production limits must be derived from characterized design verification units and gauge R&R; this table is not a factory test specification or authorization.
