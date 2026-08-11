# aicad-agent v1.8.3

v1.8.3 makes drafting detail and production-readiness explicit non-compensatory gates.

## Added

- Complete architectural construction-stage checks for axes/axis identifiers, typed furniture linework, populated paper space, title blocks, plot scale, revision/status, schedules and navigation references.
- `production_readiness_contract.schema.json`, `production_readiness_rules.json` and `aicad_production_readiness_qa.py`.
- Strict production behavior: any missing required gate yields `blocker_report_only`; candidate CAD artifacts are not exposed under a production label.
- Candidate artifact existence and SHA-256 verification.
- Hash-addressed ASCII compatibility staging for self-contained review HTML on Windows non-ASCII paths, including one retry after a direct-open failure.

## Safety boundary

A successful production-readiness run creates a release candidate only. It retains `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`; authorized professional review, statutory approval and manufacturing release remain external.
