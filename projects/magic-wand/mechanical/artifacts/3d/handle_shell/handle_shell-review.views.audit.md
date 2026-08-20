# handle_shell-review - AICAD multi-view audit

- Space/domain: `3d` / `mechanical`
- Source SHA-256: `2fe4fc4542cb540ab73bc338e05c8c1e7971837e2a26f49991a8e61e079e1e0a`
- View count: `6`
- Selection mappings: `80`
- Model coordinate system: `MODEL_XYZ` / `right-handed` / `mm`
- Typed measurements: `80` / `80`
- Coordinate display toggle: `present` (SVG views + 3D selector)
- Exact 3D selector subobjects: `16`
- Review HTML UTF-8/mojibake gate: `pass`
- Visible stroke / independent hit tolerance: `0.8px / 12px`
- Native persistent topology authority: `false` (plan-derived semantic subobjects)

| View | Kind | Geometry scope | Entities | Lost axis | Manufacturing authority |
|---|---|---|---:|---|---|
| `TOP` | `orthographic` | `feature_profiles_before_final_visibility` | 4 | `z` | `False` |
| `FRONT` | `orthographic` | `feature_operation_extents` | 10 | `y` | `False` |
| `RIGHT` | `orthographic` | `feature_operation_extents` | 10 | `x` | `False` |
| `ISOMETRIC` | `isometric` | `selectable_feature_extent_proxy` | 24 | `depth` | `False` |
| `SECTION_X0` | `section` | `feature_operation_section` | 8 | `None` | `False` |
| `SECTION_Y0` | `section` | `feature_operation_section` | 8 | `None` | `False` |

Projection entities are review proxies with semantic back-references. Native host evidence remains required before production use.
