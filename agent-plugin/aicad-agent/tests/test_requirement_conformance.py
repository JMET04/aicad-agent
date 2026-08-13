from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_requirement_conformance.py"
SPEC = importlib.util.spec_from_file_location("aicad_requirement_conformance", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
}


def _template() -> dict:
    return {
        "profileId": "ECMA_A60_20_00_03",
        "productType": "folding_carton",
        "majorFeatures": ["top_tuck", "automatic_bottom"],
        "closureSystem": {
            "standard": "ECMA A60.20.00.03",
            "top": "tuck_in",
            "bottom": "automatic_2p_glued_crash_lock",
        },
    }


def _instance() -> dict:
    return {"values": {"B": 120.0}, "locks": dict(LOCKS)}


def _contract() -> dict:
    return {
        "schema": "aicad_drawing_requirement_contract_v1",
        "contractId": "REQ.TOP_TUCK_AUTO_BOTTOM.001",
        "revision": 1,
        "requestSummary": "Top tuck-in opening with a glued automatic crash-lock bottom.",
        "productType": "folding_carton",
        "useCase": "review candidate",
        "domain": "packaging",
        "deliveryStage": "review",
        "selectedRulePacks": ["normative_governance", "packaging"],
        "applicableStandards": [
            {"id": "STD.ECMA.A60", "title": "ECMA folding carton style", "edition": "fixture", "scope": "structure and closure", "sourceId": "STANDARD"}
        ],
        "units": "mm",
        "sources": [
            {
                "id": "USER",
                "kind": "user_explicit_semantic",
                "description": "User selected the default top-tuck/auto-bottom solution.",
                "dimensionalAuthority": False,
            },
            {
                "id": "ENGINEERING",
                "kind": "approved_engineering_input",
                "description": "Typed dimensions supplied by engineering input.",
                "dimensionalAuthority": True,
            },
            {
                "id": "STANDARD",
                "kind": "selected_standard",
                "description": "Selected structural standard.",
                "dimensionalAuthority": True,
            },
            {
                "id": "IMAGE",
                "kind": "reference_image",
                "description": "Topology and appearance reference only.",
                "dimensionalAuthority": False,
            },
        ],
        "authorityOrder": ["STANDARD", "ENGINEERING", "USER", "IMAGE"],
        "requirements": [
            {
                "id": "REQ.PRODUCT",
                "category": "overall_shape",
                "statement": "Generate a folding carton.",
                "priority": "hard",
                "sourceIds": ["USER"],
                "mustConfirm": False,
                "expected": {"kind": "exact", "value": "folding_carton"},
            },
            {
                "id": "REQ.STRUCTURE",
                "category": "structure_family",
                "statement": "Use the selected ECMA structure.",
                "priority": "hard",
                "sourceIds": ["USER", "STANDARD"],
                "mustConfirm": True,
                "expected": {"kind": "exact", "value": "ECMA_A60_20_00_03"},
            },
            {
                "id": "REQ.TOP",
                "category": "top_closure",
                "statement": "Top closure is tuck-in.",
                "priority": "hard",
                "sourceIds": ["USER", "STANDARD"],
                "mustConfirm": False,
                "expected": {"kind": "exact", "value": "tuck_in"},
            },
            {
                "id": "REQ.BOTTOM",
                "category": "bottom_closure",
                "statement": "Bottom closure is an automatic glued crash lock.",
                "priority": "hard",
                "sourceIds": ["USER", "STANDARD"],
                "mustConfirm": False,
                "expected": {"kind": "exact", "value": "automatic_2p_glued_crash_lock"},
            },
            {
                "id": "REQ.WIDTH",
                "category": "dimensions",
                "statement": "Body width is exactly 120 mm.",
                "priority": "hard",
                "sourceIds": ["ENGINEERING"],
                "mustConfirm": False,
                "expected": {"kind": "exact", "value": 120, "tolerance": 0.000001},
            },
        ],
        "assumptions": [],
        "conflicts": [],
        "requiredMajorFeatures": ["top_tuck", "automatic_bottom"],
        "allowedMajorFeatures": ["top_tuck", "automatic_bottom", "glue_seam"],
        "forbiddenMajorFeatures": ["mirrored_tuck_bottom"],
        "requiredOutputs": ["plan.json", "aicad", "scr", "dxf", "audit.md", "manifest.json"],
        "locks": dict(LOCKS),
    }


