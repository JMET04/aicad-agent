# Feature transaction recovery

Stop at the first failed feature. Inspect that feature's `checks` in the SolidWorks report.

- `sketch_fully_constrained`: add or correct origin, dimension, and relation constraints. Do not suppress this gate.
- `feature_error_code`: verify the selected support, end condition, direction, and profile closure.
- `body_valid`: inspect the SolidWorks body fault entity count; do not infer faults from a non-null container alone.
- `solid_body_count`: ensure an additive profile intersects its support and a cut does not split/remove the body unexpectedly.
- `volume_before`, `volume_after`, `volume_delta`: correct support depth, overlap assumptions, or operation direction.
- `bbox`: correct sketch plane, extrusion direction, or profile location.
- `persistent_reference`: semantically reselect the support geometry, capture a new persistent reference, rebuild, and resolve it again.

After correction, rebuild from a new empty part and replay all prior transactions. Never continue from an unverified partial document.

