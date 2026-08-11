# aicad-agent v1.8.0

`v1.8.0` makes the review boundary automatic and explicit.

- Interactive `generate`, `compile`, `build3d`, and `multiview` calls generate a source-bound review HTML and open it by default on desktop hosts.
- `review_launch=auto|always|never` controls the behavior; CI and headless hosts report an explicit safe skip while retaining the review artifact.
- The launcher accepts only existing local HTML and never changes review or acceptance locks.
- Added `REVIEW-G001` through `REVIEW-G005` and regression tests for desktop launch, CI degradation, disabled mode, compile-attached review artifacts, and coordinate-switch persistence.
- The coordinate switch now hides or restores all 2D axes, origins, and the 3D triad together and remembers that choice after reopening the review.
- Production installation now preserves the verified package byte-for-byte; `REL-G016` prevents cache-busting edits from invalidating the installed integration manifest and SHA256SUMS.

Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`.
