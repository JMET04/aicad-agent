from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "mechanical-preflight.template.json"
OUTPUT = ROOT / "mechanical-preflight.json"
RUN_PREFIX = "runs/complex_servo_indexer_v116_20260820/"

SOURCE_ROWS = [
    {
        "id": "STD_AUTHORITY",
        "kind": "selected_standard",
        "description": "Selected ISO GPS, fit, surface, edge, fastener and reference-temperature ledger for review-candidate generation.",
        "path": RUN_PREFIX + "standards-authority.md",
        "sha256": "3ac4f4e815ed8bd8df162f040e7e7389b05c51bf49f9acd07c61e8e65f485ac4",
    },
    {
        "id": "DESIGN_BASIS",
        "kind": "approved_engineering_input",
        "description": "Task-approved controlled-generation design basis for SIFC-220-REV-A; not production acceptance.",
        "path": RUN_PREFIX + "design-basis.md",
        "sha256": "9dd32bad245c844a2c2611b8c78957ab74adc410a6e3380c75528e142260e09f",
    },
    {
        "id": "ANALYSIS_BASIS",
        "kind": "approved_engineering_input",
        "description": "Independent preliminary strength, joint, bearing, thermal and tolerance calculations.",
        "path": RUN_PREFIX + "analysis-basis.md",
        "sha256": "f895f2145fdd03366717cae81a6baf8a0fdf25563578ce9f6b8662df12da7367",
    },
    {
        "id": "MFG_DEFINITION",
        "kind": "approved_engineering_input",
        "description": "Controlled material, process, GPS, finish, edge, fixturing and process-capability definition.",
        "path": RUN_PREFIX + "manufacturing-definition.md",
        "sha256": "d5828102d3d3b1d1bb326b7b679f24b39a50a15a02ffd744aa8ad78223befb74",
    },
    {
        "id": "INSPECTION_PLAN",
        "kind": "approved_engineering_input",
        "description": "Characteristic-to-method inspection closure at the 20 degree Celsius reference condition.",
        "path": RUN_PREFIX + "inspection-plan.md",
        "sha256": "0bc1bd196b6db9285e03ef0fcd0eead84a5e295ce195a57da3a93c325016aa42",
    },
]

