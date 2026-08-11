from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias


class PlanError(ValueError):
    """Raised when a drawing plan is ambiguous or geometrically invalid."""


Point = tuple[float, float]
ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
LAYER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
MAX_COORDINATE = 1_000_000_000.0


@dataclass(frozen=True)
class ResolvedLine:
    id: str
    purpose: str
    reasoning: str
    start: Point
    end: Point
    constraints: tuple[dict[str, Any], ...]
    type: str = "line"
    layer: str = "AICAD_GEOMETRY"
    roles: tuple[str, ...] = ()
    editable: bool = True
    depends_on: tuple[str, ...] = ()

    @property
    def vector(self) -> Point:
        return self.end[0] - self.start[0], self.end[1] - self.start[1]

    @property
    def length(self) -> float:
        dx, dy = self.vector
        return math.hypot(dx, dy)

    @property
    def anchor(self) -> Point:
        return self.start


@dataclass(frozen=True)
class ResolvedCircle:
    id: str
    purpose: str
    reasoning: str
    center: Point
    radius: float
    constraints: tuple[dict[str, Any], ...]
    type: str = "circle"
    layer: str = "AICAD_GEOMETRY"
    roles: tuple[str, ...] = ()
    editable: bool = True
    depends_on: tuple[str, ...] = ()

    @property
    def anchor(self) -> Point:
        return self.center


@dataclass(frozen=True)
class ResolvedArc:
    id: str
    purpose: str
    reasoning: str
    center: Point
    radius: float
    start_angle_deg: float
    end_angle_deg: float
    constraints: tuple[dict[str, Any], ...]
    type: str = "arc"
    layer: str = "AICAD_GEOMETRY"
    roles: tuple[str, ...] = ()
    editable: bool = True
    depends_on: tuple[str, ...] = ()

    @property
    def start(self) -> Point:
        angle = math.radians(self.start_angle_deg)
        return self.center[0] + self.radius * math.cos(angle), self.center[1] + self.radius * math.sin(angle)

    @property
    def end(self) -> Point:
        angle = math.radians(self.end_angle_deg)
        return self.center[0] + self.radius * math.cos(angle), self.center[1] + self.radius * math.sin(angle)

    @property
    def anchor(self) -> Point:
        return self.center


@dataclass(frozen=True)
class ResolvedText:
    id: str
    purpose: str
    reasoning: str
    insert: Point
    value: str
    height: float
    rotation_deg: float
    constraints: tuple[dict[str, Any], ...]
    type: str = "text"
    layer: str = "AICAD_TEXT"
    roles: tuple[str, ...] = ()
    editable: bool = True
    depends_on: tuple[str, ...] = ()

    @property
    def anchor(self) -> Point:
        return self.insert


ResolvedEntity: TypeAlias = ResolvedLine | ResolvedCircle | ResolvedArc | ResolvedText


@dataclass(frozen=True)
class CompiledPlan:
    name: str
    units: str
    origin: Point
    tolerance: float
    entities: tuple[ResolvedEntity, ...]
    source_hash: str
    schema_version: str
    domain: str = "general"

    @property
    def lines(self) -> tuple[ResolvedLine, ...]:
        return tuple(entity for entity in self.entities if isinstance(entity, ResolvedLine))


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PlanError(f"{label} must be finite")
    if abs(result) > MAX_COORDINATE:
        raise PlanError(f"{label} exceeds the safe coordinate range")
    return result


def _positive(value: Any, label: str) -> float:
    result = _number(value, label)
    if result <= 0:
        raise PlanError(f"{label} must be greater than zero")
    return result


def _point(value: Any, label: str) -> Point:
    if not isinstance(value, list) or len(value) != 2:
        raise PlanError(f"{label} must be [x, y]")
    return _number(value[0], f"{label}[0]"), _number(value[1], f"{label}[1]")


def _close(a: Point, b: Point, tolerance: float) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tolerance


