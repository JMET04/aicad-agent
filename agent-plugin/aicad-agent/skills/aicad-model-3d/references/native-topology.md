# Native topology authority gate

Use this gate only for an executed SolidWorks build.

1. Each ordered rectangle edge or circle primitive must have a required semantic key and native `GetPersistReference3` payload.
2. Uniquely classified BREP edges and faces may be added as derived native references. Never invent an object when a cut consumes the corresponding face.
3. Embed all currently resolvable records as deterministic `AICAD_REF_NNNN` document properties before saving SLDPRT.
4. Reopen the saved SLDPRT in SolidWorks and resolve every stored payload with `GetObjectByPersistReference3`.
5. Compare the exact saved and reopened semantic-key sets. Require at least one required record and zero unresolved required records.
6. Keep volume, bounding box, body-fault, feature-error, fully-constrained-sketch, source-hash, and review-lock gates independent.
7. Set `native_topology_authority=true` only in the successful executed result. Offline semantic views remain `topology_authority=false`.

If capture or reopen fails, read the host report before retrying. In particular, do not final-release a COM object returned by reference readback while the caller may still hold the same runtime wrapper, and do not parse `AICAD_REF_COUNT` as an ordinal reference record.
