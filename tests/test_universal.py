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

from aicad.correction import PlanError, apply_correction, preview_correction
from aicad.natural import offline_plan
from aicad.semantic import CORE_DOMAIN_PROFILES, describe_plan, validate_semantic_document
from aicad.viewmap import build_multiview_review, generate_view_package, render_review_html


def correction(space: str, operations: list[dict], selected: list[str], **extra: object) -> dict:
    value = {
        "schema_version": "1.0",
        "correction": {
            "id": "CORR001", "description": "bounded test correction", "space": space,
            "selected_ids": selected, "operations": operations,
        },
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
    }
    value.update(extra)
    return value


class UniversalSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan2d = offline_plan("120x80 plate diameter 20")
        cls.plan3d = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.schemas = {
            name: json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))
            for name in (
                "aicad-semantic-document.schema.json", "aicad-correction.schema.json", "aicad-view-package.schema.json",
            )
        }

    def test_same_2d_core_supports_multiple_domains(self) -> None:
        hashes = set()
        for domain in ("mechanical", "electronics", "architecture", "packaging"):
            payload = describe_plan(self.plan2d, "2d", domain)
            self.assertEqual(payload["document"]["domain"], domain)
            self.assertEqual(len(payload["objects"]), 5)
            self.assertTrue(payload["invariants"]["all_objects_explained"])
            self.assertTrue(payload["validation"]["valid"])
            Draft202012Validator(self.schemas["aicad-semantic-document.schema.json"]).validate(payload)
            hashes.add(payload["document"]["source_sha256"])
        self.assertEqual(len(hashes), 1, "domain profiles must not rewrite source geometry")

    def test_unregistered_domain_fails_closed_and_foundation_domain_is_explicit(self) -> None:
        with self.assertRaisesRegex(PlanError, "unregistered engineering domain"):
            describe_plan(self.plan2d, "2d", "hydraulics")
        payload = describe_plan(self.plan2d, "2d", "structural")
        self.assertTrue(payload["domain_profile"]["built_in"])
        self.assertEqual(payload["domain_profile"]["id"], "structural")
        self.assertEqual(payload["domain_profile"]["maturity"], "foundation")
        self.assertTrue(payload["domain_profile"]["specialist_generation_blocked"])
        self.assertTrue(validate_semantic_document(payload)["valid"])
        self.assertIn("mechanical", CORE_DOMAIN_PROFILES)

    def test_3d_semantic_graph_is_ordered_and_origin_anchored(self) -> None:
        payload = describe_plan(self.plan3d, "3d", "electronics")
        self.assertEqual(payload["objects"][0]["anchor"], [0.0, 0.0, 0.0])
        self.assertEqual(payload["objects"][3]["depends_on"], ["F001", "F003"])
        self.assertEqual(payload["objects"][3]["parameters"]["profile"]["radius"], 5.0)
        self.assertGreater(len(payload["relations"]), len(payload["objects"]))

    def test_semantic_validator_rejects_forward_dependency(self) -> None:
        payload = describe_plan(self.plan2d, "2d", "general")
        payload["objects"][0]["depends_on"] = [payload["objects"][1]["id"]]
        with self.assertRaisesRegex(PlanError, "earlier objects"):
            validate_semantic_document(payload)

    def test_2d_parameter_correction_is_bounded_and_constraint_synced(self) -> None:
        result = preview_correction(
            self.plan2d,
            correction("2d", [{"op": "set_parameter", "target": "C001", "path": "radius", "value": 12}], ["C001"]),
            "mechanical",
        )
        self.assertEqual(result["directly_changed_ids"], ["C001"])
        self.assertEqual(result["affected_ids"], ["C001"])
        circle = next(item for item in result["candidate_plan"]["steps"] if item["id"] == "C001")
        self.assertEqual(circle["radius"], 12)
        diameter = next(item for item in circle["constraints"] if item["kind"] == "diameter")
        self.assertEqual(diameter["value"], 24.0)

    def test_2d_relation_correction_changes_later_line_only(self) -> None:
        plan = {
            "schema_version": "2.0",
            "drawing": {"name": "two_lines", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
            "steps": [
                {"id": "L001", "type": "line", "purpose": "datum", "reasoning": "origin datum", "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 40, "dy": 0}, "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 40}]},
                {"id": "L002", "type": "line", "purpose": "candidate", "reasoning": "offset candidate", "start": {"ref": "L001.end"}, "construction": {"kind": "vector", "dx": 20, "dy": 10}, "constraints": [{"kind": "start_coincident", "target": "L001.end"}, {"kind": "length", "value": 22.360679774997898}]},
            ],
        }
        result = preview_correction(plan, correction("2d", [{"op": "add_relation", "relation": "parallel", "members": ["L001", "L002"]}], ["L001", "L002"]), "architecture")
        self.assertEqual(result["directly_changed_ids"], ["L002"])
        line = result["candidate_plan"]["steps"][1]
        self.assertEqual(line["construction"]["kind"], "parallel")
        self.assertEqual(next(value for value in line["constraints"] if value["kind"] == "parallel")["target"], "L001")

    def test_3d_correction_tracks_downstream_impact_and_writes_audit(self) -> None:
        value = correction(
            "3d", [{"op": "set_parameter", "target": "F003", "path": "profile.radius", "value": 16}], ["F003"],
            change_budget={"max_direct_objects": 1, "max_affected_objects": 2},
            root_cause={"status": "candidate", "cause_class": "clearance", "explanation": "boss wall was undersized"},
            prevention_rule={"status": "candidate", "ruleEnabled": False, "requirement": "check annular wall"},
        )
        with tempfile.TemporaryDirectory() as directory:
            result = apply_correction(self.plan3d, value, Path(directory), "boss", "electronics")
            self.assertEqual(result["directly_changed_ids"], ["F003"])
            self.assertEqual(result["affected_ids"], ["F003", "F004"])
            self.assertTrue(Path(result["artifacts"]["plan"]).is_file())
            self.assertIn("check annular wall", Path(result["artifacts"]["audit"]).read_text(encoding="utf-8"))

    def test_locked_parameter_is_never_modified(self) -> None:
        value = correction(
            "3d", [{"op": "set_parameter", "target": "F001", "path": "profile.width", "value": 125}], ["F001"],
            locks=["F001.profile.*"],
        )
        with self.assertRaisesRegex(PlanError, "locked parameter"):
            preview_correction(self.plan3d, value, "mechanical")

    def test_multiview_3d_has_cross_view_semantic_mapping_and_ambiguity_gate(self) -> None:
        package = generate_view_package(self.plan3d, "3d", "mechanical")
        self.assertEqual([view["id"] for view in package["views"]], ["TOP", "FRONT", "RIGHT", "ISOMETRIC", "SECTION_X0", "SECTION_Y0"])
        self.assertGreater(len(package["selection_map"]), 50)
        sources = {row["source_object_id"] for row in package["selection_map"].values()}
        self.assertEqual(sources, {"F001", "F002", "F003", "F004"})
        top = package["views"][0]
        self.assertEqual(top["lost_axis"], "z")
        self.assertFalse(top["back_projection"]["unique_without_additional_constraints"])
        self.assertTrue(package["limits"]["projection_is_not_dimension_authority"])
        Draft202012Validator(self.schemas["aicad-view-package.schema.json"]).validate(package)

    def test_review_html_synchronizes_source_ids_across_views(self) -> None:
        package = generate_view_package(self.plan3d, "3d", "sheet_metal")
        page = render_review_html(package)
        self.assertIn("data-source-id=", page)
        self.assertIn("selected.includes(x.dataset.sourceId)", page)
        self.assertIn("可旋转三维选择器", page)
        self.assertIn("projection_is_not_dimension_authority", page)
        with tempfile.TemporaryDirectory() as directory:
            result = build_multiview_review(self.plan3d, "3d", "sheet_metal", Path(directory), "review")
            self.assertEqual(result["view_count"], 6)
            self.assertTrue(Path(result["artifacts"]["review_html"]).is_file())


if __name__ == "__main__":
    unittest.main()
