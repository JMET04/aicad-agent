---
name: aicad-draw
description: Convert natural-language or structured requirements into deterministic, origin-anchored and auditable 2D CAD using agent-native tools. Use for drawing or validating line, circle, and arc geometry; producing DXF, AutoCAD SCR/AICAD, audit, or manifest files; fixing inaccurate AI-generated CAD; enforcing mathematical relations between sequential entities; or avoiding command-stream mojibake.
---

# AI CAD Constraint Drawing

Use the bundled tools as the execution boundary. Do not emit raw AutoCAD commands from model text and do not hand-edit `.aicad` files.

## Core workflow

Use this order. Do not skip or rearrange it:

0. Load `rules/normative_governance_rules.json`. Declare `domain`, `deliveryStage`, `selectedRulePacks`, `applicableStandards` and highest-to-lowest source authority before interpreting preferences or creating geometry. The normative gate is first and non-compensatory in every domain; a missing domain pack, standard edition/scope, or standard-bound governed requirement blocks all later stages.
1. Understand the whole request before drawing. Separate explicit user facts, approved numeric inputs, selected standards, CAD references, image-only references, preferences, forbidden features and assumptions.
2. Freeze a `aicad_drawing_requirement_contract_v1` document using `rules/drawing_requirement_contract.schema.json`. Give every hard requirement an ASCII ID, source, typed expected relation and confirmation policy. Declare the product type, use case, units, structure family, top and bottom functions, dimensions, required/allowed/forbidden major features, outputs and safety locks.
3. Resolve conflicts by the declared source authority. Never derive engineering dimensions from image pixels. A high-impact assumption that changes product type, structure, closure, fit or a critical dimension must be confirmed rather than merely disclosed.
4. Create a `aicad_drawing_requirement_trace_v1` document using `rules/drawing_requirement_trace.schema.json`. Record the actual typed design identity and one observed value, resolvable actualBinding and evidence path for every hard requirement. Bind identity/features to the selected template and dimensions to the bound parameter instance; copied self-reported values are not proof.
5. Run `scripts/aicad_requirement_conformance.py`. If it fails, stop: do not load geometry, add more line constraints or create DXF/AICAD/SCR. A geometrically perfect wrong product is still wrong.
5a. For `mechanical` or `electronics`, call `aicad_get_engineering_preflight_template`, resolve every rule application from the canonical shared rules plus the domain profile, run `aicad_validate_engineering_preflight`, and embed the passing contract as `engineering_normative_preflight` in the plan. Missing, extra, duplicate, unresolved, reference-only or authority-free rules block validation and compilation before any output directory is created. Never hand-author a shorter checklist.
6. Select the exact versioned structure-family normality template. Author the origin-anchored schema 2.0 plan and logical geometry catalog. Every entity still needs purpose, reasoning, dependencies and sufficient mathematical constraints. Axis identifiers and geometry-bound tags must be real constrained TEXT steps; post-processed labels cannot satisfy the contract. Semantic architectural layers must preserve the normative linetype and lineweight through AICAD protocol 3, SCR, DXF and host readback.
7. Run `scripts/aicad_normality_prover.py`. Require plan/geometry bijection, one named owner per endpoint, full independent constraint rank, one simple closed contour when applicable, complete feature/face contracts, functional formulas, bounding box and coupled parameter-domain regression.
8. Use `scripts/aicad_guarded_delivery.py` as the candidate-output boundary. It reruns stage 1 and stage 2 in order, compiles only after both pass, verifies every required artifact, enforces ASCII execution channels and audits hashes before exposing the output directory. For architecture with strictProductionOnly=true, also require `aicad_architectural_detail_contract_v2`, typed object profiles from `architectural_symbol_profiles.json`, the full production drawing-set matrix and evidence-bound production readiness v2. Concept/review CAD is not exposed.
9. Inspect the returned manifest and audit. When presentation matters, require an opaque original-resolution visual check. When native CAD or persistence matters, perform a real host save/reopen and XData/layer/coordinate audit. Keep human engineering review for risks that are not mathematically modeled.

For a trivial rectangle, circle, arc, or rectangular plate with one centered hole, `aicad_generate` remains available as a low-risk shortcut. A caller-supplied low-risk schema 2.0 plan can still use `aicad_compile_plan`. Do not use either shortcut for packaging, closure systems, multi-face products, fit-critical parts or any request with reference material and conflicting sources.

## Opening and result presentation policy

