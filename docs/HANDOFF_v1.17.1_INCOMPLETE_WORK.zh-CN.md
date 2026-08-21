# v1.17.1 制造图纸工作交接（审查候选快照）

> 冻结时间：2026-08-21（Asia/Shanghai）  
> 发布决策：用户要求停止继续完善，按当前状态公开发布并记录未完成工作。  
> 安全状态：**仅供审查，不可直接投产、开模、制板或施工。**

## 已完成并可复核

- 制造交付核心、CLI/API/MCP、JSON Schema、接收方门禁、2D/3D 预览合同和哈希闭包已实现。
- 电子器件 land-pattern 权威台账覆盖 92/92 个引用，blocker 为 0；权威测试 19/19 通过，指纹与来源 SHA 负向变异均 fail closed。
  - canonical source catalog SHA-256：`422b782a8de94db890d32e9bfe1fc750829dd97c35e69280f5f53ac8076be8ee`
  - final authority inventory SHA-256：`ac891b611e3a53455b58177a04154872061e9a0379788a903e0c16ad016e1369`
  - 双板 JAE J1 physical fingerprint：`f6c4212f72ebd58b06723bb33283afb04e5870ac6d5795de2a26f16e70e08ea3`
- receiver 纯摆放原生 KiCad DRC 已达到 0 个几何违规；尚有 119 个未连接焊盘，因路由未冻结。
- 机械工厂审查器当前可完整打开：11 张卡片、29 个预览；2D、3D、STEP 绑定、相对路径和 SHA 闭包均存在。
- 机械文字框审计通过：16 张图、594 条文字、overflow/truncated/undersize 均为 0，最小字高 1.8 mm；线宽层级为 70/50/35/25/18/13。
- 当前已打开的审查器：
  - `projects/magic-wand/mechanical/factory-rfq/outputs/reviewer/mechanical-factory-reviewer.html`
  - `showcase/architecture/review.html`
  - `showcase/steel/review.html`
  - `showcase/pcb/review.html`（通用 PCB 示例，并非本次 Magic Wand 最终板）

## 明确未完成

### Magic Wand 电子板

- wand 最新纯摆放报告仍有 42 个真实 DRC 违规和 133 个未连接焊盘。剩余违规来自器件真实摆放碰撞/板边间距，不应全局豁免。
- 两块板尚未完成最终布线冻结、原生 ERC/DRC 全零复验、保存后重开复验、CAM/Gerber/钻孔输出、最终 2D/3D 预览与 `factory-release-source-manifest.json`。
- 当前命名为 `*-native-erc.rpt` / `*-native-drc.rpt` 的文件中仍包含早期或中间态结果；在重新生成前不得作为制板放行证据。
- 本次 Magic Wand 独立 PCB 审查器尚未生成；当前打开的 `showcase/pcb/review.html` 只是通用能力示例。

### Magic Wand 机械/装配

- 机械图本身可审查，但两个机械 manifest 的总体状态仍为 `pending_electronics_final_native_drc`。
- 必须在电子接口和最终 source manifest 冻结后，重建受影响的 J1/U1/PCB 包络、开孔、载板和装配件，再重新导出原生 CAD、STEP、2D、3D、BOM 与哈希清单。
- 在上述增量重建完成前，机械包不得标为 `production_ready` 或用于开模。

### 统一工厂交付

- `projects/magic-wand/electronics/factory-release-source-manifest.json` 尚未生成。
- 统一 factory-release 的 source lock、validation、最终 reviewer 和发送门禁尚未冻结。
- 所有 production/fabrication/施工放行标志必须继续保持 `false`，直到供应商与相应专业工程师签字复核。

### 通用工科审查器

- 建筑审查器：线宽层级通过；文字虽有命中矩形，但不是可见标注框；没有实际 3D DOM/视图。
- 钢结构审查器：线宽层级和交互式 3D 通过；轴网与坐标文字仍直接绘制，未放入可见框。
- 包装、土木、建筑和钢结构能力应继续表述为统一入口下的生成/诊断/审查候选；不得在专业校核前宣称为可生产或可施工自动设计。

## 下次恢复的最短路径

1. 从当前 92/92 authority inventory 恢复，不重新抓取或改写已冻结的官方 land pattern。
2. 先消除 wand 的 42 个纯摆放违规；只允许对官方封装固有几何使用带来源 SHA、限定具体封装/焊盘对的窄规则。
3. 对 receiver 与 wand 重新布线，分别运行 KiCad 原生 ERC、DRC、保存后重开 DRC，全部达到 0 error / 0 violation / 0 unconnected。
4. 生成 CAM、Gerber、钻孔、BOM、CPL、2D/3D 预览和电子 source manifest，并校验哈希闭包。
5. 用冻结电子接口触发机械受影响件增量重建，复验 SolidWorks/STEP/2D/3D/文字框/哈希。
6. 运行 factory-release `--freeze-source-lock`，再执行正常构建、统一审查器验证和发送门禁。
7. 最后修复建筑可见文字框与 3D、钢结构轴网文字框；分别做截图级视觉回归。

## 发布与清理注意事项

- 不提交用户目录：`.playwright-cli/`、`learning/`、`output/`、`runs/`。
- 不提交过程临时件：`native/probe-*`、`library-emitter-smoke`、临时 datasheet 下载/渲染缓存、`__pycache__`、`*-placement-native-drc.rpt`、`*-reopen-candidate*`、`*.prl`、`*.lck`。
- 正式恢复时必须覆盖旧的原生 ERC/DRC 报告；不得用删报告、全局降低间距或 blanket exclusion 伪造通过。

