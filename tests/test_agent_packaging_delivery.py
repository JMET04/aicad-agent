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


AGENT = _load("aicad_agent_packaging_surface", PLUGIN / "scripts" / "aicad_agent.py")
FIXTURE = _load(
    "guarded_delivery_fixture_for_agent_surface",
    PLUGIN / "tests" / "test_guarded_delivery.py",
)


class AgentPackagingDeliveryTests(unittest.TestCase):
    def test_tool_and_cli_expose_exact_guarded_inputs(self) -> None:
        tool = next(
            row for row in AGENT.TOOLS
            if row["name"] == "aicad_guarded_packaging_delivery"
        )
        self.assertEqual(
            tool["inputSchema"]["required"],
            ["contract", "trace", "plan", "geometry", "template", "instance"],
        )
        args = AGENT._parser().parse_args([
            "guarded-packaging-delivery",
            "--contract", "contract.json",
            "--trace", "trace.json",
            "--plan", "plan.json",
            "--geometry", "geometry.json",
            "--template", "template.json",
            "--instance", "instance.json",
        ])
        self.assertEqual(args.command, "guarded-packaging-delivery")

    def test_mcp_pass_writes_hash_bound_candidate_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = FIXTURE._write_payload(root, FIXTURE.NORMALITY_FIXTURE._payload())
            output = root / "candidate"
            reports = root / "reports"
            result = AGENT._dispatch_tool(
                "aicad_guarded_packaging_delivery",
                {
                    **{key: str(value) for key, value in paths.items()},
                    "output_dir": str(output),
                    "report_dir": str(reports),
                    "name": "agent-packaging",
                },
            )
            self.assertTrue(result["ok"], result.get("failureExplanation"))
            self.assertTrue(result["candidateArtifactsBuilt"])
            self.assertEqual([row["status"] for row in result["stages"]], ["pass", "pass", "pass"])
            self.assertTrue(Path(result["reportJson"]).is_file())
            self.assertTrue(Path(result["reportMarkdown"]).is_file())
            self.assertEqual(
                json.loads(Path(result["reportJson"]).read_text(encoding="utf-8"))["artifactSetSha256"],
                result["artifactSetSha256"],
            )
            self.assertTrue(output.is_dir())

    def test_mcp_macro_failure_exposes_reports_but_no_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = FIXTURE._write_payload(root, FIXTURE.NORMALITY_FIXTURE._payload())
            trace = json.loads(paths["trace"].read_text(encoding="utf-8"))
            trace["designIdentity"]["bottomClosure"] = "tuck_in"
            paths["trace"].write_text(json.dumps(trace), encoding="utf-8")
            output = root / "candidate"
            result = AGENT._dispatch_tool(
                "aicad_guarded_packaging_delivery",
                {
                    **{key: str(value) for key, value in paths.items()},
                    "output_dir": str(output),
                    "report_dir": str(root / "reports"),
                },
            )
            self.assertFalse(result["ok"])
            self.assertFalse(result["candidateArtifactsBuilt"])
            self.assertEqual(result["stages"][1]["status"], "blocked_by_previous_stage")
            self.assertFalse(output.exists())
            self.assertTrue(Path(result["reportJson"]).is_file())


if __name__ == "__main__":
    unittest.main()