Treat `open`, `show`, `view`, `inspect`, `look at`, and equivalent requests as requests for the current interactive drawing modifier. Call `aicad_open_review_request` only with a source-bound HTML that satisfies `aicad_selectable_vector_modifier_v1`: real `cad-view` SVG entities, one separate wide `view-hit` target per selectable entity, stable `data-view-entity-id`, `data-source-id`, `data-source-subobject`, CAD layer identity, a semantic entity catalog, model measurements, and typed correction preview with `reviewOnly=true` and `accepted=false`. The role marker `data-artifact-role=interactive_drawing_modifier` is necessary but never sufficient. A PDF/image browser with pins or comments is not a CAD modifier and must fail closed. Raster content is permitted only as an explicitly declared secondary underlay beneath a complete selectable vector entity set.

Never use an OS file opener directly on PDF, PNG, DWG, DXF, STEP, SLDPRT/SLDASM, or KiCad artifacts for a generic view request, and never substitute a stale showcase reviewer. Merely receiving a raw artifact path is not explicit native-CAD intent.

Open native CAD only when the user explicitly asks for native CAD editing or output. In that case pass the allowlisted existing CAD path and set `open_native_cad=true`; the tool must launch the modifier first and block CAD if that launch does not occur. Keep `open_native_cad=false` for every ambiguous request.

## Webpage and image reference reconstruction

When the request is to reproduce a drawing from a webpage, SVG, PDF, screenshot, or image:

1. Call `aicad_get_reference_rebuild_schema` and read [WEB_REFERENCE_REBUILD.md](../../docs/WEB_REFERENCE_REBUILD.md).
2. Never treat pixel distance as a physical dimension. Use explicit dimension labels, a user baseline, or native vector units as calibration authority.
3. For webpage SVG sources, pin the source hash and bind the actual DOM IDs for geometry and text. Do not validate a manually copied contract against itself.
4. Require one reference object per CAD target, exact text evidence, calibrated position, transformed rotation, drafting hierarchy, and complete annotation coverage.
5. Keep `source_exact` layout by default. Permit `optimized_offset` only for a measured collision, with an explicit reason and maximum displacement budget.
6. Run `aicad_validate_reference_rebuild`, then `aicad_build_reference_reconstruction`.
7. Run `scripts/aicad_reference_visual_qa.cjs` in a real browser and require every visual gate to pass before presenting the preview.
8. State that the portable DXF uses editable MTEXT and deterministic dimension graphics. Native AutoCAD DIMENSION objects, DWG layouts, XData persistence, and save/reopen remain host gates.
## Architectural plan drafting

For architectural plans, read `rules/architectural_drafting_rules.json` and [ARCHITECTURAL_DRAFTING.md](../../docs/ARCHITECTURAL_DRAFTING.md) before producing a review artifact.

