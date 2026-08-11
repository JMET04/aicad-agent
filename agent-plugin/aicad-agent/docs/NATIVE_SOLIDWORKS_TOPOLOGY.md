# Native SolidWorks topology readback

The SolidWorks host assigns stable semantic keys such as `F001|profile.edge.1`, `F002|profile.circle.3`, and `F003|feature.face.cylindrical.1` to actual SolidWorks sketch segments, edges, and faces. The host obtains native reference bytes with `GetPersistReference3`, embeds the catalog in the SLDPRT as deterministic `AICAD_REF_NNNN` custom properties, saves the file, reopens it, and resolves every stored record with `GetObjectByPersistReference3`.

## What is authoritative

- Ordered rectangle sketch edges and ordered circle sketch primitives are required references.
- Analytically classified BREP edges and faces are included when a unique native object exists.
- A successful live result reports `native_topology_authority=true` only after save/reopen key-set equality and zero unresolved required references.
- An offline plan or projected multiview review remains semantic and reports native authority as false.

The required-reference rule deliberately distinguishes editable design intent from potentially split or consumed result topology. A through-hole, for example, has a cylindrical face and circular boundary but no physical disk face. The host does not invent a disk face merely to fill a semantic slot.

## Why the host does not use screen picking

Reference classification uses the exact plan profile, analytic surface type, vertex coordinates, radius, and extrusion depth. Screen coordinates and rendered pixels are never accepted as dimensional or topology truth. This avoids selecting a visually nearby edge when multiple projected objects overlap.

## Save/reopen gate

The native host fails closed when:

1. a required sketch primitive has no persistent reference;
2. a semantic reference key is duplicated or ambiguous;
3. the reopened catalog is empty;
4. a required record cannot be resolved;
5. the saved and reopened key sets differ; or
6. body, volume, bounding-box, sketch-constraint, or feature-error checks fail.

The output is engineering-review evidence only. The safety state remains `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`.

## Failure lessons encoded as rules

- `SW-N008`: a persistent-reference read can return the same COM runtime wrapper already held by the caller. Final-releasing that wrapper disconnects the original face or edge. The host therefore avoids premature final release during capture.
- `SW-N009`: `AICAD_REF_COUNT` shares the textual prefix used by actual records. The reopen reader therefore accepts only the exact ordinal form `AICAD_REF_NNNN`.

These lessons are executable release rules, not one-off notes.
