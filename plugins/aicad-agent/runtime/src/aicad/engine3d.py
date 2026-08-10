from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .engine import PlanError


ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
Point2 = tuple[float, float]
BBox3 = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class CirclePrimitive:
    center: Point2
    radius: float

    @property
    def area(self) -> float:
        return math.pi * self.radius * self.radius


@dataclass(frozen=True)
class ResolvedProfile3D:
    kind: str
    center: Point2
    width: float | None
    height: float | None
    radius: float | None
    count: int | None
    bolt_circle_radius: float | None
    start_angle_deg: float | None
    primitives: tuple[CirclePrimitive, ...]

    @property
    def area(self) -> float:
        if self.kind == "center_rectangle":
            assert self.width is not None and self.height is not None
            return self.width * self.height
        if self.kind == "circle":
            assert self.radius is not None
            return math.pi * self.radius * self.radius
        return sum(item.area for item in self.primitives)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        x, y = self.center
        if self.kind == "center_rectangle":
            assert self.width is not None and self.height is not None
            return x - self.width / 2, y - self.height / 2, x + self.width / 2, y + self.height / 2
        if self.kind == "circle":
            assert self.radius is not None
            return x - self.radius, y - self.radius, x + self.radius, y + self.radius
        return (
            min(circle.center[0] - circle.radius for circle in self.primitives),
            min(circle.center[1] - circle.radius for circle in self.primitives),
            max(circle.center[0] + circle.radius for circle in self.primitives),
            max(circle.center[1] + circle.radius for circle in self.primitives),
        )


@dataclass(frozen=True)
class ResolvedFeature3D:
    id: str
    type: str
    purpose: str
    reasoning: str
    depends_on: tuple[str, ...]
    support_feature: str | None
    profile: ResolvedProfile3D
    depth: float
    end_condition: str
    support_top_z: float
    resulting_top_z: float
    expected_volume_before: float
    expected_volume_after: float
    expected_volume_delta: float
    expected_bbox: BBox3
    expected_body_count: int
    constraints: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SolidOperation3D:
    additive: bool
    profile: ResolvedProfile3D
    z_min: float
    z_max: float


@dataclass(frozen=True)
class CompiledPlan3D:
    name: str
    units: str
    origin: tuple[float, float, float]
    tolerance: float
    features: tuple[ResolvedFeature3D, ...]
    source_hash: str


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PlanError(f"{label} must be finite")
    if abs(result) > 1_000_000:
        raise PlanError(f"{label} exceeds the safe 3D range")
    return result


def _positive(value: Any, label: str) -> float:
    result = _number(value, label)
    if result <= 0:
        raise PlanError(f"{label} must be greater than zero")
    return result


def _point2(value: Any, label: str) -> Point2:
    if not isinstance(value, list) or len(value) != 2:
        raise PlanError(f"{label} must be [x, y]")
    return _number(value[0], f"{label}[0]"), _number(value[1], f"{label}[1]")


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


def _resolve_profile(data: Any, label: str) -> ResolvedProfile3D:
    if not isinstance(data, dict):
        raise PlanError(f"{label} must be an object")
    kind = data.get("kind")
    if kind not in {"center_rectangle", "circle", "circle_pattern"}:
        raise PlanError(f"{label}.kind must be center_rectangle, circle, or circle_pattern")
    center = _point2(data.get("center", [0, 0]), f"{label}.center")
    if kind == "center_rectangle":
        width = _positive(data.get("width"), f"{label}.width")
        height = _positive(data.get("height"), f"{label}.height")
        return ResolvedProfile3D(kind, center, width, height, None, None, None, None, ())
    if kind == "circle":
        radius = _positive(data.get("radius"), f"{label}.radius")
        return ResolvedProfile3D(kind, center, None, None, radius, None, None, None, (CirclePrimitive(center, radius),))
    radius = _positive(data.get("radius"), f"{label}.radius")
    bolt_circle = _positive(data.get("bolt_circle_radius"), f"{label}.bolt_circle_radius")
    count_value = data.get("count")
    if isinstance(count_value, bool) or not isinstance(count_value, int) or not 2 <= count_value <= 100:
        raise PlanError(f"{label}.count must be an integer from 2 through 100")
    start_angle = _number(data.get("start_angle_deg", 0), f"{label}.start_angle_deg")
    primitives = []
    for index in range(count_value):
        angle = math.radians(start_angle + index * 360 / count_value)
        primitives.append(CirclePrimitive((center[0] + bolt_circle * math.cos(angle), center[1] + bolt_circle * math.sin(angle)), radius))
    for index, circle in enumerate(primitives):
        for prior in primitives[:index]:
            if math.hypot(circle.center[0] - prior.center[0], circle.center[1] - prior.center[1]) <= circle.radius + prior.radius:
                raise PlanError(f"{label} produces overlapping pattern holes")
    return ResolvedProfile3D(kind, center, None, None, radius, count_value, bolt_circle, start_angle, tuple(primitives))