1. Classify every object as plan-cut, visible projection, hidden/overhead, datum, symbolic route, movable furniture, fixed casework, sanitary fixture, appliance, dimension or text. Layer names and colors alone are not proof.
2. Apply the typed default hierarchy unless a supplied office standard has higher authority: column/wall 0.70/0.60 mm continuous; opening/projection 0.30/0.25 mm continuous; furniture/casework/sanitary/appliance/dimension 0.18 mm continuous; route/overhead 0.18 mm dashed; grid 0.13 mm centerline.
3. Install the linetype table and set a model-space linetype scale that makes dashes visibly distinct at the intended plot scale. Reject an all-continuous drawing.
4. Keep dimensions as plan-native DIMENSION entities driven by a persisted named style and protocol 4. Bind both endpoints to earlier physical geometry, require measurement/orientation/base-offset proof, and require distinct overall, grid, major-partition and opening-purpose chains. Reserve an annotation envelope, place local chains closest and overall dimensions farther out, and reject text or dimension collisions.
5. Preserve the same layer semantics in DXF/DWG, raster/PDF preview and the interactive reviewer. A uniform review renderer is a delivery failure even if the DXF layer table is correct.
6. Build a global axis catalogue before floor-local geometry. Every axis needs one centerline, two tangent axis bubbles and two centered identical identifiers; verify local coordinate plus storey transform, identifier uniqueness and cross-floor consistency. A centerline without bubbles/identifiers is a delivery failure.
7. Expand the stage-specific annotation completeness matrix. A concept plan accounts for room names, dimensions, door/window tags, stair direction, level datum, north indicator, title, units and review state; construction plans additionally require section/elevation/detail and schedule references, sheet number and plot scale. Declare conditional omissions explicitly.
8. Bind every symbol/tag to its source geometry, reserve annotation envelopes in the order content, axis bubbles, chain dimensions, overall dimensions, then notes, and run scale-aware collision/readability checks.
9. Before compile, author `aicad_architectural_detail_contract_v2`, call `aicad_validate_architecture_detail_contract` (or `scripts/aicad_architecture_detail_qa.py`), and stop with `blocker_report_only` on failure. The contract must prove complete axis groups, room programme provenance (`categorySource` plus `categoryReference`) before the room equipment matrix, semantic interior layers, four dimension purposes, and door host-opening-sweep topology. Production rejects room categories inferred from contents. Every typed occupancy body participates in door/route clearance unless a reviewed non-occupying semantic class explicitly excludes it.
10. Run scripts/aicad_architecture_qa.py on the final DXF, then perform a rendered visual check and a native host save/reopen when DWG is requested. Record the failed invariant, root cause, correction and candidate prevention rule before redrawing.
11. Before delivery, merge root-cause lessons by stable prevention-rule ID and run scripts/aicad_report_qa.py on validation.json. Repeated runs with unchanged inputs must preserve the same canonical lesson inventory; conflicting duplicate IDs are a hard failure.
12. Furniture and fixtures required by the brief must be typed selectable linework, not labels or occupancy rectangles. Validate the minimum component matrix for each family, including sofa back/front edges, arms, seat edge and cushion divisions, plus scale and clearances. Every furniture/equipment edit must replay all dependent circulation routes and fail on any route intersection with the occupancy plus clearance envelope.
13. If the user requests construction-ready architecture, use `rules/production_readiness_contract_v2.schema.json` with `scripts/aicad_production_readiness_qa_v2.py`. For mechanical or electronics evidence-contract verification, use the canonical v3 schema/QA described below. V3 exposes only its report and may conclude only `evidenceContractReady`; it never exposes candidate artifacts or grants technical, manufacturing, fabrication or release readiness.

## Plan every entity mathematically

For each entity, determine before submitting the plan:

- its functional purpose;
- the earlier point or entity it depends on;
- the minimum constraints that uniquely determine it;
- whether it closes, continues, parallels, or is perpendicular to earlier geometry;
- whether it duplicates geometry, has zero size, or creates an unintended gap.

Anchor the first line start or first radial center at `origin`. Prefer references to earlier endpoints, midpoints, and centers. Use an explicit origin-relative offset only when no earlier geometric point is appropriate.

The origin protocol must not deform the product. Translate the model coordinate system so a real typed physical segment starts at (0,0). Never add a full-span auxiliary super-line that overlaps walls/openings; any anchor split must preserve the exact semantic union and reject duplicate or cross-role coverage.

## Three non-compensatory proof levels

Treat a drawing as the conjunction of independent gates, never as an average score:

- Whole-intent proof: the actual product and structure match every hard user requirement.
- Detail proof: every line, vertex, relation, contour, face, functional equation, process boundary and allowed parameter combination is reliable.
- Artifact proof: all requested files were built from the proved plan, execution channels are safe, the manifest matches and hashes are complete.

If any gate fails, later gates are blocked. More constraints cannot repair a wrong product family, and visual similarity cannot repair an unproved dimension.

Read [plan-schema.md](references/plan-schema.md) before authoring a non-template plan. Read [examples.md](references/examples.md) for tool-call patterns. Read [failure-recovery.md](references/failure-recovery.md) only after a tool rejects a request or plan.

## Result handling

Return the most useful artifacts to the user:

- `.dxf` for portable geometric review;
- `.aicad` for the validated AutoCAD plugin executor;
- `.scr` only as an explicit AutoCAD script fallback;
- `.audit.md` for entity purpose, relations, and reasoning;
- `.manifest.json` for hashes, counts, and artifact inventory;
- `.plan.json` as the editable source of truth.

For a strict production-only architecture request, these CAD artifacts are returned only after the v2 architectural and production-evidence gates pass. Any failure returns JSON plus a local UTF-8 `.review.html`, opaque white-background `.review.png`, and machine-readable `launch.json`; Markdown is supplemental. The report emitter must call the non-ASCII compatibility launcher and record source/staged paths; returning a path string alone is not delivery proof.

Never claim that a drawing was created when the tool returned `ok: false`, when only validation ran, or when an expected artifact path does not exist.

Never present a candidate as ready merely because the guarded build passed. State which post-build gates were actually run: visual inspection, native CAD save/reopen, persistence audit and human engineering review. Keep `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true` unless a separately authorized governance process changes them.

## CLI fallback

