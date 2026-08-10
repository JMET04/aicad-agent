# aicad-agent v1.3.4

`v1.3.4` is the engineering-review candidate that closes the clean-environment dependency gap found by GitHub Actions.

## What changed

- Added `jsonschema>=4.23,<5` to the published packaging/schema-validation requirements and third-party notices.
- Added REL-G013: every directly imported non-standard-library dependency must be declared and tested in a clean environment.
- Retains the self-contained marketplace runtime, canonical LF byte policy, real-installed-cache hash verification and isolated behavior gates from `v1.3.2` and `v1.3.3`.

## Validation target

- Core unit suite: 34 tests.
- Plugin and packaging-rule suite: 34 tests.
- Isolated marketplace suite: the same 34 tests with repository source paths unavailable.
- Real remote-tag install: official manifest validation, 68-file release hash verification and 34 behavior tests.
- GitHub Actions on the final commit must complete successfully.
- GitHub Release attachments must be downloaded again and match local SHA256 values.

## Safety boundary

This remains an engineering-review candidate. The release keeps `reviewOnly=true`, `accepted=false`, `ruleEnabled=false` and `packagingGated=true`. AutoCAD and SolidWorks native execution still require their licensed local hosts.
