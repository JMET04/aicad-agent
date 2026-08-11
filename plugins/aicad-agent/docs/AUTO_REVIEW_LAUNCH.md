# Automatic review launch

Every interactive `generate`, `compile`, `build3d`, and `multiview` command now creates a review HTML artifact and opens it after the validated artifacts have been written. This is an inspection boundary, not an acceptance action.

## Modes

- `auto` (default for CLI and Agent tools): open on a desktop host; skip in CI, `AICAD_NO_GUI=1`, or a host without a graphical display.
- `always`: require launch and fail explicitly when the host cannot open the page.
- `never`: still generate the review artifact but do not open a window.

Use `--review-launch auto|always|never` in the CLI or the `review_launch` property in Agent tool calls. `AICAD_REVIEW_LAUNCH` may centrally override the requested mode.

The launcher accepts only an existing local `.html` file. It never opens a remote URL and never marks the drawing accepted. Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`.

Every review surface includes a top-bar coordinate-system switch. It hides or restores the 2D axes, origin markers, and 3D triad together, and preserves that visibility choice when the review is reopened.

## Windows non-ASCII path compatibility

When a local self-contained review file lives under a non-ASCII Windows path, the launcher copies identical bytes to a SHA-256-addressed ASCII path under `%PUBLIC%\AICADReview` (or `AICAD_REVIEW_STAGE_DIR`) and opens that copy. A direct-open `OSError` also triggers one compatibility retry. The result records source path, launch path and whether staging occurred.
