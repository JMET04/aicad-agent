# Magic Wand Portable Firmware Core - Target Integration Pending

> **TARGET BUILD BLOCKER:** `arm-none-eabi-gcc`, Nordic nRF Connect SDK and a NINA-B302 board definition were not available on 2026-08-21. This directory is a portable C11 control/protocol skeleton. A host build can check syntax and deterministic state logic; it is not a flashable NINA image, radio stack, bootloader, production cryptographic implementation or safety certification.

The skeleton intentionally separates reviewable policy from platform code:

- `include/mw_protocol.h` / `src/mw_protocol.c`: framed AES-CCM interface, 13-byte nonce construction, authenticated header, freshness and strict monotonic replay gate. It has **no home-grown cipher**. With no reviewed CCM callback or no persistent counter readiness, it fails closed.
- `include/mw_state_machine.h` / `src/mw_state_machine.c`: wand physical-arm and receiver output-safe state logic with a 100 ms renewable physical-arm lease, 250 ms link deadline and immutable 1-500 ms command-pulse cutoff; continuous lease refresh cannot extend a pulse.
- `include/mw_gesture.h` / `src/mw_gesture.c`: eight-class relative-motion recognizer with closed-loop circle features, cross-axis suppression, stationary-return rejection, physical-arm streaming gate and 250 ms refractory control. It does not estimate absolute position or an exact 3D trajectory.
- include/mw_gesture_event_v2.h / src/mw_gesture_event_v2.c: exact 14-byte authenticated V2 event carrying channel, gesture, confidence, battery/status and duplicated device/session binding.
- include/mw_receiver_runtime.h / src/mw_receiver_runtime.c: fail-closed handshake/session/replay/heartbeat/lease runtime with explicit LEGACY_V1 or MULTICHANNEL_V2 profile.
- include/mw_receiver_multichannel.h / src/mw_receiver_multichannel.c: eight independent device/session/channel slots, pending-handshake media cleanup, immediate safe-owner release, single dangerous-output ownership and actual routing into the media scheduler.
- include/mw_pattern_renderer.h, mw_effect_audio.h and mw_effect_scheduler.h: target-independent 240x240 RGB565 animation, deterministic 16 kHz procedural audio with volume/mute limits, and FIRE/ICE/EXPLOSION plus five additional media effects.
- include/mw_receiver_rev_b_pins.h: receiver-effects-only GC9A01A, MAX98357A and discrete RGB pin contract. It does not change the wand.
- `include/mw_board_pins.h`: target-neutral NINA-B302 GPIO authority mirrored from the electronics source. `HAPTIC_EN` is assigned to the outer module pad 1 / `P0.13`; interior pad 44 / `P0.27` is intentionally unused on the wand.
- `protocol.md`, `state-machine.md`, `gesture-dictionary.yaml`: normative review intent and calibration/test gates.
- `src/main.c`: host-only deterministic safety/protocol smoke harness. `tests/gesture_vectors.c` verifies all eight gesture classes, rejection, physical-arm gating and refractory behavior; neither test emulates BLE or proves target timing.

## Host build (available-tool syntax check)

From the repository root, reproduce the recorded host review with the exact CMake, Ninja and GCC paths captured in `host-review-evidence.json`:

```powershell
D:/mingw64/mingw64/bin/cmake.exe -S projects/magic-wand/firmware -B D:/receiver-runtime-cmake -G Ninja -DCMAKE_C_COMPILER=D:/mingw64/bin/gcc.exe -DMW_HOST_REVIEW=ON
D:/mingw64/mingw64/bin/cmake.exe --build D:/receiver-runtime-cmake
D:/mingw64/mingw64/bin/ctest.exe --test-dir D:/receiver-runtime-cmake --output-on-failure
```

Use an out-of-tree disposable build directory. The 2026-08-22 strict GCC 16.1.0 / CMake / Ninja run compiled 25 steps and passed 8/8 CTest entries: host review, gesture vectors, target math, V2 payload vectors, receiver runtime, receiver multichannel, pattern/effect/audio and target contract. This remains host evidence, not a NINA image or HIL result.

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
- no claim that host-rendered RGB565 or synthesized PCM proves GC9A01A color/order, MAX98357A I2S timing, acoustic level, EMC, thermal or power behavior.
