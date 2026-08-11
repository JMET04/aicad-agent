from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class ModifierUiV3MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan3d = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.plan2d = json.loads((ROOT / "examples" / "rectangle.plan.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "schema" / "aicad-view-package.schema.json").read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema)

    def test_every_selection_has_strict_model_measurement_contract(self) -> None:
        package = generate_view_package(self.plan3d, "3d", "mechanical")
        self.validator.validate(package)
        self.assertEqual(package["coordinate_system"], {
            "id": "MODEL_XYZ", "type": "cartesian", "handedness": "right",
            "origin": [0.0, 0.0, 0.0],
            "axes": {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]},
            "unit": "mm",
        })
        self.assertTrue(package["selection_map"])
        self.assertTrue(all("measurement" in ref for ref in package["selection_map"].values()))
        broken = copy.deepcopy(package)
        del broken["selection_map"]["TOP_F001_P_1"]["measurement"]
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)

    def test_line_point_circle_values_come_from_compiled_model(self) -> None:
        package = generate_view_package(self.plan3d, "3d", "mechanical")
        refs = package["selection_map"]
        line = refs["SEL3D_F001_PROFILE_EDGE_1"]["measurement"]
        self.assertEqual(line["kind"], "line")
        self.assertEqual(line["length_mm"], 120.0)
        self.assertEqual(line["start"], [-60.0, -40.0, 0.0])
        self.assertEqual(line["end"], [60.0, -40.0, 0.0])
        self.assertEqual(line["controller_path"], "profile.width")

        perpendicular = refs["SEL3D_F001_PROFILE_EDGE_2"]["measurement"]
        self.assertEqual(perpendicular["length_mm"], 80.0)
        self.assertEqual(perpendicular["controller_path"], "profile.height")
        self.assertEqual(refs["SEL3D_F001_PROFILE_EDGE_2"]["edit_paths"], ["profile.center", "profile.height"])

        point = refs["SEL3D_F003_CENTER_POINT"]["measurement"]
        self.assertEqual(point["kind"], "point")
        self.assertEqual(point["coordinates"], [0.0, 0.0, 12.0])
        self.assertEqual(point["controller_path"], "profile.center")

        circle = refs["SEL3D_F003_PROFILE_CIRCLE_1"]["measurement"]
        self.assertEqual(circle["kind"], "circle")
        self.assertEqual(circle["center"], [0.0, 0.0, 12.0])
        self.assertEqual(circle["radius_mm"], 15.0)
        self.assertEqual(circle["diameter_mm"], 30.0)
        self.assertEqual(circle["controller_path"], "profile.radius")

    def test_2d_line_length_and_coordinates_are_authoritative(self) -> None:
        package = generate_view_package(self.plan2d, "2d", "general")
        self.validator.validate(package)
        value = package["selection_map"]["PLAN_L001"]["measurement"]
        self.assertEqual(value["authority"], "authoritative_2d")
        self.assertEqual(value["length_mm"], 120.0)
        self.assertEqual(value["start"], [0.0, 0.0, 0.0])
        self.assertEqual(value["end"], [120.0, 0.0, 0.0])

    def test_review_has_measurement_panel_and_real_coordinate_toggle(self) -> None:
        package = generate_view_package(self.plan3d, "3d", "mechanical")
        page = render_review_html(package)
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertIn('id="measurement"', page)
        self.assertIn('data-measurement-kind', page)
        self.assertIn('id="coordinateToggle"', page)
        self.assertIn('setCoordinateVisible', page)
        self.assertEqual(page.count('class="view-coordinate-triad"'), 6)
        self.assertEqual(page.count('class="model-origin-marker"'), 6)
        self.assertIn("drawCoordinateTriad", page)
        self.assertIn("aicad.coordinate-system.visible", page)
        self.assertIn("localStorage.setItem", page)
        self.assertIn("setCoordinateVisible(readCoordinatePreference(),false)", page)


if __name__ == "__main__":
    unittest.main()
