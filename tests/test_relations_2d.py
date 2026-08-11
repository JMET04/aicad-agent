from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.correction import preview_correction
from aicad.engine import PlanError, compile_plan


def two_lines() -> dict:
    return {
        "schema_version": "2.0",
        "drawing": {"name": "relation_fixture", "domain": "mechanical", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
        "steps": [
            {
                "id": "L001", "type": "line", "purpose": "primary datum", "reasoning": "origin horizontal datum",
                "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 40, "dy": 0},
                "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 40}], "layer": "DATUM",
            },
            {
                "id": "L002", "type": "line", "purpose": "secondary edge", "reasoning": "offset candidate awaiting a selected relation",
                "start": {"point": [10, 10]}, "construction": {"kind": "vector", "dx": 20, "dy": 5},
                "constraints": [
                    {"kind": "start_offset", "target": "L001.start", "dx": 10, "dy": 10},
                    {"kind": "length", "value": math.hypot(20, 5)},
                ],
                "layer": "OUTLINE",
            },
        ],
    }


def correction(relation: str) -> dict:
    return {
        "schema_version": "1.0",
        "correction": {
            "id": "CORR_REL_001", "description": f"make selected lines {relation}", "space": "2d",
            "selected_ids": ["L001", "L002"],
            "operations": [{"op": "add_relation", "relation": relation, "members": ["L001", "L002"]}],
        },
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
    }


class RelationCorrection2DTests(unittest.TestCase):
    def test_collinear_projects_only_later_line_and_preserves_length(self) -> None:
        result = preview_correction(two_lines(), correction("collinear"), "mechanical")
        self.assertEqual(result["directly_changed_ids"], ["L002"])
        self.assertEqual(result["affected_ids"], ["L002"])
        item = result["candidate_plan"]["steps"][1]
        self.assertAlmostEqual(item["start"]["point"][0], 10.0)
        self.assertAlmostEqual(item["start"]["point"][1], 0.0)
        self.assertEqual(item["construction"]["kind"], "parallel")
        self.assertEqual(next(value for value in item["constraints"] if value["kind"] == "collinear")["target"], "L001")
        compiled = compile_plan(result["candidate_plan"])
        self.assertAlmostEqual(compiled.lines[1].length, math.hypot(20, 5))
        self.assertEqual(compiled.lines[1].depends_on, ("L001",))

    def test_false_declared_collinearity_is_rejected(self) -> None:
        source = two_lines()
        source["steps"][1]["constraints"].append({"kind": "collinear", "target": "L001"})
        with self.assertRaisesRegex(PlanError, "violates collinear"):
            compile_plan(source)

    def test_locked_placement_cannot_be_moved_to_collinear(self) -> None:
        value = correction("collinear")
        value["locks"] = ["L002.start"]
        with self.assertRaisesRegex(PlanError, "locked line placement"):
            preview_correction(two_lines(), value, "mechanical")


if __name__ == "__main__":
    unittest.main()
