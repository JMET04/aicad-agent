# AICAD 执行协议 2

`.aicad` 是编译器与 AutoCAD 插件之间的 ASCII-only 执行通道。插件继续接受 1 版直线文件；2 版增加圆、圆弧和锚点证明。

```text
AICAD|2|MM|0.000001|<source-sha256>
LINE|L001|x1|y1|x2|y2|purposeHash|reasonHash|baseX|baseY|offsetX|offsetY
CIRCLE|C001|cx|cy|radius|purposeHash|reasonHash|baseX|baseY|offsetX|offsetY
ARC|A001|cx|cy|radius|startDeg|endDeg|purposeHash|reasonHash|baseX|baseY|offsetX|offsetY
END|3|<source-sha256>
```

锚点为直线起点或圆/圆弧圆心。插件要求 `anchor = base + offset`，且 `base` 必须是原点或已经建立的几何点。它还会检查有限数值、安全坐标范围、正半径、非零圆弧扫角、重复实体、首实体原点、实体总数和首尾哈希标记。

用途与推理正文不进入协议，只保留 16 位 SHA-256 摘要；完整 UTF-8 内容位于 `.plan.json` 和 `.audit.md`。因此中文不会进入 AutoCAD 命令解析器。

协议不是任意命令容器。记录类型白名单固定为 `LINE`、`CIRCLE`、`ARC`；未知记录会使整份文件在创建任何实体前被拒绝。
