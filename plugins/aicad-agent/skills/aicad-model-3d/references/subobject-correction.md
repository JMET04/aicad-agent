# Exact subobject correction protocol

Use this protocol when a user selects a specific edge, circle, or face.

1. Generate the current synchronized view package and use its exact `reference_key`.
2. Bind the correction to the current plan SHA-256. Never reuse a selection after the plan changes.
3. Copy the canonical reference metadata from the selector catalog; do not broaden `edit_paths` from a projection.
4. For a boundary move, require one preserve policy: center, opposite boundary, size, or support plane.
5. For a pattern member, require the shared scope, affected count, and shared parameter groups. Never detach silently.
6. Preview the full correction. Reject any origin, containment, residual-wall, lock, volume, or downstream replay failure.
7. Treat an already-satisfied relation as a no-op audit result.
8. Apply only after review; keep `reviewOnly=true`, `accepted=false`, and `ruleEnabled=false` in generated candidates.
9. Report semantic reference authority honestly. Native persistent BREP authority requires host evidence.

See `docs/EXACT_SUBOBJECT_CORRECTION.md` and `rules/subobject_correction_rules.json` for the full contract.

## Modifier interaction contract

- Present one user-visible modification list. Keep exact transactions and safety locks under collapsed advanced evidence; never remove them.
- Derive the complete core-parameter catalog from the compiled feature. Clicking a value must select its exact controller and prefill the editor.
- Accept free-section planes as a finite nonzero normal plus a finite point. Axis equations are shortcuts only.
- Calculate section curves from feature-operation geometry, never from image pixels, and map section selection back to an exact parameter controller.
- Keep centers, axes, pitch circles and interface edges hidden until hover/focus/selection, with a separate hit layer and stable semantic references.
- A section or construction proxy is review geometry, not native persistent BREP authority.
- Before presenting a selectable line, point, circle, or face, attach its typed measurement from the compiled `MODEL_XYZ` coordinate system. Never calculate displayed dimensions from browser pixels.
- Keep selected-object measurements separate from the global core-parameter catalog: line length/endpoints, point XYZ, circle radius/diameter/center, and face area/center.
- Provide one synchronized coordinate-system switch that hides or restores SVG axes, origin markers, and the rotating 3D XYZ triad together.
