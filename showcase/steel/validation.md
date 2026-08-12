# 三层钢结构诊断验证报告

- 总状态：**PASS**
- 处置：仅供诊断修改器审阅；不允许生产/施工发布。
- 构件：132 根；节点：52 个。
- 权威边界：productionAuthority=false。

## 检查

| 检查 | 结果 |
|---|---|
| `ascii_unique_node_and_member_ids` | PASS |
| `all_member_endpoints_reference_exact_nodes` | PASS |
| `all_member_lengths_math_exact` | PASS |
| `all_member_dependencies_backward` | PASS |
| `no_duplicate_member_centerlines` | PASS |
| `node_xy_provenance_is_column_or_explicit_core_only` | PASS |
| `column_xy_set_exactly_matches_source_union_no_cartesian_expansion` | PASS |
| `member_family_coverage` | PASS |
| `four_level_view_coverage` | PASS |
| `core_columns_continuous_all_three_storeys` | PASS |
| `axis_catalog_is_non_equal_and_not_module_authority` | PASS |
| `architecture_source_hashes_still_fresh` | PASS |
| `design_basis_hash_still_fresh` | PASS |
| `architecture_pointer_hash_still_fresh` | PASS |
| `safety_locks_fail_closed` | PASS |
| `utf8_roundtrip_no_replacement` | PASS |
| `mojibake_markers_absent` | PASS |
| `required_chinese_ui_present` | PASS |
| `interactive_api_present` | PASS |
| `four_storey_options_present` | PASS |
| `source_hash_embedded` | PASS |
| `svg_white_background_and_native_text` | PASS |
| `browser_interaction_qa` | PASS |

## 根因与永久防错

旧版把若干 X、Y 坐标分别列出后做笛卡尔积，因此在建筑没有柱的位置凭空生成钢柱；同时把 4.2 m 当成权威模数，导致非等距轴网被规则网覆盖。旧修改器又把所有楼层叠合显示，视觉上像只有一层。

本版执行 STR-D001～STR-D007：逐柱来源、禁止补点、跨专业哈希、新鲜度复核、四标高筛选、端节点依赖、浏览器交互和原子发布。以后只要源计划变化，旧钢结构候选自动失效，不能继续沿用。

## 专业边界

截面仅为概念审阅占位。承载力、挠度、稳定、节点、基础、边坡锚固、风震、耐火和盐雾防护仍需注册结构工程师完成。
