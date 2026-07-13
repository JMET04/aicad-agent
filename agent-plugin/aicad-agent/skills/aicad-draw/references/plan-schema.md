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

## Offset constraints

Use offsets to prove a disconnected anchor mathematically:

```json
{"kind":"center_offset","target":"origin","dx":60,"dy":40}
```

The compiler recomputes `target + (dx,dy)` and rejects mismatches.

The full machine schema is available through `aicad_get_plan_schema`. Prefer that tool over copying this guide into generated output.
