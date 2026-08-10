from __future__ import annotations

import math
import re
from typing import Any

from .engine import PlanError, ResolvedArc, ResolvedCircle, ResolvedLine, compile_plan


class UnsupportedRequest(PlanError):
    """Raised when the deterministic offline interpreter cannot understand a request."""


NUMBER = r"([0-9]+(?:\.[0-9]+)?)"


def _drawing(name: str, units: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "drawing": {"name": name, "units": units, "origin": [0, 0], "tolerance": 1e-6},
        "steps": steps,
    }


def rectangle_plan(width: float, height: float, units: str = "mm", name: str = "rectangle") -> dict[str, Any]:
    if width <= 0 or height <= 0:
        raise UnsupportedRequest("Rectangle width and height must be greater than zero")
    return _drawing(name, units, [
        {
            "id": "L001", "type": "line", "purpose": "bottom edge",
            "reasoning": "The first edge anchors the drawing at the origin and defines the width direction.",
            "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": width, "dy": 0},
            "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": width}, {"kind": "start_coincident", "target": "origin"}],
        },
        {
            "id": "L002", "type": "line", "purpose": "right edge",
            "reasoning": "The right edge starts at the previous endpoint and is perpendicular to the bottom edge.",
            "start": {"ref": "L001.end"}, "construction": {"kind": "perpendicular", "to": "L001", "length": height, "turn": "left"},
            "constraints": [{"kind": "vertical"}, {"kind": "length", "value": height}, {"kind": "perpendicular", "target": "L001"}, {"kind": "start_coincident", "target": "L001.end"}],
        },
        {
            "id": "L003", "type": "line", "purpose": "top edge",
            "reasoning": "The top edge is parallel to and opposite the bottom edge, preserving the rectangle width.",
            "start": {"ref": "L002.end"}, "construction": {"kind": "parallel", "to": "L001", "length": width, "direction": "opposite"},
            "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": width}, {"kind": "parallel", "target": "L001"}, {"kind": "start_coincident", "target": "L002.end"}],
        },
        {
            "id": "L004", "type": "line", "purpose": "left edge and closure",
            "reasoning": "The final edge returns to the origin, closing the profile and matching the right-edge height.",
            "start": {"ref": "L003.end"}, "construction": {"kind": "to_point", "target": {"ref": "origin"}},
            "constraints": [{"kind": "vertical"}, {"kind": "length", "value": height}, {"kind": "parallel", "target": "L002"}, {"kind": "start_coincident", "target": "L003.end"}, {"kind": "end_coincident", "target": "origin"}],
        },
    ])


def _units(text: str) -> str:
    lowered = text.lower()
    return "inch" if re.search(r"\b(?:in|inch|inches)\b|英寸", lowered) else "mm"


def offline_plan(request: str) -> dict[str, Any]:
    text = request.strip()
    if not text:
        raise UnsupportedRequest("The drawing request is empty")
    units = _units(text)
    lowered = text.lower().replace("毫米", "mm")

    rectangle = re.search(NUMBER + r"\s*(?:x|×|\*)\s*" + NUMBER, lowered)
    if not rectangle:
        rectangle = re.search(r"(?:宽|width)\s*" + NUMBER + r"\s*(?:mm)?\s*[,，;；\s]*(?:高|height)\s*" + NUMBER, lowered)
    diameter = re.search(r"(?:直径|diameter|[Øø⌀])\s*" + NUMBER, lowered)
    radius = re.search(r"(?:半径|radius|\br)\s*[:：]?\s*" + NUMBER, lowered)

    if rectangle:
        width, height = float(rectangle.group(1)), float(rectangle.group(2))
        plan = rectangle_plan(width, height, units, "rectangular_plate" if (diameter or radius) else "rectangle")
        if diameter or radius:
            hole_radius = float(diameter.group(1)) / 2 if diameter else float(radius.group(1))
            constraint = {"kind": "diameter", "value": hole_radius * 2} if diameter else {"kind": "radius", "value": hole_radius}
            plan["steps"].append({
                "id": "C001", "type": "circle", "purpose": "center hole",
                "reasoning": "The hole center is offset by half the plate width and height from the origin.",
                "center": {"point": [width / 2, height / 2]}, "radius": hole_radius,
                "constraints": [constraint, {"kind": "center_offset", "target": "origin", "dx": width / 2, "dy": height / 2}],
            })
        compile_plan(plan)
        return plan

    arc = re.search(r"(?:圆弧|arc)", lowered)
    if arc and (diameter or radius):
        arc_radius = float(diameter.group(1)) / 2 if diameter else float(radius.group(1))
        angles = re.search(NUMBER + r"\s*(?:度|°)?\s*(?:到|至|~|—|-)\s*" + NUMBER + r"\s*(?:度|°)?", lowered)
        start, end = (float(angles.group(1)), float(angles.group(2))) if angles else (0.0, 90.0)
        plan = _drawing("arc", units, [{
            "id": "A001", "type": "arc", "purpose": "origin-centered arc",
            "reasoning": "The arc center is fixed at the origin; radius and angular limits define it uniquely.",
            "center": {"ref": "origin"}, "radius": arc_radius, "start_angle_deg": start, "end_angle_deg": end,
            "constraints": [{"kind": "radius", "value": arc_radius}, {"kind": "center_coincident", "target": "origin"}, {"kind": "start_angle", "value": start}, {"kind": "end_angle", "value": end}],
        }])
        compile_plan(plan)
        return plan

    if diameter or radius:
        circle_radius = float(diameter.group(1)) / 2 if diameter else float(radius.group(1))
        measure = {"kind": "diameter", "value": circle_radius * 2} if diameter else {"kind": "radius", "value": circle_radius}
        plan = _drawing("circle", units, [{
            "id": "C001", "type": "circle", "purpose": "origin-centered circle",
            "reasoning": "The circle center is the drawing origin and its size is fixed by the requested measure.",
            "center": {"ref": "origin"}, "radius": circle_radius,
            "constraints": [measure, {"kind": "center_coincident", "target": "origin"}],
        }])
        compile_plan(plan)
        return plan

    raise UnsupportedRequest("Offline interpreter supports rectangles, circles, arcs, and rectangular plates with one centered hole")