def _resolve_ref(ref: str, entities: dict[str, ResolvedEntity], origin: Point) -> Point:
    if ref == "origin":
        return origin
    if "." not in ref:
        raise PlanError(f"Invalid point reference '{ref}'; expected ENTITY_ID.point")
    entity_id, point_name = ref.rsplit(".", 1)
    if entity_id not in entities:
        raise PlanError(f"Reference '{ref}' points to an entity that has not been drawn")
    entity = entities[entity_id]
    if isinstance(entity, ResolvedLine):
        points = {
            "start": entity.start,
            "end": entity.end,
            "midpoint": ((entity.start[0] + entity.end[0]) / 2, (entity.start[1] + entity.end[1]) / 2),
        }
    elif isinstance(entity, ResolvedCircle):
        points = {"center": entity.center}
    elif isinstance(entity, ResolvedArc):
        points = {"center": entity.center, "start": entity.start, "end": entity.end}
    else:
        points = {"insert": entity.insert}
    if point_name not in points:
        raise PlanError(f"Reference '{ref}' is not valid for a {entity.type}")
    return points[point_name]


def _resolve_anchor(value: Any, entities: dict[str, ResolvedEntity], origin: Point, label: str) -> Point:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must contain either point or ref")
    keys = set(value)
    if keys == {"point"}:
        return _point(value["point"], f"{label}.point")
    if keys == {"ref"} and isinstance(value["ref"], str):
        return _resolve_ref(value["ref"], entities, origin)
    raise PlanError(f"{label} must contain exactly one of point/ref")


def _unit_vector(line: ResolvedLine, label: str) -> Point:
    if line.length == 0:
        raise PlanError(f"{label} references a zero-length line")
    dx, dy = line.vector
    return dx / line.length, dy / line.length


def _line_by_id(entities: dict[str, ResolvedEntity], entity_id: Any, label: str) -> ResolvedLine:
    entity = entities.get(entity_id) if isinstance(entity_id, str) else None
    if not isinstance(entity, ResolvedLine):
        raise PlanError(f"{label} must reference an earlier line")
    return entity


def _resolve_end(construction: Any, start: Point, entities: dict[str, ResolvedEntity], origin: Point, label: str) -> Point:
    if not isinstance(construction, dict) or not isinstance(construction.get("kind"), str):
        raise PlanError(f"{label} must contain a construction kind")
    kind = construction["kind"]
    if kind == "to_point":
        if set(construction) != {"kind", "target"}:
            raise PlanError(f"{label} to_point requires only kind and target")
        return _resolve_anchor(construction["target"], entities, origin, f"{label}.target")
    if kind == "vector":
        dx = _number(construction.get("dx"), f"{label}.dx")
        dy = _number(construction.get("dy"), f"{label}.dy")
        return start[0] + dx, start[1] + dy
    if kind == "polar":
        length = _positive(construction.get("length"), f"{label}.length")
        angle = math.radians(_number(construction.get("angle_deg"), f"{label}.angle_deg"))
        return start[0] + length * math.cos(angle), start[1] + length * math.sin(angle)
    if kind in {"parallel", "perpendicular"}:
        target = _line_by_id(entities, construction.get("to"), f"{label}.to")
        length = _positive(construction.get("length"), f"{label}.length")
        ux, uy = _unit_vector(target, label)
        if kind == "parallel":
            direction = construction.get("direction", "same")
            if direction not in {"same", "opposite"}:
                raise PlanError(f"{label}.direction must be same or opposite")
            sign = 1.0 if direction == "same" else -1.0
            vx, vy = sign * ux, sign * uy
        else:
            turn = construction.get("turn", "left")
            if turn == "left":
                vx, vy = -uy, ux
            elif turn == "right":
                vx, vy = uy, -ux
            else:
                raise PlanError(f"{label}.turn must be left or right")
        return start[0] + length * vx, start[1] + length * vy
    raise PlanError(f"Unsupported construction kind '{kind}'")


def _parallel(a: ResolvedLine, b: ResolvedLine, tolerance: float) -> bool:
    ax, ay = a.vector
    bx, by = b.vector
    return abs(ax * by - ay * bx) <= tolerance * max(a.length * b.length, 1.0)


def _perpendicular(a: ResolvedLine, b: ResolvedLine, tolerance: float) -> bool:
    ax, ay = a.vector
    bx, by = b.vector
    return abs(ax * bx + ay * by) <= tolerance * max(a.length * b.length, 1.0)


