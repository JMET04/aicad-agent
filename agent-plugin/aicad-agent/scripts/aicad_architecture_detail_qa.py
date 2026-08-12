#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "rules" / "architectural_detail_contract_v2.schema.json"
SYMBOL_PROFILES_PATH = ROOT / "rules" / "architectural_symbol_profiles.json"
TOL = 1e-6
REQUIRED_PRODUCTION_DRAWING_CLASSES = {
    "cover_index", "site_plan", "floor_plan", "roof_plan", "elevation", "building_section",
    "wall_section_detail", "stair_detail", "waterproofing_detail", "door_window_schedule",
    "finish_schedule", "reflected_ceiling_plan", "life_safety_plan", "accessibility_detail",
    "discipline_coordination_plan",
}
REQUIRED_DIMENSION_PURPOSES = {"overall", "grid", "partition", "opening"}
REQUIRED_ANNOTATION_CLASSES = {
    "axis_line", "axis_bubble", "axis_identifier", "room_name", "door_tag", "window_tag",
    "overall_dimension", "grid_dimension_chain", "partition_dimension_chain", "opening_dimension",
    "north_indicator", "level_datum", "drawing_title", "sheet_number", "plot_scale", "revision_status",
    "stair_direction", "section_reference", "elevation_reference", "detail_reference", "units",
    "review_status", "wall_type_tag", "opening_schedule_reference",
}
PRODUCTION_AUTHORITY_FIELDS = {
    "dimensionalSurvey", "jurisdictionCode", "geotechnical", "structural", "fireLifeSafety",
    "mep", "accessibility", "licensedReview", "signedRelease",
}
TECHNICAL_ANNOTATION_LAYERS = {
    "room_name": {"TEXT", "TAG_TEXT"},
    "door_tag": {"TAG_TEXT"},
    "window_tag": {"TAG_TEXT"},
    "north_indicator": {"TAG_TEXT"},
    "level_datum": {"TAG_TEXT"},
    "drawing_title": {"TITLEBLOCK", "TEXT"},
    "sheet_number": {"TITLEBLOCK", "TAG_TEXT"},
    "plot_scale": {"TITLEBLOCK", "TAG_TEXT"},
    "revision_status": {"REVISION", "TAG_TEXT"},
    "stair_direction": {"TAG_TEXT"},
    "section_reference": {"SECTION_MARK", "TAG_TEXT"},
    "elevation_reference": {"ELEVATION_MARK", "TAG_TEXT"},
    "detail_reference": {"DETAIL_REF", "TAG_TEXT"},
    "units": {"TITLEBLOCK", "TAG_TEXT"},
    "review_status": {"STATUS", "TAG_TEXT"},
    "wall_type_tag": {"WALL_TYPE", "TAG_TEXT"},
    "opening_schedule_reference": {"SCHEDULE", "TAG_TEXT"},
}
SEMANTIC_LAYER_BY_TYPE: dict[str, str] = {
    "sofa": "FURNITURE", "chair": "FURNITURE", "table": "FURNITURE", "bed": "FURNITURE",
    "desk": "FURNITURE", "vehicle": "FURNITURE", "bench": "FURNITURE", "fitness_equipment": "FURNITURE",
    "cabinet": "CASEWORK", "wardrobe": "CASEWORK", "bookcase": "CASEWORK", "shoe_cabinet": "CASEWORK",
    "toilet": "SANITARY", "basin": "SANITARY", "sink": "SANITARY", "shower": "SANITARY",
    "bathtub": "SANITARY", "floor_drain": "SANITARY", "spa_pool": "SANITARY",
    "refrigerator": "APPLIANCE", "cooktop": "APPLIANCE", "oven": "APPLIANCE", "dishwasher": "APPLIANCE",
    "washer": "APPLIANCE", "dryer": "APPLIANCE", "equipment_unit": "APPLIANCE", "treadmill": "APPLIANCE", "screen": "APPLIANCE",
    "speaker": "APPLIANCE",
}
MINIMUM_ROOM_EQUIPMENT: dict[str, tuple[frozenset[str], ...]] = {
    "living": (frozenset({"sofa"}),),
    "dining": (frozenset({"table"}), frozenset({"chair"})),
    "kitchen": (frozenset({"sink"}), frozenset({"cooktop"}), frozenset({"refrigerator"})),
    "pantry": (frozenset({"sink"}), frozenset({"cabinet"})),
    "bedroom": (frozenset({"bed"}), frozenset({"wardrobe", "cabinet"})),
    "bathroom": (frozenset({"toilet"}), frozenset({"basin"}), frozenset({"shower", "bathtub"})),
    "laundry": (frozenset({"washer"}), frozenset({"sink", "basin"}), frozenset({"cabinet"})),
    "office": (frozenset({"desk"}), frozenset({"chair"}), frozenset({"bookcase", "cabinet"})),
    "wardrobe": (frozenset({"wardrobe", "cabinet"}),),
    "garage": (frozenset({"vehicle"}), frozenset({"cabinet"})),
    "fitness": (frozenset({"fitness_equipment", "treadmill"}),),
    "spa": (frozenset({"spa_pool", "bathtub", "shower"}),),
    "media": (frozenset({"sofa", "chair"}), frozenset({"screen"}), frozenset({"speaker"})),
    "service": (frozenset({"cabinet", "equipment_unit", "shoe_cabinet"}),),
    "circulation": (),
}


def _distance(a: list[float], b: list[float]) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _cross(a: list[float], b: list[float], p: list[float]) -> float:
    return (float(b[0]) - float(a[0])) * (float(p[1]) - float(a[1])) - (float(b[1]) - float(a[1])) * (float(p[0]) - float(a[0]))


def _point_on_segment(point: list[float], start: list[float], end: list[float], tolerance: float) -> bool:
    if abs(_cross(start, end, point)) > tolerance * max(1.0, _distance(start, end)):
        return False
    return (
        min(float(start[0]), float(end[0])) - tolerance <= float(point[0]) <= max(float(start[0]), float(end[0])) + tolerance
        and min(float(start[1]), float(end[1])) - tolerance <= float(point[1]) <= max(float(start[1]), float(end[1])) + tolerance
    )


def _angle(center: list[float], point: list[float]) -> float:
    return math.degrees(math.atan2(float(point[1]) - float(center[1]), float(point[0]) - float(center[0]))) % 360.0


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _sweep(start: float, end: float) -> float:
    value = (end - start) % 360.0
    return 360.0 if abs(value) <= TOL and abs(end - start) > TOL else value


def _project_parameter(point: list[float], start: list[float], end: list[float]) -> float:
    dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
    denominator = dx * dx + dy * dy
    if denominator <= TOL:
        return math.nan
    return ((float(point[0]) - float(start[0])) * dx + (float(point[1]) - float(start[1])) * dy) / denominator


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]], tolerance: float) -> bool:
    p = [point[0], point[1]]
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        if _point_on_segment(p, start, end, tolerance):
            return True
    inside = False
    x, y = point
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        x1, y1, x2, y2 = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def _segment_intersects_rect(start: tuple[float, float], end: tuple[float, float], bbox: list[float], clearance: float) -> bool:
    x1, y1, x2, y2 = map(float, bbox)
    xmin, xmax = min(x1, x2) - clearance, max(x1, x2) + clearance
    ymin, ymax = min(y1, y2) - clearance, max(y1, y2) + clearance
    dx, dy = end[0] - start[0], end[1] - start[1]
    p = (-dx, dx, -dy, dy)
    q = (start[0] - xmin, xmax - start[0], start[1] - ymin, ymax - start[1])
    low, high = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) <= TOL:
            if qi < 0:
                return False
            continue
        ratio = qi / pi
        if pi < 0:
            low = max(low, ratio)
        else:
            high = min(high, ratio)
        if low > high:
            return False
    return True


