# Failure recovery

Tool failures return `ok: false` with `error.code` and `error.message`.

## PLAN_INVALID

Fix the smallest reported relation. Common causes:

- first anchor is not `origin`;
- a reference points forward or names an unsupported point;
- a declared length, direction, radius, or angle disagrees with resolved geometry;
- a later anchor is disconnected and lacks a valid offset relation;
- geometry is zero-length, duplicated, non-finite, or outside the safe coordinate range.

Call `aicad_validate_plan` after the edit before compiling again.

## PROVIDER_ERROR

The optional provider is unavailable or unconfigured. Retry a supported common shape with `provider: offline`. For arbitrary geometry, author the plan directly from the user requirements and call `aicad_compile_plan`; do not silently simplify the requested geometry.

## IO_ERROR

Choose a writable output directory. Do not overwrite user-authored plan files unless explicitly requested. Omit `output_dir` to let the plugin create an isolated job directory.

## INTERNAL_ERROR

Run `aicad_capabilities` or CLI `capabilities` to confirm the packaged runtime is present. If the runtime is missing, reinstall the plugin rather than reimplementing its compiler inside the agent response.
