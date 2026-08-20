# KiCad 10.0.5 Native Validation Recipe

> **ENVIRONMENT BLOCKER (not a design finding):** On 2026-08-21, neither `kicad-cli` nor `winget` was callable. The official Windows x64 KiCad 10.0.5 installer is 967,270,176 bytes. A read-only check found only 2,037,940,224 bytes free on C: and 891,183,104 bytes free on D: (free space fluctuates). D: cannot even hold the installer; C: has no safe margin for download plus installation and libraries. No download, installation, or user-file deletion was attempted.

The official KiCad 10.0 documentation is the command source: <https://docs.kicad.org/10.0/en/cli/cli.html>. Run this recipe only after native schematics and boards have been captured from the CSV source of truth as:

- `wand/wand.kicad_sch` and `wand/wand.kicad_pcb`
- `receiver/receiver.kicad_sch` and `receiver/receiver.kicad_pcb`

## Version and command checks

```powershell
kicad-cli version
kicad-cli sch erc --help
kicad-cli pcb drc --help
kicad-cli pcb export gerbers --help
```

Acceptance: reported version is exactly `10.0.5`; each help command exits 0. Archive the version output. Do not silently substitute a different major/minor version.

Create `reports`, `outputs/wand/gerbers`, `outputs/wand/drill`, `outputs/receiver/gerbers`, and `outputs/receiver/drill` before running the following commands.

## ERC and DRC

```powershell
kicad-cli sch erc --format json --severity-all --exit-code-violations --output reports/wand-erc.json wand/wand.kicad_sch
kicad-cli pcb drc --format json --all-track-errors --schematic-parity --severity-all --exit-code-violations --refill-zones --output reports/wand-drc.json wand/wand.kicad_pcb
kicad-cli sch erc --format json --severity-all --exit-code-violations --output reports/receiver-erc.json receiver/receiver.kicad_sch
kicad-cli pcb drc --format json --all-track-errors --schematic-parity --severity-all --exit-code-violations --refill-zones --output reports/receiver-drc.json receiver/receiver.kicad_pcb
```

Acceptance for every run:

- process exit code 0 (KiCad uses exit code 5 when violations are present);
- zero non-excluded errors and zero non-excluded warnings in the JSON;
- no unconnected pins/nets except explicit `no-connect` markers matching the connection tables;
- no footprint/pad mismatch, clearance, courtyard, solder-mask, edge, via, diff-pair, zone or schematic-parity finding;
- exclusions, if any, are independently reviewed and recorded by rule ID, object IDs, owner and rationale; exclusions are not hidden by omitting `--severity-all`.

## Review plots and 3D views

```powershell
kicad-cli sch export pdf --output outputs/wand/wand-schematic.pdf wand/wand.kicad_sch
kicad-cli pcb render --width 1600 --height 1200 --quality high --side top --perspective --output outputs/wand/wand-top.png wand/wand.kicad_pcb
kicad-cli pcb render --width 1600 --height 1200 --quality high --side bottom --perspective --output outputs/wand/wand-bottom.png wand/wand.kicad_pcb
kicad-cli sch export pdf --output outputs/receiver/receiver-schematic.pdf receiver/receiver.kicad_sch
kicad-cli pcb render --width 1600 --height 1200 --quality high --side top --perspective --output outputs/receiver/receiver-top.png receiver/receiver.kicad_pcb
kicad-cli pcb render --width 1600 --height 1200 --quality high --side bottom --perspective --output outputs/receiver/receiver-bottom.png receiver/receiver.kicad_pcb
```

Acceptance: PDFs open with all sheets, readable labels and revision/title blocks; top/bottom images are non-empty and visually show correct polarity, pin-one marks, connectors, antenna keepout, board outline and no component collisions. Missing 3D models are findings, not cosmetic waivers.

## BOM and component placement (CPL)

```powershell
kicad-cli sch export bom --exclude-dnp --output outputs/wand/wand-bom.csv wand/wand.kicad_sch
kicad-cli pcb export pos --format csv --units mm --side both --smd-only --exclude-dnp --output outputs/wand/wand-cpl.csv wand/wand.kicad_pcb
kicad-cli sch export bom --exclude-dnp --output outputs/receiver/receiver-bom.csv receiver/receiver.kicad_sch
kicad-cli pcb export pos --format csv --units mm --side both --smd-only --exclude-dnp --output outputs/receiver/receiver-cpl.csv receiver/receiver.kicad_pcb
```

Acceptance: every fitted BOM line has reference, value, footprint, manufacturer and exact MPN; no duplicate references; DNP policy is explicit; BOM fitted references and CPL references match one-for-one for SMD parts; side, rotation and origin are confirmed with the selected assembler using a first-article centroid overlay.

## Gerber and Excellon

Store the reviewed fabrication layer set in each board's plot parameters, including all four copper layers, top/bottom solder mask, top/bottom silkscreen and `Edge.Cuts`. Then run:

```powershell
kicad-cli pcb export gerbers --board-plot-params --check-zones --output outputs/wand/gerbers wand/wand.kicad_pcb
kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-zeros-format decimal --excellon-separate-th --generate-map --map-format gerberx2 --generate-report --report-path reports/wand-drill-report.txt --output outputs/wand/drill wand/wand.kicad_pcb
kicad-cli pcb export gerbers --board-plot-params --check-zones --output outputs/receiver/gerbers receiver/receiver.kicad_pcb
kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-zeros-format decimal --excellon-separate-th --generate-map --map-format gerberx2 --generate-report --report-path reports/receiver-drill-report.txt --output outputs/receiver/drill receiver/receiver.kicad_pcb
```

Acceptance:

- every command exits 0 and produces non-empty files;
- Gerber set contains exactly the approved copper/mask/silkscreen/outline layers with a single closed outline and no drawing-sheet graphics;
- plated and non-plated holes are distinct when both exist; drill counts/sizes match the report and PCB statistics;
- no stale/extra layer file exists in the output directory (use a fresh empty output directory for each run);
- an independent CAM viewer shows aligned copper, mask, outline and drill, correct text polarity, antenna copper keepout, isolation moat and load copper;
- fabrication archive hashes and the KiCad source revision are recorded together. Any ERC/DRC failure or CAM discrepancy blocks fabrication release.

Until these criteria are met, `outputs/` and `reports/` are expected to be absent and no manufacturing package may be represented as generated.
