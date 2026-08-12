from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
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
DESIGN_BASIS_FIXTURE = ROOT / "tests" / "fixtures" / "architectural_design_basis_current.json"


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
        "blockerFormats": ["json", "html", "png", "launch_json"],
        "requireDetailedObjectLinework": True,
        "requireNativeHostRoundTrip": True,
        "requireOpaqueVisualAudit": True,
        "requireAuthorizedRelease": True,
        "requiredDrawingClasses": drawing_classes,
        "providedDrawingClasses": drawing_classes,
    }


def annotation_bindings() -> list[dict[str, object]]:
    fixed = {
        "room_name": ("ANNROOM", ["ROOM01"], "卫生间"),
        "door_tag": ("ANNDOOR", ["DOOR01"], "D01"),
        "window_tag": ("ANNWINDOW", [], "W01"),
        "north_indicator": ("ANNNORTHLINE", [], None),
        "level_datum": ("ANNLEVEL", [], "标高 +0.000"),
        "drawing_title": ("ANNTITLE", [], "建筑平面"),
        "sheet_number": ("ANNSHEET", [], "A-101"),
        "plot_scale": ("ANNSCALE", [], "1:100"),
        "revision_status": ("ANNREV", [], "P01"),
        "stair_direction": ("ANNSTAIR", [], "上"),
        "section_reference": ("ANNSECTION", [], "1/A-301"),
        "elevation_reference": ("ANNELEV", [], "南立面 1/A-201"),
        "detail_reference": ("ANNDETAIL", [], "1/A-501"),
        "units": ("ANNUNITS", [], "单位:mm"),
        "review_status": ("ANNSTATUS", [], "施工候选/未批准"),
        "wall_type_tag": ("ANNWALL", ["WALL01"], "WT-01"),
        "opening_schedule_reference": ("ANNSCHEDULE", ["OP01"], "门窗表 A-601"),
    }
    rows: list[dict[str, object]] = [
        {"id": "BINDAXLINE", "annotationClass": "axis_line", "entityIds": ["AX1", "AXA"], "targetObjectIds": ["1", "A"]},
        {"id": "BINDAXBUBBLE", "annotationClass": "axis_bubble", "entityIds": ["AX1B1", "AX1B2", "AXAB1", "AXAB2"], "targetObjectIds": ["1", "A"]},
        {"id": "BINDAXTEXT", "annotationClass": "axis_identifier", "entityIds": ["AX1T1", "AX1T2", "AXAT1", "AXAT2"], "targetObjectIds": ["1", "A"]},
        {"id": "BINDDIMOVERALL", "annotationClass": "overall_dimension", "entityIds": ["DIM01"], "targetObjectIds": ["DIMOVERALL"]},
        {"id": "BINDDIMGRID", "annotationClass": "grid_dimension_chain", "entityIds": ["DIM02"], "targetObjectIds": ["DIMGRID"]},
        {"id": "BINDDIMPART", "annotationClass": "partition_dimension_chain", "entityIds": ["DIM03"], "targetObjectIds": ["DIMPART"]},
        {"id": "BINDDIMOPEN", "annotationClass": "opening_dimension", "entityIds": ["DIM04"], "targetObjectIds": ["DIMOPEN"]},
    ]
    for annotation_class, (entity_id, targets, expected) in fixed.items():
        entity_ids = [entity_id, "ANNNORTHTEXT"] if annotation_class == "north_indicator" else [entity_id]
        row: dict[str, object] = {"id": f"BIND{annotation_class.upper()}", "annotationClass": annotation_class, "entityIds": entity_ids, "targetObjectIds": targets}
        if expected is not None:
            row["expectedText"] = expected
        rows.append(row)
    return rows


def drawing_sheets() -> list[dict[str, object]]:
    return [
        {
            "id": f"SHEET{index:02d}", "drawingClass": drawing_class, "sheetNumber": f"A-{index:03d}",
            "title": drawing_class, "layoutName": f"A-{index:03d}", "entityIds": [f"SHEET{index:02d}TEXT"],
            "scale": "1:100", "revisionStatus": "P01",
        }
        for index, drawing_class in enumerate(sorted(QA.REQUIRED_PRODUCTION_DRAWING_CLASSES), 1)
    ]


