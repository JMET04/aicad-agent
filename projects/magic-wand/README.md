# 魔法杖跨域工程原型包（Rev B）

> **CURRENT 2026-08-22:** Owner-authorized prototype bare-PCB ordering and prototype 3D printing are allowed. Production release, PCBA ordering, target-firmware claims and safety-critical use remain locked; see `integration/CURRENT_SYSTEM_STATUS.json`.

当前入口：

- [Current system status](integration/CURRENT_SYSTEM_STATUS.json) — 当前机器可读单一事实源；
- [System engineering handoff](integration/SYSTEM_ENGINEERING_HANDOFF.md) — 接口、开放门和插件升级经验；
- [嘉立创裸板包](electronics/manufacturing/jlcpcb-wand-rev-a0/) — 4 层、ERC/DRC 0 的裸板上传候选；
- [可打印外壳包](mechanical/printable-wand/) — 含电池位、触觉位、STEP/STL、3D 预览和网格门禁；
- [八类手势主机证据](firmware/gesture-host-evidence.json) — 主机管线证据，不代替目标固件/HIL；
- [系统合同与 QA](integration/system-design-contract.json) — 跨域接口、证据和放行锁；
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

Current authorization is limited to prototype wand bare-PCB fabrication and prototype 3D printing. PCBA, target-firmware, production and safety-critical release locks remain closed until the current handoff gates are completed.
