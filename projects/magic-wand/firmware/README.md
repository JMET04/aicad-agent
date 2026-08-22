# Magic Wand Portable Firmware Core - Target Integration Pending

> **TARGET BUILD BLOCKER:** `arm-none-eabi-gcc`, Nordic nRF Connect SDK and a NINA-B302 board definition were not available on 2026-08-21. This directory is a portable C11 control/protocol skeleton. A host build can check syntax and deterministic state logic; it is not a flashable NINA image, radio stack, bootloader, production cryptographic implementation or safety certification.

The skeleton intentionally separates reviewable policy from platform code:

- `include/mw_protocol.h` / `src/mw_protocol.c`: framed AES-CCM interface, 13-byte nonce construction, authenticated header, freshness and strict monotonic replay gate. It has **no home-grown cipher**. With no reviewed CCM callback or no persistent counter readiness, it fails closed.
- `include/mw_state_machine.h` / `src/mw_state_machine.c`: wand physical-arm and receiver output-safe state logic with a 100 ms renewable physical-arm lease, 250 ms link deadline and 500 ms command-pulse ceiling.
- `include/mw_gesture.h` / `src/mw_gesture.c`: eight-class relative-motion recognizer with closed-loop circle features, cross-axis suppression, stationary-return rejection, physical-arm streaming gate and 250 ms refractory control. It does not estimate absolute position or an exact 3D trajectory.
- `include/mw_board_pins.h`: target-neutral NINA-B302 GPIO authority mirrored from the electronics source. `HAPTIC_EN` is assigned to the outer module pad 1 / `P0.13`; interior pad 44 / `P0.27` is intentionally unused on the wand.
- `protocol.md`, `state-machine.md`, `gesture-dictionary.yaml`: normative review intent and calibration/test gates.
- `src/main.c`: host-only deterministic safety/protocol smoke harness. `tests/gesture_vectors.c` verifies all eight gesture classes, rejection, physical-arm gating and refractory behavior; neither test emulates BLE or proves target timing.

## Host build (available-tool syntax check)

From the repository root, reproduce the recorded host review with the exact CMake, Ninja and GCC paths captured in `host-review-evidence.json`:

```powershell
D:/mingw64/bin/cmake.exe -S projects/magic-wand/firmware -B projects/magic-wand/firmware/build-host3 -G Ninja -DCMAKE_C_COMPILER=D:/mingw64/bin/gcc.exe -DCMAKE_MAKE_PROGRAM=D:/mingw64/bin/ninja.exe -DMW_HOST_REVIEW=ON
D:/mingw64/bin/cmake.exe --build projects/magic-wand/firmware/build-host3 --config Release
D:/mingw64/bin/ctest.exe --test-dir projects/magic-wand/firmware/build-host3 --output-on-failure -C Release
```

The generated `build-host3/` directory is disposable verification output and must not be confused with target firmware. The recorded result is 2/2 tests passed under GCC 16.1.0, CMake 4.3.2 and Ninja 1.13.2; see `gesture-host-evidence.json`. A generic `cmake -S . ...` invocation that allows the environment to choose a default compiler is not equivalent evidence: compiler and generator selection must be explicit and archived. On another workstation, either reproduce this pinned toolchain or create a separately reviewed evidence record for the replacement toolchain.

## Target integration gates

1. Pin a supported nRF Connect SDK/toolchain and create/review an exact NINA-B302 hardware definition using the u-blox module pin allocation.
2. Configure BLE 1M and LE Secure Connections **SC-only**, with a physical OOB provisioning/authorization flow and unique per-device credentials. No Just Works fallback and no compiled fleet key.
3. Bind `mw_ccm_decrypt_fn` to the SDK's reviewed AES-CCM implementation or hardware-backed service, using a 16-byte tag and the exact nonce/AAD serialization in `protocol.md`.
4. Implement atomic/rollback-resistant session and receive high-water persistence. If persistence is corrupt, exhausted or uncertain, outputs stay safe until authenticated reprovisioning.
5. Implement signed boot/update, anti-rollback, debug policy, watchdog/brownout handling and credential lifecycle. Irreversible protection changes require a documented recovery/manufacturing plan.
6. Bind GPIOs exactly to `include/mw_board_pins.h` and the electronics connectivity tables. Configure receiver output GPIOs low before enabling output drivers; validate actual reset behavior on an oscilloscope.
7. Compile with warnings-as-errors, static analysis and target unit/HIL tests; archive SDK/compiler versions, config, map, binary hash and test logs.

## Explicit non-goals

- no precise absolute 3D position/path claim;
- no mains, emergency-stop, life-safety, weapon or unattended actuation;
- no flight arming, propulsion, primary flight-control or power-stage command;
- no claim that a host smoke build proves BLE security, hard real-time timing, radio range or hardware safety.