CONSTRAINTS = {
    "mechanical.intent.wholeIntent": "Freeze part SIFC-220-REV-A as a dual-6208 servo-indexer flange cartridge with the declared function, 220 x 180 x 56 mm envelope, review delivery stage and no production claim.",
    "mechanical.intent.dimensionalAuthority": "Derive every hard model and drawing dimension from design-basis.md; screen pixels, visual proportions and unconstrained inferred dimensions are forbidden.",
    "mechanical.intent.materialAuthority": "Assign EN AW-7075-T651 to the native part and drawing; material substitution requires a new design basis and recalculation.",
    "mechanical.intent.processAuthority": "Constrain the design to two-setup CNC milling, in-process probing, masked hard anodize and post-finish inspection defined by MFG_DEFINITION.",
    "mechanical.intent.standardsApplicabilityAndEditionResolved": "Bind the exact canonical ISO edition/applicability rows and project scope decisions; no undeclared or superseded sole authority is permitted.",
    "mechanical.intent.materialAndFastenerPropertySourcesBound": "Use the declared 7075-T651 yield basis and ISO 898-1 class 10.9 fastener property source in all preliminary calculations.",
    "mechanical.intent.operatingEnvelopeDutyCycleAndDesignLifeAuthority": "Constrain geometry and checks to 4.5 kN radial, 2.0 kN axial, 350 N m moment, 500 N m torque, 2 g abnormal case, 120 r/min, 30 percent duty, 20,000 h and -10 to +60 C.",
    "mechanical.intent.assemblyConfigurationAndInterfaceAuthority": "Preserve paired 6208 seat, axial cover retention, four M12 frame bolts, two Ø8 H7 dowels, both flange patterns and datum A/B/C interfaces.",
    "mechanical.intent.safetyRegulatoryAndRiskApplicabilityResolved": "Treat bearing creep, frame slip, ligament yielding, misalignment, thermal loosening and service-tool access as explicit controlled failure modes; retain release authorization false.",
    "mechanical.intent.currentStandardsLedger": "Carry the exact 14 canonical published ISO baseline rows into the preflight and later evidence contract.",
    "mechanical.intent.noRetiredSoleAuthority": "Set retired-or-withdrawn sole-authority count to zero and block generation if the standards ledger changes without scope review.",
    "mechanical.design.constraintCompile": "Require schema-valid ordered 3D features, fully constrained sketches, declared supports/dependencies, embedded passing preflight and zero partial artifact exposure on failure.",
    "mechanical.design.detailProof": "Trace each boss, bore, pocket, pattern, mounting feature and drawing characteristic to a frozen requirement and later normality proof.",
    "mechanical.design.loadCasesAndServiceConditions": "Model service, torque-reaction and 2 g abnormal load cases with the declared temperature, duty and life envelope.",
    "mechanical.design.analysisInputUnitsAndProvenance": "Keep all calculation inputs explicitly dimensioned in N, mm, MPa, r/min, degrees Celsius and hours with source-file SHA binding.",
    "mechanical.design.analysisRecomputedFromDeclaredInputs": "Recompute ligament stress, base bending, bolt slip, bearing L10h and differential thermal growth from the declared numeric inputs before delivery.",
    "mechanical.design.criticalLoadPathCoverage": "Maintain continuous load paths from bearing seat through Ø130 boss, intersecting rib pads, 20 mm base, M12 holes and dowels into the frame.",
    "mechanical.design.loadCombinationAndAbnormalCaseCoverage": "Check simultaneous radial/axial/moment/torque service reactions and a separate 2 g abnormal case; unrelated passing checks cannot compensate.",
    "mechanical.design.analysisEquationInputOutputMarginTrace": "Persist equations, numeric inputs, outputs and margins in analysis-basis.md and bind them to the drawing requirement trace.",
    "mechanical.design.strength": "Keep 25 mm minimum boss wall and abnormal nominal stress at or below 98.34 MPa so preliminary yield factor remains at least 4.42.",
    "mechanical.design.stiffness": "Preserve the 20 mm base, Ø130 boss and four intersecting 42 x 72 x 12 mm rib pads; detailed FEA remains mandatory before release.",
    "mechanical.design.fatigueApplicabilityAndResult": "Treat 30 percent cyclic duty over 20,000 h as fatigue-applicable; avoid unsupported sharp internal geometry and retain detailed fatigue analysis as a release gate.",
    "mechanical.design.factorOfSafety": "Require preliminary abnormal yield factor at least 2.0 and calculated 4.42 or higher; any geometry change must trigger recalculation.",
    "mechanical.design.jointBearingAndEdgeChecks": "Verify 6208 seat wall, M12 hole edge distances, dowel ligaments, counterbore floors and all hole-to-pocket separations remain positive.",
    "mechanical.design.fastenerPreloadSlipAndCapacity": "Preserve four M12 class 10.9 joints, 48.98 kN target preload per bolt, 117.6 N m review torque and abnormal slip ratio at least 3.27.",
    "mechanical.design.bearingLife": "Use paired 6208 review basis C=32.5 kN, P=5.2 kN and require calculated L10h at least 33,900 h versus 20,000 h target.",
    "mechanical.design.thermalEnvelope": "Carry the -10 to +60 C range and 0.0387 mm calculated aluminium/steel differential fit growth into fit and retention review.",
    "mechanical.design.fitAndMatingInterfaces": "Specify Ø80 H7 bearing seat, Ø8 H7 dowels, Ø92 H8 cover recess, Ø50 coaxial clearance and mating cover/frame interfaces.",
    "mechanical.design.toleranceStack": "Constrain the 36.00 +0.05/0.00 mm seat depth, two 18 mm bearings and 0.05-0.15 mm cover shim/shoulder allowance.",
    "mechanical.design.failureModesAndResidualRiskControls": "Bind every declared failure mode to its dimensional, joint, fit, datum, inspection or later-analysis control; unresolved risks block release.",
    "mechanical.design.assemblyServiceAndToolClearance": "Keep Ø24 M12 counterbores, cover fastener access, bearing insertion/removal path and CMM/probe access unobstructed.",
    "mechanical.manufacturingDefinition.materialDesignation": "Put EN AW-7075-T651 and part ID SIFC-220-REV-A on native properties and the drawing title block.",
    "mechanical.manufacturingDefinition.materialConditionAndHeatTreatment": "Require supplied T651 condition and explicitly prohibit unreviewed post-machining heat treatment.",
    "mechanical.manufacturingDefinition.materialCertificateRequirementAndIncomingInspection": "Require traceable 3.1-equivalent material certificate review and incoming identity verification per inspection plan.",
    "mechanical.manufacturingDefinition.generalAndFeatureTolerances": "Provide individual fit/GPS tolerances plus ISO 2768-m for every remaining size so tolerance coverage is 100 percent.",
    "mechanical.manufacturingDefinition.gdandtDatumScheme": "Use datum A bottom face, B Ø80 seat axis and C primary dowel axis with flatness, perpendicularity, coaxiality and true-position controls.",
    "mechanical.manufacturingDefinition.surfaceRoughness": "Assign Ra 1.6 to bearing/dowel fits, Ra 3.2 to datum A and Ra 6.3 to all other machined surfaces unless overridden.",
    "mechanical.manufacturingDefinition.stockAndPrimaryProcess": "Use minimum 230 x 190 x 60 mm 7075-T651 stock and a documented nominal two-setup CNC route.",
    "mechanical.manufacturingDefinition.fixturingFeasibility": "Keep datum-A full support for setup 1 and distortion-controlled soft-jaw or expanding-arbor reference for setup 2.",
    "mechanical.manufacturingDefinition.toolAccessibility": "Keep all holes normal to A, Ø24 counterbores tool-accessible and no pocket/rib geometry inside required cutter or socket envelopes.",
    "mechanical.manufacturingDefinition.coatingDimensionalCompensation": "Specify 25 ±5 µm hard anodize only on non-fit surfaces and mask A, Ø80, Ø8, Ø50 and retained interfaces.",
    "mechanical.manufacturingDefinition.processAndFinish": "Carry CNC milling, probing, deburr, masked clear hard anodize and post-finish critical inspection as an ordered process.",
    "mechanical.manufacturingDefinition.threadsStandardPartsAndFastenerDefinition": "Define the M12 class 10.9 frame joint, validated washer/nut/lubricant stack and ISO metric tolerance basis; no anonymous fastener callouts.",
    "mechanical.manufacturingDefinition.undefinedEdgesDeburrAndSharpEdgeControl": "Apply ISO 13715 and drawing note break sharp edges 0.2-0.5 mm, burr-free; native fillet/chamfer geometry is not assumed.",
    "mechanical.manufacturingDefinition.assemblyBomItemRevisionAndQuantityClosure": "Close the part-level BOM as item 1 SIFC-220-REV-A quantity 1 and mark bearings, cover and hardware as mating references not included.",
    "mechanical.manufacturingDefinition.criticalCharacteristicProcessCapabilityAndMeasurementMethod": "Require Cpk at least 1.33 after qualification for Ø80 H7, dowel position and A-to-B perpendicularity with declared measurement methods.",
    "mechanical.manufacturingDefinition.inspectionPlan": "Bind 100 percent of drawing characteristics to the inspection-plan matrix and inspect all critical characteristics on each qualification part.",
    "shared.rules.PROD-G001": "Trace product, use, dimensions, material, selected standards and review-only stage to the five hash-bound controlled sources.",
    "shared.rules.PROD-G002": "Require origin protocol, constraint compile, whole-intent contract, normality proof, domain QA and native save/reopen to pass independently.",
    "shared.rules.PROD-G003": "Generate a populated mechanical sheet with line hierarchy, centerlines, dimensions, GPS callouts, notes, title/revision/status and section/isometric references.",
    "shared.rules.PROD-G004": "Represent every required feature as typed selectable source-bound geometry; labels and screenshots never substitute for model features.",
    "shared.rules.PROD-G005": "Provide populated paper-space drawing sheets, title block, SIFC-220-REV-A, sheet number, scale, revision A, REVIEW status and required detail/section views.",
    "shared.rules.PROD-G006": "Carry material, manufacturing, preliminary engineering and inspection evidence; missing signed FEA/release evidence keeps all authorization locks false.",
    "shared.rules.PROD-G013": "Treat all 54 generation gates and later evidence gates as a conjunction; no visual approval, portable export or unrelated pass offsets a failure.",
}

