# aicad-agent v1.10.1

v1.10.1 fixes two completion-audit defects found only after exercising the installed 1.10.0 package against the real villa blocker workflow.

- `ARCH-D036` routes every blocker report through a verified review bundle: JSON, self-contained UTF-8 HTML, opaque PNG and `launch.json`. Non-ASCII paths are staged before opening, and the result records source path, staged path and launch status.
- `ARCH-D037` rejects phantom dimension chains. Every overall, grid, partition and opening ID must resolve to a native `DIMENSION` inventory entity with matching layer, purpose and persisted style.
- The architecture-detail CLI now exposes `--review-launch auto|always|never`, automatically writes `*.review-launch.json`, and returns both that path and the launch result instead of only returning an HTML path.
- Strict production safety remains fail-closed: incomplete sheets or professional authority expose blocker reports only; no CAD artifact is presented as construction-ready.
