from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


PLUGIN = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "scripts"))

import aicad_packaging_qa as qa  # noqa: E402


class PackagingDielineRuleRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry_path = PLUGIN / "tests" / "fixtures" / "fefco0201_geometry.json"
        cls.rules_path = PLUGIN / "rules" / "packaging_dieline_rules.json"
        cls.geometry = json.loads(cls.geometry_path.read_text(encoding="utf-8"))
        cls.rules = json.loads(cls.rules_path.read_text(encoding="utf-8"))

    def result(self, geometry, rule_id):
        rows = qa.geometry_checks(geometry, self.rules)
        return next(row for row in rows if row["rule_id"] == rule_id)

    def test_current_exact_fillet_passes_tangency(self):
        row = self.result(copy.deepcopy(self.geometry), "PKG-G002")
        self.assertTrue(row["pass"])
        self.assertLessEqual(row["evidence"]["max_angle_error_deg"], qa.ANGLE_TOL_DEG)

    def test_endpoint_only_corner_is_rejected(self):
        broken = copy.deepcopy(self.geometry)
        arc = next(item for item in broken["entities"] if item["id"] == "ARC_T_P1_L")
        arc["center"][0] += 0.5
        row = self.result(broken, "PKG-G002")
        self.assertFalse(row["pass"], "a corner that merely looks connected must fail the tangency gate")

    def test_duplicate_entity_is_rejected(self):
        broken = copy.deepcopy(self.geometry)
        duplicate = copy.deepcopy(next(item for item in broken["entities"] if item["id"] == "CUT_JOINT_TOP"))
        duplicate["id"] = "CUT_JOINT_TOP_DUPLICATE"
        broken["entities"].append(duplicate)
        row = self.result(broken, "PKG-G003")
        self.assertFalse(row["pass"])
        self.assertGreater(row["evidence"]["duplicate_count"], 0)

    def test_asymmetric_v_slot_is_rejected(self):
        broken = copy.deepcopy(self.geometry)
        edge = next(item for item in broken["entities"] if item["id"] == "SLOT_T_P2_L")
        edge["end"][0] += 0.25
        row = self.result(broken, "PKG-G004")
        self.assertFalse(row["pass"])

    def test_frame_and_semantic_delivery_rules_are_persistent(self):
        rule_ids = {row["id"] for row in self.rules["rules"]}
        self.assertTrue({"PKG-G010", "PKG-G011", "PKG-G012", "PKG-G013"}.issubset(rule_ids))
        for rule_id in ("PKG-G010", "PKG-G011", "PKG-G012", "PKG-G013"):
            row = next(item for item in self.rules["rules"] if item["id"] == rule_id)
            self.assertTrue(row["failure_cause"])
            self.assertTrue(row["prevention"])

    def test_reference_frame_config_preserves_production_scale(self):
        config_path = PLUGIN / "tests" / "fixtures" / "frame_reference_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["reference_measurements_mm"]["outer"], [420, 297])
        self.assertEqual(config["reference_measurements_mm"]["inner_margins"],
                         {"left": 25, "top": 5, "right": 5, "bottom": 5})
        self.assertEqual(config["implementation"]["model_space"], "1:1 unchanged")
        self.assertEqual(config["implementation"]["locked_viewport_scale"], "1:5")

    def test_native_sheet_rules_and_config_are_persistent(self):
        rule_ids = {row["id"] for row in self.rules["rules"]}
        required = {"PKG-G014", "PKG-G015", "PKG-G016", "PKG-G017"}
        self.assertTrue(required.issubset(rule_ids))
        config_path = PLUGIN / "tests" / "fixtures" / "native_sheet_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["dimensioning"]["counts"], {"linear": 10, "radius": 1, "total": 11})
        self.assertEqual(config["dimensioning"]["native_entity_types"]["radius"], "AcDbRadialDimension")
        self.assertFalse(config["dimensioning"]["text_override_allowed"])
        self.assertEqual(config["title_block"]["school"], "STU")
        self.assertEqual(config["title_block"]["name"], "明明")
        self.assertEqual(config["title_block"]["removed_reference_examples"], ["班级", "专业", "成绩", "学号"])
        self.assertIn("inside frame", config["technical_requirements"]["location"])


    def test_opaque_png_plus_visual_review_passes_when_svg_text_is_pathized(self):
        review = {
            "passed": True,
            "checks": {
                "all_required_chinese_visible": True,
                "no_mojibake": True,
                "no_critical_overlap": True,
                "full_sheet_visible": True,
                "opaque_white_background": True,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = root / "preview.png"
            svg = root / "preview.svg"
            Image.new("RGB", (64, 64), "white").save(png)
            svg.write_text('<svg><rect class="opaque-white-background" fill="#ffffff"/></svg>', encoding="utf-8")
            result = qa.preview_checks(png, svg, review)
        self.assertTrue(result["pass"])
        self.assertEqual(result["evidence"]["acceptance"]["accepted_formats"], ["png"])
        self.assertTrue(result["evidence"]["svg"]["text_may_be_pathized"])

    def test_structurally_valid_preview_without_visual_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "preview.png"
            Image.new("RGB", (64, 64), "white").save(png)
            result = qa.preview_checks(png, None)
        self.assertFalse(result["pass"])

    def test_bounded_normality_and_typed_closure_rule_is_persistent(self):
        rule_ids = [row["id"] for row in self.rules["rules"]]
        lesson_ids = [row["id"] for row in self.rules["historical_errors"]]
        self.assertEqual(rule_ids, [f"PKG-G{index:03d}" for index in range(1, 26)])
        self.assertIn("LESSON-016", lesson_ids)
        self.assertIn("LESSON-017", lesson_ids)
        self.assertIn("LESSON-018", lesson_ids)
        normality = next(row for row in self.rules["rules"] if row["id"] == "PKG-G023")
        self.assertIn("top and bottom closures independently", normality["requirement"])
        self.assertIn("family nullity", normality["prevention"])

    def test_whole_requirement_and_guarded_output_rules_are_persistent(self):
        macro = next(row for row in self.rules["rules"] if row["id"] == "PKG-G024")
        order = next(row for row in self.rules["rules"] if row["id"] == "PKG-G025")
        self.assertIn("Before any line-level", macro["requirement"])
        self.assertIn("Reference images", macro["requirement"])
        self.assertIn("actualBinding", macro["requirement"])
        self.assertIn("boundActual == observed", macro["requirement"])
        self.assertIn("creates no candidate DXF/AICAD/SCR", order["requirement"])
        for relative in (
            "rules/normative_governance_rules.json",
            "rules/drawing_requirement_contract.schema.json",
            "rules/drawing_requirement_trace.schema.json",
            "scripts/aicad_requirement_conformance.py",
            "scripts/aicad_guarded_delivery.py",
            "tests/test_requirement_conformance.py",
            "tests/test_guarded_delivery.py",
        ):
            self.assertTrue((PLUGIN / relative).is_file(), relative)
        trace_schema = (PLUGIN / "rules" / "drawing_requirement_trace.schema.json").read_text(encoding="utf-8")
        validator = (PLUGIN / "scripts" / "aicad_requirement_conformance.py").read_text(encoding="utf-8")
        regression = (PLUGIN / "tests" / "test_requirement_conformance.py").read_text(encoding="utf-8")
        self.assertIn('"actualBinding"', trace_schema)
        self.assertIn('"bindingMatchesObserved"', validator)
        self.assertIn("test_rejects_self_reported_dimension_when_actual_instance_differs", regression)

if __name__ == "__main__":
    unittest.main()
