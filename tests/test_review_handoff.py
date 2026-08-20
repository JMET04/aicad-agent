from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.correction import preview_correction
from aicad.engine import PlanError, compile_plan
from aicad.natural import offline_plan
from aicad.review_handoff import apply_review_handoff, validate_review_handoff
from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


def load_agent():
    script = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_review_handoff_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("agent plugin script is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def handoff(plan: dict, operations: list[dict], selected_ids: list[str], instructions: list[dict] | None = None) -> dict:
    source_hash = compile_plan(plan).source_hash
    transaction = {
        "schema_version": "1.0",
        "source_sha256": source_hash,
        "correction": {
            "id": "HANDOFF_TEST",
            "description": "interactive 2D review correction",
            "space": "2d",
            "selected_ids": selected_ids,
            "selected_refs": [],
            "operations": operations,
        },
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
    }
    return {
        "handoff_schema_version": "1.0",
        "source_sha256": source_hash,
        "space": "2d",
        "domain": "general",
        "instructions": instructions or [],
        "exact_transaction": transaction if operations else None,
        "agent_action": "validate then apply and reopen",
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
    }


class ReviewHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = offline_plan("120x80 plate diameter 20")
        cls.schema = json.loads((ROOT / "schema" / "aicad-review-handoff.schema.json").read_text(encoding="utf-8"))

    def test_2d_modifier_emits_supported_operations_and_host_bridges(self) -> None:
        package = generate_view_package(self.plan, "2d", "general")
        page = render_review_html(package)
        self.assertEqual(validate_review_html(page, "2d"), [])
        self.assertIn("pkg.space==='2d'?{op:'set_parameter'", page)
        self.assertIn("{op:'add_relation',relation,members}", page)
        self.assertIn('id="submitRequest"', page)
        self.assertIn("aicad:review-handoff", page)
        self.assertIn("chrome?.webview?.postMessage", page)
        self.assertIn("parent.postMessage", page)
        self.assertIn("aicad_apply_review_handoff", page)
        self.assertNotIn('["start", "construction"]', str(package["views"]))
        line = package["selection_map"]["PLAN_L001"]
        self.assertEqual(line["placement_path"], "start")
        self.assertEqual(line["placement_point"], [0.0, 0.0])

    def test_2d_radius_handoff_applies_and_regenerates_modifier(self) -> None:
        value = handoff(
            self.plan,
            [{"op": "set_parameter", "target": "C001", "path": "radius", "value": 12}],
            ["C001"],
        )
        Draft202012Validator(self.schema).validate(value)
        report = validate_review_handoff(self.plan, value)
        self.assertTrue(report["actionable"])
        with tempfile.TemporaryDirectory() as directory:
            result = apply_review_handoff(self.plan, value, Path(directory), "plate")
            self.assertEqual(result["status"], "applied_review_candidate")
            corrected = json.loads(Path(result["artifacts"]["plan"]).read_text(encoding="utf-8"))
            circle = next(item for item in corrected["steps"] if item["id"] == "C001")
            self.assertEqual(circle["radius"], 12)
            review = Path(result["artifacts"]["review_html"])
            self.assertTrue(review.is_file())
            self.assertEqual(validate_review_html(review.read_text(encoding="utf-8"), "2d"), [])
            receipt = json.loads(Path(result["artifacts"]["receipt"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["candidate_sha256"], result["candidate_sha256"])

    def test_2d_anchor_and_text_parameter_edits_sync_constraints(self) -> None:
        plan = {
            "schema_version": "2.0",
            "drawing": {"name": "editable_2d", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
            "steps": [
                {
                    "id": "L001", "type": "line", "purpose": "datum", "reasoning": "origin datum",
                    "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 40, "dy": 0},
                    "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 40}, {"kind": "start_coincident", "target": "origin"}],
                },
                {
                    "id": "L002", "type": "line", "purpose": "movable", "reasoning": "tests bounded placement",
                    "start": {"ref": "L001.end"}, "construction": {"kind": "polar", "length": 20, "angle_deg": 90},
                    "constraints": [{"kind": "start_coincident", "target": "L001.end"}, {"kind": "length", "value": 20}],
                },
                {
                    "id": "T001", "type": "text", "purpose": "editable label", "reasoning": "tests text parameter replay",
                    "insert": {"ref": "L002.end"}, "value": "A", "height": 4, "rotation_deg": 0,
                    "constraints": [{"kind": "position_coincident", "target": "L002.end"}, {"kind": "text_height", "value": 4}, {"kind": "rotation", "value": 0}],
                },
            ],
        }
        transaction = handoff(
            plan,
            [
                {"op": "set_parameter", "target": "L002", "path": "start", "value": {"point": [50, 10]}},
                {"op": "set_parameter", "target": "L002", "path": "construction.length", "value": 25},
                {"op": "set_parameter", "target": "T001", "path": "insert", "value": {"point": [70, 15]}},
                {"op": "set_parameter", "target": "T001", "path": "height", "value": 6},
                {"op": "set_parameter", "target": "T001", "path": "rotation_deg", "value": 30},
                {"op": "set_parameter", "target": "T001", "path": "value", "value": "B"},
            ],
            ["L002", "T001"],
        )["exact_transaction"]
        assert transaction is not None
        result = preview_correction(plan, transaction)
        line = result["candidate_plan"]["steps"][1]
        text = result["candidate_plan"]["steps"][2]
        self.assertEqual(line["start"], {"point": [50, 10]})
        self.assertEqual(next(item for item in line["constraints"] if item["kind"] == "start_offset")["target"], "origin")
        self.assertEqual(next(item for item in line["constraints"] if item["kind"] == "length")["value"], 25)
        self.assertEqual(text["insert"], {"point": [70, 15]})
        self.assertEqual(next(item for item in text["constraints"] if item["kind"] == "text_height")["value"], 6)
        self.assertEqual(next(item for item in text["constraints"] if item["kind"] == "rotation")["value"], 30)
        self.assertEqual(text["value"], "B")

    def test_stale_and_notes_only_handoffs_fail_closed(self) -> None:
        value = handoff(self.plan, [{"op": "set_parameter", "target": "C001", "path": "radius", "value": 12}], ["C001"])
        stale = copy.deepcopy(value)
        stale["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(PlanError, "stale"):
            validate_review_handoff(self.plan, stale)
        notes = handoff(self.plan, [], [], [{"text": "move the hole", "selected_refs": []}])
        report = validate_review_handoff(self.plan, notes)
        self.assertFalse(report["actionable"])
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "must-not-exist"
            with self.assertRaisesRegex(PlanError, "agent interpretation"):
                apply_review_handoff(self.plan, notes, output, "notes")
            self.assertFalse(output.exists())

    def test_runtime_rejects_extra_keys_and_nonobject_selected_refs(self) -> None:
        value = handoff(self.plan, [{"op": "set_parameter", "target": "C001", "path": "radius", "value": 12}], ["C001"])
        extra = copy.deepcopy(value)
        extra["self_approved"] = True
        with self.assertRaisesRegex(PlanError, "keys mismatch"):
            validate_review_handoff(self.plan, extra)
        bad_reference = handoff(self.plan, [], [], [{"text": "inspect", "selected_refs": ["C001"]}])
        with self.assertRaisesRegex(PlanError, "selected_refs"):
            validate_review_handoff(self.plan, bad_reference)

    def test_apply_promotes_one_complete_directory_and_refuses_overwrite(self) -> None:
        value = handoff(
            self.plan,
            [{"op": "set_parameter", "target": "C001", "path": "radius", "value": 12}],
            ["C001"],
        )
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "applied"
            result = apply_review_handoff(self.plan, value, output, "plate")
            self.assertTrue(result["gates"]["atomic_directory_promotion"])
            self.assertEqual(len(list(output.iterdir())), 5)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaisesRegex(PlanError, "must not already contain artifacts"):
                apply_review_handoff(self.plan, value, output, "plate")
            self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})

    def test_agent_surface_exposes_handoff_schema_validate_and_apply(self) -> None:
        agent = load_agent()
        names = {item["name"] for item in agent.TOOLS}
        self.assertTrue({
            "aicad_get_review_handoff_schema",
            "aicad_validate_review_handoff",
            "aicad_apply_review_handoff",
        }.issubset(names))
        self.assertEqual(agent.get_aux_schema("handoff")["schema"]["title"], "AICAD interactive reviewer handoff")
        capability = agent.capabilities()["universal_cad"]["review_handoff"]
        self.assertTrue(capability["source_hash_gate"])
        self.assertFalse(capability["notes_only_apply"])


if __name__ == "__main__":
    unittest.main()
