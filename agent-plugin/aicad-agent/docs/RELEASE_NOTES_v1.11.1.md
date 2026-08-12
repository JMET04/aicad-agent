# aicad-agent v1.11.1

v1.11.1 promotes normative governance to the first non-compensatory gate across CAD domains and closes architectural-detail failures found during a full three-storey villa review. A drawing may no longer start from an undeclared standard/rule pack, unsupported equal grid module, colliding fallback annotation, or stale visual preview.

## Normative-first governance

- Contracts declare domain, delivery stage, applicable standards, selected domain rule packs and a fixed authority order before geometry.
- Architecture, packaging, mechanical, sheet metal, electronics, civil, structural, electrical, plumbing, HVAC, process piping, product design and general CAD are covered by the same stage-0 policy.
- `NORM-G004` requires every high-priority rule to have a schema/contract field, generation constraint, independent QA and negative regression test. Documentation alone is not enforcement.

## Architectural dependency graph

- `drawingSheets` and annotation `bindings` now prove real entity IDs, semantic targets, exact text and placement. Self-reported class names do not count.
- Numeric axis identifiers such as `1` are valid semantic targets while CAD entity IDs remain letter-led ASCII IDs.
- Axis coordinates resolve from prior column/core-wall supports or authority-bound datums through explicit dependencies and offsets. Equal spacing is accepted only as a derived result.
- Every exterior opening binds exactly one wall or derived envelope host. Residual wall geometry is the host minus the opening union.
- Room, door, window, dimension and navigation annotations are plan-native. Scale-aware occupancy checks include furniture, equipment, door sweeps, axes, dimensions and title bands.
- Annotation solving reserves real text boxes and full obstacle extents, rejects collisions with door leaves/arcs and uses a separate status band; it fails closed instead of emitting a collision fallback.
- `maintenanceClearances` is a first-class contract object. Service equipment requires an unobstructed in-room clearance rectangle whose computed width meets the declared minimum.

## Review launch policy

Interactive drawing modifiers and audit/blocker reports are separate artifact roles. Automated audit emission defaults to `never`; repeated content-addressed reports do not open new browser tabs. An audit page is opened only by an explicit audit-open request.

## Safety and compatibility

The release remains engineering-review software. `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true` remain locked. Missing drawing classes, native-host evidence or professional authority still produce `blocker_report_only` and no CAD exposure.
