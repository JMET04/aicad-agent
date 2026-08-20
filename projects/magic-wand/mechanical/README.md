# 魔法棒机械样机包（Rev A）

这是一个**真实可审查、仅限原理样机**的机械包。四个制造件已经由 AICAD 约束计划生成，并在 SolidWorks 2026 中完成逐特征事务、SLDPRT/STEP 保存、重开和持久拓扑引用解析；五张 2D 图已经编译为 DXF/AICAD/SCR。它不是结构计算、射频认证、材料认证、装配干涉分析或工厂生产放行。

## 单一参数源

所有受控数值只以 `design-parameters.json` 为准。计划、BOM、装配布局、SVG 视图和生成清单均由 `build_package.py` 确定性派生。Markdown 中出现的数值只是方便审查的摘要，不构成第二参数源。

当前尺寸链：

- 后端盖外露 5 mm；
- 握柄壳 110 mm；
- 接头外露 10 mm；
- GFRP 杆外露 190 mm；
- 总长 `5 + 110 + 10 + 190 = 315 mm`；
- 握持段 `5 + 110 = 115 mm`，目标外径 27 mm；
- GFRP 脊柱名义直径 7 mm，采购长度 220 mm，插入 30 mm。

## 已生成并通过的内容

- `preflight/engineering-preflight.json`：机械域 54 项受控生成预检；
- `plans3d/`：握柄壳、内载架、后端盖、杆连接件四个特征计划；
- `drawings2d/`：四张零件图计划和一张总布置图计划；
- `artifacts/3d/`：每件的 SLDPRT、STEP、宿主报告、重开报告、审计、清单和可选择审查 HTML；8 个 SLDPRT/STEP 文件作为 review-only / quote-only 证据随公开仓库精确发布，不构成制造放行；
- `artifacts/2d/`：每图的 DXF、AICAD、SCR、审计和清单；
- `review/wand-mechanical-isometric.svg`：参数绑定的总成示意 3D 视图，不是 BREP 装配；
- `assembly-layout.json`、`bom.json`：装配基准与原理样机 BOM；
- `generated-source-manifest.json`：参数源和派生源文件的大小/SHA-256 闭包。

## 不能误读的边界

- 当前 3D 内核只支持轴向拉伸/切除；握柄侧面的 press-to-arm 孔没有进入 BREP，只有明确的 Z=72 mm 基准和 2D 要求。
- 当前没有 SLDASM、装配 mates、全装配干涉/间隙求解或质量重心结论。
- SLDPRT 的原生拓扑权威只覆盖已实际建模的轴向特征；它不覆盖缺失的侧孔、圆角、卡扣、胶槽或复杂曲面。
- 四份 `*.3d.manifest.json` 使用仓库相对 POSIX 路径，适用于公开克隆；`*.swplan.json`、`*.solidworks-report.json` 和 `*.reopen-report.json` 中的 Windows 绝对路径仅是 2026-08-21 原始宿主执行 provenance，在其他克隆位置会失效，不可当作可移植定位符；应以同目录文件名和 SHA-256 为准。
- 未选择最终树脂、GFRP 牌号、胶粘剂、阻燃等级、打印方向和工艺能力；没有材料数据库赋值、强度/刚度/跌落/疲劳结论。
- NINA-B302 天线禁布区是机械保守包络；最终尺寸与地/壳/线缆/手握影响必须依据当前厂商集成资料并做实物射频测试。
- 所有授权锁保持关闭：`reviewOnly=true`、`accepted=false`、`manufacturingAuthorized=false`、`fabricationAuthorized=false`、`productionReleaseEligible=false`。

## 复现

在仓库根目录执行：

```powershell
python projects\magic-wand\mechanical\build_package.py --check
python tests\test_magic_wand_mechanical_package.py
```

完整构建/审查顺序见 `ASSEMBLY_DFM_TEST.md`。尺寸、公差、接口和安全需求见 `REQUIREMENTS_INTERFACES_TOLERANCES.md`。
