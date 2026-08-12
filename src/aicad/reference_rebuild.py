from __future__ import annotations

import hashlib
import html
import json
import math
import re
from html.parser import HTMLParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import CompiledPlan, PlanError, ResolvedArc, ResolvedCircle, ResolvedLine, compile_plan


@dataclass(frozen=True)
class SimilarityTransform:
    a: float
    b: float
    tx: float
    ty: float
    axis_orientation: str
    rms_error: float
    max_error: float

    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.b, self.a))

    def apply(self, point: list[float] | tuple[float, float]) -> tuple[float, float]:
        x, y = float(point[0]), float(point[1])
        if self.axis_orientation == "y_down":
            y = -y
        return self.a * x - self.b * y + self.tx, self.b * x + self.a * y + self.ty


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _point(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise PlanError(f"{label} must be [x, y]")
    try:
        point = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise PlanError(f"{label} must contain finite numbers") from exc
    if not all(math.isfinite(item) for item in point):
        raise PlanError(f"{label} must contain finite numbers")
    return point


class _SvgCatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: dict[str, dict[str, Any]] = {}
        self._text_id: str | None = None
        self._text_attrs: dict[str, str | None] = {}
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        object_id = values.get("id")
        if not object_id:
            return
        if tag == "line":
            self.items[object_id] = {
                "type": "line",
                "start": [float(values["x1"]), float(values["y1"])],
                "end": [float(values["x2"]), float(values["y2"])],
            }
        elif tag == "circle":
            self.items[object_id] = {
                "type": "circle",
                "center": [float(values["cx"]), float(values["cy"])],
                "radius": float(values["r"]),
            }
        elif tag == "text":
            self._text_id = object_id
            self._text_attrs = values
            self._text_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._text_id is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "text" and self._text_id is not None:
            transform_value = self._text_attrs.get("transform") or ""
            rotation_match = re.search(r"rotate\(\s*([-+0-9.eE]+)", transform_value)
            self.items[self._text_id] = {
                "type": "text",
                "position": [float(self._text_attrs["x"]), float(self._text_attrs["y"])],
                "text": "".join(self._text_parts).strip(),
                "rotation_deg": float(rotation_match.group(1)) if rotation_match else 0.0,
            }
            self._text_id = None
            self._text_attrs = {}
            self._text_parts = []


def _read_svg_catalog(reference: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    if reference.get("kind") not in {"webpage_svg", "svg"}:
        return None
    locator = reference.get("locator")
    if not isinstance(locator, str):
        return None
    path = Path(locator)
    if not path.is_file():
        return None
    parser = _SvgCatalogParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.items


def _catalog_geometry_errors(declared: dict[str, Any], actual: dict[str, Any]) -> dict[str, float]:
    if declared.get("type") != actual.get("type"):
        return {"type_mismatch": math.inf}
    if declared["type"] == "line":
        direct = max(math.dist(declared["start"], actual["start"]), math.dist(declared["end"], actual["end"]))
        reverse = max(math.dist(declared["start"], actual["end"]), math.dist(declared["end"], actual["start"]))
        return {"source_endpoint_error": min(direct, reverse)}
    if declared["type"] == "circle":
        return {
            "source_center_error": math.dist(declared["center"], actual["center"]),
            "source_radius_error": abs(float(declared["radius"]) - float(actual["radius"])),
        }
    return {
        "source_center_error": math.dist(declared["center"], actual["center"]),
        "source_radius_error": abs(float(declared["radius"]) - float(actual["radius"])),
        "source_start_angle_error": _angle_error(float(declared["start_angle_deg"]), float(actual["start_angle_deg"])),
        "source_end_angle_error": _angle_error(float(declared["end_angle_deg"]), float(actual["end_angle_deg"])),
    }

def solve_reference_calibration(spec: dict[str, Any]) -> dict[str, Any]:
    reference = spec.get("reference")
    authority = spec.get("dimension_authority")
    if not isinstance(reference, dict) or not isinstance(authority, dict):
        raise PlanError("reference and dimension_authority are required")
    if authority.get("pixel_is_dimension_truth") is not False:
        raise PlanError("pixel_is_dimension_truth must be false")
    axis = reference.get("axis_orientation", "y_down")
    if axis not in {"y_up", "y_down"}:
        raise PlanError("reference.axis_orientation must be y_up or y_down")
    anchors = authority.get("anchors")
    if not isinstance(anchors, list) or len(anchors) < 2:
        raise PlanError("at least two calibration anchors are required")
    allowed_authorities = {"explicit_dimension", "user_baseline", "native_vector_unit"}
    source: list[tuple[float, float]] = []
    target: list[tuple[float, float]] = []
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict) or anchor.get("authority") not in allowed_authorities:
            raise PlanError(f"dimension_authority.anchors[{index}] lacks physical authority")
        sx, sy = _point(anchor.get("source"), f"anchors[{index}].source")
        if axis == "y_down":
            sy = -sy
        source.append((sx, sy))
        target.append(_point(anchor.get("cad"), f"anchors[{index}].cad"))
    source_center = tuple(sum(point[i] for point in source) / len(source) for i in (0, 1))
    target_center = tuple(sum(point[i] for point in target) / len(target) for i in (0, 1))
    denominator = 0.0
    dot = 0.0
    cross = 0.0
    for source_point, target_point in zip(source, target):
        sx, sy = source_point[0] - source_center[0], source_point[1] - source_center[1]
        tx, ty = target_point[0] - target_center[0], target_point[1] - target_center[1]
        denominator += sx * sx + sy * sy
        dot += sx * tx + sy * ty
        cross += sx * ty - sy * tx
    if denominator <= 1e-18:
        raise PlanError("calibration anchors are coincident")
    a, b = dot / denominator, cross / denominator
    if math.hypot(a, b) <= 1e-12:
        raise PlanError("calibration scale is zero")
    tx = target_center[0] - (a * source_center[0] - b * source_center[1])
    ty = target_center[1] - (b * source_center[0] + a * source_center[1])
    transform = SimilarityTransform(a, b, tx, ty, axis, 0.0, 0.0)
    errors = []
    for raw_anchor, expected in zip(anchors, target):
        actual = transform.apply(raw_anchor["source"])
        errors.append(math.hypot(actual[0] - expected[0], actual[1] - expected[1]))
    rms = math.sqrt(sum(value * value for value in errors) / len(errors))
    maximum = max(errors)
    transform = SimilarityTransform(a, b, tx, ty, axis, rms, maximum)
    rms_limit = float(authority.get("max_rms_error_mm", 0.05))
    max_limit = float(authority.get("max_point_error_mm", 0.1))
    return {
        "ok": rms <= rms_limit and maximum <= max_limit,
        "transform": transform,
        "scale_cad_per_source_unit": transform.scale,
        "rotation_deg": transform.rotation_deg,
        "translation": [transform.tx, transform.ty],
        "axis_orientation": axis,
        "anchor_count": len(anchors),
        "rms_error_mm": rms,
        "max_error_mm": maximum,
        "limits": {"max_rms_error_mm": rms_limit, "max_point_error_mm": max_limit},
        "anchor_errors_mm": errors,
    }


def _entity_map(plan: CompiledPlan) -> dict[str, Any]:
    return {entity.id: entity for entity in plan.entities}


def _require_reference_geometry_subset(plan: CompiledPlan) -> None:
    unsupported = [
        f"{entity.id}:{type(entity).__name__}"
        for entity in plan.entities
        if not isinstance(entity, (ResolvedLine, ResolvedCircle, ResolvedArc))
    ]
    if unsupported:
        raise PlanError(
            "reference reconstruction accepts only line/circle/arc source geometry; "
            "native TEXT/DIMENSION must remain in the main AICAD export path: " + ", ".join(unsupported)
        )


def _source_geometry(binding: dict[str, Any], transform: SimilarityTransform) -> dict[str, Any]:
    geometry = binding.get("source_geometry")
    if not isinstance(geometry, dict):
        raise PlanError(f"binding {binding.get('id')} has no source_geometry")
    kind = geometry.get("type")
    if kind == "line":
        return {"type": "line", "start": transform.apply(geometry.get("start")), "end": transform.apply(geometry.get("end"))}
    if kind in {"circle", "arc"}:
        radius = float(geometry.get("radius")) * transform.scale
        result = {"type": kind, "center": transform.apply(geometry.get("center")), "radius": radius}
        if kind == "arc":
            result["start_angle_deg"] = float(geometry.get("start_angle_deg")) + transform.rotation_deg
            result["end_angle_deg"] = float(geometry.get("end_angle_deg")) + transform.rotation_deg
        return result
    raise PlanError(f"binding {binding.get('id')} has unsupported source geometry '{kind}'")


def _angle_error(first: float, second: float) -> float:
    return abs(math.degrees(math.atan2(math.sin(math.radians(first - second)), math.cos(math.radians(first - second)))))


def _geometry_error(entity: Any, geometry: dict[str, Any]) -> dict[str, float]:
    if isinstance(entity, ResolvedLine) and geometry["type"] == "line":
        direct = max(math.dist(entity.start, geometry["start"]), math.dist(entity.end, geometry["end"]))
        reverse = max(math.dist(entity.start, geometry["end"]), math.dist(entity.end, geometry["start"]))
        return {"endpoint_error_mm": min(direct, reverse)}
    if isinstance(entity, ResolvedCircle) and geometry["type"] == "circle":
        return {
            "center_error_mm": math.dist(entity.center, geometry["center"]),
            "radius_error_mm": abs(entity.radius - geometry["radius"]),
        }
    if isinstance(entity, ResolvedArc) and geometry["type"] == "arc":
        return {
            "center_error_mm": math.dist(entity.center, geometry["center"]),
            "radius_error_mm": abs(entity.radius - geometry["radius"]),
            "start_angle_error_deg": _angle_error(entity.start_angle_deg, geometry["start_angle_deg"]),
            "end_angle_error_deg": _angle_error(entity.end_angle_deg, geometry["end_angle_deg"]),
        }
    raise PlanError(f"binding geometry type does not match target {entity.id}")


def _resolve_entity_point(entity: Any, point_name: str) -> tuple[float, float]:
    if isinstance(entity, ResolvedLine) and point_name in {"start", "end", "midpoint"}:
        if point_name == "start":
            return entity.start
        if point_name == "end":
            return entity.end
        return ((entity.start[0] + entity.end[0]) / 2.0, (entity.start[1] + entity.end[1]) / 2.0)
    if isinstance(entity, (ResolvedCircle, ResolvedArc)) and point_name == "center":
        return entity.center
    raise PlanError(f"point selector '{point_name}' is invalid for {entity.id}")


def _annotation_point(value: Any, entities: dict[str, Any], label: str) -> tuple[float, float]:
    if isinstance(value, list):
        return _point(value, label)
    if not isinstance(value, dict) or not isinstance(value.get("target"), str):
        raise PlanError(f"{label} must be a point or target point reference")
    entity = entities.get(value["target"])
    if entity is None:
        raise PlanError(f"{label} target '{value['target']}' does not exist")
    return _resolve_entity_point(entity, str(value.get("point")))


def _annotation_boxes(spec: dict[str, Any], entities: dict[str, Any]) -> list[dict[str, Any]]:
    presentation = spec.get("presentation", {})
    styles = presentation.get("styles", {}) if isinstance(presentation, dict) else {}
    text_style = styles.get("text", {}) if isinstance(styles, dict) else {}
    default_height = float(text_style.get("height_mm", 3.5))
    boxes: list[dict[str, Any]] = []
    for annotation in presentation.get("annotations", []):
        kind = annotation.get("type")
        if kind == "text":
            position = _point(annotation.get("position"), f"annotation {annotation.get('id')}.position")
            height = float(annotation.get("height_mm", default_height))
            width = float(annotation.get("width_mm", max(height, len(str(annotation.get("text", ""))) * height * 0.62)))
        elif kind == "linear_dimension":
            position = _point(annotation.get("placement"), f"annotation {annotation.get('id')}.placement")
            height = float(annotation.get("text_height_mm", default_height))
            width = max(height * 4.0, len(str(annotation.get("expected_value", ""))) * height * 0.7)
        elif kind == "diameter_dimension":
            position = _point(annotation.get("placement"), f"annotation {annotation.get('id')}.placement")
            height = float(annotation.get("text_height_mm", default_height))
            width = height * 6.0
        else:
            continue
        rotation = math.radians(float(annotation.get("rotation_deg", 0.0)))
        rotated_width = abs(width * math.cos(rotation)) + abs(height * math.sin(rotation))
        rotated_height = abs(width * math.sin(rotation)) + abs(height * math.cos(rotation))
        boxes.append({
            "id": annotation.get("id"),
            "box": [
                position[0] - rotated_width / 2.0, position[1] - rotated_height / 2.0,
                position[0] + rotated_width / 2.0, position[1] + rotated_height / 2.0,
            ],
            "allow_overlap": bool(annotation.get("allow_overlap", False)),
        })
    return boxes


def _boxes_overlap(first: list[float], second: list[float], gap: float = 0.5) -> bool:
    return not (
        first[2] + gap <= second[0] or second[2] + gap <= first[0]
        or first[3] + gap <= second[1] or second[3] + gap <= first[1]
    )


def _text_encoding_issues(values: list[tuple[str, str]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    suspicious_sequences = ("\u94fe\u70d8", "\u951f", "\u704f", "\u95ab", "\u7470", "\u93b4", "\u942e", "\u7eeb")
    for label, value in values:
        if not isinstance(value, str):
            continue
        markers: list[str] = []
        if "\ufffd" in value:
            markers.append("replacement_character")
        if any(0xE000 <= ord(character) <= 0xF8FF for character in value):
            markers.append("private_use_character")
        for sequence in suspicious_sequences:
            if sequence in value:
                markers.append(f"suspected_mojibake_u{ord(sequence[0]):04x}")
        if markers:
            issues.append({"field": label, "markers": sorted(set(markers))})
    return issues

def validate_reference_rebuild(plan_data: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict) or spec.get("schema_version") != "1.0":
        raise PlanError("reference rebuild schema_version must be '1.0'")
    policy = spec.get("review_policy", {})
    if policy.get("reviewOnly") is not True or policy.get("accepted") is not False or policy.get("ruleEnabled") is not False:
        raise PlanError("reference rebuild must remain reviewOnly=true, accepted=false, ruleEnabled=false")
    plan = compile_plan(plan_data)
    _require_reference_geometry_subset(plan)
    reference = spec.get("reference", {})
    locator = reference.get("locator")
    source_hash_verified: bool | None = None
    if isinstance(locator, str):
        source_path = Path(locator)
        if source_path.is_file():
            actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            source_hash_verified = actual_hash == reference.get("content_sha256")
    dom_catalog = _read_svg_catalog(reference)
    calibration = solve_reference_calibration(spec)
    transform: SimilarityTransform = calibration["transform"]
    entities = _entity_map(plan)
    rows: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for index, binding in enumerate(spec.get("geometry_bindings", [])):
        if not isinstance(binding, dict):
            raise PlanError(f"geometry_bindings[{index}] must be an object")
        target_id = binding.get("target_object_id")
        if not isinstance(target_id, str) or target_id not in entities:
            raise PlanError(f"geometry binding target '{target_id}' does not exist")
        if target_id in seen_targets:
            raise PlanError(f"target '{target_id}' has duplicate geometry bindings")
        seen_targets.add(target_id)
        reference_object_id = binding.get("reference_object_id")
        catalog_geometry = dom_catalog.get(reference_object_id) if dom_catalog is not None else None
        source_catalog_errors: dict[str, float] = {}
        source_catalog_ok = dom_catalog is None
        effective_binding = binding
        if dom_catalog is not None:
            if catalog_geometry is None or catalog_geometry.get("type") == "text":
                source_catalog_errors = {"missing_reference_object": math.inf}
                source_catalog_ok = False
            else:
                source_catalog_errors = _catalog_geometry_errors(binding["source_geometry"], catalog_geometry)
                source_tolerance = float(binding.get("source_tolerance", 1e-9))
                source_catalog_ok = all(value <= source_tolerance for value in source_catalog_errors.values())
                effective_binding = {**binding, "source_geometry": catalog_geometry}
        transformed = _source_geometry(effective_binding, transform)
        errors = _geometry_error(entities[target_id], transformed)
        tolerance = float(binding.get("tolerance_mm", plan.tolerance))
        angle_tolerance = float(binding.get("angle_tolerance_deg", 0.05))
        ok = source_catalog_ok and all(value <= (angle_tolerance if key.endswith("_deg") else tolerance) for key, value in errors.items())
        rows.append({
            "binding_id": binding.get("id"), "reference_object_id": binding.get("reference_object_id"),
            "target_object_id": target_id, "ok": ok, "tolerance_mm": tolerance,
            "angle_tolerance_deg": angle_tolerance, "errors": errors, "source_catalog_ok": source_catalog_ok, "source_catalog_errors": source_catalog_errors, "transformed_geometry": transformed,
        })
    coverage = spec.get("coverage", {})
    required_targets = set(coverage.get("required_target_ids", []))
    missing_targets = sorted(required_targets - seen_targets)
    unexpected_targets = sorted(seen_targets - set(entities))
    annotations = spec.get("presentation", {}).get("annotations", [])
    annotation_ids = {item.get("id") for item in annotations if isinstance(item, dict)}
    missing_annotations = sorted(set(coverage.get("required_annotation_ids", [])) - annotation_ids)
    dimension_checks: list[dict[str, Any]] = []
    layout_checks: list[dict[str, Any]] = []
    annotation_source_checks: list[dict[str, Any]] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        kind = annotation.get("type")
        reference_object_id = annotation.get("reference_object_id")
        source_entry = dom_catalog.get(reference_object_id) if dom_catalog is not None else None
        if dom_catalog is not None:
            source_tolerance = float(annotation.get("source_tolerance", 1e-9))
            if source_entry is None or source_entry.get("type") != "text":
                annotation_source_checks.append({"id": annotation.get("id"), "ok": False, "reason": "missing_reference_text_object"})
            else:
                position_error = math.dist(source_entry["position"], annotation.get("source_position", [math.inf, math.inf]))
                text_matches = source_entry["text"] == annotation.get("reference_text")
                source_rotation = float(source_entry.get("rotation_deg", 0.0))
                declared_source_rotation = float(annotation.get("source_rotation_deg", 0.0))
                source_rotation_error = _angle_error(source_rotation, declared_source_rotation)
                rotation_tolerance = float(annotation.get("rotation_tolerance_deg", 0.01))
                annotation_source_checks.append({
                    "id": annotation.get("id"),
                    "ok": position_error <= source_tolerance and text_matches and source_rotation_error <= rotation_tolerance,
                    "position_error_source_units": position_error, "text_matches": text_matches,
                    "source_rotation_error_deg": source_rotation_error, "rotation_tolerance_deg": rotation_tolerance,
                    "actual_text": source_entry["text"], "expected_text": annotation.get("reference_text"),
                })
        source_position = annotation.get("source_position")
        actual_position = annotation.get("position") if kind == "text" else annotation.get("placement")
        if source_position is not None and actual_position is not None:
            source_exact_position = transform.apply(source_position)
            layout_offset = _point(annotation.get("layout_offset_mm", [0.0, 0.0]), f"{annotation.get('id')}.layout_offset_mm")
            layout_mode = str(annotation.get("layout_mode", "source_exact"))
            max_layout_offset = float(annotation.get("max_layout_offset_mm", 0.0))
            layout_offset_length = math.hypot(*layout_offset)
            offset_reason = str(annotation.get("layout_offset_reason", ""))
            layout_tolerance = float(annotation.get("layout_tolerance_mm", plan.tolerance))
            offset_policy_ok = (
                layout_offset_length <= layout_tolerance
                if layout_mode == "source_exact"
                else layout_mode == "optimized_offset" and layout_offset_length <= max_layout_offset and bool(offset_reason.strip())
            )
            expected_position = (
                source_exact_position[0] + layout_offset[0],
                source_exact_position[1] + layout_offset[1],
            )
            actual_layout_position = _point(actual_position, f"{annotation.get('id')}.layout_position")
            layout_error = math.dist(expected_position, actual_layout_position)
            declared_source_rotation = float(annotation.get("source_rotation_deg", 0.0))
            expected_rotation = transform.rotation_deg + (-declared_source_rotation if transform.axis_orientation == "y_down" else declared_source_rotation)
            actual_rotation = float(annotation.get("rotation_deg", 0.0))
            rotation_error = _angle_error(expected_rotation, actual_rotation)
            rotation_tolerance = float(annotation.get("rotation_tolerance_deg", 0.01))
            layout_checks.append({
                "id": annotation.get("id"), "source_exact_position": list(source_exact_position),
                "layout_mode": layout_mode, "layout_offset_mm": list(layout_offset),
                "layout_offset_length_mm": layout_offset_length, "max_layout_offset_mm": max_layout_offset,
                "layout_offset_reason": offset_reason, "offset_policy_ok": offset_policy_ok,
                "expected": list(expected_position), "actual": list(actual_layout_position),
                "error_mm": layout_error, "tolerance_mm": layout_tolerance,
                "expected_rotation_deg": expected_rotation, "actual_rotation_deg": actual_rotation,
                "rotation_error_deg": rotation_error, "rotation_tolerance_deg": rotation_tolerance,
                "ok": offset_policy_ok and layout_error <= layout_tolerance and rotation_error <= rotation_tolerance,
            })
        elif coverage.get("mode") == "one_to_one":
            layout_checks.append({
                "id": annotation.get("id"), "expected": None, "actual": actual_position,
                "error_mm": None, "tolerance_mm": None, "ok": False,
                "reason": "one_to_one annotation lacks source_position",
            })
        if kind == "linear_dimension":
            first = _annotation_point(annotation.get("from"), entities, f"{annotation.get('id')}.from")
            second = _annotation_point(annotation.get("to"), entities, f"{annotation.get('id')}.to")
            axis = annotation.get("axis")
            actual = abs(second[0] - first[0]) if axis == "horizontal" else abs(second[1] - first[1]) if axis == "vertical" else math.dist(first, second)
            expected = float(annotation.get("expected_value"))
            tolerance = float(annotation.get("tolerance_mm", plan.tolerance))
            dimension_checks.append({"id": annotation.get("id"), "actual": actual, "expected": expected, "error": abs(actual - expected), "ok": abs(actual - expected) <= tolerance})
        elif kind == "diameter_dimension":
            target = entities.get(annotation.get("target"))
            if not isinstance(target, (ResolvedCircle, ResolvedArc)):
                raise PlanError(f"diameter annotation {annotation.get('id')} requires a circle or arc")
            actual = target.radius * 2.0
            expected = float(annotation.get("expected_value"))
            tolerance = float(annotation.get("tolerance_mm", plan.tolerance))
            dimension_checks.append({"id": annotation.get("id"), "actual": actual, "expected": expected, "error": abs(actual - expected), "ok": abs(actual - expected) <= tolerance})
    boxes = _annotation_boxes(spec, entities)
    overlaps: list[list[str]] = []
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            if not first["allow_overlap"] and not second["allow_overlap"] and _boxes_overlap(first["box"], second["box"]):
                overlaps.append([str(first["id"]), str(second["id"])])
    layer_styles = _layer_styles(spec, plan)
    outline_weights = [float(layer_styles[name].get("lineweight_mm", 0.0)) for name in {entity.layer for entity in plan.entities}]
    dimension_weight = float(layer_styles.get("DIMENSION", {}).get("lineweight_mm", 0.0))
    text_style_value = spec.get("presentation", {}).get("styles", {}).get("text", {})
    dimension_style_value = spec.get("presentation", {}).get("styles", {}).get("dimension", {})
    style_checks = {
        "outline_heavier_than_dimensions": bool(outline_weights) and min(outline_weights) > dimension_weight > 0,
        "positive_text_height": float(text_style_value.get("height_mm", 0.0)) > 0,
        "positive_dimension_text_and_arrows": float(dimension_style_value.get("text_height_mm", 0.0)) > 0 and float(dimension_style_value.get("arrow_size_mm", 0.0)) > 0,
    }
    text_values: list[tuple[str, str]] = []
    if dom_catalog is not None:
        text_values.extend(
            (f"reference_dom.{object_id}", str(item.get("text", "")))
            for object_id, item in dom_catalog.items() if item.get("type") == "text"
        )
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        annotation_id = str(annotation.get("id", "unknown"))
        for field in ("text", "reference_text", "prefix", "suffix"):
            if isinstance(annotation.get(field), str):
                text_values.append((f"annotation.{annotation_id}.{field}", annotation[field]))
    text_encoding_issues = _text_encoding_issues(text_values)
    checks = {
        "source_content_hash_verified": source_hash_verified is True,
        "reference_dom_catalog_verified": (
            dom_catalog is not None
            and all(row["source_catalog_ok"] for row in rows)
            and bool(annotation_source_checks) and all(item["ok"] for item in annotation_source_checks)
        ) if reference.get("kind") in {"webpage_svg", "svg"} else True,        "source_text_encoding_valid": not text_encoding_issues,
        "pixel_not_dimension_truth": spec["dimension_authority"].get("pixel_is_dimension_truth") is False,
        "calibration_within_tolerance": bool(calibration["ok"]),
        "geometry_bindings_match": bool(rows) and all(row["ok"] for row in rows),
        "one_to_one_target_coverage": not missing_targets and not unexpected_targets,
        "required_annotations_present": not missing_annotations,
        "dimension_values_match": bool(dimension_checks) and all(item["ok"] for item in dimension_checks),
        "annotation_layout_matches_reference": bool(layout_checks) and all(item["ok"] for item in layout_checks),
        "annotation_layout_policy_valid": bool(layout_checks) and all(item["offset_policy_ok"] for item in layout_checks),
        "drafting_style_hierarchy_valid": all(style_checks.values()),
        "annotation_boxes_do_not_overlap": not overlaps,
        "review_policy_locked": True,
    }
    return {
        "ok": all(checks.values()), "status": "pass" if all(checks.values()) else "failed",
        "space": "2d", "domain": plan.domain, "plan_sha256": plan.source_hash,
        "reference_sha256": reference.get("content_sha256"), "spec_sha256": _canonical_sha256(spec),
        "source_hash_verified": source_hash_verified,
        "calibration": {key: value for key, value in calibration.items() if key != "transform"},
        "geometry_bindings": rows, "dimension_checks": dimension_checks, "layout_checks": layout_checks, "annotation_source_checks": annotation_source_checks, "style_checks": style_checks, "reference_dom_object_count": len(dom_catalog) if dom_catalog is not None else None,
        "coverage": {
            "required_targets": sorted(required_targets), "bound_targets": sorted(seen_targets),
            "missing_targets": missing_targets, "unexpected_targets": unexpected_targets,
            "missing_annotations": missing_annotations,
        },
        "annotation_overlap_pairs": overlaps, "text_encoding_issues": text_encoding_issues, "checks": checks,
        "review_policy": policy,
        "limits": {
            "web_pixels_are_not_dimension_authority": True,
            "raster_extraction_requires_agent_or_human_object_catalog": True,
            "native_dimension_objects_require_host_postprocess": True,
        },
    }


def _fmt(value: float) -> str:
    text = format(float(value), ".12g")
    return "0" if text in {"-0", "-0.0"} else text


def _dxf_pair(code: int, value: Any) -> str:
    return f"{code}\n{value}\n"


def _dxf_unicode(value: str) -> str:
    result: list[str] = []
    for character in value:
        code = ord(character)
        if 32 <= code < 127 and character != "\\":
            result.append(character)
        elif code <= 0xFFFF:
            result.append(f"\\U+{code:04X}")
        else:
            result.append("?")
    return "".join(result)


def _layer_styles(spec: dict[str, Any], plan: CompiledPlan) -> dict[str, dict[str, Any]]:
    supplied = spec.get("presentation", {}).get("styles", {}).get("layers", {})
    defaults = {
        "AICAD_GEOMETRY": {"color": 7, "lineweight_mm": 0.25, "linetype": "CONTINUOUS"},
        "DIMENSION": {"color": 3, "lineweight_mm": 0.18, "linetype": "CONTINUOUS"},
        "TEXT": {"color": 7, "lineweight_mm": 0.18, "linetype": "CONTINUOUS"},
        "FRAME": {"color": 8, "lineweight_mm": 0.35, "linetype": "CONTINUOUS"},
    }
    for entity in plan.entities:
        defaults.setdefault(entity.layer, {"color": 7, "lineweight_mm": 0.25, "linetype": "CONTINUOUS"})
    for name, value in supplied.items():
        defaults[name] = {**defaults.get(name, {}), **value}
    return defaults


def _line_entity(layer: str, start: tuple[float, float], end: tuple[float, float]) -> list[str]:
    return [
        _dxf_pair(0, "LINE"), _dxf_pair(8, layer),
        _dxf_pair(10, _fmt(start[0])), _dxf_pair(20, _fmt(start[1])), _dxf_pair(30, 0),
        _dxf_pair(11, _fmt(end[0])), _dxf_pair(21, _fmt(end[1])), _dxf_pair(31, 0),
    ]


def _mtext_entity(layer: str, position: tuple[float, float], value: str, height: float, width: float, rotation: float = 0.0, attachment: int = 5) -> list[str]:
    return [
        _dxf_pair(0, "MTEXT"), _dxf_pair(8, layer), _dxf_pair(10, _fmt(position[0])),
        _dxf_pair(20, _fmt(position[1])), _dxf_pair(30, 0), _dxf_pair(40, _fmt(height)),
        _dxf_pair(41, _fmt(width)), _dxf_pair(50, _fmt(rotation)), _dxf_pair(71, attachment),
        _dxf_pair(1, _dxf_unicode(value)),
    ]


def _dimension_graphics(annotation: dict[str, Any], entities: dict[str, Any], style: dict[str, Any]) -> tuple[list[tuple[tuple[float, float], tuple[float, float]]], str, tuple[float, float]]:
    first = _annotation_point(annotation.get("from"), entities, f"{annotation.get('id')}.from")
    second = _annotation_point(annotation.get("to"), entities, f"{annotation.get('id')}.to")
    placement = _point(annotation.get("placement"), f"{annotation.get('id')}.placement")
    axis = annotation.get("axis")
    arrow = float(style.get("arrow_size_mm", 2.5))
    gap = float(style.get("extension_gap_mm", 1.0))
    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    if axis == "horizontal":
        y = placement[1]
        a, b = (first[0], y), (second[0], y)
        direction = 1.0 if b[0] >= a[0] else -1.0
        lines.extend([
            ((first[0], first[1] + math.copysign(gap, y - first[1] or 1.0)), a),
            ((second[0], second[1] + math.copysign(gap, y - second[1] or 1.0)), b), (a, b),
            (a, (a[0] + direction * arrow, a[1] + arrow * 0.45)),
            (a, (a[0] + direction * arrow, a[1] - arrow * 0.45)),
            (b, (b[0] - direction * arrow, b[1] + arrow * 0.45)),
            (b, (b[0] - direction * arrow, b[1] - arrow * 0.45)),
        ])
        value = abs(second[0] - first[0])
    elif axis == "vertical":
        x = placement[0]
        a, b = (x, first[1]), (x, second[1])
        direction = 1.0 if b[1] >= a[1] else -1.0
        lines.extend([
            ((first[0] + math.copysign(gap, x - first[0] or 1.0), first[1]), a),
            ((second[0] + math.copysign(gap, x - second[0] or 1.0), second[1]), b), (a, b),
            (a, (a[0] + arrow * 0.45, a[1] + direction * arrow)),
            (a, (a[0] - arrow * 0.45, a[1] + direction * arrow)),
            (b, (b[0] + arrow * 0.45, b[1] - direction * arrow)),
            (b, (b[0] - arrow * 0.45, b[1] - direction * arrow)),
        ])
        value = abs(second[1] - first[1])
    else:
        raise PlanError("linear_dimension.axis must be horizontal or vertical")
    precision = int(annotation.get("precision", 0))
    label = f"{annotation.get('prefix', '')}{value:.{precision}f}{annotation.get('suffix', '')}"
    return lines, label, placement


def write_reference_dxf(plan: CompiledPlan, spec: dict[str, Any], path: Path) -> dict[str, int]:
    layers = _layer_styles(spec, plan)
    content = [
        _dxf_pair(0, "SECTION"), _dxf_pair(2, "HEADER"), _dxf_pair(9, "$ACADVER"), _dxf_pair(1, "AC1027"),
        _dxf_pair(9, "$INSUNITS"), _dxf_pair(70, 4 if plan.units == "mm" else 1), _dxf_pair(0, "ENDSEC"),
        _dxf_pair(0, "SECTION"), _dxf_pair(2, "TABLES"), _dxf_pair(0, "TABLE"), _dxf_pair(2, "LAYER"), _dxf_pair(70, len(layers)),
    ]
    lineweight_codes = {0.05: 5, 0.09: 9, 0.13: 13, 0.18: 18, 0.25: 25, 0.35: 35, 0.5: 50, 0.7: 70}
    for name, style in layers.items():
        width = min(lineweight_codes, key=lambda value: abs(value - float(style.get("lineweight_mm", 0.25))))
        content.extend([
            _dxf_pair(0, "LAYER"), _dxf_pair(2, name), _dxf_pair(70, 0),
            _dxf_pair(62, int(style.get("color", 7))), _dxf_pair(6, style.get("linetype", "CONTINUOUS")),
            _dxf_pair(370, lineweight_codes[width]),
        ])
    content.extend([_dxf_pair(0, "ENDTAB"), _dxf_pair(0, "ENDSEC"), _dxf_pair(0, "SECTION"), _dxf_pair(2, "ENTITIES")])
    counts = {"line": 0, "circle": 0, "arc": 0, "mtext": 0, "dimension_graphics": 0}
    for entity in plan.entities:
        if isinstance(entity, ResolvedLine):
            content.extend(_line_entity(entity.layer, entity.start, entity.end))
            counts["line"] += 1
        elif isinstance(entity, ResolvedCircle):
            content.extend([
                _dxf_pair(0, "CIRCLE"), _dxf_pair(8, entity.layer), _dxf_pair(10, _fmt(entity.center[0])),
                _dxf_pair(20, _fmt(entity.center[1])), _dxf_pair(30, 0), _dxf_pair(40, _fmt(entity.radius)),
            ])
            counts["circle"] += 1
        else:
            content.extend([
                _dxf_pair(0, "ARC"), _dxf_pair(8, entity.layer), _dxf_pair(10, _fmt(entity.center[0])),
                _dxf_pair(20, _fmt(entity.center[1])), _dxf_pair(30, 0), _dxf_pair(40, _fmt(entity.radius)),
                _dxf_pair(50, _fmt(entity.start_angle_deg)), _dxf_pair(51, _fmt(entity.end_angle_deg)),
            ])
            counts["arc"] += 1
    entities = _entity_map(plan)
    styles = spec.get("presentation", {}).get("styles", {})
    text_style = styles.get("text", {})
    dimension_style = styles.get("dimension", {})
    for annotation in spec.get("presentation", {}).get("annotations", []):
        kind = annotation.get("type")
        layer = str(annotation.get("layer", "TEXT" if kind == "text" else "DIMENSION"))
        if kind == "text":
            height = float(annotation.get("height_mm", text_style.get("height_mm", 3.5)))
            width = float(annotation.get("width_mm", max(20.0, len(str(annotation.get("text", ""))) * height * 0.7)))
            content.extend(_mtext_entity(layer, _point(annotation.get("position"), "text.position"), str(annotation.get("text", "")), height, width, float(annotation.get("rotation_deg", 0.0)), int(annotation.get("attachment", 5))))
            counts["mtext"] += 1
        elif kind == "linear_dimension":
            lines, label, placement = _dimension_graphics(annotation, entities, dimension_style)
            for start, end in lines:
                content.extend(_line_entity(layer, start, end))
                counts["dimension_graphics"] += 1
            height = float(annotation.get("text_height_mm", dimension_style.get("text_height_mm", 3.5)))
            content.extend(_mtext_entity(layer, placement, label, height, max(12.0, len(label) * height), float(annotation.get("rotation_deg", 0.0)), 5))
            counts["mtext"] += 1
        elif kind == "diameter_dimension":
            target = entities[annotation["target"]]
            placement = _point(annotation.get("placement"), "diameter_dimension.placement")
            center = target.center
            vector = placement[0] - center[0], placement[1] - center[1]
            length = math.hypot(*vector) or 1.0
            edge = center[0] + vector[0] / length * target.radius, center[1] + vector[1] / length * target.radius
            content.extend(_line_entity(layer, edge, placement))
            counts["dimension_graphics"] += 1
            value = target.radius * 2.0
            precision = int(annotation.get("precision", 0))
            label = f"{annotation.get('prefix', '\u2300')}{value:.{precision}f}{annotation.get('suffix', '')}"
            height = float(annotation.get("text_height_mm", dimension_style.get("text_height_mm", 3.5)))
            content.extend(_mtext_entity(layer, placement, label, height, max(14.0, len(label) * height), float(annotation.get("rotation_deg", 0.0)), 5))
            counts["mtext"] += 1
    content.extend([_dxf_pair(0, "ENDSEC"), _dxf_pair(0, "EOF")])
    path.write_text("".join(content), encoding="ascii", newline="\n")
    return counts


def _plan_bounds(plan: CompiledPlan) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for entity in plan.entities:
        if isinstance(entity, ResolvedLine):
            xs.extend([entity.start[0], entity.end[0]])
            ys.extend([entity.start[1], entity.end[1]])
        else:
            xs.extend([entity.center[0] - entity.radius, entity.center[0] + entity.radius])
            ys.extend([entity.center[1] - entity.radius, entity.center[1] + entity.radius])
    return min(xs), min(ys), max(xs), max(ys)


def render_reference_svg(plan: CompiledPlan, spec: dict[str, Any], validation: dict[str, Any]) -> str:
    left, bottom, right, top = _plan_bounds(plan)
    boxes = _annotation_boxes(spec, _entity_map(plan))
    for row in boxes:
        left, bottom = min(left, row["box"][0]), min(bottom, row["box"][1])
        right, top = max(right, row["box"][2]), max(top, row["box"][3])
    margin = max(right - left, top - bottom, 1.0) * 0.08
    left, bottom, right, top = left - margin, bottom - margin, right + margin, top + margin
    width, height = right - left, top - bottom
    styles = _layer_styles(spec, plan)
    color_map = {1: "#dc2626", 2: "#d97706", 3: "#16a34a", 4: "#0891b2", 5: "#2563eb", 6: "#c026d3", 7: "#111827", 8: "#64748b"}

    def xy(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] - left, top - point[1]

    def style(layer: str) -> tuple[str, float]:
        value = styles.get(layer, styles["AICAD_GEOMETRY"])
        return color_map.get(int(value.get("color", 7)), "#111827"), max(0.6, float(value.get("lineweight_mm", 0.25)) * 3.0)

    canvas_width = 1600.0
    canvas_height = canvas_width * height / width
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width:g}" height="{canvas_height:g}" viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="AICAD reference reconstruction">',
        f'<rect width="{width:g}" height="{height:g}" fill="#ffffff"/>',
        '<g id="cad-geometry">',
    ]
    for entity in plan.entities:
        color, stroke = style(entity.layer)
        if isinstance(entity, ResolvedLine):
            start, end = xy(entity.start), xy(entity.end)
            rows.append(f'<line data-object-id="{entity.id}" x1="{start[0]:g}" y1="{start[1]:g}" x2="{end[0]:g}" y2="{end[1]:g}" fill="none" stroke="{color}" stroke-width="{stroke:g}" vector-effect="non-scaling-stroke"/>')
        elif isinstance(entity, ResolvedCircle):
            center = xy(entity.center)
            rows.append(f'<circle data-object-id="{entity.id}" cx="{center[0]:g}" cy="{center[1]:g}" r="{entity.radius:g}" fill="none" stroke="{color}" stroke-width="{stroke:g}" vector-effect="non-scaling-stroke"/>')
        else:
            start = xy(entity.start)
            end = xy(entity.end)
            large = 1 if entity.sweep_angle_deg > 180 else 0
            rows.append(f'<path data-object-id="{entity.id}" d="M {start[0]:g},{start[1]:g} A {entity.radius:g},{entity.radius:g} 0 {large} 0 {end[0]:g},{end[1]:g}" fill="none" stroke="{color}" stroke-width="{stroke:g}" vector-effect="non-scaling-stroke"/>')
    rows.append('</g><g id="annotations">')
    entities = _entity_map(plan)
    dimension_style = spec.get("presentation", {}).get("styles", {}).get("dimension", {})
    for annotation in spec.get("presentation", {}).get("annotations", []):
        kind = annotation.get("type")
        layer = annotation.get("layer", "TEXT" if kind == "text" else "DIMENSION")
        color, stroke = style(layer)
        if kind == "text":
            position = xy(_point(annotation["position"], "text.position"))
            size = float(annotation.get("height_mm", 3.5))
            rotation = -float(annotation.get("rotation_deg", 0.0))
            rotation_attr = f' transform="rotate({rotation:g} {position[0]:g} {position[1]:g})"' if abs(rotation) > 1e-12 else ""
            rows.append(f'<text data-annotation-id="{html.escape(annotation["id"])}" x="{position[0]:g}" y="{position[1]:g}" fill="{color}" font-family="Microsoft YaHei, sans-serif" font-size="{size:g}" text-anchor="middle"{rotation_attr}>{html.escape(str(annotation["text"]))}</text>')
        elif kind == "linear_dimension":
            lines, label, placement = _dimension_graphics(annotation, entities, dimension_style)
            for start, end in lines:
                first, second = xy(start), xy(end)
                rows.append(f'<line x1="{first[0]:g}" y1="{first[1]:g}" x2="{second[0]:g}" y2="{second[1]:g}" stroke="{color}" stroke-width="{stroke:g}" vector-effect="non-scaling-stroke"/>')
            position = xy(placement)
            size = float(annotation.get("text_height_mm", dimension_style.get("text_height_mm", 3.5)))
            rotation = -float(annotation.get("rotation_deg", 0.0))
            rotation_attr = f' transform="rotate({rotation:g} {position[0]:g} {position[1]:g})"' if abs(rotation) > 1e-12 else ""
            rows.append(f'<text data-annotation-id="{html.escape(annotation["id"])}" x="{position[0]:g}" y="{position[1]:g}" fill="{color}" font-family="Microsoft YaHei, sans-serif" font-size="{size:g}" text-anchor="middle"{rotation_attr}>{html.escape(label)}</text>')
        elif kind == "diameter_dimension":
            target = entities[annotation["target"]]
            placement_raw = _point(annotation["placement"], "diameter.placement")
            vector = placement_raw[0] - target.center[0], placement_raw[1] - target.center[1]
            length = math.hypot(*vector) or 1.0
            edge_raw = target.center[0] + vector[0] / length * target.radius, target.center[1] + vector[1] / length * target.radius
            edge, placement = xy(edge_raw), xy(placement_raw)
            rows.append(f'<line x1="{edge[0]:g}" y1="{edge[1]:g}" x2="{placement[0]:g}" y2="{placement[1]:g}" stroke="{color}" stroke-width="{stroke:g}" vector-effect="non-scaling-stroke"/>')
            value = target.radius * 2.0
            precision = int(annotation.get("precision", 0))
            label = f"{annotation.get('prefix', '\u2300')}{value:.{precision}f}{annotation.get('suffix', '')}"
            size = float(annotation.get("text_height_mm", dimension_style.get("text_height_mm", 3.5)))
            rotation = -float(annotation.get("rotation_deg", 0.0))
            rotation_attr = f' transform="rotate({rotation:g} {placement[0]:g} {placement[1]:g})"' if abs(rotation) > 1e-12 else ""
            rows.append(f'<text data-annotation-id="{html.escape(annotation["id"])}" x="{placement[0]:g}" y="{placement[1]:g}" fill="{color}" font-family="Microsoft YaHei, sans-serif" font-size="{size:g}" text-anchor="middle"{rotation_attr}>{html.escape(label)}</text>')
    rows.append('</g>')
    status = "PASS" if validation["status"] == "pass" else "FAILED"
    rows.append(f'<text x="4" y="{height - 4:g}" fill="#475569" font-family="Microsoft YaHei, sans-serif" font-size="3">reference reconstruction {status} &#x00B7; geometry 1:1 in CAD units &#x00B7; pixels not dimension truth</text>')
    rows.append('</svg>')
    return "".join(rows)


def build_reference_reconstruction(plan_data: dict[str, Any], spec: dict[str, Any], output_dir: Path, stem: str) -> dict[str, Any]:
    validation = validate_reference_rebuild(plan_data, spec)
    if validation["status"] != "pass":
        raise PlanError("reference reconstruction validation failed")
    plan = compile_plan(plan_data)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "spec": output_dir / f"{stem}.reference.json",
        "validation_json": output_dir / f"{stem}.validation.json",
        "validation_md": output_dir / f"{stem}.validation.md",
        "dxf": output_dir / f"{stem}.annotated.dxf",
        "preview_svg": output_dir / f"{stem}.preview.svg",
        "preview_html": output_dir / f"{stem}.preview.html",
        "manifest": output_dir / f"{stem}.manifest.json",
    }
    paths["spec"].write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["validation_json"].write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dxf_counts = write_reference_dxf(plan, spec, paths["dxf"])
    svg = render_reference_svg(plan, spec, validation)
    paths["preview_svg"].write_text(svg, encoding="utf-8")
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>AICAD &#x7F51;&#x9875;&#x53C2;&#x8003;&#x56FE;&#x91CD;&#x5EFA;&#x5BA1;&#x67E5;</title><style>body{{margin:0;background:#e5e7eb;font-family:"Microsoft YaHei",sans-serif}}main{{max-width:1680px;margin:auto;padding:20px}}section{{background:white;padding:16px;border-radius:12px;box-shadow:0 8px 30px #0f172a22}}svg{{width:100%;height:auto;background:white}}.gate{{margin-bottom:12px;color:#166534;font-weight:700}}</style></head><body><main><section><div class="gate">&#x4E00;&#x6BD4;&#x4E00;&#x51E0;&#x4F55;&#x6821;&#x51C6;&#xFF1A;&#x901A;&#x8FC7; &#x00B7; &#x4E2D;&#x6587;&#x6807;&#x6CE8;&#xFF1A;UTF-8/&#x539F;&#x751F; SVG text &#x00B7; &#x4EC5;&#x5BA1;&#x9605;</div>{svg}</section></main></body></html>'''
    paths["preview_html"].write_text(page, encoding="utf-8")
    md_rows = [
        f"# {stem} - webpage/reference CAD reconstruction validation", "",
        f"- Status: `{validation['status']}`", f"- Plan SHA-256: `{validation['plan_sha256']}`",
        f"- Reference SHA-256: `{validation['reference_sha256']}`", f"- Spec SHA-256: `{validation['spec_sha256']}`",
        f"- Calibration scale: `{validation['calibration']['scale_cad_per_source_unit']:.12g}` CAD unit/source unit",
        f"- Calibration RMS/max: `{validation['calibration']['rms_error_mm']:.6g}` / `{validation['calibration']['max_error_mm']:.6g}` mm",
        "- Pixel dimension authority: `false`", "- Review only: `true`", "",
        "## Gates", "",
    ]
    md_rows.extend(f"- {name}: `{'pass' if passed else 'failed'}`" for name, passed in validation["checks"].items())
    md_rows.extend(["", "## Geometry bindings", "", "| Binding | Target | Result | Errors |", "|---|---|---|---|"])
    for row in validation["geometry_bindings"]:
        md_rows.append(f"| `{row['binding_id']}` | `{row['target_object_id']}` | `{'pass' if row['ok'] else 'failed'}` | `{json.dumps(row['errors'], ensure_ascii=False)}` |")
    md_rows.extend(["", "Native AutoCAD DIMENSION objects and paper-space layout remain a host post-process gate; this DXF contains editable geometry plus deterministic exploded dimension graphics and MTEXT."])
    paths["validation_md"].write_text("\n".join(md_rows) + "\n", encoding="utf-8")
    artifacts = {key: str(path.resolve()) for key, path in paths.items() if key != "manifest"}
    hashes = {key: hashlib.sha256(Path(value).read_bytes()).hexdigest() for key, value in artifacts.items()}
    manifest = {
        "schema_version": "1.0", "status": "pass", "reviewOnly": True, "accepted": False,
        "ruleEnabled": False, "domainGated": True, "geometry_scale": "1:1 model units",
        "dxf_entity_counts": dxf_counts, "artifacts": artifacts, "sha256": hashes,
        "known_limits": validation["limits"],
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True, "status": "pass", "validation": validation, "dxf_entity_counts": dxf_counts,
        "artifacts": {**artifacts, "manifest": str(paths["manifest"].resolve())},
        "review_policy": spec["review_policy"], "limits": validation["limits"],
    }
