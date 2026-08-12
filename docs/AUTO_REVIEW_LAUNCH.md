# Review launch policy

Every `generate`, `compile`, `build3d`, and `multiview` command creates a local review HTML artifact. Window opening is a separate inspection action, not acceptance.

## Modes

- `never` (default for CLI and Agent tools): generate the review artifact and launch record without opening another browser tab.
- `stage`: copy the report to a persistent content-addressed ASCII-compatible path without opening a browser. Strict blocker-report emitters use this mode so a later manual open cannot point at a deleted temporary file.
- `auto`: open on a desktop host, but suppress a repeated launch of identical bytes inside the bounded deduplication window; skip in CI, `AICAD_NO_GUI=1`, or a host without a graphical display.
- `always`: explicit user-requested reopen; require launch and allow a new tab even when the same bytes were opened recently.

Use `--review-launch auto|stage|always|never` in the CLI or the `review_launch` property in Agent tool calls. `AICAD_REVIEW_LAUNCH` may centrally override the requested mode. `AICAD_REVIEW_AUTO_DEDUP_SECONDS` controls the `auto` duplicate window and defaults to 300 seconds.

Before any GUI launch, the launcher copies the HTML to a persistent content-addressed path below `%PUBLIC%\AICADReview` on Windows (or `AICAD_REVIEW_STAGE_DIR`). This applies to ASCII temporary paths as well as Chinese paths, so deletion of a build/test directory cannot invalidate an open browser page. A launch-state JSON record makes identical `auto` calls idempotent.

The launcher accepts only an existing local `.html` file. It never opens a remote URL and never marks the drawing accepted. Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`.

Every review surface includes a top-bar coordinate-system switch. It hides or restores the 2D axes, origin markers, and 3D triad together, and preserves that visibility choice when the review is reopened.
