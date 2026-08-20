from __future__ import annotations

import html
from html.parser import HTMLParser
import json
import math
from pathlib import Path
from typing import Any

from .engine import PlanError, ResolvedArc, ResolvedCircle, ResolvedDimension, ResolvedLine, ResolvedText, compile_plan
from .engine3d import ResolvedFeature3D, ResolvedProfile3D, compile_plan3d
from .semantic import describe_plan
from .measurements import coordinate_system, selector_measurement, view_measurement


def _line(
    entity_id: str, view_id: str, source_id: str, start: tuple[float, float], end: tuple[float, float],
    role: str, derived: bool, edit_paths: list[str], source_subobject: str,
) -> dict[str, Any]:
    return {
        "id": entity_id, "view_id": view_id, "source_object_id": source_id,
        "source_subobject": source_subobject, "geometry": {"type": "line", "start": list(start), "end": list(end)},
        "role": role, "derived": derived, "selectable": True, "edit_paths": edit_paths,
    }


def _circle(
    entity_id: str, view_id: str, source_id: str, center: tuple[float, float], radius: float,
    role: str, derived: bool, edit_paths: list[str], source_subobject: str,
) -> dict[str, Any]:
    return {
        "id": entity_id, "view_id": view_id, "source_object_id": source_id,
        "source_subobject": source_subobject, "geometry": {"type": "circle", "center": list(center), "radius": radius},
        "role": role, "derived": derived, "selectable": True, "edit_paths": edit_paths,
    }


def _rectangle(
    prefix: str, view_id: str, source_id: str, bounds: tuple[float, float, float, float],
    role: str, derived: bool, edit_paths: list[str], source_subobject: str,
) -> list[dict[str, Any]]:
    left, bottom, right, top = bounds
    points = ((left, bottom), (right, bottom), (right, top), (left, top))
    return [
        _line(f"{prefix}_{index + 1}", view_id, source_id, points[index], points[(index + 1) % 4], role, derived, edit_paths, f"{source_subobject}.edge.{index + 1}")
        for index in range(4)
    ]


def _profile_top(feature: ResolvedFeature3D, view_id: str) -> list[dict[str, Any]]:
    profile = feature.profile
    role = "additive" if feature.type != "cut_extrude" else "subtractive"
    if profile.kind == "center_rectangle":
        return _rectangle(
            f"{view_id}_{feature.id}_P", view_id, feature.id, profile.bounds, role, False,
            ["profile.center", "profile.width", "profile.height"], "profile",
        )
    circles = profile.primitives
    return [
        _circle(
            f"{view_id}_{feature.id}_C{index + 1:03d}", view_id, feature.id, item.center, item.radius,
            role, False, ["profile.center", "profile.radius"], f"profile.circle.{index + 1}",
        )
        for index, item in enumerate(circles)
    ]


def _feature_depth_bounds(feature: ResolvedFeature3D) -> tuple[float, float]:
    if feature.type == "cut_extrude":
        low = 0.0 if feature.end_condition == "through_all" else feature.support_top_z - feature.depth
        return low, feature.support_top_z
    return feature.support_top_z, feature.resulting_top_z


def _feature_elevation(feature: ResolvedFeature3D, view_id: str, axis: str) -> list[dict[str, Any]]:
    bounds = feature.profile.bounds
    low, high = _feature_depth_bounds(feature)
    horizontal = (bounds[0], bounds[2]) if axis == "x" else (bounds[1], bounds[3])
    role = "additive" if feature.type != "cut_extrude" else "subtractive"
    edit_paths = ["depth", "profile.center"]
    if feature.profile.kind == "center_rectangle":
        edit_paths.append("profile.width" if axis == "x" else "profile.height")
    else:
        edit_paths.append("profile.radius")
    return _rectangle(
        f"{view_id}_{feature.id}_B", view_id, feature.id, (horizontal[0], low, horizontal[1], high),
        role, True, edit_paths, f"projected_{axis}z_extent",
    )


def _iso(point: tuple[float, float, float]) -> tuple[float, float]:
    x, y, z = point
    angle = math.radians(30.0)
    return (x - y) * math.cos(angle), z + (x + y) * math.sin(angle)


def _feature_iso(feature: ResolvedFeature3D, view_id: str) -> list[dict[str, Any]]:
    left, bottom, right, top = feature.profile.bounds
    low, high = _feature_depth_bounds(feature)
    corners = (
        (left, bottom, low), (right, bottom, low), (right, top, low), (left, top, low),
        (left, bottom, high), (right, bottom, high), (right, top, high), (left, top, high),
    )
    edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
    role = "additive" if feature.type != "cut_extrude" else "subtractive"
    return [
        _line(
            f"{view_id}_{feature.id}_E{index + 1:02d}", view_id, feature.id,
            _iso(corners[first]), _iso(corners[second]), role, True,
            ["profile.center", "profile.width", "profile.height", "profile.radius", "depth"],
            f"feature_bbox.edge.{index + 1}",
        )
        for index, (first, second) in enumerate(edges)
    ]


def _profile_intervals(profile: ResolvedProfile3D, value: float, axis: str) -> list[tuple[float, float]]:
    if profile.kind == "center_rectangle":
        left, bottom, right, top = profile.bounds
        if axis == "x" and left <= value <= right:
            return [(bottom, top)]
        if axis == "y" and bottom <= value <= top:
            return [(left, right)]
        return []
    intervals: list[tuple[float, float]] = []
    for circle in profile.primitives:
        fixed = circle.center[0] if axis == "x" else circle.center[1]
        delta = value - fixed
        if abs(delta) <= circle.radius:
            span = math.sqrt(max(0.0, circle.radius * circle.radius - delta * delta))
            center = circle.center[1] if axis == "x" else circle.center[0]
            intervals.append((center - span, center + span))
    return intervals


def _feature_section(feature: ResolvedFeature3D, view_id: str, plane_axis: str, plane_value: float) -> list[dict[str, Any]]:
    low, high = _feature_depth_bounds(feature)
    role = "additive" if feature.type != "cut_extrude" else "subtractive"
    rows: list[dict[str, Any]] = []
    for index, interval in enumerate(_profile_intervals(feature.profile, plane_value, plane_axis), 1):
        rows.extend(_rectangle(
            f"{view_id}_{feature.id}_S{index:02d}", view_id, feature.id,
            (interval[0], low, interval[1], high), role, True,
            ["profile.center", "profile.width", "profile.height", "profile.radius", "depth"],
            f"section_{plane_axis}_{plane_value:g}.interval.{index}",
        ))
    return rows


def _view(
    view_id: str, label: str, kind: str, axes: list[str], lost_axis: str | None,
    geometry_scope: str, entities: list[dict[str, Any]], plane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": view_id, "label": label, "kind": kind, "axes": axes, "lost_axis": lost_axis,
        "plane": plane, "geometry_scope": geometry_scope, "entities": entities,
        "manufacturing_authority": False,
        "back_projection": {
            "unique_without_additional_constraints": lost_axis is None,
            "requires": [] if lost_axis is None else [f"lock_{lost_axis}", "second_view", "semantic_parameter"],
        },
    }


