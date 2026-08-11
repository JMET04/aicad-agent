# aicad-agent v1.6.0

`v1.6.0` turns the multiview reviewer into a single-flow CAD modifier and adds arbitrary semantic sections.

## User-facing changes

- Replaced separate “intent” and “formal transaction” panels with one modification list. Natural-language notes and direct numeric edits share one visible workflow; exact source-bound transactions remain available under collapsed advanced details.
- Added a free-section workbench. It accepts axis planes such as `X=10` and arbitrary planes such as `normal 1,1,0 through origin`, renders feature/plane intersections, and lets the reviewer select the owning exact parameter controller.
- Added hover-discovered geometric centers, center axes, pattern pitch circles, opposite outlines and vertical interface edges. They remain hidden until hovered or selected.
- Added a complete, clickable core-parameter catalog for each feature. Clicking a value selects its exact semantic controller and prefills the right-side editor.
- Added point-to-point coincident relations and shared pattern controller edits for count, pitch radius and start angle.

## Safety and authority

- Free-section geometry is calculated from compiled feature operations, never from pixels.
- Section curves and hidden construction geometry are review/select proxies, not native persistent BREP authority.
- Every exact edit still binds the current source SHA-256, scope, affected instance count, preserve policy and full dependency replay.
- Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`.

## Validation

- Source regression: 101/101 tests passed.
- Real Chrome interaction: hidden-geometry hover, pitch-circle selection, core-parameter prefill/edit, axis section, oblique section, section selection, point relation, UTF-8, no horizontal overflow and safety locks all passed.
- Existing AutoCAD 2025 and SolidWorks 2026 evidence is preserved; this UI-only release does not claim a new native-host rerun.
