# Changelog

## Unreleased

## 1.15.2 - 2026-08-14

- Replaced role-marker-only reviewer validation with the fail-closed `aicad_selectable_vector_modifier_v1` structural contract.
- Require source-bound `cad-view` SVG entities, separate wide `view-hit` geometry, stable source/subobject IDs, semantic catalogs, model measurements, typed correction preview, and review safety locks.
- Reject raster-only PDF/image wrappers; raster content is permitted only as a declared secondary underlay beneath a complete selectable vector entity set.
- Added REVIEW-G009/G010 and negative regressions for raster wrappers, missing hit geometry, and unbound hit targets while retaining compatibility with the canonical civil/architecture modifier.
## 1.15.1 - 2026-08-14

- Added a fail-closed reviewer-first open boundary for generic drawing view requests.
- Added the `aicad_open_review_request` MCP/CLI tool; raw PDF/image/CAD paths never imply native-host intent.
- Required an explicit native-CAD switch, an allowlisted CAD suffix, and recorded modifier-before-CAD launch order.
- Added negative regression coverage for ambiguous CAD paths, raw PDFs, unmarked HTML, headless launch, MCP defaults, and CLI defaults.

## 1.15.0 - 2026-08-14

- Published deterministic standardized-regeneration review archives for the mechanical servo-reducer bracket and industrial-controller electronics packages.
- Bound the mechanical package to 54-rule preflight, native SolidWorks/AutoCAD save-reopen, drawings, BOM, analysis, and v3 evidence closure while retaining all technical/manufacturing authorization locks.
- Bound the electronics package to 63-rule preflight, accepted schematic, complete placement/pad-net parity, native KiCad ERC/DRC, constrained routing, documentation, and renders.
- Failed the electronics package closed at 37 native unconnected items; withheld Gerber, drill, and job outputs and retained every fabrication/manufacturing authorization lock.
- Added reproducible public-showcase assembly, exact SHA-256 manifests, and v1.15.0 release/source verification.

## 1.14.0 - 2026-08-14

- Added a canonical pre-geometry normative contract derived from the existing production rule inventory: exactly 54 mechanical gates and 63 electronics gates, including seven shared authority, detail, drafting, sheet, discipline and non-compensation rules.
- Added schema-backed MCP/CLI template, validation and exact-inventory QA; missing, extra, duplicate, unresolved, reference-only, cross-domain, standard-drift, conflict and unauthorized `not_applicable` mutations fail closed.
- Required an embedded passing normative preflight before mechanical/electronics 2D validation or compilation and mechanical 3D validation or SolidWorks build, before artifact directories are created.
- Kept the generation gate deliberately separate from the v3 post-generation 71/99 evidence gates; neither layer grants technical readiness or production, manufacturing or fabrication authorization.
- Repaired double-encoded requirement-conformance report literals and added an explicit UTF-8/mojibake regression.

## 1.13.0 - 2026-08-13

- Added the canonical v3 mechanical/PCB evidence-contract schema and verifier inside the existing production rule inventory while retaining the architectural v2 compatibility entry point.
- Added exact subject/expected/candidate closure. Artifact IDs and case-folded paths are unique, kinds may repeat, and the digest binds artifact ID, part/subject identity, revision, path, size and hash; selectors require complete artifact-ID maps.
- Added candidate-declared closure consistency: canonical QA parses normalized mechanical BOM subject rows and final KiCad board copper/PTH/NPTH inventory, then requires product-structure, board-inventory and CAM manifests to match exact artifact-ID/hash sets without claiming external authority.
- Persisted mechanical gates for authoritative units and inputs, independent recalculation, load paths, fasteners/joints/edges, bearing life, thermal envelope, manufacturing definition, inspection trace, model/drawing/inspection parity and native source/material persistence.
- Persisted PCB gates for per-PCB native schematic/project/board, schematic PDF, BOM, CPL, assembly drawing, independent fabrication drawing, 3D board and same-revision CAM closure; bidirectional pad/net and footprint parity; official package/datasheet/Pin 1 authority; placement/edge/keepout checks; zero final unconnected and ignored/excluded ERC/DRC items; and functional/thermal/EMC/integrity analysis.
- Limited the generic v3 conclusion to `evidenceContractReady`: it never authenticates evidence, replays native tools, grants `technicalPackageReady`, exposes candidate artifacts or authorizes production.
- Added deterministic failure-to-lesson harvesting with exact report/event/hash closure and a strict prevention-rule/failure-alias catalog for current mechanical, electronics and release failures.
- Kept learning candidate-only: JSON writes are confined below `learning/`; recorded reviewer IDs are not authenticated by the tool, promotion eligibility and every technical/release/manufacturing authorization remain false pending external authenticated review.

## 1.12.0 - 2026-08-12

