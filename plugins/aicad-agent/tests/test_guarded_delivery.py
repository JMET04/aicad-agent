from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


NORMALITY_FIXTURE = _load(
    "normality_fixture_for_guarded_delivery",
    ROOT / "tests" / "test_normality_prover.py",
)
REQUIREMENT_FIXTURE = _load(
    "requirement_fixture_for_guarded_delivery",
    ROOT / "tests" / "test_requirement_conformance.py",
)
DELIVERY = _load(
    "aicad_guarded_delivery_under_test",
    ROOT / "scripts" / "aicad_guarded_delivery.py",
)


def _macro_for_template(template: dict, instance: dict) -> tuple[dict, dict]:
    contract = REQUIREMENT_FIXTURE._contract()
    closure = template["closureSystem"]
    contract["contractId"] = "REQ.GUARDED.PIPELINE.001"
    replacements = {
        "REQ.STRUCTURE": template["profileId"],
        "REQ.TOP": closure["top"],
        "REQ.BOTTOM": closure["bottom"],
        "REQ.WIDTH": instance["values"]["W"],
    }
    for requirement in contract["requirements"]:
        if requirement["id"] in replacements:
            requirement["expected"]["value"] = replacements[requirement["id"]]
    trace = REQUIREMENT_FIXTURE._trace(contract)
    width_row = next(row for row in trace["requirementEvidence"] if row["requirementId"] == "REQ.WIDTH")
    width_row["actualBinding"] = {
        "source": "normality_instance",
        "transform": "identity",
        "jsonPointer": "/values/W",
    }
    trace["designIdentity"].update(
        {
            "structureFamily": template["profileId"],
            "standard": closure["standard"],
            "topClosure": closure["top"],
            "bottomClosure": closure["bottom"],
        }
    )
    for row in trace["requirementEvidence"]:
        if row["requirementId"] in replacements:
            row["observed"] = replacements[row["requirementId"]]
    trace["contractSha256"] = REQUIREMENT_FIXTURE.MODULE.canonical_sha256(contract)
    return contract, trace


def _write_payload(root: Path, payload: tuple[dict, dict, dict, dict]) -> dict[str, Path]:
    plan, geometry, template, instance = payload
    paths = {
        "plan": root / "fixture.plan.json",
        "geometry": root / "geometry.json",
        "template": root / "template.json",
        "instance": root / "instance.json",
    }
    for key, data in zip(("plan", "geometry", "template", "instance"), payload):
        paths[key].write_text(json.dumps(data), encoding="utf-8")
    contract, trace = _macro_for_template(template, instance)
    paths["contract"] = root / "contract.json"
    paths["trace"] = root / "trace.json"
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    paths["trace"].write_text(json.dumps(trace), encoding="utf-8")
    return paths


class GuardedDeliveryTests(unittest.TestCase):
    def test_macro_failure_blocks_detail_read_and_creates_no_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = NORMALITY_FIXTURE._payload()
            paths = _write_payload(root, payload)
            trace = json.loads(paths["trace"].read_text(encoding="utf-8"))
            trace["designIdentity"]["bottomClosure"] = "tuck_in"
            paths["trace"].write_text(json.dumps(trace), encoding="utf-8")
            paths["plan"].unlink()
            output = root / "candidate"
            report = DELIVERY.run_pipeline(
                paths["contract"],
                paths["trace"],
                paths["plan"],
                paths["geometry"],
                paths["template"],
                paths["instance"],
                output,
                root / "reports",
                "macro_block",
            )
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["stages"][1]["status"], "blocked_by_previous_stage")
            self.assertFalse(report["candidateArtifactsBuilt"])
            self.assertFalse(output.exists())

    def test_detail_failure_blocks_artifact_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _write_payload(root, NORMALITY_FIXTURE._payload(waist=True))
            output = root / "candidate"
            report = DELIVERY.run_pipeline(
                paths["contract"],
                paths["trace"],
                paths["plan"],
                paths["geometry"],
                paths["template"],
                paths["instance"],
                output,
                root / "reports",
                "detail_block",
            )
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["stages"][0]["status"], "pass")
            self.assertEqual(report["stages"][1]["status"], "failed")
            self.assertEqual(report["stages"][2]["status"], "blocked_by_previous_stage")
            self.assertFalse(output.exists())

    def test_all_gates_pass_before_candidate_artifacts_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _write_payload(root, NORMALITY_FIXTURE._payload())
            output = root / "candidate"
            report = DELIVERY.run_pipeline(
                paths["contract"],
                paths["trace"],
                paths["plan"],
                paths["geometry"],
                paths["template"],
                paths["instance"],
                output,
                root / "reports",
                "guarded_fixture",
            )
            self.assertEqual(report["status"], "pass", report.get("failureExplanation"))
            self.assertTrue(report["candidateArtifactsBuilt"])
            self.assertEqual([row["status"] for row in report["stages"]], ["pass", "pass", "pass"])
            self.assertEqual(
                {row["kind"] for row in report["artifacts"]},
                {"plan.json", "aicad", "scr", "dxf", "audit.md", "manifest.json"},
            )
            self.assertTrue(all(Path(row["path"]).is_file() for row in report["artifacts"]))
            self.assertEqual(report["artifactSetSha256"], report["stages"][2]["artifactSetSha256"])


if __name__ == "__main__":
    unittest.main()
