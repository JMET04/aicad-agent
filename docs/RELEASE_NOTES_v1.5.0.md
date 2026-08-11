# aicad-agent v1.5.0

`v1.5.0` completes the exact 3D subobject correction path and adds evidence-bound native SolidWorks topology readback.

Highlights:

- line, circle, and face corrections use exact semantic references, source-hash pinning, explicit preserve policies, and downstream dependency replay;
- shared pattern parameters require declared fanout and cannot silently detach one instance;
- product-level residual-wall checks reject edits that erase a supporting boss;
- the multiview reviewer separates thin display strokes from click targets, blocks ambiguous projections, exports formal correction JSON, and passes real-browser UTF-8/overflow checks;
- the SolidWorks host gives ordered sketch primitives and uniquely classified BREP objects native persistent references;
- the SLDPRT stores the catalog in document properties and must pass a real save/reopen per-record resolution and exact key-set equality gate;
- two failures found during live validation—premature COM wrapper release and broad custom-property prefix matching—are now permanent SW-N008/SW-N009 prevention rules.

Real SolidWorks 2026 validation of the mounting-plate fixture produced 36 stored native topology records, including 10 required sketch references. All 36 resolved after reopening; required unresolved count was zero. The final body remained one fault-free solid with its expected volume and bounding box.

This remains an engineering-review candidate. It does not imply manufacturing or technical acceptance. Safety state:

```text
reviewOnly=true
accepted=false
ruleEnabled=false
packagingGated=true
```
