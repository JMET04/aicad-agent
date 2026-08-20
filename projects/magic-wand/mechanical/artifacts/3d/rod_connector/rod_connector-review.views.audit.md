# rod_connector-review - AICAD multi-view audit

- Space/domain: `3d` / `mechanical`
- Source SHA-256: `f1eaa4487e1d26a47276faae45addca9b400da3bf05a8881ece6411c71f97ec7`
- View count: `6`
- Selection mappings: `120`
- Model coordinate system: `MODEL_XYZ` / `right-handed` / `mm`
- Typed measurements: `120` / `120`
- Coordinate display toggle: `present` (SVG views + 3D selector)
- Exact 3D selector subobjects: `24`
- Review HTML UTF-8/mojibake gate: `pass`
- Visible stroke / independent hit tolerance: `0.8px / 12px`
- Native persistent topology authority: `false` (plan-derived semantic subobjects)

| View | Kind | Geometry scope | Entities | Lost axis | Manufacturing authority |
|---|---|---|---:|---|---|
| `TOP` | `orthographic` | `feature_profiles_before_final_visibility` | 6 | `z` | `False` |
| `FRONT` | `orthographic` | `feature_operation_extents` | 15 | `y` | `False` |
| `RIGHT` | `orthographic` | `feature_operation_extents` | 15 | `x` | `False` |
| `ISOMETRIC` | `isometric` | `selectable_feature_extent_proxy` | 36 | `depth` | `False` |
| `SECTION_X0` | `section` | `feature_operation_section` | 12 | `None` | `False` |
| `SECTION_Y0` | `section` | `feature_operation_section` | 12 | `None` | `False` |

Projection entities are review proxies with semantic back-references. Native host evidence remains required before production use.
