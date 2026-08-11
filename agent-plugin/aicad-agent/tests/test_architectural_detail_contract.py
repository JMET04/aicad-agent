from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_architecture_detail_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_architecture_detail_qa", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


def authority(available: bool = False) -> dict[str, dict[str, object]]:
    return {
        name: {"available": available, "reference": f"AUTH-{name}" if available else ""}
        for name in QA.PRODUCTION_AUTHORITY_FIELDS
    }


def valid_contract() -> dict[str, object]:
    annotations = sorted(QA.REQUIRED_ANNOTATION_CLASSES)
    return {
        "schema": "aicad_architectural_detail_contract_v1",
        "projectId": "ARCH-DETAIL-TEST",
        "stage": "construction_candidate",
        "units": "mm",
        "toleranceMm": 1e-6,
        "axisGrid": {
            "conventionDeclared": True,
            "verticalIdentifierPattern": "positive_integer",
            "horizontalIdentifierPattern": "uppercase_latin",
            "structuralCoverageBounds": [0, 0, 5000, 4000],
            "axes": [
                {"id": "1", "direction": "vertical", "coordinate": 0, "lineEntityId": "AX1", "bubbleEntityIds": ["AX1B1", "AX1B2"], "identifierEntityIds": ["AX1T1", "AX1T2"]},
                {"id": "A", "direction": "horizontal", "coordinate": 0, "lineEntityId": "AXA", "bubbleEntityIds": ["AXAB1", "AXAB2"], "identifierEntityIds": ["AXAT1", "AXAT2"]},
            ],
            "exceptions": [],
        },
        "walls": [
            {
                "id": "WALL01", "start": [0, 0], "end": [5000, 0], "openingIds": ["OP01"],
                "segments": [
                    {"entityId": "WALL01S1", "start": [0, 0], "end": [1000, 0]},
                    {"entityId": "WALL01S2", "start": [1900, 0], "end": [5000, 0]},
                ],
            }
        ],
        "openings": [{"id": "OP01", "hostWallId": "WALL01", "start": [1000, 0], "end": [1900, 0], "widthMm": 900}],
        "doors": [{"id": "DOOR01", "hostWallId": "WALL01", "openingId": "OP01", "leafEntityId": "DOOR01LEAF", "arcEntityId": "DOOR01ARC", "hinge": [1000, 0], "leafEnd": [1900, 0], "widthMm": 900, "arcStartDeg": 0, "arcEndDeg": 90, "requiredSweepDeg": 90, "clearanceMm": 100}],
        "rooms": [{"id": "ROOM01", "name": "卫生间", "category": "bathroom", "boundary": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]], "requiredEquipmentTypes": ["toilet", "basin", "shower"]}],
        "equipment": [
            {"id": "EQ01", "roomId": "ROOM01", "type": "toilet", "layer": "SANITARY", "bbox": [3000, 500, 3600, 1200], "componentEntityIds": ["EQ01A", "EQ01B"]},
            {"id": "EQ02", "roomId": "ROOM01", "type": "basin", "layer": "SANITARY", "bbox": [3800, 500, 4600, 1100], "componentEntityIds": ["EQ02A", "EQ02B"]},
            {"id": "EQ03", "roomId": "ROOM01", "type": "shower", "layer": "SANITARY", "bbox": [3600, 2300, 4700, 3600], "componentEntityIds": ["EQ03A", "EQ03B"]},
        ],
        "dimensionChains": [
            {"id": "DIMOVERALL", "purpose": "overall", "entityIds": ["DIM01"]},
            {"id": "DIMGRID", "purpose": "grid", "entityIds": ["DIM02"]},
            {"id": "DIMPART", "purpose": "partition", "entityIds": ["DIM03"]},
            {"id": "DIMOPEN", "purpose": "opening", "entityIds": ["DIM04"]},
        ],
        "annotations": {"requiredClasses": annotations, "providedClasses": annotations},
        "authority": authority(False),
        "safetyLocks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def resolved_entities() -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {
        "AX1": {"type": "line", "layer": "GRID", "start": [0, -200], "end": [0, 4200]},
        "AXA": {"type": "line", "layer": "GRID", "start": [-200, 0], "end": [5200, 0]},
        "WALL01S1": {"type": "line", "layer": "WALL", "start": [0, 0], "end": [1000, 0]},
        "WALL01S2": {"type": "line", "layer": "WALL", "start": [1900, 0], "end": [5000, 0]},
        "DOOR01LEAF": {"type": "line", "layer": "OPENING", "start": [1000, 0], "end": [1900, 0]},
        "DOOR01ARC": {"type": "arc", "layer": "OPENING", "center": [1000, 0], "radius": 900, "startAngleDeg": 0, "endAngleDeg": 90},
    }
    for entity_id in ("AX1B1", "AX1B2", "AXAB1", "AXAB2"):
        rows[entity_id] = {"type": "circle", "layer": "GRID_BUBBLE", "center": [0, 0], "radius": 200}
    for prefix in ("EQ01", "EQ02", "EQ03"):
        for suffix in ("A", "B"):
            rows[prefix + suffix] = {"type": "line", "layer": "SANITARY", "start": [3000, 500], "end": [3100, 500]}
    return rows


