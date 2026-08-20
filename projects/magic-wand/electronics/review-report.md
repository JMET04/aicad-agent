# Electronics Review Report — EVT Review Only

## Blocking findings (must be read first)

| ID | Severity | Finding | Required closure evidence |
|---|---|---|---|
| BLK-EDA-001 | Blocker | `kicad-cli` not present on PATH or checked common paths. No native KiCad source, ERC, DRC, schematic PDF, PCB render, Gerber, drill, BOM or CPL output exists. | Capture both CSV connection tables in a supported KiCad release; peer-check symbols/footprints; run ERC/DRC; archive exact tool version, reports and plots. |
| ENV-KICAD-001 | Environment blocker | KiCad 10.0.5 is the official stable target but the 967,270,176-byte Windows x64 installer cannot be safely downloaded/installed with the observed free space (C: 2,037,940,224 B; D: 891,183,104 B); `winget` is absent. No user files were deleted. | Provision a separate environment with adequate disk; run and archive the exact commands/acceptance criteria in `native-validation.md`. |
| BLK-SIM-001 | Blocker | `ngspice` not present. Charger thermal, converter transient and output switching behavior have not been simulated. | Run worst-case vendor-model simulations and bench correlation. |
| BLK-FW-001 | Blocker | `arm-none-eabi-gcc` / nRF Connect SDK toolchain not present. Firmware skeleton was not target-compiled or flashed. | Pin SDK/tool versions, compile with warnings-as-errors, run unit/HIL tests, sign an EVT image and archive logs. |
| BLK-MECH-001 | Blocker | Enclosure, exact battery pack, haptic actuator and receiver load harness are not frozen. Antenna and thermal constraints cannot be closed. | Mechanical stack-up, battery/NTC characterization, antenna pre-scan and thermal test reports. |
| BLK-SAFE-001 | Blocker | No product-level hazard analysis, regulatory test or external relay/flight-controller integration qualification has been completed. | Independent safety review plus applicable radio/EMC/electrical/battery/regional compliance evidence. |

## Analyses actually performed

| Analysis | Status | Evidence basis | Result/limit |
|---|---|---|---|
| Manufacturer pin/power/decoupling cross-check | Performed manually | Documents in `evidence-manifest.json` | Logical connection intent recorded in CSV; this is not ERC. |
| Power/current first-order calculations | Performed manually | `design-calculations.md` | Order-of-magnitude EVT sizing only; tolerances and thermal bench work remain. |
| Interface boundary review | Performed manually | `interface-control.md` | Mains and propulsion power excluded; signal limits explicitly stated. |
| BOM lifecycle screen | Performed manually | Manufacturer product status captured 2026-08-21 | TLP291 base part rejected as NRND; TLP291(SE) selected subject to procurement recheck. |
| KiCad ERC | **Not run** | Tool unavailable; no native schematic | No pass claim. |
| KiCad DRC / physical layout analysis | **Not run** | Tool unavailable; no native PCB | No clearance, connectivity, return-path or antenna-layout pass claim. |
| SPICE | **Not run** | Tool unavailable | No waveform, stability or transient pass claim. |
| SI/PI, RF, EMC, thermal FEA | **Not run** | Models/layout unavailable | Requires specialist review and measurement. |
| Manufacturing file review | **Not run** | No Gerber/drill/BOM/CPL output | Fabrication release prohibited. |

## Manual review observations

1. NINA-B302 VCC_IO (pin 9) and VCC (pin 10) are both tied to regulated 3.3 V; exposed ground pads and all specified GND pins are grounded. Its integrated PIFA antenna is used; ANT pin 13 is left unconnected for the B302 variant.
2. LSM6DSV16X uses I²C: CS is high, SDO/SA0 is low, VDD and VDD_IO each receive local 100 nF decoupling, and unused auxiliary/Qvar pins are terminated per the selected disabled mode. This termination must be rechecked during symbol capture.
3. The BQ25185 setting is the data-sheet example for nominal 300 mA charge and 500 mA input limit: RISET = 1.00 kΩ and RILIM/VSET = 18.0 kΩ. Battery-specific charge limits and the 10 kΩ NTC network remain approval gates.
4. TPS63900 uses the cited 3.3 V configuration with 2.2 µH, 10 µF input and 22 µF output. All EN/SEL/CFG pins have defined states; they are not allowed to float.
5. DRV2605L has 1 µF on REG, 1 µF plus 100 nF on VDD and IN/TRIG grounded when unused. Actuator-rated voltage/current and auto-calibration must be validated on the exact LRA/ERM.
6. USB-C sink ports use separate 5.1 kΩ Rd resistors on CC1 and CC2. USB D+/D− are protected by USBLC6-2SC6 and routed only for USB 2.0 Full-Speed service/debug. These choices do not imply USB-IF compliance.
7. Receiver `VREF_IO` is an input reference supplied by the external controller and may be 3.3 V or 5.0 V. Direction-controlled SN74LVC2T45 devices translate NINA GPIO without exposing it directly to 5 V. It is not a power output; output-safe reset behavior still requires hardware/bench review because this translator has no dedicated OE pin.
8. The optocoupler output is only a signal-isolated floating phototransistor pair. It does not create isolated power and does not authorize mains wiring.
9. The MOSFET output shares receiver ground and is limited by this EVT interface to 5–12 V, 1 A continuous, 2 A for 100 ms, pending copper/thermal/load validation. Inductive loads require the specified external/load-side flyback path.
10. BLE security is necessary but not sufficient for functional safety. Physical arming, bounded leases, watchdogs and output defaults are required and must be tested for brownout, reset, disconnect and replay.

## False-positive / ambiguity triage

| Candidate issue | Disposition | Rationale |
|---|---|---|
| NINA pin 13 has no connection | Intentional for B302 only | Pin is the external antenna connection for B301; the selected B302 uses its internal PIFA. The exact symbol variant must encode this. |
| LSM6DSV16X auxiliary/Qvar pins are tied | Intentional only while features disabled | If sensor-hub auxiliary SPI or Qvar is enabled later, connectivity must change and the review must be repeated. |
| Receiver isolated emitter is not board GND | Intentional | The isolation boundary would be defeated if tied to local GND. |
| Receiver load ground equals board GND | Intentional, explicitly non-isolated | This is the common-ground low-side channel, not the isolated channel. |
| No relay or SBUS inverter on board | Intentional boundary | Mains relay is external; SBUS inversion is an external adapter option unless a reviewed inverter population option is added later. CRSF and normal UART are non-inverted. |

## Release gates

- **G0 architecture:** peer approval of boundaries, pin map and security/hazard assumptions.
- **G1 schematic:** native KiCad capture, exact symbols/footprints/MPNs, ERC closure with justified waivers.
- **G2 PCB:** stack-up and controlled-impedance values from chosen fabricator; DRC, antenna/return-path and thermal review.
- **G3 prototype:** current-limited bring-up, charger/NTC/USB/haptic/output fault tests, antenna pre-scan.
- **G4 firmware:** reproducible target build, signed image, crypto/replay tests and state-machine HIL fault injection.
- **G5 compliance:** applicable radio/EMC/USB/battery/electrical and end-product assessments. Module approvals do not automatically approve the end product.
- **G6 manufacturing:** verified Gerber/drill/BOM/CPL package, assembly drawing, golden-unit test limits and independent release sign-off.

This report is a review aid, not a certificate, safety case, or production release.
