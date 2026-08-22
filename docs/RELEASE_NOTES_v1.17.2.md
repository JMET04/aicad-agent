# aicad-agent 1.17.2

Release date: 2026-08-22

## Public release closure

- Publishes the cross-domain system-design and manufacturing-release package
  under a new immutable version because the existing `v1.17.1` tag remains a
  historical work-in-progress snapshot.
- Aligns plugin, runtime API, compiler, CI, installer, verifier, documentation
  and archive metadata at `1.17.2` with exact public-tree and archive closure.

## System contract and QA

- Includes `aicad.system-engineering-contract.v1` for requirements, subsystem
  ownership, interfaces, flows, evidence hashes, change impacts and release
  gates across PCB, enclosure, power, firmware and manufacturing work.
- Includes the `aicad-system-design` skill and deterministic QA with negative
  regressions for evidence tampering, missing change propagation, invalid
  subsystem crossings and production claims while required gates remain open.
- Adds a source-faithful Rev B machine map from `SYS-001..012` to the current
  contract requirements, verification gates and evidence bindings, plus a
  current delivery manifest that binds status, contract, QA, handoff and all
  four tool-verified evidence artifacts by portable path, size and SHA-256.

## Printable package portability

- Regenerates the printable-wand package with repository-relative POSIX
  `sourcePcb.path` metadata instead of a workstation-specific drive path.
- Adds a regression that rejects drive-letter or backslash-absolute paths in
  packaged JSON while retaining the verified six-of-six STL mesh gate.

## Manufacturing capability and claim boundary

- Publishes the public manufacturing-release schema, API, CLI, MCP and reviewer
  workflow for building and checking hash-bound mechanical and electronics
  release candidates.
- Prototype bare-PCB ordering and prototype 3D printing are owner-authorized.
  PCBA ordering, target-firmware release, physical first-article acceptance and
  production release remain locked behind open evidence gates.
- A passing report proves contract consistency and bound-file identity only; it
  does not rerun CAD/EDA tools, prove physical engineering adequacy or grant
  professional/manufacturing/production approval.
