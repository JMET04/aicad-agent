from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "agent-plugin" / "aicad-agent"
SCRIPT = PLUGIN / "scripts" / "aicad_agent.py"


def load_agent_module():
    spec = importlib.util.spec_from_file_location("aicad_agent_plugin", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load agent plugin script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent_module()

    def test_manifest_skill_and_mcp_are_complete(self) -> None:
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "aicad-agent")
        self.assertEqual(manifest["version"], "1.2.0")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertIn("MCP tools", manifest["interface"]["capabilities"])
        mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(mcp["mcpServers"]["aicad-agent"]["command"], "python")
        skill = (PLUGIN / "skills" / "aicad-draw" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill)
        self.assertIn("aicad_compile_plan", skill)
        self.assertIn("avoiding command-stream mojibake", skill)
        skill3d = (PLUGIN / "skills" / "aicad-model-3d" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill3d)
        self.assertIn("aicad_build_solidworks_part", skill3d)
        self.assertIn("fully constrained sketch", skill3d)

    def test_capabilities_are_machine_readable(self) -> None:
        payload = self.agent.capabilities()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["entities"], ["line", "circle", "arc"])
        self.assertTrue(Path(payload["schema_path"]).is_file())
        self.assertTrue(payload["agent_native"]["default"])
        self.assertFalse(payload["agent_native"]["api_key_required"])
        self.assertEqual(payload["agent_native"]["compiler_provider"], "caller-plan")
        self.assertTrue(payload["packaging_dieline_qa"]["available"])
        self.assertTrue(Path(payload["packaging_dieline_qa"]["script"]).is_file())
        self.assertTrue(Path(payload["packaging_dieline_qa"]["rules"]).is_file())
        self.assertTrue(payload["packaging_dieline_qa"]["review_only"])
        self.assertTrue(Path(payload["solidworks_3d"]["schema_path"]).is_file())

    def test_generate_creates_complete_artifact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self.agent.generate("120x80 plate with centered diameter 20 hole", directory, "plate", "offline")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["entity_count"], 5)
            self.assertEqual(payload["provider"], "offline")
            for key in ("plan", "execution", "script", "dxf", "audit", "manifest"):
                self.assertTrue(Path(payload[key]).is_file(), key)
            manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["entity_types"], {"line": 4, "circle": 1, "arc": 0})

    def test_cli_reads_utf8_request_file_and_emits_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "generate", "--request-file", str(ROOT / "examples" / "agent-request-zh.txt"), "--out", directory, "--name", "zh-plate"],
                check=False, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            payload = json.loads(result.stdout.decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["entity_count"], 5)

    def test_validate_plan_does_not_write_artifacts(self) -> None:
        plan_path = ROOT / "examples" / "arc.plan.json"
        payload = self.agent.validate_plan_value(str(plan_path))
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["entities"], [{"index": 1, "id": "A001", "type": "arc"}])

    def test_mcp_handshake_tool_listing_and_call(self) -> None:
        initialize = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        })
        self.assertEqual(initialize["result"]["serverInfo"]["name"], "aicad-agent")
        listing = self.agent._handle_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in listing["result"]["tools"]}
        self.assertEqual(names, {
            "aicad_capabilities", "aicad_get_plan_schema", "aicad_generate",
            "aicad_validate_plan", "aicad_compile_plan", "aicad_solidworks_doctor",
            "aicad_get_3d_plan_schema", "aicad_validate_3d_plan", "aicad_build_solidworks_part",
        })
        call = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "aicad_capabilities", "arguments": {}},
        })
        self.assertTrue(call["result"]["structuredContent"]["ok"])

    def test_agent_authored_plan_compile_never_calls_provider_or_api(self) -> None:
        plan = json.loads((ROOT / "examples" / "arc.plan.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                self.agent,
                "generate_plan",
                side_effect=AssertionError("agent-authored compile must not call a provider"),
            ):
                call = self.agent._handle_mcp({
                    "jsonrpc": "2.0", "id": 30, "method": "tools/call",
                    "params": {
                        "name": "aicad_compile_plan",
                        "arguments": {"plan": plan, "output_dir": directory, "name": "agent-direct"},
                    },
                })
            payload = call["result"]["structuredContent"]
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["provider"], "caller-plan")
            for key in ("plan", "execution", "script", "dxf", "audit", "manifest"):
                self.assertTrue(Path(payload[key]).is_file(), key)

    def test_mcp_returns_stable_error_instead_of_crashing(self) -> None:
        call = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "aicad_validate_plan", "arguments": {"plan": {}}},
        })
        self.assertTrue(call["result"]["isError"])
        error = call["result"]["structuredContent"]["error"]
        self.assertEqual(error["code"], "PLAN_INVALID")

    def test_3d_schema_validation_and_compile_without_execution(self) -> None:
        plan_path = ROOT / "examples" / "mounting_plate_3d.plan.json"
        validated = self.agent.validate_3d_plan_value(str(plan_path))
        self.assertTrue(validated["valid"])
        self.assertEqual(validated["feature_count"], 4)
        with tempfile.TemporaryDirectory() as directory:
            compiled = self.agent.build_solidworks_part(str(plan_path), directory, "mcp-part", False)
            self.assertFalse(compiled["executed"])
            self.assertTrue(Path(compiled["solidworks_plan"]).is_file())
            self.assertTrue(Path(compiled["audit"]).is_file())
            self.assertFalse(Path(compiled["sldprt"]).exists())

    def test_solidworks_host_explicitly_constrains_circle_center_and_radius(self) -> None:
        source = (ROOT / "solidworks-host" / "AiCad.SolidWorksHost" / "Program.cs").read_text(encoding="utf-8")
        for token in (
            "ModelToSketchTransform",
            "AddExplicitCircleConstraints",
            "explicit_radius_dimension_count",
            "explicit_center_dimension_count",
            "explicit_center_relation_count",
            'model.SketchAddConstraints("sgCOINCIDENT")',
            'model.SketchAddConstraints("sgHORIZONTALPOINTS2D")',
            'model.SketchAddConstraints("sgVERTICALPOINTS2D")',
            "model.AddHorizontalDimension2",
            "model.AddVerticalDimension2",
            "model.AddRadialDimension2",
            "supportFeature.GetFaces()",
            'report.support_face_selection_method = "named_feature_exact_z"',
            "PASS:support_plane_feature_and_z",
        ):
            self.assertIn(token, source)
        self.assertNotIn("AddCircleRadiusDimensions", source)
        self.assertNotIn("SelectByRay", source)

    def test_solidworks_doctor_reports_real_host_or_graceful_unavailable(self) -> None:
        payload = self.agent.solidworks_doctor()
        self.assertIn("ok", payload)
        if payload["ok"]:
            self.assertTrue(Path(payload["host"]).is_file())
        else:
            self.assertIsNone(payload["host"])
            self.assertIn("solidworks_registered", payload)


if __name__ == "__main__":
    unittest.main()