ALL_STANDARDS = [
    "ISO 8015:2011", "ISO 14405-1:2025", "ISO 5459:2024", "ISO 1101:2017",
    "ISO 22081:2021", "ISO 13715:2017", "ISO 21920-1:2021", "ISO 1:2022",
    "ISO 2768-1:1989", "ISO 286-1:2010", "ISO 286-2:2010", "ISO 965-1:2026",
    "ISO 898-1:2013", "ISO 16047:2005+Amd 1:2012",
]


def standard_ids(path: str) -> list[str]:
    if path == "mechanical.intent.currentStandardsLedger" or path.startswith("shared.rules."):
        return ALL_STANDARDS
    values = ["ISO 8015:2011", "ISO 14405-1:2025"]
    lowered = path.lower()
    if any(token in lowered for token in ("datum", "gdandt", "position", "coax", "perpendicular")):
        values += ["ISO 5459:2024", "ISO 1101:2017", "ISO 22081:2021"]
    if any(token in lowered for token in ("fit", "bearing", "tolerancestack", "thermal")):
        values += ["ISO 286-1:2010", "ISO 286-2:2010", "ISO 1:2022"]
    if "tolerance" in lowered:
        values += ["ISO 2768-1:1989", "ISO 22081:2021"]
    if "surface" in lowered or "finish" in lowered:
        values += ["ISO 21920-1:2021"]
    if "edge" in lowered or "deburr" in lowered:
        values += ["ISO 13715:2017"]
    if "fastener" in lowered or "joint" in lowered or "thread" in lowered:
        values += ["ISO 965-1:2026", "ISO 898-1:2013", "ISO 16047:2005+Amd 1:2012"]
    return list(dict.fromkeys(values))


