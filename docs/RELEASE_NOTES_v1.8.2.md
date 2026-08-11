# aicad-agent v1.8.2

v1.8.2 is a report-quality patch on top of the architectural drafting gates in v1.8.1.

## Changes

- Adds ARCH-D014 for idempotent validation/audit report generation.
- Requires one complete symptom, root cause, correction and prevention rule per stable rule ID.
- Collapses identical repeated lessons before write and rejects conflicting duplicate IDs.
- Adds scripts/aicad_report_qa.py and reusable aicad.reporting helpers.
- Adds positive and negative tests for unique IDs, incomplete records, conflicts and exact safety locks.
- Does not alter the validated architectural geometry, axis grid, AutoCAD XData or 3D steel model.

## Safety

This remains an engineering review candidate. Defaults remain reviewOnly=true, accepted=false, ruleEnabled=false and packagingGated=true.
