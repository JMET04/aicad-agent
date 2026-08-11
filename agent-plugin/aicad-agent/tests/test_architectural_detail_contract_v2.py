from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_architecture_detail_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_architecture_detail_qa_v2", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)
PROFILES = json.loads((ROOT / "rules" / "architectural_symbol_profiles.json").read_text(encoding="utf-8"))


def authority(available: bool = True) -> dict[str, dict[str, object]]:
    return {
        name: {"available": available, "reference": f"AUTH-{name}" if available else ""}
        for name in QA.PRODUCTION_AUTHORITY_FIELDS
    }


def component_rows(equipment_id: str, profile_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    sequence = 0
    for role, count in PROFILES["profiles"][profile_id]["requiredRoles"].items():
        for _ in range(int(count)):
            sequence += 1
            rows.append({"entityId": f"{equipment_id}C{sequence:03d}", "role": role})
    return rows


def equipment(equipment_id: str, item_type: str, bbox: list[float]) -> dict[str, object]:
    components = component_rows(equipment_id, item_type)
    x1, y1, x2, y2 = bbox
    return {
        "id": equipment_id,
        "roomId": "ROOM01",
        "type": item_type,
        "layer": "SANITARY",
        "bbox": bbox,
        "componentEntityIds": [row["entityId"] for row in components],
        "representation": {
            "profileId": item_type,
            "standard": "detailed_plan_linework",
            "actualSizeMm": [abs(x2 - x1), abs(y2 - y1)],
            "clearanceBBox": bbox,
            "components": components,
        },
    }


def delivery_policy() -> dict[str, object]:
    drawing_classes = sorted(QA.REQUIRED_PRODUCTION_DRAWING_CLASSES)
    return {
        "strictProductionOnly": True,
        "cadExposure": "production_release_candidate_only",
        "allowIntermediateCad": False,
        "blockerFormats": ["json", "html", "png"],
        "requireDetailedObjectLinework": True,
        "requireNativeHostRoundTrip": True,
        "requireOpaqueVisualAudit": True,
        "requireAuthorizedRelease": True,
        "requiredDrawingClasses": drawing_classes,
        "providedDrawingClasses": drawing_classes,
    }


def valid_contract() -> dict[str, object]:
    annotations = sorted(QA.REQUIRED_ANNOTATION_CLASSES)
    return {
        "schema": "aicad_architectural_detail_contract_v2",
        "projectId": "ARCH-DETAIL-TEST",
        "stage": "production",
        "units": "mm",
        "toleranceMm": 1e-6,
        "deliveryPolicy": delivery_policy(),
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
            equipment("EQ01", "toilet", [3000, 500, 3600, 1200]),
            equipment("EQ02", "basin", [3800, 500, 4600, 1100]),
            equipment("EQ03", "shower", [3600, 2300, 4700, 3600]),
        ],
        "dimensionChains": [
            {"id": "DIMOVERALL", "purpose": "overall", "entityIds": ["DIM01"]},
            {"id": "DIMGRID", "purpose": "grid", "entityIds": ["DIM02"]},
            {"id": "DIMPART", "purpose": "partition", "entityIds": ["DIM03"]},
            {"id": "DIMOPEN", "purpose": "opening", "entityIds": ["DIM04"]},
        ],
        "annotations": {"requiredClasses": annotations, "providedClasses": annotations},
        "authority": authority(True),
        "safetyLocks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def add_equipment_entities(rows: dict[str, dict[str, object]], item: dict[str, object]) -> None:
    bbox = list(map(float, item["bbox"]))
    x1, y1, x2, y2 = bbox
    corners = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    role_index = Counter()
    center = [(x1 + x2) / 2, (y1 + y2) / 2]
    for component in item["representation"]["components"]:
        entity_id, role = component["entityId"], component["role"]
        index = role_index[role]
        role_index[role] += 1
        primitive = PROFILES["rolePrimitiveTypes"][role][0]
        if role == "outline":
            rows[entity_id] = {"type": "line", "layer": item["layer"], "start": corners[index], "end": corners[(index + 1) % 4]}
        elif primitive == "circle":
            rows[entity_id] = {"type": "circle", "layer": item["layer"], "center": center, "radius": 20 + index}
        elif primitive == "arc":
            rows[entity_id] = {"type": "arc", "layer": item["layer"], "center": center, "radius": 20 + index, "startAngleDeg": 0, "endAngleDeg": 180}
        else:
            offset = 30 + index * 12
            rows[entity_id] = {"type": "line", "layer": item["layer"], "start": [x1 + offset, y1 + offset], "end": [x2 - offset, y1 + offset]}


def resolved_entities(contract: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    contract = contract or valid_contract()
    rows: dict[str, dict[str, object]] = {
        "AX1": {"type": "line", "layer": "GRID", "start": [0, -200], "end": [0, 4200]},
        "AXA": {"type": "line", "layer": "GRID", "start": [-200, 0], "end": [5200, 0]},
        "WALL01S1": {"type": "line", "layer": "WALL", "start": [0, 0], "end": [1000, 0]},
        "WALL01S2": {"type": "line", "layer": "WALL", "start": [1900, 0], "end": [5000, 0]},
        "DOOR01LEAF": {"type": "line", "layer": "OPENING", "start": [1000, 0], "end": [1900, 0]},
        "DOOR01ARC": {"type": "arc", "layer": "OPENING", "center": [1000, 0], "radius": 900, "startAngleDeg": 0, "endAngleDeg": 90},
    }
    axis_graphics = {
        "AX1B1": [0, -400], "AX1B2": [0, 4400],
        "AXAB1": [-400, 0], "AXAB2": [5400, 0],
    }
    for entity_id, center in axis_graphics.items():
        rows[entity_id] = {"type": "circle", "layer": "GRID_BUBBLE", "center": center, "radius": 200}
    for entity_id, center, label in (
        ("AX1T1", [0, -400], "1"), ("AX1T2", [0, 4400], "1"),
        ("AXAT1", [-400, 0], "A"), ("AXAT2", [5400, 0], "A"),
    ):
        rows[entity_id] = {"type": "mtext", "layer": "GRID_TEXT", "insert": center, "text": label}
    for item in contract["equipment"]:
        add_equipment_entities(rows, item)
    return rows


def evaluate_contract(contract: dict[str, object]) -> dict[str, object]:
    return QA.evaluate(contract, resolved_entities(contract))


class ArchitecturalDetailContractV2Tests(unittest.TestCase):
    def test_schema_is_valid_and_fixture_conforms(self) -> None:
        schema = json.loads((ROOT / "rules" / "architectural_detail_contract_v2.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(valid_contract())

    def test_complete_production_release_candidate_passes(self) -> None:
        report = evaluate_contract(valid_contract())
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["releaseAllowed"])
        self.assertEqual(report["artifactDisposition"], "production_release_candidate")
        self.assertTrue(all(item["pass"] for item in report["checks"].values()))

    def test_non_production_stage_is_blocked(self) -> None:
        contract = valid_contract()
        contract["stage"] = "construction_candidate"
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["production_stage_required"]["pass"])
        self.assertEqual(report["artifactDisposition"], "blocker_report_only")

    def test_complete_architecture_drawing_set_is_required(self) -> None:
        contract = valid_contract()
        contract["deliveryPolicy"]["providedDrawingClasses"].remove("building_section")
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["production_drawing_set_complete"]["pass"])

    def test_placeholder_equipment_representation_is_rejected(self) -> None:
        contract = valid_contract()
        item = contract["equipment"][0]
        item["representation"]["components"] = item["representation"]["components"][:4]
        item["componentEntityIds"] = [row["entityId"] for row in item["representation"]["components"]]
        report = QA.evaluate(contract, resolved_entities(contract))
        self.assertEqual(report["status"], "failed")

    def test_missing_sofa_or_fixture_role_is_rejected(self) -> None:
        contract = valid_contract()
        item = contract["equipment"][0]
        item["representation"]["components"] = [row for row in item["representation"]["components"] if row["role"] != "orientation"]
        item["componentEntityIds"] = [row["entityId"] for row in item["representation"]["components"]]
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["recognisable_detailed_object_linework"]["pass"])

    def test_outline_must_be_exact_closed_object_bbox(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        outline_id = next(row["entityId"] for row in contract["equipment"][0]["representation"]["components"] if row["role"] == "outline")
        resolved[outline_id]["end"] = [3500, 500]
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["recognisable_detailed_object_linework"]["pass"])

    def test_role_primitive_type_is_enforced(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        drain_id = next(row["entityId"] for row in contract["equipment"][1]["representation"]["components"] if row["role"] == "drain")
        resolved[drain_id] = {"type": "line", "layer": "SANITARY", "start": [4000, 700], "end": [4100, 700]}
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["recognisable_detailed_object_linework"]["pass"])

    def test_axis_line_must_match_declared_coordinate(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        resolved["AX1"]["start"] = [25, -200]
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["aicad_entity_bindings"]["pass"])

    def test_axis_line_must_be_tangent_to_two_exterior_bubbles(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        resolved["AX1B1"]["center"] = [0, -350]
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["aicad_entity_bindings"]["pass"])

    def test_axis_identifier_text_and_center_are_bound(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        resolved["AX1T1"]["text"] = "2"
        resolved["AX1T2"]["insert"] = [10, 4400]
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["aicad_entity_bindings"]["pass"])

    def test_axis_grid_requires_both_directions(self) -> None:
        contract = valid_contract()
        contract["axisGrid"]["axes"][1].update({"id": "2", "direction": "vertical", "coordinate": 5000})
        report = QA.evaluate(contract, resolved_entities(contract))
        self.assertFalse(report["checks"]["axis_direction_pairs_complete"]["pass"])

    def test_door_leaf_must_match_arc_endpoint(self) -> None:
        contract = valid_contract()
        contract["doors"][0]["arcStartDeg"] = 90
        contract["doors"][0]["arcEndDeg"] = 180
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["door_leaf_endpoint_matches_arc"]["pass"])

    def test_wall_must_be_split_around_opening(self) -> None:
        contract = valid_contract()
        contract["walls"][0]["segments"] = [{"entityId": "WALL01S1", "start": [0, 0], "end": [5000, 0]}]
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["host_wall_openings_segmented"]["pass"])

    def test_production_requires_all_authority_references(self) -> None:
        contract = valid_contract()
        contract["authority"] = authority(False)
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["production_authority_complete"]["pass"])
        self.assertFalse(report["releaseAllowed"])

    def test_semantic_layer_mismatch_is_rejected(self) -> None:
        contract = copy.deepcopy(valid_contract())
        contract["equipment"][0]["layer"] = "FURNITURE"
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["equipment_semantic_layers"]["pass"])


if __name__ == "__main__":
    unittest.main()