def _as_number(value: Any, label: str, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PlanError(f"AI draft {label} must be a finite number")
    return float(value)


def draft_to_plan(draft: dict[str, Any]) -> dict[str, Any]:
    """Turn a strict, flat model response into a fully constrained executable plan."""
    if not isinstance(draft, dict) or not isinstance(draft.get("entities"), list) or not draft["entities"]:
        raise PlanError("AI draft must contain entities")
    units = draft.get("units")
    if units not in {"mm", "inch"}:
        raise PlanError("AI draft units must be mm or inch")
    steps: list[dict[str, Any]] = []
    known_refs: list[tuple[float, float, str]] = [(0.0, 0.0, "origin")]
    prior_lines: list[tuple[str, float, float]] = []

    def matching_ref(x: float, y: float) -> str | None:
        for px, py, ref in reversed(known_refs):
            if math.hypot(x - px, y - py) <= 1e-7:
                return ref
        return None

    def anchor_and_relation(x: float, y: float, radial: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        ref = matching_ref(x, y)
        prefix = "center" if radial else "start"
        if ref is not None:
            return {"ref": ref}, {"kind": f"{prefix}_coincident", "target": ref}
        return {"point": [x, y]}, {"kind": f"{prefix}_offset", "target": "origin", "dx": x, "dy": y}

    for index, item in enumerate(draft["entities"]):
        if not isinstance(item, dict):
            raise PlanError(f"AI draft entity {index + 1} must be an object")
        entity_id = f"E{index + 1:03d}"
        kind = item.get("type")
        common = {
            "id": entity_id, "type": kind,
            "purpose": str(item.get("purpose") or f"{kind} entity"),
            "reasoning": str(item.get("reasoning") or "Position and dimensions are resolved from the request."),
        }
        if kind == "line":
            x1, y1 = _as_number(item.get("x1"), "x1"), _as_number(item.get("y1"), "y1")
            x2, y2 = _as_number(item.get("x2"), "x2"), _as_number(item.get("y2"), "y2")
            length = math.hypot(x2 - x1, y2 - y1)
            anchor, relation = anchor_and_relation(x1, y1, False)
            constraints: list[dict[str, Any]] = [{"kind": "length", "value": length}]
            if abs(y2 - y1) <= 1e-8:
                constraints.append({"kind": "horizontal"})
            if abs(x2 - x1) <= 1e-8:
                constraints.append({"kind": "vertical"})
            dx, dy = x2 - x1, y2 - y1
            for prior_id, pdx, pdy in reversed(prior_lines):
                scale = max(math.hypot(dx, dy) * math.hypot(pdx, pdy), 1.0)
                if abs(dx * pdy - dy * pdx) <= 1e-8 * scale:
                    constraints.append({"kind": "parallel", "target": prior_id})
                    break
                if abs(dx * pdx + dy * pdy) <= 1e-8 * scale:
                    constraints.append({"kind": "perpendicular", "target": prior_id})
                    break
            constraints.append(relation)
            steps.append({**common, "start": anchor, "construction": {"kind": "to_point", "target": {"point": [x2, y2]}}, "constraints": constraints})
            known_refs.extend([(x1, y1, f"{entity_id}.start"), (x2, y2, f"{entity_id}.end"), ((x1 + x2) / 2, (y1 + y2) / 2, f"{entity_id}.midpoint")])
            prior_lines.append((entity_id, dx, dy))
        elif kind in {"circle", "arc"}:
            cx, cy = _as_number(item.get("cx"), "cx"), _as_number(item.get("cy"), "cy")
            radius = _as_number(item.get("radius"), "radius")
            anchor, relation = anchor_and_relation(cx, cy, True)
            constraints = [{"kind": "radius", "value": radius}, relation]
            if kind == "circle":
                steps.append({**common, "center": anchor, "radius": radius, "constraints": constraints})
                known_refs.append((cx, cy, f"{entity_id}.center"))
            else:
                start = _as_number(item.get("start_angle_deg"), "start_angle_deg")
                end = _as_number(item.get("end_angle_deg"), "end_angle_deg")
                constraints.extend([{"kind": "start_angle", "value": start}, {"kind": "end_angle", "value": end}])
                steps.append({**common, "center": anchor, "radius": radius, "start_angle_deg": start, "end_angle_deg": end, "constraints": constraints})
                known_refs.extend([
                    (cx, cy, f"{entity_id}.center"),
                    (cx + radius * math.cos(math.radians(start)), cy + radius * math.sin(math.radians(start)), f"{entity_id}.start"),
                    (cx + radius * math.cos(math.radians(end)), cy + radius * math.sin(math.radians(end)), f"{entity_id}.end"),
                ])
        else:
            raise PlanError(f"AI draft entity {index + 1} has unsupported type")
    name = draft.get("name") if isinstance(draft.get("name"), str) else "ai_drawing"
    plan = _drawing(name, units, steps)
    compile_plan(plan)
    return plan
