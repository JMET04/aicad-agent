# Receiver Runtime, Hardware Boundary and HIL Entry

Status: **portable 8-channel receiver policy plus pattern/audio effects implemented and host-tested; receiver-effects PCB, target image, cryptography, real display/audio and HIL gates remain open**.

This document binds only to the tracked receiver sources. Untracked reopen
candidates, lock files, route fixtures and native reports are deliberately not
used as release evidence.

## Current hardware boundary

| Function | Tracked implementation | Runtime use and safety boundary |
|---|---|---|
| MCU/radio | U1 u-blox NINA-B302-00B-00, nRF52840, internal PIFA | Candidate target for BLE 1M, LE Secure Connections, AES-CCM service and GPIO. No target image exists yet. |
| Power | USB-C J1, PTC F1, TPS62162 3.3 V buck, `PWR_GOOD_N` on NINA pad 46 / P0.12 | A low/uncertain power-good indication must invoke `mw_receiver_runtime_power_good_changed(..., false)` and force `MW_RECEIVER_FAULT`. |
| Logic J2 | external VREF_IO input; non-inverted UART TX/RX and PWM/AUX at 3.3 V or 5 V | Signal-only. VREF_IO is not a power output. No SBUS claim without an externally reviewed inverter. No flight arming, propulsion or primary-control mapping. |
| Isolated J3 | TLP291 floating open collector, 3.3–24 V target, <=10 mA design limit | Low-rate SELV signal isolation only. It is not an isolated power output and permits no mains conductor on this PCB or in its enclosure. |
| Load J4 | CSD17313Q2 common-ground 5–12 V low-side channel, provisional 1 A continuous / 2 A for 100 ms | Low-voltage dummy/load channel only, with external supply protection and reviewed flyback. No mains or flight propulsion. Physical thermal/load verification remains open. |
| Service | USB device/service plus SWDIO, SWDCLK, RESET_N, SWO test pads | Development and manufacturing access only. Signed boot, anti-rollback, credential lifecycle and debug lock policy are target gates. |

The receiver GPIO authority is captured in `include/mw_receiver_board_pins.h`:

| NINA pad | nRF GPIO | Net | Required reset/safe behavior |
|---:|---|---|---|
| 32 | P0.11 | UART_TX_3V3 | configure low/inactive before translator-facing peripheral enable |
| 33 | P1.09 | UART_RX_3V3 | input; translator-protected |
| 42 | P0.26 | PWM_3V3 | configure low/inactive before peripheral enable |
| 43 | P0.06 | OPTO_DRV | configure low before all other application tasks |
| 44 | P0.27 | LOAD_GATE_CTL | configure low before all other application tasks; hardware 100 kOhm pulldown is only a second layer |
| 46 | P0.12 | PWR_GOOD_N | input; unhealthy/uncertain state faults safe |

## Native KiCad audit of the tracked baseline

The following commands were replayed with KiCad CLI 10.0.5 on 2026-08-22,
writing reports outside the repository:

```powershell
kicad-cli sch erc -o <temporary>/receiver-erc.rpt projects/magic-wand/electronics/receiver/receiver.kicad_sch
kicad-cli pcb drc -o <temporary>/receiver-drc.rpt projects/magic-wand/electronics/receiver/receiver.kicad_pcb
```

Results for the tracked files:

- schematic SHA-256 `E3AD8919BC27010B4C90ACEC7D2EFC51CC7914E1CA2C7603ADB334FD6B7CF052`:
  51 ERC messages: 8 errors and 43 warnings;
- PCB SHA-256 `DA3F44AF29E3422AE032A43C770A751F71E0B333F0A4BCB23192F0BBA79E5C95`:
  0 geometric DRC violations, **119 unconnected items**, 0 footprint errors;
- connectivity-table SHA-256
  `69F387E92D351A74EF2B4D718B5B269FC28418D41C88857DFC6C4E351C26BAB8`.

The tracked `receiver-factory-design.json` records a different source-board
hash (`eefea6...`) and `0_unconnected`; that evidence does not bind to the
current tracked PCB. Its own gates also keep ERC `NOT_RUN`, manufacturer land
pattern overlay `OPEN` and fabrication authorization `false`. Therefore the
receiver is an interface/pinout baseline, **not a fabrication candidate**.
Fixing its KiCad source is outside this receiver-runtime change and must not be
done by adopting an untracked reopen candidate without an explicit reviewed
merge.

