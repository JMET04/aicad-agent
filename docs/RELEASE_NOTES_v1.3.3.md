# aicad-agent v1.3.3

`v1.3.3` is the final engineering-review candidate produced by the remote-install audit.

## What changed

- Added `.gitattributes` so Git checkouts preserve canonical LF bytes on Windows, macOS and Linux while ZIP, PNG and other binary files remain untouched.
- Added REL-G012 documenting why the `v1.3.2` installed-cache byte hashes failed even though all 32 behavior tests passed.
- The release gate now requires official plugin validation, release-manifest verification and isolated behavior tests inside the plugin installed from the real remote tag.
- Retains the `v1.3.2` self-contained marketplace runtime fix and REL-G011.

## Validation target

- Core unit suite: 34 tests.
- Plugin and packaging-rule suite: 33 tests.
- Isolated marketplace suite: the same 33 tests with repository source paths unavailable.
- Real remote-tag install: official manifest validation, 68-file release hash verification and 33 behavior tests.
- GitHub Release attachments downloaded again and checked against local SHA256 values.

## Safety boundary

This remains an engineering-review candidate. The release keeps `reviewOnly=true`, `accepted=false`, `ruleEnabled=false` and `packagingGated=true`. AutoCAD and SolidWorks native execution still require their licensed local hosts.
