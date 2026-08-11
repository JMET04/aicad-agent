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

- one center-pattern axis line;
- two continuous axis bubbles tangent to the two line endpoints;
- two centered, identical axis identifiers;
- stable references/XData from all members to the axis identity;
- numeric vertical axes ordered west-to-east and uppercase-letter horizontal axes ordered south-to-north;
- one global-coordinate-to-identifier mapping shared by every storey.

Build the global catalogue before floor-local geometry. Validate local coordinate plus storey transform against the catalogued global coordinate; restarting 1/A on each floor is a failure when it changes the identity of the same datum.

The stage profile is also non-compensatory. A concept architectural plan must account for room names, native overall/chain dimensions, door and window tags, stair direction, level datum, north indicator, drawing title, units and review state in addition to the complete axis grid. Construction-plan profiles add section/elevation references, wall/opening schedules, detail references, sheet number and plot scale. Conditional omissions must be declared with a reason; silent omissions fail.

Keep full-content, structural-axis and annotation envelopes separate. Remote equipment, bridges, routes and notes do not stretch the primary grid unless the axis coverage contract explicitly includes them. Reserve space in this order: model content, axis bubbles, chain dimensions, overall dimensions, then sheet notes. Resolve bubble size, text height, lineweight and dash cadence from the declared plot scale. Run geometry-binding and collision checks after every edit, not only at initial generation.

## Precompile architectural detail contract

Do not wait for a rendered drawing to discover missing axes, empty rooms or disconnected door symbols. Before compiling CAD, author `aicad_architectural_detail_contract_v1` from `rules/architectural_detail_contract.schema.json` and run `scripts/aicad_architecture_detail_qa.py`.

The contract treats the following as one dependency graph:

- every axis is a line plus two tangent bubbles and two identical identifiers inside a declared structural coverage scope;
- overall, grid, partition and opening dimensions are four distinct native-purpose chains;
- every room has a functional category and the required typed equipment families;
- movable furniture, fixed casework, sanitary fixtures and appliances stay on separate semantic layers with selectable component linework;
- every door binds to one host wall and one wall opening; the host wall is segmented around the opening; hinge, opening endpoint, leaf length, arc endpoint, sweep and clearance agree mathematically;
- construction/production stages carry the required annotation and authority evidence.

The contract is non-compensatory. A failure produces `artifactDisposition=blocker_report_only`; the generator must not compile, launch or label a review/production drawing. Any wall, opening, door, equipment or dimension edit replays the affected checks.

## Mandatory QA

Run:

```powershell
python scripts/aicad_architecture_detail_qa.py drawing.architecture-detail.json --plan drawing.plan.json --output drawing.architecture-detail-qa.json --markdown drawing.architecture-detail-qa.md
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

A complete axis grid is necessary but not sufficient. Construction-stage drawings also require typed furniture/detail linework, bound section/elevation/detail references, populated paper-space viewports, title blocks, plot scale, revision/status and schedule navigation. Run `scripts/aicad_production_readiness_qa.py` after architectural DXF QA. A failed production gate may not be offset by a high geometry score; strict production mode exposes only the blocker report.