- Added one canonical cross-domain normative quality contract and derived QA for support-pair transfer, forward annotation reservations, dual viewport readability, semantic candidate cycling, document isolation, and native UTF-8 evidence.
- Added multi-storey architectural document-set, independent axis-authority and plan/view/modifier/open-target freshness contracts without permitting fixed-module grid compensation.
- Added deterministic sanitized GitHub showcase assembly and required its script, regression test and public index in the publishable source tree.
- Hardened plugin and GitHub-source publication with hidden same-volume staging, independent pre-publish verification, rollback, exact manifest/SHA256 closure and source-input hash freshness.
- Updated the official build/verify/build-source commands to use one consistent `release/ci` root.

## 1.11.2 - 2026-08-12

- Added persistent no-window `stage` review mode for strict blocker reports, preventing deleted temporary review paths without creating repeated browser tabs.
- Added `ARCH-D047`, SHA-bound design-basis freshness, local-to-global axis catalogue comparison and a negative stale-`structuralGrid` regression.
- Kept architecture output blocker-only while the complete drawing set and professional authority remain absent.

## 1.11.1 - 2026-08-12

- Promoted cross-domain normative governance to the first non-compensatory gate. Requirement contracts now bind domain, delivery stage, applicable standards, domain rule packs and the authority order before geometry.
- Added `NORM-G004`: every high-priority rule must exist as a schema/contract field, generation constraint, independent QA and negative regression test; prose-only rules do not count.
- Replaced unsupported equal architectural grid modules with axes derived from prior column/core-wall supports and explicit dependency/offset proof.
- Made annotation clearance executable against resolved full axes, columns, bubbles, equipment, furniture, dimensions, door leaves and opening arcs; no-solution placement now fails closed and status notes occupy a separate band.
- Bound every declared architectural annotation class to real plan entities and semantic targets; drawing classes now derive from entity-backed sheet records instead of self-reported names.
- Added exterior opening host topology closure so continuous glazed edges cannot disappear from wall/opening and schedule contracts.
- Added annotation spatial-occupancy rules covering text, furniture, door sweeps, dimensions, axes and sheet bands; room names use constrained nearest-free-space placement.
- Added first-class service-equipment maintenance clearances with in-room, unobstructed and minimum-width proof.
- Separated interactive drawing-modifier launch from blocker-report generation: audit/blocker bundles default to `never` and no longer replace or repeatedly reopen the modifier UI.
- Added regression coverage for numeric axis semantic IDs, annotation/sheet entity bindings and service maintenance clearance.

## 1.11.0 - 2026-08-12

- Added persistent content-addressed review staging and bounded duplicate suppression; automated Agent/CLI calls now default to no browser launch.
- Added protocol-4 native DIMENSION plan/compiler/export/AutoCAD support with overall/grid/partition/opening purpose binding and real AutoCAD 2025 save/reopen XData proof.
- Replaced headless-incompatible AutoCAD Application COM usage with the native command execution path after a real Core Console capability probe returned nil.
- Added `ARCH-D038` through `ARCH-D040` and `PROD-G010` for idempotent review launch, cross-host dimension parity, physical origin-segment union invariance and blocker-only direct-production behavior.

## 1.10.1 - 2026-08-12

- Added `ARCH-D036`: blocker reviews now invoke the non-ASCII compatibility launcher and emit a source/staged-path launch record; returning a local path alone no longer counts as delivery.
- Added `ARCH-D037`: all four dimension-chain classes must resolve to native DIMENSION inventory rows with matching layer, purpose and named style.
- Added review-bundle and phantom-dimension regressions, and bumped the immutable package version instead of replacing already-uploaded 1.10.0 bytes.

## 1.10.0 - 2026-08-12

- The DXF exporter uses a standards-valid AC1018 document and real AutoCAD import/save/reopen evidence; capability surfaces are cross-checked against the implemented protocol.
- Added constrained native `text` steps with middle-centre placement, UTF-8-to-ASCII CAD escaping, audit/manifest support and real DXF/SCR/AutoCAD TEXT creation.
- Upgraded schema-2 execution to backward-compatible AICAD protocol 3 so every entity retains its semantic layer in the AutoCAD host and XData workflow.
- Applied the architectural lineweight/linetype profile across DXF, SCR and AutoCAD layers; GRID is CENTER2/0.13 mm while cut, projection, secondary, hidden and annotation layers retain their hierarchy.
- Added `ARCH-D030` through `ARCH-D035` for native axis identifiers, semantic style transport, end-to-end entity protocol parity, unique redundant-door recovery, programme-authoritative room categories and exhaustive typed occupancy clearance; added `REL-G019` for generated-target compilation after migrations.
- Architectural room contracts now require `categorySource` and `categoryReference`; production rejects categories inferred from already placed furniture. Vehicles and other typed occupancy bodies can no longer be excluded from door-clearance QA by name.
- Kept strict production-only gates: incomplete authority or drawing sets still yield blocker reports and no CAD exposure.