def _trace(contract: dict) -> dict:
    rows = []
    observations = {
        "REQ.PRODUCT": "folding_carton",
        "REQ.STRUCTURE": "ECMA_A60_20_00_03",
        "REQ.TOP": "tuck_in",
        "REQ.BOTTOM": "automatic_2p_glued_crash_lock",
        "REQ.WIDTH": 120.0,
    }
    bindings = {
        "REQ.PRODUCT": {
            "source": "normality_template",
            "transform": "identity",
            "jsonPointer": "/productType",
        },
        "REQ.STRUCTURE": {
            "source": "normality_template",
            "transform": "identity",
            "jsonPointer": "/profileId",
        },
        "REQ.TOP": {
            "source": "normality_template",
            "transform": "identity",
            "jsonPointer": "/closureSystem/top",
        },
        "REQ.BOTTOM": {
            "source": "normality_template",
            "transform": "identity",
            "jsonPointer": "/closureSystem/bottom",
        },
        "REQ.WIDTH": {
            "source": "normality_instance",
            "transform": "identity",
            "jsonPointer": "/values/B",
        },
    }
    for requirement in contract["requirements"]:
        method = "human_confirmation" if requirement["mustConfirm"] else "exact_value"
        rows.append(
            {
                "requirementId": requirement["id"],
                "status": "satisfied",
                "observed": observations[requirement["id"]],
                "actualBinding": bindings[requirement["id"]],
                "evidence": [
                    {
                        "method": method,
                        "sourcePath": f"design/{requirement['id']}",
                        "note": "Independent typed evidence for the actual design.",
                    }
                ],
            }
        )
    return {
        "schema": "aicad_drawing_requirement_trace_v1",
        "contractId": contract["contractId"],
        "contractSha256": MODULE.canonical_sha256(contract),
        "designIdentity": {
            "productType": "folding_carton",
            "structureFamily": "ECMA_A60_20_00_03",
            "standard": "ECMA A60.20.00.03",
            "topClosure": "tuck_in",
            "bottomClosure": "automatic_2p_glued_crash_lock",
            "units": "mm",
        },
        "requirementEvidence": rows,
        "declaredMajorFeatures": ["top_tuck", "automatic_bottom"],
        "dimensionSources": [
            {"dimensionId": "BODY_WIDTH", "sourceId": "ENGINEERING", "derivedFromImagePixels": False}
        ],
        "outputsPlanned": list(contract["requiredOutputs"]),
        "locks": dict(LOCKS),
    }