def _views_2d(data: dict[str, Any]) -> list[dict[str, Any]]:
    plan = compile_plan(data)
    drawing = data.get("drawing", {}) if isinstance(data.get("drawing"), dict) else {}
    domain = str(drawing.get("domain", "")).strip().lower()
    dimension_text_height = 280.0 if domain == "architecture" else 4.0
    source_by_id = {
        str(item.get("id")): item
        for item in data.get("steps", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    entities: list[dict[str, Any]] = []
    for item in plan.entities:
        if isinstance(item, ResolvedLine):
            source = source_by_id.get(item.id, {})
            construction = source.get("construction", {}) if isinstance(source, dict) else {}
            edit_paths = ["start"]
            if isinstance(construction, dict) and construction.get("kind") in {"polar", "parallel", "perpendicular"}:
                edit_paths.append("construction.length")
            entity = _line(
                f"PLAN_{item.id}", "PLAN", item.id, item.start, item.end, "geometry", False,
                edit_paths, "entity",
            )
            entity["placement_path"] = "start"
            entity["placement_point"] = list(item.start)
            entities.append(entity)
        elif isinstance(item, ResolvedCircle):
            entity = _circle(
                f"PLAN_{item.id}", "PLAN", item.id, item.center, item.radius, "geometry", False,
                ["center", "radius"], "entity",
            )
            entity["placement_path"] = "center"
            entity["placement_point"] = list(item.center)
            entities.append(entity)
        elif isinstance(item, ResolvedArc):
            segments = 32
            start = math.radians(item.start_angle_deg)
            sweep = math.radians((item.end_angle_deg - item.start_angle_deg) % 360)
            points = [
                (item.center[0] + item.radius * math.cos(start + sweep * index / segments), item.center[1] + item.radius * math.sin(start + sweep * index / segments))
                for index in range(segments + 1)
            ]
            arc_entities = [
                _line(
                    f"PLAN_{item.id}_A{index + 1:02d}", "PLAN", item.id, points[index], points[index + 1],
                    "geometry", True, ["center", "radius", "start_angle_deg", "end_angle_deg"], f"arc.segment.{index + 1}",
                )
                for index in range(segments)
            ]
            for entity in arc_entities:
                entity["placement_path"] = "center"
                entity["placement_point"] = list(item.center)
            entities.extend(arc_entities)
        elif isinstance(item, ResolvedText):
            entities.append({
                "id": f"PLAN_{item.id}", "view_id": "PLAN", "source_object_id": item.id,
                "source_subobject": "entity.insert", "geometry": {
                    "type": "point", "point": list(item.insert),
                    "display": {
                        "kind": "text", "value": item.value, "height": item.height,
                        "rotation_deg": item.rotation_deg,
                    },
                },
                "role": "annotation", "derived": False, "selectable": True,
                "edit_paths": ["insert", "value", "height", "rotation_deg"],
                "placement_path": "insert", "placement_point": list(item.insert),
            })
        else:
            dx, dy = item.second[0] - item.first[0], item.second[1] - item.first[1]
            length = math.hypot(dx, dy)
            nx, ny = -dy / length, dx / length
            offset = item.offset_distance
            first_base = (item.first[0] + nx * offset, item.first[1] + ny * offset)
            second_base = (item.second[0] + nx * offset, item.second[1] + ny * offset)
            dimension_line = _line(
                f"PLAN_{item.id}_D", "PLAN", item.id, first_base, second_base,
                "annotation", False, ["dimension_purpose"], "dimension.line",
            )
            dimension_line["geometry"]["display"] = {
                "kind": "dimension", "measurement": item.measurement,
                "orientation_deg": item.orientation_deg, "unit": "mm",
                "style_name": item.style_name,
                "dimension_purpose": item.dimension_purpose,
                "text_height": dimension_text_height,
                "owner_id": item.id,
            }
            entities.extend([
                dimension_line,
                _line(f"PLAN_{item.id}_E1", "PLAN", item.id, item.first, first_base, "annotation", True, [], "dimension.extension.1"),
                _line(f"PLAN_{item.id}_E2", "PLAN", item.id, item.second, second_base, "annotation", True, [], "dimension.extension.2"),
            ])
    return [_view("PLAN", "二维设计视图", "native_2d", ["x", "y"], None, "authoritative_2d_geometry", entities)]



def _key_point(
    entity_id: str, view_id: str, source_id: str, point: tuple[float, float],
    role: str, edit_paths: list[str], source_subobject: str, key_kind: str,
) -> dict[str, Any]:
    return {
        "id": entity_id, "view_id": view_id, "source_object_id": source_id,
        "source_subobject": source_subobject, "geometry": {"type": "point", "point": list(point)},
        "role": role, "derived": False, "selectable": True, "edit_paths": edit_paths,
        "key_geometry": True, "key_kind": key_kind,
    }


def _mark_key(entity: dict[str, Any], key_kind: str) -> dict[str, Any]:
    entity["key_geometry"] = True
    entity["key_kind"] = key_kind
    return entity


def _views_3d(data: dict[str, Any]) -> list[dict[str, Any]]:
    plan = compile_plan3d(data)
    top: list[dict[str, Any]] = []
    front: list[dict[str, Any]] = []
    right: list[dict[str, Any]] = []
    iso: list[dict[str, Any]] = []
    section_x: list[dict[str, Any]] = []
    section_y: list[dict[str, Any]] = []
    for feature in plan.features:
        profile = feature.profile
        role = "additive" if feature.type != "cut_extrude" else "subtractive"
        low, high = _feature_depth_bounds(feature)
        top.extend(_profile_top(feature, "TOP"))
        top.append(_key_point(
            f"TOP_{feature.id}_CENTER", "TOP", feature.id, profile.center, role,
            ["profile.center"], "profile.center", "geometric_center",
        ))
        if profile.kind == "circle_pattern" and profile.bolt_circle_radius is not None:
            top.append(_mark_key(_circle(
                f"TOP_{feature.id}_PITCH", "TOP", feature.id, profile.center,
                profile.bolt_circle_radius, role, True,
                ["profile.count", "profile.bolt_circle_radius", "profile.start_angle_deg"],
                "profile.pattern.pitch_circle",
            ), "pitch_circle"))
        front.extend(_feature_elevation(feature, "FRONT", "x"))
        front.append(_mark_key(_line(
            f"FRONT_{feature.id}_CENTER_AXIS", "FRONT", feature.id,
            (profile.center[0], low), (profile.center[0], high), role, True,
            ["profile.center", "depth"], "feature.axis.center.xz",
        ), "center_axis"))
        right.extend(_feature_elevation(feature, "RIGHT", "y"))
        right.append(_mark_key(_line(
            f"RIGHT_{feature.id}_CENTER_AXIS", "RIGHT", feature.id,
            (profile.center[1], low), (profile.center[1], high), role, True,
            ["profile.center", "depth"], "feature.axis.center.yz",
        ), "center_axis"))
        iso.extend(_feature_iso(feature, "ISOMETRIC"))
        section_x.extend(_feature_section(feature, "SECTION_X0", "x", 0.0))
        section_y.extend(_feature_section(feature, "SECTION_Y0", "y", 0.0))
    return [
        _view("TOP", "\u4fef\u89c6\u56fe", "orthographic", ["x", "y"], "z", "feature_profiles_before_final_visibility", top),
        _view("FRONT", "\u4e3b\u89c6\u56fe", "orthographic", ["x", "z"], "y", "feature_operation_extents", front),
        _view("RIGHT", "\u53f3\u89c6\u56fe", "orthographic", ["y", "z"], "x", "feature_operation_extents", right),
        _view("ISOMETRIC", "\u7b49\u8f74\u8bed\u4e49\u9009\u62e9\u56fe", "isometric", ["u", "v"], "depth", "selectable_feature_extent_proxy", iso),
        _view("SECTION_X0", "X=0 \u57fa\u51c6\u622a\u9762", "section", ["y", "z"], None, "feature_operation_section", section_x, {"axis": "x", "value": 0.0}),
        _view("SECTION_Y0", "Y=0 \u57fa\u51c6\u622a\u9762", "section", ["x", "z"], None, "feature_operation_section", section_y, {"axis": "y", "value": 0.0}),
    ]


def _core_parameters_for_selector(feature: ResolvedFeature3D) -> list[dict[str, Any]]:
    profile = feature.profile
    center_selection = f"SEL3D_{feature.id}_CENTER_POINT"
    pattern_selection = f"SEL3D_{feature.id}_PATTERN_CONTROLLER"
    rows: list[dict[str, Any]] = [{
        "id": "center", "path": "profile.center", "label": "\u4e2d\u5fc3 X, Y",
        "value": list(profile.center), "unit": "mm", "selection_id": center_selection,
    }]
    controller = pattern_selection if profile.kind == "circle_pattern" else center_selection
    if profile.width is not None:
        rows.append({"id": "width", "path": "profile.width", "label": "\u5bbd\u5ea6", "value": profile.width, "unit": "mm", "selection_id": controller})
    if profile.height is not None:
        rows.append({"id": "height", "path": "profile.height", "label": "\u9ad8\u5ea6", "value": profile.height, "unit": "mm", "selection_id": controller})
    if profile.radius is not None:
        rows.append({"id": "radius", "path": "profile.radius", "label": "\u534a\u5f84", "value": profile.radius, "unit": "mm", "selection_id": controller})
    if profile.count is not None:
        rows.append({"id": "count", "path": "profile.count", "label": "\u9635\u5217\u6570\u91cf", "value": profile.count, "unit": "", "selection_id": controller})
    if profile.bolt_circle_radius is not None:
        rows.append({"id": "pitch_radius", "path": "profile.bolt_circle_radius", "label": "\u5206\u5e03\u5706\u534a\u5f84", "value": profile.bolt_circle_radius, "unit": "mm", "selection_id": controller})
    if profile.start_angle_deg is not None:
        rows.append({"id": "start_angle", "path": "profile.start_angle_deg", "label": "\u8d77\u59cb\u89d2", "value": profile.start_angle_deg, "unit": "\u00b0", "selection_id": controller})
    rows.append({"id": "depth", "path": "depth", "label": "\u6df1\u5ea6", "value": feature.depth, "unit": "mm", "selection_id": controller})
    return rows


def _selector_3d(data: dict[str, Any]) -> dict[str, Any]:
    plan = compile_plan3d(data)
    objects: list[dict[str, Any]] = []
    for feature in plan.features:
        low, high = _feature_depth_bounds(feature)
        sketch_z = high if feature.type == "cut_extrude" else low
        profile = feature.profile
        subobjects: list[dict[str, Any]] = []

        def add(
            suffix: str, source_subobject: str, geometry_type: str, edit_paths: list[str], derived: bool,
            edit_scope: str, affected_instance_count: int = 1, requires_preserve_policy: bool = False,
            key_geometry: bool = False, relation_capabilities: list[str] | None = None,
        ) -> None:
            if relation_capabilities is None:
                relation_capabilities = {
                    "line": ["parallel", "perpendicular", "collinear", "equal_length"],
                    "circle": ["concentric", "equal_radius"],
                    "face": ["parallel", "perpendicular", "coincident", "offset"],
                    "point": ["coincident"],
                }.get(geometry_type, [])
            subobjects.append({
                "id": f"SEL3D_{feature.id}_{suffix}", "source_object_id": feature.id,
                "source_subobject": source_subobject, "geometry_type": geometry_type,
                "role": "subtractive" if feature.type == "cut_extrude" else "additive",
                "derived": derived, "selectable": True, "edit_paths": edit_paths,
                "reference_key": f"{feature.id}|{source_subobject}", "edit_scope": edit_scope,
                "shared_parameter_groups": [f"{feature.id}.{path}" for path in edit_paths],
                "affected_instance_count": affected_instance_count,
                "requires_preserve_policy": requires_preserve_policy, "detach_supported": False,
                "key_geometry": key_geometry, "relation_capabilities": relation_capabilities,
                "measurement": selector_measurement(feature, source_subobject),
            })

        is_pattern = profile.kind == "circle_pattern"
        count = max(1, len(profile.primitives or ()))
        feature_scope = "shared_pattern_parameter" if is_pattern else "feature_parameter"
        core_paths = [row["path"] for row in _core_parameters_for_selector(feature)]
        center_paths = ["profile.center"] if is_pattern else core_paths
        add("CENTER_POINT", "profile.center", "point", center_paths, False, feature_scope, count if is_pattern else 1, key_geometry=True)
        add("CENTER_AXIS_XZ", "feature.axis.center.xz", "line", ["profile.center", "depth"], True, feature_scope, count if is_pattern else 1, key_geometry=True, relation_capabilities=[])
        add("CENTER_AXIS_YZ", "feature.axis.center.yz", "line", ["profile.center", "depth"], True, feature_scope, count if is_pattern else 1, key_geometry=True, relation_capabilities=[])

        if profile.kind == "center_rectangle":
            for index in range(1, 5):
                axis_path = "profile.width" if index in {1, 3} else "profile.height"
                add(f"PROFILE_EDGE_{index}", f"profile.edge.{index}", "line", ["profile.center", axis_path], False, "subobject_parameterized", requires_preserve_policy=True)
                add(f"OPPOSITE_EDGE_{index}", f"feature.edge.opposite.{index}", "line", ["depth", "profile.center", axis_path], True, "derived_parameter_proxy", requires_preserve_policy=True, key_geometry=True)
                add(f"VERTICAL_EDGE_{index}", f"feature.edge.vertical.{index}", "line", ["depth", "profile.center"], True, "derived_parameter_proxy", requires_preserve_policy=True, key_geometry=True)
                add(f"SIDE_FACE_{index}", f"feature.face.side.{index}", "face", ["profile.center", axis_path, "depth"], True, "derived_parameter_proxy", requires_preserve_policy=True)
            add("SKETCH_FACE", "profile.face", "face", ["profile.center", "profile.width", "profile.height"], False, "feature_parameter")
            add("OPPOSITE_FACE", "feature.face.opposite", "face", ["depth", "profile.width", "profile.height"], True, "derived_parameter_proxy")
        else:
            if is_pattern:
                add("PATTERN_CONTROLLER", "profile.pattern.pitch_circle", "circle", core_paths, False, "shared_pattern_parameter", count, key_geometry=True, relation_capabilities=[])
            scope = "shared_pattern_parameter" if count > 1 else "feature_parameter"
            for index, _circle_value in enumerate(profile.primitives or (), 1):
                add(f"PROFILE_CIRCLE_{index}", f"profile.circle.{index}", "circle", ["profile.center", "profile.radius"], False, scope, count)
                add(f"OPPOSITE_CIRCLE_{index}", f"feature.circle.opposite.{index}", "circle", ["depth", "profile.radius"], True, scope, count, key_geometry=True)
                add(f"CYLINDER_FACE_{index}", f"feature.face.cylindrical.{index}", "face", ["profile.center", "profile.radius", "depth"], True, scope, count)
                add(f"SKETCH_FACE_{index}", f"profile.face.{index}", "face", ["profile.center", "profile.radius"], False, scope, count)
                add(f"OPPOSITE_FACE_{index}", f"feature.face.opposite.{index}", "face", ["depth", "profile.radius"], True, "derived_parameter_proxy", count)
        objects.append({
            "source_object_id": feature.id, "feature_type": feature.type,
            "role": "subtractive" if feature.type == "cut_extrude" else "additive",
            "z_min": low, "z_max": high, "sketch_z": sketch_z,
            "profile": _profile_parameters_for_selector(profile),
            "core_parameters": _core_parameters_for_selector(feature), "subobjects": subobjects,
        })
    return {"mode": "semantic_subobject", "topology_authority": False, "topology_stability": "plan_derived_not_native_persistent_name", "objects": objects}


def _profile_parameters_for_selector(profile: ResolvedProfile3D) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": profile.kind, "center": list(profile.center), "bounds": list(profile.bounds)}
    for key in ("width", "height", "radius", "count", "bolt_circle_radius", "start_angle_deg"):
        item = getattr(profile, key)
        if item is not None:
            value[key] = item
    value["primitives"] = [{"center": list(item.center), "radius": item.radius} for item in profile.primitives]
    return value

def generate_view_package(data: dict[str, Any], space: str, domain: str = "general") -> dict[str, Any]:
    if space not in {"2d", "3d"}:
        raise PlanError("space must be 2d or 3d")
    semantic = describe_plan(data, space, domain)
    views = _views_2d(data) if space == "2d" else _views_3d(data)
    layer_by_id = {
        str(item["id"]): str(item.get("source", {}).get("cad_layer", "0")).upper()
        for item in semantic.get("objects", [])
    }
    selector_3d = _selector_3d(data) if space == "3d" else None
    compiled_origin = compile_plan(data).origin if space == "2d" else compile_plan3d(data).origin
    model_coordinate_system = coordinate_system(compiled_origin, space)
    selector_objects_by_id = {item["source_object_id"]: item for item in (selector_3d or {}).get("objects", [])}
    selection_map: dict[str, dict[str, Any]] = {}
    for view in views:
        for entity in view["entities"]:
            selection = {
                "view_id": view["id"], "view_entity_id": entity["id"], "source_object_id": entity["source_object_id"],
                "source_subobject": entity["source_subobject"], "reference_key": f"{entity['source_object_id']}|{entity['source_subobject']}",
                "geometry_type": entity["geometry"]["type"], "role": entity["role"], "derived": entity["derived"],
                "edit_paths": entity["edit_paths"], "back_projection": view["back_projection"],
                "measurement": view_measurement(view, entity, space, selector_objects_by_id),
            }
            if entity.get("placement_path") and entity.get("placement_point") is not None:
                selection["placement_path"] = entity["placement_path"]
                selection["placement_point"] = list(entity["placement_point"])
            if space == "2d":
                geometry_type = entity["geometry"]["type"]
                layer = layer_by_id.get(entity["source_object_id"], "0")
                annotation = layer in {"DIMENSION", "TEXT", "TAG_TEXT", "GRID_TEXT", "TITLEBLOCK", "SCHEDULE", "REVISION", "WALL_TYPE"}
                capabilities = [] if annotation else {
                    "line": ["parallel", "perpendicular", "collinear", "equal_length"],
                    "circle": ["concentric", "equal_radius"],
                    "point": ["coincident"],
                }.get(geometry_type, [])
                selection.update({
                    "edit_scope": "subobject_parameterized",
                    "shared_parameter_groups": [],
                    "affected_instance_count": 1,
                    "requires_preserve_policy": geometry_type == "line" and not annotation,
                    "detach_supported": False,
                    "relation_capabilities": capabilities,
                })
            selection_map[entity["id"]] = selection
            if entity.get("key_geometry"):
                selection_map[entity["id"]].update({"key_geometry": True, "key_kind": entity.get("key_kind", "construction")})
    if selector_3d is not None:
        for item in selector_3d["objects"]:
            for subobject in item["subobjects"]:
                selection_map[subobject["id"]] = {
                    "view_id": "SELECTOR_3D", "view_entity_id": subobject["id"],
                    "source_object_id": subobject["source_object_id"],
                    "source_subobject": subobject["source_subobject"],
                    "reference_key": subobject["reference_key"],
                    "geometry_type": subobject["geometry_type"], "role": subobject["role"],
                    "derived": subobject["derived"], "edit_paths": subobject["edit_paths"],
                    "back_projection": {"unique_without_additional_constraints": not subobject["derived"], "requires": [] if not subobject["derived"] else ["semantic_parameter", "native_topology_readback"]},
                    "key_geometry": subobject.get("key_geometry", False),
                    "relation_capabilities": subobject.get("relation_capabilities", []),
                    "measurement": subobject["measurement"],
                }
    if selector_3d is not None:
        scope_by_key = {
            subobject["reference_key"]: {
                key: subobject[key]
                for key in (
                    "edit_paths", "edit_scope", "shared_parameter_groups", "affected_instance_count",
                    "requires_preserve_policy", "detach_supported", "key_geometry", "relation_capabilities",
                    "measurement",
                )
            }
            for item in selector_3d["objects"]
            for subobject in item["subobjects"]
        }
        for selection in selection_map.values():
            metadata = scope_by_key.get(selection["reference_key"])
            if metadata is not None:
                selection.update(metadata)
    return {
        "schema_version": "1.1", "space": space, "domain": domain,
        "source_sha256": semantic["document"]["source_sha256"],
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
        "semantic_document": semantic, "coordinate_system": model_coordinate_system,
        "views": views, "selection_map": selection_map, "selector_3d": selector_3d,
        "limits": {
            "projection_is_not_dimension_authority": True,
            "derived_entities_require_semantic_parameter_or_second_view": True,
            "native_host_hidden_line_and_section_evidence_required_for_manufacturing": space == "3d",
        },
    }


def _bounds(entities: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for entity in entities:
        geometry = entity["geometry"]
        if geometry["type"] == "line":
            xs.extend((float(geometry["start"][0]), float(geometry["end"][0])))
            ys.extend((float(geometry["start"][1]), float(geometry["end"][1])))
        else:
            cx, cy = geometry["center"]
            radius = float(geometry["radius"])
            xs.extend((cx - radius, cx + radius))
            ys.extend((cy - radius, cy + radius))
    if not xs:
        return 0.0, 0.0, 100.0, 100.0
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    padding = max(right - left, top - bottom, 1.0) * 0.08
    return left - padding, bottom - padding, right + padding, top + padding


def _svg(view: dict[str, Any]) -> str:
    left, bottom, right, top = _bounds(view["entities"])
    width, height = right - left, top - bottom
    parts = [
        f'<svg class="cad-view" data-view-id="{html.escape(view["id"])}" viewBox="{left:g} {-top:g} {width:g} {height:g}" role="img" aria-label="{html.escape(view["label"])}">',
        '<g transform="scale(1,-1)">',
    ]
    for entity in view["entities"]:
        geometry = entity["geometry"]
        visible_classes = f'view-entity role-{entity["role"]}' + (" derived" if entity["derived"] else "")
        data_attributes = (
            f'data-view-entity-id="{html.escape(entity["id"])}" '
            f'data-source-id="{html.escape(entity["source_object_id"])}" '
            f'data-source-subobject="{html.escape(entity["source_subobject"])}" '
            f'data-derived="{str(entity["derived"]).lower()}"'
        )
        visible_attributes = f'class="{visible_classes}" {data_attributes}'
        hit_attributes = f'class="view-hit" {data_attributes} aria-label="{html.escape(entity["source_object_id"])} {html.escape(entity["source_subobject"])}"'
        if geometry["type"] == "line":
            start, end = geometry["start"], geometry["end"]
            shape = f'x1="{start[0]:g}" y1="{start[1]:g}" x2="{end[0]:g}" y2="{end[1]:g}"'
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            if length > 1e-12:
                hit_half = max(width, height, 1.0) * 0.02
                nx, ny = -dy / length * hit_half, dx / length * hit_half
                points = (
                    (start[0] + nx, start[1] + ny), (end[0] + nx, end[1] + ny),
                    (end[0] - nx, end[1] - ny), (start[0] - nx, start[1] - ny),
                )
                polygon = " ".join(f"{x:g},{y:g}" for x, y in points)
                parts.append(f'<polygon {hit_attributes} points="{polygon}"/>')
            parts.append(f'<line {visible_attributes} {shape}/>')
        else:
            center = geometry["center"]
            shape = f'cx="{center[0]:g}" cy="{center[1]:g}" r="{geometry["radius"]:g}"'
            parts.append(f'<circle {hit_attributes} {shape}/>')
            parts.append(f'<circle {visible_attributes} {shape}/>')
    parts.extend(["</g>", "</svg>"])
    return "".join(parts)


def _selector_script() -> str:
    return r"""
function initAicad3dSelector(){
  const canvas=document.getElementById('aicad3d-selector');
  if(!canvas||!pkg.selector_3d)return;canvas.style.touchAction='none';
  const ctx=canvas.getContext('2d');
  let yaw=-0.65,pitch=0.52,zoom=1,dragging=false,moved=false,lastX=0,lastY=0,hitFaces=[],hitEdges=[],hoveredKey=null;
  const faces=[],edges=[],refs=pkg.selection_map;
  const ref=id=>refs[id];
  function addPrism(o){
    const [x0,y0,x1,y1]=o.profile.bounds,z0=o.z_min,z1=o.z_max,id=o.source_object_id;
    const v=[[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]];
    const sketchBottom=Math.abs(o.sketch_z-z0)<1e-9;
    const bottomFace=ref(`SEL3D_${id}_${sketchBottom?'SKETCH_FACE':'OPPOSITE_FACE'}`),topFace=ref(`SEL3D_${id}_${sketchBottom?'OPPOSITE_FACE':'SKETCH_FACE'}`);
    faces.push({ref:bottomFace,kind:o.feature_type,vertices:[v[0],v[1],v[2],v[3]]},{ref:topFace,kind:o.feature_type,vertices:[v[4],v[7],v[6],v[5]]});
    const sideFaces=[[0,4,5,1],[1,5,6,2],[2,6,7,3],[3,7,4,0]];
    sideFaces.forEach((f,i)=>faces.push({ref:ref(`SEL3D_${id}_SIDE_FACE_${i+1}`),kind:o.feature_type,vertices:f.map(n=>v[n])}));
    const bottom=[[0,1],[1,2],[2,3],[3,0]],top=[[4,5],[5,6],[6,7],[7,4]],vertical=[[0,4],[1,5],[2,6],[3,7]];
    for(let i=0;i<4;i++){
      const profilePair=sketchBottom?bottom[i]:top[i],oppositePair=sketchBottom?top[i]:bottom[i];
      edges.push({ref:ref(`SEL3D_${id}_PROFILE_EDGE_${i+1}`),kind:o.feature_type,a:v[profilePair[0]],b:v[profilePair[1]]});
      edges.push({ref:ref(`SEL3D_${id}_OPPOSITE_EDGE_${i+1}`),kind:o.feature_type,a:v[oppositePair[0]],b:v[oppositePair[1]]});
      edges.push({ref:ref(`SEL3D_${id}_VERTICAL_EDGE_${i+1}`),kind:o.feature_type,a:v[vertical[i][0]],b:v[vertical[i][1]]});
    }
  }
  function addCylinders(o){
    const n=32,id=o.source_object_id,sketchBottom=Math.abs(o.sketch_z-o.z_min)<1e-9;
    (o.profile.primitives||[]).forEach((c,index)=>{
      const k=index+1,b=[],t=[];
      for(let i=0;i<n;i++){const a=i*Math.PI*2/n;b.push([c.center[0]+c.radius*Math.cos(a),c.center[1]+c.radius*Math.sin(a),o.z_min]);t.push([c.center[0]+c.radius*Math.cos(a),c.center[1]+c.radius*Math.sin(a),o.z_max]);}
      const sketchFace=ref(`SEL3D_${id}_SKETCH_FACE_${k}`),oppositeFace=ref(`SEL3D_${id}_OPPOSITE_FACE_${k}`),cylFace=ref(`SEL3D_${id}_CYLINDER_FACE_${k}`);
      faces.push({ref:sketchBottom?sketchFace:oppositeFace,kind:o.feature_type,vertices:b},{ref:sketchBottom?oppositeFace:sketchFace,kind:o.feature_type,vertices:[...t].reverse()});
      for(let i=0;i<n;i++){const j=(i+1)%n;faces.push({ref:cylFace,kind:o.feature_type,vertices:[b[i],b[j],t[j],t[i]]});}
      const profileRef=ref(`SEL3D_${id}_PROFILE_CIRCLE_${k}`),oppositeRef=ref(`SEL3D_${id}_OPPOSITE_CIRCLE_${k}`),profileRing=sketchBottom?b:t,oppositeRing=sketchBottom?t:b;
      for(let i=0;i<n;i++){const j=(i+1)%n;edges.push({ref:profileRef,kind:o.feature_type,a:profileRing[i],b:profileRing[j]},{ref:oppositeRef,kind:o.feature_type,a:oppositeRing[i],b:oppositeRing[j]});}
    });
  }
  for(const o of pkg.selector_3d.objects){if(o.profile.kind==='center_rectangle')addPrism(o);else addCylinders(o);const c=o.profile.center,r=ref(`SEL3D_${o.source_object_id}_CENTER_POINT`);edges.push({ref:r,kind:o.feature_type,key:true,a:[c[0],c[1],o.z_min],b:[c[0],c[1],o.z_max]});}
  const all=[...faces.flatMap(x=>x.vertices),...edges.flatMap(x=>[x.a,x.b])],mins=[0,1,2].map(a=>Math.min(...all.map(v=>v[a]))),maxs=[0,1,2].map(a=>Math.max(...all.map(v=>v[a]))),center=mins.map((v,i)=>(v+maxs[i])/2),span=Math.max(...maxs.map((v,i)=>v-mins[i]),1);
  function rotate(v){const x=v[0]-center[0],y=v[1]-center[1],z=v[2]-center[2],cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),x1=cy*x-sy*y,y1=sy*x+cy*y;return[x1,cp*z-sp*y1,sp*z+cp*y1];}
  function inside(x,y,p){let c=false;for(let i=0,j=p.length-1;i<p.length;j=i++){if(((p[i][1]>y)!==(p[j][1]>y))&&(x<(p[j][0]-p[i][0])*(y-p[i][1])/(p[j][1]-p[i][1])+p[i][0]))c=!c;}return c;}
  function segmentDistance(x,y,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],l=dx*dx+dy*dy;if(!l)return Math.hypot(x-a[0],y-a[1]);const t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/l));return Math.hypot(x-(a[0]+t*dx),y-(a[1]+t*dy));}
  function drawCoordinateTriad(context,w,h,dpr){const origin={x:48*dpr,y:h-42*dpr},size=27*dpr,axes=[['X',[1,0,0],'#c9362b'],['Y',[0,1,0],'#2f6f54'],['Z',[0,0,1],'#2563eb']];for(const [label,v,color] of axes){const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),x1=cy*v[0]-sy*v[1],y1=sy*v[0]+cy*v[1],rx=x1,ry=cp*v[2]-sp*y1,n=Math.hypot(rx,ry)||1,ex=origin.x+rx/n*size,ey=origin.y-ry/n*size;context.beginPath();context.moveTo(origin.x,origin.y);context.lineTo(ex,ey);context.strokeStyle=color;context.lineWidth=1.7*dpr;context.stroke();context.beginPath();context.arc(ex,ey,2.1*dpr,0,Math.PI*2);context.fillStyle=color;context.fill();context.font=`bold ${10*dpr}px Consolas`;context.fillText(label,ex+(rx/n)*7*dpr,ey-(ry/n)*7*dpr);}context.beginPath();context.arc(origin.x,origin.y,2.4*dpr,0,Math.PI*2);context.fillStyle='#132433';context.fill();context.font=`${9*dpr}px Consolas`;context.fillStyle='#475569';context.fillText('MODEL XYZ',12*dpr,h-10*dpr);}
  function draw(){
    const box=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2),w=Math.max(1,Math.round(box.width*dpr)),h=Math.max(1,Math.round(box.height*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
    ctx.clearRect(0,0,w,h);ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);const scale=Math.min(w,h)*.68/span*zoom;
    const project=v=>{const r=rotate(v);return{x:w/2+r[0]*scale,y:h/2-r[1]*scale,z:r[2]};};
    hitFaces=faces.map(f=>{const p=f.vertices.map(project);return{...f,p,depth:p.reduce((s,v)=>s+v.z,0)/p.length};}).sort((a,b)=>a.depth-b.depth);
    for(const f of hitFaces){if(!f.ref)continue;const exact=selectedReferenceKeys().has(f.ref.reference_key),context=selected.includes(f.ref.source_object_id),cut=f.kind==='cut_extrude';ctx.beginPath();ctx.moveTo(f.p[0].x,f.p[0].y);for(const p of f.p.slice(1))ctx.lineTo(p.x,p.y);ctx.closePath();ctx.fillStyle=exact?'rgba(245,158,11,.52)':cut?'rgba(220,38,38,.16)':context?'rgba(96,165,250,.24)':'rgba(37,99,235,.13)';ctx.strokeStyle=exact?'#f59e0b':cut?'#ef4444':context?'#60a5fa':'#94a3b8';ctx.lineWidth=(exact?1.4:.5)*dpr;ctx.fill();ctx.stroke();}
    hitEdges=edges.map(e=>{const a=project(e.a),b=project(e.b);return{...e,a,b,depth:(a.z+b.z)/2};}).sort((a,b)=>a.depth-b.depth);
    for(const e of hitEdges){if(!e.ref)continue;const exact=selectedReferenceKeys().has(e.ref.reference_key),context=selected.includes(e.ref.source_object_id),isKey=e.key||e.ref.key_geometry;if(isKey&&!exact&&!context&&hoveredKey!==e.ref.reference_key)continue;ctx.beginPath();ctx.moveTo(e.a.x,e.a.y);ctx.lineTo(e.b.x,e.b.y);ctx.strokeStyle=exact?'#f59e0b':context?'#2563eb':'#334155';ctx.lineWidth=(exact?1.8:context?1:.65)*dpr;ctx.stroke();}
    if(window.__aicadCoordinateVisible!==false)drawCoordinateTriad(ctx,w,h,dpr);ctx.fillStyle='#475569';ctx.font=`${12*dpr}px Microsoft YaHei,sans-serif`;ctx.fillText('\u62d6\u52a8\u65cb\u8f6c \u00b7 \u6eda\u8f6e\u7f29\u653e \u00b7 \u5355\u51fb\u9009\u62e9\u8fb9\u6216\u9762',12*dpr,20*dpr);
  }
  canvas.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'&&e.button!==0)return;dragging=true;moved=false;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture?.(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!dragging){const b=canvas.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2),x=(e.clientX-b.left)*d,y=(e.clientY-b.top)*d,c=[...hitEdges].filter(v=>v.ref&&(v.key||v.ref.key_geometry)).map(edge=>({edge,distance:segmentDistance(x,y,[edge.a.x,edge.a.y],[edge.b.x,edge.b.y])})).filter(v=>v.distance<=9*d).sort((a,b)=>a.distance-b.distance),next=c.length?c[0].edge.ref.reference_key:null;if(next!==hoveredKey){hoveredKey=next;canvas.style.cursor=next?'pointer':'grab';draw();}return;}const dx=e.clientX-lastX,dy=e.clientY-lastY;if(Math.abs(dx)+Math.abs(dy)>1)moved=true;yaw+=dx*.009;pitch=Math.max(-1.45,Math.min(1.45,pitch+dy*.009));lastX=e.clientX;lastY=e.clientY;draw();});
  canvas.addEventListener('pointerup',e=>{dragging=false;canvas.releasePointerCapture?.(e.pointerId);if(moved)return;const b=canvas.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2),x=(e.clientX-b.left)*d,y=(e.clientY-b.top)*d,threshold=7*d;const nearest=[...hitEdges].reverse().map(edge=>({edge,distance:segmentDistance(x,y,[edge.a.x,edge.a.y],[edge.b.x,edge.b.y])})).filter(x=>x.distance<=threshold).sort((a,b)=>a.distance-b.distance)[0];if(nearest){toggleSelectionRef(nearest.edge.ref);return;}const face=[...hitFaces].reverse().find(f=>f.ref&&inside(x,y,f.p.map(p=>[p.x,p.y])));if(face)toggleSelectionRef(face.ref);});
  canvas.addEventListener('pointercancel',()=>{dragging=false;hoveredKey=null;canvas.style.cursor='grab';draw();});canvas.addEventListener('pointerleave',()=>{if(!dragging){hoveredKey=null;canvas.style.cursor='grab';draw();}});canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.35,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});window.addEventListener('resize',draw);document.addEventListener('visibilitychange',()=>{if(!document.hidden)draw();});window.drawAicad3d=draw;window.__aicad3dSelector={draw,get coordinateSystemVisible(){return window.__aicadCoordinateVisible!==false}};draw();
}
"""


def _interaction_script() -> str:
    return r"""
const selected=[],selectedRefs=[],operations=[],notes=[],transactionRefs=new Map();
window.aicadReviewState={selected,selectedRefs,operations,notes,transactionRefs};
const referenceKey=r=>r.reference_key||`${r.source_object_id}|${r.source_subobject}`;
const selectedReferenceKeys=()=>new Set(selectedRefs.map(referenceKey));
const objectOrder=new Map(pkg.semantic_document.objects.map((x,i)=>[x.id,i]));
const isExactReference=r=>!!(r&&r.edit_scope&&r.reference_key);
function compactRef(r){return{source_object_id:r.source_object_id,source_subobject:r.source_subobject,reference_key:referenceKey(r),geometry_type:r.geometry_type,edit_paths:r.edit_paths};}
function syncSelectedObjects(){selected.length=0;for(const r of selectedRefs)if(!selected.includes(r.source_object_id))selected.push(r.source_object_id);}
function remember(r){transactionRefs.set(referenceKey(r),compactRef(r));}
function toggleSelectionRef(raw){if(!raw)return;const r={...raw,reference_key:referenceKey(raw)},key=referenceKey(r),i=selectedRefs.findIndex(x=>referenceKey(x)===key);if(i>=0)selectedRefs.splice(i,1);else{if(selectedRefs.length===2)selectedRefs.shift();selectedRefs.push(r);}syncSelectedObjects();render();}
function relationOptions(){
  if(selectedRefs.length!==2||!selectedRefs.every(isExactReference))return[];const [a,b]=selectedRefs,types=[a.geometry_type,b.geometry_type];
  if(types.every(x=>x==='line'))return['parallel','perpendicular','collinear','equal_length'];
  if(types.every(x=>x==='circle'))return['concentric','equal_radius'];
  if(types.every(x=>x==='face'))return['parallel','perpendicular','coincident','offset'];
  return[];
}
function movableRef(refs){return [...refs].sort((a,b)=>(objectOrder.get(a.source_object_id)-objectOrder.get(b.source_object_id))||referenceKey(a).localeCompare(referenceKey(b)))[1];}
function scopeFields(r){const shared=r.edit_scope==='shared_pattern_parameter',value={scope:shared?'shared_parameter_group':(r.edit_scope==='subobject_parameterized'?'subobject':'feature'),expected_affected_instance_count:r.affected_instance_count||1};if(shared)value.expected_shared_parameter_groups=r.shared_parameter_groups||[];return value;}
function preservePolicy(){return document.getElementById('preserve').value;}
function requireExact(refs){if(refs.every(isExactReference))return true;notes.push({text:'\u6295\u5f71\u4ee3\u7406\u4e0d\u80fd\u76f4\u63a5\u4fee\u6539\uff1b\u8bf7\u5728\u4e09\u7ef4\u9009\u62e9\u5668\u6216\u5bf9\u5e94\u539f\u751f\u89c6\u56fe\u4e2d\u9009\u62e9\u7cbe\u786e\u8fb9\u3001\u5706\u6216\u9762\u3002',selected_refs:refs.map(compactRef),status:'requires_disambiguation'});renderDraft();return false;}
function appendOperation(operation,refs){if(!requireExact(refs))return false;for(const r of refs)remember(r);operations.push(operation);renderDraft();return true;}
const preserveLabels={keep_center:'\u4fdd\u6301\u4e2d\u5fc3',keep_opposite:'\u4fdd\u6301\u5bf9\u8fb9',keep_size:'\u4fdd\u6301\u5c3a\u5bf8',keep_support:'\u4fdd\u6301\u652f\u6491\u9762'};
const editScopeLabels={subobject_parameterized:'\u5b50\u5bf9\u8c61\u53c2\u6570\u5316',feature_parameter:'\u5355\u7279\u5f81\u53c2\u6570',shared_pattern_parameter:'\u9635\u5217\u5171\u4eab\u53c2\u6570',derived_parameter_proxy:'\u6d3e\u751f\u51e0\u4f55\u4ee3\u7406'};
const relationLabels={parallel:'\u5e73\u884c',perpendicular:'\u5782\u76f4',collinear:'\u5171\u7ebf',equal_length:'\u7b49\u957f',concentric:'\u540c\u5fc3',equal_radius:'\u7b49\u534a\u5f84',coincident:'\u91cd\u5408',offset:'\u504f\u79fb'};
function populatePath(){const select=document.getElementById('parameterPath'),r=selectedRefs.length===1?selectedRefs[0]:null,paths=r?.edit_paths||[];select.innerHTML=paths.map(x=>`<option value="${x}">${x}</option>`).join('');}
function render(){
  const exact=selectedReferenceKeys();document.querySelectorAll('.view-entity').forEach(x=>{const key=`${x.dataset.sourceId}|${x.dataset.sourceSubobject}`;x.classList.toggle('selected',exact.has(key));x.classList.toggle('context-selected',!exact.has(key)&&selected.includes(x.dataset.sourceId));});
  document.getElementById('selection').innerHTML=selectedRefs.length?selectedRefs.map(r=>{const o=objects.get(r.source_object_id);return `<div class="item"><b>${r.source_object_id} \u00b7 ${r.source_subobject}</b><br>${o?.purpose||''}<br>\u89c6\u56fe\uff1a${r.view_id} \u00b7 \u7c7b\u578b\uff1a${r.geometry_type}<br>\u7f16\u8f91\u4f5c\u7528\u57df\uff1a${editScopeLabels[r.edit_scope]||r.edit_scope||'\u672a\u6807\u6ce8'}<br>\u53ef\u4fee\u6539\uff1a${(r.edit_paths||[]).join(', ')||'\u9700\u6d88\u6b67'}${r.affected_instance_count>1?`<br><span class="scope-warning">\u6ce8\u610f\uff1a\u8be5\u53c2\u6570\u5171\u4eab\uff0c\u5c06\u5f71\u54cd ${r.affected_instance_count} \u4e2a\u5b9e\u4f8b\uff1b\u4e0d\u4f1a\u9ed8\u8ba4\u62c6\u5206\u9635\u5217\u3002</span>`:''}${r.requires_preserve_policy?'<br><span class="scope-warning">\u79fb\u52a8\u524d\u5fc5\u987b\u9009\u62e9\u4fdd\u6301\u7b56\u7565\u3002</span>':''}</div>`;}).join(''):'<span>\u5c1a\u672a\u9009\u62e9\u8fb9\u3001\u5706\u6216\u9762</span>';
  document.getElementById('relations').innerHTML=relationOptions().map(x=>`<button data-relation="${x}" title="${x}">${relationLabels[x]||x}</button>`).join('');
  document.querySelectorAll('[data-relation]').forEach(button=>button.onclick=()=>{const relation=button.dataset.relation,movable=movableRef(selectedRefs),operation={op:'add_subobject_relation',relation,members:selectedRefs.map(referenceKey),...scopeFields(movable)};if(['collinear','equal_length','coincident','offset'].includes(relation))operation.preserve_policy=preservePolicy();if(relation==='offset')operation.offset=Number(document.getElementById('offsetValue').value||0);appendOperation(operation,selectedRefs);});
  populatePath();if(window.drawAicad3d)window.drawAicad3d();
}
function formalCorrection(){const refs=[...transactionRefs.values()],ids=[...new Set(refs.map(r=>r.source_object_id))].sort();return{schema_version:'1.0',source_sha256:pkg.source_sha256,correction:{id:'UI_CORR_001',description:'Exact semantic subobject correction drafted in synchronized review views',space:pkg.space,selected_ids:ids,selected_refs:refs,operations:[...operations]},root_cause:{status:'candidate',cause_class:'user_selected_subobject',explanation:'The selected exact semantic reference requires a bounded correction.'},prevention_rule:{status:'candidate',ruleEnabled:false,requirement:'Recheck the same typed invariant and exact reference after dependency replay.'},review_policy:{reviewOnly:true,accepted:false,ruleEnabled:false}};}
function renderDraft(){const payload={formal_correction:operations.length?formalCorrection():null,natural_language_notes:[...notes],status:operations.length?'ready_for_preview':'candidate_intent'};document.getElementById('draft').textContent=(operations.length||notes.length)?JSON.stringify(payload,null,2):'\u5c1a\u65e0\u7ea0\u9519\u610f\u56fe';}
document.querySelectorAll('.view-hit').forEach(x=>x.onclick=e=>{e.stopPropagation();toggleSelectionRef(pkg.selection_map[x.dataset.viewEntityId]);});
document.getElementById('addMove').onclick=()=>{if(selectedRefs.length!==1||!requireExact(selectedRefs))return;const r=selectedRefs[0],operation={op:'move_subobject',reference_key:referenceKey(r),axis:document.getElementById('moveAxis').value,value:Number(document.getElementById('moveValue').value),value_mode:document.getElementById('valueMode').value,preserve_policy:preservePolicy(),...scopeFields(r)};appendOperation(operation,[r]);};
document.getElementById('setParameter').onclick=()=>{if(selectedRefs.length!==1||!requireExact(selectedRefs))return;const r=selectedRefs[0],path=document.getElementById('parameterPath').value,raw=document.getElementById('parameterValue').value.trim();if(!path||!raw)return;const value=path==='profile.center'?raw.split(',').map(Number):Number(raw),operation={op:'set_subobject_parameter',reference_key:referenceKey(r),path,value,preserve_policy:preservePolicy(),...scopeFields(r)};appendOperation(operation,[r]);};
document.getElementById('addText').onclick=()=>{const t=document.getElementById('text'),value=t.value.trim();if(value){notes.push({text:value,selected_refs:selectedRefs.map(compactRef),status:'candidate_intent'});t.value='';renderDraft();}};
document.getElementById('download').onclick=()=>{const value=operations.length?formalCorrection():{schema_version:'1.0',source_sha256:pkg.source_sha256,natural_language_notes:notes,review_policy:{reviewOnly:true,accepted:false,ruleEnabled:false}},blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=operations.length?'aicad-subobject-correction.json':'aicad-correction-notes.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
if(typeof initAicad3dSelector==='function')initAicad3dSelector();render();renderDraft();
"""


def render_review_html(package: dict[str, Any]) -> str:
    from .review_ui_v2 import render_review_html_v2
    return render_review_html_v2(package, _selector_script() if package["space"] == "3d" else "")

class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.visible_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.visible_text.append(data)


def validate_review_html(review_html: str, space: str) -> list[str]:
    issues: list[str] = []
    suspicious = ("\ufffd", "\u951f", "\u704f", "\u95ab", "\u7470", "\u93b4", "\u942e", "\u7eeb")
    for marker in suspicious:
        if marker in review_html:
            issues.append(f"suspected_mojibake:{ord(marker):04x}")
    structural = ('<meta charset="utf-8">', 'lang="zh-CN"', '</title>', '</strong>', '</span>')
    for marker in structural:
        if marker not in review_html:
            issues.append(f"missing_html_marker:{marker}")
    parser = _VisibleTextParser()
    try:
        parser.feed(review_html)
        parser.close()
    except Exception as exc:
        issues.append(f"html_parse_error:{exc}")
    visible = "".join(parser.visible_text)
    required = ["\u5f53\u524d\u5bf9\u8c61", "\u51e0\u4f55\u6570\u503c", "\u5750\u6807\u7cfb", "\u6838\u5fc3\u53c2\u6570", "\u5bf9\u8c61\u5173\u7cfb", "\u4fee\u6539\u6e05\u5355"]
    if space == "3d":
        required.extend(["\u53ef\u65cb\u8f6c\u4e09\u7ef4\u9009\u62e9\u5668", "\u81ea\u7531\u622a\u9762", "\u4fef\u89c6\u56fe", "\u4e3b\u89c6\u56fe", "\u53f3\u89c6\u56fe"])
    for phrase in required:
        if phrase not in visible:
            issues.append(f"missing_visible_text:{phrase.encode('unicode_escape').decode('ascii')}")
    if 'id="measurement"' not in review_html or 'id="coordinateToggle"' not in review_html:
        issues.append("missing_measurement_or_coordinate_controls")
    if 'class="view-hit"' not in review_html or 'stroke-width:12' not in review_html:
        issues.append("missing_independent_hit_layer")
    if 'stroke-width:.8' not in review_html:
        issues.append("visible_line_not_precision_weight")
    return issues

def write_view_artifacts(package: dict[str, Any], output_dir: Path, stem: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.views.json"
    html_path = output_dir / f"{stem}.review.html"
    audit_path = output_dir / f"{stem}.views.audit.md"
    json_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_html = render_review_html(package)
    html_issues = validate_review_html(review_html, package["space"])
    if html_issues:
        raise PlanError("review HTML validation failed: " + "; ".join(html_issues))
    html_path.write_text(review_html, encoding="utf-8")
    rows = [
        f"# {stem} - AICAD multi-view audit", "",
        f"- Space/domain: `{package['space']}` / `{package['domain']}`",
        f"- Source SHA-256: `{package['source_sha256']}`", f"- View count: `{len(package['views'])}`",
        f"- Selection mappings: `{len(package['selection_map'])}`",
        f"- Model coordinate system: `{package['coordinate_system']['id']}` / `{package['coordinate_system']['handedness']}-handed` / `mm`",
        f"- Typed measurements: `{sum(1 for value in package['selection_map'].values() if value.get('measurement'))}` / `{len(package['selection_map'])}`",
        "- Coordinate display toggle: `present` (SVG views + 3D selector)",
        f"- Exact 3D selector subobjects: `{sum(len(item['subobjects']) for item in (package['selector_3d'] or {}).get('objects', []))}`",
        "- Review HTML UTF-8/mojibake gate: `pass`",
        "- Visible stroke / independent hit tolerance: `0.8px / 12px`",
        "- Native persistent topology authority: `false` (plan-derived semantic subobjects)", "",
        "| View | Kind | Geometry scope | Entities | Lost axis | Manufacturing authority |", "|---|---|---|---:|---|---|",
    ]
    for view in package["views"]:
        rows.append(f"| `{view['id']}` | `{view['kind']}` | `{view['geometry_scope']}` | {len(view['entities'])} | `{view['lost_axis']}` | `{view['manufacturing_authority']}` |")
    rows.extend(["", "Projection entities are review proxies with semantic back-references. Native host evidence remains required before production use."])
    audit_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"view_package": str(json_path.resolve()), "review_html": str(html_path.resolve()), "audit": str(audit_path.resolve())}


def build_multiview_review(data: dict[str, Any], space: str, domain: str, output_dir: Path, stem: str) -> dict[str, Any]:
    package = generate_view_package(data, space, domain)
    artifacts = write_view_artifacts(package, output_dir, stem)
    return {
        "ok": True, "status": "pass", "space": space, "domain": domain,
        "view_count": len(package["views"]), "selection_mapping_count": len(package["selection_map"]),
        "source_sha256": package["source_sha256"], "artifacts": artifacts,
        "review_policy": package["review_policy"], "limits": package["limits"],
    }
