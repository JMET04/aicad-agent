from __future__ import annotations

import copy
import math
import re
from typing import Any

from .engine import PlanError
from .engine3d import ResolvedFeature3D, compile_plan3d
from .viewmap import generate_view_package


NEW_SUBOBJECT_OPERATIONS = {
    "set_subobject_parameter",
    "move_subobject",
    "add_subobject_relation",
}

PRESERVE_POLICIES = {"keep_center", "keep_opposite", "keep_size", "keep_support"}
SCOPES = {"subobject", "feature", "shared_parameter_group", "detached_instance"}


def _feature_items(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in data.get("features", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _feature_order(data: dict[str, Any]) -> dict[str, int]:
    return {
        item["id"]: index
        for index, item in enumerate(data.get("features", []))
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _catalog(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    package = generate_view_package(data, "3d", "general")
    selector = package["selector_3d"]
    assert isinstance(selector, dict)
    return {
        row["reference_key"]: copy.deepcopy(row)
        for item in selector["objects"]
        for row in item["subobjects"]
    }


def validate_selected_refs(
    data: dict[str, Any], correction: dict[str, Any], source_sha256: str, supplied_sha256: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate exact selections against the current plan-derived reference catalog.

    Subobject corrections are rejected when the source hash or any semantic reference
    is stale.  Native host topology is intentionally not claimed by this catalog.
    """
    uses_subobjects = any(
        isinstance(operation, dict) and operation.get("op") in NEW_SUBOBJECT_OPERATIONS
        for operation in correction.get("operations", [])
    )
    if not uses_subobjects:
        return {}, {}
    if supplied_sha256 != source_sha256:
        raise PlanError("subobject correction source_sha256 is missing or stale")
    rows = correction.get("selected_refs")
    if not isinstance(rows, list) or not rows:
        raise PlanError("subobject correction requires non-empty correction.selected_refs")
    catalog = _catalog(data)
    selected: dict[str, dict[str, Any]] = {}
    exact_fields = ("source_object_id", "source_subobject", "geometry_type")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("reference_key"), str):
            raise PlanError(f"correction.selected_refs[{index}] requires reference_key")
        key = row["reference_key"]
        if key in selected:
            raise PlanError(f"duplicate selected subobject reference '{key}'")
        actual = catalog.get(key)
        if actual is None:
            raise PlanError(f"selected subobject reference '{key}' does not exist in the current plan")
        for field in exact_fields:
            if row.get(field) != actual.get(field):
                raise PlanError(f"selected subobject reference '{key}' has stale {field}")
        if "edit_paths" in row and row["edit_paths"] != actual["edit_paths"]:
            raise PlanError(f"selected subobject reference '{key}' has stale edit_paths")
        selected[key] = actual
    return catalog, selected


def _constraint(item: dict[str, Any], kind: str) -> dict[str, Any]:
    constraints = item.get("constraints")
    if not isinstance(constraints, list):
        raise PlanError(f"{item.get('id')}.constraints must be an array")
    matches = [row for row in constraints if isinstance(row, dict) and row.get("kind") == kind]
    if len(matches) != 1:
        raise PlanError(f"{item.get('id')} must declare exactly one {kind} constraint")
    return matches[0]


def _sync(item: dict[str, Any], path: str) -> None:
    if path == "depth":
        _constraint(item, "depth")["value"] = item["depth"]
    elif path == "profile.width":
        _constraint(item, "width")["value"] = item["profile"]["width"]
    elif path == "profile.height":
        _constraint(item, "height")["value"] = item["profile"]["height"]
    elif path == "profile.radius":
        _constraint(item, "radius")["value"] = item["profile"]["radius"]
    elif path == "profile.count":
        _constraint(item, "pattern_count")["value"] = item["profile"]["count"]
    elif path == "profile.bolt_circle_radius":
        _constraint(item, "bolt_circle_radius")["value"] = item["profile"]["bolt_circle_radius"]
    elif path == "profile.center":
        center = item["profile"]["center"]
        target = _constraint(item, "center_offset")
        target["dx"], target["dy"] = center


def _set_path(item: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor: Any = item
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise PlanError(f"parameter path '{path}' does not exist")
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        raise PlanError(f"parameter path '{path}' does not exist")
    cursor[parts[-1]] = copy.deepcopy(value)
    _sync(item, path)


def _locked(object_id: str, path: str, locks: list[str]) -> bool:
    full = f"{object_id}.{path}"
    return any(
        lock in {"*", object_id, f"{object_id}.*", full}
        or (lock.endswith(".*") and full.startswith(lock[:-1]))
        for lock in locks
    )


def _require_unlocked(object_id: str, paths: list[str], locks: list[str]) -> None:
    for path in paths:
        if _locked(object_id, path, locks):
            raise PlanError(f"correction would modify locked parameter {object_id}.{path}")


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PlanError(f"{label} must be greater than zero")
    return result


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PlanError(f"{label} must be finite")
    return result


def _validate_scope(metadata: dict[str, Any], operation: dict[str, Any]) -> None:
    scope = operation.get("scope")
    if scope not in SCOPES:
        raise PlanError("subobject operation requires an explicit valid scope")
    if scope == "detached_instance":
        if not metadata.get("detach_supported", False):
            raise PlanError("detached_instance is unsupported for this semantic reference")
        raise PlanError("detached_instance is not implemented by the current 3D plan compiler")
    expected = operation.get("expected_affected_instance_count")
    actual = int(metadata.get("affected_instance_count", 1))
    if expected != actual:
        raise PlanError(f"expected_affected_instance_count must equal current value {actual}")
    groups = metadata.get("shared_parameter_groups", [])
    if metadata.get("edit_scope") == "shared_pattern_parameter":
        if scope != "shared_parameter_group":
            raise PlanError("pattern-instance correction requires scope=shared_parameter_group")
        if operation.get("expected_shared_parameter_groups") != groups:
            raise PlanError("expected_shared_parameter_groups is missing or stale")
    elif scope == "shared_parameter_group":
        raise PlanError("shared_parameter_group scope is only valid for shared pattern parameters")


def _resolve_ref(
    key: Any, catalog: dict[str, dict[str, Any]], selected: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(key, str) or key not in selected:
        raise PlanError("subobject operation reference_key must be present in correction.selected_refs")
    metadata = catalog.get(key)
    if metadata is None:
        raise PlanError(f"subobject reference '{key}' is stale")
    return metadata


def _rectangle_side(source_subobject: str, axis: str | None = None) -> tuple[str, float, int]:
    """Return (axis, side_sign, index) for a parameterized rectangle boundary."""
    patterns = (
        r"^profile\.edge\.(\d+)$",
        r"^feature\.edge\.opposite\.(\d+)$",
        r"^feature\.face\.side\.(\d+)$",
        r"^feature\.edge\.vertical\.(\d+)$",
    )
    match = next((re.match(pattern, source_subobject) for pattern in patterns if re.match(pattern, source_subobject)), None)
    if match is None:
        raise PlanError(f"'{source_subobject}' is not a parameterized rectangle boundary")
    index = int(match.group(1))
    if not 1 <= index <= 4:
        raise PlanError("rectangle boundary index must be 1 through 4")
    if ".vertical." in source_subobject:
        if axis not in {"x", "y"}:
            raise PlanError("vertical edge movement requires explicit axis x or y")
        if axis == "x":
            return axis, -1.0 if index in {1, 4} else 1.0, index
        return axis, -1.0 if index in {1, 2} else 1.0, index
    expected_axis = "y" if index in {1, 3} else "x"
    if axis is not None and axis != expected_axis:
        raise PlanError(f"rectangle boundary {source_subobject} can move only on axis {expected_axis}")
    sign = -1.0 if index in {1, 4} else 1.0
    return expected_axis, sign, index


def _rectangle_length_axis(source_subobject: str) -> str:
    axis, _sign, _index = _rectangle_side(source_subobject)
    return "x" if axis == "y" else "y"


def _rectangle_parameter(item: dict[str, Any], axis: str) -> tuple[int, str, float, float]:
    profile = item.get("profile")
    if not isinstance(profile, dict) or profile.get("kind") != "center_rectangle":
        raise PlanError("selected boundary is not backed by a center_rectangle profile")
    center_index = 0 if axis == "x" else 1
    size_name = "width" if axis == "x" else "height"
    center = float(profile["center"][center_index])
    size = float(profile[size_name])
    return center_index, f"profile.{size_name}", center, size


def _move_rectangle_boundary(
    item: dict[str, Any], source_subobject: str, axis: str | None, target: float,
    preserve_policy: Any, locks: list[str],
) -> dict[str, Any]:
    resolved_axis, sign, index = _rectangle_side(source_subobject, axis)
    center_index, size_path, center, size = _rectangle_parameter(item, resolved_axis)
    current = center + sign * size / 2.0
    if preserve_policy == "keep_center":
        new_size = 2.0 * sign * (target - center)
        new_center = center
    elif preserve_policy == "keep_opposite":
        opposite = center - sign * size / 2.0
        new_size = sign * (target - opposite)
        new_center = (target + opposite) / 2.0
    elif preserve_policy == "keep_size":
        new_size = size
        new_center = target - sign * size / 2.0
    else:
        raise PlanError("rectangle boundary movement requires keep_center, keep_opposite, or keep_size")
    if new_size <= 0:
        raise PlanError("rectangle boundary movement would invert or collapse the profile")
    changed_paths = [size_path] if preserve_policy == "keep_center" else ["profile.center"]
    if preserve_policy == "keep_opposite":
        changed_paths.append(size_path)
    _require_unlocked(item["id"], changed_paths, locks)
    item["profile"][size_path.split(".")[-1]] = new_size
    item["profile"]["center"][center_index] = new_center
    _sync(item, size_path)
    _sync(item, "profile.center")
    return {
        "axis": resolved_axis, "boundary_index": index, "old_coordinate": current,
        "new_coordinate": target, "old_size": size, "new_size": new_size,
        "old_center": center, "new_center": new_center,
        "changed_paths": changed_paths,
    }


def _depth_plane(feature: ResolvedFeature3D, source_subobject: str) -> tuple[float, float] | None:
    opposite = bool(
        re.match(r"^feature\.(face|edge)\.opposite(?:\.\d+)?$", source_subobject)
        or re.match(r"^feature\.circle\.opposite\.\d+$", source_subobject)
    )
    if not opposite:
        return None
    if feature.type == "cut_extrude":
        if feature.end_condition == "through_all":
            raise PlanError("through_all opposite topology is body-derived and cannot set a blind depth")
        return feature.support_top_z - feature.depth, -1.0
    return feature.support_top_z + feature.depth, 1.0


def _move_depth_plane(
    item: dict[str, Any], feature: ResolvedFeature3D, source_subobject: str,
    target: float, preserve_policy: Any, locks: list[str],
) -> dict[str, Any]:
    plane = _depth_plane(feature, source_subobject)
    if plane is None:
        raise PlanError("the selected subobject has no independently movable depth plane")
    if preserve_policy != "keep_support":
        raise PlanError("depth-plane movement requires preserve_policy=keep_support")
    current, direction = plane
    new_depth = direction * (target - feature.support_top_z)
    if new_depth <= 0:
        raise PlanError("depth-plane movement would invert or collapse the extrusion")
    _require_unlocked(item["id"], ["depth"], locks)
    item["depth"] = new_depth
    _sync(item, "depth")
    return {
        "axis": "z", "old_coordinate": current, "new_coordinate": target,
        "support_coordinate": feature.support_top_z, "old_depth": feature.depth,
        "new_depth": new_depth, "changed_paths": ["depth"],
    }


def _scope_evidence(metadata: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": operation["scope"],
        "edit_scope": metadata["edit_scope"],
        "affected_instance_count": metadata["affected_instance_count"],
        "shared_parameter_groups": metadata["shared_parameter_groups"],
        "detach_supported": metadata["detach_supported"],
    }


def _set_subobject_parameter(
    data: dict[str, Any], operation: dict[str, Any], metadata: dict[str, Any], locks: list[str],
) -> tuple[set[str], dict[str, Any]]:
    _validate_scope(metadata, operation)
    object_id = metadata["source_object_id"]
    item = _feature_items(data).get(object_id)
    if item is None:
        raise PlanError(f"subobject feature '{object_id}' does not exist")
    path = operation.get("path")
    if path not in metadata["edit_paths"]:
        raise PlanError(f"parameter path '{path}' is not editable through {metadata['reference_key']}")
    preserve = operation.get("preserve_policy")
    if path in {"profile.width", "profile.height"} and metadata.get("requires_preserve_policy"):
        expected_axis = "x" if path.endswith("width") else "y"
        _axis, _sign, _index = _rectangle_side(metadata["source_subobject"], expected_axis)
        new_size = _positive_number(operation.get("value"), path)
        if preserve == "keep_center":
            _require_unlocked(object_id, [path], locks)
            _set_path(item, path, new_size)
            details = {"old_center_preserved": True, "changed_paths": [path]}
        elif preserve == "keep_opposite":
            _center_index, _size_path, center, old_size = _rectangle_parameter(item, expected_axis)
            _axis, sign, _index = _rectangle_side(metadata["source_subobject"], expected_axis)
            old_selected = center + sign * old_size / 2.0
            new_selected = center - sign * old_size / 2.0 + sign * new_size
            details = _move_rectangle_boundary(item, metadata["source_subobject"], expected_axis, new_selected, preserve, locks)
            details["old_selected_coordinate"] = old_selected
        elif preserve == "keep_size":
            raise PlanError("keep_size conflicts with setting a rectangle size; use move_subobject")
        else:
            raise PlanError("rectangle size correction requires keep_center or keep_opposite")
    elif path == "depth" and metadata.get("requires_preserve_policy"):
        if preserve != "keep_support":
            raise PlanError("depth correction through a derived edge requires keep_support")
        _require_unlocked(object_id, [path], locks)
        _set_path(item, path, _positive_number(operation.get("value"), path))
        details = {"support_preserved": True, "changed_paths": [path]}
    else:
        if metadata.get("requires_preserve_policy") and preserve not in PRESERVE_POLICIES:
            raise PlanError("selected subobject requires an explicit preserve_policy")
        _require_unlocked(object_id, [path], locks)
        _set_path(item, path, operation.get("value"))
        details = {"changed_paths": [path]}
    return {object_id}, {
        "op": operation["op"], "reference_key": metadata["reference_key"],
        "source_object_id": object_id, "source_subobject": metadata["source_subobject"],
        "path": path, "preserve_policy": preserve, **_scope_evidence(metadata, operation), **details,
    }


def _move_subobject(
    data: dict[str, Any], operation: dict[str, Any], metadata: dict[str, Any], locks: list[str],
) -> tuple[set[str], dict[str, Any]]:
    _validate_scope(metadata, operation)
    if metadata["geometry_type"] not in {"line", "face"}:
        raise PlanError("move_subobject requires a selected line or face")
    object_id = metadata["source_object_id"]
    item = _feature_items(data).get(object_id)
    if item is None:
        raise PlanError(f"subobject feature '{object_id}' does not exist")
    compiled = {feature.id: feature for feature in compile_plan3d(data).features}
    feature = compiled[object_id]
    axis = operation.get("axis")
    if axis not in {"x", "y", "z"}:
        raise PlanError("move_subobject.axis must be x, y, or z")
    value = _number(operation.get("value"), "move_subobject.value")
    mode = operation.get("value_mode", "absolute")
    if mode not in {"absolute", "delta"}:
        raise PlanError("move_subobject.value_mode must be absolute or delta")
    source_subobject = metadata["source_subobject"]
    if axis in {"x", "y"}:
        resolved_axis, sign, _index = _rectangle_side(source_subobject, axis)
        _center_index, _size_path, center, size = _rectangle_parameter(item, resolved_axis)
        current = center + sign * size / 2.0
        target = value if mode == "absolute" else current + value
        details = _move_rectangle_boundary(item, source_subobject, axis, target, operation.get("preserve_policy"), locks)
    else:
        plane = _depth_plane(feature, source_subobject)
        if plane is None:
            raise PlanError("selected subobject cannot move independently on z")
        current = plane[0]
        target = value if mode == "absolute" else current + value
        details = _move_depth_plane(item, feature, source_subobject, target, operation.get("preserve_policy"), locks)
    return {object_id}, {
        "op": operation["op"], "reference_key": metadata["reference_key"],
        "source_object_id": object_id, "source_subobject": source_subobject,
        "value_mode": mode, "requested_value": value,
        "preserve_policy": operation.get("preserve_policy"),
        **_scope_evidence(metadata, operation), **details,
    }


def _circle_center(feature: ResolvedFeature3D, source_subobject: str) -> tuple[float, float]:
    match = re.search(r"\.(\d+)$", source_subobject)
    if match is None:
        return feature.profile.center
    index = int(match.group(1)) - 1
    if not 0 <= index < len(feature.profile.primitives):
        raise PlanError("circle subobject index is stale")
    return feature.profile.primitives[index].center


def _face_axis_coordinate(feature: ResolvedFeature3D, source_subobject: str) -> tuple[str, float] | None:
    match = re.match(r"^feature\.face\.side\.(\d+)$", source_subobject)
    if match is not None:
        index = int(match.group(1))
        axis, sign, _ = _rectangle_side(source_subobject)
        center = feature.profile.center[0 if axis == "x" else 1]
        size = feature.profile.width if axis == "x" else feature.profile.height
        assert size is not None
        return axis, center + sign * size / 2.0
    if source_subobject == "profile.face" or re.match(r"^profile\.face\.\d+$", source_subobject):
        return "z", feature.support_top_z
    plane = _depth_plane(feature, source_subobject)
    if plane is not None:
        return "z", plane[0]
    return None


def _line_axis_length(feature: ResolvedFeature3D, source_subobject: str) -> tuple[str, float]:
    length_axis = _rectangle_length_axis(source_subobject)
    length = feature.profile.width if length_axis == "x" else feature.profile.height
    if length is None:
        raise PlanError("line relation requires rectangle profile edges")
    return length_axis, float(length)


def _relation_scope(operation: dict[str, Any], movable: dict[str, Any]) -> None:
    scoped = dict(operation)
    scoped.setdefault("scope", "feature")
    scoped.setdefault("expected_affected_instance_count", movable.get("affected_instance_count", 1))
    if movable.get("edit_scope") == "shared_pattern_parameter":
        scoped.setdefault("scope", "shared_parameter_group")
        scoped.setdefault("expected_shared_parameter_groups", movable.get("shared_parameter_groups", []))
    _validate_scope(movable, scoped)


def _add_subobject_relation(
    data: dict[str, Any], operation: dict[str, Any], refs: list[dict[str, Any]], locks: list[str],
) -> tuple[set[str], dict[str, Any]]:
    relation = operation.get("relation")
    if relation not in {"parallel", "perpendicular", "collinear", "equal_length", "concentric", "equal_radius", "coincident", "offset"}:
        raise PlanError(f"unsupported subobject relation '{relation}'")
    if refs[0]["reference_key"] == refs[1]["reference_key"]:
        raise PlanError("add_subobject_relation requires two distinct exact references")
    if refs[0]["geometry_type"] != refs[1]["geometry_type"]:
        raise PlanError("subobject relation members must have matching geometry types")
    order = _feature_order(data)
    fixed, movable = sorted(refs, key=lambda row: (order[row["source_object_id"]], row["reference_key"]))
    _relation_scope(operation, movable)
    plan = compile_plan3d(data)
    compiled = {feature.id: feature for feature in plan.features}
    items = _feature_items(data)
    fixed_feature = compiled[fixed["source_object_id"]]
    movable_feature = compiled[movable["source_object_id"]]
    movable_item = items[movable_feature.id]
    changed: set[str] = set()
    details: dict[str, Any] = {}
    geometry_type = fixed["geometry_type"]

    if geometry_type == "circle":
        if relation not in {"concentric", "equal_radius"}:
            raise PlanError(f"circle subobjects do not support relation '{relation}'")
        if relation == "equal_radius":
            if fixed_feature.profile.radius is None or movable_feature.profile.radius is None:
                raise PlanError("equal_radius requires circular profiles")
            old = movable_feature.profile.radius
            if math.isclose(old, fixed_feature.profile.radius, rel_tol=0.0, abs_tol=1e-12):
                details = {"status": "already_satisfied", "changed_paths": [], "old_radius": old, "new_radius": fixed_feature.profile.radius}
            else:
                _require_unlocked(movable_feature.id, ["profile.radius"], locks)
                _set_path(movable_item, "profile.radius", fixed_feature.profile.radius)
                details = {"changed_paths": ["profile.radius"], "old_radius": old, "new_radius": fixed_feature.profile.radius}
                changed.add(movable_feature.id)
        else:
            fixed_center = _circle_center(fixed_feature, fixed["source_subobject"])
            movable_center = _circle_center(movable_feature, movable["source_subobject"])
            if all(math.isclose(a, b, rel_tol=0.0, abs_tol=1e-12) for a, b in zip(fixed_center, movable_center)):
                details = {"status": "already_satisfied", "changed_paths": [], "old_selected_center": list(movable_center), "new_selected_center": list(fixed_center)}
            else:
                feature_center = movable_feature.profile.center
                new_center = [feature_center[0] + fixed_center[0] - movable_center[0], feature_center[1] + fixed_center[1] - movable_center[1]]
                _require_unlocked(movable_feature.id, ["profile.center"], locks)
                _set_path(movable_item, "profile.center", new_center)
                details = {"changed_paths": ["profile.center"], "old_selected_center": list(movable_center), "new_selected_center": list(fixed_center)}
                changed.add(movable_feature.id)
    elif geometry_type == "point":
        if relation != "coincident":
            raise PlanError(f"point subobjects do not support relation '{relation}'")
        fixed_center = list(fixed_feature.profile.center)
        movable_center = list(movable_feature.profile.center)
        if all(math.isclose(a, b, rel_tol=0.0, abs_tol=1e-12) for a, b in zip(fixed_center, movable_center)):
            details = {"status": "already_satisfied", "changed_paths": [], "old_center": movable_center, "new_center": fixed_center}
        else:
            _require_unlocked(movable_feature.id, ["profile.center"], locks)
            _set_path(movable_item, "profile.center", fixed_center)
            details = {"changed_paths": ["profile.center"], "old_center": movable_center, "new_center": fixed_center}
            changed.add(movable_feature.id)
    elif geometry_type == "line":
        if relation not in {"parallel", "perpendicular", "collinear", "equal_length"}:
            raise PlanError(f"line subobjects do not support relation '{relation}'")
        fixed_axis, fixed_length = _line_axis_length(fixed_feature, fixed["source_subobject"])
        movable_axis, movable_length = _line_axis_length(movable_feature, movable["source_subobject"])
        satisfied = (fixed_axis == movable_axis) if relation == "parallel" else (fixed_axis != movable_axis)
        if relation in {"parallel", "perpendicular"}:
            if not satisfied:
                raise PlanError(f"{relation} requires a rotation parameter not present in the current profile model")
            details = {"status": "already_satisfied_by_axis_aligned_profile", "changed_paths": []}
        elif relation == "collinear":
            if fixed_axis != movable_axis:
                raise PlanError("collinear requires parallel rectangle edges")
            axis, _sign, _index = _rectangle_side(fixed["source_subobject"])
            _center_index, _size_path, fixed_center, fixed_size = _rectangle_parameter(items[fixed_feature.id], axis)
            _axis, fixed_sign, _ = _rectangle_side(fixed["source_subobject"], axis)
            coordinate = fixed_center + fixed_sign * fixed_size / 2.0
            details = _move_rectangle_boundary(
                movable_item, movable["source_subobject"], axis, coordinate,
                operation.get("preserve_policy"), locks,
            )
            changed.add(movable_feature.id)
        else:
            size_path = "profile.width" if movable_axis == "x" else "profile.height"
            preserve = operation.get("preserve_policy")
            if preserve not in {"keep_center", "keep_opposite"}:
                raise PlanError("equal_length requires keep_center or keep_opposite")
            if preserve == "keep_center":
                _require_unlocked(movable_feature.id, [size_path], locks)
                _set_path(movable_item, size_path, fixed_length)
                details = {"old_length": movable_length, "new_length": fixed_length, "changed_paths": [size_path]}
            else:
                normal_axis, sign, _ = _rectangle_side(movable["source_subobject"])
                _ci, _sp, center, normal_size = _rectangle_parameter(movable_item, normal_axis)
                coordinate = center + sign * normal_size / 2.0
                length_size_path = "profile.width" if movable_axis == "x" else "profile.height"
                _require_unlocked(movable_feature.id, [length_size_path], locks)
                _set_path(movable_item, length_size_path, fixed_length)
                details = {
                    "old_length": movable_length, "new_length": fixed_length,
                    "selected_boundary_coordinate_preserved": coordinate,
                    "changed_paths": [length_size_path],
                }
            changed.add(movable_feature.id)
    else:
        if relation not in {"parallel", "perpendicular", "coincident", "offset"}:
            raise PlanError(f"face subobjects do not support relation '{relation}'")
        fixed_plane = _face_axis_coordinate(fixed_feature, fixed["source_subobject"])
        movable_plane = _face_axis_coordinate(movable_feature, movable["source_subobject"])
        if fixed_plane is None or movable_plane is None:
            raise PlanError("relation requires planar parameterized faces")
        fixed_axis, fixed_coordinate = fixed_plane
        movable_axis, movable_coordinate = movable_plane
        if relation in {"parallel", "perpendicular"}:
            satisfied = (fixed_axis == movable_axis) if relation == "parallel" else (fixed_axis != movable_axis)
            if not satisfied:
                raise PlanError(f"selected faces are not {relation} and no rotation parameter exists")
            details = {"status": "already_satisfied_by_axis_aligned_profile", "changed_paths": []}
        else:
            if fixed_axis != movable_axis:
                raise PlanError(f"{relation} requires parallel planar faces")
            offset = 0.0 if relation == "coincident" else _number(operation.get("offset"), "relation offset")
            target = fixed_coordinate + offset
            if movable_axis in {"x", "y"}:
                details = _move_rectangle_boundary(
                    movable_item, movable["source_subobject"], movable_axis, target,
                    operation.get("preserve_policy"), locks,
                )
            else:
                details = _move_depth_plane(
                    movable_item, movable_feature, movable["source_subobject"], target,
                    operation.get("preserve_policy"), locks,
                )
            details.update({"fixed_coordinate": fixed_coordinate, "requested_offset": offset})
            changed.add(movable_feature.id)
    return changed, {
        "op": operation["op"], "relation": relation,
        "members": [fixed["reference_key"], movable["reference_key"]],
        "fixed_reference_key": fixed["reference_key"], "movable_reference_key": movable["reference_key"],
        "source_object_id": movable["source_object_id"],
        "preserve_policy": operation.get("preserve_policy"),
        **_scope_evidence(movable, {
            **operation,
            "scope": operation.get("scope", "shared_parameter_group" if movable.get("edit_scope") == "shared_pattern_parameter" else "feature"),
        }),
        **details,
    }


def apply_subobject_operation(
    data: dict[str, Any], operation: dict[str, Any], catalog: dict[str, dict[str, Any]],
    selected: dict[str, dict[str, Any]], locks: list[str],
) -> tuple[set[str], dict[str, Any]]:
    kind = operation.get("op")
    if kind not in NEW_SUBOBJECT_OPERATIONS:
        raise PlanError(f"unsupported subobject operation '{kind}'")
    if kind == "add_subobject_relation":
        members = operation.get("members")
        if not isinstance(members, list) or len(members) != 2:
            raise PlanError("add_subobject_relation requires exactly two reference keys")
        refs = [_resolve_ref(key, catalog, selected) for key in members]
        return _add_subobject_relation(data, operation, refs, locks)
    metadata = _resolve_ref(operation.get("reference_key"), catalog, selected)
    if kind == "set_subobject_parameter":
        return _set_subobject_parameter(data, operation, metadata, locks)
    return _move_subobject(data, operation, metadata, locks)