## 1.9.0 - 2026-08-12
- Strengthened axis-grid precompile proof: declared coordinate and coverage, two equal exterior tangent bubbles, centered matching identifiers, both directions and coordinate-ordered IDs are now non-compensatory gates.

- Made architecture CAD delivery strict-production-only through `aicad_architectural_detail_contract_v2`; non-production stage, incomplete drawing set, missing authority or failed detail gates expose blocker reports only.
- Added selectable component-role furniture/equipment profiles and exact entity binding (`ARCH-D026`).
- Added local UTF-8 HTML and opaque PNG validation reviews (`ARCH-D028`).
- Added evidence-bound production readiness v2 with file hashes, JSON Pointer readback and artifact-set binding (`PROD-G009`).

## 1.8.4 - 2026-08-12

- Added a fail-closed architectural detail contract before validate/compile artifact exposure.
- Added complete axis identity, room equipment, interior semantic layer, four-purpose native dimension and door host/opening/sweep gates.
- Bound contract geometry back to resolved AICAD entity IDs and coordinates; added blocker-only failures and regression tests.
- Added dimension-purpose AICAD XData verification and fixed duplicate model-space entity counting in architectural DXF QA.

## 1.8.3 - 2026-08-11

- Adds a non-compensatory, fail-closed production-readiness contract and machine/Chinese blocker reports.
- Deepens architectural drafting rules for complete axes, populated paper space, sheet/revision control and recognisable typed furniture linework.
- Revalidates all circulation routes after furniture/equipment edits and blocks route-clearance intersections.
- Adds scale-aware symbolic-line versus annotation-envelope collision gates.
- Stages self-contained review HTML to a hash-addressed ASCII Windows path when non-ASCII paths or direct-open failures make local review unreliable.
- Keeps production candidates review-only and prevents automated acceptance or self-signing.
- Derives Windows compatibility paths from environment/system roots and locks release verification to a no-bytecode process tree.

## 1.8.2 - 2026-08-11

- Added ARCH-D014: validation/audit reports now require complete root-cause records, stable unique prevention-rule IDs and repeat-run idempotence.
- Added a shared report-invariant module plus scripts/aicad_report_qa.py with positive and negative regression fixtures.
- Fixed post-validation reports that could append the same lessons on every rerun; identical records collapse and conflicting records fail.
- Preserved all architectural axis, annotation, AutoCAD XData and review-only safety gates from 1.8.1.


## 1.8.1 - 2026-08-11

- Added architectural drafting semantics for plan-cut, projection, hidden/overhead, route, datum, furniture and annotation objects.
- Propagated `source.cad_layer` into every selectable 2D reviewer entity so wall/column weights, dashed routes and centerline grids remain visible.
- Added `ARCH-D001` through `ARCH-D006`, a machine-readable rule pack and `aicad_architecture_qa.py` for DXF layer, effective linetype and native DIMSTYLE gates.
- Recorded the root cause: valid geometry had been mistaken for complete drafting quality, while the reviewer erased real DXF lineweight differences with one hard-coded stroke.
- Added positive and negative regression tests so all-continuous routes or a uniform semantic renderer fail before delivery.
- Changed production installation to copy only integration-manifest allowlisted files; REL-G017 blocks test caches and temporary files from entering the installed plugin.

## 1.8.0 - 2026-08-11

- Added automatic source-bound review HTML generation and desktop launch after interactive 2D/3D builds.
- Added `review_launch=auto|always|never` for CLI and Agent tools with explicit CI/headless degradation.
- Restricted the launcher to existing local HTML while preserving all review and acceptance safety locks.
- Made the shared coordinate-system switch persist its hidden/visible choice across review reopen while synchronizing 2D axes, origins, and the 3D triad.
- Made production installation byte-preserving so plugin manifest, integration manifest, and SHA256SUMS remain verifiable after install; development cache busting is no longer silently applied to release installs.
- Added REVIEW-G001 through REVIEW-G004 and compile/launcher regression coverage.

## 1.7.0 - 2026-08-11

- Added typed compiled-model measurements for every selectable line, point, circle and face.
- Added right-handed MODEL_XYZ axes, per-view origin markers and one synchronized visibility switch across SVG and rotating 3D views.
- Added click-to-prefill from selected length, coordinates and radius values.
- Corrected horizontal/vertical rectangle edge mapping to width/height controllers.
- Added SUB-G016/SUB-G017 plus real-Chrome line/point/circle and coordinate-toggle regression coverage.

## 1.6.0 - 2026-08-11