def source_ids(path: str) -> list[str]:
    if ".intent." in path:
        return ["STD_AUTHORITY", "DESIGN_BASIS"]
    if ".design." in path:
        return ["STD_AUTHORITY", "DESIGN_BASIS", "ANALYSIS_BASIS"]
    if ".manufacturingDefinition." in path:
        return ["STD_AUTHORITY", "MFG_DEFINITION", "INSPECTION_PLAN"]
    return ["STD_AUTHORITY", "DESIGN_BASIS", "ANALYSIS_BASIS", "MFG_DEFINITION", "INSPECTION_PLAN"]


def verification(path: str) -> str:
    if ".intent." in path:
        return "Verify exact source hashes, requirement-contract bindings and standards-ledger identity before any geometry."
    if ".design." in path:
        return "Recompute analysis-basis equations, validate the constrained plan, inspect feature trace, and require native save/reopen geometry evidence."
    if ".manufacturingDefinition." in path:
        return "Cross-check manufacturing-definition and inspection-plan characteristic closure against the drawing and native model readback."
    return "Require independent requirement, constraint, drawing, native-host and evidence-contract gates; retain every authorization lock false."


def main() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload["contractId"] = "SIFC-220-REV-A-MECHANICAL-PREFLIGHT"
    payload["sources"] = SOURCE_ROWS
    for row in payload["applicableStandards"]:
        row["scopeDecision"] = (
            "Applicable to metric review-candidate generation of SIFC-220-REV-A within the stated "
            "GPS, fit, texture, edge, fastener or reference-temperature scope."
        )
    paths = {row["gatePath"] for row in payload["ruleApplications"]}
    if paths != set(CONSTRAINTS):
        raise SystemExit(
            "constraint inventory mismatch: "
            + json.dumps({"missing": sorted(paths - set(CONSTRAINTS)), "extra": sorted(set(CONSTRAINTS) - paths)})
        )
    for row in payload["ruleApplications"]:
        path = row["gatePath"]
        row["disposition"] = "constrained"
        row["generationConstraint"] = CONSTRAINTS[path]
        row["sourceIds"] = source_ids(path)
        row["standardIds"] = standard_ids(path)
        row["verificationMethod"] = verification(path)
    payload["conflicts"] = []
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "built", "output": str(OUTPUT), "gateCount": len(paths)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

