# 魔法棒系统整合审查包（Rev A）

Status: **legacy Rev A baseline, superseded for current execution status by `CURRENT_SYSTEM_STATUS.json` and `SYSTEM_ENGINEERING_HANDOFF.md`**.

## 一眼结论

- Current verified artifacts: zero-error frozen wand PCB, JLC bare-board upload ZIP, printable enclosure package, and host-tested eight-class gesture core. Use them only within the explicit prototype limits.
- Current exception: the owner authorized the verified wand **prototype bare-PCB** order and prototype 3D print. PCBA, target firmware and production release remain prohibited.
- The legacy 18-blocker count below is retained as historical Rev A evidence; use the current status file for live gates.
- 浏览器总览：`system-review-overview.svg`。所有注释位于边框内，电源/RF/安全/普通信号采用不同线宽和线型。

## 交付索引

当前权威文件：

- `CURRENT_SYSTEM_STATUS.json`：当前事实、授权、哈希和开放门；
- `SYSTEM_ENGINEERING_HANDOFF.md`：当前接口、制造交接和经验教训；
- `system-design-contract.json` / `system-design-qa-report.*`：当前跨域合同与自动 QA。
- `current-system-traceability.json`：Rev B `SYS-001..012` 到当前合同、门禁与证据的源忠实机器映射；
- `current-delivery-manifest.json`：当前状态、合同、QA、交接与四项工具证据的哈希闭包。

历史 Rev A 文件（只用于追溯，内容不得解释为当前结论）：

- `integration-status.json`、`system-blockers.json`、`delivery-manifest.json`：旧状态、阻塞和旧哈希闭包；
- `system-interface-control.json` / `.md`、`system-traceability.json`：旧 27 mm 机械/未冻结 PCB 接口基线；
- `evt-dvt-pvt-plan.json` / `.md`、`system-review-overview.svg`：旧阶段门和旧总览；
- `combined-bom.*`、`system-fmea.json`、`rough-cost-estimate.*`：仍可作历史分析输入，但供应链价格和状态需重新验证。

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

The legacy paragraph here described the pre-native baseline. Current wand PCB ERC/DRC and fabrication outputs are verified, the printable enclosure is a verified prototype candidate, and the portable gesture core passes host tests. Physical, receiver, target-firmware, security and production gates remain open.

## 当前复核

在仓库根目录执行当前外壳生成器与系统合同 QA。旧的 `integration/build_package.py`
及其测试只复现 Rev A，且会重新生成过期结论，不应用于当前放行。

```powershell
python projects/magic-wand/mechanical/printable-wand/build_printable_wand.py
python plugins/aicad-agent/tests/test_system_engineering_contract.py -v
```
