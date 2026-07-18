# Changelog

## 1.2.2 - 2026-07-18

- Revalidated runtime packaging-QA discovery and fail-closed visual-review acceptance against the packaged payload.
- Added REL-G007 and REL-G008 to prevent manifest/runtime drift and block uploads until behavioral tests pass.
- Added REL-G009 and an API-version regression assertion after remote-baseline comparison caught a stale local release source.
- Added REL-G010 to prevent mutable hashes under an already published version.
- Rebuilt the installable archive under a new immutable patch version.

## 1.2.1 - 2026-07-14

- Deferred SolidWorks template and host discovery until `execute=true`.
- Made 3D validation and compile-only artifact generation work on clean machines without SolidWorks.
- Added a regression test that explicitly masks both the SolidWorks template and host.
- Added REL-G006 after GitHub Actions exposed the local-environment coupling.

## 1.2.0 - 2026-07-14

- Added packaging-dieline global QA and 21 persistent prevention rules.
- Added closed-loop defect reporting: symptom, root cause, repair, prevention rule, regression test.
- Made packaging regression fixtures self-contained and removed personal-path dependencies.
- Declared the no-key Agent-first path explicitly in machine-readable capabilities.
- Added AutoCAD source bundle to the installable plugin.
- Changed the default SolidWorks distribution to source-only to avoid redistributing proprietary interop assemblies.
- Preserved fail-closed 2D origin anchoring, per-entity reasoning, and transactional 3D feature verification.

## 1.1.0 - 2026-07-11

- Added typed SolidWorks 3D planning, per-feature rebuild/readback, SLDPRT/STEP output, and reopen verification.

## 1.0.0 - 2026-07-11

- Initial Agent-native 2D constraint compiler, AutoCAD bundle, DXF/SCR/AICAD outputs, XData, and audit manifests.

