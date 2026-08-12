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
        self.assertEqual(manifest["version"], "1.12.0")
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
        self.assertEqual(payload["api_version"], "1.12.0")
        self.assertEqual(payload["entities"], ["line", "circle", "arc", "text", "dimension"])
        self.assertTrue({"position_coincident", "position_offset", "text_height", "rotation", "dimension_measurement", "dimension_orientation", "base_offset"}.issubset(payload["constraints"]))
        self.assertIn("schema 2.0 compiles to AICAD protocol 3, or protocol 4 when native dimensions are present", payload["invariants"])
        self.assertTrue(Path(payload["schema_path"]).is_file())
        self.assertTrue(payload["agent_native"]["default"])
        self.assertFalse(payload["agent_native"]["api_key_required"])
        self.assertEqual(payload["agent_native"]["compiler_provider"], "caller-plan")
        self.assertTrue(payload["architectural_drafting_qa"]["available"])
        self.assertTrue(Path(payload["architectural_drafting_qa"]["script"]).is_file())
        self.assertTrue(payload["architectural_drafting_qa"]["complete_axis_groups"])
        self.assertTrue(payload["architectural_detail_contract"]["available"])
        self.assertTrue(Path(payload["architectural_detail_contract"]["script"]).is_file())
        self.assertTrue(Path(payload["architectural_detail_contract"]["schema"]).is_file())
        self.assertEqual(payload["architectural_detail_contract"]["failure_disposition"], "blocker_report_only")
        self.assertEqual(payload["architectural_detail_contract"]["blocker_formats"], ["json", "html", "png", "launch_json"])
        self.assertTrue(payload["report_quality_qa"]["available"])
        self.assertTrue(Path(payload["report_quality_qa"]["script"]).is_file())
        self.assertTrue(payload["report_quality_qa"]["unique_prevention_rule_ids"])
        self.assertTrue(payload["packaging_dieline_qa"]["available"])
        self.assertTrue(Path(payload["packaging_dieline_qa"]["script"]).is_file())
        self.assertTrue(Path(payload["packaging_dieline_qa"]["rules"]).is_file())
        self.assertTrue(payload["packaging_dieline_qa"]["review_only"])
        self.assertTrue(Path(payload["solidworks_3d"]["schema_path"]).is_file())
        normative = payload["normative_governance"]
        self.assertTrue(normative["available"])
        self.assertEqual(normative["priority"], "first_non_compensatory_gate")
        self.assertEqual(normative["authority_precedence"][0], "selected_standard")
        self.assertIn("NORM-G004", normative["rule_ids"])
        self.assertTrue({"architecture", "packaging", "mechanical", "sheet_metal", "electronics", "civil", "structural", "electrical", "plumbing", "hvac", "process_piping", "product_design", "general"}.issubset(normative["governed_domains"]))
        self.assertEqual(normative["implementation_proof"], ["schema_contract_field", "generation_constraint", "independent_qa", "negative_regression_test"])
        self.assertTrue(Path(normative["rules"]).is_file())
        self.assertTrue(Path(normative["validator"]).is_file())
        self.assertTrue(Path(normative["contract_schema"]).is_file())
        self.assertTrue(payload["universal_cad"]["core_is_domain_agnostic"])
        self.assertIn("mechanical", payload["universal_cad"]["domain_profiles"])
        self.assertIn("electronics", payload["universal_cad"]["domain_profiles"])
        self.assertIn("point", payload["universal_cad"]["exact_subobject_correction"]["geometry_types"])
        self.assertTrue(payload["reference_reconstruction"]["available"])
        self.assertTrue(Path(payload["reference_reconstruction"]["schema_path"]).is_file())
        self.assertIn("mojibake", payload["reference_reconstruction"]["gates"])

    def test_architecture_compile_without_detail_contract_is_blocked_before_artifacts(self) -> None:
        plan = {
            "schema_version": "2.0",
            "drawing": {
                "name": "blocked architecture", "units": "mm", "origin": [0, 0], "tolerance": 1e-6,
                "domain": "architecture",
                "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
            },
            "steps": [{
                "id": "L001", "type": "line", "purpose": "origin wall", "reasoning": "test precompile gate",
                "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 1000, "dy": 0},
                "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 1000}],
                "layer": "WALL", "role": "wall",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"
            with self.assertRaisesRegex(self.agent.PlanError, "architecture_detail_contract"):
                self.agent.compile_plan_value(plan, str(output), "blocked")
            self.assertFalse(output.exists())

    def test_generate_creates_complete_artifact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self.agent.generate("120x80 plate with centered diameter 20 hole", directory, "plate", "offline")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["entity_count"], 5)
            self.assertEqual(payload["provider"], "offline")
            for key in ("plan", "execution", "script", "dxf", "audit", "manifest"):
                self.assertTrue(Path(payload[key]).is_file(), key)
            manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["entity_types"], {"line": 4, "circle": 1, "arc": 0, "text": 0, "dimension": 0})

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
            "aicad_capabilities", "aicad_get_plan_schema",
            "aicad_get_architecture_detail_contract_schema", "aicad_validate_architecture_detail_contract",
            "aicad_generate",
            "aicad_validate_plan", "aicad_compile_plan", "aicad_solidworks_doctor",
            "aicad_get_3d_plan_schema", "aicad_validate_3d_plan", "aicad_build_solidworks_part",
            "aicad_get_semantic_schema", "aicad_get_correction_schema", "aicad_get_view_package_schema",
            "aicad_describe_plan", "aicad_preview_correction", "aicad_apply_correction",
            "aicad_build_multiview_review",
            "aicad_get_domain_validation_schema", "aicad_validate_domain_plan",
            "aicad_get_reference_rebuild_schema", "aicad_validate_reference_rebuild",
            "aicad_build_reference_reconstruction",
        })
        call = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "aicad_capabilities", "arguments": {}},
        })
        self.assertTrue(call["result"]["structuredContent"]["ok"])

    def test_universal_semantic_correction_and_multiview_tools(self) -> None:
        plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        described = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 80, "method": "tools/call",
            "params": {"name": "aicad_describe_plan", "arguments": {"plan": plan, "space": "3d", "domain": "electronics"}},
        })["result"]["structuredContent"]
        self.assertTrue(described["ok"])
        self.assertEqual(described["document"]["domain"], "electronics")
        self.assertEqual(len(described["objects"]), 4)
        correction = {
            "schema_version": "1.0",
            "correction": {
                "id": "CORR001", "description": "increase bore", "space": "3d", "selected_ids": ["F004"],
                "operations": [{"op": "set_parameter", "target": "F004", "path": "profile.radius", "value": 6}],
            },
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
        }
        preview = self.agent._handle_mcp({
            "jsonrpc": "2.0", "id": 81, "method": "tools/call",
            "params": {"name": "aicad_preview_correction", "arguments": {"plan": plan, "correction": correction, "domain": "mechanical"}},
        })["result"]["structuredContent"]
        self.assertEqual(preview["status"], "pass")
        self.assertEqual(preview["directly_changed_ids"], ["F004"])
        with tempfile.TemporaryDirectory() as directory:
            review = self.agent._handle_mcp({
                "jsonrpc": "2.0", "id": 82, "method": "tools/call",
                "params": {"name": "aicad_build_multiview_review", "arguments": {
                    "plan": plan, "space": "3d", "domain": "mechanical", "output_dir": directory, "name": "part",
                }},
            })["result"]["structuredContent"]
            self.assertEqual(review["view_count"], 6)
            self.assertTrue(Path(review["artifacts"]["review_html"]).is_file())

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
            with patch("aicad.solidworks3d.find_solidworks_template", return_value=None), \
                 patch("aicad.solidworks3d.find_solidworks_host", return_value=None):
                compiled = self.agent.build_solidworks_part(str(plan_path), directory, "mcp-part", False)
            self.assertFalse(compiled["executed"])
            self.assertTrue(compiled["host_requirements_deferred"])
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


    def test_production_installer_preserves_verified_plugin_manifest(self) -> None:
        installer = (ROOT / "scripts" / "install-agent-plugin.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("$installedManifest.version =", installer)
        self.assertIn("Installed plugin version", installer)
        self.assertIn("Copy-Item", installer)
        self.assertIn("$sourceIntegrity.files", installer)
        self.assertIn("Unsafe integration-manifest path", installer)
        self.assertIn("integration-manifest.json", installer)
        self.assertNotIn("Get-ChildItem -LiteralPath $source -Force", installer)

if __name__ == "__main__":
    unittest.main()