def _door_hits_bbox(door: dict[str, Any], bbox: list[float]) -> bool:
    center = tuple(map(float, door["hinge"]))
    radius = float(door["widthMm"])
    start, end = float(door["arcStartDeg"]), float(door["arcEndDeg"])
    clearance = float(door["clearanceMm"])
    steps = max(2, int(math.ceil(_sweep(start, end))) + 1)
    points = [
        (
            center[0] + radius * math.cos(math.radians(start + _sweep(start, end) * index / (steps - 1))),
            center[1] + radius * math.sin(math.radians(start + _sweep(start, end) * index / (steps - 1))),
        )
        for index in range(steps)
    ]
    return any(_segment_intersects_rect(a, b, bbox, clearance) for a, b in zip([center, *points[:-1]], points))


def _schema_failure(errors: list[Any]) -> dict[str, Any]:
    evidence = [{"path": "/".join(map(str, error.path)), "message": error.message} for error in errors]
    return {
        "schema": "aicad_architectural_detail_validation_v2", "status": "failed", "releaseAllowed": False,
        "artifactDisposition": "blocker_report_only", "checks": {"contract_schema_valid": {"pass": False, "evidence": evidence}},
        "rootCause": "The architectural semantic contract is incomplete or malformed, so geometry must not be compiled or exposed.",
        "candidatePreventionRules": ["ARCH-D021", "ARCH-D022", "ARCH-D023", "ARCH-D024", "ARCH-D025", "ARCH-D026", "ARCH-D027", "ARCH-D028", "ARCH-D029", "ARCH-D030", "ARCH-D031", "ARCH-D032", "ARCH-D033", "ARCH-D034", "ARCH-D035", "ARCH-D036", "ARCH-D037", "ARCH-D041", "ARCH-D042", "ARCH-D043", "ARCH-D044", "ARCH-D045", "ARCH-D046"],
        "reviewPolicy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def _bbox_contains(outer: list[float], inner: list[float], tolerance: float) -> bool:
    ox1, oy1, ox2, oy2 = map(float, outer)
    ix1, iy1, ix2, iy2 = map(float, inner)
    return (
        min(ox1, ox2) <= min(ix1, ix2) + tolerance
        and min(oy1, oy2) <= min(iy1, iy2) + tolerance
        and max(ox1, ox2) >= max(ix1, ix2) - tolerance
        and max(oy1, oy2) >= max(iy1, iy2) - tolerance
    )


def _bbox_overlaps(first: list[float], second: list[float], tolerance: float) -> bool:
    ax1, ay1, ax2, ay2 = map(float, first)
    bx1, by1, bx2, by2 = map(float, second)
    return (
        max(min(ax1, ax2), min(bx1, bx2)) < min(max(ax1, ax2), max(bx1, bx2)) - tolerance
        and max(min(ay1, ay2), min(by1, by2)) < min(max(ay1, ay2), max(by1, by2)) - tolerance
    )


def _entity_inside_bbox(entity: dict[str, Any], bbox: list[float], tolerance: float) -> bool:
    x1, y1, x2, y2 = map(float, bbox)
    bounds = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
    if entity.get("type") == "line":
        points = [entity.get("start"), entity.get("end")]
        return all(point is not None and _bbox_contains(bounds, [point[0], point[1], point[0], point[1]], tolerance) for point in points)
    if entity.get("type") in {"circle", "arc"}:
        center = entity.get("center")
        radius = float(entity.get("radius", math.inf))
        if center is None:
            return False
        return _bbox_contains(bounds, [float(center[0]) - radius, float(center[1]) - radius, float(center[0]) + radius, float(center[1]) + radius], tolerance)
    return False


def _outline_matches_bbox(entities: list[dict[str, Any]], bbox: list[float], tolerance: float) -> bool:
    x1, y1, x2, y2 = map(float, bbox)
    corners = [[min(x1, x2), min(y1, y2)], [max(x1, x2), min(y1, y2)], [max(x1, x2), max(y1, y2)], [min(x1, x2), max(y1, y2)]]
    expected = list(zip(corners, corners[1:] + corners[:1]))
    return len(entities) == 4 and all(any(_same_line(entity, start, end, tolerance) for entity in entities) for start, end in expected)


def _same_point(actual: Any, expected: list[float], tolerance: float) -> bool:
    return actual is not None and math.dist(tuple(map(float, actual)), tuple(map(float, expected))) <= tolerance


def _same_line(entity: dict[str, Any], start: list[float], end: list[float], tolerance: float) -> bool:
    return entity.get("type") == "line" and (
        _same_point(entity.get("start"), start, tolerance) and _same_point(entity.get("end"), end, tolerance)
        or _same_point(entity.get("start"), end, tolerance) and _same_point(entity.get("end"), start, tolerance)
    )


def _annotation_clearance_bbox(entity: dict[str, Any]) -> list[float] | None:
    insert = entity.get("insert")
    value = str(entity.get("text", ""))
    height = float(entity.get("height", 0.0) or 0.0)
    if insert is None or len(insert) != 2 or not value or not math.isfinite(height) or height <= 0.0:
        return None
    half_width = max(height * 0.45, len(value) * height * 0.34) + 80.0
    half_height = height * 0.55 + 80.0
    return [float(insert[0]) - half_width, float(insert[1]) - half_height, float(insert[0]) + half_width, float(insert[1]) + half_height]


def _axis_or_symbol_hits_bbox(entity: dict[str, Any], bbox: list[float]) -> bool:
    entity_type = str(entity.get("type", "")).lower()
    layer = str(entity.get("layer", "")).upper()
    if entity_type == "line" and layer == "GRID":
        start, end = entity.get("start"), entity.get("end")
        if start is None or end is None:
            return False
        if abs(float(start[0]) - float(end[0])) <= 1e-9:
            return bbox[0] <= float(start[0]) <= bbox[2] and max(min(float(start[1]), float(end[1])), bbox[1]) <= min(max(float(start[1]), float(end[1])), bbox[3])
        if abs(float(start[1]) - float(end[1])) <= 1e-9:
            return bbox[1] <= float(start[1]) <= bbox[3] and max(min(float(start[0]), float(end[0])), bbox[0]) <= min(max(float(start[0]), float(end[0])), bbox[2])
    if entity_type == "circle" and layer in {"COLUMN", "GRID_BUBBLE"}:
        center = entity.get("center")
        radius = float(entity.get("radius", 0.0) or 0.0)
        if center is None or radius <= 0.0:
            return False
        nearest_x = min(max(float(center[0]), bbox[0]), bbox[2])
        nearest_y = min(max(float(center[1]), bbox[1]), bbox[3])
        return (nearest_x - float(center[0])) ** 2 + (nearest_y - float(center[1])) ** 2 <= (radius + 80.0) ** 2
    return False


def normalize_resolved_entities(compiled: Any) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for entity in compiled.entities:
        row: dict[str, Any] = {
            "type": entity.type,
            "layer": entity.layer,
            "purposeText": entity.purpose,
            "roles": list(entity.roles),
            "dependsOn": list(entity.depends_on),
            "constraints": [dict(value) for value in entity.constraints],
        }
        if entity.type == "line":
            row.update({"start": list(entity.start), "end": list(entity.end)})
        elif entity.type == "circle":
            row.update({"center": list(entity.center), "radius": float(entity.radius)})
        elif entity.type == "arc":
            row.update({"center": list(entity.center), "radius": float(entity.radius), "startAngleDeg": float(entity.start_angle_deg), "endAngleDeg": float(entity.end_angle_deg)})
        elif entity.type == "text":
            row.update({"insert": list(entity.insert), "text": entity.value, "height": float(entity.height), "rotationDeg": float(entity.rotation_deg)})
        elif entity.type == "dimension":
            row.update({
                "first": list(entity.first), "second": list(entity.second), "base": list(entity.base),
                "measurement": float(entity.measurement), "dimensionKind": entity.dimension_kind,
                "purpose": entity.dimension_purpose, "styleName": entity.style_name,
            })
        rows[entity.id] = row
    return rows


def evaluate(contract: dict[str, Any], resolved_entities: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(contract), key=lambda error: list(error.path))
    if schema_errors:
        return _schema_failure(schema_errors)

    tolerance = float(contract["toleranceMm"])
    checks: dict[str, dict[str, Any]] = {"contract_schema_valid": {"pass": True, "evidence": []}}
    policy = contract["deliveryPolicy"]

    def add(name: str, passed: bool, evidence: Any) -> None:
        checks[name] = {"pass": bool(passed), "evidence": evidence}

    policy_ok = (
        policy["strictProductionOnly"] is True
        and policy["cadExposure"] == "production_release_candidate_only"
        and policy["allowIntermediateCad"] is False
        and set(policy["blockerFormats"]) >= {"json", "html", "png", "launch_json"}
        and all(policy[key] is True for key in (
            "requireDetailedObjectLinework", "requireNativeHostRoundTrip", "requireOpaqueVisualAudit", "requireAuthorizedRelease"
        ))
    )
    add("strict_production_output_policy", policy_ok, policy)
    drawing_sheets = contract["drawingSheets"]
    sheet_classes = [row["drawingClass"] for row in drawing_sheets]
    declared_sheet_classes = set(policy["providedDrawingClasses"])
    bound_sheet_classes = set(sheet_classes)
    drawing_sheet_binding_failures: list[dict[str, Any]] = []
    if declared_sheet_classes != bound_sheet_classes:
        drawing_sheet_binding_failures.append({
            "reason": "provided_drawing_classes_do_not_match_bound_sheets",
            "declaredOnly": sorted(declared_sheet_classes - bound_sheet_classes),
            "boundOnly": sorted(bound_sheet_classes - declared_sheet_classes),
        })
    for field in ("id", "sheetNumber", "layoutName"):
        values = [str(row[field]) for row in drawing_sheets]
        if len(values) != len(set(values)):
            drawing_sheet_binding_failures.append({"reason": f"duplicate_sheet_{field}", "values": values})
    for row in drawing_sheets:
        for entity_id in row["entityIds"]:
            if resolved_entities is None or entity_id not in resolved_entities:
                drawing_sheet_binding_failures.append({"sheetId": row["id"], "entityId": entity_id, "reason": "sheet_entity_missing"})
    missing_drawing_classes = sorted(set(policy["requiredDrawingClasses"]) - bound_sheet_classes)
    missing_default_classes = sorted(REQUIRED_PRODUCTION_DRAWING_CLASSES - bound_sheet_classes)
    add("production_drawing_set_entity_bindings", not drawing_sheet_binding_failures, {"failures": drawing_sheet_binding_failures, "sheetCount": len(drawing_sheets)})
    add("production_drawing_set_complete", not missing_drawing_classes and not missing_default_classes and not drawing_sheet_binding_failures, {"missingDeclared": missing_drawing_classes, "missingArchitectureDefault": missing_default_classes, "boundSheetClasses": sorted(bound_sheet_classes)})
    add("production_stage_required", contract["stage"] == "production", {"actualStage": contract["stage"], "requiredStage": "production"})

    binding_failures: list[dict[str, Any]] = []
    axis_support_failures: list[dict[str, Any]] = []
    if resolved_entities is None:
        binding_failures.append({"reason": "resolved_aicad_entities_not_supplied"})
        axis_support_failures.append({"reason": "resolved_aicad_entities_not_supplied"})
    else:
        for axis in contract["axisGrid"]["axes"]:
            axis_id = axis["id"]
            line = resolved_entities.get(axis["lineEntityId"])
            line_valid = line is not None and line.get("type") == "line" and str(line.get("layer", "")).upper() == "GRID"
            if not line_valid:
                binding_failures.append({"objectId": axis_id, "entityId": axis["lineEntityId"], "reason": "axis_line_missing_or_wrong_type_layer"})

            coordinate = float(axis["coordinate"])
            coordinate_index = 0 if axis["direction"] == "vertical" else 1
            support_ids = list(axis["supportEntityIds"])
            for support_id in support_ids:
                support = resolved_entities.get(support_id)
                support_valid = False
                if support is not None and support.get("type") == "circle" and str(support.get("layer", "")).upper() == "COLUMN":
                    center = support.get("center")
                    support_valid = center is not None and abs(float(center[coordinate_index]) - coordinate) <= tolerance and "column" in set(support.get("roles", []))
                elif support is not None and support.get("type") == "line" and str(support.get("layer", "")).upper() == "WALL":
                    start, end = support.get("start"), support.get("end")
                    support_valid = (
                        start is not None and end is not None
                        and abs(float(start[coordinate_index]) - coordinate) <= tolerance
                        and abs(float(end[coordinate_index]) - coordinate) <= tolerance
                        and "structural_core_wall" in set(support.get("roles", []))
                    )
                if not support_valid:
                    failure = {"objectId": axis_id, "entityId": support_id, "reason": "axis_support_missing_wrong_semantics_or_off_coordinate"}
                    axis_support_failures.append(failure)
                    binding_failures.append(failure)
            if line_valid:
                dependencies = set(line.get("dependsOn", []))
                if not set(support_ids).issubset(dependencies):
                    failure = {"objectId": axis_id, "entityId": axis["lineEntityId"], "reason": "axis_supports_not_declared_as_earlier_dependencies", "supportEntityIds": support_ids, "dependsOn": sorted(dependencies)}
                    axis_support_failures.append(failure)
                    binding_failures.append(failure)
                anchor_targets = {
                    str(row.get("target", "")).split(".", 1)[0]
                    for row in line.get("constraints", [])
                    if row.get("kind") == "start_offset"
                }
                if not (set(support_ids) & anchor_targets):
                    failure = {"objectId": axis_id, "entityId": axis["lineEntityId"], "reason": "axis_line_not_mathematically_anchored_to_support", "supportEntityIds": support_ids, "startOffsetTargets": sorted(anchor_targets)}
                    axis_support_failures.append(failure)
                    binding_failures.append(failure)

            bubbles: list[dict[str, Any]] = []
            for entity_id in axis["bubbleEntityIds"]:
                bubble = resolved_entities.get(entity_id)
                valid = bubble is not None and bubble.get("type") == "circle" and str(bubble.get("layer", "")).upper() == "GRID_BUBBLE"
                if not valid:
                    binding_failures.append({"objectId": axis_id, "entityId": entity_id, "reason": "axis_bubble_missing_or_wrong_type_layer"})
                else:
                    bubbles.append(bubble)

            identifiers: list[dict[str, Any]] = []
            for entity_id in axis["identifierEntityIds"]:
                label = resolved_entities.get(entity_id)
                valid = label is not None and str(label.get("type", "")).lower() in {"text", "mtext"} and str(label.get("layer", "")).upper() == "GRID_TEXT"
                if not valid:
                    binding_failures.append({"objectId": axis_id, "entityId": entity_id, "reason": "axis_identifier_missing_or_wrong_type_layer"})
                elif str(label.get("text", "")).strip() != axis_id:
                    binding_failures.append({"objectId": axis_id, "entityId": entity_id, "reason": "axis_identifier_text_mismatch"})
                else:
                    identifiers.append(label)

            if line_valid:
                start, end = line.get("start"), line.get("end")
                if start is None or end is None:
                    binding_failures.append({"objectId": axis_id, "entityId": axis["lineEntityId"], "reason": "axis_line_missing_endpoints"})
                else:
                    start = list(map(float, start))
                    end = list(map(float, end))
                    span_index = 1 - coordinate_index
                    if abs(start[coordinate_index] - coordinate) > tolerance or abs(end[coordinate_index] - coordinate) > tolerance:
                        binding_failures.append({"objectId": axis_id, "entityId": axis["lineEntityId"], "reason": "axis_line_declared_coordinate_mismatch"})
                    coverage = list(map(float, contract["axisGrid"]["structuralCoverageBounds"]))
                    coverage_min, coverage_max = (min(coverage[1], coverage[3]), max(coverage[1], coverage[3])) if axis["direction"] == "vertical" else (min(coverage[0], coverage[2]), max(coverage[0], coverage[2]))
                    if min(start[span_index], end[span_index]) > coverage_min + tolerance or max(start[span_index], end[span_index]) < coverage_max - tolerance:
                        binding_failures.append({"objectId": axis_id, "entityId": axis["lineEntityId"], "reason": "axis_line_does_not_span_structural_coverage"})

                    if len(bubbles) == 2:
                        centers = [bubble.get("center") for bubble in bubbles]
                        radii = [float(bubble.get("radius", math.nan)) for bubble in bubbles]
                        if any(center is None for center in centers) or any(not math.isfinite(radius) or radius <= tolerance for radius in radii):
                            binding_failures.append({"objectId": axis_id, "reason": "axis_bubble_invalid_center_or_radius"})
                        else:
                            centers = [list(map(float, center)) for center in centers]
                            if any(abs(center[coordinate_index] - coordinate) > tolerance for center in centers):
                                binding_failures.append({"objectId": axis_id, "reason": "axis_bubble_not_collinear_with_axis"})
                            if abs(radii[0] - radii[1]) > tolerance:
                                binding_failures.append({"objectId": axis_id, "reason": "axis_bubble_pair_radius_mismatch"})
                            tangent_direct = abs(math.dist(start, centers[0]) - radii[0]) <= tolerance and abs(math.dist(end, centers[1]) - radii[1]) <= tolerance
                            tangent_reverse = abs(math.dist(start, centers[1]) - radii[1]) <= tolerance and abs(math.dist(end, centers[0]) - radii[0]) <= tolerance
                            if not (tangent_direct or tangent_reverse):
                                binding_failures.append({"objectId": axis_id, "reason": "axis_line_endpoints_not_tangent_to_bubble_pair"})
                            bubble_spans = sorted(center[span_index] for center in centers)
                            if bubble_spans[0] >= coverage_min - tolerance or bubble_spans[1] <= coverage_max + tolerance:
                                binding_failures.append({"objectId": axis_id, "reason": "axis_bubbles_not_on_opposite_exterior_sides"})
                            if len(identifiers) == 2:
                                inserts = [label.get("insert") for label in identifiers]
                                paired = all(insert is not None for insert in inserts) and (
                                    _same_point(inserts[0], centers[0], tolerance) and _same_point(inserts[1], centers[1], tolerance)
                                    or _same_point(inserts[0], centers[1], tolerance) and _same_point(inserts[1], centers[0], tolerance)
                                )
                                if not paired:
                                    binding_failures.append({"objectId": axis_id, "reason": "axis_identifiers_not_centered_in_bubble_pair"})
        for wall in contract["walls"]:
            for segment in wall["segments"]:
                entity = resolved_entities.get(segment["entityId"])
                if entity is None or str(entity.get("layer", "")).upper() != "WALL" or not _same_line(entity, segment["start"], segment["end"], tolerance):
                    binding_failures.append({"objectId": wall["id"], "entityId": segment["entityId"], "reason": "wall_segment_geometry_or_layer_mismatch"})
        for item in contract["equipment"]:
            for entity_id in item["componentEntityIds"]:
                entity = resolved_entities.get(entity_id)
                if entity is None or str(entity.get("layer", "")).upper() != item["layer"]:
                    binding_failures.append({"objectId": item["id"], "entityId": entity_id, "reason": "equipment_component_missing_or_wrong_layer"})
        for door in contract["doors"]:
            leaf = resolved_entities.get(door["leafEntityId"])
            arc = resolved_entities.get(door["arcEntityId"])
            if leaf is None or str(leaf.get("layer", "")).upper() != "OPENING" or not _same_line(leaf, door["hinge"], door["leafEnd"], tolerance):
                binding_failures.append({"objectId": door["id"], "entityId": door["leafEntityId"], "reason": "door_leaf_geometry_or_layer_mismatch"})
            if arc is None or arc.get("type") != "arc" or str(arc.get("layer", "")).upper() != "OPENING" or not _same_point(arc.get("center"), door["hinge"], tolerance) or abs(float(arc.get("radius", math.nan)) - float(door["widthMm"])) > tolerance or _angle_delta(float(arc.get("startAngleDeg", math.nan)), float(door["arcStartDeg"])) > tolerance or _angle_delta(float(arc.get("endAngleDeg", math.nan)), float(door["arcEndDeg"])) > tolerance:
                binding_failures.append({"objectId": door["id"], "entityId": door["arcEntityId"], "reason": "door_arc_geometry_or_layer_mismatch"})
        dimension_binding_failures: list[dict[str, Any]] = []
        for chain in contract["dimensionChains"]:
            for entity_id in chain["entityIds"]:
                entity = resolved_entities.get(entity_id)
                valid = (
                    entity is not None
                    and str(entity.get("type", "")).lower() == "dimension"
                    and str(entity.get("layer", "")).upper() == chain["layer"]
                    and str(entity.get("purpose", "")).lower() == chain["purpose"]
                    and str(entity.get("styleName", "")) == chain["styleName"]
                )
                if not valid:
                    failure = {
                        "chainId": chain["id"], "entityId": entity_id,
                        "reason": "native_dimension_missing_or_type_layer_purpose_style_mismatch",
                        "expected": {"type": chain["entityKind"], "layer": chain["layer"], "purpose": chain["purpose"], "styleName": chain["styleName"]},
                        "actual": entity,
                    }
                    dimension_binding_failures.append(failure)
                    binding_failures.append(failure)
    add("aicad_entity_bindings", not binding_failures, {"failures": binding_failures})
    add("axis_structure_support_bindings", not axis_support_failures, {"failures": axis_support_failures})
    add("native_dimension_entity_bindings", not dimension_binding_failures if resolved_entities is not None else False, {"failures": dimension_binding_failures if resolved_entities is not None else [{"reason": "resolved_native_dimensions_not_supplied"}]})

    axes = contract["axisGrid"]["axes"]
    axis_keys = [(axis["direction"], axis["id"]) for axis in axes]
    complete_axes = all(len(axis["bubbleEntityIds"]) == 2 and len(axis["identifierEntityIds"]) == 2 for axis in axes)
    add("axis_groups_complete", complete_axes and len(axis_keys) == len(set(axis_keys)), {"axisCount": len(axes), "groups": axis_keys})
    convention_failures = [
        axis["id"] for axis in axes
        if (axis["direction"] == "vertical" and (not axis["id"].isdigit() or int(axis["id"]) <= 0))
        or (axis["direction"] == "horizontal" and (not axis["id"].isalpha() or not axis["id"].isupper()))
    ]
    add("axis_identifier_convention", not convention_failures, {"invalidIdentifiers": convention_failures})
    direction_counts = Counter(axis["direction"] for axis in axes)
    add("axis_direction_pairs_complete", all(direction_counts[direction] > 0 for direction in ("vertical", "horizontal")), {"counts": dict(direction_counts)})
    ordering_failures: list[dict[str, Any]] = []
    vertical_axes = sorted((axis for axis in axes if axis["direction"] == "vertical"), key=lambda axis: float(axis["coordinate"]))
    if [int(axis["id"]) for axis in vertical_axes if axis["id"].isdigit()] != sorted(int(axis["id"]) for axis in vertical_axes if axis["id"].isdigit()):
        ordering_failures.append({"direction": "vertical", "reason": "numeric_identifiers_not_west_to_east"})
    horizontal_axes = sorted((axis for axis in axes if axis["direction"] == "horizontal"), key=lambda axis: float(axis["coordinate"]))
    if [axis["id"] for axis in horizontal_axes] != sorted(axis["id"] for axis in horizontal_axes):
        ordering_failures.append({"direction": "horizontal", "reason": "letter_identifiers_not_south_to_north"})
    for direction in ("vertical", "horizontal"):
        coordinates = [round(float(axis["coordinate"]), 9) for axis in axes if axis["direction"] == direction]
        if len(coordinates) != len(set(coordinates)):
            ordering_failures.append({"direction": direction, "reason": "duplicate_axis_coordinate"})
    add("axis_coordinate_identifier_order", not ordering_failures, {"failures": ordering_failures})
    x1, y1, x2, y2 = map(float, contract["axisGrid"]["structuralCoverageBounds"])
    coverage_failures = []
    for axis in axes:
        coordinate = float(axis["coordinate"])
        valid = min(x1, x2) - tolerance <= coordinate <= max(x1, x2) + tolerance if axis["direction"] == "vertical" else min(y1, y2) - tolerance <= coordinate <= max(y1, y2) + tolerance
        if not valid:
            coverage_failures.append(axis["id"])
    add("axis_structural_coverage", not coverage_failures, {"coverageBounds": [x1, y1, x2, y2], "outside": coverage_failures})

    dimension_counts = Counter(row["purpose"] for row in contract["dimensionChains"])
    missing_dimension_purposes = sorted(REQUIRED_DIMENSION_PURPOSES - set(dimension_counts))
    add("dimension_chain_matrix_complete", not missing_dimension_purposes, {"counts": dict(dimension_counts), "missing": missing_dimension_purposes})

    rooms = {row["id"]: row for row in contract["rooms"]}
    equipment = {row["id"]: row for row in contract["equipment"]}
    programme_failures = [
        {
            "roomId": room["id"],
            "category": room["category"],
            "categorySource": room.get("categorySource"),
            "reason": "programme_category_must_precede_contents",
        }
        for room in rooms.values()
        if room.get("categorySource") == "inferred_unverified" or not str(room.get("categoryReference", "")).strip()
    ]
    add("room_programme_authority", not programme_failures, {"failures": programme_failures})
    equipment_by_room: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in equipment.values():
        equipment_by_room[row["roomId"]].append(row)
    room_failures: list[dict[str, Any]] = []
    for room in rooms.values():
        present = {row["type"] for row in equipment_by_room.get(room["id"], [])}
        explicit = set(room["requiredEquipmentTypes"])
        missing_explicit = sorted(explicit - present)
        groups = MINIMUM_ROOM_EQUIPMENT.get(room["category"])
        missing_groups: list[list[str]] = []
        if groups is None:
            if not explicit:
                missing_groups.append(["explicit_required_equipment_profile"])
        else:
            for alternatives in groups:
                if not present.intersection(alternatives):
                    missing_groups.append(sorted(alternatives))
        if missing_explicit or missing_groups:
            room_failures.append({"roomId": room["id"], "category": room["category"], "missingExplicit": missing_explicit, "missingAlternativeGroups": missing_groups})
    add("room_equipment_matrix_complete", not room_failures, {"roomCount": len(rooms), "failures": room_failures})

    layer_failures = [
        {"equipmentId": row["id"], "type": row["type"], "expected": SEMANTIC_LAYER_BY_TYPE.get(row["type"]), "actual": row["layer"]}
        for row in equipment.values()
        if SEMANTIC_LAYER_BY_TYPE.get(row["type"]) is not None and SEMANTIC_LAYER_BY_TYPE[row["type"]] != row["layer"]
    ]
    add("equipment_semantic_layers", not layer_failures, {"failures": layer_failures})
    location_failures = []
    for row in equipment.values():
        room = rooms.get(row["roomId"])
        if room is None:
            location_failures.append({"equipmentId": row["id"], "reason": "unknown_room"})
            continue
        bx1, by1, bx2, by2 = map(float, row["bbox"])
        center = ((bx1 + bx2) / 2.0, (by1 + by2) / 2.0)
        if not _point_in_polygon(center, room["boundary"], tolerance):
            location_failures.append({"equipmentId": row["id"], "roomId": row["roomId"], "center": list(center)})
    add("equipment_inside_assigned_rooms", not location_failures, {"failures": location_failures})

    service_types = {"equipment_unit"}
    maintenance_rows = contract["maintenanceClearances"]
    maintenance_failures: list[dict[str, Any]] = []
    clearance_ids = [row["id"] for row in maintenance_rows]
    if len(clearance_ids) != len(set(clearance_ids)):
        maintenance_failures.append({"reason": "duplicate_maintenance_clearance_id", "ids": clearance_ids})
    covered_service_equipment: set[str] = set()
    for clearance in maintenance_rows:
        room = rooms.get(clearance["roomId"])
        if room is None:
            maintenance_failures.append({"clearanceId": clearance["id"], "reason": "maintenance_room_missing"})
            continue
        target_equipment = []
        for equipment_id in clearance["equipmentIds"]:
            item = equipment.get(equipment_id)
            if item is None or item["roomId"] != clearance["roomId"]:
                maintenance_failures.append({"clearanceId": clearance["id"], "equipmentId": equipment_id, "reason": "maintenance_equipment_missing_or_wrong_room"})
                continue
            target_equipment.append(item)
            if item["type"] in service_types:
                covered_service_equipment.add(equipment_id)
        clear_bbox = list(map(float, clearance["clearBBox"]))
        x1, y1, x2, y2 = clear_bbox
        actual_width = min(abs(x2 - x1), abs(y2 - y1))
        if abs(actual_width - float(clearance["actualClearWidthMm"])) > tolerance:
            maintenance_failures.append({"clearanceId": clearance["id"], "reason": "actual_clear_width_mismatch", "computed": actual_width, "declared": clearance["actualClearWidthMm"]})
        if actual_width + tolerance < float(clearance["minimumClearWidthMm"]):
            maintenance_failures.append({"clearanceId": clearance["id"], "reason": "maintenance_clear_width_below_required", "actual": actual_width, "required": clearance["minimumClearWidthMm"]})
        corners = [(min(x1, x2), min(y1, y2)), (max(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2)), (min(x1, x2), max(y1, y2))]
        if not all(_point_in_polygon(corner, room["boundary"], tolerance) for corner in corners):
            maintenance_failures.append({"clearanceId": clearance["id"], "reason": "maintenance_clearance_outside_room"})
        for item in equipment_by_room.get(clearance["roomId"], []):
            if _bbox_overlaps(clear_bbox, item["bbox"], tolerance):
                maintenance_failures.append({"clearanceId": clearance["id"], "equipmentId": item["id"], "reason": "maintenance_clearance_obstructed"})
    required_service_equipment = {row["id"] for row in equipment.values() if row["type"] in service_types}
    missing_service_coverage = sorted(required_service_equipment - covered_service_equipment)
    if missing_service_coverage:
        maintenance_failures.append({"reason": "service_equipment_maintenance_coverage_missing", "equipmentIds": missing_service_coverage})
    add("service_equipment_maintenance_clearance", not maintenance_failures, {"clearanceCount": len(maintenance_rows), "failures": maintenance_failures})

    profiles_document = json.loads(SYMBOL_PROFILES_PATH.read_text(encoding="utf-8"))
    profiles = profiles_document["profiles"]
    role_primitives = profiles_document["rolePrimitiveTypes"]
    linework_failures: list[dict[str, Any]] = []
    for row in equipment.values():
        representation = row["representation"]
        profile_id = representation["profileId"]
        profile = profiles.get(profile_id)
        if profile_id != row["type"] or profile is None:
            linework_failures.append({"equipmentId": row["id"], "reason": "missing_or_mismatched_symbol_profile", "type": row["type"], "profileId": profile_id})
            continue
        components = representation["components"]
        component_ids = [item["entityId"] for item in components]
        if len(component_ids) != len(set(component_ids)):
            linework_failures.append({"equipmentId": row["id"], "reason": "duplicate_component_entity_id"})
        if set(component_ids) != set(row["componentEntityIds"]):
            linework_failures.append({"equipmentId": row["id"], "reason": "component_catalog_mismatch", "declared": row["componentEntityIds"], "represented": component_ids})
        bx1, by1, bx2, by2 = map(float, row["bbox"])
        expected_size = [abs(bx2 - bx1), abs(by2 - by1)]
        actual_size = list(map(float, representation["actualSizeMm"]))
        if any(abs(actual - expected) > tolerance for actual, expected in zip(actual_size, expected_size)):
            linework_failures.append({"equipmentId": row["id"], "reason": "actual_size_does_not_match_bbox", "expected": expected_size, "actual": actual_size})
        if not _bbox_contains(representation["clearanceBBox"], row["bbox"], tolerance):
            linework_failures.append({"equipmentId": row["id"], "reason": "clearance_bbox_does_not_contain_object"})
        role_counts = Counter(item["role"] for item in components)
        for role, minimum in profile["requiredRoles"].items():
            if role_counts[role] < int(minimum):
                linework_failures.append({"equipmentId": row["id"], "reason": "required_linework_role_missing", "role": role, "minimum": minimum, "actual": role_counts[role]})
        resolved_components: dict[str, dict[str, Any]] = {}
        for component in components:
            entity_id, role = component["entityId"], component["role"]
            entity = (resolved_entities or {}).get(entity_id)
            if entity is None:
                linework_failures.append({"equipmentId": row["id"], "entityId": entity_id, "reason": "linework_entity_missing"})
                continue
            resolved_components[entity_id] = entity
            if str(entity.get("layer", "")).upper() != row["layer"]:
                linework_failures.append({"equipmentId": row["id"], "entityId": entity_id, "reason": "linework_layer_mismatch"})
            allowed = role_primitives.get(role, [])
            if entity.get("type") not in allowed:
                linework_failures.append({"equipmentId": row["id"], "entityId": entity_id, "reason": "linework_primitive_mismatch", "role": role, "actual": entity.get("type"), "allowed": allowed})
            if not _entity_inside_bbox(entity, row["bbox"], tolerance):
                linework_failures.append({"equipmentId": row["id"], "entityId": entity_id, "reason": "linework_outside_object_bbox"})
        outlines = [resolved_components[item["entityId"]] for item in components if item["role"] == "outline" and item["entityId"] in resolved_components]
        if not _outline_matches_bbox(outlines, row["bbox"], tolerance):
            linework_failures.append({"equipmentId": row["id"], "reason": "outline_is_not_exact_closed_bbox", "outlineCount": len(outlines)})
    add("recognisable_detailed_object_linework", not linework_failures, {"equipmentCount": len(equipment), "failures": linework_failures})

    walls = {row["id"]: row for row in contract["walls"]}
    openings = {row["id"]: row for row in contract["openings"]}
    binding_failures: list[dict[str, Any]] = []
    segmentation_failures: list[dict[str, Any]] = []
    for opening in openings.values():
        wall = walls.get(opening["hostWallId"])
        if wall is None or opening["id"] not in (wall or {}).get("openingIds", []):
            binding_failures.append({"openingId": opening["id"], "reason": "opening_not_bound_bidirectionally_to_host_wall"})
            continue
        if not all(_point_on_segment(point, wall["start"], wall["end"], tolerance) for point in (opening["start"], opening["end"])):
            binding_failures.append({"openingId": opening["id"], "reason": "opening_not_collinear_with_host_wall"})
        if abs(_distance(opening["start"], opening["end"]) - float(opening["widthMm"])) > tolerance:
            binding_failures.append({"openingId": opening["id"], "reason": "opening_width_mismatch"})
    for wall in walls.values():
        wall_length = _distance(wall["start"], wall["end"])
        intervals: list[tuple[float, float, str]] = []
        for segment in wall["segments"]:
            if not all(_point_on_segment(point, wall["start"], wall["end"], tolerance) for point in (segment["start"], segment["end"])):
                segmentation_failures.append({"wallId": wall["id"], "segmentId": segment["entityId"], "reason": "segment_not_on_host_wall"})
                continue
            a = _project_parameter(segment["start"], wall["start"], wall["end"])
            b = _project_parameter(segment["end"], wall["start"], wall["end"])
            intervals.append((min(a, b), max(a, b), segment["entityId"]))
        opening_intervals = []
        for opening_id in wall["openingIds"]:
            opening = openings.get(opening_id)
            if opening:
                a = _project_parameter(opening["start"], wall["start"], wall["end"])
                b = _project_parameter(opening["end"], wall["start"], wall["end"])
                opening_intervals.append((min(a, b), max(a, b), opening_id))
        overlaps = [
            {"segmentId": segment_id, "openingId": opening_id}
            for s1, s2, segment_id in intervals for o1, o2, opening_id in opening_intervals
            if min(s2, o2) - max(s1, o1) > tolerance / max(wall_length, 1.0)
        ]
        segment_length = sum((b - a) * wall_length for a, b, _ in intervals)
        opening_length = sum((b - a) * wall_length for a, b, _ in opening_intervals)
        if overlaps or abs(segment_length + opening_length - wall_length) > tolerance:
            segmentation_failures.append({"wallId": wall["id"], "reason": "wall_segments_do_not_exactly_exclude_openings", "overlaps": overlaps, "segmentLengthMm": segment_length, "openingLengthMm": opening_length, "wallLengthMm": wall_length})
    add("host_wall_openings_segmented", not segmentation_failures, {"failures": segmentation_failures})

    leaf_failures: list[dict[str, Any]] = []
    arc_endpoint_failures: list[dict[str, Any]] = []
    sweep_failures: list[dict[str, Any]] = []
    door_binding_failures: list[dict[str, Any]] = []
    clearance_failures: list[dict[str, Any]] = []
    for door in contract["doors"]:
        wall = walls.get(door["hostWallId"])
        opening = openings.get(door["openingId"])
        if wall is None or opening is None or opening.get("hostWallId") != door["hostWallId"]:
            door_binding_failures.append({"doorId": door["id"], "reason": "missing_or_inconsistent_host"})
        elif not any(_distance(door["hinge"], endpoint) <= tolerance for endpoint in (opening["start"], opening["end"])):
            door_binding_failures.append({"doorId": door["id"], "reason": "hinge_not_at_opening_endpoint"})
        leaf_length = _distance(door["hinge"], door["leafEnd"])
        if abs(leaf_length - float(door["widthMm"])) > tolerance or opening and abs(float(opening["widthMm"]) - float(door["widthMm"])) > tolerance:
            leaf_failures.append({"doorId": door["id"], "leafLengthMm": leaf_length, "doorWidthMm": door["widthMm"], "openingWidthMm": opening.get("widthMm") if opening else None})
        leaf_angle = _angle(door["hinge"], door["leafEnd"])
        if min(_angle_delta(leaf_angle, float(door["arcStartDeg"])), _angle_delta(leaf_angle, float(door["arcEndDeg"]))) > tolerance:
            arc_endpoint_failures.append({"doorId": door["id"], "leafAngleDeg": leaf_angle, "arcStartDeg": door["arcStartDeg"], "arcEndDeg": door["arcEndDeg"]})
        actual_sweep = _sweep(float(door["arcStartDeg"]), float(door["arcEndDeg"]))
        if abs(actual_sweep - float(door["requiredSweepDeg"])) > tolerance:
            sweep_failures.append({"doorId": door["id"], "actualSweepDeg": actual_sweep, "requiredSweepDeg": door["requiredSweepDeg"]})
        for item in equipment.values():
            if _door_hits_bbox(door, item["bbox"]):
                clearance_failures.append({"doorId": door["id"], "equipmentId": item["id"], "clearanceMm": door["clearanceMm"]})
    add("door_host_opening_binding", not door_binding_failures and not binding_failures, {"doorFailures": door_binding_failures, "openingFailures": binding_failures})
    add("door_leaf_radius_matches_opening", not leaf_failures, {"failures": leaf_failures})
    add("door_leaf_endpoint_matches_arc", not arc_endpoint_failures, {"failures": arc_endpoint_failures})
    add("door_arc_sweep", not sweep_failures, {"failures": sweep_failures})
    add("door_equipment_clearance", not clearance_failures, {"failures": clearance_failures})

    annotation_bindings = contract["annotations"]["bindings"]
    declared_annotations = set(contract["annotations"]["providedClasses"])
    bound_annotations = {row["annotationClass"] for row in annotation_bindings}
    required = set(contract["annotations"]["requiredClasses"]) | REQUIRED_ANNOTATION_CLASSES
    annotation_binding_failures: list[dict[str, Any]] = []
    if declared_annotations != bound_annotations:
        annotation_binding_failures.append({
            "reason": "provided_annotation_classes_do_not_match_bindings",
            "declaredOnly": sorted(declared_annotations - bound_annotations),
            "boundOnly": sorted(bound_annotations - declared_annotations),
        })
    binding_ids = [row["id"] for row in annotation_bindings]
    if len(binding_ids) != len(set(binding_ids)):
        annotation_binding_failures.append({"reason": "duplicate_annotation_binding_id", "ids": binding_ids})
    dimension_class_purpose = {
        "overall_dimension": "overall", "grid_dimension_chain": "grid",
        "partition_dimension_chain": "partition", "opening_dimension": "opening",
    }
    semantic_targets = {
        **{row["id"]: ("wall", row) for row in contract["walls"]},
        **{row["id"]: ("room", row) for row in contract["rooms"]},
        **{row["id"]: ("door", row) for row in contract["doors"]},
        **{row["id"]: ("opening", row) for row in contract["openings"]},
        **{row["id"]: ("dimension_chain", row) for row in contract["dimensionChains"]},
        **{row["id"]: ("axis", row) for row in contract["axisGrid"]["axes"]},
    }
    targets_by_class: dict[str, set[str]] = defaultdict(set)
    types_by_class: dict[str, set[str]] = defaultdict(set)
    for binding in annotation_bindings:
        annotation_class = binding["annotationClass"]
        targets_by_class[annotation_class].update(binding["targetObjectIds"])
        for target_id in binding["targetObjectIds"]:
            if target_id not in semantic_targets:
                annotation_binding_failures.append({"bindingId": binding["id"], "targetObjectId": target_id, "reason": "annotation_target_missing"})
        resolved_for_binding: list[dict[str, Any]] = []
        for entity_id in binding["entityIds"]:
            entity = (resolved_entities or {}).get(entity_id)
            if entity is None:
                annotation_binding_failures.append({"bindingId": binding["id"], "entityId": entity_id, "reason": "annotation_entity_missing"})
                continue
            resolved_for_binding.append(entity)
            entity_type = str(entity.get("type", "")).lower()
            entity_layer = str(entity.get("layer", "")).upper()
            types_by_class[annotation_class].add(entity_type)
            if annotation_class == "axis_line" and not (entity_type == "line" and entity_layer == "GRID"):
                annotation_binding_failures.append({"bindingId": binding["id"], "entityId": entity_id, "reason": "axis_line_annotation_type_or_layer"})
            elif annotation_class == "axis_bubble" and not (entity_type == "circle" and entity_layer == "GRID_BUBBLE"):
                annotation_binding_failures.append({"bindingId": binding["id"], "entityId": entity_id, "reason": "axis_bubble_annotation_type_or_layer"})
            elif annotation_class == "axis_identifier" and not (entity_type in {"text", "mtext"} and entity_layer == "GRID_TEXT"):
                annotation_binding_failures.append({"bindingId": binding["id"], "entityId": entity_id, "reason": "axis_identifier_annotation_type_or_layer"})
            elif annotation_class in dimension_class_purpose and not (
                entity_type == "dimension" and entity_layer == "DIMENSION"
                and str(entity.get("purpose", "")).lower() == dimension_class_purpose[annotation_class]
            ):
                annotation_binding_failures.append({"bindingId": binding["id"], "entityId": entity_id, "reason": "dimension_annotation_type_layer_or_purpose"})
            elif annotation_class not in {"axis_line", "axis_bubble", "axis_identifier", *dimension_class_purpose} and not (
                entity_type in {"text", "mtext", "line"}
                and entity_layer in TECHNICAL_ANNOTATION_LAYERS.get(annotation_class, {"TAG_TEXT", "TEXT"})
            ):
                annotation_binding_failures.append({
                    "bindingId": binding["id"], "entityId": entity_id,
                    "reason": "technical_annotation_type_or_layer",
                    "allowedLayers": sorted(TECHNICAL_ANNOTATION_LAYERS.get(annotation_class, {"TAG_TEXT", "TEXT"})),
                })
        expected_text = binding.get("expectedText")
        if expected_text is not None:
            text_entities = [row for row in resolved_for_binding if str(row.get("type", "")).lower() in {"text", "mtext"}]
            if not text_entities or any(str(row.get("text", "")) != expected_text for row in text_entities):
                annotation_binding_failures.append({"bindingId": binding["id"], "reason": "annotation_text_mismatch", "expectedText": expected_text})
        if annotation_class == "room_name" and len(binding["targetObjectIds"]) == 1 and resolved_for_binding:
            target = semantic_targets.get(binding["targetObjectIds"][0])
            text_entity = next((row for row in resolved_for_binding if row.get("insert") is not None), None)
            if target is None or target[0] != "room" or text_entity is None or not _point_in_polygon(tuple(map(float, text_entity["insert"])), target[1]["boundary"], tolerance):
                annotation_binding_failures.append({"bindingId": binding["id"], "reason": "room_name_not_inside_target_room"})
        if annotation_class == "door_tag" and len(binding["targetObjectIds"]) == 1 and resolved_for_binding:
            target = semantic_targets.get(binding["targetObjectIds"][0])
            text_entity = next((row for row in resolved_for_binding if row.get("insert") is not None), None)
            if target is None or target[0] != "door" or text_entity is None or _distance(list(map(float, text_entity["insert"])), target[1]["hinge"]) > float(target[1]["widthMm"]) + 900.0:
                annotation_binding_failures.append({"bindingId": binding["id"], "reason": "door_tag_not_near_target_door"})
        if annotation_class == "window_tag" and len(binding["targetObjectIds"]) == 1 and resolved_for_binding:
            target = semantic_targets.get(binding["targetObjectIds"][0])
            text_entity = next((row for row in resolved_for_binding if row.get("insert") is not None), None)
            if target is None or target[0] != "opening" or text_entity is None:
                annotation_binding_failures.append({"bindingId": binding["id"], "reason": "window_tag_target_or_text_missing"})
            else:
                midpoint = [(float(target[1]["start"][0]) + float(target[1]["end"][0])) / 2.0, (float(target[1]["start"][1]) + float(target[1]["end"][1])) / 2.0]
                if _distance(list(map(float, text_entity["insert"])), midpoint) > float(target[1]["widthMm"]) / 2.0 + 1200.0:
                    annotation_binding_failures.append({"bindingId": binding["id"], "reason": "window_tag_not_near_target_opening"})
    expected_targets = {
        "axis_line": {row["id"] for row in contract["axisGrid"]["axes"]},
        "axis_bubble": {row["id"] for row in contract["axisGrid"]["axes"]},
        "axis_identifier": {row["id"] for row in contract["axisGrid"]["axes"]},
        "room_name": {row["id"] for row in contract["rooms"]},
        "door_tag": {row["id"] for row in contract["doors"]},
        "window_tag": {row["id"] for row in contract["openings"]} - {row["openingId"] for row in contract["doors"]},
        "wall_type_tag": {row["id"] for row in contract["walls"]},
        "opening_schedule_reference": {row["id"] for row in contract["openings"]},
        **{annotation_class: {row["id"] for row in contract["dimensionChains"] if row["purpose"] == purpose} for annotation_class, purpose in dimension_class_purpose.items()},
    }
    for annotation_class, expected in expected_targets.items():
        missing_targets = sorted(expected - targets_by_class[annotation_class])
        if missing_targets:
            annotation_binding_failures.append({"annotationClass": annotation_class, "reason": "annotation_target_coverage_incomplete", "missingTargetObjectIds": missing_targets})
    if types_by_class["north_indicator"] and not {"line", "text"}.issubset(types_by_class["north_indicator"] | ({"text"} if "mtext" in types_by_class["north_indicator"] else set())):
        annotation_binding_failures.append({"annotationClass": "north_indicator", "reason": "north_indicator_requires_line_and_text"})
    missing_annotations = sorted(required - bound_annotations)
    add("annotation_entity_bindings", not annotation_binding_failures, {"failures": annotation_binding_failures, "bindingCount": len(annotation_bindings)})
    add("annotation_completeness", not missing_annotations and not annotation_binding_failures, {"missing": missing_annotations, "requiredCount": len(required), "providedCount": len(bound_annotations), "boundClasses": sorted(bound_annotations)})


    spatial_annotation_classes = {
        "room_name", "door_tag", "window_tag", "wall_type_tag", "opening_schedule_reference",
        "drawing_title", "sheet_number", "plot_scale", "units", "revision_status", "review_status",
        "level_datum", "stair_direction", "section_reference", "elevation_reference", "detail_reference",
    }
    spatial_entity_classes = {
        entity_id: binding["annotationClass"]
        for binding in annotation_bindings
        if binding["annotationClass"] in spatial_annotation_classes
        for entity_id in binding["entityIds"]
    }
    spatial_failures: list[dict[str, Any]] = []
    if resolved_entities is None:
        spatial_failures.append({"reason": "resolved_aicad_entities_not_supplied"})
    else:
        obstacles = [
            (entity_id, entity)
            for entity_id, entity in resolved_entities.items()
            if (
                str(entity.get("type", "")).lower() == "line" and str(entity.get("layer", "")).upper() == "GRID"
                or str(entity.get("type", "")).lower() == "circle" and str(entity.get("layer", "")).upper() in {"COLUMN", "GRID_BUBBLE"}
            )
        ]
        for entity_id, annotation_class in spatial_entity_classes.items():
            entity = resolved_entities.get(entity_id)
            if entity is None or str(entity.get("type", "")).lower() not in {"text", "mtext"}:
                continue
            bbox = _annotation_clearance_bbox(entity)
            if bbox is None:
                spatial_failures.append({"entityId": entity_id, "annotationClass": annotation_class, "reason": "annotation_text_missing_insert_value_or_height"})
                continue
            for obstacle_id, obstacle in obstacles:
                if _axis_or_symbol_hits_bbox(obstacle, bbox):
                    spatial_failures.append({
                        "entityId": entity_id, "annotationClass": annotation_class,
                        "obstacleEntityId": obstacle_id, "obstacleLayer": str(obstacle.get("layer", "")).upper(),
                        "reason": "annotation_clearance_box_hits_axis_or_structural_symbol",
                    })
    add("annotation_spatial_occupancy_clearance", not spatial_failures, {"failures": spatial_failures, "checkedEntityCount": len(spatial_entity_classes)})

    missing_authority = sorted(
        key for key in PRODUCTION_AUTHORITY_FIELDS
        if not contract["authority"][key]["available"] or not contract["authority"][key]["reference"].strip()
    )
    add("production_authority_complete", not missing_authority, {"stage": contract["stage"], "missing": missing_authority})
    locks = contract["safetyLocks"]
    locks_ok = locks == {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True}
    add("safety_locks_preserved", locks_ok, locks)

    status = "pass" if all(row["pass"] for row in checks.values()) else "failed"
    release_allowed = status == "pass" and contract["stage"] == "production" and not missing_authority
    return {
        "schema": "aicad_architectural_detail_validation_v2", "status": status,
        "releaseAllowed": release_allowed,
        "artifactDisposition": "production_release_candidate" if release_allowed else "blocker_report_only",
        "checks": checks,
        "rootCause": "Low-level drafting defects recur when axes, room contents, dimensions, door topology, detailed object graphics, drawing-set coverage and authority are counted independently instead of validated as one production dependency graph.",
        "candidatePreventionRules": ["ARCH-D021", "ARCH-D022", "ARCH-D023", "ARCH-D024", "ARCH-D025", "ARCH-D026", "ARCH-D027", "ARCH-D028", "ARCH-D029", "ARCH-D030", "ARCH-D031", "ARCH-D032", "ARCH-D033", "ARCH-D034", "ARCH-D035", "ARCH-D036", "ARCH-D037", "ARCH-D041", "ARCH-D042", "ARCH-D043", "ARCH-D044", "ARCH-D045", "ARCH-D046"],
        "reviewPolicy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# AICAD 建筑细节契约核验", "", f"- 总状态：**{report['status'].upper()}**",
        f"- 工件处置：`{report['artifactDisposition']}`", f"- 允许生产候选：`{str(report['releaseAllowed']).lower()}`", "",
        "## 检查", "", "| 检查 | 结果 |", "|---|---|",
    ]
    for name, item in report["checks"].items():
        lines.append(f"| `{name}` | `{'pass' if item['pass'] else 'failed'}` |")
    lines.extend(["", "## 根因", "", report["rootCause"], "", "## 预防规则", ""])
    lines.extend(f"- `{rule_id}`" for rule_id in report["candidatePreventionRules"])
    if report["artifactDisposition"] == "blocker_report_only":
        lines.extend(["", "未通过时只允许输出本阻断报告；不得编译、打开或标称施工/生产图。"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate architectural axes, detail completeness, dimension purposes and door host topology before CAD compilation.")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--png", type=Path)
    parser.add_argument("--review-launch", choices=("auto", "always", "never"), default="never")
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    from aicad_agent import _load_plan
    from aicad_review_report import write_html, write_png, write_review_bundle
    from aicad.engine import compile_plan
    compiled = compile_plan(_load_plan(str(args.plan)))
    report = evaluate(contract, normalize_resolved_entities(compiled))
    output = args.output or args.contract.with_suffix(".architecture-detail-qa.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        write_markdown(report, args.markdown)
    review_launch_result = None
    review_launch_json = None
    if args.html:
        bundle = write_review_bundle(report, args.html, args.png, "AICAD 建筑生产输出审核", args.review_launch)
        review_launch_result = bundle["reviewLaunch"]
        review_launch_json = bundle["launchJson"]
    elif args.png:
        write_png(report, args.png, "AICAD 建筑生产输出审核")
    print(json.dumps({"ok": report["status"] == "pass", "status": report["status"], "artifactDisposition": report["artifactDisposition"], "output": str(output.resolve()), "html": str(args.html.resolve()) if args.html else None, "png": str(args.png.resolve()) if args.png else None, "reviewLaunchJson": review_launch_json, "reviewLaunch": review_launch_result}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
