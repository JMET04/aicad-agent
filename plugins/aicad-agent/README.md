# aicad-agent 1.17.0

## 跨领域规范第一门禁

任何建筑、结构、土木、机械、钣金、包装、电子、电气、给排水、暖通、工艺管道或产品设计任务，都必须先声明领域、交付阶段、适用标准、启用规则包和输入权威顺序。`normative_governance` 与对应领域规则包是阶段 0 非补偿门禁；标准和批准工程输入优先于用户偏好、参考 CAD、图片与推测。缺少适用标准、版本/范围或对应规则包时，只能输出缺项诊断，不能先画几何再用分数补偿。

高优先级规范只有同时具备 schema/contract 字段、生成时约束、独立 QA 和能稳定复现旧错误的负向回归测试，才算真正落地。该原则适用于所有领域，不是建筑专用补丁。

## 1:1 webpage and image reference reconstruction

Version 1.15.0 can rebuild calibrated webpage SVG, SVG, raster, and PDF references as editable 1:1 CAD model geometry. Vector sources are hash-pinned and read from their actual DOM object IDs; raster pixels never become dimension truth. Geometry, dimensions, exact text, annotation position/rotation, lineweight hierarchy, aspect ratio, mojibake, and overlap are separate hard gates. A bounded `optimized_offset` is allowed only when real font metrics create a measured collision. See [the reference reconstruction guide](docs/WEB_REFERENCE_REBUILD.md).

Portable reference-rebuild output includes annotated DXF, native-text SVG/HTML, validation, manifest, and browser-backed PNG evidence. The main AICAD protocol-4 path emits true native DIMENSION entities with purpose/style XData; DWG save/reopen remains an explicit licensed AutoCAD host gate.
## 建筑平面制图语义

建筑图不再使用统一线条。插件按对象语义区分剖切柱/墙粗实线、门窗与可见投影中实线、家具/柜体/洁具/家电和标注细实线、交通/上方构件虚线以及轴网中心线；轴线坐标必须由此前已建立的柱中心、核心筒/承重墙中心或权威轴网输入推导，并记录 `supportEntityIds`、依赖和偏移；无支撑的固定模数或“看着整齐”的等距轴网直接失败，等距只能是结构推导后的结果。原生 DIMENSION 使用持久命名 DIMSTYLE。建筑编译前必须通过 strict-production-only 的 `aicad_architectural_detail_contract_v2`，证明轴线坐标/覆盖范围+两端相切轴圈+居中同值轴号的数学绑定、完整生产图纸集、总/轴网/分隔/洞口四类尺寸链、带来源引用的逐房间用途与设备矩阵、门-墙-洞口-开启弧拓扑，以及沙发靠背/扶手/坐垫分缝、床枕、洁具芯体/排水、家电控制等逐实体线稿角色。房间用途不得由已有家具反推；文字占用框必须避让真实轴线全长、柱、轴圈、家具、设备、尺寸、门扇和开启弧；无可行位置时阻断，禁止碰撞回退。车辆、家具、柜体、洁具和家电默认全部参加门扇/通道净空。任何失败只输出 JSON、单文件 UTF-8 HTML 和白底 PNG 阻断报告，零 CAD 工件。最终 DXF 再由 `scripts/aicad_architecture_qa.py` 检查，二维修改器也会继承每个对象的 `cad_layer`。详见 [建筑制图不变量](docs/ARCHITECTURAL_DRAFTING.md)。

## 生产就绪门禁

插件不再把“几何能打开”误当成“可以施工/生产”。生产请求必须提交 `production_readiness_contract`，分别证明整体要求、逐实体几何、轴网轴号、线型线宽、原生尺寸、家具类型线稿、图纸空间/图签/版本、专业依据、真实宿主重开和授权放行。任何一关失败，`strictProductionOnly=true` 时只输出中文阻断报告，不暴露带“生产”标签的工件；机器通过也保持 `accepted=false`，不能替代签章或制造放行。

## 自动打开审查界面

`generate`、`compile`、`build3d` 和 `multiview` 会生成绑定当前源哈希的审查 HTML 和打开记录；CLI/Agent 默认 `review_launch=never`，不会反复新建浏览器标签。显式使用 `auto` 时，HTML 会先复制到持久内容寻址目录并在 300 秒窗口内对相同内容去重；只有 `always` 才强制再次打开。临时源文件删除后，已打开页面仍有效；打开界面不等于接受设计。

