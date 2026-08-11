from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_production_readiness_qa_v2.py"
SPEC = importlib.util.spec_from_file_location("aicad_production_readiness_qa_v2", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)
PROFILE = json.loads((ROOT / "rules" / "production_readiness_rules.json").read_text(encoding="utf-8"))["architectureProductionProfile"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProductionReadinessV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.artifact = self.root / "drawing.dwg"
        self.artifact.write_bytes(b"verified dwg fixture")
        artifact_row = {
            "kind": "dwg", "path": str(self.artifact), "exists": True,
            "sizeBytes": self.artifact.stat().st_size, "declaredSha256": sha(self.artifact),
            "actualSha256": sha(self.artifact), "pass": True,
        }
        artifact_set_sha = QA._artifact_set_sha([artifact_row])
        machine = {"gates": {}, "artifactSetSha256": artifact_set_sha}
        for group, names in PROFILE.items():
            if group in {"authority", "professionalRelease"}:
                continue
            machine["gates"][group] = {name: True for name in names}
        self.machine = self.root / "machine-report.json"
        self.machine.write_text(json.dumps(machine), encoding="utf-8")
        self.authority = self.root / "authority-evidence.pdf"
        self.authority.write_bytes(b"authority fixture")
        self.release = self.root / "professional-release.pdf"
        self.release.write_bytes(b"professional release fixture")
        evidence: dict[str, dict[str, object]] = {}
        for group, names in PROFILE.items():
            evidence[group] = {}
            for name in names:
                if group == "authority":
                    ref = {
                        "kind": "authority_document", "path": str(self.authority), "sha256": sha(self.authority),
                        "issuer": "Fixture authority", "scope": name, "issuedAt": "2026-08-12",
                    }
                elif group == "professionalRelease":
                    ref = {
                        "kind": "professional_release", "path": str(self.release), "sha256": sha(self.release),
                        "signer": "Fixture professional", "credential": "TEST-ONLY", "scope": name,
                        "subjectArtifactSetSha256": artifact_set_sha,
                    }
                else:
                    ref = {
                        "kind": "machine_report", "path": str(self.machine), "sha256": sha(self.machine),
                        "jsonPointer": f"/gates/{group}/{name}", "expectedValue": True,
                    }
                    if group == "host":
                        ref["artifactSetPointer"] = "/artifactSetSha256"
                evidence[group][name] = {"evidenceRef": ref}
        self.contract = {
            "schema": "aicad_production_readiness_contract_v2",
            "project": {"id": "fixture-house", "title": "Fixture house"},
            "requestedStage": "production",
            "discipline": "architecture",
            "strictProductionOnly": True,
            "evidence": evidence,
            "candidateArtifacts": [{"kind": "dwg", "path": str(self.artifact), "sha256": sha(self.artifact)}],
            "safetyLocks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_and_evidence_bound_fixture_pass(self) -> None:
        schema = json.loads((ROOT / "rules" / "production_readiness_contract_v2.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.contract)
        result = QA.evaluate(self.contract, self.root)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["productionArtifactAllowed"])
        self.assertEqual(len(result["exposedArtifacts"]), 1)

    def test_old_self_reported_boolean_contract_is_rejected(self) -> None:
        payload = copy.deepcopy(self.contract)
        payload["evidence"]["drafting"]["axisIdentifiers"] = {"passed": True, "evidence": "looks good"}
        with self.assertRaises(ValidationError):
            QA.evaluate(payload, self.root)

    def test_tampered_machine_report_blocks_all_artifact_exposure(self) -> None:
        self.machine.write_text("{}", encoding="utf-8")
        result = QA.evaluate(self.contract, self.root)
        self.assertEqual(result["status"], "blocked_for_production")
        self.assertFalse(result["productionArtifactAllowed"])
        self.assertEqual(result["exposedArtifacts"], [])

    def test_host_report_must_bind_same_artifact_set(self) -> None:
        machine = json.loads(self.machine.read_text(encoding="utf-8"))
        machine["artifactSetSha256"] = "0" * 64
        self.machine.write_text(json.dumps(machine), encoding="utf-8")
        new_hash = sha(self.machine)
        for record in self.contract["evidence"]["host"].values():
            record["evidenceRef"]["sha256"] = new_hash
        result = QA.evaluate(self.contract, self.root)
        self.assertTrue(any("host." in name for name in result["failedGates"]))
        self.assertEqual(result["deliveryDisposition"], "blocker_report_only")

    def test_professional_release_must_bind_same_artifact_set(self) -> None:
        payload = copy.deepcopy(self.contract)
        first = next(iter(payload["evidence"]["professionalRelease"].values()))
        first["evidenceRef"]["subjectArtifactSetSha256"] = "f" * 64
        result = QA.evaluate(payload, self.root)
        self.assertTrue(any("professionalRelease." in name for name in result["failedGates"]))
        self.assertEqual(result["exposedArtifacts"], [])

    def test_candidate_artifact_hash_mismatch_blocks_release(self) -> None:
        payload = copy.deepcopy(self.contract)
        payload["candidateArtifacts"][0]["sha256"] = "a" * 64
        result = QA.evaluate(payload, self.root)
        self.assertIn("artifacts.hashAndExistence", result["failedGates"])
        self.assertFalse(result["productionArtifactAllowed"])


if __name__ == "__main__":
    unittest.main()
