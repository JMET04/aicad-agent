# Plan schema guide

Use schema version `2.0`, units `mm` or `inch`, origin `[0,0]`, and a tolerance from `0` through `0.1` exclusive of zero.

## Common fields

Every step requires an ASCII ID, `type`, non-empty `purpose`, non-empty `reasoning`, and at least one constraint. IDs must match `^[A-Za-z0-9_]+$` and may only reference earlier steps.

Anchors use exactly one form:

```json
{"ref":"L001.end"}
```

```json
{"point":[120,80]}
```

Available point references:

- line: `.start`, `.end`, `.midpoint`;
- circle: `.center`;
- arc: `.center`, `.start`, `.end`;
- text: `.insert`;
- dimension: `.first`, `.second`, `.base`, `.midpoint`;
- global: `origin`.

## Line

Required fields: `start`, `construction`, `constraints`.

Construction kinds:

- `to_point`: `target` anchor;
- `vector`: `dx`, `dy`;
- `polar`: positive `length`, `angle_deg`;
- `parallel`: earlier line `to`, positive `length`, `direction` (`same` or `opposite`);
- `perpendicular`: earlier line `to`, positive `length`, `turn` (`left` or `right`).

Line constraints: `horizontal`, `vertical`, `length`, `parallel`, `perpendicular`, `start_coincident`, `end_coincident`, `start_offset`.

## Circle

Required fields: `center`, positive `radius`, `constraints`.

Circle constraints: `radius`, `diameter`, `center_coincident`, `center_offset`.

## Arc

Required fields: `center`, positive `radius`, `start_angle_deg`, `end_angle_deg`, `constraints`. Arcs are counter-clockwise and cannot have a zero or 360-degree-equivalent sweep.

Arc constraints: circle constraints plus `start_angle` and `end_angle`.

## Text

Required fields: `insert`, non-empty `value`, positive `height`, and `constraints`; `rotation_deg` defaults to zero. Text is middle-centre aligned at `insert` so an axis identifier can be mathematically coincident with its bubble centre.

Text constraints: `position_coincident`, `position_offset`, `text_height`, and `rotation`. Unicode BMP text is escaped as ASCII `\U+XXXX` in `.aicad`, `.scr`, and `.dxf`, while the UTF-8 plan and audit retain the original string. Control characters, the record separator `|`, backslash input, and non-BMP characters fail closed.

For architecture, use semantic layers such as `GRID`, `GRID_BUBBLE`, `GRID_TEXT`, `WALL`, `OPENING`, `FURNITURE`, `DIMENSION`, and `OVERHEAD`. Schema 2.0 compiles to AICAD protocol 3 when no native dimension is present and protocol 4 when native dimensions are present, which transports the actual layer; DXF, SCR, and AutoCAD resolve the same normative linetype/lineweight profile. A complete axis is one line, two tangent bubbles, and two identical centred text entities generated from one axis record.

## Dimension

Required fields: `first`, `second`, `base`, `dimension_kind`, `dimension_purpose`, and exactly three constraints. `first` and `second` must reference earlier resolved geometry; free coordinate endpoints are rejected. Use layer `DIMENSION` and a named ASCII `style_name` such as `AICAD_ARCH`.

Kinds are `horizontal`, `vertical`, and `aligned`. Purposes are `overall`, `grid`, `partition`, `opening`, and `general`. Required constraints are one each of `dimension_measurement`, `dimension_orientation`, and `base_offset`. Protocol 4 preserves the entity ID, purpose, style, kind and proof through DXF/AICAD/SCR, AutoCAD creation, XData and save/reopen.

## Offset constraints

Use offsets to prove a disconnected anchor mathematically:

```json
{"kind":"center_offset","target":"origin","dx":60,"dy":40}
```

The compiler recomputes `target + (dx,dy)` and rejects mismatches.

The full machine schema is available through `aicad_get_plan_schema`. Prefer that tool over copying this guide into generated output.