def _collinear(a: ResolvedLine, b: ResolvedLine, tolerance: float) -> bool:
    if not _parallel(a, b, tolerance):
        return False
    bx, by = b.vector
    offset_x, offset_y = a.start[0] - b.start[0], a.start[1] - b.start[1]
    return abs(bx * offset_y - by * offset_x) <= tolerance * max(b.length, 1.0)


def _validate_offset(anchor: Point, constraint: dict[str, Any], entities: dict[str, ResolvedEntity], origin: Point, tolerance: float, label: str) -> None:
    target = constraint.get("target")
    if not isinstance(target, str):
        raise PlanError(f"{label} requires target")
    base = _resolve_ref(target, entities, origin)
    expected = (base[0] + _number(constraint.get("dx"), f"{label}.dx"), base[1] + _number(constraint.get("dy"), f"{label}.dy"))
    if not _close(anchor, expected, tolerance):
        raise PlanError(f"{label} does not match its mathematical offset")


def _validate_line_constraints(line: ResolvedLine, entities: dict[str, ResolvedEntity], origin: Point, tolerance: float) -> bool:
    has_anchor_relation = False
    for index, constraint in enumerate(line.constraints):
        if not isinstance(constraint, dict) or not isinstance(constraint.get("kind"), str):
            raise PlanError(f"{line.id}.constraints[{index}] must contain a kind")
        kind = constraint["kind"]
        if kind == "horizontal":
            if abs(line.end[1] - line.start[1]) > tolerance:
                raise PlanError(f"{line.id} violates horizontal constraint")
        elif kind == "vertical":
            if abs(line.end[0] - line.start[0]) > tolerance:
                raise PlanError(f"{line.id} violates vertical constraint")
        elif kind == "length":
            expected = _positive(constraint.get("value"), f"{line.id}.length.value")
            if abs(line.length - expected) > tolerance:
                raise PlanError(f"{line.id} length is {line.length:g}, expected {expected:g}")
        elif kind in {"parallel", "perpendicular", "collinear"}:
            target = _line_by_id(entities, constraint.get("target"), f"{line.id}.{kind}.target")
            valid = {"parallel": _parallel, "perpendicular": _perpendicular, "collinear": _collinear}[kind](line, target, tolerance)
            if not valid:
                raise PlanError(f"{line.id} violates {kind} constraint to {target.id}")
        elif kind in {"start_coincident", "end_coincident"}:
            target = constraint.get("target")
            if not isinstance(target, str):
                raise PlanError(f"{line.id} {kind} requires target")
            expected = _resolve_ref(target, entities, origin)
            actual = line.start if kind == "start_coincident" else line.end
            if not _close(actual, expected, tolerance):
                raise PlanError(f"{line.id} violates {kind} constraint to {target}")
            if kind == "start_coincident":
                has_anchor_relation = True
        elif kind == "start_offset":
            _validate_offset(line.start, constraint, entities, origin, tolerance, f"{line.id}.start_offset")
            has_anchor_relation = True
        else:
            raise PlanError(f"Unsupported constraint kind '{kind}' on {line.id}")
    return has_anchor_relation


def _validate_radial_constraints(entity: ResolvedCircle | ResolvedArc, entities: dict[str, ResolvedEntity], origin: Point, tolerance: float) -> bool:
    has_anchor_relation = False
    for index, constraint in enumerate(entity.constraints):
        if not isinstance(constraint, dict) or not isinstance(constraint.get("kind"), str):
            raise PlanError(f"{entity.id}.constraints[{index}] must contain a kind")
        kind = constraint["kind"]
        if kind in {"radius", "diameter"}:
            expected = _positive(constraint.get("value"), f"{entity.id}.{kind}.value")
            actual = entity.radius if kind == "radius" else entity.radius * 2
            if abs(actual - expected) > tolerance:
                raise PlanError(f"{entity.id} violates {kind} constraint")
        elif kind == "center_coincident":
            target = constraint.get("target")
            if not isinstance(target, str) or not _close(entity.center, _resolve_ref(target, entities, origin), tolerance):
                raise PlanError(f"{entity.id} violates center_coincident constraint")
            has_anchor_relation = True
        elif kind == "center_offset":
            _validate_offset(entity.center, constraint, entities, origin, tolerance, f"{entity.id}.center_offset")
            has_anchor_relation = True
        elif isinstance(entity, ResolvedArc) and kind in {"start_angle", "end_angle"}:
            expected = _number(constraint.get("value"), f"{entity.id}.{kind}.value")
            actual = entity.start_angle_deg if kind == "start_angle" else entity.end_angle_deg
            if abs(((actual - expected + 180) % 360) - 180) > tolerance:
                raise PlanError(f"{entity.id} violates {kind} constraint")
        else:
            raise PlanError(f"Unsupported constraint kind '{kind}' on {entity.id}")
    return has_anchor_relation