## Portable runtime contract

`mw_receiver_runtime` composes the protocol parser, replay guard, gesture
decoder and output-safe policy into one fail-closed transaction boundary:

1. Boot begins with every desired output inactive. Invalid device identities,
   unavailable rollback-resistant session storage, failed self-test or bad
   power-good enters a latched fault.
2. A candidate peer must equal the provisioned wand identity. The application
   session epoch is non-zero, strictly greater than the last atomically stored
   epoch, and cannot wrap or be reused.
3. Session activation requires authenticated BLE, authenticated application
   handshake, ready direction-specific traffic keys and one authenticated exact
   gesture payload profile. The replay guard resets to UNSUPPORTED; a profile
   must be explicitly installed only after negotiation. The new session epoch
   is committed before the guard becomes active; channels 1..7 require
   MULTICHANNEL_V2.
4. A frame is checked for direction, device, session, command shape, future or
   stale timestamp, sequence 0/max/replay, AES-CCM acceptance and atomic receive
   high-water commit before plaintext reaches policy code.
5. A protocol rejection closes the session and forces safe output. A receive
   persistence failure additionally latches `MW_RECEIVER_FAULT` because replay
   state is uncertain.
6. Only `HEARTBEAT` or `ARM_LEASE` renews the 250 ms receiver heartbeat
   deadline. Heartbeat expiry or link loss closes the session; recovery needs a
   strictly newer authenticated session.
7. `ARM_LEASE` is renewable for 100 ms. Refreshing it while a command is
   pending preserves that state and its immutable 1-500 ms pulse deadline.
   DISARM, pulse deadline, lease expiry, heartbeat/link loss, power-good loss
   or fault clears AUX, optocoupler and low-side desired state; the earliest
   applicable deadline wins.
8. `GESTURE_EVENT` is decoded and retained as telemetry only. It never calls
   the output state machine. V2 media routing additionally requires the
   authenticated `ARM_ACTIVE` bit; absence closes the slot silently before
   display/audio scheduling. The bit does not grant output authority or renew
   an `ARM_LEASE`. A separate authenticated, allow-listed output command is
   always required.

The runtime returns desired policy state; it does not write GPIO. This is
intentional: the target adapter must initialize physical outputs low before
radio, flash or scheduler start, then apply runtime state in one reviewed,
highest-priority output manager.

## Host negative vectors

The host suite covers:

- invalid/duplicate identities and unavailable storage fail closed;
- wrong peer, stale/reused session, handshake timeout, pending pairing-media
  cleanup, wrong-profile precheck closure, missing security predicate and
  failed atomic session commit;
- duplicate sequence, sequence max, wrong command direction, future/stale
  timestamp, foreign device and failed tag callback;
- persistence failure latching a fault;
- output command without arm lease;
- gesture telemetry before and during an output without direct actuation;
- immediate authenticated DISARM, lease/heartbeat interruption of a pulse,
  immutable 200/500 ms pulse cutoffs despite continuous 25 ms ARM_LEASE
  refresh, deadline-zero UINT32 wrap, explicit link loss and power-good failure;
- exact legacy receiver module-pad/GPIO mapping;
- eight unique peer/session slots, cross-channel replay/profile/binding
  negatives, V2 missing-`ARM_ACTIVE` silent rejection, independent timeout,
  owner release immediately after output-off, and output arbitration;
- all eight distinct RGB565 gesture animations, status scenes, procedural
  audio hashes, volume/boom limits, mute behavior, unknown-battery effect,
  bounded disconnect recovery and timed-effect UINT32 wrap.

The host decrypt callback uses a sentinel and copies bytes. It is deliberately
non-cryptographic and cannot prove ciphertext integrity, nonce uniqueness,
constant-time behavior, key isolation or target-library correctness.

## Target adapter and HIL entry

### Target integration sequence

1. Pin nRF Connect SDK/Zephyr, compiler, NINA-B302 board definition and u-blox
   hardware revision. Archive configuration, map, binary and hashes.
2. Before starting BLE or mounting a filesystem, drive P0.11, P0.26, P0.06 and
   P0.27 inactive; configure P1.09 and P0.12 as reviewed inputs. Verify the
   physical levels at J2/J3/J4 during boot, reset and brownout.
