# aicad-agent 1.15.0

Release date: 2026-08-14

## What changed

This release publishes a standards-first regeneration of the mechanical servo-reducer bracket package and the industrial-controller electronics package. Both packages start from the v1.14.0 normative preflight and retain native-source, reopen, visual-review, analysis, and hash-closure evidence.

- Mechanical: 54-rule preflight, regenerated bracket/carrier/assembly geometry, native SolidWorks 2026 and AutoCAD 2025 save-reopen evidence, STEP/DWG/PDF/DXF deliverables, BOM, inspection, material, interference, thermal, and v3 evidence reports.
- Electronics: 63-rule preflight, accepted Stage A schematic, Stage B 156-reference placement and 479/479 pad-net parity, constrained KiCad Stage C board, native ERC/DRC reports, BOM/CPL, assembly/copper PDFs, STEP, renders, and pinned Freerouting evidence.
- Public showcase archives are deterministic, SHA-256 closed, and exclude KiCad, Java, and Freerouting runtimes.
- The release builder and independent repository verifier now target v1.15.0.

## Readiness boundary

The mechanical archive reaches `evidenceContractReady=true`, but `technicalPackageReady`, production-release eligibility, and manufacturing authorization remain false.

The electronics archive is intentionally blocked. Native KiCad checks report zero ERC violations and zero geometric DRC violations, but 37 unconnected items remain. Field-return, buck hot-loop, impedance, EMC, thermal, and qualification gates are also unresolved. Therefore:

- `evidenceContractReady=false` and `technicalPackageReady=false`;
- Gerber, drill, and job outputs are withheld;
- fabrication, manufacturing, and production-release authorization remain false.

The archives supersede the earlier showcase drawings for engineering review only. They do not authorize manufacture, assembly, or PCB fabrication.

## Verification

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_*.py" -v
.\scripts\build-agent-plugin.ps1 -OutputDirectory release/v1.15.0 -Version 1.15.0
.\scripts\build-github-source.ps1 -OutputDirectory release/v1.15.0/github-repository -Version 1.15.0 -PluginArchive release/v1.15.0/aicad-agent-1.15.0.zip -PluginDirectory release/v1.15.0/aicad-agent
```
