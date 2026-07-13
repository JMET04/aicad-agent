# Release packaging lessons

The 1.2.0 publication audit converted each discovered release defect into a persistent rule rather than relying on a one-off rebuild.

| Rule | What failed | Why | Permanent prevention |
|---|---|---|---|
| REL-G001 | The 1.1.0 ZIP lacked current packaging QA. | The old archive was mistaken for current source. | Build from source, bind versions, and verify per-file hashes. |
| REL-G002 | Clean tests could not find CAD plans. | Tests depended on `jobs` and research experiment directories. | Store minimal sanitized inputs under `tests/fixtures`. |
| REL-G003 | A correct PNG was rejected by an optional SVG check. | The validator used “all formats” instead of “at least one format plus visual review.” | Encode the actual delivery contract and regress it. |
| REL-G004 | Verification created cache files. | Python wrote bytecode inside the staged tree. | Use `python -B`, then verify cache absence and hashes. |
| REL-G005 | Local host packaging included vendor interop DLLs. | Local completeness was conflated with redistribution permission. | Publish source/build instructions; keep proprietary binaries local unless licensed. |

Machine-readable definitions live in `agent-plugin/aicad-agent/rules/release_integrity_rules.json` and are covered by a packaged regression test.