def _validate_text_constraints(entity: ResolvedText, entities: dict[str, ResolvedEntity], origin: Point, tolerance: float) -> bool:
    has_anchor_relation = False
    for index, constraint in enumerate(entity.constraints):
        if not isinstance(constraint, dict) or not isinstance(constraint.get("kind"), str):
            raise PlanError(f"{entity.id}.constraints[{index}] must contain a kind")
        kind = constraint["kind"]
        if kind == "position_coincident":
            target = constraint.get("target")
            if not isinstance(target, str) or not _close(entity.insert, _resolve_ref(target, entities, origin), tolerance):
                raise PlanError(f"{entity.id} violates position_coincident constraint")
            has_anchor_relation = True
        elif kind == "position_offset":
            _validate_offset(entity.insert, constraint, entities, origin, tolerance, f"{entity.id}.position_offset")
            has_anchor_relation = True
        elif kind == "text_height":
            expected = _positive(constraint.get("value"), f"{entity.id}.text_height.value")
            if abs(entity.height - expected) > tolerance:
                raise PlanError(f"{entity.id} violates text_height constraint")
        elif kind == "rotation":
            expected = _number(constraint.get("value"), f"{entity.id}.rotation.value")
            if abs(((entity.rotation_deg - expected + 180) % 360) - 180) > tolerance:
                raise PlanError(f"{entity.id} violates rotation constraint")
        else:
            raise PlanError(f"Unsupported constraint kind '{kind}' on {entity.id}")
    return has_anchor_relation


def _entity_points(entity: ResolvedEntity) -> tuple[Point, ...]:
    if isinstance(entity, ResolvedLine):
        return (entity.start, entity.end, ((entity.start[0] + entity.end[0]) / 2, (entity.start[1] + entity.end[1]) / 2))
    if isinstance(entity, ResolvedCircle):
        return (entity.center,)
    if isinstance(entity, ResolvedArc):
        return (entity.center, entity.start, entity.end)
    return (entity.insert,)


def _is_duplicate(candidate: ResolvedEntity, prior: ResolvedEntity, tolerance: float) -> bool:
    if isinstance(candidate, ResolvedLine) and isinstance(prior, ResolvedLine):
        return (_close(candidate.start, prior.start, tolerance) and _close(candidate.end, prior.end, tolerance)) or (_close(candidate.start, prior.end, tolerance) and _close(candidate.end, prior.start, tolerance))
    if isinstance(candidate, ResolvedCircle) and isinstance(prior, ResolvedCircle):
        return _close(candidate.center, prior.center, tolerance) and abs(candidate.radius - prior.radius) <= tolerance
    if isinstance(candidate, ResolvedArc) and isinstance(prior, ResolvedArc):
        return (_close(candidate.center, prior.center, tolerance) and abs(candidate.radius - prior.radius) <= tolerance and abs(candidate.start_angle_deg - prior.start_angle_deg) <= tolerance and abs(candidate.end_angle_deg - prior.end_angle_deg) <= tolerance)
    if isinstance(candidate, ResolvedText) and isinstance(prior, ResolvedText):
        return (_close(candidate.insert, prior.insert, tolerance) and candidate.value == prior.value and
                abs(candidate.height - prior.height) <= tolerance and abs(candidate.rotation_deg - prior.rotation_deg) <= tolerance)
    return False


def _referenced_entity_ids(value: Any) -> tuple[str, ...]:
    result: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            candidate = item.split(".", 1)[0]
            if candidate != "origin" and ID_PATTERN.fullmatch(candidate) and candidate not in result:
                result.append(candidate)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return tuple(result)


