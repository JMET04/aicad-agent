# 魔法杖跨域工程原型包（Rev B）

> **CURRENT 2026-08-23:** Wand 配置与既有裸板候选保持冻结；独立 receiver-effects 的八槽/八效果 host 逻辑已验证，A1 裸板候选已通过原生 ERC/DRC 并哈希绑定（旧 receiver CAM 仍为 **REJECTED**）。授权仅覆盖原型裸板与原型 3D 打印；PCBA、目标固件、HIL 和量产仍锁定，见 `integration/CURRENT_SYSTEM_STATUS.json`。

当前入口：

- [Current system status](integration/CURRENT_SYSTEM_STATUS.json) — 当前机器可读单一事实源；
- [System engineering handoff](integration/SYSTEM_ENGINEERING_HANDOFF.md) — 接口、开放门和插件升级经验；
- [冻结 Wand 嘉立创裸板包](electronics/manufacturing/jlcpcb-wand-rev-a0/) — 4 层、ERC/DRC 0 的 Wand 裸板上传候选；
- [可打印外壳包](mechanical/printable-wand/) — 含电池位、触觉位、STEP/STL、3D 预览和网格门禁；
- [receiver-effects 系统交接](integration/RECEIVER_EFFECTS_SYSTEM_HANDOFF.md) — 直接 BLE 端点、八槽/八效果、屏幕/音效和开放硬件门；
- [receiver-effects KiCad 工作源](electronics/receiver-effects/) — A1 60 × 50 mm、4 层；ERC/DRC 0/0/0，裸板上传候选已哈希绑定；
- [八类手势主机证据](firmware/gesture-host-evidence.json) — Wand 分类管线证据，不代替目标固件/HIL；
- [接收器运行时主机证据](firmware/host-review-evidence.json) — 34/34 build、10/10 CTest、cppcheck 9/9、52/52 哈希；目标/HIL 仍开放；
- [系统合同与 QA](integration/system-design-contract.json) — 跨域接口、证据和放行锁；
- [当前 SYS-001..012 追踪](integration/current-system-traceability.json) — Rev B 需求到当前合同、门禁和证据的机器映射；
- [当前交付哈希清单](integration/current-delivery-manifest.json) — 当前状态、合同、双交接和五项工具证据的精确闭包；
- [历史机械/电子/整合包](integration/README.md) — Rev A 追溯材料，不再是当前状态源；
- [整机审查 SVG](integration/system-review-overview.svg)；
- [成本粗算](integration/rough-cost-estimate.md)；
- [合并 BOM](integration/combined-bom.csv)。

在仓库根目录复核当前机械与系统门禁：

```powershell
python projects\magic-wand\mechanical\printable-wand\build_printable_wand.py
python plugins\aicad-agent\tests\test_system_engineering_contract.py -v
```

旧的 `integration/build_package.py` 只复现 Rev A 历史快照，不能生成当前状态。

Current authorization is limited to prototype bare-PCB fabrication and prototype 3D printing. The frozen Wand package is already a verified upload candidate; receiver-effects A1 is now also a verified bare-PCB upload candidate (ERC/DRC 0/0/0, hash-bound JLC archive; NINA In1 GND coverage 96% vs the 98% production target remains the only open manufacturing item). PCBA, target-firmware, HIL, production and safety-critical release locks remain closed.
