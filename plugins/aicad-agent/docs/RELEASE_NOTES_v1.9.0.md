# aicad-agent v1.9.0

v1.9.0 makes architectural CAD delivery strict-production-only and replaces self-reported readiness with entity- and evidence-bound gates.

## Production-only architectural contract

- Axis grids now fail precompile unless line coordinate/span, opposite exterior bubble tangency, equal bubble radii, centered identifier text and coordinate ordering are all entity-bound and mathematically verified.

- Adds `aicad_architectural_detail_contract_v2`.
- Requires `stage=production`, `strictProductionOnly=true`, `allowIntermediateCad=false` and `cadExposure=production_release_candidate_only`.
- Requires the complete declared and default architecture production drawing-set matrix.
- A non-production stage, missing sheet class or missing authority returns `blocker_report_only`; no CAD output directory is created.

## Selectable detailed furniture and equipment

- Adds `architectural_symbol_profiles.json` and rule `ARCH-D026`.
- Every sofa, bed, table, cabinet, sanitary fixture and appliance binds actual-size selectable components to typed roles.
- The validator checks exact closed outline, component ID bijection, semantic layer, profile-specific minimum roles, permitted primitive types, bbox and clearance bbox.
- Text, fills, anonymous blocks and occupancy rectangles cannot satisfy the linework gate.

## Evidence-bound production readiness

- Adds `production_readiness_contract_v2.schema.json`, `aicad_production_readiness_qa_v2.py` and `PROD-G009`.
- `passed=true` plus an arbitrary string is no longer accepted.
- Machine results are read from SHA-256-pinned files through JSON Pointers.
- Native-host and professional-release evidence must bind the exact candidate artifact-set SHA-256.
- A missing, modified or mismatched evidence file exposes zero candidate artifacts.

## Readable blocker reviews

- Adds `aicad_review_report.py` and rule `ARCH-D028`.
- Failed gates can emit machine JSON, local single-file UTF-8 HTML and opaque white-background RGB PNG.
- The HTML contains all checks, expandable evidence, root-cause lessons and print/PDF support without a server or external assets.

## Verification

```powershell
python -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_*.py"
python agent-plugin/aicad-agent/scripts/aicad_architecture_detail_qa.py drawing.architecture-detail.json --plan drawing.plan.json --output architecture.json --html architecture.review.html --png architecture.review.png
python agent-plugin/aicad-agent/scripts/aicad_production_readiness_qa_v2.py production-contract-v2.json --output production.json --html production.review.html --png production.review.png
```

Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`. The plugin does not self-sign a drawing or replace licensed professional release.
