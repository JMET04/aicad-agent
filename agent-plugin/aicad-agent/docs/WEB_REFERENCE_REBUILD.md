# Webpage and image reference reconstruction

This workflow rebuilds a reference drawing as editable CAD while separating physical truth from screen appearance.

## What “1:1” means

- CAD model-space geometry is generated in declared physical units and compared to the calibrated reference object by object.
- Raw webpage or image pixels are never treated as millimetres or inches.
- A vector webpage or SVG is hash-pinned and its identified `line`, `circle`, and `text` DOM objects are read directly.
- A raster capture or PDF needs reviewed object extraction plus at least two authoritative dimensional anchors. OCR and visual similarity are evidence, not dimensional authority.
- Sheet framing, text hierarchy, label rotation, lineweights, and annotation placement are validated separately from model geometry.

## Required workflow

1. Call `aicad_get_reference_rebuild_schema`.
2. Author an origin-anchored AICAD 2D plan with purpose, reasoning, dependencies, and mathematical constraints for every object.
3. Author a reference contract that pins the source hash, declares axis orientation, and supplies authoritative calibration anchors.
4. Bind every required reference geometry object to exactly one AICAD object.
5. Bind every required source text object by ID, exact text, source position, and source rotation.
6. Keep annotations at `source_exact` placement by default. When real font metrics cause a collision, use `optimized_offset` with an explicit offset, reason, and maximum displacement budget.
7. Call `aicad_validate_reference_rebuild`, then `aicad_build_reference_reconstruction`.
8. Run `scripts/aicad_reference_visual_qa.cjs` in a real browser. The gate checks UTF-8 Chinese, opaque white background, preserved viewBox aspect ratio, native SVG text, required label visibility, text-to-text collision, text-to-geometry collision, mojibake, and browser console errors. It records the PNG/report and hashes in the manifest.
9. When native DWG, AutoCAD DIMENSION objects, layouts, or persistence are required, perform the AutoCAD host post-process and save/reopen audit. Portable DXF cannot prove those host properties.

## CLI

```powershell
python scripts/aicad_agent.py reference-schema
python scripts/aicad_agent.py reference-validate --plan drawing.plan.json --reference drawing.reference.json
python scripts/aicad_agent.py reference-build --plan drawing.plan.json --reference drawing.reference.json --out build/reference --name drawing
node scripts/aicad_reference_visual_qa.cjs build/reference/drawing.preview.html build/reference/drawing.visual-validation.json build/reference/drawing.preview.png
```

## Output contract

The portable build produces the pinned reference contract, validation JSON/Markdown, editable 1:1 DXF geometry, MTEXT and deterministic dimension graphics, native-text SVG, HTML preview, manifest, and hashes. Browser QA adds a PNG and machine-readable visual report.

All outputs remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `domainGated=true` until a separately authorized review accepts them.
