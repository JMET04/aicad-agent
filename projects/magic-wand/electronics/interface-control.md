# Interface Control Document

Status: EVT review-only. All limits are design limits to be verified on hardware and are not component absolute maximum ratings.

## Wand external interfaces

### J1 USB-C receptacle (USB 2.0 sink/device)

| Contact group | Net | Contract |
|---|---|---|
| A4/A9/B4/B9 | USB_VBUS_5V | 5 V nominal sink input only; no source/host role; feeds protection, BQ25185 IN and NINA VBUS sense. |
| A5 | CC1 | Independent 5.1 kΩ Rd to GND. |
| B5 | CC2 | Independent 5.1 kΩ Rd to GND. |
| A6/B6 | USB_DP | Joined at receptacle, ESD protected, controlled pair to NINA pin 54. |
| A7/B7 | USB_DM | Joined at receptacle, ESD protected, controlled pair to NINA pin 55. |
| GND/shield | GND/SHIELD | Shell tied through reviewed EMC option; no shield current through sensitive IMU return. |

### J2 battery connector

| Pin | Signal | Contract |
|---:|---|---|
| 1 | BAT+ | Protected 1S LiPo only, 3.0–4.2 V operating target. Battery pack must include protection; polarity keyed. |
| 2 | NTC | 10 kΩ-at-25 °C pack NTC sense to BQ25185 TS/MR network; exact beta and thresholds must be validated. |
| 3 | GND | Battery negative. |

### SW1 press-to-arm

Dedicated normally-open momentary switch grounds `ARM_N` when pressed. `ARM_N` has a local 100 kΩ pull-up to 3.3 V and 1 kΩ series resistor at the NINA input. It is not shared with USB, I²C, SWD or a capacitive touch function. Firmware samples the raw pin independently; a stuck-low condition produces a fault rather than automatic arming.

### J3 actuator

Two-wire LRA/ERM output from DRV2605L `OUT+`/`OUT-`. No side may be tied to ground. Exact actuator must stay inside DRV2605L voltage/current/thermal limits and be validated by auto-calibration at prototype stage.

## Receiver external interfaces

### J1 USB-C power/service

Same sink/device contact contract as wand. VBUS feeds TPS62162 and NINA VBUS sense; USB data reaches NINA through USBLC6-2SC6.

### J2 logic interface

| Pin | Signal | Direction at receiver | Contract |
|---:|---|---|---|
| 1 | GND | — | Signal reference only; do not connect propulsion high-current return through this pin. |
| 2 | VREF_IO | input | External controller supplies 3.3 V ±5% or 5.0 V ±5%; ≤2 mA translator bias; never treated as power output. |
| 3 | UART_TX | output | Push-pull at VREF_IO; CRSF or normal non-inverted UART. 33 Ω source series resistor. |
| 4 | UART_RX | input | VREF_IO-domain input through dedicated direction-controlled translator. 10 kΩ idle pull appropriate to selected protocol fitted only after integration review. |
| 5 | PWM_AUX | output | Push-pull at VREF_IO, 50 Hz–10 kHz design range, 33 Ω source series resistor. |

SBUS normally requires an inverted serial electrical interface. This EVT PCB exposes non-inverted UART; connect SBUS only through an externally reviewed inverter/adapter. CRSF uses the UART pins. Direction pins are hard-strapped and 100 kΩ pulls hold receiver-driven translator inputs low during reset; there is no external output-enable claim. Flight controller connections are signals only—no ESC, battery or motor power passes through the receiver.

### J3 isolated open collector

| Pin | Signal | Contract |
|---:|---|---|
| 1 | ISO_OC_COL | Floating phototransistor collector; external pull-up required; 3.3–24 V target, ≤10 mA design current. |
| 2 | ISO_OC_EMIT | Floating phototransistor emitter; return to the external low-voltage input circuit only. |

The two pins have no intentional connection to receiver ground. The output is for low-rate control/status and is not an isolated power source. It may drive only the low-voltage input of a separately certified relay/contactor. No mains conductor may enter the receiver PCB or enclosure.

### J4 common-ground low-side output

| Pin | Signal | Contract |
|---:|---|---|
| 1 | LOAD_SUPPLY_5_12V | External protected 5–12 V load supply positive; routed to load connector only, not board 3.3 V. |
| 2 | LOAD_DRAIN | Connect load negative here; CSD17313Q2 sinks to ground. |
| 3 | LOAD_GND | External supply return and receiver ground; non-isolated. |

EVT limit: 1 A continuous or 2 A for 100 ms, subject to DRC copper sizing, connector rating and measured temperature rise. Inductive loads require a flyback diode placed at the load or across pins 1–2 with correct polarity. A 15 V TVS option is documented but must be selected against the actual load waveform. Never use this channel for mains or flight propulsion.

## Debug and programming

Both boards expose keyed/tagged test pads for NINA SWDIO, SWDCLK, RESET_N, SWO, 3V3 and GND. They are service-only; do not route SWD under the antenna. Production images must enable verified boot/debug policy appropriate to the threat model, with recoverability documented before irreversible protection settings.