When MCP tools are unavailable, invoke the bundled script from the plugin root:

```powershell
python scripts/aicad_agent.py capabilities
python scripts/aicad_agent.py open-review --review-html build/job/drawing.modifier.html
python scripts/aicad_agent.py generate --request "120x80 plate with centered diameter 20 hole" --out build/job
python scripts/aicad_agent.py generate --request-file request-utf8.txt --out build/job
python scripts/aicad_agent.py validate --plan drawing.plan.json
python scripts/aicad_agent.py compile --plan drawing.plan.json --out build/job
python scripts/aicad_agent.py reference-validate --plan drawing.plan.json --reference drawing.reference.json
python scripts/aicad_agent.py reference-build --plan drawing.plan.json --reference drawing.reference.json --out build/reference --name drawing
node scripts/aicad_reference_visual_qa.cjs build/reference/drawing.preview.html build/reference/drawing.visual-validation.json build/reference/drawing.preview.png
python scripts/aicad_agent.py architecture-detail-schema
python scripts/aicad_agent.py architecture-detail-validate --contract drawing.architecture-detail.json --plan drawing.plan.json
python scripts/aicad_architecture_detail_qa.py drawing.architecture-detail.json --plan drawing.plan.json --output build/reports/drawing.architecture-detail-qa.json --markdown build/reports/drawing.architecture-detail-qa.md
python scripts/aicad_architecture_qa.py build/job/drawing.dxf --output build/reports/drawing.architecture-qa.json
python scripts/aicad_report_qa.py build/reports/validation.json --output build/reports/report-quality.json
python scripts/aicad_production_readiness_qa_v2.py production-contract-v2.json --output build/reports/production-readiness.json --markdown build/reports/production-readiness.md --html build/reports/production-readiness.review.html --png build/reports/production-readiness.review.png
python scripts/aicad_requirement_conformance.py --contract requirement-contract.json --trace requirement-trace.json --normality-template structure.normality.json --normality-instance drawing.instance.json --out-json build/reports/requirement.json --out-md build/reports/requirement.md
python scripts/aicad_guarded_delivery.py --contract requirement-contract.json --trace requirement-trace.json --plan drawing.plan.json --geometry geometry.json --template structure.normality.json --instance instance.json --out build/candidate --report-dir build/reports --name drawing
python scripts/aicad_architecture_detail_qa.py drawing.architecture-detail.json --plan drawing.plan.json --output build/reports/architecture.json --html build/reports/architecture.review.html --png build/reports/architecture.review.png
python scripts/aicad_production_readiness_qa_v2.py production-contract-v2.json --output build/reports/production.json --html build/reports/production.review.html --png build/reports/production.review.png
```

Parse stdout as one JSON object. A successful call has `ok: true`; failures are JSON on stderr with a stable `error.code`.

## Mechanical/electronics normative generation preflight

`rules/production_readiness_rules.json` is the only authoritative mechanical/electronics inventory. Before geometry, derive an exact preflight from its seven shared rules (`PROD-G001..G006`, `PROD-G013`) and the selected profile's `intent`, `design` and `manufacturingDefinition` gates. The result is 54 generation gates for mechanical and 63 for electronics. Each gate must declare a controlled requirement, authoritative source binding, generation constraint, verification method and any standard binding. `not_applicable` is forbidden for shared and intent gates; other gates require an engineering/standard authority and a specific rationale.

Use `aicad_get_engineering_preflight_schema`, `aicad_get_engineering_preflight_template` and `aicad_validate_engineering_preflight`, or the equivalent CLI:

`python scripts/aicad_engineering_preflight.py --template mechanical --output mechanical-preflight.json`

`python scripts/aicad_engineering_preflight.py --contract mechanical-preflight.json --output mechanical-preflight.report.json --markdown mechanical-preflight.report.md`

A pass authorizes only controlled generation. It does not prove the finished design, expose an artifact, replay CAD/EDA tools or set any technical/manufacturing/fabrication/release authorization. After generation, the v3 evidence contract below remains mandatory.

## Canonical mechanical/PCB evidence-contract gate

For construction-ready architecture, keep the v2 compatibility contract and QA. For a mechanical or electronics job, prepare evidence with the same authoritative `rules/production_readiness_rules.json`, then verify it with `rules/production_readiness_contract_v3.schema.json` and `scripts/aicad_production_readiness_qa_v3.py`; do not create a second rule inventory.