3. Configure BLE LE Secure Connections SC-only with physical OOB authorization,
   unique credentials and no Just Works/fleet key. Bind a reviewed KDF and
   AES-128-CCM implementation to the exact protocol nonce/AAD.
4. Implement atomic, wear-levelled and rollback-resistant session epoch plus
   receive high-water storage. Corruption, interrupted write, exhaustion or
   rollback must report not-ready and keep outputs safe.
5. Route authenticated frames through mw_receiver_multichannel_receive,
   which owns eight mw_receiver_runtime instances and one output-owner
   arbiter. Apply only its aggregate desired outputs. Its gesture path
   invokes only the media scheduler and cannot call an output driver.
6. Feed hardware watchdog, reset reason, BLE disconnect and PWR_GOOD into the
   runtime safe/fault paths. A stalled output manager must not be able to pet
   the watchdog.

### Required HIL matrix

Use current-limited SELV supplies, logic analyzer/oscilloscope, UART loopback,
an optocoupler dummy input and a protected resistive/inductive dummy load. Do
not connect mains, propulsion or primary flight-control hardware.

| HIL case | Required evidence |
|---|---|
| boot/reset/watchdog/brownout/PWR_GOOD loss | every J2/J3/J4 output inactive; zero unintended pulse |
| release/DISARM and dropped DISARM copies | normal authenticated release target <=100 ms; lease fallback <=100 ms |
| BLE loss or missing heartbeat | all outputs inactive by 250 ms; old session cannot re-arm |
| wrong peer/session/direction/device, sequence 0/max/duplicate/rollback | rejected; no output; invalid packet does not renew lease/heartbeat |
| changed AAD/ciphertext/tag, truncated/oversized frame | target AES-CCM rejects; plaintext erased; outputs safe |
| session/high-water interrupted flash commit | reboot/power-cut campaign proves no rollback/reuse; uncertainty latches safe fault |
| gesture event for every ID/confidence boundary | telemetry only; no AUX/opto/low-side transition |
| output without lease; 1/500/501 ms boundaries; continuous refresh; UINT32 wrap | unauthorized and 501 ms reject; valid pulse ends at the earliest pulse deadline, lease expiry or heartbeat expiry, including deadline value zero |
| J2 VREF_IO 3.3/5 V, absent-side power | correct direction/levels, no back-power, safe reset state |
| J3 and J4 limits | optocoupler CTR across temperature; MOSFET/connector/copper thermal rise and flyback waveform |

Until the target image, current receiver KiCad errors/unconnected items,
cryptographic negative vectors, power-cut persistence, oscilloscope timing and
physical interface tests all close, `GATE-TARGET-FW-001` and
`GATE-RECEIVER-001` must remain open.


## Eight-channel session and media-effect expansion

The portable core now contains eight independently provisioned logical slots.
Each slot owns a peer device ID, authenticated session epoch, replay high-water
mark and heartbeat deadline. Duplicate peer assignment is rejected. A replay,
profile mismatch, V2 device/session/channel mismatch, heartbeat timeout or
persistence fault closes only the affected slot. Dangerous desired outputs have
a single-owner arbiter: a second channel cannot activate an output while
another owner is active; the conflicting channel is closed safe and the first
owner is not disturbed. An owner that turns its output off is released in the
same receive transaction, so another valid slot need not wait for manager tick.
A pending handshake timeout or wrong profile closes that slot and replaces a
pairing scene with a bounded disconnect prompt before returning to another
online channel. The multichannel manager defaults to media-only with dangerous
output authority disabled. Legacy receiver targets must explicitly
enable that authority before any session starts; receiver-effects never does.

The application handshake authenticates one exact gesture profile per session.
LEGACY_V1 accepts exactly two bytes and is limited to channel zero.
MULTICHANNEL_V2 accepts exactly 14 bytes and is required on channels 1 through
7. V2 duplicates device ID, session ID and logical channel inside the encrypted
payload; all three are cross-checked after AES-CCM acceptance and before effect
routing. Its authenticated `ARM_ACTIVE` flag must also be set or that slot is
closed without starting any pattern/audio cue. LEGACY_V1 has no equivalent
flag and remains a weaker channel-zero compatibility profile only; it can never
stand in for physical-arm evidence or output authorization.

Successful gesture reception calls the effect scheduler from
mw_receiver_multichannel_receive. It is not a parallel demo path. The scheduler
can update only the 240x240 pattern scene, RGB status and synthesized PCM cue;
it has no reference to, or API for, the dangerous output state machine.
Battery 0xff with BATTERY_KNOWN clear means unknown and still plays the gesture
effect. Only a valid known percentage at or below 15 selects low-battery media.