def evaluate_contract(contract: dict[str, object]) -> dict[str, object]:
    return QA.evaluate(contract, resolved_entities())


class ArchitecturalDetailContractTests(unittest.TestCase):
    def test_schema_is_valid_and_fixture_conforms(self) -> None:
        schema = json.loads((ROOT / "rules" / "architectural_detail_contract.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(valid_contract())

    def test_complete_review_candidate_passes_without_production_authority(self) -> None:
        report = evaluate_contract(valid_contract())
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["artifactDisposition"], "review_candidate")
        self.assertFalse(report["releaseAllowed"])
        self.assertTrue(all(item["pass"] for item in report["checks"].values()))

    def test_door_leaf_must_match_arc_endpoint(self) -> None:
        contract = valid_contract()
        contract["doors"][0]["arcStartDeg"] = 90
        contract["doors"][0]["arcEndDeg"] = 180
        report = evaluate_contract(contract)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["door_leaf_endpoint_matches_arc"]["pass"])
        self.assertEqual(report["artifactDisposition"], "blocker_report_only")

    def test_wall_must_be_split_around_opening(self) -> None:
        contract = valid_contract()
        contract["walls"][0]["segments"] = [{"entityId": "WALL01S1", "start": [0, 0], "end": [5000, 0]}]
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["host_wall_openings_segmented"]["pass"])

    def test_room_equipment_profile_is_not_optional(self) -> None:
        contract = valid_contract()
        contract["equipment"] = contract["equipment"][:1]
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["room_equipment_matrix_complete"]["pass"])

    def test_all_four_dimension_purposes_are_required(self) -> None:
        contract = valid_contract()
        contract["dimensionChains"][-1]["purpose"] = "partition"
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["dimension_chain_matrix_complete"]["pass"])

    def test_production_requires_all_authority_references(self) -> None:
        contract = valid_contract()
        contract["stage"] = "production"
        failed = evaluate_contract(contract)
        self.assertFalse(failed["checks"]["production_authority_complete"]["pass"])
        self.assertEqual(failed["artifactDisposition"], "blocker_report_only")
        contract["authority"] = authority(True)
        passed = evaluate_contract(contract)
        self.assertEqual(passed["status"], "pass")
        self.assertTrue(passed["releaseAllowed"])
        self.assertEqual(passed["artifactDisposition"], "production_candidate")

    def test_semantic_layer_mismatch_is_rejected(self) -> None:
        contract = copy.deepcopy(valid_contract())
        contract["equipment"][0]["layer"] = "FURNITURE"
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["equipment_semantic_layers"]["pass"])


if __name__ == "__main__":
    unittest.main()
