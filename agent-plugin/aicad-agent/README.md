# aicad-agent 1.3.3

确定性、原点锚定、面向 Agent 的 CAD 约束插件。它把 2D AICAD 计划编译为 AICAD/SCR/DXF/审计工件，提供包装刀版正常性证明与交互修改器，并通过可选 Windows 宿主支持 AutoCAD 和 SolidWorks。

![包装刀版交互审查界面](docs/images/packaging-review.png)

## 不可跳过的三级门禁

1. **整体要求一致性**：冻结需求契约，校验产品类型、结构族、标准、上下闭合、尺寸、主要功能、输入权威和安全锁。每条硬要求必须满足 `boundActual = observed = expected`。
2. **细节数学可靠性**：验证逐实体约束、独立雅可比秩、端点归属、单闭合轮廓、功能面、结构公式和耦合参数域。
3. **隔离候选构建**：前两关通过后才编译；验证必需文件、ASCII 执行通道、manifest 身份和 SHA-256 后才暴露候选目录。

任何前级失败都会将后级标记为 `blocked_by_previous_stage`，并且不生成候选 DXF/AICAD/SCR。

## 核心能力

- 默认 Agent-first 调用，不需要 API Key；
- `LINE`、`CIRCLE`、`ARC` 逐实体约束与禁止前向引用；
- 首实体从 `(0,0)` 锚定，必要时使用非生产 `ORIGIN_BOOTSTRAP`；
- AICAD/SCR 保持 ASCII，中文用途与推理进入 UTF-8 审计；
- PKG-G001..PKG-G025 包装刀版规则；
- 类型化上/下闭合与非镜像合同；
- 独立约束秩、面/拓扑/工艺区和参数域证明；
- 70 边、60 角、12 面等语义对象可交互审查；
- 两线选择后即时显示平行、垂直、共线、端点重合、等长、对称/联动；
- AutoCAD bundle、DXF/SCR、AICAD XData 工作流；
- 可选 SolidWorks 事务式 3D 构建、STEP 和重开验证；
- 错误现象、根因、修复与永久预防规则闭环。

完整说明见 [详细功能说明](docs/FUNCTIONS.zh-CN.md)，安装方法见 [安装和使用指南](docs/INSTALL.zh-CN.md)。

## 运行要求

- 核心：Python 3.10+；
- 包装 QA：安装 `requirements-packaging.txt`；
- AutoCAD：可选 AutoCAD 2025+，bundle 位于 `runtime/autocad`；
- SolidWorks：可选 Windows x64、.NET Framework 4.8、已授权 SolidWorks 2026。

默认发布包不分发 SolidWorks 专有互操作 DLL。

## 快速验证

```powershell
python scripts/aicad_agent.py capabilities
python scripts/aicad_agent.py compile --plan runtime/examples/rectangle.plan.json --out smoke --name rectangle
python scripts/aicad_agent.py build3d --plan runtime/examples/mounting_plate_3d.plan.json --out smoke3d --name plate --no-execute
python -B -m unittest discover -s tests -p "test_*.py" -v
```

## 安全边界

这是工程候选和人工审核材料，不代表量产或技术验收。安全锁保持：

```text
reviewOnly=true
accepted=false
ruleEnabled=false
packagingGated=true
```

MIT License。
