# aicad-agent 1.15.2

## Selectable-vector modifier contract

- `aicad_open_review_request` now validates the complete `aicad_selectable_vector_modifier_v1` contract instead of trusting the HTML role marker alone.
- A valid modifier must expose real `cad-view` SVG geometry, separate wide `view-hit` targets, stable view/source/subobject IDs, a semantic entity catalog, model measurements, typed correction preview, and `reviewOnly=true` / `accepted=false` safety locks.
- Raster-only PDF/image browsers fail closed. A raster image is allowed only as a declared secondary underlay beneath a larger complete source-bound vector selection set.
- The canonical civil/architecture modifier remains accepted by the stricter boundary.

## Prevention and regression coverage

- Added `REVIEW-G009` and `REVIEW-G010` to make the selectable-vector and raster-underlay rules durable.
- Added negative tests for role-marker-only raster wrappers, SVG pages without hit geometry, and hit geometry without source identity.
- Generic view requests remain reviewer-first; native CAD still requires explicit intent and still opens only after the modifier.

This release changes reviewer validation only. Opening or previewing a modifier does not accept an engineering design and does not grant manufacturing, fabrication, or release authorization.
