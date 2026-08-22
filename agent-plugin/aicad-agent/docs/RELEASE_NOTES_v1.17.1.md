# aicad-agent 1.17.1

Release date: 2026-08-22

## Cross-domain system design

- Added `aicad.system-engineering-contract.v1` for requirements, subsystem
  ownership, interfaces, flows, evidence hashes, change impacts and release
  gates across PCB, enclosure, power, firmware and manufacturing work.
- Added the `aicad-system-design` skill and reusable workflow for mechanical,
  electronics, packaging, civil and architectural coordination.
- Added deterministic QA and six negative regressions covering tampered
  evidence, missing change propagation, invalid subsystem crossings and
  production claims while required gates remain open.

## Claim boundary

- A passing system report proves contract consistency and bound-file identity;
  it does not rerun CAD/EDA tools or prove physical engineering adequacy.
- Prototype-build authorization remains separate from purchasing, PCBA,
  physical validation, professional approval and production release.
- Open required gates keep production authorization and eligibility false.

## Release integrity

- The schema, QA, tests, workflow and skill are required package files and are
  included in the exact path/size/SHA-256 release closure.
- Plugin, runtime API, compiler and manifest versions remain aligned at 1.17.1.
