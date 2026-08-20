# EVT Design Calculations

These are first-order calculations, not simulation or measured validation. Values shall be recomputed with exact tolerances, DC-bias derating, temperature, component lots and layout parasitics before G2/G3 release.

## Wand charger

The BQ25185 data-sheet relationship is approximately:

`I_CHG = 300 A·Ω / R_ISET`

With `R_ISET = 1.00 kΩ`, nominal `I_CHG = 300 mA`. The cited 5 V/4.2 V reference application uses `R_ILIM/VSET = 18.0 kΩ` for a nominal 500 mA input limit and 4.2 V battery regulation. Both are 1% resistors.

Approximate charger dissipation while charging is `(V_IN - V_BAT) × I_CHG`, ignoring system sharing:

- at 5.0 V in, 3.7 V battery: `(5.0 - 3.7) × 0.3 = 0.39 W`;
- at 5.0 V in, 3.0 V battery: `(5.0 - 3.0) × 0.3 = 0.60 W`.

That is enough to require the exposed-pad land pattern, ground copper and thermal regulation test. The battery supplier's maximum charge current may force RISET upward. Charge is prohibited until pack protection, capacity, NTC beta and JEITA/temperature thresholds are reviewed.

Nominal capacitors: IN 1 µF minimum plus 4.7 µF design margin, SYS 10 µF nominal with at least 1 µF effective after bias, BAT 4.7 µF. X5R/X7R parts are selected with voltage rating margin; effective capacitance must be checked in the vendor curve.

## Wand 3.3 V rail

TPS63900 data-sheet 3.3 V configuration:

- L = 2.2 µH;
- C_IN = 10 µF;
- C_OUT = 22 µF;
- CFG3 = 16.2 kΩ for VOUT1 = 3.3 V;
- CFG1 = 36.5 kΩ for VOUT2 = 3.3 V;
- CFG2 = 0 Ω for no programmed input-current limit;
- SEL = 0, with both selections intentionally configured to 3.3 V;
- EN has a defined pull state and never floats.

Preliminary peak rail budget:

| Load | Peak design allowance |
|---|---:|
| NINA-B302 radio/MCU | 25 mA (above cited +8 dBm TX typical peak for margin) |
| LSM6DSV16X | 5 mA |
| DRV2605L logic | 5 mA excluding actuator energy |
| haptic actuator | 120 mA provisional; exact actuator required |
| LEDs/leakage/margin | 25 mA |
| **provisional total** | **180 mA** |

This is below the TPS63900 headline output capability at the relevant operating point, but only a transient bench test across battery state, haptic actuation and BLE TX can close the rail margin.

## I²C pull-ups

One shared 3.3 V bus uses 4.7 kΩ pull-ups on SDA/SCL (design choice). Static low current per line is `3.3 V / 4.7 kΩ = 0.70 mA`. For a conservative 200 pF bus estimate, the 30–70% rise approximation is `0.8473 × R × C = 0.80 µs`, too slow for a 1 µs 100 kHz limit only marginally and unsuitable for a 300 ns 400 kHz target. Therefore EVT starts at 100 kHz and requires measured capacitance/rise time; use 2.2 kΩ if 400 kHz is needed and sink-current margins remain valid.

## USB-C sink declaration

Each CC pin has its own 5.1 kΩ ±1% Rd to ground. They are not tied together. Default USB current is assumed until Type-C current advertisement is decoded; the design does not rely on 1.5 A or 3 A advertisement. BQ25185 input limiting is nominally 500 mA and firmware/system loading must remain inside the enumerated/advertised source contract.

## Receiver 3.3 V supply

TPS62162 is a fixed 3.3 V, 1 A buck with 3–17 V input range; in this design its input is protected USB 5 V only. Use the data-sheet application network (2.2 µH with input/output ceramic capacitance, exact values confirmed during schematic capture). Provisional receiver peak budget is 25 mA NINA + 15 mA translators/opto/gate/LED + 40 mA margin = 80 mA. The low-side load current does not flow through this regulator.

## Optocoupler LED

For 3.3 V drive, provisional TLP291(SE LED forward voltage 1.25 V and target 5 mA:

`R = (3.3 - 1.25) / 0.005 = 410 Ω`; select 430 Ω.

At 1.35 V worst-case assumed forward voltage, current is `(3.3 - 1.35)/430 = 4.53 mA`. The exact data-sheet Vf/CTR bin and temperature limits must be checked against a ≤10 mA output sink requirement. A minimum CTR of 50% at the stated test point would theoretically yield >2 mA, so the external pull-up must be chosen so required sink current is low; the 10 mA interface ceiling is not a guaranteed saturation value. Bench validation is mandatory.

## Low-side MOSFET

CSD17313Q2 is a 30 V logic-level N-MOSFET. Using 32 mΩ maximum at 4.5 V would not directly guarantee the same value at 3.3 V; therefore use the data-sheet 3 V curve/limit during exact review. A conservative 50 mΩ assumed effective resistance gives:

- 1 A: `P = I²R = 0.05 W`;
- 2 A pulse: `P = 0.20 W` before switching/transient losses.

Gate network: 33 Ω series, 100 kΩ gate-to-source pull-down. GPIO high drive and VGS margin require bench confirmation. Connector, trace/via and flyback heating—not silicon headline current—set the EVT 1 A limit.

## Battery-life estimate boundary

No runtime claim is made because battery capacity, duty cycle, haptic waveform, BLE connection interval and sleep policy are not frozen. Runtime shall be calculated from measured mode currents and a derated pack capacity, then verified at hot/cold temperature and end-of-life impedance.
