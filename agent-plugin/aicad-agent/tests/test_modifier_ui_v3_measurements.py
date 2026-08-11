from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" if (ROOT / "runtime" / "src").is_dir() else ROOT.parents[1]
sys.path.insert(0, str(SOURCE / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class PackagedModifierUiV3MeasurementTests(unittest.TestCase):
    def test_packaged_runtime_exposes_exact_measurements_and_coordinate_toggle(self) -> None:
        plan = json.loads((SOURCE / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        schema = json.loads((SOURCE / "schema" / "aicad-view-package.schema.json").read_text(encoding="utf-8"))
        package = generate_view_package(plan, "3d", "mechanical")
        Draft202012Validator(schema).validate(package)
        refs = package["selection_map"]
        self.assertEqual(refs["TOP_F001_P_1"]["measurement"]["length_mm"], 120.0)
        self.assertEqual(refs["TOP_F001_P_2"]["measurement"]["controller_path"], "profile.height")
        self.assertEqual(refs["TOP_F003_CENTER"]["measurement"]["coordinates"], [0.0, 0.0, 12.0])
        self.assertEqual(refs["TOP_F003_C001"]["measurement"]["radius_mm"], 15.0)
        page = render_review_html(package)
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertIn('id="measurement"', page)
        self.assertIn('id="coordinateToggle"', page)
        self.assertIn("drawCoordinateTriad", page)
        self.assertIn("aicad.coordinate-system.visible", page)
        self.assertIn("localStorage.setItem", page)
        self.assertIn("setCoordinateVisible(readCoordinatePreference(),false)", page)
        qa = (ROOT / "scripts" / "aicad_modifier_measurement_qa.cjs").read_text(encoding="utf-8")
        self.assertIn("coordinatesOffPersisted", qa)
        self.assertIn("coordinatesOnPersisted", qa)


if __name__ == "__main__":
    unittest.main()
