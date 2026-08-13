from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "scripts" / "aicad_engineering_preflight.py"
SPEC = importlib.util.spec_from_file_location("aicad_engineering_preflight", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot import engineering normative preflight")
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


def valid_contract(domain: str) -> dict:
    contract = PREFLIGHT.build_template(domain)
    first_standard = contract["applicableStandards"][0]["standard"]
    for row in contract["ruleApplications"]:
        row["disposition"] = "constrained"
        row["generationConstraint"] = f"Generate only after resolving {row['gatePath']} from controlled inputs."
        row["verificationMethod"] = f"Recompute and independently verify {row['gatePath']} before artifact exposure."
        row["standardIds"] = [first_standard]
    return contract


class EngineeringNormativePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = json.loads((PLUGIN / "rules" / "production_readiness_rules.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((PLUGIN / "rules" / "engineering_normative_preflight.schema.json").read_text(encoding="utf-8"))

    def test_mechanical_and_electronics_positive_contracts_pass_without_readiness_overclaim(self) -> None:
        expected = {"mechanical": 54, "electronics": 63}
        for domain, gate_count in expected.items():
            with self.subTest(domain=domain):
                contract = valid_contract(domain)
                Draft202012Validator(self.schema).validate(contract)
                report = PREFLIGHT.evaluate(contract)
                self.assertEqual(report["status"], "pass", report)
                self.assertEqual(report["counts"]["canonicalGates"], gate_count)
                self.assertEqual(report["counts"]["contractGates"], gate_count)
                self.assertEqual(report["conclusion"], "normative_preflight_ready_for_controlled_generation_only")
                self.assertTrue(report["generationGate"]["nextStageAllowed"])
                self.assertFalse(report["generationGate"]["artifactExposureAllowed"])
                self.assertEqual(
                    report["readinessBoundary"],
                    {
                        "evidenceContractReady": False,
                        "technicalPackageReady": False,
                        "productionReleaseEligible": False,
                        "manufacturingAuthorized": False,
                        "fabricationAuthorized": False,
                    },
                )

    def test_template_is_exact_but_unresolved_and_fails_closed(self) -> None:
        for domain in ("mechanical", "electronics"):
            with self.subTest(domain=domain):
                draft = PREFLIGHT.build_template(domain)
                report = PREFLIGHT.evaluate(draft)
                self.assertEqual(report["status"], "failed")
                self.assertFalse(report["generationGate"]["nextStageAllowed"])
                unresolved = report["failures"][0]["details"] if report["failures"][0]["code"] == "schema_invalid" else None
                self.assertIsNone(unresolved)
                gate_failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
                self.assertEqual(len(gate_failure["details"]["unresolved"]), len(draft["ruleApplications"]))

    def test_every_canonical_generation_gate_has_an_individual_missing_gate_regression(self) -> None:
        for domain in ("mechanical", "electronics"):
            baseline = valid_contract(domain)
            for index, application in enumerate(baseline["ruleApplications"]):
                with self.subTest(domain=domain, gate=application["gatePath"]):
                    candidate = copy.deepcopy(baseline)
                    del candidate["ruleApplications"][index]
                    report = PREFLIGHT.evaluate(candidate)
                    self.assertEqual(report["status"], "failed")
                    failure = next(item for item in report["failures"] if item["code"] == "gate_inventory_mismatch")
                    self.assertEqual(failure["details"]["missing"], [application["gatePath"]])

    def test_duplicate_extra_and_cross_domain_gate_paths_fail_exact_inventory(self) -> None:
        contract = valid_contract("mechanical")
        contract["ruleApplications"].append(copy.deepcopy(contract["ruleApplications"][0]))
        report = PREFLIGHT.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_inventory_mismatch")
        self.assertEqual(failure["details"]["duplicates"], [contract["ruleApplications"][0]["gatePath"]])

        contract = valid_contract("mechanical")
        contract["ruleApplications"][0]["gatePath"] = "electronics.intent.wholeIntent"
        report = PREFLIGHT.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_inventory_mismatch")
        self.assertEqual(failure["details"]["extra"], ["electronics.intent.wholeIntent"])

    def test_intent_cannot_be_not_applicable_but_a_design_gate_can_with_authority(self) -> None:
        contract = valid_contract("mechanical")
        shared = next(row for row in contract["ruleApplications"] if row["gatePath"].startswith("shared.rules."))
        shared["disposition"] = "not_applicable"
        shared["notApplicableRationale"] = "Attempted waiver"
        shared.pop("generationConstraint")
        report = PREFLIGHT.evaluate(contract)
        self.assertIn("gate_application_invalid", [item["code"] for item in report["failures"]])

        contract = valid_contract("mechanical")
        intent = next(row for row in contract["ruleApplications"] if ".intent." in row["gatePath"])
        intent["disposition"] = "not_applicable"
        intent["notApplicableRationale"] = "Attempted waiver"
        intent.pop("generationConstraint")
        report = PREFLIGHT.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
        self.assertEqual(failure["details"]["intentMarkedNotApplicable"], [intent["gatePath"]])

        contract = valid_contract("mechanical")
        fatigue = next(row for row in contract["ruleApplications"] if row["gatePath"].endswith(".fatigueApplicabilityAndResult"))
        fatigue["disposition"] = "not_applicable"
        fatigue["notApplicableRationale"] = "Approved engineering input proves no cyclic duty in the declared life envelope."
        fatigue.pop("generationConstraint")
        self.assertEqual(PREFLIGHT.evaluate(contract)["status"], "pass")

    def test_missing_standard_wrong_standard_source_and_version_drift_fail(self) -> None:
        contract = valid_contract("electronics")
        removed = contract["applicableStandards"].pop()
        report = PREFLIGHT.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "standards_ledger_incomplete")
        self.assertIn((removed["standard"], removed["applicability"]), map(tuple, failure["details"]["missing"]))

        contract = valid_contract("electronics")
        contract["applicableStandards"][0]["sourceId"] = "ENG_INPUT"
        report = PREFLIGHT.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "standards_ledger_incomplete")
        self.assertEqual(failure["details"]["invalidStandardSource"], [contract["applicableStandards"][0]["standard"]])

        contract = valid_contract("electronics")
        contract["canonicalRulesVersion"] = "999.0.0"
        report = PREFLIGHT.evaluate(contract)
        self.assertIn("canonical_rules_identity_mismatch", [item["code"] for item in report["failures"]])

    def test_reference_only_binding_unknown_standard_unresolved_conflict_and_open_lock_fail(self) -> None:
        contract = valid_contract("mechanical")
        contract["sources"].append({"id": "IMG", "kind": "reference_image", "description": "Visual reference only"})
        row = contract["ruleApplications"][0]
        row["sourceIds"] = ["IMG"]
        row["standardIds"] = ["UNKNOWN-EDITION"]
        contract["conflicts"] = [{"id": "C1", "sourceIds": ["IMG", "ENG_INPUT"], "status": "unresolved"}]
        report = PREFLIGHT.evaluate(contract)
        gate_failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
        self.assertEqual(gate_failure["details"]["missingAuthoritativeSourceBinding"], [row["gatePath"]])
        self.assertEqual(gate_failure["details"]["unknownStandardReferences"], [f"{row['gatePath']}:UNKNOWN-EDITION"])
        self.assertIn("unresolved_source_conflict", [item["code"] for item in report["failures"]])

        contract = valid_contract("mechanical")
        contract["locks"]["manufacturingAuthorized"] = True
        report = PREFLIGHT.evaluate(contract)
        self.assertFalse(report["checks"]["schemaValid"])
        self.assertFalse(report["generationGate"]["nextStageAllowed"])

    def test_rule_inventory_declares_one_canonical_preflight_not_a_second_rule_catalog(self) -> None:
        policy = self.rules["generationPreflightPolicy"]
        self.assertEqual(policy["canonicalProfileByDomain"], {
            "mechanical": "mechanicalManufacturingProfileV3",
            "electronics": "electronicsFabricationProfileV3",
        })
        self.assertEqual(policy["includedSections"], ["intent", "design", "manufacturingDefinition"])
        self.assertEqual(policy["sharedRuleIds"], ["PROD-G001", "PROD-G002", "PROD-G003", "PROD-G004", "PROD-G005", "PROD-G006", "PROD-G013"])
        self.assertTrue(policy["exactGateInventoryRequired"])
        self.assertFalse(policy["technicalReadinessGranted"])
        self.assertFalse(policy["artifactExposureGranted"])
        self.assertFalse((PLUGIN / "rules" / "mechanical_rules_duplicate.json").exists())
        self.assertFalse((PLUGIN / "rules" / "electronics_rules_duplicate.json").exists())


if __name__ == "__main__":
    unittest.main()