def _contains(container: ResolvedProfile3D, child: ResolvedProfile3D, tolerance: float) -> bool:
    cx, cy = container.center
    if container.kind == "center_rectangle":
        assert container.width is not None and container.height is not None
        left, bottom, right, top = cx - container.width / 2, cy - container.height / 2, cx + container.width / 2, cy + container.height / 2
        if child.kind == "center_rectangle":
            c_left, c_bottom, c_right, c_top = child.bounds
            return c_left >= left - tolerance and c_right <= right + tolerance and c_bottom >= bottom - tolerance and c_top <= top + tolerance
        return all(
            circle.center[0] - circle.radius >= left - tolerance
            and circle.center[0] + circle.radius <= right + tolerance
            and circle.center[1] - circle.radius >= bottom - tolerance
            and circle.center[1] + circle.radius <= top + tolerance
            for circle in child.primitives
        )
    if container.kind == "circle":
        assert container.radius is not None
        if child.kind == "center_rectangle":
            left, bottom, right, top = child.bounds
            return all(math.hypot(x - cx, y - cy) <= container.radius + tolerance for x, y in ((left, bottom), (left, top), (right, bottom), (right, top)))
        return all(math.hypot(circle.center[0] - cx, circle.center[1] - cy) + circle.radius <= container.radius + tolerance for circle in child.primitives)
    return False


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for low, high in sorted(intervals):
        if high <= low:
            continue
        if not merged or low > merged[-1][1]:
            merged.append([low, high])
        else:
            merged[-1][1] = max(merged[-1][1], high)
    return [(low, high) for low, high in merged]


