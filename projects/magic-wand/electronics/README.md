# Magic Wand Electronics Package — EVT Review Only

> **BLOCKED NATIVE OUTPUTS:** `kicad-cli`, `ngspice`, and `arm-none-eabi-gcc` were not found on PATH or in the checked common installation paths on 2026-08-21. No KiCad schematic/PCB was synthesized, no ERC/DRC or SPICE analysis was run, no Gerber/drill/BOM/CPL was exported, and no embedded binary was compiled. The CSV connectivity tables and JSON constraints in this directory are the review source of truth until a qualified engineer captures them in KiCad and closes the gates in `review-report.md`.

Status: **EVT review-only; not certified, not production-authorized, and not approved for safety-critical actuation.**

This package defines two low-voltage prototypes:

- a battery wand using NINA-B302-00B-00, LSM6DSV16X, BQ25185, TPS63900 and DRV2605L; and
- a USB-powered receiver using NINA-B302-00B-00 with 3.3/5 V-referenced UART/PWM, one signal-isolated open-collector output, and one common-ground 5–12 V low-side MOSFET output.

The receiver contains **no mains circuitry** and **no flight-power stage**. Mains loads require an external, appropriately certified relay/contactor product. Flight controllers may connect only through UART, SBUS/CRSF-over-UART, PWM/AUX signal interfaces; propulsion, ESC battery and motor wiring stay outside this PCB.

## Review order

1. `review-report.md` — native-tool blockers, analyses run/not run, gates and risk.
2. `evidence-manifest.json` — primary manufacturer evidence and checked claims.
3. `system-architecture.md` and `interface-control.md` — boundaries and electrical contracts.
4. `wand/connectivity.csv` and `receiver/connectivity.csv` — source-of-truth logical connectivity.
5. `design-calculations.md`, `pcb-constraints.json`, `test-points.csv` — calculations and layout/test intent.
6. `bom.csv` and `fmea.csv` — sourcing, alternates and risk controls.
7. `bring-up-and-production-test.md` — safe staged evaluation and proposed manufacturing tests.

## Evidence status vocabulary

- **datasheet-checked**: directly supported by the cited manufacturer document.
- **design-choice**: selected by this EVT design and still requires hardware validation.
- **inferred**: engineering inference requiring independent review.
- **blocked**: cannot be demonstrated with the tools or artifacts available here.

Part numbers, footprints, land patterns, polarity, pin-one orientation, antenna clearance and assembly options must be independently checked against the exact orderable-part revision before schematic capture or procurement.
