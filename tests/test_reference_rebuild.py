from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.engine import PlanError, compile_plan
from aicad.reference_rebuild import (
    build_reference_reconstruction,
    render_reference_svg,
    solve_reference_calibration,
    validate_reference_rebuild,
)


class ReferenceRebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan_data = json.loads((ROOT / "examples" / "web_reference_plate.plan.json").read_text(encoding="utf-8"))
        cls.spec = json.loads((ROOT / "examples" / "web_reference_plate.reference.json").read_text(encoding="utf-8"))
        cls.spec["reference"]["locator"] = str((ROOT / "examples" / "web_reference_plate.html").resolve())
        cls.schema = json.loads((ROOT / "schema" / "aicad-reference-rebuild.schema.json").read_text(encoding="utf-8"))

    def test_schema_and_calibration_are_exact(self) -> None:
        Draft202012Validator(self.schema).validate(self.spec)
        result = solve_reference_calibration(self.spec)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["scale_cad_per_source_unit"], 1.0, places=12)
        self.assertAlmostEqual(result["rms_error_mm"], 0.0, places=12)
        self.assertEqual(result["axis_orientation"], "y_down")

    def test_dom_geometry_text_layout_and_style_are_verified(self) -> None:
        result = validate_reference_rebuild(self.plan_data, self.spec)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["source_hash_verified"])
        self.assertTrue(result["checks"]["reference_dom_catalog_verified"])
        self.assertTrue(result["checks"]["source_text_encoding_valid"])
        self.assertTrue(result["checks"]["annotation_layout_matches_reference"])
        self.assertTrue(result["checks"]["drafting_style_hierarchy_valid"])
        self.assertEqual(result["reference_dom_object_count"], 10)
        self.assertEqual(result["coverage"]["missing_targets"], [])
        self.assertEqual(len(result["geometry_bindings"]), 5)
        self.assertTrue(all(row["ok"] and row["source_catalog_ok"] for row in result["geometry_bindings"]))
        self.assertTrue(all(item["ok"] for item in result["annotation_source_checks"]))
        self.assertTrue(all(item["ok"] for item in result["layout_checks"]))
        height_layout = next(item for item in result["layout_checks"] if item["id"] == "DIM_HEIGHT")
        self.assertEqual(height_layout["actual_rotation_deg"], 90.0)
        status_layout = next(item for item in result["layout_checks"] if item["id"] == "TXT_STATUS")
        self.assertEqual(status_layout["layout_mode"], "optimized_offset")
        self.assertEqual(status_layout["layout_offset_mm"], [0.0, -2.0])
        self.assertTrue(all(item["ok"] for item in result["dimension_checks"]))
        self.assertEqual(result["annotation_overlap_pairs"], [])
        self.assertEqual(result["text_encoding_issues"], [])

    def test_missing_local_vector_source_fails_closed(self) -> None:
        missing = copy.deepcopy(self.spec)
        missing["reference"]["locator"] = str(ROOT / "examples" / "missing-reference.svg")
        result = validate_reference_rebuild(self.plan_data, missing)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["source_content_hash_verified"])
        self.assertFalse(result["checks"]["reference_dom_catalog_verified"])
    def test_pixel_truth_is_rejected_and_geometry_drift_fails_dom_gate(self) -> None:
        unsafe = copy.deepcopy(self.spec)
        unsafe["dimension_authority"]["pixel_is_dimension_truth"] = True
        with self.assertRaisesRegex(PlanError, "pixel_is_dimension_truth"):
            validate_reference_rebuild(self.plan_data, unsafe)
        drifted = copy.deepcopy(self.spec)
        drifted["geometry_bindings"][0]["source_geometry"]["end"][0] += 0.5
        result = validate_reference_rebuild(self.plan_data, drifted)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["reference_dom_catalog_verified"])
        self.assertFalse(result["checks"]["geometry_bindings_match"])

    def test_reference_text_drift_fails_dom_gate(self) -> None:
        drifted = copy.deepcopy(self.spec)
        drifted["presentation"]["annotations"][0]["reference_text"] += "X"
        result = validate_reference_rebuild(self.plan_data, drifted)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["reference_dom_catalog_verified"])

    def test_annotation_layout_drift_fails(self) -> None:
        drifted = copy.deepcopy(self.spec)
        drifted["presentation"]["annotations"][0]["position"][0] += 2
        result = validate_reference_rebuild(self.plan_data, drifted)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["annotation_layout_matches_reference"])

    def test_optimized_layout_offset_over_budget_fails(self) -> None:
        drifted = copy.deepcopy(self.spec)
        status = next(item for item in drifted["presentation"]["annotations"] if item["id"] == "TXT_STATUS")
        status["max_layout_offset_mm"] = 1
        result = validate_reference_rebuild(self.plan_data, drifted)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["annotation_layout_policy_valid"])
    def test_mojibake_private_use_character_fails(self) -> None:
        drifted = copy.deepcopy(self.spec)
        drifted["presentation"]["annotations"][0]["text"] += "\ue000"
        result = validate_reference_rebuild(self.plan_data, drifted)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["source_text_encoding_valid"])
        self.assertTrue(result["text_encoding_issues"])

    def test_native_dimension_plan_fails_closed_in_legacy_reference_renderer(self) -> None:
        native = json.loads((ROOT / "examples" / "architecture-dimensions.plan.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(PlanError, "native TEXT/DIMENSION"):
            validate_reference_rebuild(native, self.spec)

    def test_build_writes_ascii_safe_annotated_dxf_and_native_svg_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = build_reference_reconstruction(self.plan_data, self.spec, Path(directory), "plate")
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["dxf_entity_counts"]["line"], 4)
            self.assertEqual(result["dxf_entity_counts"]["circle"], 1)
            self.assertEqual(result["dxf_entity_counts"]["mtext"], 5)
            dxf = Path(result["artifacts"]["dxf"]).read_text(encoding="ascii")
            self.assertIn("\\U+673A\\U+68B0", dxf)
            self.assertIn("\n50\n90\n", dxf)
            self.assertIn("\nDIMENSION\n", dxf)
            self.assertIn("\nTEXT\n", dxf)
            svg = Path(result["artifacts"]["preview_svg"]).read_text(encoding="utf-8")
            self.assertIn("<text", svg)
            self.assertIn('transform="rotate(-90', svg)
            self.assertIn('preserveAspectRatio="xMidYMid meet"', svg)
            self.assertIn("\u673a\u68b0\u5b89\u88c5\u677f", svg)
            self.assertIn('fill="#ffffff"', svg)
            manifest = json.loads(Path(result["artifacts"]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["geometry_scale"], "1:1 model units")
            self.assertFalse(manifest["accepted"])

    def test_svg_is_generated_from_compiled_plan_not_reference_pixels(self) -> None:
        plan = compile_plan(self.plan_data)
        validation = validate_reference_rebuild(self.plan_data, self.spec)
        svg = render_reference_svg(plan, self.spec, validation)
        self.assertEqual(svg.count("data-object-id="), 5)
        self.assertIn('data-object-id="L001"', svg)
        self.assertIn('data-object-id="C001"', svg)
        self.assertIn("pixels not dimension truth", svg)


if __name__ == "__main__":
    unittest.main()