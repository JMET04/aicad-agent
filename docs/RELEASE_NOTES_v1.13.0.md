# aicad-agent 1.13.0

Release date: 2026-08-13

## What changed

- Added one canonical v3 mechanical/electronics evidence-contract schema and QA path. It supports repeated artifact kinds, exact subject and artifact IDs, revisions, normalized paths, sizes and SHA-256 bindings.
- Added non-compensatory mechanical gates for authoritative inputs and units, independent recalculation, load paths, bearings, joints, thermal fits, manufacturing definition, inspection trace, native material persistence and drawing/model/inspection parity.
- Added per-PCB closure for the native KiCad project, schematic and board, schematic PDF, BOM, CPL, assembly drawing, independent fabrication drawing, 3D board, CAM job, every copper-layer Gerber and typed PTH/NPTH drill output.
- Added direct parsing of normalized mechanical BOM subject rows and final KiCad board copper/drill inventory, so a declaration cannot hide a missing part, copper layer or drill class.
- Added a controlled continuous-learning loop. Structured failed checks become deterministic, hash-bound lessons with symptom, root cause, correction, prevention candidate, reproducer and negative regression.
- Hardened GitHub showcase verification around four fixed domains, exact role bijection, input safety locks, source/output closure and complete local README links.

## Safety boundary

The v3 generic QA reports only `evidenceContractReady`. It does not authenticate evidence, replay native CAD/EDA tools, expose candidate artifacts, grant `technicalPackageReady`, or authorize production, manufacturing or fabrication.

Learning is intentionally candidate-only. Generated candidates remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false` and `packagingGated=true`. The harvester and QA can write only explicit JSON below `learning/`; they cannot modify rules, tests, plugin metadata, installed plugins or release packages. Even structurally complete approval records remain ineligible until an external authenticated review and a separately authorized versioned change.

## Verification

Use the official source-freshness chain:

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_*.py" -v
.\scripts\build-agent-plugin.ps1 -OutputDirectory release/ci -Version 1.13.0
python -B scripts/verify_release_package.py release/ci/aicad-agent --source-root .
.\scripts\build-github-source.ps1 -OutputDirectory release/ci/github-repository -Version 1.13.0 -PluginArchive release/ci/aicad-agent-1.13.0.zip -PluginDirectory release/ci/aicad-agent
python -B scripts/verify_github_source.py release/ci/github-repository --source-root .
```
