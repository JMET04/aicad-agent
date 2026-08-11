from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.correction import preview_correction
from aicad.engine3d import compile_plan3d
from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class ModifierUiV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.view_schema = json.loads((ROOT / "schema" / "aicad-view-package.schema.json").read_text(encoding="utf-8"))
        cls.correction_schema = json.loads((ROOT / "schema" / "aicad-correction.schema.json").read_text(encoding="utf-8"))

    def package(self, plan: dict | None = None) -> dict:
        return generate_view_package(plan or self.plan, "3d", "mechanical")

    def test_package_has_core_parameters_and_hidden_key_geometry(self) -> None:
        package = self.package()
        Draft202012Validator(self.view_schema).validate(package)
        objects = {row["source_object_id"]: row for row in package["selector_3d"]["objects"]}
        self.assertEqual([p["path"] for p in objects["F001"]["core_parameters"]], ["profile.center", "profile.width", "profile.height", "depth"])
        self.assertEqual([p["path"] for p in objects["F002"]["core_parameters"]], ["profile.center", "profile.radius", "profile.count", "profile.bolt_circle_radius", "profile.start_angle_deg", "depth"])
        refs = {s["reference_key"]: s for o in objects.values() for s in o["subobjects"]}
        self.assertEqual(refs["F003|profile.center"]["geometry_type"], "point")
        self.assertTrue(refs["F003|profile.center"]["key_geometry"])
        self.assertEqual(refs["F002|profile.pattern.pitch_circle"]["edit_scope"], "shared_pattern_parameter")
        self.assertEqual(refs["F001|feature.axis.center.xz"]["relation_capabilities"], [])
        key_entities = [e for v in package["views"] for e in v["entities"] if e.get("key_geometry")]
        self.assertGreaterEqual(len(key_entities), 13)
        self.assertTrue(any(e["source_subobject"] == "profile.pattern.pitch_circle" for e in key_entities))

    def test_visible_ui_is_simplified_and_contains_free_section(self) -> None:
        page = render_review_html(self.package())
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertIn("修改清单", page)
        self.assertIn("核心参数", page)
        self.assertIn("自由截面", page)
        self.assertIn("parseRequest", page)
        self.assertIn("profile.pattern.pitch_circle", page)
        self.assertIn("entity-pair.key-geometry .view-entity{opacity:0}", page)
        self.assertIn("parameter-row", page)
        self.assertNotIn("纠错意图", page)
        self.assertNotIn("正式事务", page)

    def test_pattern_controller_can_change_count_and_start_angle(self) -> None:
        package = self.package()
        ref = next(s for o in package["selector_3d"]["objects"] for s in o["subobjects"] if s["reference_key"] == "F002|profile.pattern.pitch_circle")
        selected_ref = {key: ref[key] for key in ("reference_key", "source_object_id", "source_subobject", "geometry_type", "edit_paths")}
        operations = []
        for path, value in (("profile.count", 2), ("profile.start_angle_deg", 50)):
            operations.append({
                "op": "set_subobject_parameter", "reference_key": ref["reference_key"], "path": path, "value": value,
                "scope": "shared_parameter_group", "expected_affected_instance_count": 4,
                "expected_shared_parameter_groups": ref["shared_parameter_groups"],
            })
        transaction = {
            "schema_version": "1.0", "source_sha256": compile_plan3d(self.plan).source_hash,
            "correction": {"id": "UIV2", "description": "pattern controller update", "space": "3d", "selected_ids": ["F002"], "selected_refs": [selected_ref], "operations": operations},
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
        }
        Draft202012Validator(self.correction_schema).validate(transaction)
        result = preview_correction(copy.deepcopy(self.plan), transaction, "mechanical")
        feature = result["candidate_plan"]["features"][1]
        self.assertEqual(feature["profile"]["count"], 2)
        self.assertEqual(feature["profile"]["start_angle_deg"], 50)
        self.assertEqual(next(c for c in feature["constraints"] if c["kind"] == "pattern_count")["value"], 2)

    def test_point_coincident_relation_is_a_real_backend_operation(self) -> None:
        plan = copy.deepcopy(self.plan)
        feature = plan["features"][2]
        feature["profile"]["center"] = [4, 2]
        center = next(c for c in feature["constraints"] if c["kind"] == "center_offset")
        center["dx"], center["dy"] = 4, 2
        package = self.package(plan)
        refs = {s["reference_key"]: s for o in package["selector_3d"]["objects"] for s in o["subobjects"]}
        fixed, movable = refs["F001|profile.center"], refs["F003|profile.center"]
        selected = [{key: row[key] for key in ("reference_key", "source_object_id", "source_subobject", "geometry_type", "edit_paths")} for row in (fixed, movable)]
        transaction = {
            "schema_version": "1.0", "source_sha256": compile_plan3d(plan).source_hash,
            "correction": {"id": "POINTREL", "description": "center coincidence", "space": "3d", "selected_ids": ["F001", "F003"], "selected_refs": selected, "operations": [{"op": "add_subobject_relation", "relation": "coincident", "members": [fixed["reference_key"], movable["reference_key"]], "scope": "feature", "expected_affected_instance_count": 1}]},
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
        }
        Draft202012Validator(self.correction_schema).validate(transaction)
        result = preview_correction(plan, transaction, "mechanical")
        self.assertEqual(result["candidate_plan"]["features"][2]["profile"]["center"], [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