普通“打开/看看/预览”请求必须调用 `aicad_open_review_request`，并且只打开通过 `aicad_selectable_vector_modifier_v1` 的当前交互修改器：真实 `cad-view` SVG、独立宽 `view-hit`、源对象/子对象 ID、图层、语义目录、模型测量和受控纠错缺一不可；单有 `data-artifact-role` 标签的 PDF/图片浏览器必须失败关闭。栅格内容只能作为已声明的次要底图。即使参数中有 PDF、DWG、STEP 或 KiCad 路径，也不得直接打开。只有用户明确要求原生 CAD 编辑或输出时才设置 `open_native_cad=true`，而且修改器必须先成功打开，否则原生 CAD 被阻断。

## Exact 3D subobject correction and native topology

The multiview selector addresses individual lines, circles, and faces with stable semantic keys. Corrections are bound to a source hash, explicit preservation policy, shared-pattern fanout, and full downstream dependency replay. Thin visible strokes are separate from the larger click target, so precision and usability do not conflict.

On a licensed SolidWorks 2026 host, version 1.15.0 maps required sketch primitives and uniquely classified BREP edges/faces to native `GetPersistReference3` bytes. The catalog is embedded in the SLDPRT, saved, reopened, and resolved record by record. Only that live gate may report `native_topology_authority=true`; offline review remains explicitly semantic. See [native SolidWorks topology readback](docs/NATIVE_SOLIDWORKS_TOPOLOGY.md) and [exact subobject correction](docs/EXACT_SUBOBJECT_CORRECTION.md).

确定性、原点锚定、面向 Agent 的 CAD 约束插件。它把 2D AICAD 计划编译为 AICAD/SCR/DXF/审计工件，提供包装刀版正常性证明与交互修改器，并通过可选 Windows 宿主支持 AutoCAD 和 SolidWorks。

![包装刀版交互审查界面](docs/images/packaging-review.png)

## Selected geometry measurements and MODEL_XYZ

Clicking a line now shows its compiled-model length and XYZ endpoints; clicking a point shows XYZ; clicking a circle shows radius, diameter and XYZ center. Editable values can prefill the exact controller in the right panel. A right-handed `MODEL_XYZ` triad is visible in every review view, and one top-bar switch hides or restores SVG axes, model origins and the rotating 3D triad together. See [the selection measurement contract](docs/SELECTION_MEASUREMENT_UI_V3.md).

## Single-flow CAD modifier and free sections

The reviewer now exposes one modification list instead of separate user-facing intent and transaction stages. “Copy and submit to AI” emits clipboard, browser-event, parent-frame and WebView handoff channels. The agent validates the schema and current source hash, previews the exact transaction, applies it, writes audit/receipt artifacts and regenerates the corrected selectable modifier; stale, notes-only and invalid requests fail before output writes. Every compiled 3D feature publishes clickable core parameters; geometric centers, center axes, pitch circles and interface edges remain hidden until hover or selection. The free-section workbench accepts axis planes and arbitrary `normal + point` planes, renders feature-operation intersections, and maps a clicked section curve back to an exact semantic parameter controller. See [CAD modifier interaction contract](docs/MODIFIER_UI_V2.md).

## 不可跳过的四级门禁

0. **跨领域规范治理**：冻结领域、交付阶段、适用标准、启用规则包和输入权威顺序；缺项或冲突不可被其他评分补偿。
1. **整体要求一致性**：冻结需求契约，校验产品类型、结构族、标准、上下闭合、尺寸、主要功能、输入权威和安全锁。每条硬要求必须满足 `boundActual = observed = expected`。
2. **细节数学可靠性**：验证逐实体约束、独立雅可比秩、端点归属、单闭合轮廓、功能面、结构公式和耦合参数域。
3. **隔离候选构建**：前三关通过后才编译；验证必需文件、ASCII 执行通道、manifest 身份和 SHA-256 后才暴露候选目录。

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
python scripts/aicad_engineering_preflight.py --template mechanical --output mechanical-preflight.json
python scripts/aicad_engineering_preflight.py --contract mechanical-preflight.json --output mechanical-preflight.report.json --markdown mechanical-preflight.report.md
python scripts/aicad_production_readiness_qa_v3.py production-contract-v3.json --output production-validation-v3.json --markdown production-validation-v3.md
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

## Mechanical/electronics normative generation preflight

Mechanical and electronics plans derive one exact pre-geometry checklist from `rules/production_readiness_rules.json`: 54 mechanical gates and 63 electronics gates. The checklist covers shared authority/detail/drafting/sheet controls plus the selected profile's intent, design and manufacturing-definition rules. Missing, extra, duplicate, unresolved or non-authoritative rows block both 2D and 3D generation before artifacts are written.

Call `aicad_get_engineering_preflight_template`, resolve and source-bind every row, validate with `aicad_validate_engineering_preflight`, and embed the pass as `engineering_normative_preflight`. See [the preflight guide](docs/ENGINEERING_NORMATIVE_PREFLIGHT.md). A pass permits controlled generation only and grants no technical/manufacturing/fabrication/release status.

