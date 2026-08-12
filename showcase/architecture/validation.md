# 海边悬崖别墅三层诊断修改器核验

- 诊断修改器状态：**PASS**
- 生产放行：**否**（仍为 review-only）
- 楼层：`LF / MF / UF`
- 组合源哈希：`2348f84b9172e225229853f12ac6a1a91332cd1f96b3793104365284b851c929`

## 检查结果

| 检查 | 结果 |
|---|---|
| `requested_storey_set_bijection` | 通过 |
| `three_unique_source_plans` | 通过 |
| `modifier_source_freshness` | 通过 |
| `per_storey_source_view_packages_fresh` | 通过 |
| `design_basis_hash_bound` | 通过 |
| `concept_axis_authority_review_only_and_design_basis_bound` | 通过 |
| `axis_catalog_matches_design_basis` | 通过 |
| `unsupported_equal_module_absent` | 通过 |
| `all_axes_depend_on_earlier_supports` | 通过 |
| `contract_geometry_and_annotations_bound` | 通过 |
| `only_noncompensable_production_blockers_remain` | 通过 |
| `native_text_geometry_parity` | 通过 |
| `native_dimension_text_parity` | 通过 |
| `all_plan_text_visible_before_payload` | 通过 |
| `native_svg_text_present` | 通过 |
| `floor_switch_controls_present` | 通过 |
| `selection_references_document_scoped` | 通过 |
| `safety_locks_preserved` | 通过 |
| `review_html_utf8_and_structure` | 通过 |
| `formal_architectural_document_set_qa` | 通过 |
| `formal_document_set_digest_embedded_before_release` | 通过 |
| `browser_qa_v2_pass` | 通过 |

## 本轮根因与永久规则

### ARCH-D049

- 根因：楼层类别曾被集合化，三个 floor_plan 被错误视为一个图种即可满足。
- 新规则：要求楼层 ID 与计划、视图、修改器文档一一双射；重复或缺失任一层立即失败。

### ARCH-D050

- 根因：旧流程只复制主层 HTML，修改器没有文档集或楼层切换语义。
- 新规则：多层任务必须发布 document_set_switcher，切层清空选择并把纠错引用限定在当前 document/storey。

### ARCH-D051

- 根因：几何验证器未比较实际打开 HTML 的源计划哈希，且把 drawingModifierPreserved 写死。
- 新规则：发布与打开前逐层比对 plan、view package、design basis、生成器和 renderer 哈希；全部通过后原子发布。

### ARCH-D052

- 根因：TEXT 被降为点、DIMENSION 只画三条线，导致中文和尺寸值在修改器中消失。
- 新规则：浏览器视图的原生 TEXT/DIMENSION 数量必须与已解析计划完全对应，并在 payload 前的可见 DOM 中逐值核验。

### ARCH-D053

- 根因：标注虽存在，但模型空间固定偏移未形成语义标注带，缩放后出现低于8px文字和跨owner碰撞。
- 新规则：原子发布前必须在1920x1200与1280x800真实浏览器中逐层检查文字最小高度、标注数量和不同owner包围盒零碰撞；失败即拒绝发布。

## 边界

本文件只证明三层诊断修改器的几何、轴网、标注、文档集和交互数据一致；缺少完整施工图集及持证多专业权威，因此不得称为施工图或生产 CAD。
