# 校验摘要

结论：**BLOCKED_FOR_FABRICATION**。公开审查包可上传；制造与封装放行被锁定。

固定状态：`reviewOnly=true`、`accepted=false`、`ruleEnabled=false`、`packagingGated=true`、`fabricationReady=false`。

| 检查 | 结果 | 影响 | 证据 | 说明 |
|---|---|---|---|---|
| LOCK-001 | PASS | 记录 | design_contract.json | Five fixed review locks match exactly. |
| ART-001 | PASS | 记录 | project/industrial_controller.kicad_pro, project/industrial_controller.kicad_sch, project/industrial_controller.kicad_pcb, project/industrial_controller.kicad_dru, outputs/bom.csv, outputs/positions.csv, outputs/review_drawing.pdf, preview/board_top_white.svg, preview/board_top_white.png, preview/board_isometric_concept.svg, analysis/schematic.json, analysis/pcb.json, analysis/cross.json, analysis/thermal.json, analysis/emc.json, analysis/gerbers.json, analysis/fab_gate.json, analysis/independent_drc.json | All required artifacts exist. |
| RAW-001 | PASS | 记录 | project/industrial_controller.kicad_pcb, project/industrial_controller.kicad_sch | Parentheses are balanced in both raw files. |
| PCB-001 | PASS | 记录 | analysis/pcb.json | Four layers; 96 x 72 mm. |
| PCB-002 | FAIL | 阻断 | analysis/pcb.json | 37 networks unrouted; this is a manufacturing blocker. |
| DRC-ALT-001 | PASS | 记录 | analysis/geometry_classification.json | Deduplicated explicit tracks: 0 hard copper conflicts and 0 clearance-only conflicts across 11503 unique pairs; native DRC still required. |
| NATIVE-001 | FAIL | 阻断 | analysis/tool_inventory.json | Native ERC, DRC, zone refill, plots and 3D were not run. |
| BOM-001 | FAIL | 阻断 | analysis/schematic.json, analysis/fab_gate.json | Manufacturer-part-number coverage below pre-fabrication threshold. |
| EMC-001 | FAIL | 记录 | analysis/emc.json | Risk analyzer has 1 error finding(s); laboratory compliance remains outside scope. |
| THERM-001 | FAIL | 阻断 | analysis/thermal.json | Analyzer assessed zero powered components. |
| GERBER-001 | PASS | 记录 | analysis/gerbers.json | Review Gerber/drill set structurally readable; not native output. |
| PREVIEW-001 | PASS | 记录 | preview/board_top_white.png, preview/board_top_white.svg | PNG 1800x1200 mode=RGB; alphaOpaque=true, four RGB corners meet >=245, and SVG has an explicit white backdrop. |
| FAB-GATE-001 | FAIL | 阻断 | analysis/fab_gate.json | Gate FAIL: {'total_checks': 12, 'pass': 8, 'warn': 0, 'fail': 4, 'skip': 0}. |

通过 7 项，失败 6 项，其中制造阻断 5 项。失败不是工具异常的同义词：40 个路由器口径未路由网络、采购覆盖、原生工具缺失、热证据缺失和总体制造门禁均为真实阻断；独立显式线段几何检查已通过。