- Unified natural-language and exact numeric corrections into one visible modification list while preserving source-bound transactions in collapsed advanced evidence.
- Added arbitrary semantic section planes with selectable feature intersections.
- Added hover-discovered centers, center axes, pitch circles and interface edges with independent hit tolerance.
- Added clickable core feature parameters and point-coincident relation support.
- Added SUB-G011 through SUB-G015 and real-Chrome regression coverage for the new interaction contract.

## 1.5.0 - 2026-08-11

- Added formal exact line/circle/face correction transactions with source-hash binding, preserve policies, shared-pattern fanout protection, and full dependency replay.
- Added product-level positive residual-wall validation to prevent a corrected bore or pocket from deleting its supporting boss.
- Added a real-browser multiview transaction gate with thin precision strokes, independent hit targets, ambiguity blocking, UTF-8 checks, and exported correction evidence.
- Added native SolidWorks persistent references for ordered sketch primitives and uniquely classified BREP edges/faces.
- Embedded the topology catalog in SLDPRT custom properties and added real save/reopen per-record resolution plus exact key-set equality checks.
- Encoded COM-wrapper lifetime and custom-property prefix failures as SW-N008/SW-N009 prevention rules.
## 1.4.0 - 2026-08-11

- Added calibrated webpage/SVG/image reference reconstruction with direct DOM object evidence and source hash pinning.
- Added exact geometry, dimension, annotation text/position/rotation, style hierarchy, mojibake, and controlled layout-offset gates.
- Added aspect-ratio-preserving SVG/HTML previews and a real-browser visual QA script that records PNG/report hashes in the manifest.
- Added MCP resources/tools and CLI commands for reference schema, validation, and artifact builds.
- Added precision 3D subobject selector mappings with thin visible strokes, independent hit targets, and explicit shared-parameter edit scope.
## 1.3.4 - 2026-08-10

- Declared `jsonschema>=4.23,<5`, which is directly required by the normality and whole-requirement schema gates.
- Added REL-G013 and a clean-environment dependency-closure regression after GitHub Actions exposed the developer machine's ambient dependency.
- Updated third-party notices, release manifests and documentation so runtime imports and install declarations remain coherent.

## 1.3.3 - 2026-08-10

- Added a repository-wide `.gitattributes` policy that fixes text files to LF and marks release binaries as binary.
- Added REL-G012 and a dedicated regression proving that byte-level release manifests must survive a real Windows Git marketplace checkout.
- Extended the release gate to require both isolated behavior tests and installed-cache hash verification from the remote tag.

## 1.3.2 - 2026-08-10

- Fixed Git marketplace packaging so it installs the fully assembled, hash-verified runtime instead of the source template.
- Added REL-G011 and CI coverage requiring the isolated marketplace copy to contain `runtime/src/aicad` and pass the complete plugin regression suite without repository source paths.
- Added real remote-tag installation and post-install behavior verification to the release checklist.

## 1.3.1 - 2026-08-10

- Added detailed Chinese feature, installation and release documentation with an interaction-review screenshot.
- Added machine-readable whole-drawing requirement-contract and evidence-trace schemas.
- Added independent macro conformance checks for user intent, source authority, high-impact assumptions, conflicts, typed product/closure identity, major features, dimensions and required outputs.
- Bound every hard observed value to the selected structure template, actual parameter instance or contract, and require boundActual == observed == expected; a 120 self-report against an actual 121 instance is a blocking regression.
- Added a non-skippable guarded pipeline: whole intent, detail normality, then isolated deterministic artifact build and hash audit.
- Added PKG-G024/PKG-G025, LESSON-017/LESSON-018 and eleven executable red/green regressions.
- Verified the default top-tuck/automatic-bottom case with 12/12 hard requirements before its existing 144/144 detail proof and six-artifact guarded build.

## 1.3.0 - 2026-08-10

- Added the versioned bounded-normality contract, JSON Schema and independent Jacobian-rank prover.
- Added typed top/bottom closure selection and the ECMA A60.20.00.03 top-tuck/bottom-auto-lock default.
- Added complete face/process-region, endpoint ownership, contour, bounding-box and coupled parameter-domain gates.
- Added red/green regressions proving that full rank alone cannot catch an inward flap waist or the wrong mirrored closure family.
- Added PKG-G023, LESSON-016, EFC-PREVENT-154, EFC-TEST-015 and EFC-PIPELINE-137.

## 1.2.0 - 2026-07-12

- Rebuilt from latest source because 1.1.0 omitted packaging rules/QA/tests and AutoCAD integration assets.
- Added PKG-G001 through PKG-G021 packaging prevention rules and self-contained regression fixtures.
- Parameterized dimension-chain QA; removed case-specific dimensional constants.
- Added honest no-host status and true SolidWorks `--no-execute` offline plan export.
- Unified component version metadata and removed personal SolidWorks SDK path.
- Added strict AI Apprentice request/result contracts, adapters, hashes and safety locks.

## 1.1.0

- Added Codex MCP surface and SolidWorks 3D transaction host.
