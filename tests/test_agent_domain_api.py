from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"


def load_agent():
    spec = importlib.util.spec_from_file_location("aicad_agent_domain_api", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentDomainApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent()

    def plan3d(self) -> dict:
        value = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        value["part"]["domain"] = "mechanical"
        for feature, role in zip(value["features"], ("body", "mounting_hole", "boss", "hole")):
            feature["role"] = role
        return value

    def test_domain_schema_is_available_as_tool_and_resource(self) -> None:
        tool = self.agent._dispatch_tool("aicad_get_domain_validation_schema", {})
        self.assertTrue(tool["ok"])
        self.assertEqual(tool["schema"]["title"], "AICAD cross-domain validation report")
        resource = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "resources/read",
            "params": {"uri": "aicad://domain-validation-schema"},
        })
        self.assertIn("AICAD cross-domain validation report", resource["result"]["contents"][0]["text"])

    def test_domain_validation_tool_writes_root_cause_capable_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self.agent._dispatch_tool("aicad_validate_domain_plan", {
                "plan": self.plan3d(), "space": "3d", "output_dir": directory, "name": "mechanical-part",
            })
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "passed")
            self.assertTrue(payload["summary"]["manual_review_required"])
            self.assertTrue(Path(payload["artifacts"]["validation"]).is_file())
            self.assertTrue(Path(payload["artifacts"]["audit"]).is_file())

    def test_capabilities_expose_domain_packs_and_honest_host_boundaries(self) -> None:
        value = self.agent.capabilities()["universal_cad"]
        self.assertIn("electronics", value["domain_rule_packs"])
        self.assertIn("sheet_metal", value["domain_rule_packs"])
        self.assertIn("native_sheet_metal", value["host_capability_matrix"]["solidworks"]["not_supported"])
        self.assertIn("collinear", self.agent.capabilities()["constraints"])


if __name__ == "__main__":
    unittest.main()
