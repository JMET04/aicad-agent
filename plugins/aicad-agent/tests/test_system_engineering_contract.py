from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PLUGIN_ROOT / "scripts" / "aicad_system_engineering_qa.py"
SCHEMA_PATH = PLUGIN_ROOT / "rules" / "system_engineering_contract.schema.json"


def load_module():
    spec = importlib.util.spec_from_file_location("aicad_system_engineering_qa", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence_row(root: Path) -> dict[str, object]:
    payload = root / "evidence.txt"
    payload.write_text("verified evidence\n", encoding="utf-8")
    data = payload.read_bytes()
    return {
        "id": "E-TOOL",
        "path": "evidence.txt",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "level": "tool_verified",
        "toolVersion": "test-1.0",
    }


def valid_contract(root: Path) -> dict[str, object]:
    return {
        "schema": "aicad.system-engineering-contract.v1",
        "systemId": "TEST-SYSTEM",
        "revision": "A",
        "intendedUse": "Cross-domain contract regression.",
        "prohibitedUses": ["Production release from this fixture."],
        "requirements": [{
            "id": "SYS-001",
            "statement": "The mechanical and electronic interfaces shall agree.",
            "verificationMethod": "Bound interface evidence.",
            "subsystemIds": ["MECH", "ELEC"],
            "gateIds": ["G-ICD"],
            "status": "tool_verified",
        }],
        "subsystems": [
            {"id": "MECH", "domain": "mechanical", "scope": "Enclosure", "artifactIds": ["A-STEP"], "status": "tool_verified"},
            {"id": "ELEC", "domain": "electronics", "scope": "PCB", "artifactIds": ["A-PCB"], "status": "tool_verified"},
        ],
        "artifacts": [
            {"id": "A-STEP", "subsystemId": "MECH", "kind": "step", "path": "enclosure.step", "evidenceLevel": "tool_verified", "evidenceIds": ["E-TOOL"]},
            {"id": "A-PCB", "subsystemId": "ELEC", "kind": "pcb", "path": "board.kicad_pcb", "evidenceLevel": "tool_verified", "evidenceIds": ["E-TOOL"]},
        ],
        "interfaces": [{
            "id": "ICD-PCB-CASE",
            "kind": "mechanical",
            "providerSubsystemId": "ELEC",
            "consumerSubsystemId": "MECH",
            "contract": "PCB origin and mount axes are frozen.",
            "parameters": [{"name": "board_width", "value": 15.0, "unit": "mm", "tolerance": 0.1, "authority": "A-PCB"}],
            "verificationGateIds": ["G-ICD"],
        }],
        "flows": [{
            "id": "FLOW-SIGNAL",
            "type": "signal",
            "orderedSubsystemIds": ["ELEC", "MECH"],
            "interfaceIds": ["ICD-PCB-CASE"],
            "failureState": "Block assembly.",
        }],
        "verificationGates": [{
            "id": "G-ICD",
            "requirementIds": ["SYS-001"],
            "requiredEvidenceLevel": "tool_verified",
            "verification": "Hash and interface consistency check.",
            "status": "passed",
            "evidenceIds": ["E-TOOL"],
        }],
        "changeImpacts": [{
            "sourceId": "ICD-PCB-CASE",
            "impactedIds": ["A-STEP", "A-PCB", "FLOW-SIGNAL"],
            "requiredRechecks": ["G-ICD"],
        }],
        "evidenceBindings": [evidence_row(root)],
        "authorizations": {"prototypeBuild": True, "productionRelease": False, "notes": "Fixture only."},
        "releaseLocks": {"reviewOnly": True, "technicalReady": False, "physicalVerified": False, "productionReleaseEligible": False},
    }


def error_codes(report: dict[str, object]) -> set[str]:
    return {item["code"] for item in report["errors"]}  # type: ignore[index]


class SystemEngineeringContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def with_root(self):
        return tempfile.TemporaryDirectory()

    def test_schema_is_valid_json_and_declares_v1(self):
        value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            value["properties"]["schema"]["const"],
            "aicad.system-engineering-contract.v1",
        )
        self.assertEqual(value["properties"]["subsystems"]["minItems"], 2)

    def test_valid_cross_domain_contract_passes(self):
        with self.with_root() as temporary:
            root = Path(temporary)
            report = self.module.validate_contract(valid_contract(root), root)
            self.assertTrue(report["ok"])
            self.assertTrue(report["systemContractReady"])
            self.assertFalse(report["productionReleaseEligible"])
            self.assertEqual(report["warnings"], [])

    def test_missing_interface_change_impact_fails(self):
        with self.with_root() as temporary:
            root = Path(temporary)
            contract = valid_contract(root)
            contract["changeImpacts"] = []
            report = self.module.validate_contract(contract, root)
            self.assertFalse(report["ok"])
            self.assertIn("SYS-IMPACT-006", error_codes(report))

    def test_tampered_evidence_fails(self):
        with self.with_root() as temporary:
            root = Path(temporary)
            contract = valid_contract(root)
            (root / "evidence.txt").write_text("tampered\n", encoding="utf-8")
            report = self.module.validate_contract(contract, root)
            self.assertFalse(report["ok"])
            self.assertTrue({"SYS-EVID-006", "SYS-EVID-007"} & error_codes(report))

    def test_open_gate_cannot_claim_production_release(self):
        with self.with_root() as temporary:
            root = Path(temporary)
            contract = copy.deepcopy(valid_contract(root))
            contract["verificationGates"][0]["status"] = "open"  # type: ignore[index]
            contract["authorizations"]["productionRelease"] = True  # type: ignore[index]
            contract["releaseLocks"]["productionReleaseEligible"] = True  # type: ignore[index]
            report = self.module.validate_contract(contract, root)
            self.assertFalse(report["ok"])
            self.assertIn("SYS-RELEASE-001", error_codes(report))

    def test_interface_must_cross_subsystems(self):
        with self.with_root() as temporary:
            root = Path(temporary)
            contract = valid_contract(root)
            contract["interfaces"][0]["consumerSubsystemId"] = "ELEC"  # type: ignore[index]
            report = self.module.validate_contract(contract, root)
            self.assertFalse(report["ok"])
            self.assertIn("SYS-ICD-002", error_codes(report))


if __name__ == "__main__":
    unittest.main()
