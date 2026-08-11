# aicad-agent 1.8.4

## 1:1 webpage and image reference reconstruction

Version 1.8.4 can rebuild calibrated webpage SVG, SVG, raster, and PDF references as editable 1:1 CAD model geometry. Vector sources are hash-pinned and read from their actual DOM object IDs; raster pixels never become dimension truth. Geometry, dimensions, exact text, annotation position/rotation, lineweight hierarchy, aspect ratio, mojibake, and overlap are separate hard gates. A bounded `optimized_offset` is allowed only when real font metrics create a measured collision. See [the reference reconstruction guide](docs/WEB_REFERENCE_REBUILD.md).

Portable output includes annotated DXF, native-text SVG/HTML, validation, manifest, and browser-backed PNG evidence. Native AutoCAD DIMENSION objects and DWG save/reopen remain an explicit host post-process gate.
## 建筑平面制图语义

建筑图不再使用统一线条。插件按对象语义区分剖切柱/墙粗实线、门窗与可见投影中实线、家具/柜体/洁具/家电和标注细实线、交通/上方构件虚线以及轴网中心线；原生 DIMENSION 使用持久命名 DIMSTYLE。编译前必须通过 `aicad_architectural_detail_contract_v1`，证明完整轴线+双轴圈+双轴号、总/轴网/分隔/洞口四类尺寸链、逐房间设备矩阵和门-墙-洞口-开启弧拓扑；失败仅输出阻断报告。最终 DXF 再由 `scripts/aicad_architecture_qa.py` 检查，二维修改器也会继承每个对象的 `cad_layer`。详见 [建筑制图不变量](docs/ARCHITECTURAL_DRAFTING.md)。验证报告也必须通过稳定规则 ID、完整根因记录和重复运行幂等门禁；可使用 scripts/aicad_report_qa.py 独立复核。

## 生产就绪门禁

插件不再把“几何能打开”误当成“可以施工/生产”。生产请求必须提交 `production_readiness_contract`，分别证明整体要求、逐实体几何、轴网轴号、线型线宽、原生尺寸、家具类型线稿、图纸空间/图签/版本、专业依据、真实宿主重开和授权放行。任何一关失败，`strictProductionOnly=true` 时只输出中文阻断报告，不暴露带“生产”标签的工件；机器通过也保持 `accepted=false`，不能替代签章或制造放行。

## 自动打开审查界面

交互式 `generate`、`compile`、`build3d` 和 `multiview` 在产物验证完成后，会生成绑定当前源哈希的审查 HTML，并在桌面宿主中自动打开。CI、无桌面环境或 `AICAD_NO_GUI=1` 会明确记录 `skipped`，但不会丢失审查文件。使用 `review_launch=auto|always|never` 控制行为；打开界面不等于接受设计。

## Exact 3D subobject correction and native topology

The multiview selector addresses individual lines, circles, and faces with stable semantic keys. Corrections are bound to a source hash, explicit preservation policy, shared-pattern fanout, and full downstream dependency replay. Thin visible strokes are separate from the larger click target, so precision and usability do not conflict.

On a licensed SolidWorks 2026 host, version 1.8.4 maps required sketch primitives and uniquely classified BREP edges/faces to native `GetPersistReference3` bytes. The catalog is embedded in the SLDPRT, saved, reopened, and resolved record by record. Only that live gate may report `native_topology_authority=true`; offline review remains explicitly semantic. See [native SolidWorks topology readback](docs/NATIVE_SOLIDWORKS_TOPOLOGY.md) and [exact subobject correction](docs/EXACT_SUBOBJECT_CORRECTION.md).

确定性、原点锚定、面向 Agent 的 CAD 约束插件。它把 2D AICAD 计划编译为 AICAD/SCR/DXF/审计工件，提供包装刀版正常性证明与交互修改器，并通过可选 Windows 宿主支持 AutoCAD 和 SolidWorks。

![包装刀版交互审查界面](docs/images/packaging-review.png)

## Selected geometry measurements and MODEL_XYZ

Clicking a line now shows its compiled-model length and XYZ endpoints; clicking a point shows XYZ; clicking a circle shows radius, diameter and XYZ center. Editable values can prefill the exact controller in the right panel. A right-handed `MODEL_XYZ` triad is visible in every review view, and one top-bar switch hides or restores SVG axes, model origins and the rotating 3D triad together. See [the selection measurement contract](docs/SELECTION_MEASUREMENT_UI_V3.md).

## Single-flow CAD modifier and free sections

The reviewer now exposes one modification list instead of separate user-facing intent and transaction stages. Every compiled 3D feature publishes clickable core parameters; geometric centers, center axes, pitch circles and interface edges remain hidden until hover or selection. The free-section workbench accepts axis planes and arbitrary `normal + point` planes, renders feature-operation intersections, and maps a clicked section curve back to an exact semantic parameter controller. See [CAD modifier interaction contract](docs/MODIFIER_UI_V2.md).

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
python scripts/aicad_production_readiness_qa.py production-contract.json --output production-validation.json --markdown production-validation.md
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
