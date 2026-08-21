# MW-FACTORY-RFQ-001 CAD brief

- Model: Rev B-RFQ magic-wand mechanical product package; six molded components, one purchased GFRP rod and a positioned assembly.
- Primary output: STEP AP214 closed BREP parts and a labeled assembly STEP. SolidWorks files are host-imported BREP containers and are not claimed as editable feature-history authority.
- Secondary output: per-part DXF manufacturing drawings, assembly/general-arrangement, exploded, section and harness-interface DXFs, an interactive vector reviewer, BOM, assembly work instruction, molding input specification, inspection plan and hash manifest.
- Units: millimetres.
- Coordinate system: right-handed `MODEL_XYZ`; datum A is the rear-cap exterior plane at global Z=0; +Z points toward the rod tip; +Y points through the press-to-arm button.
- Product envelope: 315 overall length, 27 grip OD, 115 grip segment and 190 exposed GFRP.
- Injection architecture: the former one-piece axial tube is replaced by upper/lower longitudinal shells so the button, service openings, seam location and M2 retention can be represented without hiding impossible axial-core assumptions.
- Required BREP features: real Ø8.2 press-to-arm side aperture, recessed guard, rounded USB-C and debug openings, nominal 2 mm shell wall, tongue/groove seam, four screw stations, carrier key rail/groove, PCB bosses, rear energy director, connector adhesive grooves and plunger anti-rotation flat.
- Assembly datums: upper/lower shell at Z=5; rear cap at Z=0; carrier at Z=9; rod connector at Z=100; GFRP at Z=95; button at Z=72.
- Validation targets: one valid solid per part, named assembly children, exact bounding boxes within declared tolerances, button/service cut tools intersect both the pre-cut shell and the final void, pairwise interference classified as zero or explicitly intended, STEP hash closure, SolidWorks save/reopen when available and interactive vector review.
- Factory boundary: sufficient for mold-maker DFM/RFQ and T0 planning; not permission to cut production tool steel. Final resin/shrinkage, moldflow, gate/ejector/parting decisions, welding DOE, structural/RF tests and signed engineering release remain open.

## Authority order

1. Selected controlled standards/scope in `../../authority/selected-standards-scope.json`.
2. Approved review-stage design basis in `../../authority/engineering-design-basis.json`.
3. Explicit user requirement for factory DFM/RFQ drawings, assembly drawings and true CAD geometry.
4. `factory-design-input.json` Rev B-RFQ engineering assumptions.
5. Existing Rev A CAD as reference baseline.
6. Inferred molding suggestions, always marked vendor-review/steel-safe.

## Normative declaration

- Domain: `mechanical`.
- Delivery stage: `tooling_dfm_rfq_input_not_tool_release`.
- Selected rule packs: datum scheme, fits/tolerances, wall thickness, interference, manufacturability, drawing standard, canonical mechanical preflight and post-generation evidence closure.
- Standards: ISO 8015, ISO 14405-1, ISO 5459, ISO 1101, ISO 22081, ISO 13715, ISO 21920-1, ISO 1, ISO 2768-1 and ISO 286 where explicitly invoked. Edition/scope remain bound to the package standards ledger; this package does not assert independent compliance certification.
