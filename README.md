# AI CAD Constraint Agent 1.2

这是一个 Agent 优先的 CAD 插件：2D 图元从 `(0,0)` 开始逐条约束绘制，3D SolidWorks 零件从 `(0,0,0)` 开始逐特征思考、构建和验证。

它不把 AI 输出直接当 CAD 指令执行。2D 指令通道只接受 ASCII 的 `LINE/CIRCLE/ARC`，中文用途与推理保存在 UTF-8 审计文件中；3D 由类型化 C# 宿主调用 SolidWorks API，不依赖鼠标坐标或界面文字，从根源上避免命令流乱码。

默认使用 Agent-first 调用：Codex/Agent 在会话里编写 AICAD 计划，插件只负责本地约束验证、编译、AutoCAD/SolidWorks 执行和审计，因此普通使用不需要配置 `OPENAI_API_KEY`。OpenAI/Responses API provider 仅作为独立自然语言 CLI 的可选后备。

## 版本口径

本仓库的发布版本是 Agent 插件/API `1.2.0`。内嵌组件保持各自兼容版本：Python 2D 编译器与 AutoCAD bundle 为 `1.0.0`，2D 计划 Schema 为 `2.0`，3D 计划 Schema 为 `1.0`。组件版本不等同于发布包版本，具体绑定以 `integration-manifest.json` 为准。
## 3D SolidWorks 工作流

每个特征都是一个失败即停的交易：

```text
用途/关系 → 数学约束 → 完全定义草图 → 特征 → 重建 → 体积/边界/实体/持久引用回读
```

当前支持：

- `base_extrude`、`boss_extrude`、`cut_extrude`；
- `center_rectangle`、`circle`、`circle_pattern`；
- SLDPRT、STEP、3D 审计、每特征验收报告和重开验收报告。

示例：`examples/mounting_plate_3d.plan.json` 会构建带 4 个通孔、中央凸台和中心通孔的安装板。

```powershell
python agent-plugin/aicad-agent/scripts/aicad_agent.py solidworks-doctor
python agent-plugin/aicad-agent/scripts/aicad_agent.py validate3d --plan examples/mounting_plate_3d.plan.json
python agent-plugin/aicad-agent/scripts/aicad_agent.py build3d --plan examples/mounting_plate_3d.plan.json --out build/solidworks-job
```

## Agent 工具

插件名为 `aicad-agent`，包含 9 个 MCP 工具：

- 2D：`aicad_get_plan_schema`、`aicad_generate`、`aicad_validate_plan`、`aicad_compile_plan`；
- 3D：`aicad_solidworks_doctor`、`aicad_get_3d_plan_schema`、`aicad_validate_3d_plan`、`aicad_build_solidworks_part`；
- 通用：`aicad_capabilities`。

它还提供两个独立技能：`aicad-draw` 用于 2D，`aicad-model-3d` 用于 SolidWorks 逐特征建模。

## 构建与安装

环境：Windows、Python 3.10+；2D 真实落图需 AutoCAD，3D 真实建模需 SolidWorks 2026 和 .NET Framework 4.8。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-solidworks-host.ps1
powershell -ExecutionPolicy Bypass -File scripts/build-agent-plugin.ps1
powershell -ExecutionPolicy Bypass -File scripts/install-agent-plugin.ps1
```

发布包：`release/aicad-agent-1.2.1.zip`。安装脚本会把插件注册到个人 Codex marketplace；安装或更新后新建任务以加载新的技能和 MCP 工具。1.2.0 新增包装刀版整体细节核验、错误根因记录和预防规则回归闭环；1.2.1 修复无 SolidWorks 环境下的 3D 纯编译降级。默认发布包不再分发 SolidWorks 专有互操作程序集；已安装 SolidWorks SDK 的机器可用构建脚本生成本地宿主。

## 验证

```powershell
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File scripts/test-autocad.ps1
```

SolidWorks 验收不仅查“文件是否存在”：它检查草图完全定义、特征错误码、实体故障、实体数、体积及增量、精确边界框、持久拓扑引用，并在 SLDPRT 保存后重新打开和强制重建再验一次。

详细依据见 [SolidWorks 3D 研究与决策](docs/solidworks-3d-research.md)，Agent 接口见 [插件说明](docs/agent-plugin.md)。

## 当前边界

3D 1.2.0 仍故意保持小而严格的特征集。圆角、倒角、旋转、扫掠、放样、壳、装配体和任意曲面暂不接受；编译器会明确拒绝，不会猜测或静默降级。
