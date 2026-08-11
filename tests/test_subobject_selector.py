from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class PreciseSubobjectSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "schema" / "aicad-view-package.schema.json").read_text(encoding="utf-8"))

    def test_selector_uses_unique_object_plus_subobject_references(self) -> None:
        package = generate_view_package(self.plan, "3d", "mechanical")
        Draft202012Validator(self.schema).validate(package)
        subobjects = [
            subobject
            for item in package["selector_3d"]["objects"]
            for subobject in item["subobjects"]
        ]
        keys = [item["reference_key"] for item in subobjects]
        self.assertEqual(len(subobjects), 61)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all("|" in key for key in keys))
        self.assertFalse(package["selector_3d"]["topology_authority"])
        by_key = {item["reference_key"]: item for item in subobjects}
        self.assertEqual(by_key["F001|profile.edge.1"]["edit_scope"], "subobject_parameterized")
        self.assertTrue(by_key["F001|profile.edge.1"]["requires_preserve_policy"])
        self.assertEqual(by_key["F002|profile.circle.1"]["edit_scope"], "shared_pattern_parameter")
        self.assertEqual(by_key["F002|profile.circle.1"]["affected_instance_count"], 4)
        self.assertFalse(by_key["F002|profile.circle.1"]["detach_supported"])

    def test_same_edge_maps_between_native_profile_view_and_3d_selector(self) -> None:
        package = generate_view_package(self.plan, "3d", "mechanical")
        top = package["selection_map"]["TOP_F001_P_1"]
        selector = package["selection_map"]["SEL3D_F001_PROFILE_EDGE_1"]
        self.assertEqual(top["reference_key"], "F001|profile.edge.1")
        self.assertEqual(top["reference_key"], selector["reference_key"])
        self.assertEqual(top["geometry_type"], "line")
        self.assertEqual(selector["geometry_type"], "line")

    def test_visual_stroke_is_decoupled_from_click_tolerance(self) -> None:
        package = generate_view_package(self.plan, "3d", "mechanical")
        page = render_review_html(package)
        line_count = sum(
            entity["geometry"]["type"] == "line"
            for view in package["views"]
            for entity in view["entities"]
        )
        circle_count = sum(
            entity["geometry"]["type"] == "circle"
            for view in package["views"]
            for entity in view["entities"]
        )
        point_count = sum(
            entity["geometry"]["type"] == "point"
            for view in package["views"]
            for entity in view["entities"]
        )
        self.assertEqual(page.count('<polygon class="view-hit"'), line_count)
        self.assertEqual(page.count('<circle class="view-hit"'), circle_count)
        self.assertEqual(page.count('<circle class="view-hit point-hit"'), point_count)
        self.assertIn("stroke-width:.8", page)
        self.assertIn("stroke-width:12", page)
        self.assertIn("document.querySelectorAll('.view-hit')", page)
        self.assertIn("source_subobject", page)
        self.assertIn("add_subobject_relation", page)
        self.assertIn("relation_capabilities", page)
        self.assertIn("affected_instance_count", page)
        self.assertIn("\u4fdd\u6301\u5bf9\u8fb9", page)

    def test_utf8_gate_rejects_mojibake_before_artifact_write(self) -> None:
        package = generate_view_package(self.plan, "3d", "mechanical")
        page = render_review_html(package)
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertIn("\u53ef\u65cb\u8f6c\u4e09\u7ef4\u9009\u62e9\u5668", page)
        self.assertIn("\u70b9\u9009\u7ebf\u3001\u9762\u3001\u4e2d\u5fc3\u6216\u53c2\u6570\u5f00\u59cb\u4fee\u6539", page)
        corrupted = page.replace("\u5f53\u524d\u5bf9\u8c61", "\u951f\u65a4\u62f7", 1)
        issues = validate_review_html(corrupted, "3d")
        self.assertTrue(any(item.startswith("suspected_mojibake") for item in issues))
        self.assertTrue(any(item.startswith("missing_visible_text") for item in issues))


if __name__ == "__main__":
    unittest.main()