V3 is an evidence-contract verifier, not a technical-readiness assessor. Declare every manufactured part, assembly, or PCB design in `artifactSubjects`, then make `expectedArtifactClosure` and `candidateArtifacts` an exact bijection. Artifact IDs and case-folded paths are unique; kinds may repeat for separate parts, Gerber layers or drill outputs. Source selectors and reopen results bind every selected artifact ID, and the artifact-set digest binds artifact/part/subject identity, kind, revision, path, size and SHA-256. V3 does not authenticate evidence origin, replay a CAD/EDA host, reproduce analysis, expose candidate artifacts, or grant technical/manufacturing/fabrication/release readiness. A pass may set only `evidenceContractReady=true`; all readiness, exposure and authorization fields remain false.

For mechanical evidence, bind the operating envelope, duty cycle and design life; recomputed load combinations and abnormal cases; equation/input/output/margin trace; strength/stiffness/fatigue/FoS; fastener, joint, bearing and thermal margins; risk controls; mating fits, threads, undefined edges, tolerances/GD&T/roughness; process capability and measurement method; native material-database assignment; BOM/revision/inspection parity; and feature-bound drawing dimensions/datums/FCFs. Never treat custom properties or volume-times-density as native material evidence. Every manufactured part and required assembly needs its own native CAD, STEP and manufacturing drawing plus source-hash and native-reopen evidence. Supply one `aicad_machine_mechanical_bom_v1` JSON BOM with a positive-quantity row for every exact subject type/revision/artifact-ID set. The `aicad_product_structure_manifest_v1` must bind that BOM hash and repeat the same rows. Generic QA parses both and proves only candidate-declared consistency.

For electronics evidence, resolve the exact ordered MPN to symbol pins by number, function and electrical type; bind ratings/derating, power/startup/fault recovery, transient energy and protection coordination, analog/filter/clamp/ADC accuracy, clock/reset/programming/protocol, grounding/isolation/common mode, connector/tool/enclosure and test access; prove bidirectional pad/net and BOM/footprint parity; require zero final unconnected nets and zero ignored/excluded ERC/DRC items; and bind granular Gerber layers and plated/non-plated drill/CAM outputs to the same source revision. Each `pcb_design` must own its own KiCad project/schematic/board, schematic PDF, BOM, CPL, assembly drawing, fabrication drawing, 3D board, job file, CAM manifest and all Gerber/PTH/NPTH drill outputs; never let one package-level output satisfy multiple PCB subjects. Do not collapse repeated Gerber or drill artifacts into a single kind slot. Generic QA parses the final `.kicad_pcb` S-expression to derive copper layers and PTH/NPTH presence, then requires `aicad_native_board_fabrication_inventory_v1` and `aicad_cam_output_manifest_v1` to match every named layer, typed drill and job artifact-ID/hash in both directions. This proves candidate-declared consistency only; native host replay and external authenticity remain separate gates. Dynamic supplier stock, price and fabricator capability require a timestamped snapshot plus order-time recheck policy.

`python scripts/aicad_production_readiness_qa_v3.py production-contract-v3.json --output build/reports/production-readiness-v3.json --markdown build/reports/production-readiness-v3.md`

## Controlled continuous learning

Whenever a test or gate fails, read `rules/continuous_learning_rules.json` and create an `aicad_test_failure_report_v1` that declares every actual failed check exactly once. Each row must include a stable failure alias; failing test/gate; symptom, root cause and correction; one disabled prevention-rule candidate; a minimal negative regression; and safe-relative size/SHA-256 closures for the reproducer, evidence, source inputs and affected artifacts. Run `scripts/aicad_lesson_harvester.py` with an explicit `--root`, then audit the bundle with `scripts/aicad_continuous_learning_qa.py`. Missing, extra or mixed lessons, conflicting same-ID content, absolute/traversal/link paths and stale hashes are hard failures.

The loop is controlled learning, not unattended self-modification. Candidate locks always remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`, and output is restricted to JSON below `learning/`. A promotion preflight verifies only that recorded red-before-fix, green-after-fix, unrelated-suite pass and two distinct reviewer IDs are bound to the same bundle SHA-256, target rule and strictly newer version. It does not authenticate reviewer identity or grant eligibility; external authenticated review is mandatory. The tools never rewrite authoritative rules or tests, change an installed plugin/version, package, install, publish, accept a design, or unlock technical/manufacturing/fabrication readiness.

```powershell
python scripts/aicad_lesson_harvester.py reports/failures.json --root . --output learning/candidates.json
python scripts/aicad_continuous_learning_qa.py learning/candidates.json --root . --output learning/audit.json
```
