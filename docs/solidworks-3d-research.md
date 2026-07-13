# SolidWorks 3D 逐特征约束建模研究与决策

## 结论

三维建模不应被当成“一次性生成最终形状”，而应被当成有向的特征交易链：

```text
先决条件 → 语义支撑 → 完全约束草图 → 特征操作 → 重建 → 回读断言 → 接受/回滚
```

SolidWorks 将草图区分为欠定义、完全定义和过定义，API 可通过 `ISketch::GetConstrainedStatus` 回读状态；因此“完全约束”可以成为机器可判定的提交门槛。[Sketch Status Conventions](https://help.solidworks.com/2026/english/SolidWorks/Sldworks/c_Sketch_Status_Conventions.htm) [GetConstrainedStatus](https://help.solidworks.com/2026/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.isketch~getconstrainedstatus.html)

SolidWorks 特征 API 提供拉伸/切除构建、重建后特征错误码以及关闭交互式错误对话框的能力；因此返回非空特征对象不足以证明成功，必须在强制重建后读取错误码。[FeatureExtrusion3](https://help.solidworks.com/2026/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~FeatureExtrusion3.html) [GetErrorCode2](https://help.solidworks.com/2025/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeature~GetErrorCode2.html) [ShowFeatureErrorDialog](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~ShowFeatureErrorDialog.html)

CAD 特征的拓扑名称会因后续重建而漂移，这是已有研究明确描述的 persistent naming 问题；因此插件禁止计划使用 `Face1`/`Edge3` 等序号名，优先使用主基准面和几何语义重选，并在必须依赖拓扑时使用 SolidWorks 持久引用在重建后重新解析。[Bidarra et al., Persistent Naming](https://graphics.tudelft.nl/~rafa/myPapers/jrnl-bidarra.CAD05.html) [GetObjectByPersistReference3](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~GetObjectByPersistReference3.html)

CAD 草图本质上是几何实体与约束构成的图，近年数据集和生成研究也普遍使用这种表示；这支持了本项目用 `depends_on` 和 `support_feature` 显式建模设计意图。[SketchGraphs](https://arxiv.org/abs/2007.08506) [CAD constraint review](https://arxiv.org/abs/2202.13795) [Design-intent constraints](https://arxiv.org/abs/2504.13178)

## 提交门槛

每个特征只有在以下条件同时成立时才能提交：

1. 草图状态为 `swFullyConstrained`。
2. 特征重建错误码为 0。
3. `IBody2::Check3` 返回的故障容器 `Count` 为 0；容器对象非空不代表有故障。[Check3](https://help.solidworks.com/2025/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IBody2~Check3.html)
4. 实体数、体积、体积增量和六方向极值边界框与数学预期一致。SolidWorks 质量属性 API 提供体积回读，实现使用实体极值点而不是文档警告为近似值的 `GetPartBox`。[IMassProperty2](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IMassProperty2.html)
5. 拓扑持久引用在重建后仍能解析。
6. SLDPRT 保存成功后从磁盘重开、强制重建，再次通过特征错误、实体健康、体积和边界框校验。SolidWorks `SaveAs3` 提供可回读的保存错误与警告。[SaveAs3](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SaveAs3.html)

## 实现边界

1.1.0 三维引擎有意只接受小而可证明的特征集：基体拉伸、凸台拉伸、拉伸切除；中心矩形、圆、圆周阵列。不支持的特征将被 Schema/编译器拒绝，而不会降级为鼠标点击或未验证的宏。

