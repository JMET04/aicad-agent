# 架构与信任边界

处理链路：

```text
用户需求
  → 任意 Agent
  → aicad-agent MCP 工具或 JSON CLI
  → Agent 编写的 Schema 2.0 计划、离线确定性模板，或显式启用的可选结构化 provider
  → 本地重建数学约束
  → Python 约束编译与几何复算
  → ASCII AICAD v2 协议
  → AutoLISP 二次校验
  → entmakex 逐实体创建 + XData 审计标识
```

`aicad-agent` 是主要复用边界。它把能力发现、Schema 获取、生成、验证和编译暴露为稳定工具；AutoCAD bundle 只是可选执行器。默认路径是 Agent-first：调用方 Agent 读取 Schema 后自行编写计划，再调用本地验证和编译工具。MCP 不可用时，同一入口脚本提供等价 CLI，因此调用方不需要依赖 Codex 专有运行时。

模型位于不可信边界之外。即使模型返回合法 JSON，它仍不能指定命令、文件操作或 AutoLISP；本地转换器只读取数值化的直线、圆和圆弧字段，再自行生成长度、方向、圆心偏移、半径和角度约束。任何不完整、非有限、零长度、重复或未锚定的几何都会在 AutoCAD 之前失败。

OpenAI API 不是默认要求。普通 Codex/Agent 使用中，Agent 已经在会话内完成推理，插件只接收 Agent 编写的 `schema_version 2.0` 计划并在本地复算约束；因此不需要 `OPENAI_API_KEY`。本地 CLI 与 MCP 的默认 provider 都是 `offline`，不会主动读取 API Key 或访问网络。Responses API 仅作为独立自然语言 CLI 的显式可选 provider；只有显式选择 `provider=openai` 或 `provider=auto` 后才读取 `OPENAI_API_KEY` / Windows Credential Manager 的 `AiCadConstraint/OpenAI` 项。非本机 provider 地址必须使用 HTTPS。

AutoCAD 端不依赖 Python 对计划“已经验证”的声明。它重新解析协议、检查原点/锚点证明、数量和哈希标记，随后才批量 `entmakex`。每个实体写入 `AICAD` XData：实体 ID、类型和步骤序号。中途创建失败时插件删除本批已建实体。

ASCII 执行协议与 UTF-8 审计数据分开，是乱码治理的核心：中文不参与 CAD 指令解释，AutoLISP 源本身也保持 ASCII。
