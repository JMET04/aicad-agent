from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.cli import main
from aicad.engine import PlanError, ResolvedArc, ResolvedCircle, compile_plan
from aicad.exporters import export_all
from aicad.natural import UnsupportedRequest, draft_to_plan, offline_plan
from aicad import provider as provider_module
from aicad.settings import DEFAULT_CONFIG


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((ROOT / "examples" / "rectangle.plan.json").read_text(encoding="utf-8"))

    def test_schema_1_rectangle_remains_backward_compatible(self) -> None:
        plan = compile_plan(self.data)
        self.assertEqual(plan.schema_version, "1.0")
        self.assertEqual(len(plan.lines), 4)
        self.assertEqual(plan.lines[0].start, (0.0, 0.0))
        self.assertAlmostEqual(plan.lines[1].end[0], 120.0)
        self.assertAlmostEqual(plan.lines[1].end[1], 80.0)
        self.assertAlmostEqual(plan.lines[-1].end[0], 0.0, places=8)
        self.assertAlmostEqual(plan.lines[-1].end[1], 0.0, places=8)

    def test_first_entity_must_anchor_at_origin(self) -> None:
        data = copy.deepcopy(self.data)
        data["steps"][0]["start"] = {"point": [5, 5]}
        with self.assertRaisesRegex(PlanError, "first entity anchor"):
            compile_plan(data)

    def test_duplicate_geometry_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["steps"].append({
            "id": "L005", "type": "line", "purpose": "duplicate", "reasoning": "test duplicate rejection",
            "start": {"ref": "origin"}, "construction": {"kind": "to_point", "target": {"ref": "L001.end"}},
            "constraints": [{"kind": "horizontal"}],
        })
        with self.assertRaisesRegex(PlanError, "duplicates L001"):
            compile_plan(data)

    def test_rejects_forward_reference(self) -> None:
        data = copy.deepcopy(self.data)
        data["steps"][0]["construction"] = {
            "kind": "to_point",
            "target": {"ref": "L002.end"},
        }
        with self.assertRaisesRegex(PlanError, "has not been drawn"):
            compile_plan(data)

    def test_false_coincident_relation_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["steps"][1]["start"] = {"point": [999, 999]}
        with self.assertRaisesRegex(PlanError, "violates start_coincident"):
            compile_plan(data)

    def test_default_generation_stays_offline_without_api_key(self) -> None:
        self.assertEqual(DEFAULT_CONFIG["provider"], "offline")
        with patch.object(provider_module, "offline_plan", side_effect=UnsupportedRequest("unsupported")):
            with patch.object(provider_module, "_openai_plan") as remote:
                with self.assertRaises(UnsupportedRequest):
                    provider_module.generate_plan("arbitrary unsupported request")
                remote.assert_not_called()
    def test_offline_plate_has_a_constrained_center_hole(self) -> None:
        plan = compile_plan(offline_plan("120×80板，中心直径20孔"))
        self.assertEqual(len(plan.entities), 5)
        circle = plan.entities[-1]
        self.assertIsInstance(circle, ResolvedCircle)
        self.assertEqual(circle.center, (60.0, 40.0))
        self.assertEqual(circle.radius, 10.0)
        self.assertIn("center_offset", {constraint["kind"] for constraint in circle.constraints})

    def test_offline_circle_and_arc(self) -> None:
        circle = compile_plan(offline_plan("diameter 30 circle")).entities[0]
        arc = compile_plan(offline_plan("radius 20 arc 0 to 90")).entities[0]
        self.assertIsInstance(circle, ResolvedCircle)
        self.assertIsInstance(arc, ResolvedArc)
        self.assertEqual(circle.radius, 15.0)
        self.assertEqual((arc.start_angle_deg, arc.end_angle_deg), (0.0, 90.0))

    def test_strict_ai_draft_is_reconstrained_locally(self) -> None:
        nulls = {"cx": None, "cy": None, "radius": None, "start_angle_deg": None, "end_angle_deg": None}
        draft = {
            "name": "triangle", "units": "mm",
            "entities": [
                {"type": "line", "purpose": "base", "reasoning": "origin base", "x1": 0, "y1": 0, "x2": 50, "y2": 0, **nulls},
                {"type": "line", "purpose": "side", "reasoning": "connect", "x1": 50, "y1": 0, "x2": 25, "y2": 40, **nulls},
                {"type": "line", "purpose": "close", "reasoning": "return", "x1": 25, "y1": 40, "x2": 0, "y2": 0, **nulls},
            ],
        }
        plan = compile_plan(draft_to_plan(draft))
        self.assertEqual(len(plan.entities), 3)
        self.assertTrue(all(any(c["kind"] == "length" for c in line.constraints) for line in plan.lines))
        self.assertTrue(any(c["kind"] == "start_coincident" and c["target"] == "E001.end" for c in plan.lines[1].constraints))
        self.assertTrue(any(c["kind"] == "start_coincident" and c["target"] == "E002.end" for c in plan.lines[2].constraints))

    def test_v2_export_contains_ascii_entities_anchor_proofs_and_valid_dxf(self) -> None:
        plan = compile_plan(offline_plan("120x80 plate diameter 20"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = export_all(plan, output, "plate")
            execution = (output / "plate.aicad").read_bytes()
            execution.decode("ascii")
            self.assertTrue(execution.startswith(b"AICAD|2|"))
            self.assertEqual(execution.count(b"\nLINE|"), 4)
            self.assertEqual(execution.count(b"\nCIRCLE|"), 1)
            circle_record = next(line for line in execution.decode().splitlines() if line.startswith("CIRCLE|"))
            self.assertEqual(len(circle_record.split("|")), 11)
            dxf = (output / "plate.dxf").read_text(encoding="ascii")
            self.assertEqual(dxf.count("\nLINE\n"), 4)
            self.assertEqual(dxf.count("\nCIRCLE\n"), 1)
            self.assertTrue(dxf.endswith("0\nEOF\n"))
            script = (output / "plate.scr").read_bytes()
            script.decode("ascii")
            self.assertEqual(script.count(b"_.LINE\n"), 4)
            self.assertEqual(script.count(b"_.CIRCLE\n"), 1)
            self.assertTrue(script.endswith(b"\n"))
            self.assertEqual(len(paths), 5)

    def test_natural_cli_writes_plan_execution_and_result_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, result = root / "request.txt", root / "result.txt"
            request.write_text("画120×80板，中心直径20孔", encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(["natural", str(request), "--out", str(root / "out"), "--result", str(result), "--provider", "offline"])
            self.assertEqual(code, 0)
            self.assertEqual(result.read_text(encoding="utf-8").splitlines()[0], "OK")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["entities"], 5)
            self.assertTrue(Path(payload["execution"]).is_file())

    def test_bundle_manifest_lisp_and_installer_are_production_version(self) -> None:
        manifest = ET.parse(ROOT / "plugin" / "AiCadConstraint.bundle" / "PackageContents.xml")
        self.assertEqual(manifest.getroot().attrib["AppVersion"], "1.3.4")
        source = (ROOT / "plugin" / "AiCadConstraint.bundle" / "Contents" / "AiCadConstraint.lsp").read_bytes()
        text = source.decode("ascii")
        depth, in_string, escaped, in_comment = 0, False, False, False
        for char in text:
            if in_comment:
                if char == "\n": in_comment = False
                continue
            if in_string:
                if escaped: escaped = False
                elif char == "\\": escaped = True
                elif char == '"': in_string = False
                continue
            if char == ";": in_comment = True
            elif char == '"': in_string = True
            elif char == "(": depth += 1
            elif char == ")":
                depth -= 1
                self.assertGreaterEqual(depth, 0)
        self.assertFalse(in_string)
        self.assertEqual(depth, 0)
        self.assertIn("(defun c:AICAD_AI", text)
        self.assertIn("(defun c:AICAD_DOCTOR", text)
        self.assertIn('(setq aicad:*version* "1.3.4")', text)
        self.assertNotIn('(command "_.UNDO"', text)
        installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("AICAD_RUNNER", installer)
        self.assertIn("Windows Credential", (ROOT / "src" / "aicad" / "cli.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
