---
name: aicad-draw
description: Convert natural-language or structured requirements into deterministic, origin-anchored and auditable 2D CAD using agent-native tools. Use for drawing or validating line, circle, and arc geometry; producing DXF, AutoCAD SCR/AICAD, audit, or manifest files; fixing inaccurate AI-generated CAD; enforcing mathematical relations between sequential entities; or avoiding command-stream mojibake.
---

# AI CAD Constraint Drawing

Use the bundled tools as the execution boundary. Do not emit raw AutoCAD commands from model text and do not hand-edit `.aicad` files.

## Core workflow

1. Call `aicad_capabilities` once when entity, constraint, or output support is uncertain.
2. Determine whether dimensions uniquely define the drawing. Ask one focused question when a fit-critical dimension is missing; otherwise state harmless assumptions.
3. Do not ask the user for an API key. For arbitrary, reference-driven, or production-like geometry, call `aicad_get_plan_schema`, author a schema 2.0 plan yourself from the requirements, then call `aicad_validate_plan` and `aicad_compile_plan`.
4. For a rectangle, circle, arc, or rectangular plate with one centered hole, call `aicad_generate`. Keep its default `provider: offline` unless the user explicitly chose a configured provider.
5. Read the returned manifest and audit paths. Treat `ok: true` plus the generated manifest as the completion gate.
6. When visual review matters and a CAD renderer is available, hand the returned DXF path to it. Keep AutoCAD execution as a separate explicit step.

## Plan every entity mathematically

For each entity, determine before submitting the plan:

- its functional purpose;
- the earlier point or entity it depends on;
- the minimum constraints that uniquely determine it;
- whether it closes, continues, parallels, or is perpendicular to earlier geometry;
- whether it duplicates geometry, has zero size, or creates an unintended gap.

Anchor the first line start or first radial center at `origin`. Prefer references to earlier endpoints, midpoints, and centers. Use an explicit origin-relative offset only when no earlier geometric point is appropriate.

Read [plan-schema.md](references/plan-schema.md) before authoring a non-template plan. Read [examples.md](references/examples.md) for tool-call patterns. Read [failure-recovery.md](references/failure-recovery.md) only after a tool rejects a request or plan.

## Result handling

Return the most useful artifacts to the user:

- `.dxf` for portable geometric review;
- `.aicad` for the validated AutoCAD plugin executor;
- `.scr` only as an explicit AutoCAD script fallback;
- `.audit.md` for entity purpose, relations, and reasoning;
- `.manifest.json` for hashes, counts, and artifact inventory;
- `.plan.json` as the editable source of truth.

Never claim that a drawing was created when the tool returned `ok: false`, when only validation ran, or when an expected artifact path does not exist.

## CLI fallback

When MCP tools are unavailable, invoke the bundled script from the plugin root:

```powershell
python scripts/aicad_agent.py capabilities
python scripts/aicad_agent.py generate --request "120x80 plate with centered diameter 20 hole" --out build/job
python scripts/aicad_agent.py generate --request-file request-utf8.txt --out build/job
python scripts/aicad_agent.py validate --plan drawing.plan.json
python scripts/aicad_agent.py compile --plan drawing.plan.json --out build/job
```

Parse stdout as one JSON object. A successful call has `ok: true`; failures are JSON on stderr with a stable `error.code`.
