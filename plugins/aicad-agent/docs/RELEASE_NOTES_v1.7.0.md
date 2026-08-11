# aicad-agent v1.7.0

`v1.7.0` adds typed selection measurements and a synchronized coordinate-system visibility control to the CAD modifier.

- Clicking a line shows model length and XYZ endpoints.
- Clicking a point shows XYZ coordinates.
- Clicking a circle shows radius, diameter and XYZ center.
- Measurement values can prefill their exact controlling parameter when editable.
- Every selection reference carries a schema-validated compiled measurement; pixels never become dimension authority.
- Every review view shows `MODEL_XYZ`; one switch hides or restores SVG axes, model origins and the rotating 3D triad.
- Rectangle edge-to-width/height controller mapping is corrected and regression-tested.
- Real Chrome QA clicks line, point and circle and verifies coordinate-system off/on behavior.

Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and domain/packaging gated.
