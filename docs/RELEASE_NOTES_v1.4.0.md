# aicad-agent v1.4.0

`v1.4.0` adds calibrated webpage/image reference reconstruction and precision subobject review.

- Direct SVG DOM geometry and text evidence with source hash pinning.
- Similarity calibration from authoritative dimensions; raw pixels remain non-authoritative.
- One-reference-object-to-one-CAD-object validation with exact geometry tolerances.
- Annotation text, position, rotation, lineweight hierarchy, overlap, and mojibake gates.
- Bounded, reasoned collision-avoidance offsets instead of untracked visual nudging.
- Aspect-ratio-preserving native-text SVG/HTML preview plus real-browser PNG validation.
- MCP and CLI schema, validate, and build tools for reference reconstruction.
- Edge/circle/face-level 3D selector mappings with thin visible strokes and independent hit targets.

The portable reference build emits annotated DXF rather than native AutoCAD DIMENSION objects. Native DWG, layouts, XData persistence, and save/reopen evidence still require the AutoCAD host gate.
