# Agent call examples

## Common shape

Call `aicad_generate`:

```json
{
  "request": "120x80 mm plate with a centered diameter 20 mm hole",
  "provider": "offline"
}
```

Expected result: four ordered lines, one circle, and six artifact paths. The circle center is constrained to `(60,40)` from the origin.

## Arbitrary caller-authored plan

For a triangle, call `aicad_compile_plan` with:

```json
{
  "plan": {
    "schema_version": "2.0",
    "drawing": {"name": "triangle", "units": "mm", "origin": [0,0], "tolerance": 0.000001},
    "steps": [
      {
        "id": "L001", "type": "line", "purpose": "base", "reasoning": "anchors width at origin",
        "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 50, "dy": 0},
        "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 50}, {"kind": "start_coincident", "target": "origin"}]
      },
      {
        "id": "L002", "type": "line", "purpose": "right side", "reasoning": "continues from the base endpoint",
        "start": {"ref": "L001.end"}, "construction": {"kind": "to_point", "target": {"point": [25,40]}},
        "constraints": [{"kind": "length", "value": 47.1699056603}, {"kind": "start_coincident", "target": "L001.end"}]
      },
      {
        "id": "L003", "type": "line", "purpose": "closure", "reasoning": "returns to origin",
        "start": {"ref": "L002.end"}, "construction": {"kind": "to_point", "target": {"ref": "origin"}},
        "constraints": [{"kind": "length", "value": 47.1699056603}, {"kind": "start_coincident", "target": "L002.end"}, {"kind": "end_coincident", "target": "origin"}]
      }
    ]
  },
  "name": "triangle"
}
```

Use tool-returned paths instead of predicting output paths.

## Validate only

Call `aicad_validate_plan` when reviewing or repairing a plan. This returns resolved entity IDs and the source hash but writes no CAD artifacts.