| Gesture | Effect | Display intent | Procedural audio intent |
|---|---|---|---|
| TAP | EXPLOSION | white/yellow flash, star and radial shockwave | digitally limited boom |
| TWIST_CW | FIRE | red/orange rotating spiral and sparks | whoosh plus deterministic crackle |
| TWIST_CCW | ICE | blue/white expanding crystal | chime plus deterministic ice crack |
| SWISH_LEFT | LIGHTNING | electric-blue moving stroke | synthesized zap |
| SWISH_RIGHT | SHIELD | cyan/white moving shield stroke | shimmer |
| THRUST | ARCANE | magenta/gold burst | pulse |
| CIRCLE_CW | HEAL | green/white orbit | rising chime |
| CIRCLE_CCW | PORTAL | violet/cyan counter-orbit | warp |
| unknown ID | UNKNOWN | violet question glyph | short two-tone cue |
| pairing/disconnect/low battery/fault | status patterns | distinct status palette/animation | paired status cues; fault is muted |

All sound is generated in firmware from integer oscillators and deterministic
noise; no third-party audio asset is embedded. PCM is mono 16 kHz. The digital
master cap is 40 percent and EXPLOSION is separately capped to 25 percent and
7000 sample absolute peak. The MAX98357A SD/MODE pin must have a hardware
pull-down so reset, boot, watchdog and target fault are physically muted.

Host coverage now includes receiver_runtime_vectors,
receiver_multichannel_vectors and pattern_effect_vectors. The pinned strict
GCC/CMake run on 2026-08-22 passed all 8 CTest entries. These tests exercise
only the enumerated portable host vectors; they do not prove BLE cryptography,
speaker sound pressure, display color/order, SPI/I2S timing or target resource
headroom.

## Independent receiver-effects Rev A0 hardware direction

Do not stack media circuits onto the tracked receiver baseline with 119
unconnected items and legacy output channels. The safer manufacturing direction
is an independent projects/magic-wand/electronics/receiver-effects board. It
reuses the NINA-B302 concept and USB-C/3.3 V architecture, but does not copy the
old UART level translator, optocoupler, 12 V MOSFET output or their connectors.
It is ordered separately from the wand. No file below
projects/magic-wand/electronics/wand is changed by this work.

The proposed GPIO allocation is authoritative only as a design input in
include/mw_receiver_rev_b_pins.h:

| Function | NINA pad / nRF GPIO |
|---|---|
| GC9A01A SCK, MOSI, CS, DC, RST, BL | 52/P0.19, 50/P0.20, 51/P0.17, 48/P0.21, 49/P0.22, 47/P0.23 |
| MAX98357A BCLK, LRCLK, DIN, SD/MODE | 1/P0.13, 2/P0.14, 3/P0.15, 4/P0.16 |
| discrete RGB R, G, B | 5/P0.24, 7/P0.25, 8/P1.00 |

The display interface is an 8-pin 1.28 inch round GC9A01A 240x240 SPI module,
not an unqualified bare LCD. Backlight current must use a transistor or load
switch, not a NINA GPIO. Audio is MAX98357AETE+T or an independently qualified
equivalent, 5 V powered, with differential JST-PH speaker connector for a 4 ohm
speaker, local bulk/high-frequency decoupling, EMI-aware routing and SD/MODE
hardware mute. RGB is a discrete 3.3 V LED with one resistor per color; a 5 V
addressable LED is not accepted without a proper level shifter.

Power input is explicitly 5 V / 2 A from a qualified USB-C supply, not an
ordinary PC USB port. The previous 500 mA PTC is inadequate; MF-MSMF150-2
(LCSC C89648) is only a candidate pending trip/hold, inrush and thermal review.
MAX98357AETE+T (LCSC C910544) is only a sourcing candidate. The exact display
module, connector pin order, mechanical envelope, backlight current, speaker,
USB-C current-advertisement policy, power switch and enclosure remain
selection gates.

No receiver-effects KiCad schematic/PCB, native ERC/DRC report, JLC Gerber,
drill, BOM or placement package is claimed by this firmware change.
fabrication-gate.json keeps fabrication authorization false until exact parts,
power/thermal/EMI/antenna rules, source review and native verification close.
