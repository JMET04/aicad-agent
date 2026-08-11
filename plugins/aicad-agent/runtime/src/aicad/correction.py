from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .engine import PlanError, ResolvedArc, ResolvedCircle, ResolvedLine, compile_plan
from .engine3d import compile_plan3d
from .semantic import describe_plan, semantic_from_plan
from .subobject_correction import (
    NEW_SUBOBJECT_OPERATIONS,
    apply_subobject_operation,
    validate_selected_refs,
)


SUPPORTED_OPERATIONS = {
    "set_parameter", "add_constraint", "remove_constraint", "add_relation",
    "replace_dependency", "insert_object", "remove_object",
} | NEW_SUBOBJECT_OPERATIONS


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compile(data: dict[str, Any], space: str) -> Any:
    return compile_plan(data) if space == "2d" else compile_plan3d(data)


def _collection(data: dict[str, Any], space: str) -> list[dict[str, Any]]:
    key = "steps" if space == "2d" else "features"
    value = data.get(key)
    if not isinstance(value, list):
        raise PlanError(f"plan.{key} must be an array")
    return value


def _index(data: dict[str, Any], space: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(_collection(data, space)):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise PlanError(f"plan object at index {index} has no ID")
        result[item["id"]] = item
    return result


def _target(data: dict[str, Any], space: str, object_id: Any) -> dict[str, Any]:
    if not isinstance(object_id, str):
        raise PlanError("correction target must be an object ID")
    item = _index(data, space).get(object_id)
    if item is None:
        raise PlanError(f"correction target '{object_id}' does not exist")
    if item.get("editable", True) is False:
        raise PlanError(f"correction target '{object_id}' is read-only")
    return item


def _path_parts(path: Any) -> list[str]:
    if not isinstance(path, str) or not path or path.startswith(".") or path.endswith("."):
        raise PlanError("parameter path must be a non-empty dotted path")
    parts = path.split(".")
    if any(not part.replace("_", "").isalnum() for part in parts):
        raise PlanError(f"unsafe parameter path '{path}'")
    return parts


def _set_path(item: dict[str, Any], path: str, value: Any) -> None:
    parts = _path_parts(path)
    cursor: Any = item
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise PlanError(f"parameter path '{path}' does not exist")
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        raise PlanError(f"parameter path '{path}' does not exist")
    cursor[parts[-1]] = copy.deepcopy(value)


def _is_locked(object_id: str, path: str, locks: list[str]) -> bool:
    full = f"{object_id}.{path}"
    for lock in locks:
        if lock == "*" or lock == object_id or lock == f"{object_id}.*" or lock == full:
            return True
        if lock.endswith(".*") and full.startswith(lock[:-1]):
            return True
    return False


def _constraint(item: dict[str, Any], kind: str) -> dict[str, Any] | None:
    constraints = item.get("constraints")
    if not isinstance(constraints, list):
        return None
    return next((value for value in constraints if isinstance(value, dict) and value.get("kind") == kind), None)


def _replace_constraint(item: dict[str, Any], kinds: set[str], value: dict[str, Any]) -> None:
    constraints = item.setdefault("constraints", [])
    if not isinstance(constraints, list):
        raise PlanError(f"{item.get('id')}.constraints must be an array")
    first = next((index for index, entry in enumerate(constraints) if isinstance(entry, dict) and entry.get("kind") in kinds), None)
    constraints[:] = [entry for entry in constraints if not (isinstance(entry, dict) and entry.get("kind") in kinds)]
    constraints.insert(first if first is not None else len(constraints), value)


def _sync_2d(item: dict[str, Any], path: str) -> None:
    if path == "radius":
        radius = float(item["radius"])
        existing = _constraint(item, "diameter")
        if existing is not None:
            existing["value"] = radius * 2.0
        else:
            target = _constraint(item, "radius")
            if target is not None:
                target["value"] = radius
    elif path == "construction.length":
        target = _constraint(item, "length")
        if target is not None:
            target["value"] = item["construction"]["length"]
    elif path in {"start_angle_deg", "end_angle_deg"}:
        kind = "start_angle" if path.startswith("start") else "end_angle"
        target = _constraint(item, kind)
        if target is not None:
            target["value"] = item[path]


def _sync_3d(item: dict[str, Any], path: str) -> None:
    mapping = {
        "depth": "depth", "profile.width": "width", "profile.height": "height",
        "profile.radius": "radius", "profile.count": "pattern_count",
        "profile.bolt_circle_radius": "bolt_circle_radius",
    }
    kind = mapping.get(path)
    if kind is not None:
        target = _constraint(item, kind)
        if target is not None:
            cursor: Any = item
            for part in path.split("."):
                cursor = cursor[part]
            target["value"] = cursor
    elif path == "profile.center":
        center = item["profile"]["center"]
        target = _constraint(item, "center_offset")
        if target is not None:
            target["dx"], target["dy"] = center


def _set_parameter(data: dict[str, Any], space: str, operation: dict[str, Any], locks: list[str]) -> str:
    object_id = operation.get("target")
    path = operation.get("path")
    if not isinstance(object_id, str) or not isinstance(path, str):
        raise PlanError("set_parameter requires target and path")
    if _is_locked(object_id, path, locks):
        raise PlanError(f"correction would modify locked parameter {object_id}.{path}")
    item = _target(data, space, object_id)
    _set_path(item, path, operation.get("value"))
    (_sync_2d if space == "2d" else _sync_3d)(item, path)
    return object_id


def _line_angle(line: ResolvedLine) -> float:
    return math.atan2(line.vector[1], line.vector[0])


def _add_relation_2d(data: dict[str, Any], operation: dict[str, Any], locks: list[str]) -> str:
    relation = operation.get("relation")
    members = operation.get("members")
    if relation not in {"parallel", "perpendicular", "collinear", "concentric", "equal_radius", "equal_length"}:
        raise PlanError(f"unsupported 2D correction relation '{relation}'")
    if not isinstance(members, list) or len(members) != 2 or members[0] == members[1]:
        raise PlanError("add_relation requires two distinct members")
    compiled = compile_plan(data)
    order = {entity.id: index for index, entity in enumerate(compiled.entities)}
    if any(member not in order for member in members):
        raise PlanError("add_relation members must exist")
    fixed, movable = sorted(members, key=order.get)
    fixed_entity = compiled.entities[order[fixed]]
    movable_entity = compiled.entities[order[movable]]
    item = _target(data, "2d", movable)
    if relation in {"parallel", "perpendicular", "collinear", "equal_length"}:
        if not isinstance(fixed_entity, ResolvedLine) or not isinstance(movable_entity, ResolvedLine):
            raise PlanError(f"{relation} requires two lines")
        if _is_locked(movable, "construction", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.construction")
        if relation == "collinear":
            if _is_locked(movable, "start", locks) or _is_locked(movable, "construction", locks):
                raise PlanError(f"correction would modify locked line placement {movable}")
            ux, uy = fixed_entity.vector[0] / fixed_entity.length, fixed_entity.vector[1] / fixed_entity.length
            offset_x = movable_entity.start[0] - fixed_entity.start[0]
            offset_y = movable_entity.start[1] - fixed_entity.start[1]
            along = offset_x * ux + offset_y * uy
            projected = [fixed_entity.start[0] + along * ux, fixed_entity.start[1] + along * uy]
            same_angle, opposite_angle = _line_angle(fixed_entity), _line_angle(fixed_entity) + math.pi
            chosen = min((same_angle, opposite_angle), key=lambda value: abs(math.atan2(math.sin(value - _line_angle(movable_entity)), math.cos(value - _line_angle(movable_entity)))))
            direction = "same" if chosen == same_angle else "opposite"
            item["start"] = {"point": projected}
            item["construction"] = {"kind": "parallel", "to": fixed, "length": movable_entity.length, "direction": direction}
            _replace_constraint(item, {"start_coincident", "start_offset"}, {"kind": "start_offset", "target": f"{fixed}.start", "dx": projected[0] - fixed_entity.start[0], "dy": projected[1] - fixed_entity.start[1]})
            _replace_constraint(item, {"parallel", "perpendicular", "collinear"}, {"kind": "collinear", "target": fixed})
            if _constraint(item, "length") is None:
                item.setdefault("constraints", []).append({"kind": "length", "value": movable_entity.length})
        elif relation == "equal_length":
            angle = _line_angle(movable_entity)
            item["construction"] = {"kind": "polar", "length": fixed_entity.length, "angle_deg": math.degrees(angle)}
            _replace_constraint(item, {"length"}, {"kind": "length", "value": fixed_entity.length})
        else:
            if relation == "parallel":
                same_angle, opposite_angle = _line_angle(fixed_entity), _line_angle(fixed_entity) + math.pi
                chosen = min((same_angle, opposite_angle), key=lambda value: abs(math.atan2(math.sin(value - _line_angle(movable_entity)), math.cos(value - _line_angle(movable_entity)))))
                direction = "same" if chosen == same_angle else "opposite"
                item["construction"] = {"kind": "parallel", "to": fixed, "length": movable_entity.length, "direction": direction}
            else:
                left, right = _line_angle(fixed_entity) + math.pi / 2, _line_angle(fixed_entity) - math.pi / 2
                chosen = min((left, right), key=lambda value: abs(math.atan2(math.sin(value - _line_angle(movable_entity)), math.cos(value - _line_angle(movable_entity)))))
                turn = "left" if chosen == left else "right"
                item["construction"] = {"kind": "perpendicular", "to": fixed, "length": movable_entity.length, "turn": turn}
            _replace_constraint(item, {"parallel", "perpendicular", "collinear"}, {"kind": relation, "target": fixed})
            if _constraint(item, "length") is None:
                item.setdefault("constraints", []).append({"kind": "length", "value": movable_entity.length})
    elif relation == "concentric":
        if not isinstance(fixed_entity, (ResolvedCircle, ResolvedArc)) or not isinstance(movable_entity, (ResolvedCircle, ResolvedArc)):
            raise PlanError("concentric requires two circles/arcs")
        if _is_locked(movable, "center", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.center")
        item["center"] = {"ref": f"{fixed}.center"}
        _replace_constraint(item, {"center_offset", "center_coincident"}, {"kind": "center_coincident", "target": f"{fixed}.center"})
    else:
        if not isinstance(fixed_entity, (ResolvedCircle, ResolvedArc)) or not isinstance(movable_entity, (ResolvedCircle, ResolvedArc)):
            raise PlanError("equal_radius requires two circles/arcs")
        if _is_locked(movable, "radius", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.radius")
        item["radius"] = fixed_entity.radius
        _replace_constraint(item, {"radius", "diameter"}, {"kind": "radius", "value": fixed_entity.radius})
    return movable


def _feature_index(plan: Any) -> dict[str, Any]:
    return {feature.id: feature for feature in plan.features}


def _add_relation_3d(data: dict[str, Any], operation: dict[str, Any], locks: list[str]) -> str:
    relation = operation.get("relation")
    members = operation.get("members")
    if relation not in {"concentric", "equal_radius", "equal_depth", "support_coincident"}:
        raise PlanError(f"unsupported 3D correction relation '{relation}'")
    if not isinstance(members, list) or len(members) != 2 or members[0] == members[1]:
        raise PlanError("add_relation requires two distinct members")
    plan = compile_plan3d(data)
    order = {feature.id: index for index, feature in enumerate(plan.features)}
    if any(member not in order for member in members):
        raise PlanError("add_relation members must exist")
    fixed, movable = sorted(members, key=order.get)
    by_id = _feature_index(plan)
    fixed_feature, movable_feature = by_id[fixed], by_id[movable]
    item = _target(data, "3d", movable)
    if relation == "concentric":
        if _is_locked(movable, "profile.center", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.profile.center")
        item["profile"]["center"] = list(fixed_feature.profile.center)
        _sync_3d(item, "profile.center")
    elif relation == "equal_radius":
        if fixed_feature.profile.radius is None or movable_feature.profile.radius is None:
            raise PlanError("equal_radius requires circular profiles")
        if _is_locked(movable, "profile.radius", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.profile.radius")
        item["profile"]["radius"] = fixed_feature.profile.radius
        _sync_3d(item, "profile.radius")
    elif relation == "equal_depth":
        if _is_locked(movable, "depth", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.depth")
        item["depth"] = fixed_feature.depth
        _sync_3d(item, "depth")
    else:
        if fixed_feature.type not in {"base_extrude", "boss_extrude"}:
            raise PlanError("support_coincident target must be an additive feature")
        if _is_locked(movable, "support_feature", locks):
            raise PlanError(f"correction would modify locked parameter {movable}.support_feature")
        dependencies = list(item.get("depends_on", []))
        if fixed not in dependencies:
            dependencies.append(fixed)
        item["depends_on"] = dependencies
        item["support_feature"] = fixed
        _replace_constraint(item, {"support_coincident"}, {"kind": "support_coincident", "target": fixed})
    return movable


def _apply_operation(data: dict[str, Any], space: str, operation: dict[str, Any], locks: list[str]) -> str:
    kind = operation.get("op")
    if kind not in SUPPORTED_OPERATIONS:
        raise PlanError(f"unsupported correction operation '{kind}'")
    if kind == "set_parameter":
        return _set_parameter(data, space, operation, locks)
    if kind == "add_relation":
        return (_add_relation_2d if space == "2d" else _add_relation_3d)(data, operation, locks)
    if kind in {"add_constraint", "remove_constraint"}:
        object_id = operation.get("target")
        item = _target(data, space, object_id)
        if _is_locked(str(object_id), "constraints", locks):
            raise PlanError(f"correction would modify locked parameter {object_id}.constraints")
        constraints = item.setdefault("constraints", [])
        if not isinstance(constraints, list):
            raise PlanError(f"{object_id}.constraints must be an array")
        if kind == "add_constraint":
            value = operation.get("constraint")
            if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
                raise PlanError("add_constraint requires a typed constraint")
            constraints.append(copy.deepcopy(value))
        else:
            constraint_kind = operation.get("kind")
            target_ref = operation.get("target_ref")
            before = len(constraints)
            constraints[:] = [entry for entry in constraints if not (
                isinstance(entry, dict) and entry.get("kind") == constraint_kind
                and (target_ref is None or entry.get("target") == target_ref)
            )]
            if len(constraints) == before:
                raise PlanError(f"no matching constraint was found on {object_id}")
        return str(object_id)
    if kind == "replace_dependency":
        if space != "3d":
            raise PlanError("replace_dependency currently applies to 3D features")
        object_id = operation.get("target")
        item = _target(data, space, object_id)
        if _is_locked(str(object_id), "depends_on", locks):
            raise PlanError(f"correction would modify locked parameter {object_id}.depends_on")
        old, new = operation.get("old"), operation.get("new")
        dependencies = item.get("depends_on")
        if not isinstance(dependencies, list) or old not in dependencies or not isinstance(new, str):
            raise PlanError("replace_dependency requires an existing old dependency and a new ID")
        item["depends_on"] = [new if value == old else value for value in dependencies]
        if item.get("support_feature") == old:
            item["support_feature"] = new
            support = _constraint(item, "support_coincident")
            if support is not None:
                support["target"] = new
        return str(object_id)
    collection = _collection(data, space)
    if kind == "insert_object":
        value = operation.get("object")
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise PlanError("insert_object requires an object with an ID")
        if value["id"] in _index(data, space):
            raise PlanError(f"inserted object ID '{value['id']}' already exists")
        after = operation.get("after")
        if after is None:
            collection.append(copy.deepcopy(value))
        else:
            positions = {entry.get("id"): index for index, entry in enumerate(collection) if isinstance(entry, dict)}
            if after not in positions:
                raise PlanError(f"insert_object.after '{after}' does not exist")
            collection.insert(positions[after] + 1, copy.deepcopy(value))
        return value["id"]
    object_id = operation.get("target")
    if not isinstance(object_id, str):
        raise PlanError("remove_object requires target")
    if _is_locked(object_id, "*", locks):
        raise PlanError(f"correction would remove locked object {object_id}")
    graph = _dependency_graph(data, space)
    dependents = sorted(candidate for candidate, dependencies in graph.items() if object_id in dependencies)
    if dependents:
        raise PlanError(f"cannot remove {object_id}; dependent objects exist: {', '.join(dependents)}")
    collection[:] = [entry for entry in collection if not (isinstance(entry, dict) and entry.get("id") == object_id)]
    return object_id


def _dependency_graph(data: dict[str, Any], space: str) -> dict[str, set[str]]:
    document = semantic_from_plan(data, space)
    return {item.id: set(item.depends_on) for item in document.objects}


def _downstream(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    affected = set(roots)
    changed = True
    while changed:
        changed = False
        for object_id, dependencies in graph.items():
            if object_id not in affected and dependencies & affected:
                affected.add(object_id)
                changed = True
    return affected


def _diff(before: Any, after: Any, prefix: str = "") -> list[dict[str, Any]]:
    if (
        not isinstance(before, bool) and not isinstance(after, bool)
        and isinstance(before, (int, float)) and isinstance(after, (int, float))
        and math.isclose(float(before), float(after), rel_tol=0.0, abs_tol=1e-12)
    ):
        return []
    if type(before) is not type(after):
        return [{"path": prefix or "$", "before": before, "after": after}]
    if isinstance(before, dict):
        rows: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in before:
                rows.append({"path": path, "before": None, "after": after[key]})
            elif key not in after:
                rows.append({"path": path, "before": before[key], "after": None})
            else:
                rows.extend(_diff(before[key], after[key], path))
        return rows
    if isinstance(before, list):
        rows = []
        for index in range(max(len(before), len(after))):
            path = f"{prefix}[{index}]"
            if index >= len(before):
                rows.append({"path": path, "before": None, "after": after[index]})
            elif index >= len(after):
                rows.append({"path": path, "before": before[index], "after": None})
            else:
                rows.extend(_diff(before[index], after[index], path))
        return rows
    return [] if before == after else [{"path": prefix or "$", "before": before, "after": after}]


def validate_correction(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise PlanError("correction schema_version must be '1.0'")
    correction = value.get("correction")
    if not isinstance(correction, dict):
        raise PlanError("correction object is required")
    for field in ("id", "description"):
        if not isinstance(correction.get(field), str) or not correction[field].strip():
            raise PlanError(f"correction.{field} is required")
    if correction.get("space") not in {"2d", "3d"}:
        raise PlanError("correction.space must be 2d or 3d")
    operations = correction.get("operations")
    if not isinstance(operations, list) or not operations:
        raise PlanError("correction.operations must be non-empty")
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get("op") not in SUPPORTED_OPERATIONS:
            raise PlanError(f"correction.operations[{index}] is unsupported")
    policy = value.get("review_policy", {})
    if policy.get("reviewOnly", True) is not True or policy.get("accepted", False) is not False or policy.get("ruleEnabled", False) is not False:
        raise PlanError("correction must remain reviewOnly=true, accepted=false, ruleEnabled=false")
    return {"ok": True, "valid": True, "operation_count": len(operations), "space": correction["space"]}


def preview_correction(plan_data: dict[str, Any], correction_data: dict[str, Any], domain: str = "general") -> dict[str, Any]:
    validation = validate_correction(correction_data)
    correction = correction_data["correction"]
    space = correction["space"]
    before_plan = _compile(plan_data, space)
    before_graph = _dependency_graph(plan_data, space)
    before_ids = set(before_graph)
    subobject_catalog, selected_refs = validate_selected_refs(
        plan_data, correction, before_plan.source_hash, correction_data.get("source_sha256")
    )
    selected = correction.get("selected_ids", [])
    if not isinstance(selected, list) or any(value not in before_ids for value in selected):
        raise PlanError("correction.selected_ids must reference existing objects")
    locks_raw = correction_data.get("locks", [])
    if not isinstance(locks_raw, list) or not all(isinstance(value, str) for value in locks_raw):
        raise PlanError("correction.locks must be an array of strings")
    metadata = plan_data.get("drawing") if space == "2d" else plan_data.get("part")
    plan_locks = metadata.get("locks", []) if isinstance(metadata, dict) else []
    locks = list(dict.fromkeys([*plan_locks, *locks_raw]))
    candidate = copy.deepcopy(plan_data)
    directly_changed: set[str] = set()
    subobject_transactions: list[dict[str, Any]] = []
    for operation in correction["operations"]:
        if operation["op"] in NEW_SUBOBJECT_OPERATIONS:
            if space != "3d":
                raise PlanError("exact subobject operations currently require correction.space=3d")
            changed_ids, transaction = apply_subobject_operation(
                candidate, operation, subobject_catalog, selected_refs, locks
            )
            directly_changed.update(changed_ids)
            subobject_transactions.append(transaction)
        else:
            directly_changed.add(_apply_operation(candidate, space, operation, locks))
    after_plan = _compile(candidate, space)
    after_graph = _dependency_graph(candidate, space)
    affected = _downstream(after_graph, directly_changed)
    budget = correction_data.get("change_budget", {})
    if not isinstance(budget, dict):
        raise PlanError("change_budget must be an object")
    max_direct = int(budget.get("max_direct_objects", max(1, len(directly_changed))))
    max_affected = int(budget.get("max_affected_objects", max(len(after_graph), 1)))
    if len(directly_changed) > max_direct:
        raise PlanError(f"correction changes {len(directly_changed)} direct objects; budget is {max_direct}")
    if len(affected) > max_affected:
        raise PlanError(f"correction affects {len(affected)} objects; budget is {max_affected}")
    before_hash = before_plan.source_hash
    after_hash = after_plan.source_hash
    changes = _diff(plan_data, candidate)
    root_cause = correction_data.get("root_cause")
    prevention = correction_data.get("prevention_rule")
    return {
        "ok": True, "status": "pass", "validation": validation, "correction_id": correction["id"],
        "description": correction["description"], "space": space, "domain": domain,
        "before_sha256": before_hash, "after_sha256": after_hash,
        "directly_changed_ids": sorted(directly_changed), "affected_ids": sorted(affected),
        "preserved_ids": sorted(set(after_graph) - affected), "added_ids": sorted(set(after_graph) - before_ids),
        "subobject_transactions": subobject_transactions,
        "removed_ids": sorted(before_ids - set(after_graph)), "change_count": len(changes), "changes": changes,
        "locks_enforced": locks,
        "root_cause": root_cause if isinstance(root_cause, dict) else {
            "status": "candidate", "symptom": correction["description"],
            "cause_class": "user_directed_correction", "explanation": "No explicit root cause was supplied; preserve as a review candidate.",
        },
        "prevention_rule": prevention if isinstance(prevention, dict) else {
            "status": "candidate", "ruleEnabled": False,
            "requirement": "A future recurrence must be detected by the same typed invariant before artifact exposure.",
        },
        "before_semantic": describe_plan(plan_data, space, domain),
        "after_semantic": describe_plan(candidate, space, domain),
        "candidate_plan": candidate,
        "gates": {
            "before_valid": True, "after_valid": True, "locks_preserved": True,
            "direct_change_budget": True, "affected_change_budget": True,
            "reviewOnly": True, "accepted": False, "ruleEnabled": False,
        },
        "topology_authority": {
            "semantic_reference_catalog": True, "native_persistent_topology": False,
            "status": "plan_derived_exact_reference_pending_native_host_readback",
        },
    }


def write_correction_artifacts(result: dict[str, Any], output_dir: Path, stem: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / f"{stem}.corrected.plan.json"
    transaction_path = output_dir / f"{stem}.correction.json"
    audit_path = output_dir / f"{stem}.correction.audit.md"
    plan_path.write_text(json.dumps(result["candidate_plan"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    transaction = {key: value for key, value in result.items() if key not in {"candidate_plan", "before_semantic", "after_semantic"}}
    transaction["candidate_plan_sha256"] = _canonical_hash(result["candidate_plan"])
    transaction_path.write_text(json.dumps(transaction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = [
        f"# {result['correction_id']} - AICAD correction audit", "",
        f"- Space/domain: `{result['space']}` / `{result['domain']}`",
        f"- Before SHA-256: `{result['before_sha256']}`", f"- After SHA-256: `{result['after_sha256']}`",
        f"- Direct objects: `{', '.join(result['directly_changed_ids'])}`",
        f"- Affected objects: `{', '.join(result['affected_ids'])}`",
        f"- Change records: `{result['change_count']}`", "",
        "## Root cause candidate", "", json.dumps(result["root_cause"], ensure_ascii=False, indent=2), "",
        "## Prevention rule candidate", "", json.dumps(result["prevention_rule"], ensure_ascii=False, indent=2), "",
        "## Exact subobject transactions", "",
    ]
    rows.extend(f"- `{json.dumps(item, ensure_ascii=False, sort_keys=True)}`" for item in result.get("subobject_transactions", []))
    rows.extend(["", "## Changed paths", ""])
    rows.extend(f"- `{item['path']}`: `{item['before']}` -> `{item['after']}`" for item in result["changes"])
    audit_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"plan": str(plan_path.resolve()), "transaction": str(transaction_path.resolve()), "audit": str(audit_path.resolve())}


def apply_correction(
    plan_data: dict[str, Any], correction_data: dict[str, Any], output_dir: Path, stem: str,
    domain: str = "general",
) -> dict[str, Any]:
    result = preview_correction(plan_data, correction_data, domain)
    artifacts = write_correction_artifacts(result, output_dir, stem)
    public = {key: value for key, value in result.items() if key not in {"candidate_plan", "before_semantic", "after_semantic"}}
    public["artifacts"] = artifacts
    return public
