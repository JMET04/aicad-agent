from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"


def load_agent_module():
    spec = importlib.util.spec_from_file_location("aicad_agent_reference_plugin", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load agent plugin script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentReferenceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent_module()
        cls.plan_path = ROOT / "examples" / "web_reference_plate.plan.json"
        cls.reference_path = ROOT / "examples" / "web_reference_plate.reference.json"

    def test_schema_resource_and_validate_tool(self) -> None:
        schema = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "resources/read",
            "params": {"uri": "aicad://reference-rebuild-schema"},
        })
        contents = schema["result"]["contents"][0]
        self.assertEqual(json.loads(contents["text"])["title"], "AICAD webpage/image reference reconstruction contract")
        validation = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "aicad_validate_reference_rebuild", "arguments": {
                "plan": str(self.plan_path), "reference": str(self.reference_path),
            }},
        })["result"]["structuredContent"]
        self.assertEqual(validation["status"], "pass")
        self.assertTrue(validation["checks"]["reference_dom_catalog_verified"])
        self.assertTrue(validation["checks"]["source_text_encoding_valid"])

    def test_build_tool_writes_full_reference_artifact_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.agent._handle_mcp({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "aicad_build_reference_reconstruction", "arguments": {
                    "plan": str(self.plan_path), "reference": str(self.reference_path),
                    "output_dir": directory, "name": "web-plate",
                }},
            })["result"]["structuredContent"]
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "pass")
            for value in result["artifacts"].values():
                self.assertTrue(Path(value).is_file(), value)
            page = Path(result["artifacts"]["preview_html"]).read_text(encoding="utf-8")
            self.assertIn("&#x4E00;&#x6BD4;&#x4E00;", page)
            self.assertNotIn("\ufffd", page)


if __name__ == "__main__":
    unittest.main()