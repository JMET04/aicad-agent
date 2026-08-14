# aicad-agent 1.15.0

Release date: 2026-08-14

## What changed

This release publishes deterministic, standards-first mechanical and electronics regeneration evidence on top of the v1.14.0 normative preflight.

- Mechanical evidence includes a 54-rule preflight, regenerated bracket/carrier/assembly geometry, native SolidWorks 2026 and AutoCAD 2025 save-reopen checks, drawings, BOM, inspection, material, analysis, and v3 closure.
- Electronics evidence includes a 63-rule preflight, accepted Stage A schematic, Stage B 156-reference placement and 479/479 pad-net parity, constrained KiCad Stage C, native ERC/DRC, BOM/CPL, PDFs, STEP, renders, and pinned Freerouting evidence.
- Deterministic public archives bind every file by SHA-256 without redistributing KiCad, Java, or Freerouting runtimes.

## Safety boundary

The mechanical package has complete review-evidence closure, but it does not grant technical-package readiness or manufacturing authorization. The electronics package remains blocked by 37 native unconnected items and unresolved field-return, buck hot-loop, impedance, EMC, thermal, and qualification gates. Gerber, drill, and job files are withheld; production, fabrication, and manufacturing authorization remain false.

## Verification

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_*.py" -v
.\scripts\build-agent-plugin.ps1 -OutputDirectory release/v1.15.0 -Version 1.15.0
python -B scripts/verify_release_package.py release/v1.15.0/aicad-agent --source-root . --expected-version 1.15.0
```