def _subtract_intervals(
    occupied: list[tuple[float, float]],
    cutters: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    result = occupied
    for cut_low, cut_high in cutters:
        next_result: list[tuple[float, float]] = []
        for low, high in result:
            if cut_high <= low or cut_low >= high:
                next_result.append((low, high))
                continue
            if cut_low > low:
                next_result.append((low, min(cut_low, high)))
            if cut_high < high:
                next_result.append((max(cut_high, low), high))
        result = next_result
    return result


def _profile_intervals(profile: ResolvedProfile3D, x: float) -> list[tuple[float, float]]:
    if profile.kind == "center_rectangle":
        assert profile.width is not None and profile.height is not None
        half_width = profile.width / 2.0
        if profile.center[0] - half_width <= x <= profile.center[0] + half_width:
            half_height = profile.height / 2.0
            return [(profile.center[1] - half_height, profile.center[1] + half_height)]
        return []
    intervals: list[tuple[float, float]] = []
    for circle in profile.primitives:
        dx = x - circle.center[0]
        if abs(dx) <= circle.radius:
            half_height = math.sqrt(max(0.0, circle.radius * circle.radius - dx * dx))
            intervals.append((circle.center[1] - half_height, circle.center[1] + half_height))
    return _merge_intervals(intervals)


def _circle_intersection_x(first: CirclePrimitive, second: CirclePrimitive) -> tuple[float, ...]:
    dx = second.center[0] - first.center[0]
    dy = second.center[1] - first.center[1]
    distance = math.hypot(dx, dy)
    if distance == 0.0 or distance > first.radius + second.radius or distance < abs(first.radius - second.radius):
        return ()
    along = (first.radius * first.radius - second.radius * second.radius + distance * distance) / (2.0 * distance)
    height_squared = max(0.0, first.radius * first.radius - along * along)
    height = math.sqrt(height_squared)
    base_x = first.center[0] + along * dx / distance
    offset_x = -dy * height / distance
    if height == 0.0:
        return (base_x,)
    return base_x - offset_x, base_x + offset_x


_GAUSS8_NODES_WEIGHTS = (
    (0.1834346424956498, 0.3626837833783620),
    (0.5255324099163290, 0.3137066458778873),
    (0.7966664774136267, 0.2223810344533745),
    (0.9602898564975363, 0.1012285362903763),
)


def _gauss8(function: Any, low: float, high: float) -> float:
    midpoint = (low + high) / 2.0
    half_width = (high - low) / 2.0
    total = 0.0
    for node, weight in _GAUSS8_NODES_WEIGHTS:
        offset = half_width * node
        total += weight * (function(midpoint - offset) + function(midpoint + offset))
    return total * half_width


def _adaptive_gauss8(function: Any, low: float, high: float, tolerance: float, depth: int = 24) -> float:
    whole = _gauss8(function, low, high)

    def integrate(left: float, right: float, estimate: float, allowed: float, remaining: int) -> float:
        midpoint = (left + right) / 2.0
        left_value = _gauss8(function, left, midpoint)
        right_value = _gauss8(function, midpoint, right)
        refined = left_value + right_value
        if remaining <= 0 or abs(refined - estimate) <= allowed:
            return refined
        return integrate(left, midpoint, left_value, allowed / 2.0, remaining - 1) + integrate(
            midpoint, right, right_value, allowed / 2.0, remaining - 1
        )

    return integrate(low, high, whole, tolerance, depth)


def _csg_cross_section_area(operations: tuple[SolidOperation3D, ...]) -> float:
    if not operations:
        return 0.0
    breakpoints: set[float] = set()
    circles: list[CirclePrimitive] = []
    rectangles: list[tuple[float, float, float, float]] = []
    for operation in operations:
        profile = operation.profile
        if profile.kind == "center_rectangle":
            left, bottom, right, top = profile.bounds
            rectangles.append((left, bottom, right, top))
            breakpoints.update((left, right))
        else:
            for circle in profile.primitives:
                circles.append(circle)
                breakpoints.update((circle.center[0] - circle.radius, circle.center[0], circle.center[0] + circle.radius))
    for circle in circles:
        for _, bottom, _, top in rectangles:
            for y in (bottom, top):
                dy = y - circle.center[1]
                if abs(dy) <= circle.radius:
                    dx = math.sqrt(max(0.0, circle.radius * circle.radius - dy * dy))
                    breakpoints.update((circle.center[0] - dx, circle.center[0] + dx))
    for index, circle in enumerate(circles):
        for prior in circles[:index]:
            breakpoints.update(_circle_intersection_x(circle, prior))
    ordered = sorted(breakpoints)
    if len(ordered) < 2:
        return 0.0

    def occupied_length(x: float) -> float:
        occupied: list[tuple[float, float]] = []
        for operation in operations:
            intervals = _profile_intervals(operation.profile, x)
            if operation.additive:
                occupied = _merge_intervals(occupied + intervals)
            else:
                occupied = _subtract_intervals(occupied, intervals)
        return sum(high - low for low, high in occupied)

    area = 0.0
    for low, high in zip(ordered, ordered[1:]):
        if high - low <= 1e-12:
            continue
        area += _adaptive_gauss8(occupied_length, low, high, 1e-12)
    return area


def _solid_volume(operations: list[SolidOperation3D]) -> float:
    z_levels = sorted({value for operation in operations for value in (operation.z_min, operation.z_max)})
    volume = 0.0
    for low, high in zip(z_levels, z_levels[1:]):
        if high - low <= 1e-12:
            continue
        midpoint = (low + high) / 2.0
        active = tuple(operation for operation in operations if operation.z_min < midpoint < operation.z_max)
        volume += _csg_cross_section_area(active) * (high - low)
    return volume


def _constraint(feature_id: str, constraints: tuple[dict[str, Any], ...], kind: str) -> dict[str, Any]:
    matches = [item for item in constraints if isinstance(item, dict) and item.get("kind") == kind]
    if len(matches) != 1:
        raise PlanError(f"{feature_id} must declare exactly one {kind} constraint")
    return matches[0]


def _validate_declared_constraints(feature: ResolvedFeature3D, tolerance: float) -> None:
    constraints = feature.constraints
    depth = _constraint(feature.id, constraints, "depth")
    if not _close(_positive(depth.get("value"), f"{feature.id}.depth constraint"), feature.depth, tolerance):
        raise PlanError(f"{feature.id} depth constraint does not match the operation")
    center = _constraint(feature.id, constraints, "center_offset")
    if center.get("target") != "origin":
        raise PlanError(f"{feature.id} center_offset target must be origin")
    if not _close(_number(center.get("dx"), f"{feature.id}.center_offset.dx"), feature.profile.center[0], tolerance) or not _close(_number(center.get("dy"), f"{feature.id}.center_offset.dy"), feature.profile.center[1], tolerance):
        raise PlanError(f"{feature.id} center_offset does not match the profile")
    if feature.support_feature is not None:
        support = _constraint(feature.id, constraints, "support_coincident")
        if support.get("target") != feature.support_feature:
            raise PlanError(f"{feature.id} support_coincident must target {feature.support_feature}")
    if feature.profile.kind == "center_rectangle":
        for kind, actual in (("width", feature.profile.width), ("height", feature.profile.height)):
            item = _constraint(feature.id, constraints, kind)
            if not _close(_positive(item.get("value"), f"{feature.id}.{kind}"), float(actual), tolerance):
                raise PlanError(f"{feature.id} {kind} constraint does not match the profile")
    else:
        radius = _constraint(feature.id, constraints, "radius")
        if not _close(_positive(radius.get("value"), f"{feature.id}.radius"), float(feature.profile.radius), tolerance):
            raise PlanError(f"{feature.id} radius constraint does not match the profile")
        if feature.profile.kind == "circle_pattern":
            count = _constraint(feature.id, constraints, "pattern_count")
            bolt = _constraint(feature.id, constraints, "bolt_circle_radius")
            if count.get("value") != feature.profile.count:
                raise PlanError(f"{feature.id} pattern_count does not match the profile")
            if not _close(_positive(bolt.get("value"), f"{feature.id}.bolt_circle_radius"), float(feature.profile.bolt_circle_radius), tolerance):
                raise PlanError(f"{feature.id} bolt_circle_radius does not match the profile")


def compile_plan3d(data: dict[str, Any]) -> CompiledPlan3D:
    if data.get("schema_version") != "1.0":
        raise PlanError("3D schema_version must be '1.0'")
    part = data.get("part")
    if not isinstance(part, dict):
        raise PlanError("part object is required")
    name = part.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PlanError("part.name is required")
    units = part.get("units", "mm")
    if units != "mm":
        raise PlanError("3D version 1.0 currently requires mm units")
    origin_raw = part.get("origin")
    if not isinstance(origin_raw, list) or len(origin_raw) != 3:
        raise PlanError("part.origin must be [x,y,z]")
    origin = tuple(_number(value, f"part.origin[{index}]") for index, value in enumerate(origin_raw))
    if origin != (0.0, 0.0, 0.0):
        raise PlanError("part.origin must be exactly [0,0,0]")
    tolerance = _positive(part.get("tolerance", 1e-5), "part.tolerance")
    if tolerance > 0.1:
        raise PlanError("part.tolerance must be <= 0.1 mm")
    steps = data.get("features")
    if not isinstance(steps, list) or not steps:
        raise PlanError("features must contain at least one feature")

    resolved: dict[str, ResolvedFeature3D] = {}
    ordered: list[ResolvedFeature3D] = []
    operations: list[SolidOperation3D] = []
    volume = 0.0
    bbox: BBox3 | None = None
    for index, step in enumerate(steps):
        label = f"features[{index}]"
        if not isinstance(step, dict):
            raise PlanError(f"{label} must be an object")
        feature_id = step.get("id")
        if not isinstance(feature_id, str) or not ID_PATTERN.fullmatch(feature_id):
            raise PlanError(f"{label}.id must be an ASCII alphanumeric/underscore ID")
        if feature_id in resolved:
            raise PlanError(f"Duplicate feature ID '{feature_id}'")
        feature_type = step.get("type")
        if feature_type not in {"base_extrude", "boss_extrude", "cut_extrude"}:
            raise PlanError(f"{feature_id}.type must be base_extrude, boss_extrude, or cut_extrude")
        purpose, reasoning = step.get("purpose"), step.get("reasoning")
        if not isinstance(purpose, str) or not purpose.strip() or not isinstance(reasoning, str) or not reasoning.strip():
            raise PlanError(f"{feature_id} requires non-empty purpose and reasoning")
        dependencies = step.get("depends_on", [])
        if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
            raise PlanError(f"{feature_id}.depends_on must be an array of earlier feature IDs")
        if any(item not in resolved for item in dependencies):
            raise PlanError(f"{feature_id} depends on an unknown or later feature")
        profile = _resolve_profile(step.get("profile"), f"{feature_id}.profile")
        depth = _positive(step.get("depth"), f"{feature_id}.depth")
        end_condition = step.get("end_condition", "blind")
        if end_condition not in {"blind", "through_all"}:
            raise PlanError(f"{feature_id}.end_condition must be blind or through_all")
        constraints_raw = step.get("constraints")
        if not isinstance(constraints_raw, list) or not constraints_raw:
            raise PlanError(f"{feature_id}.constraints are required")
        constraints = tuple(constraints_raw)

        support_feature: str | None = None
        support_top_z = 0.0
        if index == 0:
            if feature_type != "base_extrude" or dependencies:
                raise PlanError("The first 3D feature must be a dependency-free base_extrude")
            if profile.center != (0.0, 0.0):
                raise PlanError("The base profile center must be origin [0,0]")
            if end_condition != "blind":
                raise PlanError("base_extrude must use a blind depth")
        else:
            if feature_type == "base_extrude" or not dependencies:
                raise PlanError(f"{feature_id} must depend on an earlier additive feature")
            support_feature = step.get("support_feature")
            if not isinstance(support_feature, str) or support_feature not in dependencies:
                raise PlanError(f"{feature_id}.support_feature must be one of depends_on")
            support = resolved[support_feature]
            if support.type not in {"base_extrude", "boss_extrude"}:
                raise PlanError(f"{feature_id} support must be an additive feature")
            if not _contains(support.profile, profile, tolerance):
                raise PlanError(f"{feature_id} profile is not contained in support {support_feature}")
            support_top_z = support.resulting_top_z

        if feature_type != "cut_extrude" and end_condition != "blind":
            raise PlanError(f"{feature_id} additive extrusions must use blind depth")
        if feature_type == "cut_extrude" and end_condition == "blind" and depth > support_top_z + tolerance:
            raise PlanError(f"{feature_id} blind cut exceeds the support material depth")
        if feature_type in {"base_extrude", "boss_extrude"}:
            operation = SolidOperation3D(True, profile, support_top_z, support_top_z + depth)
        else:
            cut_bottom_z = 0.0 if end_condition == "through_all" else support_top_z - depth
            operation = SolidOperation3D(False, profile, cut_bottom_z, support_top_z)
        before = volume
        operations.append(operation)
        after = _solid_volume(operations)
        delta = after - before
        if after <= tolerance:
            raise PlanError(f"{feature_id} would remove the complete solid")

        if feature_type in {"base_extrude", "boss_extrude"}:
            min_x, min_y, max_x, max_y = profile.bounds
            new_box = (min_x, min_y, support_top_z, max_x, max_y, support_top_z + depth)
            if bbox is None:
                bbox = new_box
            else:
                bbox = (
                    min(bbox[0], new_box[0]), min(bbox[1], new_box[1]), min(bbox[2], new_box[2]),
                    max(bbox[3], new_box[3]), max(bbox[4], new_box[4]), max(bbox[5], new_box[5]),
                )
        assert bbox is not None
        resulting_top = support_top_z + depth if feature_type in {"base_extrude", "boss_extrude"} else support_top_z
        feature = ResolvedFeature3D(
            feature_id, feature_type, purpose.strip(), reasoning.strip(), tuple(dependencies), support_feature,
            profile, depth, end_condition, support_top_z, resulting_top, before, after, delta, bbox, 1, constraints,
        )
        _validate_declared_constraints(feature, tolerance)
        resolved[feature_id] = feature
        ordered.append(feature)
        volume = after

    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CompiledPlan3D(name.strip(), units, origin, tolerance, tuple(ordered), hashlib.sha256(canonical).hexdigest())
