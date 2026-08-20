from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "agent-plugin" / "aicad-agent"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(PLUGIN / "scripts"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AGENT = _load("aicad_agent_civil_integration", PLUGIN / "scripts" / "aicad_agent.py")
FIXTURE = _load("aicad_civil_fixture_for_agent", ROOT / "tests" / "test_civil_review_candidate.py")


def _civil_plan(evidence_root: Path) -> tuple[dict, Path]:
    plan = json.loads((ROOT / "examples" / "arc.plan.json").read_text(encoding="utf-8"))
    plan["drawing"]["domain"] = "civil"
    plan["civil_review_candidate"] = FIXTURE.valid_candidate(evidence_root)
    plan_path = evidence_root / "civil.plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return plan, plan_path


class AgentCivilIntegrationTests(unittest.TestCase):
    def test_schema_registry_mcp_and_cli_surface(self) -> None:
        schema = AGENT.get_civil_review_candidate_schema()
        self.assertTrue(schema["ok"])
        self.assertEqual(
            schema["schema"]["title"],
            "AICAD civil engineering constrained review candidate",
        )
        registry = AGENT.get_engineering_domain_registry()["registry"]
        self.assertEqual(registry["domains"]["civil"]["maturity"], "constrained")
        self.assertIn("aicad_validate_civil_review_candidate", registry["domains"]["civil"]["validators"])
        args = AGENT._parser().parse_args([
            "civil-review-validate", "--candidate", "civil.json", "--evidence-root", "evidence",
        ])
        self.assertEqual(args.command, "civil-review-validate")
        names = {row["name"] for row in AGENT.TOOLS}
        self.assertIn("aicad_get_civil_review_candidate_schema", names)
        self.assertIn("aicad_validate_civil_review_candidate", names)

    def test_source_bound_civil_plan_passes_only_as_review_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            _, plan_path = _civil_plan(evidence_root)
            result = AGENT.validate_plan_value(str(plan_path))
            self.assertTrue(result["ok"])
            self.assertEqual(result["civil_review_validation"]["status"], "review_candidate")
            self.assertEqual(result["civil_review_validation"]["authorizedOutput"], "review_candidate")
            self.assertIn(
                result["domain_validation"]["status"],
                {"passed", "passed_with_warnings"},
            )
            self.assertFalse(
                result["civil_review_validation"]["releaseBoundary"][
                    "productionArtifactExposureGranted"
                ]
            )

    def test_generic_civil_geometry_and_missing_evidence_root_fail_closed(self) -> None:
        from aicad.domain_rules import evaluate_domain_plan
        from aicad.engine import PlanError

        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            plan, _ = _civil_plan(evidence_root)
            generic = dict(plan)
            generic.pop("civil_review_candidate")
            report = evaluate_domain_plan(generic, "2d", "civil")
            self.assertEqual(report["status"], "failed")
            gate = next(row for row in report["checks"] if row["id"] == "DOMAIN.G000")
            self.assertTrue(gate["evidence"]["specialist_generation_blocked"])
            with self.assertRaisesRegex(PlanError, "evidence_root"):
                AGENT.validate_plan_value(plan)

    def test_tampered_civil_evidence_blocks_before_artifact_directory(self) -> None:
        from aicad.engine import PlanError

        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            plan, plan_path = _civil_plan(evidence_root)
            source = evidence_root.joinpath(
                *Path(plan["civil_review_candidate"]["sources"][0]["path"]).parts
            )
            source.write_bytes(source.read_bytes() + b"tampered")
            output = evidence_root / "must-not-exist"
            with self.assertRaisesRegex(PlanError, "civil constrained precompile gate failed"):
                AGENT.compile_plan_value(str(plan_path), str(output), "civil")
            self.assertFalse(output.exists())

    def test_candidate_tool_defaults_file_input_to_parent_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            candidate = FIXTURE.valid_candidate(evidence_root)
            candidate_path = evidence_root / "civil-candidate.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            result = AGENT._dispatch_tool(
                "aicad_validate_civil_review_candidate",
                {"candidate": str(candidate_path)},
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["status"], "review_candidate")


if __name__ == "__main__":
    unittest.main()