def _inferred_dependencies(step: dict[str, Any], known: set[str]) -> tuple[str, ...]:
    result: list[str] = []
    for field in ("start", "center", "insert", "construction", "constraints"):
        for candidate in _referenced_entity_ids(step.get(field)):
            if candidate in known and candidate not in result:
                result.append(candidate)
    return tuple(result)

def _common_step(step: dict[str, Any], label: str, resolved: dict[str, ResolvedEntity]) -> tuple[str, str, str, tuple[dict[str, Any], ...]]:
    entity_id = step.get("id")
    if not isinstance(entity_id, str) or not ID_PATTERN.fullmatch(entity_id):
        raise PlanError(f"{label}.id must be a non-empty ASCII alphanumeric/underscore ID")
    if entity_id in resolved:
        raise PlanError(f"Duplicate entity ID '{entity_id}'")
    purpose, reasoning, constraints = step.get("purpose"), step.get("reasoning"), step.get("constraints")
    if not isinstance(purpose, str) or not purpose.strip():
        raise PlanError(f"{entity_id}.purpose is required")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise PlanError(f"{entity_id}.reasoning is required")
    if not isinstance(constraints, list) or not constraints:
        raise PlanError(f"{entity_id}.constraints must explain at least one mathematical relation")
    return entity_id, purpose.strip(), reasoning.strip(), tuple(constraints)


