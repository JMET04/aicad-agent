# EVT → DVT → PVT 与工厂打样清单

当前门：**pre_EVT_definition_blocked_from_pcb_fabrication_and_production**。机械文件仅可用于带 REVIEW ONLY 标识的询价/DFM 讨论；电子文件禁止投板。

| 阶段 | ID | 必需证据 | 状态 |
|---|---|---|---|
| EVT | EVT-001 | Freeze exact battery, haptic, switch, connectors, PCB outlines and controlled datasheet revisions | open |
| EVT | EVT-002 | Add missing native press-to-arm side cut and prove native assembly fit/interference/reopen | blocked |
| EVT | EVT-003 | Capture wand and receiver in KiCad; peer-check symbols/footprints/pins; run zero-unresolved ERC/DRC | blocked |
| EVT | EVT-004 | Export revision-bound schematic PDF, PCB, BOM, CPL, assembly/fab drawings, Gerbers and PTH/NPTH drills | blocked |
| EVT | EVT-005 | Target-build/flash pinned firmware and run host unit tests plus target HIL fault/security tests | blocked |
| EVT | EVT-006 | Build supervised mechanical samples and PCBA engineering samples with incoming inspection | blocked |
| EVT | EVT-007 | Measure charge/thermal, rail transient, RF, I/O loads, arm/link-loss timing and gesture confusion matrix | blocked |
| EVT | EVT-008 | Independent EVT hazard review; document every failure and controlled ECO | blocked |
| DVT | DVT-001 | Freeze design inputs, material/process specifications, tolerances, firmware protocol and threat model | blocked |
| DVT | DVT-002 | Complete structural/drop/fatigue/adhesive, environmental and battery/charging validation | blocked |
| DVT | DVT-003 | Complete RF/EMC pre-scan and applicable radio, USB, battery and regional compliance plan/tests | blocked |
| DVT | DVT-004 | Validate misuse, fault injection, security, usability and all receiver interface limits on representative units | blocked |
| DVT | DVT-005 | Release native manufacturing drawings, DFM feedback, test fixtures and service/recovery instructions for review | blocked |
| PVT | PVT-001 | Approve supplier AVL, incoming controls, golden samples and revision-locked factory package | blocked |
| PVT | PVT-002 | Run pilot build with calibrated fixtures, programming/key injection, serialization and end-of-line tests | blocked |
| PVT | PVT-003 | Demonstrate yield, process capability, traceability, rework controls and failure containment | blocked |
| PVT | PVT-004 | Close independent engineering, regulatory, quality and release approvals before any production authorization | blocked |

## 工厂询价边界

- 可发：`evt-dvt-pvt-plan.json` 列出的五个机械参考文件，且只用于报价与 DFM 意见；
- 不可发作生产依据：任何电子 CSV、概念方框、未绑定原生特征的便携图或固件骨架；
- 必须回填：假定材料/工艺/公差、最小批量、单价阶梯、模具/治具、检测能力、交期和偏差；
- 投板前硬门：原生 KiCad、同行 pin/footprint 审查、零未解决 ERC/DRC、完整 CAM/PTH/NPTH 和同版 BOM/CPL；
- 每个阶段只凭实际证据关闭，不得用“计划完成”代替测试结果。
