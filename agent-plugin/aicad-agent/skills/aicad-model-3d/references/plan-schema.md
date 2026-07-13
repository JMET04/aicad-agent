# 3D plan authoring notes

Use `aicad_get_3d_plan_schema` as the normative contract. Version 1.0 supports:

- features: `base_extrude`, `boss_extrude`, `cut_extrude`;
- profiles: `center_rectangle`, `circle`, `circle_pattern`;
- end conditions: `blind`, and `through_all` for cuts;
- millimetres only and exact part origin `[0,0,0]`.

Every feature needs an ASCII `id`, `purpose`, `reasoning`, ordered `depends_on`, profile, depth, end condition, and declared constraints. Non-base features also need `support_feature`, which must be an earlier additive dependency.

Declare exactly one applicable constraint of each kind:

- all features: `depth`, `center_offset` targeting `origin`;
- supported features: `support_coincident` targeting `support_feature`;
- rectangles: `width`, `height`;
- circles: `radius`;
- circle patterns: `radius`, `pattern_count`, `bolt_circle_radius`.

The compiler independently derives geometry from the profile and rejects declarations that disagree with it. Profiles must fit inside their support. Pattern circles must not overlap.

Example plan: `runtime/examples/mounting_plate_3d.plan.json` in the packaged plugin.

