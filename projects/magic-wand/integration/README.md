# 魔法棒系统整合审查包（Rev A）

状态：**review_only_pre_evt_open_blockers**。本目录把机械、电子、固件和系统需求串成一份可审计的 EVT 前审查包；它不是工厂生产放行包。

## 一眼结论

- 可做：需求/接口审查、机械 STEP/DXF 询价与 DFM 讨论、KiCad 录入准备、主机侧固件契约审查、EVT→DVT→PVT 规划和粗算。
- 不可做：PCB 投板、生产放行、直接市电控制、无人机武装/动力/主飞控，或宣称 ERC/DRC、目标固件、HIL、RF、结构、锂电和法规已经通过。
- 当前开放阻塞项：18 个；所有授权锁保持关闭，`reviewOnly=true`。
- 浏览器总览：`system-review-overview.svg`。所有注释位于边框内，电源/RF/安全/普通信号采用不同线宽和线型。

## 交付索引

- `integration-status.json`：可做/不可做和各域状态；
- `system-interface-control.json` / `.md`：wand↔receiver、机械↔PCB、电源、RF、press-to-arm、安全输出边界；
- `system-traceability.json`：SYS-001..012 原文级追溯；
- `combined-bom.json` / `.csv`：机械+电子合并 BOM，未询价单价保持 `null`/空白；
- `system-fmea.json`：系统 FMEA；
- `evt-dvt-pvt-plan.json` / `.md`：阶段门和工厂打样/询价边界；
- `rough-cost-estimate.json` / `.md`：人工、OpenAI API、DeepSeek API 粗算；
- `system-blockers.json`：源域阻塞项与系统级阻塞项；
- `delivery-manifest.json`：真实 path/size/SHA-256 清单。

## SYS-001..012 总览

| ID | 类别 | 源状态 | 当前验证状态 | 开放阻塞 |
|---|---|---|---|---|
| SYS-001 | mechanical | design_defined_physical_test_pending | evidence_pending | MW-BLK-002, MW-BLK-003, MW-BLK-005, INT-BLK-001 |
| SYS-002 | functional_safety | implementation_and_test_pending | evidence_pending | BLK-FW-001, INT-BLK-002 |
| SYS-003 | functional_safety | implementation_and_test_pending | evidence_pending | BLK-FW-001, INT-BLK-002 |
| SYS-004 | gesture | algorithm_and_dataset_pending | evidence_pending | BLK-FW-001, INT-BLK-003 |
| SYS-005 | communications_security | implementation_and_security_review_pending | evidence_pending | BLK-FW-001, INT-BLK-003 |
| SYS-006 | power | ordered_parts_and_bench_test_pending | evidence_pending | BLK-EDA-001, BLK-SIM-001, BLK-MECH-001 |
| SYS-007 | radio_mechanical | pcb_layout_and_rf_test_pending | evidence_pending | MW-BLK-004, INT-BLK-004 |
| SYS-008 | receiver_interfaces | eda_and_bench_test_pending | evidence_pending | BLK-EDA-001, INT-BLK-002 |
| SYS-009 | mains_boundary | external_specialist_required | evidence_pending | BLK-SAFE-001, INT-BLK-005 |
| SYS-010 | drone_boundary | external_specialist_required | evidence_pending | BLK-SAFE-001, INT-BLK-005 |
| SYS-011 | human_factors | implementation_and_test_pending | evidence_pending | BLK-FW-001, INT-BLK-002 |
| SYS-012 | release | enforced | release_lock_control_enforced | INT-BLK-006 |

## 放行声明

机械包虽有实际 SolidWorks 零件重开证据，仍缺侧孔、原生装配干涉、材料/结构和制造图闭环；电子包只有逻辑连接意图，没有原生 KiCad、ERC/DRC、CAM 或板级实测；固件没有目标构建、烧录、HIL 或独立安全审查。因此整机只能作为 review-only 的 EVT 输入。

## 复现

在仓库根目录执行：

```powershell
python projects/magic-wand/integration/build_package.py --check
python tests/test_magic_wand_integration_package.py
```
