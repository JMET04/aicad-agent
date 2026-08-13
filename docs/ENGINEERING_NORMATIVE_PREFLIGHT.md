# Mechanical and electronics normative generation preflight

This gate closes the gap between naming a mechanical/electronics rule pack and actually applying it before geometry. It is mandatory for plans whose domain is `mechanical` or `electronics`.

## One canonical inventory

`rules/production_readiness_rules.json` remains the only authoritative inventory. The preflight does not copy or reinterpret it. It derives an exact application checklist from:

- seven shared rules: `PROD-G001` through `PROD-G006`, plus `PROD-G013`;
- the selected profile's `intent` gates;
- the selected profile's `design` gates;
- the selected profile's `manufacturingDefinition` gates.

The exact inventories are:

- mechanical: 54 generation gates = 7 shared + 11 intent + 20 design + 16 manufacturing-definition gates;
- electronics: 63 generation gates = 7 shared + 12 intent + 27 design + 17 manufacturing-definition gates.

The remaining profile sections (`verification`, `host`, `release`) are post-generation evidence gates and stay in the v3 evidence contract.

## Mechanical coverage

The mechanical preflight freezes source authority, units, standards edition/scope, material/process authority, operating envelope, duty cycle, design life, interfaces and safety applicability. It then requires generation constraints for load cases and abnormal combinations, recomputed calculations and margins, strength, stiffness, fatigue, factor of safety, joints/fasteners/bearings, thermal envelope, fits, tolerance stack, risk controls and assembly/service/tool access.

Manufacturing definition covers material designation/condition/heat treatment, incoming certification/inspection, general and feature tolerances, datum/GD&T scheme, surface texture, stock and primary process, fixturing, tool access, coating compensation, finishes, threads/standard parts, undefined edges/deburr, BOM/revision/quantity closure, critical-characteristic capability and measurement method, and inspection planning. Shared rules add professional drafting, recognizable details, sheets/title/revision/navigation and discipline authority.

The canonical baseline ledger currently contains 14 ISO rows, including GPS fundamentals, dimensional tolerancing, datums, geometrical tolerancing, general specifications, undefined edges, surface texture, reference temperature, invoked general tolerances/fits/threads, fastener properties and torque-clamp testing. A contract must retain every canonical row and bind it to a `selected_standard` source; project applicability and order-time currency still require controlled review.

## Electronics coverage

The electronics preflight freezes schematic, stackup/fabricator, package/footprint/pin-1, power/interface, safety/environmental, product/assembly class and transient/immunity authority. Design constraints cover schematic/PCB parity; pad/net, reference/footprint, footprint/pin-1 and symbol-pin parity; exact ordered MPN resolution; netclass coverage; creepage/clearance; stackup and impedance; complete routing and zero unconnected nets; current zone fill; board outline; courtyard/edge/keepout/connector/mounting geometry; enclosure/tool/wire access; return paths; ratings/derating; power/startup/fault recovery; protection/transient energy; analog accuracy; clocks/reset/programming/protocol; grounding/isolation/common mode; and test/debug access.

Manufacturing definition covers BOM/MPN/parity, Gerber/drill/job/CPL closures, assembly and fabrication plots, native 3D board, reference parity, pin-1/rotation/side audit, DNP ledger, mask/paste/silkscreen/polarity/fab notes, PTH/NPTH/slot/castellation semantics and supplier lifecycle/recheck policy. Shared rules enforce sheet/detail readability and exact discipline authority before layout.

The canonical baseline ledger currently contains seven IPC rows for generic and rigid-board design, rigid-board qualification, bare-board acceptability, soldered assemblies, assembly acceptability and land patterns. The preflight requires the full canonical subset plus a controlled edition/scope decision; it never treats a standard title alone as proof of compliance.

## Contract and fail-closed behavior

Use `rules/engineering_normative_preflight.schema.json`. Every rule application contains:

- exact canonical `gatePath`;
- `constrained`, `unresolved` or justified `not_applicable` disposition;
- requirement statement;
- authoritative `sourceIds`;
- concrete generation constraint;
- verification method;
- applicable standard IDs where governed.

Shared and intent gates cannot be marked not applicable. Other not-applicable decisions require a rationale plus standard or approved-engineering authority. Missing/extra/duplicate gates, profile-version drift, reference-only authority, unknown standards, unresolved conflicts, unsafe paths or opened safety locks fail before geometry and before an output directory is created.

## MCP workflow

1. `aicad_get_engineering_preflight_schema`
2. `aicad_get_engineering_preflight_template` with `mechanical` or `electronics`
3. Replace every unresolved row with a source-bound constraint or valid not-applicable decision.
4. `aicad_validate_engineering_preflight`
5. Embed the passing object as `engineering_normative_preflight` in the 2D/3D plan.
6. Validate/compile/build through the normal AICAD tool.
7. After generation, run `aicad_production_readiness_qa_v3.py` on the actual artifact/evidence closure.

## CLI workflow

```powershell
python scripts/aicad_engineering_preflight.py --template mechanical --output mechanical-preflight.json
python scripts/aicad_engineering_preflight.py --contract mechanical-preflight.json --output mechanical-preflight.report.json --markdown mechanical-preflight.report.md
```

Use `electronics` for PCB/schematic work.

## Meaning of pass

A pass means only `normative_preflight_ready_for_controlled_generation_only`. It permits the controlled generator to begin. It does not prove calculations, native-host persistence, ERC/DRC, manufacturing outputs or evidence authenticity. It exposes no technical artifacts and keeps these values false:

```text
technicalPackageReady=false
productionReleaseEligible=false
manufacturingAuthorized=false
fabricationAuthorized=false
accepted=false
```

The post-generation v3 evidence contract and independent engineering/release trust chain remain separate mandatory gates.
