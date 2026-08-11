from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.correction import PlanError, preview_correction
from aicad.engine3d import compile_plan3d
from aicad.viewmap import generate_view_package


def rectangle_stack_plan() -> dict:
    return {
        "schema_version": "1.0",
        "part": {"name": "rectangle_stack", "units": "mm", "origin": [0, 0, 0], "tolerance": 0.001},
        "features": [
            {
                "id": "F001", "type": "base_extrude", "purpose": "datum plate",
                "reasoning": "Origin-centered base establishes the immutable global datum.",
                "depends_on": [], "profile": {"kind": "center_rectangle", "center": [0, 0], "width": 120, "height": 80},
                "depth": 12, "end_condition": "blind",
                "constraints": [
                    {"kind": "center_offset", "target": "origin", "dx": 0, "dy": 0},
                    {"kind": "width", "value": 120}, {"kind": "height", "value": 80}, {"kind": "depth", "value": 12},
                ],
            },
            {
                "id": "F002", "type": "boss_extrude", "purpose": "movable child pad",
                "reasoning": "The child pad exercises exact edge edits without moving the global datum feature.",
                "depends_on": ["F001"], "support_feature": "F001",
                "profile": {"kind": "center_rectangle", "center": [0, 0], "width": 40, "height": 20},
                "depth": 5, "end_condition": "blind",
                "constraints": [
                    {"kind": "support_coincident", "target": "F001"},
                    {"kind": "center_offset", "target": "origin", "dx": 0, "dy": 0},
                    {"kind": "width", "value": 40}, {"kind": "height", "value": 20}, {"kind": "depth", "value": 5},
                ],
            },
        ],
    }


class ExactSubobjectCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mounting = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "schema" / "aicad-correction.schema.json").read_text(encoding="utf-8"))

    def metadata(self, plan: dict, *keys: str) -> list[dict]:
        package = generate_view_package(plan, "3d", "mechanical")
        rows = {
            row["reference_key"]: row
            for item in package["selector_3d"]["objects"]
            for row in item["subobjects"]
        }
        return [rows[key] for key in keys]

    def transaction(self, plan: dict, refs: list[dict], operations: list[dict], **extra: object) -> dict:
        selected_refs = [
            {
                "reference_key": row["reference_key"], "source_object_id": row["source_object_id"],
                "source_subobject": row["source_subobject"], "geometry_type": row["geometry_type"],
                "edit_paths": row["edit_paths"],
            }
            for row in refs
        ]
        value = {
            "schema_version": "1.0", "source_sha256": compile_plan3d(plan).source_hash,
            "correction": {
                "id": "SUB001", "description": "exact semantic subobject correction", "space": "3d",
                "selected_ids": sorted({row["source_object_id"] for row in refs}),
                "selected_refs": selected_refs, "operations": operations,
            },
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
        }
        value.update(extra)
        Draft202012Validator(self.schema).validate(value)
        return value

    def test_child_edge_absolute_move_keeps_opposite_edge_exactly(self) -> None:
        plan = rectangle_stack_plan()
        ref = self.metadata(plan, "F002|profile.edge.1")[0]
        operation = {
            "op": "move_subobject", "reference_key": ref["reference_key"], "axis": "y",
            "value": -15, "value_mode": "absolute", "preserve_policy": "keep_opposite",
            "scope": "subobject", "expected_affected_instance_count": 1,
        }
        result = preview_correction(plan, self.transaction(plan, [ref], [operation]), "mechanical")
        feature = result["candidate_plan"]["features"][1]
        self.assertEqual(feature["profile"]["height"], 25.0)
        self.assertEqual(feature["profile"]["center"], [0, -2.5])
        self.assertEqual(feature["constraints"][2]["value"], 40)
        self.assertEqual(feature["constraints"][3]["value"], 25.0)
        self.assertEqual(feature["constraints"][1]["dy"], -2.5)
        evidence = result["subobject_transactions"][0]
        self.assertEqual(evidence["old_coordinate"], -10.0)
        self.assertEqual(evidence["new_coordinate"], -15.0)
        self.assertEqual(evidence["preserve_policy"], "keep_opposite")

    def test_base_edge_move_that_breaks_origin_datum_fails_closed(self) -> None:
        plan = rectangle_stack_plan()
        ref = self.metadata(plan, "F001|profile.edge.1")[0]
        operation = {
            "op": "move_subobject", "reference_key": ref["reference_key"], "axis": "y",
            "value": -45, "value_mode": "absolute", "preserve_policy": "keep_opposite",
            "scope": "subobject", "expected_affected_instance_count": 1,
        }
        with self.assertRaisesRegex(PlanError, "base profile center must be origin"):
            preview_correction(plan, self.transaction(plan, [ref], [operation]), "mechanical")

    def test_missing_preserve_policy_is_schema_rejected(self) -> None:
        plan = rectangle_stack_plan()
        ref = self.metadata(plan, "F002|profile.edge.1")[0]
        operation = {
            "op": "move_subobject", "reference_key": ref["reference_key"], "axis": "y",
            "value": -2, "value_mode": "delta", "scope": "subobject",
            "expected_affected_instance_count": 1,
        }
        value = self.transaction(plan, [ref], [{**operation, "preserve_policy": "keep_center"}])
        del value["correction"]["operations"][0]["preserve_policy"]
        errors = list(Draft202012Validator(self.schema).iter_errors(value))
        self.assertTrue(errors)

    def test_pattern_circle_radius_requires_explicit_shared_scope(self) -> None:
        plan = copy.deepcopy(self.mounting)
        ref = self.metadata(plan, "F002|profile.circle.1")[0]
        operation = {
            "op": "set_subobject_parameter", "reference_key": ref["reference_key"],
            "path": "profile.radius", "value": 6, "scope": "shared_parameter_group",
            "expected_affected_instance_count": 4,
            "expected_shared_parameter_groups": ref["shared_parameter_groups"],
        }
        result = preview_correction(plan, self.transaction(plan, [ref], [operation]), "mechanical")
        feature = result["candidate_plan"]["features"][1]
        self.assertEqual(feature["profile"]["radius"], 6)
        self.assertEqual(next(row for row in feature["constraints"] if row["kind"] == "radius")["value"], 6)
        evidence = result["subobject_transactions"][0]
        self.assertEqual(evidence["affected_instance_count"], 4)
        self.assertEqual(evidence["scope"], "shared_parameter_group")

        wrong = copy.deepcopy(operation)
        wrong["scope"] = "subobject"
        with self.assertRaisesRegex(PlanError, "shared_parameter_group"):
            preview_correction(plan, self.transaction(plan, [ref], [wrong]), "mechanical")

    def test_pattern_instance_detach_is_never_silent(self) -> None:
        plan = copy.deepcopy(self.mounting)
        ref = self.metadata(plan, "F002|profile.circle.1")[0]
        operation = {
            "op": "set_subobject_parameter", "reference_key": ref["reference_key"],
            "path": "profile.radius", "value": 6, "scope": "detached_instance",
            "expected_affected_instance_count": 4,
            "expected_shared_parameter_groups": ref["shared_parameter_groups"],
        }
        with self.assertRaisesRegex(PlanError, "detached_instance is unsupported"):
            preview_correction(plan, self.transaction(plan, [ref], [operation]), "mechanical")

    def test_stale_source_hash_and_reference_metadata_are_rejected(self) -> None:
        plan = rectangle_stack_plan()
        ref = self.metadata(plan, "F002|profile.edge.1")[0]
        operation = {
            "op": "move_subobject", "reference_key": ref["reference_key"], "axis": "y",
            "value": -12, "value_mode": "absolute", "preserve_policy": "keep_center",
            "scope": "subobject", "expected_affected_instance_count": 1,
        }
        value = self.transaction(plan, [ref], [operation])
        value["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(PlanError, "source_sha256"):
            preview_correction(plan, value, "mechanical")
        value = self.transaction(plan, [ref], [operation])
        value["correction"]["selected_refs"][0]["source_subobject"] = "profile.edge.3"
        with self.assertRaisesRegex(PlanError, "stale source_subobject"):
            preview_correction(plan, value, "mechanical")

    def test_equal_radius_that_removes_supporting_boss_is_rejected(self) -> None:
        plan = copy.deepcopy(self.mounting)
        fixed, movable = self.metadata(plan, "F003|profile.circle.1", "F004|profile.circle.1")
        operation = {
            "op": "add_subobject_relation", "relation": "equal_radius",
            "members": [fixed["reference_key"], movable["reference_key"]],
            "scope": "feature", "expected_affected_instance_count": 1,
        }
        with self.assertRaisesRegex(PlanError, "positive residual wall"):
            preview_correction(plan, self.transaction(plan, [fixed, movable], [operation]), "mechanical")

    def test_already_concentric_circles_are_audited_without_fake_change(self) -> None:
        plan = copy.deepcopy(self.mounting)
        fixed, movable = self.metadata(plan, "F003|profile.circle.1", "F004|profile.circle.1")
        operation = {
            "op": "add_subobject_relation", "relation": "concentric",
            "members": [fixed["reference_key"], movable["reference_key"]],
            "scope": "feature", "expected_affected_instance_count": 1,
        }
        result = preview_correction(plan, self.transaction(plan, [fixed, movable], [operation]), "mechanical")
        self.assertEqual(result["directly_changed_ids"], [])
        self.assertEqual(result["change_count"], 0)
        self.assertEqual(result["subobject_transactions"][0]["status"], "already_satisfied")

    def test_already_satisfied_axis_relation_is_audited_without_fake_geometry_change(self) -> None:
        plan = rectangle_stack_plan()
        first, second = self.metadata(plan, "F001|profile.edge.1", "F002|profile.edge.1")
        operation = {
            "op": "add_subobject_relation", "relation": "parallel",
            "members": [first["reference_key"], second["reference_key"]],
            "scope": "feature", "expected_affected_instance_count": 1,
        }
        result = preview_correction(plan, self.transaction(plan, [first, second], [operation]), "mechanical")
        self.assertEqual(result["directly_changed_ids"], [])
        self.assertEqual(result["change_count"], 0)
        self.assertEqual(result["subobject_transactions"][0]["status"], "already_satisfied_by_axis_aligned_profile")


if __name__ == "__main__":
    unittest.main()
