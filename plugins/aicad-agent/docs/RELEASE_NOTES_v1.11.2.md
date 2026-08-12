# aicad-agent v1.11.2

v1.11.2 closes two cross-artifact failures found during whole-detail architectural review without weakening the production gate.

- Adds `review_launch=stage`: blocker HTML is copied to a persistent content-addressed ASCII-compatible path but no browser tab is opened. Strict architectural blocker emitters default to this mode; `always` remains explicit reopen only.
- Adds `ARCH-D047` and a required `designBasisBinding` contract. Every local axis is checked against the exact SHA-bound design-basis global catalogue after the floor transform, and stale `structuralGrid` authority is rejected.
- Adds negative regression coverage for stale fixed-grid metadata and positive coverage for persistent no-window review staging.
- Keeps production output fail-closed. Missing drawing classes or professional authority still expose only JSON/HTML/PNG blocker evidence with `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`.
