# aicad-agent 1.16.0

Release date: 2026-08-20

## Reviewer-to-agent apply bridge

- The 2D and 3D selectable reviewers now submit one typed handoff through clipboard, browser event, parent-frame, or Windows WebView channels.
- The agent validates the exact handoff schema, domain, model space, current source SHA-256, review safety locks, and actionable correction transaction before writing any output.
- Valid handoffs are previewed, dependency-replayed, atomically promoted, audited, receipted, and regenerated as a fresh source-bound selectable reviewer.
- Stale, malformed, notes-only, wrong-space, wrong-domain, unknown-path, and non-empty-output requests fail closed without partial artifacts.

## Correct source-of-truth edits

- 2D line anchors, circle/arc centers and text insertion points now synchronize back to their controlling coincident/offset constraints.
- Text height and rotation update their canonical plan fields; line length edits remain available only when the underlying construction mode can represent them safely.
- 3D features retain exact object/subobject transactions, shared-pattern fanout protection, dependency replay, and product-level residual-wall checks.

## Safety and verification

- Every generated or corrected reviewer remains `reviewOnly=true`, `accepted=false`, and `ruleEnabled=false`.
- The release adds three MCP tools, three CLI commands, a strict handoff schema, packaged-runtime checks, atomic-promotion tests, source-hash regressions, and complete source/package test coverage.
- This package is an engineering review candidate. It does not grant technical acceptance, production release, manufacturing, or fabrication authorization.

