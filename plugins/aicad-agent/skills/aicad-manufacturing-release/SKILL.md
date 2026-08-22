---
name: aicad-manufacturing-release
description: Build and review hash-closed factory RFQ, prototype, and manufacturing handoff candidate packages for mechanical parts, assemblies, and PCBs. Use when native CAD/EDA, drawings, CAM, BOM/CPL, inspection, supplier, or actual 2D/3D preview evidence must be packaged together; do not use for an ordinary single drawing or model request.
---

# AICAD Manufacturing Release

Use this skill after the underlying geometry and engineering source have been generated. For 2D drawing work use `$aicad-draw`; for mechanical 3D work use `$aicad-model-3d`. This workflow proves a controlled delivery closure; it does not replace domain engineering, native CAD/EDA checks, supplier review, certification, or statutory approval.

Read [MANUFACTURING_RELEASE_CONTRACT.md](../../docs/MANUFACTURING_RELEASE_CONTRACT.md) before authoring a package.

## Workflow

1. Resolve the exact package scope, revision, engineering domain, units, coordinate systems, recipient class, and requested readiness stage. Preserve RFQ, prototype, factory handoff, tooling, and production as distinct stages.
2. Keep one controlled evidence root. Represent every source, native artifact, drawing, report, preview, and supplier record with its relative path, positive byte size, SHA-256, and allowed kind. Reject absolute, traversal, linked, missing, mutated, probe, temporary, or WIP paths.
3. Close every subject independently:
   - A mechanical part needs native CAD, STEP, a manufacturing drawing, an actual 2D preview, an actual 3D preview, and native reopen evidence.
   - An assembly additionally needs native assembly CAD, assembly STEP, assembly/exploded/section drawings, BOM, positions, assembly work instructions, inspection and molding inputs where applicable, interference evidence, and native reopen evidence.
   - Each PCB needs its own project, schematic, board, native ERC/DRC, schematic PDF, fabrication and assembly drawings/notes, BOM, CPL, IPC-D-356, board 3D model, actual previews, CAM job, every declared Gerber layer, and typed PTH/NPTH drill outputs.
4. Bind every actual preview to the exact source artifact SHA it depicts. A generic illustration, placeholder, stale image, or reviewer screenshot cannot satisfy a subject preview role.
5. Record native execution with the real tool name/version, `nativeExecution=true`, exact gate/subject/revision, input and output SHA maps, and zero failed checks. Do not convert an unavailable or failed native host run into PASS.
6. Validate the package with `aicad_validate_manufacturing_release_package`. Fix all blockers at their source; do not suppress, waive, average, or replace them with narrative claims.
7. Build with `aicad_build_manufacturing_release_package`. A passing domain may produce a non-null scoped digital candidate while another domain remains blocked. Only a real package-specific supplier confirmation may unlock a factory-handoff candidate. An unassigned RFQ recipient can unlock only a neutral mechanical RFQ candidate.
8. Open the returned same-page reviewer with `aicad_open_manufacturing_release_review`. It must expose the real hash-bound 2D and 3D previews, subject identity, line-style legend, blockers, and one repair action per blocker using portable relative links.
9. Report the highest stage actually reached and every remaining blocker. Keep tooling cut, mass production, professional release, and production authorization false; those decisions remain external even when the digital package is complete.

## MCP tools

- `aicad_get_manufacturing_release_schema`
- `aicad_validate_manufacturing_release_package`
- `aicad_build_manufacturing_release_package`
- `aicad_open_manufacturing_release_review`

## CLI fallback

```powershell
python scripts/aicad_agent.py manufacturing-release-schema
python scripts/aicad_agent.py manufacturing-release-validate --package package.json --evidence-root evidence
python scripts/aicad_agent.py manufacturing-release-build --package package.json --evidence-root evidence --out build/factory --name product
python scripts/aicad_agent.py manufacturing-release-open --review-html build/factory/product.review.html
```

Parse stdout as one JSON object. A successful command has `ok: true`; a failed gate returns structured errors and must not expose a higher-stage artifact.
