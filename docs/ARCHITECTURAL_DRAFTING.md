# Architectural drafting invariants

This profile prevents a geometrically valid plan from becoming an unreadable drawing. It is a candidate engineering rule set and does not replace an office CAD standard or professional review.

## Required semantic order

| Object class | Default layer | Lineweight | Linetype |
|---|---|---:|---|
| Plan-cut column | COLUMN | 0.70 mm | Continuous |
| Plan-cut wall | WALL | 0.60 mm | Continuous |
| Door/window and visible projection | OPENING / ROOM / STAIR | 0.30 / 0.25 mm | Continuous |
| Furniture, casework, sanitary fixtures, appliances and annotation | FURNITURE / CASEWORK / SANITARY / APPLIANCE / DIMENSION / TEXT | 0.18 mm | Continuous |
| Hidden, overhead and circulation | OVERHEAD / ROUTE | 0.18 mm | Dashed |
| Grid/datum | GRID | 0.13 mm | Center |

The invariant is an order, not merely a list: cut > projection > secondary/annotation. A layer must contain actual entities, and the effective entity linetype after BYLAYER resolution must be checked.

## Native dimensions

Use a named DIMSTYLE and native DIMENSION entities. For millimetre model space at a 1:100 review scale, the default candidate uses 280 mm text, 150 mm architectural ticks, 100 mm extension-line offset, 150 mm extension beyond the dimension line, 90 mm text gap and zero decimal places. Chain dimensions sit nearest the plan; the overall dimension sits farther away. Do not explode dimensions into independent lines and text.

## Cross-render parity

DXF/DWG, PDF/PNG and the interactive reviewer must all show the same hierarchy. The reviewer propagates each semantic object's `source.cad_layer` to `data-cad-layer` and a `layer-*` CSS class. This is a presentation invariant: one hard-coded SVG stroke width is a failure even when the DXF is correct.

## Complete axis-grid and annotation gates

A GRID centerline is not a complete axis. For every plan view, generate one typed axis group from a shared catalogue:

- one center-pattern axis line whose resolved endpoints span the structural coverage bounds and whose constant coordinate equals the declared datum;
- two equal-radius continuous axis bubbles on opposite exterior sides, collinear with the axis and tangent to the two line endpoints;
- two centered, identical axis identifiers whose resolved TEXT/MTEXT content equals the axis ID;
- stable references/XData from all members to the axis identity;
- one or more `supportEntityIds` resolving only to earlier column centres, core/structural-wall centres or an authority-bound datum; the axis dependency and mathematical offset must resolve to the declared coordinate;
- numeric vertical axes ordered west-to-east and uppercase-letter horizontal axes ordered south-to-north;
- one global-coordinate-to-identifier mapping shared by every storey.

Build the global catalogue before floor-local geometry. Validate local coordinate plus storey transform against the catalogued global coordinate; restarting 1/A on each floor is a failure when it changes the identity of the same datum. Never generate axes from an unsupported constant module merely because equal spacing looks orderly. Equal spacing is permitted only when the authority input or the resolved structural supports produce it.

The stage profile is also non-compensatory. A concept architectural plan must account for room names, native overall/chain dimensions, door and window tags, stair direction, level datum, north indicator, drawing title, units and review state in addition to the complete axis grid. Construction-plan profiles add section/elevation references, wall/opening schedules, detail references, sheet number and plot scale. Conditional omissions must be declared with a reason; silent omissions fail.

Keep full-content, structural-axis and annotation envelopes separate. Remote equipment, bridges, routes and notes do not stretch the primary grid unless the axis coverage contract explicitly includes them. Reserve space in this order: model content, axis bubbles, chain dimensions, overall dimensions, then sheet notes. Status notes use a distinct band and may not reuse an overall-dimension band. Resolve bubble size, text height, lineweight and dash cadence from the declared plot scale. Run geometry-binding and collision checks after every edit, not only at initial generation. Collision checks use the resolved full axis extent and real text bounding boxes, reserve already placed labels, and include columns, bubbles, equipment, furniture, dimensions, each door leaf and its sampled opening arc. If no feasible label location exists, fail closed; never place a colliding fallback label.

## Precompile architectural detail contract

Do not wait for a rendered drawing to discover missing axes, empty rooms or disconnected door symbols. Before compiling CAD, author `aicad_architectural_detail_contract_v2` from `rules/architectural_detail_contract_v2.schema.json` and run `scripts/aicad_architecture_detail_qa.py`. Version 2 is strict-production-only: concept, coordination and incomplete construction packages remain diagnostic inputs and cannot expose CAD artifacts.

The contract treats the following as one dependency graph:

- every axis is a line plus two tangent bubbles and two identical identifiers inside a declared structural coverage scope;
- overall, grid, partition and opening dimensions are four distinct native-purpose chains;
- every room has a functional category declared before contents, plus `categorySource` and `categoryReference`; production rejects `inferred_unverified`, then checks the required typed equipment families against that programme;
- movable furniture, fixed casework, sanitary fixtures and appliances stay on separate semantic layers; each object binds an actual-size closed outline and profile-specific selectable roles such as sofa backs/arms/seat divisions, bed pillows, fixture cores, drains, controls and handles from `rules/architectural_symbol_profiles.json`;
- every door binds to one host wall and one wall opening; the host wall is segmented around the opening; hinge, opening endpoint, leaf length, arc endpoint, sweep and clearance agree mathematically; vehicles, furniture, casework, sanitary fixtures and appliances all participate in clearance, while any exclusion requires a reviewed non-occupying semantic role;
- the complete production drawing-set matrix and all annotation/authority evidence are present; strictProductionOnly=true, allowIntermediateCad=false and CAD exposure is limited to production-release candidates.
- every provided drawing class resolves from `drawingSheets` to a unique sheet/layout and real plan entities; every annotation class resolves from `bindings` to real entities and its room, door, window, axis or dimension targets;
- every exterior opening has exactly one wall/envelope host, including continuous glazed boundaries; compile the host-minus-opening residual union and reject missing, ambiguous or overlapping ownership;
- every service equipment unit binds a `maintenanceClearances` rectangle inside its room, clear of every equipment bbox and not narrower than the declared project minimum;
- annotation occupancy is solved against text, furniture/equipment, door sweeps, structural geometry, axes, dimensions and reserved sheet bands. Text-to-text counting alone is insufficient.

