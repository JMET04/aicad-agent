from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import ezdxf
from ezdxf.enums import TextEntityAlignment
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.cli import main
from aicad.engine import PlanError, ResolvedArc, ResolvedCircle, ResolvedDimension, ResolvedText, compile_plan
from aicad.exporters import _layer_style, export_all
from aicad.natural import UnsupportedRequest, draft_to_plan, offline_plan
from aicad.semantic import semantic_from_plan
from aicad.viewmap import build_multiview_review
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
            self.assertTrue(execution.startswith(b"AICAD|3|"))
            self.assertEqual(execution.count(b"\nLINE|"), 4)
            self.assertEqual(execution.count(b"\nCIRCLE|"), 1)
            circle_record = next(line for line in execution.decode().splitlines() if line.startswith("CIRCLE|"))
            self.assertEqual(len(circle_record.split("|")), 12)
            self.assertEqual(circle_record.split("|")[2], "AICAD_GEOMETRY")
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

    def test_architecture_layer_styles_match_normative_profile(self) -> None:
        profile = json.loads((ROOT / "agent-plugin" / "aicad-agent" / "rules" / "architectural_drafting_rules.json").read_text(encoding="utf-8"))["defaultLayerProfile"]
        for layer, expected in profile.items():
            style = _layer_style(layer)
            self.assertEqual(style["lineweight"], round(float(expected["lineweightMm"]) * 100), layer)
            self.assertEqual(str(style["linetype"]).upper(), str(expected["linetype"]).upper(), layer)

    def test_constrained_text_is_real_ascii_transport_and_semantic_layer_entity(self) -> None:
        data = {
            "schema_version": "2.0",
            "drawing": {"name": "axis", "domain": "architecture", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
            "steps": [
                {"id": "AX1", "type": "line", "purpose": "vertical axis", "reasoning": "datum begins at origin", "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 0, "dy": 1000}, "constraints": [{"kind": "vertical"}, {"kind": "length", "value": 1000}], "layer": "GRID"},
                {"id": "AX1B", "type": "circle", "purpose": "axis bubble", "reasoning": "bubble is offset from the axis origin", "center": {"point": [0, 1200]}, "radius": 100, "constraints": [{"kind": "center_offset", "target": "AX1.start", "dx": 0, "dy": 1200}, {"kind": "radius", "value": 100}], "layer": "GRID_BUBBLE", "depends_on": ["AX1"]},
                {"id": "AX1T", "type": "text", "purpose": "axis identifier", "reasoning": "identifier is centered in its bubble", "insert": {"ref": "AX1B.center"}, "value": "轴1", "height": 80, "rotation_deg": 0, "constraints": [{"kind": "position_coincident", "target": "AX1B.center"}, {"kind": "text_height", "value": 80}, {"kind": "rotation", "value": 0}], "layer": "GRID_TEXT", "depends_on": ["AX1B"]},
            ],
        }
        plan = compile_plan(data)
        self.assertIsInstance(plan.entities[-1], ResolvedText)
        self.assertEqual(plan.entities[-1].depends_on, ("AX1B",))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            export_all(plan, output, "axis")
            execution = (output / "axis.aicad").read_bytes()
            execution.decode("ascii")
            text_record = next(line for line in execution.decode("ascii").splitlines() if line.startswith("TEXT|"))
            fields = text_record.split("|")
            self.assertEqual(len(fields), 14)
            self.assertEqual(fields[2], "GRID_TEXT")
            self.assertEqual(fields[7], "\\U+8F741")
            dxf_path = output / "axis.dxf"
            dxf = dxf_path.read_text(encoding="ascii")
            document = ezdxf.readfile(dxf_path)
            grid = document.layers.get("GRID")
            self.assertEqual(document.dxfversion, "AC1018")
            self.assertEqual(grid.dxf.linetype, "CENTER2")
            self.assertEqual(grid.dxf.lineweight, 13)
            text_entities = list(document.modelspace().query('TEXT[layer=="GRID_TEXT"]'))
            self.assertEqual(len(text_entities), 1)
            self.assertEqual(text_entities[0].dxf.text, "\\U+8F741")
            self.assertEqual(text_entities[0].get_placement()[0], TextEntityAlignment.MIDDLE_CENTER)
            self.assertIn("\\U+8F741", dxf)
            script = (output / "axis.scr").read_text(encoding="ascii")
            self.assertIn("_.-TEXT", script)
            manifest = json.loads((output / "axis.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["entity_types"]["text"], 1)

    def test_native_dimension_compiles_through_protocol_dxf_semantic_and_review(self) -> None:
        data = json.loads((ROOT / "examples" / "architecture-dimensions.plan.json").read_text(encoding="utf-8"))
        plan = compile_plan(data)
        self.assertEqual(len(plan.dimensions), 5)
        self.assertTrue(all(isinstance(entity, ResolvedDimension) for entity in plan.dimensions))
        self.assertEqual([entity.dimension_purpose for entity in plan.dimensions], ["overall", "grid", "partition", "opening", "general"])
        self.assertEqual([entity.measurement for entity in plan.dimensions], [1000.0, 1000.0, 800.0, 1000.0, 500.0])
        self.assertEqual(plan.dimensions[-1].orientation_deg, 53.13010235415598)

        semantic = semantic_from_plan(data, "2d", "architecture")
        dimension_objects = [entity for entity in semantic.objects if entity.kind == "dimension"]
        self.assertEqual(len(dimension_objects), 5)
        self.assertEqual(dimension_objects[0].parameters["style_name"], "AICAD_ARCH")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            export_all(plan, output, "native-dimensions")
            execution = (output / "native-dimensions.aicad").read_text(encoding="ascii")
            self.assertTrue(execution.startswith("AICAD|4|"))
            records = [row.split("|") for row in execution.splitlines() if row.startswith("DIMENSION|")]
            self.assertEqual(len(records), 5)
            self.assertTrue(all(len(row) == 18 for row in records))
            self.assertEqual(records[0][3:12], ["horizontal", "0", "0", "1000", "0", "0", "-500", "AICAD_ARCH", "overall"])

            document = ezdxf.readfile(output / "native-dimensions.dxf")
            dimensions = list(document.modelspace().query('DIMENSION[layer=="DIMENSION"]'))
            self.assertEqual(len(dimensions), 5)
            self.assertEqual([round(entity.get_measurement(), 6) for entity in dimensions], [1000.0, 1000.0, 800.0, 1000.0, 500.0])
            style = document.dimstyles.get("AICAD_ARCH")
            self.assertEqual(style.dxf.dimtxt, 280.0)
            self.assertEqual(style.dxf.dimtsz, 150.0)
            xdata = [[value for _, value in entity.get_xdata("AICAD")] for entity in dimensions]
            self.assertEqual([row[0] for row in xdata], ["D_OVERALL_X", "D_GRID_X", "D_PARTITION_Y", "D_OPENING_X", "D_ALIGNED"])
            self.assertEqual(xdata[0][3:], ["DIM_PURPOSE:overall", "DIM_STYLE:AICAD_ARCH", "DIM_KIND:horizontal"])
            script = (output / "native-dimensions.scr").read_text(encoding="ascii")
            self.assertEqual(script.count("_.DIMLINEAR\n"), 4)
            self.assertEqual(script.count("_.DIMALIGNED\n"), 1)
            manifest = json.loads((output / "native-dimensions.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["entity_types"]["dimension"], 5)
            self.assertIn("D_OVERALL_X", (output / "native-dimensions.audit.md").read_text(encoding="utf-8"))

            review = build_multiview_review(data, "2d", "architecture", output, "native-dimensions")
            self.assertEqual(review["status"], "pass")
            package = json.loads(Path(review["artifacts"]["view_package"]).read_text(encoding="utf-8"))
            dimension_views = [entity for entity in package["views"][0]["entities"] if entity["source_object_id"].startswith("D_")]
            self.assertEqual(len(dimension_views), 15)

    def test_native_dimension_rejects_false_measurement_and_unbound_points(self) -> None:
        data = json.loads((ROOT / "examples" / "architecture-dimensions.plan.json").read_text(encoding="utf-8"))
        false_measurement = copy.deepcopy(data)
        false_measurement["steps"][5]["constraints"][0]["value"] = 999
        with self.assertRaisesRegex(PlanError, "measurement is 1000"):
            compile_plan(false_measurement)
        unbound = copy.deepcopy(data)
        unbound["steps"][5]["first"] = {"point": [0, 0]}
        with self.assertRaisesRegex(PlanError, "must reference earlier resolved geometry"):
            compile_plan(unbound)

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
        self.assertEqual(manifest.getroot().attrib["AppVersion"], "1.6.0")
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
        self.assertIn('(= version "3")', text)
        self.assertIn('(= version "4")', text)
        self.assertIn('(= kind "TEXT")', text)
        self.assertIn('(= kind "DIMENSION")', text)
        self.assertIn('"_.DIMLINEAR"', text)
        self.assertIn('"_.DIMALIGNED"', text)
        self.assertIn('"_.-DIMSTYLE"', text)
        self.assertNotIn('(vla-AddDimRotated', text)
        self.assertNotIn('(vla-AddDimAligned', text)
        self.assertIn('DIM_PURPOSE:', text)
        self.assertIn('(cons 8 layer)', text)
        self.assertIn('(defun aicad:layer-style', text)
        self.assertIn('(cons 370 (nth 1 style))', text)
        self.assertIn('(setq aicad:*version* "1.6.0")', text)
        self.assertNotIn('(command "_.UNDO"', text)
        installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("AICAD_RUNNER", installer)
        self.assertIn("Windows Credential", (ROOT / "src" / "aicad" / "cli.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
