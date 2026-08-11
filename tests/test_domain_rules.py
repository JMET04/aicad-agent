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

from aicad.domain_rules import HOST_CAPABILITIES, evaluate_domain_plan, write_domain_validation


def electronics_board() -> dict:
    return {
        "schema_version": "2.0",
        "drawing": {"name": "pcb", "domain": "electronics", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
        "steps": [
            {"id": "L001", "type": "line", "purpose": "board bottom", "reasoning": "origin datum edge", "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 100, "dy": 0}, "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 100}], "layer": "BOARD_OUTLINE", "role": "board_outline"},
            {"id": "L002", "type": "line", "purpose": "board right", "reasoning": "perpendicular boundary", "start": {"ref": "L001.end"}, "construction": {"kind": "perpendicular", "to": "L001", "length": 60, "turn": "left"}, "constraints": [{"kind": "start_coincident", "target": "L001.end"}, {"kind": "perpendicular", "target": "L001"}, {"kind": "length", "value": 60}], "layer": "BOARD_OUTLINE", "role": "board_outline"},
            {"id": "L003", "type": "line", "purpose": "board top", "reasoning": "parallel opposite boundary", "start": {"ref": "L002.end"}, "construction": {"kind": "parallel", "to": "L001", "length": 100, "direction": "opposite"}, "constraints": [{"kind": "start_coincident", "target": "L002.end"}, {"kind": "parallel", "target": "L001"}, {"kind": "length", "value": 100}], "layer": "BOARD_OUTLINE", "role": "board_outline"},
            {"id": "L004", "type": "line", "purpose": "board left", "reasoning": "close the boundary", "start": {"ref": "L003.end"}, "construction": {"kind": "to_point", "target": {"ref": "L001.start"}}, "constraints": [{"kind": "start_coincident", "target": "L003.end"}, {"kind": "end_coincident", "target": "L001.start"}, {"kind": "perpendicular", "target": "L001"}, {"kind": "length", "value": 60}], "layer": "BOARD_OUTLINE", "role": "board_outline"},
            {"id": "C001", "type": "circle", "purpose": "mounting hole", "reasoning": "fixed board corner offset", "center": {"point": [10, 10]}, "radius": 2, "constraints": [{"kind": "center_offset", "target": "L001.start", "dx": 10, "dy": 10}, {"kind": "diameter", "value": 4}], "layer": "HOLE", "role": "mounting_hole"}
        ]
    }


class DomainRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((ROOT / "schema" / "aicad-domain-validation.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)

    def test_valid_electronics_plan_passes_role_layer_kind_and_closure(self) -> None:
        report = evaluate_domain_plan(electronics_board(), "2d")
        Draft202012Validator(self.schema).validate(report)
        self.assertEqual(report["status"], "passed")
        closure = next(item for item in report["checks"] if item["id"] == "DOMAIN.2D.CLOSED.BOARD_OUTLINE")
        self.assertEqual(closure["status"], "pass")
        self.assertTrue(report["summary"]["manual_review_required"])

    def test_wrong_kind_and_layer_fail_with_root_cause_and_prevention(self) -> None:
        source = electronics_board()
        source["steps"][1]["role"] = "mounting_hole"
        source["steps"][1]["layer"] = "WALL"
        report = evaluate_domain_plan(source, "2d")
        self.assertEqual(report["status"], "failed")
        failures = [item for item in report["checks"] if item["status"] == "fail"]
        self.assertGreaterEqual(len(failures), 2)
        self.assertTrue(all(item["root_cause"] for item in failures))
        self.assertTrue(all(item["prevention_rule_candidate"]["ruleEnabled"] is False for item in failures))

    def test_mechanical_3d_feature_roles_are_checked(self) -> None:
        source = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        source["part"]["domain"] = "mechanical"
        roles = ("body", "mounting_hole", "boss", "hole")
        for feature, role in zip(source["features"], roles):
            feature["role"] = role
        report = evaluate_domain_plan(source, "3d")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["capability_boundary"]["native"]["profiles"], ["center_rectangle", "circle", "circle_pattern"])
        self.assertIn("native_sheet_metal", report["capability_boundary"]["native"]["not_supported"])

    def test_validation_artifacts_are_machine_and_human_readable(self) -> None:
        source = electronics_board()
        source["steps"][4]["layer"] = "PAD"
        with tempfile.TemporaryDirectory() as directory:
            result = write_domain_validation(source, "2d", Path(directory), "pcb")
            payload = json.loads(Path(result["validation"]).read_text(encoding="utf-8"))
            markdown = Path(result["audit"]).read_text(encoding="utf-8")
            self.assertEqual(payload["status"], "failed")
            self.assertIn("Root cause:", markdown)
            self.assertIn("Prevention candidate (disabled):", markdown)

    def test_autocad_capability_matrix_matches_protocol3_host_evidence(self) -> None:
        host = HOST_CAPABILITIES["autocad_2025"]
        self.assertIn("text", host["supported"])
        self.assertIn("aicad_protocol_v3_semantic_layers", host["supported"])
        self.assertIn("native_linetype_and_lineweight", host["supported"])
        self.assertIn("aicad_xdata_save_reopen", host["supported"])
        self.assertNotIn("per_entity_layer_in_aicad_protocol_v2", host["not_supported"])


if __name__ == "__main__":
    unittest.main()