def valid_contract() -> dict[str, object]:
    bindings = annotation_bindings()
    annotations = sorted({row["annotationClass"] for row in bindings})
    return {
        "schema": "aicad_architectural_detail_contract_v2",
        "projectId": "ARCH-DETAIL-TEST",
        "stage": "production",
        "units": "mm",
        "toleranceMm": 1e-6,
        "deliveryPolicy": delivery_policy(),
        "designBasisBinding": {
            "sourcePath": str(DESIGN_BASIS_FIXTURE.resolve()),
            "sourceSha256": hashlib.sha256(DESIGN_BASIS_FIXTURE.read_bytes()).hexdigest(),
            "floorCode": "TEST",
            "localToGlobalOrigin": [0.0, 0.0],
            "axisBasis": "declared_column_centres_and_core_wall_centrelines",
            "structuralModuleAuthority": False,
            "freshnessStatus": "bound_current",
        },
        "axisGrid": {
            "conventionDeclared": True,
            "verticalIdentifierPattern": "positive_integer",
            "horizontalIdentifierPattern": "uppercase_latin",
            "structuralCoverageBounds": [0, 0, 5000, 4000],
            "axes": [
                {"id": "1", "direction": "vertical", "coordinate": 0, "lineEntityId": "AX1", "supportEntityIds": ["COL0"], "bubbleEntityIds": ["AX1B1", "AX1B2"], "identifierEntityIds": ["AX1T1", "AX1T2"]},
                {"id": "A", "direction": "horizontal", "coordinate": 0, "lineEntityId": "AXA", "supportEntityIds": ["COL0"], "bubbleEntityIds": ["AXAB1", "AXAB2"], "identifierEntityIds": ["AXAT1", "AXAT2"]},
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
        "rooms": [{"id": "ROOM01", "name": "卫生间", "category": "bathroom", "categorySource": "approved_programme", "categoryReference": "fixture/test programme", "boundary": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]], "requiredEquipmentTypes": ["toilet", "basin", "shower"]}],
        "equipment": [
            equipment("EQ01", "toilet", [3000, 500, 3600, 1200]),
            equipment("EQ02", "basin", [3800, 500, 4600, 1100]),
            equipment("EQ03", "shower", [3600, 2300, 4700, 3600]),
        ],
        "maintenanceClearances": [],
        "drawingSheets": drawing_sheets(),
        "dimensionChains": [
            {"id": "DIMOVERALL", "purpose": "overall", "entityIds": ["DIM01"], "entityKind": "dimension", "layer": "DIMENSION", "styleName": "AICAD_ARCH"},
            {"id": "DIMGRID", "purpose": "grid", "entityIds": ["DIM02"], "entityKind": "dimension", "layer": "DIMENSION", "styleName": "AICAD_ARCH"},
            {"id": "DIMPART", "purpose": "partition", "entityIds": ["DIM03"], "entityKind": "dimension", "layer": "DIMENSION", "styleName": "AICAD_ARCH"},
            {"id": "DIMOPEN", "purpose": "opening", "entityIds": ["DIM04"], "entityKind": "dimension", "layer": "DIMENSION", "styleName": "AICAD_ARCH"},
        ],
        "annotations": {"requiredClasses": annotations, "providedClasses": annotations, "bindings": bindings},
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
        "COL0": {"type": "circle", "layer": "COLUMN", "center": [0, 0], "radius": 200, "roles": ["column"], "dependsOn": [], "constraints": []},
        "AX1": {"type": "line", "layer": "GRID", "start": [0, -200], "end": [0, 4200], "roles": ["grid"], "dependsOn": ["COL0"], "constraints": [{"kind": "start_offset", "target": "COL0.center", "dx": 0, "dy": -200}]},
        "AXA": {"type": "line", "layer": "GRID", "start": [-200, 0], "end": [5200, 0], "roles": ["grid"], "dependsOn": ["COL0"], "constraints": [{"kind": "start_offset", "target": "COL0.center", "dx": -200, "dy": 0}]},
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
        rows[entity_id] = {"type": "text", "layer": "GRID_TEXT", "insert": center, "text": label}
    for item in contract["equipment"]:
        add_equipment_entities(rows, item)
    for sheet in contract["drawingSheets"]:
        for entity_id in sheet["entityIds"]:
            rows[entity_id] = {"type": "text", "layer": "TEXT", "insert": [-1500, -1500], "text": sheet["sheetNumber"]}
    for binding in contract["annotations"]["bindings"]:
        for entity_id in binding["entityIds"]:
            if entity_id in rows:
                continue
            if entity_id == "ANNNORTHLINE":
                rows[entity_id] = {"type": "line", "layer": "TAG_TEXT", "start": [-1200, -1200], "end": [-1200, -300]}
                continue
            insert = [2500, 2000] if binding["annotationClass"] == "room_name" else [1450, 400] if binding["annotationClass"] == "door_tag" else [-1000, -1000]
            allowed_layers = QA.TECHNICAL_ANNOTATION_LAYERS.get(binding["annotationClass"], {"TAG_TEXT"})
            rows[entity_id] = {"type": "text", "layer": sorted(allowed_layers)[0], "insert": insert, "text": binding.get("expectedText", "N" if entity_id == "ANNNORTHTEXT" else binding["annotationClass"]), "height": 240.0}
    for chain in contract["dimensionChains"]:
        for entity_id in chain["entityIds"]:
            rows[entity_id] = {"type": "dimension", "layer": chain["layer"], "purpose": chain["purpose"], "styleName": chain["styleName"]}
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

    def test_stale_fixed_grid_design_basis_is_rejected(self) -> None:
        contract = valid_contract()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design_basis.json"
            basis = json.loads(DESIGN_BASIS_FIXTURE.read_text(encoding="utf-8"))
            basis["parameters"]["structuralGrid"] = 4200.0
            path.write_text(json.dumps(basis, ensure_ascii=False), encoding="utf-8")
            contract["designBasisBinding"]["sourcePath"] = str(path.resolve())
            contract["designBasisBinding"]["sourceSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["design_basis_axis_catalog_binding"]["pass"])
        reasons = {row["reason"] for row in report["checks"]["design_basis_axis_catalog_binding"]["evidence"]["failures"]}
        self.assertIn("stale_fixed_structural_grid_parameter_forbidden", reasons)

    def test_malformed_design_basis_axis_coordinate_fails_closed(self) -> None:
        contract = valid_contract()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design_basis.json"
            basis = json.loads(DESIGN_BASIS_FIXTURE.read_text(encoding="utf-8"))
            basis["axisGrid"]["vertical"][0]["globalX"] = "not-a-number"
            path.write_text(json.dumps(basis, ensure_ascii=False), encoding="utf-8")
            contract["designBasisBinding"]["sourcePath"] = str(path.resolve())
            contract["designBasisBinding"]["sourceSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["design_basis_axis_catalog_binding"]["pass"])
        reasons = {row["reason"] for row in report["checks"]["design_basis_axis_catalog_binding"]["evidence"]["failures"]}
        self.assertIn("local_axis_not_bijective_with_global_catalog", reasons)

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

    def test_self_reported_annotation_without_entity_binding_is_rejected(self) -> None:
        contract = valid_contract()
        contract["annotations"]["bindings"] = [row for row in contract["annotations"]["bindings"] if row["annotationClass"] != "room_name"]
        report = QA.evaluate(contract, resolved_entities(contract))
        self.assertFalse(report["checks"]["annotation_entity_bindings"]["pass"])
        self.assertFalse(report["checks"]["annotation_completeness"]["pass"])

    def test_annotation_clearance_box_cannot_cross_axis(self) -> None:
        contract = valid_contract()
        entities = resolved_entities(contract)
        entities["ANNROOM"]["insert"] = [0, 2000]
        report = QA.evaluate(contract, entities)
        self.assertFalse(report["checks"]["annotation_spatial_occupancy_clearance"]["pass"])

    def test_self_reported_drawing_class_without_sheet_binding_is_rejected(self) -> None:
        contract = valid_contract()
        contract["drawingSheets"] = [row for row in contract["drawingSheets"] if row["drawingClass"] != "roof_plan"]
        report = QA.evaluate(contract, resolved_entities(contract))
        self.assertFalse(report["checks"]["production_drawing_set_entity_bindings"]["pass"])
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

    def test_axis_without_structural_support_dependency_is_rejected(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        resolved["AX1"]["dependsOn"] = []
        resolved["AX1"]["constraints"] = [{"kind": "start_offset", "target": "origin", "dx": 0, "dy": -200}]
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["axis_structure_support_bindings"]["pass"])
        self.assertFalse(report["checks"]["aicad_entity_bindings"]["pass"])

    def test_axis_support_must_share_coordinate_and_structural_semantics(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        resolved["COL0"]["center"] = [50, 0]
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["axis_structure_support_bindings"]["pass"])

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

    def test_content_inferred_room_category_is_rejected(self) -> None:
        contract = valid_contract()
        contract["rooms"][0]["categorySource"] = "inferred_unverified"
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["room_programme_authority"]["pass"])

    def test_vehicle_participates_in_door_sweep_clearance(self) -> None:
        contract = valid_contract()
        vehicle = equipment("EQVEHICLE", "vehicle", [1500, 100, 1800, 700])
        vehicle["layer"] = "FURNITURE"
        contract["equipment"].append(vehicle)
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["door_equipment_clearance"]["pass"])
        self.assertIn("EQVEHICLE", {row["equipmentId"] for row in report["checks"]["door_equipment_clearance"]["evidence"]["failures"]})

    def test_service_equipment_requires_maintenance_clearance(self) -> None:
        contract = valid_contract()
        unit = equipment("EQUNIT", "equipment_unit", [300, 2500, 900, 3500])
        unit["layer"] = "APPLIANCE"
        contract["equipment"].append(unit)
        contract["rooms"][0]["requiredEquipmentTypes"].append("equipment_unit")
        report = evaluate_contract(contract)
        self.assertFalse(report["checks"]["service_equipment_maintenance_clearance"]["pass"])

    def test_service_equipment_clearance_is_geometrically_bound(self) -> None:
        contract = valid_contract()
        unit = equipment("EQUNIT", "equipment_unit", [300, 2500, 900, 3500])
        unit["layer"] = "APPLIANCE"
        contract["equipment"].append(unit)
        contract["rooms"][0]["requiredEquipmentTypes"].append("equipment_unit")
        contract["maintenanceClearances"] = [{
            "id": "MC01", "roomId": "ROOM01", "equipmentIds": ["EQUNIT"],
            "clearBBox": [1100, 2500, 2400, 3500], "minimumClearWidthMm": 900,
            "actualClearWidthMm": 1000, "authorityStatus": "concept_rule",
        }]
        report = evaluate_contract(contract)
        self.assertTrue(report["checks"]["service_equipment_maintenance_clearance"]["pass"])

    def test_dimension_chain_ids_must_resolve_to_native_dimension_entities(self) -> None:
        contract = valid_contract()
        resolved = resolved_entities(contract)
        resolved["DIM04"] = {"type": "line", "layer": "DIMENSION", "purpose": "opening", "styleName": "AICAD_ARCH"}
        report = QA.evaluate(contract, resolved)
        self.assertFalse(report["checks"]["native_dimension_entity_bindings"]["pass"])
        self.assertFalse(report["checks"]["aicad_entity_bindings"]["pass"])
        failure = report["checks"]["native_dimension_entity_bindings"]["evidence"]["failures"][0]
        self.assertEqual(failure["entityId"], "DIM04")


if __name__ == "__main__":
    unittest.main()
