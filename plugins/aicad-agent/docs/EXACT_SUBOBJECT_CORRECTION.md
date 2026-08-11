# Exact 3D subobject correction

This capability turns an exact selected edge, circle, or face into a bounded mathematical transaction. It does not treat a highlighted line as an independent solid and does not infer dimensions from display pixels.

## Transaction boundary

Every exact operation carries:

- the current plan `source_sha256`;
- an exact `feature_id|semantic_subobject` reference;
- the selected feature, subobject type, and canonical edit paths;
- explicit edit scope and expected affected instance count;
- a preserve policy when the selected geometry is underdetermined;
- review locks: `reviewOnly=true`, `accepted=false`, and `ruleEnabled=false`.

The backend rejects stale hashes, stale reference metadata, hidden pattern fan-out, unsupported instance detachment, locked parameters, inverted profiles, broken origin datums, invalid support containment, complete boss removal, and any later feature that fails during full dependency replay.

## Preserve policies

| Policy | Mathematical meaning |
|---|---|
| `keep_center` | Move the selected boundary symmetrically; the profile center remains fixed. |
| `keep_opposite` | Keep the opposite boundary fixed; update both profile size and center. |
| `keep_size` | Translate the whole profile; keep its width or height unchanged. |
| `keep_support` | Move an extrusion end plane while keeping its support plane fixed. |

The global base feature remains anchored at the origin. A `keep_opposite` edit that translates the base is therefore rejected even if the local rectangle math is valid.

## Shared pattern behavior

A visible pattern hole is not an independent object. Its radius and pattern center are shared parameters. A correction must explicitly use `scope=shared_parameter_group`, repeat the current `affected_instance_count`, and carry the exact shared parameter groups. `detached_instance` is fail-closed in the current compiler.

## Relation behavior

Two selected lines expose parallel, perpendicular, collinear, and equal-length choices. Two circles expose concentric and equal-radius choices. Two planar faces expose parallel, perpendicular, coincident, and signed offset choices.

Relations already guaranteed by an axis-aligned profile are recorded as `already_satisfied` without fake changed paths. A requested equal-radius relation that would remove the positive residual wall of a supporting boss is rejected by the complete-model gate.

## End-to-end evidence

The synchronized review page can draft `move_subobject`, `set_subobject_parameter`, and `add_subobject_relation` operations. The real-browser smoke test clicks exact SVG/canvas references, checks Chinese and layout, exports the formal JSON transaction, and sends it back through the correction compiler. The resulting audit lists exact references, preserve decisions, shared impact, changed paths, and downstream replay.

Plan-derived references remain semantic references only. Native SolidWorks persistent BREP references require host readback and are not claimed by this layer.
