---
name: aicad-model-3d
description: Build, validate, inspect, or troubleshoot deterministic SolidWorks 3D parts feature by feature from mathematical constraints. Use for AI CAD modeling requests involving SLDPRT/STEP output, extrudes and cuts, origin-anchored sketches, feature dependencies, design intent, fully constrained sketches, persistent topology references, or per-feature geometry verification.
---

# AICAD Model 3D

Model slowly and transactionally: reason about one feature, validate it, execute it, read it back, then continue.

## Workflow

0. Resolve the registered engineering domain with `aicad_get_engineering_domain_registry`. Build the strict experience context, call `aicad_recall_experience`, and validate exact real-file coverage before authoring features. Unknown domains and `foundation` profiles may produce only intent/obligation blocker reports, never specialist 3D.
1. Call `aicad_capabilities` and `aicad_solidworks_doctor`. Treat unsupported features, assemblies or host evidence as hard boundaries rather than approximating them silently.
1a. For a mechanical part, call `aicad_get_engineering_preflight_template` with `domain=mechanical`, source-bind and resolve all 54 canonical shared/mechanical gates, validate with `aicad_validate_engineering_preflight`, and embed the pass as `engineering_normative_preflight`. The 3D validator and SolidWorks builder fail before execution when it is missing or incomplete.
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

## Mechanical evidence-contract preparation

The generation preflight and evidence contract are distinct mandatory stages. The preflight freezes applicable standards, authority, calculations, manufacturing definition and drawing intent before features exist; its pass permits controlled modeling only. After the model exists, the evidence contract below binds the actual native model, STEP, drawing, BOM, analysis, inspection and host readback. Neither pass is an engineering approval.

For a mechanical job, prepare the canonical v3 evidence contract named by `rules/production_readiness_rules.json`. Geometry and topology alone are insufficient: bind authoritative inputs and units; operating envelope, duty cycle and design life; independently recomputed load combinations and abnormal cases; equation/input/output/margin trace; strength, stiffness, fatigue, fastener, joint, bearing and thermal margins; risk controls; mating fits, threads, undefined edges, tolerances/GD&T/roughness; stock/process/fixturing/tool access/coating compensation; process capability and measurement method; native material-database assignment; BOM/revision/inspection parity; and feature-bound drawing annotations. Declare each manufactured part and required assembly as an artifact subject and provide separate native CAD, STEP and manufacturing drawing artifacts with source-hash and native-reopen evidence. Supply one `aicad_machine_mechanical_bom_v1` JSON BOM with a positive-quantity row for every exact subject type/revision/artifact-ID set, then bind its hash and repeat those rows in `aicad_product_structure_manifest_v1`. Generic QA parses both for candidate-declared consistency; it does not establish external authority. Custom properties or volume-times-density do not substitute for native material evidence.

The generic v3 QA verifies only the declared evidence contract. It does not authenticate the reports, replay SolidWorks, reproduce the calculations, expose candidate files, or grant technical/manufacturing/release readiness. A pass may set only `evidenceContractReady=true`; `technicalPackageReady`, `manufacturingAuthorized`, `fabricationAuthorized`, `productionReleaseEligible` and `accepted` remain false.

## Controlled failure learning

On every mechanical test or host-gate failure, follow the controlled-learning workflow in `skills/aicad-draw/SKILL.md` and `rules/continuous_learning_rules.json`. Declare every failed check separately with a stable alias, hash-bound minimal reproducer, source/artifact closures and a disabled prevention candidate plus negative regression. In particular, preserve rules for native material/mass/density readback, bearing duty life, eccentric loads, artifact-derived critical parameters, role/region/volume-specific interference, clean assembly imports, signed thermal-fit margins, per-subject native/STEP/drawing closure, native feature-bound dimensions, metadata privacy and owned host-process cleanup.

Never allow a lesson candidate to modify an authoritative mechanical rule, test, installed plugin or readiness state. Manual promotion remains outside the tool. QA proves only two distinct recorded reviewer IDs/roles and matching hashes; an external trust chain must authenticate and authorize reviewers before any promotion decision. Red/green regression evidence and a strictly newer plugin version are also required.
