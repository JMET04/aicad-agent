# aicad-agent v1.8.1

`v1.8.1` makes architectural drafting semantics a delivery invariant instead of a visual afterthought.

- Architectural plans now distinguish plan-cut walls/columns, visible projections, furniture/annotation, dashed routes or overhead items, and centerline grids.
- The 2D reviewer propagates each object's `source.cad_layer` into selectable SVG geometry and renders the same relative hierarchy as CAD.
- Named native DIMSTYLE values, native DIMENSION entities, millimetre units and linetype scale can be checked by the new `scripts/aicad_architecture_qa.py`.
- `ARCH-D001` through `ARCH-D006` capture the failure causes, mathematical order constraints, cross-render parity and required whole-drawing review.
- Regression coverage rejects a route layer that silently falls back to Continuous and rejects a reviewer that collapses architecture layers to one stroke.
- Production installation now copies only integration-manifest allowlisted files; REL-G017 prevents caches or temporary test artifacts from entering the installed plugin.
- Existing automatic review launch, coordinate persistence, XData, packaging and SolidWorks capabilities remain unchanged.

Safety state remains `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`.

- Complete architectural axis groups: global cross-storey numbering, tangent bubbles, centered identifiers, reviewer labels and XData-aware QA.
- Stage-aware annotation completeness rules now cover door/window tags, stair direction, levels, north indicator, section/elevation references, plot scale and failure-learning regressions.
