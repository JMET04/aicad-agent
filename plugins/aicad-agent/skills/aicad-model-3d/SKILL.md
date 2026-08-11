---
name: aicad-model-3d
description: Build, validate, inspect, or troubleshoot deterministic SolidWorks 3D parts feature by feature from mathematical constraints. Use for AI CAD modeling requests involving SLDPRT/STEP output, extrudes and cuts, origin-anchored sketches, feature dependencies, design intent, fully constrained sketches, persistent topology references, or per-feature geometry verification.
---

# AICAD Model 3D

Model slowly and transactionally: reason about one feature, validate it, execute it, read it back, then continue.

## Workflow

1. Call `aicad_capabilities` and `aicad_solidworks_doctor`.
2. Decompose the part into an ordered feature graph. Start the base sketch at `[0,0,0]`.
3. For every feature, state:
   - purpose;
   - relation to earlier features;
   - dependency and support feature;
   - profile dimensions and location;
   - operation depth/end condition;
   - expected volume delta and resulting bounds.
4. Call `aicad_get_3d_plan_schema`, then author a schema `1.0` plan. Read [plan-schema.md](references/plan-schema.md) when creating or editing the plan.
5. Call `aicad_validate_3d_plan`. Correct the first reported invariant violation before execution.
6. Call `aicad_build_solidworks_part` with `execute=true`.
7. Accept a feature only when its report passes all gates: fully constrained sketch, feature error code zero, fault-free single body, expected volume/delta/bounds, persistent support resolution, and all required native sketch references resolved.
8. Require native save/reopen topology verification before claiming native topology authority. Read [native-topology.md](references/native-topology.md).
9. Deliver the SLDPRT, STEP, audit, manifest, host report, and reopen report together. Summarize the feature-to-feature reasoning.

## Hard rules

- Never issue raw mouse/keyboard CAD drawing as the primary modeling path.
- Never create all features first and inspect only the final shape.
- Never continue after a failed feature transaction.
- Never reference volatile names such as `Face1` or `Edge3` in a plan.
- Prefer principal planes and semantic support geometry. Require persistent-reference re-resolution after rebuild when topology is used.
- Treat a non-null feature object as insufficient evidence of success.
- Keep identifiers and the SolidWorks execution channel ASCII-safe; keep human explanations in UTF-8 plan/audit fields.
- Do not save a partial SLDPRT when any gate fails.
- In selectable review output, show typed compiled-model measurements for the current line, point, circle, or face; do not substitute the global parameter catalog.
- Bind displayed coordinates to right-handed `MODEL_XYZ` and provide one synchronized visibility switch for all 2D/3D coordinate overlays.

Read [failure-recovery.md](references/failure-recovery.md) when execution fails.
## Exact subobject correction

When the user selects a specific edge, circle, or face, read [subobject-correction.md](references/subobject-correction.md) before drafting a change. Bind the transaction to the current source hash and exact semantic reference, require an explicit preserve policy and shared-pattern scope where applicable, replay all downstream dependencies, and fail closed on any product-level invariant. Do not claim native persistent BREP authority without host readback evidence.
