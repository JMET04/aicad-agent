# AICAD system engineering workflow

Use this workflow when a deliverable succeeds only if two or more subsystems agree. Examples include a PCB, battery, enclosure, firmware and factory package; a machine, control cabinet and safety logic; packaging around a product; or civil, architectural, structural and building-services interfaces.

The system contract coordinates the domains. It never weakens their standards, calculations, CAD/EDA checks, drawings, testing, professional review, or release authority.

## 1. Freeze the system boundary

Record the intended use, prohibited uses and revision first. Split work into independently verifiable subsystem scopes rather than file types. A PCB and its Gerbers are normally one electronics subsystem; the enclosure is mechanical; embedded behavior is firmware; ordering/assembly outputs may form a manufacturing subsystem.

Use the actual registered disciplines—such as `mechanical`, `electronics`, `firmware`, `packaging`, `civil`, `architecture`, `manufacturing`, or `systems`. Use `other` only for a genuinely unmatched discipline and state its scope precisely.

## 2. Build traceable requirements and gates

Give every system-level obligation a stable ASCII ID. Trace it both ways:

- requirement → owning subsystem IDs and verification gate IDs;
- gate → requirement IDs, required evidence level, method, status and evidence IDs.

Do not use a score to compensate for a failed gate. A passed gate needs bound evidence at or above its required level. Keep a gate `open`, `failed`, or `blocked` when its evidence is unavailable or insufficient.

Evidence levels are deliberately distinct:

| Level | Meaning |
| --- | --- |
| `defined` | Intent or interface has been specified. |
| `generated` | An artifact exists but has not passed its governing tool. |
| `tool_verified` | The named deterministic/native tool check passed for the bound revision. |
| `physical_verified` | A real prototype, assembly, test, inspection, or site observation passed. |
| `released` | The separately authorized release record exists. |
| `blocked` | Required work or evidence cannot currently proceed. |

## 3. Freeze interface control data

An interface is a contract between different subsystems, not a note attached to one model. Record:

- provider and consumer;
- interface kind;
- an unambiguous contract statement;
- each authoritative parameter with value, unit, tolerance when applicable, and source authority;
- verification gates.

For a PCB/enclosure/firmware product, typical interfaces include board outline and datum, mounting-hole axes, connector keep-outs, antenna clearance, battery envelope and polarity, power/current/thermal limits, haptic reservation, button access, sensor axes, firmware event framing, programming access, and the fabrication package revision.

For packaging or civil work, the same pattern applies to product envelope and compression limits, handling and pallet flows, coordinate reference system, datum/epoch, invert levels, utility crossings, drainage discharge, loads, tolerances, inspection points, and construction sequencing. Never infer authoritative site or engineering values from a screenshot.

## 4. Model end-to-end flows

Record the ordered subsystems and interface IDs for every material flow that can determine system behavior. Include the defined failure state.

- Energy: source → protection/charging → regulation → loads.
- Signal/data: sensor → firmware → protocol → receiver or actuator command.
- Force/thermal/fluid: source → transfer path → sink and abnormal state.
- Manufacturing: controlled source files → fabrication outputs → inspection → assembly.
- Human/site: user, maintainer, installer or field action across the affected interfaces.

Flows reveal gaps that isolated drawings miss: a reserved battery volume without a wire bend path, a connector without service access, a command without a safe receiver state, or a site outlet without an accepted discharge route.

## 5. Bind artifacts and evidence

Each artifact belongs to exactly one subsystem, while interfaces link the subsystem meanings. Bind evidence beneath one controlled root using a safe relative path, exact byte size and content SHA-256. Record the producing tool/version when known.

The contract QA checks identity and internal traceability. It does not authenticate who produced an artifact, rerun KiCad/SolidWorks/AutoCAD/analysis software, validate a supplier's process, or independently approve engineering calculations.

## 6. Declare change propagation

Every interface needs an explicit `changeImpacts` entry. A change must identify affected requirements, artifacts, interfaces or flows and the exact gates to replay. Typical examples:

- PCB outline or connector move → enclosure/carrier rebuild, clearance review, assembly drawing and fit test.
- Battery chemistry/capacity change → envelope, protection, charge current, thermal, runtime and shipping/packaging checks.
- Sensor-axis or gesture-protocol change → firmware classifier, event framing, receiver state machine and end-to-end test.
- Civil datum or alignment change → grading, utilities, drainage, structure interfaces, quantities and drawing-set regeneration.

Do not accept “review everything” as a substitute for named rechecks; it is neither auditable nor reliably executable.

## 7. Validate and hand off

From the plugin root, run:

```powershell
python scripts/aicad_system_engineering_qa.py path/to/system-contract.json --root path/to/evidence-root --output path/to/system-qa.json --markdown path/to/system-qa.md
```

A passing report means the contract graph and evidence hashes are internally consistent. Report separately:

- domain-tool results actually run;
- physical and site tests actually run;
- open/failed/blocked gates;
- prototype and production authorizations;
- the next action and its owner;
- the claim boundary from the QA report.

Prototype permission and production permission are separate. With any open gate, production authorization and eligibility stay false. Even with all gates passed, external purchasing, fabrication, construction, deployment, payment, professional sign-off, and release remain distinct authorized actions.