The contract is non-compensatory. A failure produces `artifactDisposition=blocker_report_only`; the generator must not compile, launch or label a review/production drawing. Any wall, opening, door, equipment or dimension edit replays the affected checks.

## Mandatory QA

Run:

```powershell
python scripts/aicad_architecture_detail_qa.py drawing.architecture-detail.json --plan drawing.plan.json --output drawing.architecture-detail-qa.json --markdown drawing.architecture-detail-qa.md --html drawing.architecture-detail-qa.review.html --png drawing.architecture-detail-qa.review.png
python scripts/aicad_architecture_qa.py drawing.dxf --output drawing.architecture-qa.json
```

Then inspect a rendered original-resolution preview and, when DWG is requested, save and reopen in the real host. Record:

- failed invariant;
- why the process allowed it;
- the specific candidate rule preventing recurrence;
- which artifact and renderer were rechecked.

The safety state remains `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`.

## 规范报告门禁

最终验证报告本身也是交付物，不能在重复运行时不断累积相同经验。每条经验必须同时包含现象、根因、修正和稳定的预防规则 ID；相同 ID 的相同记录在写入前折叠，相同 ID 的冲突记录直接失败。使用 scripts/aicad_report_qa.py 检查完整性、ID 唯一性和安全锁；同一输入连续运行的规范化报告哈希必须一致。

## Construction and production boundary

A complete axis grid is necessary but not sufficient. Construction-stage drawings also require typed furniture/detail linework, bound section/elevation/detail references, populated paper-space viewports, title blocks, plot scale, revision/status and schedule navigation. Run `scripts/aicad_production_readiness_qa_v2.py` after architectural DXF QA. Its v2 contract rejects `passed=true` self-reporting: every machine gate is read from a hash-fixed file through a JSON Pointer, and native-host plus professional-release evidence must bind the exact artifact-set SHA-256. A failed production gate may not be offset by a high geometry score; strict production mode exposes only JSON plus a local UTF-8 HTML review and opaque PNG blocker summary. The HTML is the primary human review entry and must not require a server or external assets.

## Verified blocker-report launch

Creating an HTML file is not delivery proof. Every strict-production blocker emitter must use `write_review_bundle`, include JSON, UTF-8 self-contained HTML, opaque PNG and an automatically persisted `*.review-launch.json`, and record both the source path and the compatibility-staged path. Strict blocker emitters default to `stage`: persist content-addressed bytes without opening a browser tab. Every GUI-launched source path, including an ASCII temporary path, is also staged before opening. Browser QA must open those persisted bytes and record a rendered screenshot or equivalent DOM evidence; returning a path string alone fails `ARCH-D036`. General compile calls default to `never`, repeated identical `auto` launches are suppressed by `ARCH-D038`, and `always` is reserved for an explicit reopen request.

Dimension-chain completeness is also entity-bound. Every declared overall, grid, partition and opening dimension ID must resolve to a native `DIMENSION` inventory row on `DIMENSION`, with matching purpose and named style. The native host save/reopen report must preserve the same ID set; purpose counts without entities fail `ARCH-D037`.

## Native dimension host parity and physical origin

Schema-2 plans with dimensions use AICAD protocol 4. Every dimension endpoint references earlier physical geometry and carries measurement, orientation and base-offset proof. AutoCAD creation must use a path shared by desktop AutoCAD and `accoreconsole.exe`; Core Console may return no Application COM object. Release therefore requires a real native-command save/reopen regression that proves DIMSTYLE, entity subtype, measurement, layer and XData.

The first entity at `(0,0)` is a real wall/opening/product segment, never an auxiliary full-span line. If dimension anchors require more endpoints, split only collinear physical segments and prove that their union, ownership and semantic layer are unchanged and non-overlapping.

When the user asks for directly usable construction/production output, `PROD-G010` applies: all non-compensatory drawing-set, authority, host and authorized-release gates must pass or no CAD artifact is exposed. The only permitted failure output is the persistent blocker bundle.

## Whole-drawing review loop

After each semantic or geometric edit, replay one dependency graph in this order: envelope/wall/opening topology, rooms and typed contents, door and service clearances, plan-native annotations, drawing-sheet bindings, scale-aware occupancy, raster/vector parity, then native-host persistence. Record the observed defect, why the previous gate allowed it, the stable prevention-rule ID and the exact artifact rechecked. A failed audit report is evidence only; it never replaces or automatically opens the interactive drawing modifier.

### Design-basis freshness (`ARCH-D047`)

Axis geometry, dimensions, contracts, previews and design metadata are one dependency graph. Bind the current design-basis file by SHA-256, add each floor's local-to-global origin, compare every local axis ID and coordinate against the global catalogue, and reject fixed `structuralGrid` metadata as stale authority. A geometry fix is incomplete until every downstream artifact is regenerated or independently proven current.