def compile_plan(data: dict[str, Any]) -> CompiledPlan:
    schema_version = data.get("schema_version")
    if schema_version not in {"1.0", "2.0"}:
        raise PlanError("schema_version must be '1.0' or '2.0'")
    drawing = data.get("drawing")
    if not isinstance(drawing, dict):
        raise PlanError("drawing object is required")
    name = drawing.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PlanError("drawing.name is required")
    domain = drawing.get("domain", "general")
    if not isinstance(domain, str) or not DOMAIN_PATTERN.fullmatch(domain):
        raise PlanError("drawing.domain must be a lower-case ASCII identifier")
    units = drawing.get("units", "mm")
    if units not in {"mm", "inch"}:
        raise PlanError("drawing.units must be mm or inch")
    origin = _point(drawing.get("origin"), "drawing.origin")
    if origin != (0.0, 0.0):
        raise PlanError("drawing.origin must be exactly [0, 0]")
    tolerance = _number(drawing.get("tolerance", 1e-6), "drawing.tolerance")
    if tolerance <= 0 or tolerance > 0.1:
        raise PlanError("drawing.tolerance must be > 0 and <= 0.1")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlanError("steps must contain at least one entity")

    resolved: dict[str, ResolvedEntity] = {}
    ordered: list[ResolvedEntity] = []
    known_points: list[Point] = [origin]
    for index, raw_step in enumerate(steps):
        label = f"steps[{index}]"
        if not isinstance(raw_step, dict):
            raise PlanError(f"{label} must be an object")
        step_type = raw_step.get("type")
        if schema_version == "1.0" and step_type != "line":
            raise PlanError(f"{label}.type must be line in schema 1.0")
        if step_type not in {"line", "circle", "arc", "text"}:
            raise PlanError(f"{label}.type must be line, circle, arc, or text")
        entity_id, purpose, reasoning, constraints = _common_step(raw_step, label, resolved)
        layer = raw_step.get("layer", "AICAD_GEOMETRY")
        if not isinstance(layer, str) or not LAYER_PATTERN.fullmatch(layer):
            raise PlanError(f"{entity_id}.layer must be an ASCII CAD layer name")
        role = raw_step.get("role")
        roles_raw = raw_step.get("roles")
        if roles_raw is None:
            roles_raw = [role] if isinstance(role, str) and role else []
        if not isinstance(roles_raw, list) or not all(isinstance(value, str) and value for value in roles_raw):
            raise PlanError(f"{entity_id}.roles must be an array of non-empty strings")
        roles = tuple(dict.fromkeys(roles_raw))
        editable = raw_step.get("editable", True)
        if not isinstance(editable, bool):
            raise PlanError(f"{entity_id}.editable must be boolean")
        depends_raw = raw_step.get("depends_on", [])
        if not isinstance(depends_raw, list) or not all(isinstance(value, str) and ID_PATTERN.fullmatch(value) for value in depends_raw):
            raise PlanError(f"{entity_id}.depends_on must be an array of earlier entity IDs")
        depends_on = tuple(dict.fromkeys(depends_raw))
        unknown_dependencies = [value for value in depends_on if value not in resolved]
        if unknown_dependencies:
            raise PlanError(f"{entity_id}.depends_on may only reference earlier entities: {unknown_dependencies}")
        depends_on = tuple(dict.fromkeys([*depends_on, *_inferred_dependencies(raw_step, set(resolved))]))

        if step_type == "line":
            start = _resolve_anchor(raw_step.get("start"), resolved, origin, f"{entity_id}.start")
            end = _resolve_end(raw_step.get("construction"), start, resolved, origin, f"{entity_id}.construction")
            entity: ResolvedEntity = ResolvedLine(entity_id, purpose, reasoning, start, end, constraints, layer=layer, roles=roles, editable=editable, depends_on=depends_on)
            if entity.length <= tolerance:
                raise PlanError(f"{entity_id} is zero-length within tolerance")
            has_relation = _validate_line_constraints(entity, resolved, origin, tolerance)
        elif step_type == "circle":
            center = _resolve_anchor(raw_step.get("center"), resolved, origin, f"{entity_id}.center")
            entity = ResolvedCircle(entity_id, purpose, reasoning, center, _positive(raw_step.get("radius"), f"{entity_id}.radius"), constraints, layer=layer, roles=roles, editable=editable, depends_on=depends_on)
            has_relation = _validate_radial_constraints(entity, resolved, origin, tolerance)
        elif step_type == "arc":
            center = _resolve_anchor(raw_step.get("center"), resolved, origin, f"{entity_id}.center")
            radius = _positive(raw_step.get("radius"), f"{entity_id}.radius")
            start_angle = _number(raw_step.get("start_angle_deg"), f"{entity_id}.start_angle_deg")
            end_angle = _number(raw_step.get("end_angle_deg"), f"{entity_id}.end_angle_deg")
            if abs(((end_angle - start_angle) % 360)) <= tolerance:
                raise PlanError(f"{entity_id} arc sweep must be between 0 and 360 degrees")
            entity = ResolvedArc(entity_id, purpose, reasoning, center, radius, start_angle, end_angle, constraints, layer=layer, roles=roles, editable=editable, depends_on=depends_on)
            has_relation = _validate_radial_constraints(entity, resolved, origin, tolerance)
        else:
            insert = _resolve_anchor(raw_step.get("insert"), resolved, origin, f"{entity_id}.insert")
            value = raw_step.get("value")
            if not isinstance(value, str) or not value:
                raise PlanError(f"{entity_id}.value must be non-empty text")
            if any(ord(char) < 32 or ord(char) > 0xFFFF for char in value) or "|" in value or "\\" in value:
                raise PlanError(f"{entity_id}.value contains unsupported control, separator, escape, or non-BMP characters")
            height = _positive(raw_step.get("height"), f"{entity_id}.height")
            rotation = _number(raw_step.get("rotation_deg", 0), f"{entity_id}.rotation_deg")
            entity = ResolvedText(entity_id, purpose, reasoning, insert, value, height, rotation, constraints, layer=layer, roles=roles, editable=editable, depends_on=depends_on)
            has_relation = _validate_text_constraints(entity, resolved, origin, tolerance)

        if index == 0 and not _close(entity.anchor, origin, tolerance):
            raise PlanError("The first entity anchor must be origin [0, 0]")
        if index > 0 and not any(_close(entity.anchor, point, tolerance) for point in known_points) and not has_relation:
            raise PlanError(f"{entity_id} anchor is disconnected and lacks an origin/geometry offset constraint")
        for prior in ordered:
            if _is_duplicate(entity, prior, tolerance):
                raise PlanError(f"{entity_id} duplicates {prior.id}")
        resolved[entity_id] = entity
        ordered.append(entity)
        known_points.extend(_entity_points(entity))

    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CompiledPlan(name.strip(), units, origin, tolerance, tuple(ordered), hashlib.sha256(canonical).hexdigest(), schema_version, domain)


def load_and_compile(path: Path) -> CompiledPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"Cannot read UTF-8 plan {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("Plan root must be a JSON object")
    return compile_plan(data)
