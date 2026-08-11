from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_production_readiness_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_production_readiness_qa", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


PROFILE = json.loads((ROOT / "rules" / "production_readiness_rules.json").read_text(encoding="utf-8"))["architectureProductionProfile"]


def contract(passed: bool = True) -> dict:
    evidence = {}
    for group, names in PROFILE.items():
        evidence[group] = {name: {"passed": passed, "evidence": f"fixture:{group}.{name}"} for name in names}
    return {
        "schema": "aicad_production_readiness_contract_v1",
        "project": {"id": "fixture-house", "title": "Fixture house"},
        "requestedStage": "production",
        "discipline": "architecture",
        "strictProductionOnly": True,
        "evidence": evidence,
        "candidateArtifacts": [{"kind": "script", "path": str(SCRIPT), "sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest()}],
        "safetyLocks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


class ProductionReadinessRulesTests(unittest.TestCase):
    def test_all_gates_create_release_candidate_but_not_auto_acceptance(self) -> None:
        result = QA.evaluate(contract())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["deliveryDisposition"], "production_release_candidate")
        self.assertTrue(result["productionArtifactAllowed"])
        self.assertFalse(result["automaticAcceptanceAllowed"])
        self.assertFalse(result["safetyLocks"]["accepted"])

    def test_missing_axis_identifier_blocks_all_artifact_exposure(self) -> None:
        payload = contract()
        payload["evidence"]["drafting"]["axisIdentifiers"] = {"passed": False, "evidence": "missing bubbles and labels"}
        result = QA.evaluate(payload)
        self.assertEqual(result["status"], "blocked_for_production")
        self.assertEqual(result["deliveryDisposition"], "blocker_report_only")
        self.assertFalse(result["productionArtifactAllowed"])
        self.assertEqual(result["exposedArtifacts"], [])
        self.assertIn("drafting.axisIdentifiers", result["failedGates"])
        self.assertEqual(result["rootCauseLessons"][0]["ruleId"], "PROD-G001")

    def test_review_stage_remains_review_candidate(self) -> None:
        payload = contract(False)
        payload["requestedStage"] = "review"
        result = QA.evaluate(payload)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["deliveryDisposition"], "review_candidate")
        self.assertFalse(result["productionArtifactAllowed"])
        self.assertEqual(len(result["exposedArtifacts"]), 1)


if __name__ == "__main__":
    unittest.main()