class RequirementConformanceTests(unittest.TestCase):
    def test_accepts_exact_whole_requirement_trace(self):
        contract = _contract()
        report = MODULE.evaluate(contract, _trace(contract), _template(), _instance())
        self.assertEqual(report["status"], "pass", report["failures"])
        self.assertTrue(all(report["checks"].values()))

    def test_rejects_wrong_structure_identity_even_with_green_line_evidence(self):
        contract = _contract()
        trace = _trace(contract)
        trace["designIdentity"]["bottomClosure"] = "tuck_in"
        report = MODULE.evaluate(contract, trace, _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["typedDesignIdentityMatchesContractAndTemplate"])
        self.assertIn("design_identity", {row["gate"] for row in report["failures"]})

    def test_rejects_missing_hard_requirement_evidence(self):
        contract = _contract()
        trace = _trace(contract)
        trace["requirementEvidence"] = [
            row for row in trace["requirementEvidence"] if row["requirementId"] != "REQ.BOTTOM"
        ]
        report = MODULE.evaluate(contract, trace, _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["everyHardRequirementIndependentlyProven"])

    def test_rejects_user_first_authority_order_before_selected_standard(self):
        contract = _contract()
        contract["authorityOrder"] = ["USER", "STANDARD", "ENGINEERING", "IMAGE"]
        report = MODULE.evaluate(contract, _trace(contract), _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["normativeRulesPrecedePreferencesReferencesAndGeometry"])
        self.assertFalse(report["normativeGate"]["nextStageAllowed"])

    def test_rejects_standard_governed_structure_without_standard_source(self):
        contract = _contract()
        structure = next(row for row in contract["requirements"] if row["id"] == "REQ.STRUCTURE")
        structure["sourceIds"] = ["USER"]
        report = MODULE.evaluate(contract, _trace(contract), _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["normativeRulesPrecedePreferencesReferencesAndGeometry"])

    def test_rejects_missing_domain_rule_pack(self):
        contract = _contract()
        contract["selectedRulePacks"] = ["normative_governance", "mechanical"]
        report = MODULE.evaluate(contract, _trace(contract), _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["normativeRulesPrecedePreferencesReferencesAndGeometry"])

    def test_rejects_cross_domain_drawing_standard_without_standard_binding(self):
        contract = _contract()
        trace = _trace(contract)
        contract["requirements"].append({
            "id": "REQ.DRAWING_STANDARD", "category": "drawing_standard",
            "statement": "Use the declared mechanical drawing standard.", "priority": "hard",
            "sourceIds": ["USER"], "mustConfirm": False,
            "expected": {"kind": "exact", "value": "ISO-128"},
        })
        report = MODULE.evaluate(contract, trace, _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["normativeRulesPrecedePreferencesReferencesAndGeometry"])

    def test_rejects_unconfirmed_high_impact_assumption(self):
        contract = _contract()
        contract["assumptions"].append(
            {
                "id": "ASM.CLOSURE",
                "statement": "Assume the bottom closure without user confirmation.",
                "impact": "high",
                "status": "disclosed",
                "sourceIds": ["USER"],
            }
        )
        trace = _trace(contract)
        report = MODULE.evaluate(contract, trace, _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["highImpactAssumptionsConfirmed"])

    def test_rejects_image_pixels_as_dimension_truth(self):
        contract = _contract()
        trace = _trace(contract)
        trace["dimensionSources"][0] = {
            "dimensionId": "BODY_WIDTH",
            "sourceId": "IMAGE",
            "derivedFromImagePixels": False,
        }
        report = MODULE.evaluate(contract, trace, _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["dimensionsUseAuthoritativeNonPixelSources"])

    def test_rejects_unrequested_major_feature(self):
        contract = _contract()
        trace = _trace(contract)
        trace["declaredMajorFeatures"].append("display_window")
        report = MODULE.evaluate(contract, trace, _template(), _instance())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["majorFeaturesAreRequiredOrExplicitlyAllowed"])

    def test_rejects_self_reported_dimension_when_actual_instance_differs(self):
        contract = _contract()
        trace = _trace(contract)
        instance = _instance()
        instance["values"]["B"] = 121.0
        report = MODULE.evaluate(contract, trace, _template(), instance)
        self.assertEqual(report["status"], "failed")
        width = next(row for row in report["hardRequirementResults"] if row["requirementId"] == "REQ.WIDTH")
        self.assertTrue(width["independentComparisonPass"])
        self.assertFalse(width["bindingMatchesObserved"])

    def test_schemas_accept_valid_contract_and_trace(self):
        contract = _contract()
        trace = _trace(contract)
        contract_schema = json.loads(
            (ROOT / "rules" / "drawing_requirement_contract.schema.json").read_text(encoding="utf-8")
        )
        trace_schema = json.loads(
            (ROOT / "rules" / "drawing_requirement_trace.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(contract_schema).validate(contract)
        jsonschema.Draft202012Validator(trace_schema).validate(trace)

    def test_active_root_cause_and_prevention_text_is_stable_utf8_without_mojibake(self):
        source = SCRIPT.read_text(encoding="utf-8")
        source.encode("utf-8").decode("utf-8")
        for root_cause, prevention in MODULE.ROOT_CAUSES.values():
            self.assertTrue(root_cause.isascii(), root_cause)
            self.assertTrue(prevention.isascii(), prevention)
        bad_sequences = (
            "".join(map(chr, (0x00E7, 0x201D, 0x0178))),
            "".join(map(chr, (0x00E9, 0x0153, 0x20AC))),
            "".join(map(chr, (0x00E5, 0x00A5, 0x2018))),
            chr(0x9225),
        )
        for token in bad_sequences:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
