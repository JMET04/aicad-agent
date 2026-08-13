# aicad-agent 1.14.0

Release date: 2026-08-14

## What changed

Mechanical and electronics work now has an executable pre-geometry normative gate. It derives its checklist from the same canonical `production_readiness_rules.json` inventory used by the post-generation QA, so the generator and verifier cannot silently maintain divergent rule catalogs.

- Mechanical generation requires exactly 54 resolved rules: seven shared controls plus 11 intent, 20 design and 16 manufacturing-definition gates.
- Electronics generation requires exactly 63 resolved rules: seven shared controls plus 12 intent, 27 design and 17 manufacturing-definition gates.
- New MCP/CLI surfaces create templates, return the schema and validate contracts.
- Mechanical/electronics 2D validation and compilation require an embedded passing `engineering_normative_preflight` before any artifact output.
- Mechanical 3D validation and SolidWorks build enforce the same preflight.
- Per-gate mutation tests remove every required rule in turn; separate negative tests cover duplicates, extras, cross-domain rows, unresolved or reference-only decisions, source/standard drift, conflicts, safety locks and unauthorized `not_applicable` use.
- Requirement-conformance report text is valid UTF-8 and protected by a mojibake regression.

## Two-layer engineering rule model

The new gate controls generation intent before geometry:

1. selected standards and authority precedence;
2. exact rule inventory and applicability decisions;
3. source-bound rule resolutions, conflicts and safety locks;
4. controlled permission to begin deterministic generation.

The existing v3 evidence contract remains the post-generation layer: 71 mechanical or 99 electronics evidence gates close native files, drawings, BOM/CPL/CAM, analysis, inspection and revision relationships.

## Safety boundary

A passing preflight permits controlled generation only. It does not prove the generated result, expose blocked artifacts, authenticate evidence, grant technical-package readiness or authorize production, manufacturing or fabrication. Those conclusions remain fail-closed and require the applicable post-generation evidence gate, native-tool checks and external professional authority.

## Verification

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_*.py" -v
.\scripts\build-agent-plugin.ps1 -OutputDirectory release/ci -Version 1.14.0
python -B scripts/verify_release_package.py release/ci/aicad-agent --source-root .
```