## Mechanical and PCB evidence-contract gates

The canonical v3 contract is fail-closed and non-compensatory, but its conclusion is intentionally limited to `evidenceContractReady`. It verifies the declared file hashes, rule-owned values, required-standard subset, exact `expectedArtifactClosure`/candidate bijection, complete artifact-ID source maps and one artifact-set binding. Repeated artifact kinds are supported through unique artifact IDs, part/subject identity, revision and case-insensitive path identity. It does not authenticate evidence origin, replay native CAD/EDA execution, independently reproduce an engineering analysis, expose candidate artifacts, or grant technical/manufacturing/fabrication readiness.

Mechanical evidence covers the frozen operating envelope, duty cycle and design life; recomputed load combinations and abnormal cases; equation/input/output/margin trace; strength, stiffness, fatigue, fastener/joint/bearing and thermal margins; risk controls; fits, threads, undefined edges, GD&T, roughness, process capability and measurement method; native material-database assignment; BOM/revision/inspection parity; and feature-bound drawing annotations. Every manufactured part and required assembly has separate native CAD, STEP, drawing, source binding and reopen evidence. Canonical QA parses one `aicad_machine_mechanical_bom_v1` JSON BOM with one positive-quantity row per subject and exact subject type, revision and artifact IDs, then checks that the hash-bound product-structure manifest repeats those subject-scoped BOM rows. PCB evidence covers exact MPN-to-symbol pin number/function/type resolution; ratings/derating, power/startup/fault, transient, analog, clock/reset/programming, grounding/isolation, connector and test access; bidirectional net/pad and BOM/footprint parity; enclosure/height checks; zero final unconnected or ignored/excluded ERC/DRC items; and granular Gerber/drill/CAM outputs bound to the same revision. Every `pcb_design` independently owns its KiCad project/schematic/board, schematic PDF, BOM, CPL, assembly drawing, fabrication drawing, 3D board, job file, CAM manifest and all Gerber/PTH/NPTH drill outputs. Canonical QA parses each final `.kicad_pcb` S-expression for the copper-layer set and PTH/NPTH presence; the candidate board inventory must match that parse, and each CAM manifest must close every named Gerber layer, typed drill output and job artifact ID/hash. This is candidate-declared consistency, not external source authority or evidence authenticity.

Every artifact-set digest includes artifact ID, part ID, subject type, kind, revision, normalized relative path, byte size and content SHA-256. Artifact IDs and case-folded paths are unique while kinds may repeat. Reports persist portable paths only. `independentEvidenceAuthenticityVerified`, `nativeExecutionReplayedByThisQA`, `technicalPackageReady`, `productionReleaseEligible`, `manufacturingAuthorized`, `fabricationAuthorized` and every candidate-artifact exposure field remain `false`. Recorded approval metadata is hash-bound evidence only, never an independently verified trust chain.

## Controlled failure-to-lesson loop

Every structured failed test/gate can be harvested into a deterministic lesson bundle. The bundle stores no implicit time or machine absolute path: each failed check has one stable alias/event, a failing-check name, symptom/root cause/correction, a disabled candidate rule, a minimal negative regression, and safe-relative size/SHA-256 closures for its reproducer, evidence, source inputs and affected artifacts. The QA recomputes all files and requires exact bidirectional failure-to-lesson closure; missing, extra, mixed, stale, traversal or link-backed records fail.

```powershell
python scripts/aicad_lesson_harvester.py reports/failures.json --root . --output learning/candidates.json
python scripts/aicad_continuous_learning_qa.py learning/candidates.json --root . --output learning/audit.json
```

Candidates always retain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`. Both CLIs accept output only as explicit JSON below `learning/`; authority, tests, plugin metadata and package surfaces cannot be destinations. Optional promotion QA verifies recorded prerequisites only: red-before-fix, green-after-fix, unrelated-suite pass, two distinct reviewer IDs bound to the same bundle hash/rule/newer version, and a no-weakening/no-test-deletion policy. It does not authenticate reviewer identity and always leaves manual-promotion eligibility false pending external authenticated review. It never edits authoritative rules or tests, changes/installs/publishes the plugin, or unlocks technical/manufacturing/fabrication status.

The seeded inventory captures the mechanical, electronics and release failures found during production-level validation, including artifact/source closure, native CAD/EDA readback, datasheet-required electronics, surge/return/isolation models, per-IC decoupling, schematic readability, Stage-A acceptance, Stage-B fallback prevention, portable paths, atomic release publication and sanitized showcase closure.
