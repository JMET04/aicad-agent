# aicad-agent v1.3.2

`v1.3.2` is the corrected engineering-review release for the Git marketplace distribution path.

## What changed

- The marketplace now copies the fully assembled plugin directory, including `runtime/src/aicad`, schemas, examples, AutoCAD assets, SolidWorks host source, `integration-manifest.json` and `SHA256SUMS`.
- The source builder rejects an incomplete or version-mismatched assembled plugin before it can create a GitHub snapshot.
- The release verifier now requires the core runtime entry point.
- CI builds both distribution paths and runs the complete plugin suite from the isolated marketplace directory.
- REL-G011 records the symptom, root cause and permanent prevention rule for the `v1.3.1` pre-release portability failure.

## Validation target

- Core unit suite: 34 tests.
- Plugin and packaging-rule suite: 32 tests after REL-G011.
- Official Codex plugin manifest validation.
- Release manifest and SHA256 verification.
- Remote Git tag installation followed by isolated behavior tests.

## Safety boundary

This remains an engineering-review candidate. The release keeps `reviewOnly=true`, `accepted=false`, `ruleEnabled=false` and `packagingGated=true`. AutoCAD and SolidWorks native execution still require their licensed local hosts.
