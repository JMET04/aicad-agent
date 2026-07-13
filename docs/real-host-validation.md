# AutoCAD 2025 真实宿主验收

验收日期：2026-07-11。宿主为简体中文 AutoCAD 2025，`acad.exe` 与 `accoreconsole.exe` 文件版本 `25.0.58.0`，DWG 签名 `AC1032`。

自动验收由三个相互独立的 AutoCAD Core Console 进程完成：

1. 加载 1.0.0 插件并绘制 1 版矩形计划，核对 4 条线的坐标、ID、步骤号和 XData，保存 DWG；
2. 重新打开该 DWG，复核坐标和 XData 持久化；
3. 执行 2 版计划和自然语言桥接，核对半径 25、0–90° 的圆弧，离线生成并绘制 `120×80 + 中心直径20孔`，复核 4 条线、圆心 `(60,40)`、半径 `10`，并确认伪造锚点证明会被拒绝。

Agent 通用插件增加了端到端宿主门禁：先通过 `aicad-agent` 工具生成中心孔板件，再把其 `.aicad` 产物送入真实 AutoCAD。GUI AutoCAD 2025 验收结果为 `AICAD_AGENT_PASS`，确认 4 条边、1 个圆、圆心 `(60,40)` 和半径 `10` 全部一致。

运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-autocad.ps1
```

验收报告位于 `build/autocad-host-test/`：`integration-report.txt`、`persistence-report.txt`、`v2-report.txt` 和 `host-validation.json`。

此前 GUI 验收还确认 bundle 可在启动时自动加载，`AICAD_DRAW` 文件选择、`AICAD_INFO` 元数据读取和一次撤销整批实体均正常。1.0 保留 AutoLISP 命令自动撤销组，且不在绘制命令内执行自动缩放，以维持一次 `UNDO` 语义。
