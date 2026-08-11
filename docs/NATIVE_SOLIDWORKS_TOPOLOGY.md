# SolidWorks 原生拓扑持久引用

插件现在把语义子对象键（例如 `F001|profile.edge.1`）绑定到真实 SolidWorks 草图线、圆、实体边和实体面。宿主先用 `GetPersistReference3` 获取原生引用，再把目录写入 SLDPRT 自定义属性；保存后重新打开文件，并逐项调用 `GetObjectByPersistReference3` 复核。

只有真实宿主执行、保存、重开、引用键集合完全一致且必需引用零丢失时，结果才允许声明 `native_topology_authority=true`。离线计划和二维投影视图仍明确标记为非原生拓扑权威。

必需引用是可编辑设计意图：矩形的四条有序草图边以及每一个有序草图圆。结果实体中的边和面只有在数学分类唯一时才进入目录；例如通孔不存在圆盘终止面，插件不会伪造一个面来凑齐目录。

本次实测暴露并固化了两条预防规则：

- SolidWorks 可能为原对象与持久引用回读返回同一个 COM 包装器；过早执行 `FinalReleaseComObject` 会让仍在使用的面/边失效，因此捕获期间禁止提前最终释放。
- `AICAD_REF_COUNT` 与真正记录共享前缀；读取器必须只接受 `AICAD_REF_` 加四位数字，不能只做宽泛前缀匹配。

这些规则已写入 `rules/native_solidworks_topology_rules.json` 并由插件测试与真实保存重开验证共同约束。
