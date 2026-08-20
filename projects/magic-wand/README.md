# 魔法棒跨域工程审查包（Rev A）

> **REVIEW ONLY / PRE-EVT：18 个阻塞项仍开放。禁止直接 PCB 投板、工厂生产、量产放行、安全关键控制或宣称目标固件/KiCad/ERC/DRC/HIL/RF/结构/法规已通过。**

入口：

- [机械包](mechanical/README.md) — 约束 CAD、2D 图、review-only SLDPRT/STEP 与机械阻塞项；
- [电子包](electronics/README.md) — 连接表、BOM、计算与 KiCad 录入/验证计划；
- [固件包](firmware/README.md) — 可移植 C11 契约骨架和主机侧验证；
- [系统整合包](integration/README.md) — 需求追溯、接口、FMEA、EVT→DVT→PVT 阶段门与交付清单；
- [整机审查 SVG](integration/system-review-overview.svg)；
- [成本粗算](integration/rough-cost-estimate.md)；
- [合并 BOM](integration/combined-bom.csv)。

在仓库根目录复核确定性输出与专项契约：

```powershell
python projects\magic-wand\mechanical\build_package.py --check
python projects\magic-wand\integration\build_package.py --check
python tests\test_magic_wand_mechanical_package.py
python tests\test_magic_wand_electronics_package.py
python tests\test_magic_wand_integration_package.py
```

所有制造、投板和生产授权锁均保持关闭；只有在原生工具、实物测试、独立工程审查和适用法规门全部闭环后，才可另行考虑放行。
