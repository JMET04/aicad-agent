# aicad-agent v1.8.4

v1.8.4 moves architectural drafting detail from visual post-checks to a fail-closed precompile contract.

## Architectural detail contract

- Adds `aicad_architectural_detail_contract_v1` and `scripts/aicad_architecture_detail_qa.py`.
- Adds agent-native schema and validation tools for the contract.
- Architecture plans now require an embedded, passing contract before `validate` or `compile` can expose artifacts.
- A failed contract returns `artifactDisposition=blocker_report_only`; no CAD directory is created and no reviewer is launched.

## New non-compensatory rules

- `ARCH-D021`: room-by-room functional equipment completeness.
- `ARCH-D022`: separate FURNITURE, CASEWORK, SANITARY and APPLIANCE semantics.
- `ARCH-D023`: native overall, grid, partition and opening dimension-purpose matrix.
- `ARCH-D024`: door-to-host-wall/opening topology, wall gap, leaf/arc identity and sweep clearance.
- `ARCH-D025`: all architectural detail checks run before compilation as one dependency graph.

Contract claims are not accepted on trust. Axis lines/bubbles, wall segments, door leaves/arcs and equipment components are bound back to resolved AICAD entity IDs, types, layers and coordinates.

## Post-DXF verification

- Native dimensions carry `DIM_PURPOSE:overall|grid|partition|opening` in AICAD XData.
- Architectural DXF QA requires all four purposes and the new interior semantic layers.
- Model-space entities are no longer double-counted through the DXF block table.

## Boundary

This release does not turn an image or concept diagram into construction authority. Production still requires survey, jurisdiction/code, geotechnical, structural, fire/life-safety, MEP, accessibility, licensed review and signed release evidence. Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`.

## Verification

```powershell
python -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_architectural*.py" -v
python -m unittest discover -s tests -p "test_agent_plugin.py" -v
python scripts/aicad_agent.py architecture-detail-schema
python scripts/aicad_agent.py architecture-detail-validate --contract drawing.architecture-detail.json --plan drawing.plan.json
```
