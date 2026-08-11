from __future__ import annotations

import math
import re
from typing import Any

from .engine3d import ResolvedFeature3D


MODEL_COORDINATE_SYSTEM_ID = "MODEL_XYZ"


def coordinate_system(origin: tuple[float, ...], space: str) -> dict[str, Any]:
    values = [float(value) for value in origin]
    if space == "2d":
        values = [values[0], values[1], 0.0]
    return {
        "id": MODEL_COORDINATE_SYSTEM_ID,
        "type": "cartesian",
        "handedness": "right",
        "origin": values,
        "axes": {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]},
        "unit": "mm",
    }


def _point(values: tuple[float, float, float] | list[float | None]) -> list[float | None]:
    return [None if value is None else float(value) for value in values]


def _base(kind: str, authority: str = "model_semantic") -> dict[str, Any]:
    return {
        "kind": kind,
        "authority": authority,
        "coordinate_system_id": MODEL_COORDINATE_SYSTEM_ID,
        "unit": "mm",
    }


def _line(
    start: tuple[float, float, float] | list[float | None],
    end: tuple[float, float, float] | list[float | None],
    *,
    authority: str = "model_semantic",
    controller_path: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    a, b = _point(start), _point(end)
    known = [(float(x), float(y)) for x, y in zip(a, b) if x is not None and y is not None]
    length = math.sqrt(sum((y - x) ** 2 for x, y in known))
    value = {**_base("line", authority), "start": a, "end": b, "length_mm": length}
    if controller_path:
        value.update({"controller_path": controller_path, "controller_value": length})
    if note:
        value["note"] = note
    return value


def _point_measurement(
    coordinates: tuple[float, float, float] | list[float | None],
    *,
    authority: str = "model_semantic",
    controller_path: str | None = None,
    controller_value: list[float] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    value = {**_base("point", authority), "coordinates": _point(coordinates)}
    if controller_path:
        value["controller_path"] = controller_path
        value["controller_value"] = controller_value if controller_value is not None else list(coordinates[:2])
    if note:
        value["note"] = note
    return value


def _circle(
    center: tuple[float, float, float] | list[float | None],
    radius: float,
    *,
    authority: str = "model_semantic",
    controller_path: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    value = {
        **_base("circle", authority),
        "center": _point(center),
        "radius_mm": float(radius),
        "diameter_mm": float(radius) * 2.0,
    }
    if controller_path:
        value.update({"controller_path": controller_path, "controller_value": float(radius)})
    if note:
        value["note"] = note
    return value


def _face(area: float, center: tuple[float, float, float], note: str) -> dict[str, Any]:
    return {**_base("face"), "center": _point(center), "area_mm2": float(area), "note": note}


def _feature_depth_bounds(feature: ResolvedFeature3D) -> tuple[float, float]:
    if feature.type == "cut_extrude":
        low = 0.0 if feature.end_condition == "through_all" else feature.support_top_z - feature.depth
        return low, feature.support_top_z
    return feature.support_top_z, feature.resulting_top_z


def selector_measurement(feature: ResolvedFeature3D, source_subobject: str) -> dict[str, Any]:
    profile = feature.profile
    left, bottom, right, top = profile.bounds
    low, high = _feature_depth_bounds(feature)
    sketch_z = high if feature.type == "cut_extrude" else low
    opposite_z = low if math.isclose(sketch_z, high, abs_tol=1e-9) else high
    cx, cy = profile.center
    corners = ((left, bottom), (right, bottom), (right, top), (left, top))

    if source_subobject == "profile.center":
        return _point_measurement(
            (cx, cy, sketch_z), controller_path="profile.center", controller_value=[float(cx), float(cy)]
        )
    if source_subobject in {"feature.axis.center.xz", "feature.axis.center.yz"}:
        return _line((cx, cy, low), (cx, cy, high), controller_path="depth", note="特征中心轴")
    if source_subobject == "profile.pattern.pitch_circle":
        assert profile.bolt_circle_radius is not None
        return _circle(
            (cx, cy, sketch_z), profile.bolt_circle_radius,
            controller_path="profile.bolt_circle_radius", note="阵列分布圆",
        )

    edge_match = re.fullmatch(r"profile\.edge\.(\d+)", source_subobject)
    opposite_match = re.fullmatch(r"feature\.edge\.opposite\.(\d+)", source_subobject)
    vertical_match = re.fullmatch(r"feature\.edge\.vertical\.(\d+)", source_subobject)
    if edge_match or opposite_match:
        index = int((edge_match or opposite_match).group(1))
        start_xy, end_xy = corners[index - 1], corners[index % 4]
        z = sketch_z if edge_match else opposite_z
        controller = "profile.width" if index in {1, 3} else "profile.height"
        return _line((*start_xy, z), (*end_xy, z), controller_path=controller)
    if vertical_match:
        index = int(vertical_match.group(1))
        x, y = corners[index - 1]
        return _line((x, y, low), (x, y, high), controller_path="depth")

    circle_match = re.fullmatch(r"profile\.circle\.(\d+)", source_subobject)
    opposite_circle_match = re.fullmatch(r"feature\.circle\.opposite\.(\d+)", source_subobject)
    if circle_match or opposite_circle_match:
        index = int((circle_match or opposite_circle_match).group(1))
        primitive = profile.primitives[index - 1]
        z = sketch_z if circle_match else opposite_z
        return _circle((*primitive.center, z), primitive.radius, controller_path="profile.radius")

    side_match = re.fullmatch(r"feature\.face\.side\.(\d+)", source_subobject)
    if side_match:
        index = int(side_match.group(1))
        side_length = (right - left) if index in {1, 3} else (top - bottom)
        return _face(side_length * (high - low), (cx, cy, (low + high) / 2.0), "矩形特征侧面")
    if source_subobject in {"profile.face", "feature.face.opposite"}:
        z = sketch_z if source_subobject == "profile.face" else opposite_z
        return _face((right - left) * (top - bottom), (cx, cy, z), "矩形轮廓面")

    cylinder_match = re.fullmatch(r"feature\.face\.cylindrical\.(\d+)", source_subobject)
    circle_face_match = re.fullmatch(r"profile\.face\.(\d+)", source_subobject)
    opposite_face_match = re.fullmatch(r"feature\.face\.opposite\.(\d+)", source_subobject)
    if cylinder_match:
        primitive = profile.primitives[int(cylinder_match.group(1)) - 1]
        return _face(
            2.0 * math.pi * primitive.radius * (high - low),
            (*primitive.center, (low + high) / 2.0),
            "圆柱侧面展开面积",
        )
    if circle_face_match or opposite_face_match:
        match = circle_face_match or opposite_face_match
        primitive = profile.primitives[int(match.group(1)) - 1]
        z = sketch_z if circle_face_match else opposite_z
        return _face(math.pi * primitive.radius ** 2, (*primitive.center, z), "圆形端面")

    raise ValueError(f"unsupported semantic subobject measurement: {feature.id}|{source_subobject}")


def _lift(point: list[float], axes: list[str], plane: dict[str, Any] | None, space: str) -> list[float | None]:
    if space == "2d":
        return [float(point[0]), float(point[1]), 0.0]
    result: list[float | None] = [None, None, None]
    for index, axis in enumerate(axes[:2]):
        if axis in "xyz":
            result["xyz".index(axis)] = float(point[index])
    if plane and plane.get("axis") in "xyz":
        result["xyz".index(plane["axis"])] = float(plane["value"])
    return result


def _bbox_edge(selector_object: dict[str, Any], index: int) -> dict[str, Any]:
    left, bottom, right, top = map(float, selector_object["profile"]["bounds"])
    low, high = float(selector_object["z_min"]), float(selector_object["z_max"])
    vertices = (
        (left, bottom, low), (right, bottom, low), (right, top, low), (left, top, low),
        (left, bottom, high), (right, bottom, high), (right, top, high), (left, top, high),
    )
    edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
    first, second = edges[index - 1]
    controller = "profile.width" if index in {1, 3, 5, 7} else "profile.height" if index in {2, 4, 6, 8} else "depth"
    return _line(vertices[first], vertices[second], controller_path=controller, note="特征外包框语义边")


def view_measurement(
    view: dict[str, Any], entity: dict[str, Any], space: str,
    selector_objects: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selector_object = (selector_objects or {}).get(entity["source_object_id"])
    bbox_match = re.fullmatch(r"feature_bbox\.edge\.(\d+)", entity["source_subobject"])
    if bbox_match and selector_object is not None:
        return _bbox_edge(selector_object, int(bbox_match.group(1)))

    geometry = entity["geometry"]
    kind = geometry["type"]
    axes = list(view["axes"])
    plane = view.get("plane")
    authority = "authoritative_2d" if space == "2d" and not entity["derived"] else "orthographic_projection"
    note = None
    if any(axis not in "xyz" for axis in axes):
        authority = "isometric_projection"
        note = "等轴投影值仅用于屏幕定位，不作为尺寸真值"
    elif entity["derived"]:
        note = "由编译特征生成的正投影/截面代理"

    if kind == "line":
        return _line(
            _lift(geometry["start"], axes, plane, space),
            _lift(geometry["end"], axes, plane, space),
            authority=authority,
            note=note,
        )
    if kind == "circle":
        return _circle(
            _lift(geometry["center"], axes, plane, space),
            float(geometry["radius"]), authority=authority, note=note,
        )
    return _point_measurement(
        _lift(geometry["point"], axes, plane, space), authority=authority, note=note,
    )
