---
name: aicad-draw
description: Convert natural-language or structured requirements into deterministic, origin-anchored and auditable 2D CAD using agent-native tools. Use for drawing or validating line, circle, and arc geometry; producing DXF, AutoCAD SCR/AICAD, audit, or manifest files; fixing inaccurate AI-generated CAD; enforcing mathematical relations between sequential entities; or avoiding command-stream mojibake.
---

# AI CAD Constraint Drawing

Use the bundled tools as the execution boundary. Do not emit raw AutoCAD commands from model text and do not hand-edit `.aicad` files.

## Core workflow

Use this order. Do not skip or rearrange it:

1. Understand the whole request before drawing. Separate explicit user facts, approved numeric inputs, selected standards, CAD references, image-only references, preferences, forbidden features and assumptions.
2. Freeze a `aicad_drawing_requirement_contract_v1` document using `rules/drawing_requirement_contract.schema.json`. Give every hard requirement an ASCII ID, source, typed expected relation and confirmation policy. Declare the product type, use case, units, structure family, top and bottom functions, dimensions, required/allowed/forbidden major features, outputs and safety locks.
3. Resolve conflicts by the declared source authority. Never derive engineering dimensions from image pixels. A high-impact assumption that changes product type, structure, closure, fit or a critical dimension must be confirmed rather than merely disclosed.
4. Create a `aicad_drawing_requirement_trace_v1` document using `rules/drawing_requirement_trace.schema.json`. Record the actual typed design identity and one observed value, resolvable actualBinding and evidence path for every hard requirement. Bind identity/features to the selected template and dimensions to the bound parameter instance; copied self-reported values are not proof.
5. Run `scripts/aicad_requirement_conformance.py`. If it fails, stop: do not load geometry, add more line constraints or create DXF/AICAD/SCR. A geometrically perfect wrong product is still wrong.
6. Select the exact versioned structure-family normality template. Author the origin-anchored schema 2.0 plan and logical geometry catalog. Every entity still needs purpose, reasoning, dependencies and sufficient mathematical constraints.
7. Run `scripts/aicad_normality_prover.py`. Require plan/geometry bijection, one named owner per endpoint, full independent constraint rank, one simple closed contour when applicable, complete feature/face contracts, functional formulas, bounding box and coupled parameter-domain regression.
8. Use `scripts/aicad_guarded_delivery.py` as the candidate-output boundary. It reruns stage 1 and stage 2 in order, compiles only after both pass, verifies every required artifact, enforces ASCII execution channels and audits hashes before exposing the output directory.
9. Inspect the returned manifest and audit. When presentation matters, require an opaque original-resolution visual check. When native CAD or persistence matters, perform a real host save/reopen and XData/layer/coordinate audit. Keep human engineering review for risks that are not mathematically modeled.

For a trivial rectangle, circle, arc, or rectangular plate with one centered hole, `aicad_generate` remains available as a low-risk shortcut. A caller-supplied low-risk schema 2.0 plan can still use `aicad_compile_plan`. Do not use either shortcut for packaging, closure systems, multi-face products, fit-critical parts or any request with reference material and conflicting sources.

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

1. Classify every object as plan-cut, visible projection, hidden/overhead, datum, symbolic route, furniture, dimension or text. Layer names and colors alone are not proof.
2. Apply the typed default hierarchy unless a supplied office standard has higher authority: column/wall 0.70/0.60 mm continuous; opening/projection 0.30/0.25 mm continuous; furniture/dimension 0.18 mm continuous; route/overhead 0.18 mm dashed; grid 0.13 mm centerline.
3. Install the linetype table and set a model-space linetype scale that makes dashes visibly distinct at the intended plot scale. Reject an all-continuous drawing.
4. Keep dimensions as native DIMENSION entities driven by a persisted named style. Reserve an annotation envelope, place chain dimensions closest and overall dimensions farther out, and reject text or dimension collisions.
5. Preserve the same layer semantics in DXF/DWG, raster/PDF preview and the interactive reviewer. A uniform review renderer is a delivery failure even if the DXF layer table is correct.
6. Build a global axis catalogue before floor-local geometry. Every axis needs one centerline, two tangent axis bubbles and two centered identical identifiers; verify local coordinate plus storey transform, identifier uniqueness and cross-floor consistency. A centerline without bubbles/identifiers is a delivery failure.
7. Expand the stage-specific annotation completeness matrix. A concept plan accounts for room names, dimensions, door/window tags, stair direction, level datum, north indicator, title, units and review state; construction plans additionally require section/elevation/detail and schedule references, sheet number and plot scale. Declare conditional omissions explicitly.
8. Bind every symbol/tag to its source geometry, reserve annotation envelopes in the order content → axis bubbles → chain dimensions → overall dimensions → notes, and run scale-aware collision/readability checks.
9. Run scripts/aicad_architecture_qa.py on the final DXF, then perform a rendered visual check and a native host save/reopen when DWG is requested. Record the failed invariant, root cause, correction and candidate prevention rule before redrawing.

## Plan every entity mathematically

For each entity, determine before submitting the plan:

- its functional purpose;
- the earlier point or entity it depends on;
- the minimum constraints that uniquely determine it;
- whether it closes, continues, parallels, or is perpendicular to earlier geometry;
- whether it duplicates geometry, has zero size, or creates an unintended gap.

Anchor the first line start or first radial center at `origin`. Prefer references to earlier endpoints, midpoints, and centers. Use an explicit origin-relative offset only when no earlier geometric point is appropriate.

The origin protocol must not deform the product. If the real production contour has no valid first entity at (0,0), add a named non-production origin bootstrap, exclude it from the production catalog and prove the exclusion in the normality template.

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

Never claim that a drawing was created when the tool returned `ok: false`, when only validation ran, or when an expected artifact path does not exist.

Never present a candidate as ready merely because the guarded build passed. State which post-build gates were actually run: visual inspection, native CAD save/reopen, persistence audit and human engineering review. Keep `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true` unless a separately authorized governance process changes them.

## CLI fallback

When MCP tools are unavailable, invoke the bundled script from the plugin root:

```powershell
python scripts/aicad_agent.py capabilities
python scripts/aicad_agent.py generate --request "120x80 plate with centered diameter 20 hole" --out build/job
python scripts/aicad_agent.py generate --request-file request-utf8.txt --out build/job
python scripts/aicad_agent.py validate --plan drawing.plan.json
python scripts/aicad_agent.py compile --plan drawing.plan.json --out build/job
python scripts/aicad_agent.py reference-validate --plan drawing.plan.json --reference drawing.reference.json
python scripts/aicad_agent.py reference-build --plan drawing.plan.json --reference drawing.reference.json --out build/reference --name drawing
node scripts/aicad_reference_visual_qa.cjs build/reference/drawing.preview.html build/reference/drawing.visual-validation.json build/reference/drawing.preview.png
python scripts/aicad_architecture_qa.py build/job/drawing.dxf --output build/reports/drawing.architecture-qa.json
python scripts/aicad_requirement_conformance.py --contract requirement-contract.json --trace requirement-trace.json --normality-template structure.normality.json --normality-instance drawing.instance.json --out-json build/reports/requirement.json --out-md build/reports/requirement.md
python scripts/aicad_guarded_delivery.py --contract requirement-contract.json --trace requirement-trace.json --plan drawing.plan.json --geometry geometry.json --template structure.normality.json --instance instance.json --out build/candidate --report-dir build/reports --name drawing
```

Parse stdout as one JSON object. A successful call has `ok: true`; failures are JSON on stderr with a stable `error.code`.
