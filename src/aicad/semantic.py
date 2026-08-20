from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .engine import PlanError, ResolvedArc, ResolvedCircle, ResolvedDimension, ResolvedLine, ResolvedText, compile_plan
from .engine3d import compile_plan3d
from .domain_maturity import DOMAIN_MATURITY_CEILINGS, assess_domain_maturity


ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


CORE_DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "general": {
        "label": "通用工程图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["boundary", "construction", "center", "feature", "reference", "annotation"],
        "review_groups": ["requirements", "geometry", "relations", "manufacturability", "delivery"],
    },
    "mechanical": {
        "label": "机械零件与装配",
        "dimensions": ["2d", "3d"],
        "object_roles": ["datum", "outline", "hole", "shaft", "boss", "pocket", "interface", "fastener"],
        "review_groups": ["datums", "degrees_of_freedom", "fit", "wall_thickness", "interference", "tolerance"],
    },
    "electronics": {
        "label": "电子结构与板级外形",
        "dimensions": ["2d", "3d"],
        "object_roles": ["board_outline", "keepout", "connector", "mounting_hole", "enclosure", "thermal", "cable_path"],
        "review_groups": ["board_fit", "connector_access", "keepout", "clearance", "thermal_path", "serviceability"],
    },
    "sheet_metal": {
        "label": "钣金与折弯件",
        "dimensions": ["2d", "3d"],
        "object_roles": ["blank", "bend", "relief", "flange", "hem", "seam", "hole"],
        "review_groups": ["bend_allowance", "minimum_radius", "relief", "flat_pattern", "collision", "tool_access"],
    },
    "architecture": {
        "label": "建筑与空间平面",
        "dimensions": ["2d", "3d"],
        "object_roles": ["grid", "grid_bubble", "wall", "opening", "room", "column", "stair", "equipment", "route"],
        "review_groups": ["grid", "closure", "clearance", "egress", "accessibility", "coordination"],
    },
    "packaging": {
        "label": "包装刀版与折叠结构",
        "dimensions": ["2d", "3d"],
        "object_roles": ["cut", "crease", "slot", "panel", "flap", "tab", "lock", "glue"],
        "review_groups": ["structure_identity", "closure", "fold_order", "clearance", "collision", "manufacturing"],
    },
    "civil": {
        "label": "土木工程意图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["control_point", "terrain", "alignment", "profile", "grading", "drainage", "utility", "right_of_way", "parcel", "road", "structure", "annotation"],
        "review_groups": ["survey", "coordinate_system", "grading", "drainage", "utilities", "drawing_standard"],
    },
    "structural": {
        "label": "结构工程意图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["grid", "node", "member", "slab", "wall", "support", "load", "connection", "reinforcement", "annotation"],
        "review_groups": ["load_path", "member_system", "connections", "stability", "detailing", "drawing_standard"],
    },
    "electrical": {
        "label": "电气工程意图",
        "dimensions": ["2d"],
        "object_roles": ["bus", "circuit", "device", "cable", "panel", "transformer", "protection", "earthing", "conduit", "annotation"],
        "review_groups": ["single_line", "protection", "cable_sizing", "clearance", "earthing", "schematic_standard"],
    },
    "plumbing": {
        "label": "给排水工程意图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["fixture", "pipe", "fitting", "valve", "vent", "drain", "equipment", "access", "annotation"],
        "review_groups": ["fixture_demand", "pipe_sizing", "slope", "venting", "access", "drawing_standard"],
    },
    "hvac": {
        "label": "暖通工程意图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["zone", "equipment", "duct", "pipe", "terminal", "damper", "control", "clearance", "annotation"],
        "review_groups": ["load_basis", "airflow", "duct_pipe_sizing", "clearance", "controls", "drawing_standard"],
    },
    "process_piping": {
        "label": "工艺管道工程意图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["equipment", "nozzle", "line", "pipe", "fitting", "valve", "instrument", "support", "isometric", "annotation"],
        "review_groups": ["line_class", "pressure_temperature", "routing", "supports", "isometrics", "drawing_standard"],
    },
    "product_design": {
        "label": "工业产品多专业意图",
        "dimensions": ["2d", "3d"],
        "object_roles": ["requirement", "datum", "body", "interface", "component", "fastener", "clearance", "service_envelope", "annotation"],
        "review_groups": ["design_intent", "interfaces", "material_process", "tolerances", "assembly", "drawing_standard"],
    },
}


DOMAIN_MATURITY: dict[str, str] = dict(DOMAIN_MATURITY_CEILINGS)
REGISTERED_ENGINEERING_DOMAINS = frozenset(CORE_DOMAIN_PROFILES)


@dataclass(frozen=True)
class SemanticObject:
    id: str
    kind: str
    space: str
    purpose: str
    reasoning: str
    depends_on: tuple[str, ...]
    anchor: tuple[float, ...]
    parameters: dict[str, Any]
    source: dict[str, Any]
    roles: tuple[str, ...]
    editable: bool


@dataclass(frozen=True)
class SemanticRelation:
    id: str
    kind: str
    members: tuple[str, ...]
    purpose: str
    hard: bool
    value: Any
    tolerance: float | None
    source: dict[str, Any]


@dataclass(frozen=True)
class SemanticDocument:
    id: str
    name: str
    space: str
    domain: str
    units: str
    origin: tuple[float, ...]
    tolerance: float
    source_hash: str
    objects: tuple[SemanticObject, ...]
    relations: tuple[SemanticRelation, ...]
    locks: tuple[str, ...]
    review_policy: dict[str, bool]


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _target_object_id(value: Any) -> str | None:
    if not isinstance(value, str) or value == "origin":
        return None
    return value.split(".", 1)[0]


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _dependencies_2d(raw: dict[str, Any], known: set[str]) -> tuple[str, ...]:
    dependencies: list[str] = []
    for value in _walk_strings(raw):
        candidate = _target_object_id(value)
        if candidate in known and candidate not in dependencies:
            dependencies.append(candidate)
    return tuple(dependencies)


def _relation_members(owner: str, constraint: dict[str, Any]) -> tuple[str, ...]:
    target = _target_object_id(constraint.get("target"))
    return (owner, target) if target is not None else (owner,)


def _roles(raw: dict[str, Any], fallback: str) -> tuple[str, ...]:
    values = raw.get("roles")
    if isinstance(values, list) and values and all(isinstance(item, str) and item for item in values):
        return tuple(dict.fromkeys(values))
    role = raw.get("role")
    if isinstance(role, str) and role:
        return (role,)
    return (fallback,)


def _review_policy(raw: Any) -> dict[str, bool]:
    value = raw if isinstance(raw, dict) else {}
    return {
        "reviewOnly": bool(value.get("reviewOnly", True)),
        "accepted": bool(value.get("accepted", False)),
        "ruleEnabled": bool(value.get("ruleEnabled", False)),
        "domainGated": bool(value.get("domainGated", True)),
    }


def _validate_domain(domain: str) -> None:
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise PlanError("domain must be a lower-case ASCII identifier")
    if domain not in REGISTERED_ENGINEERING_DOMAINS:
        raise PlanError(f"unregistered engineering domain: {domain!r}")


def _semantic_from_2d(data: dict[str, Any], domain: str) -> SemanticDocument:
    plan = compile_plan(data)
    raw_by_id = {str(item.get("id")): item for item in data["steps"] if isinstance(item, dict)}
    objects: list[SemanticObject] = []
    relations: list[SemanticRelation] = []
    known: set[str] = set()
    for entity in plan.entities:
        raw = raw_by_id[entity.id]
        dependencies = entity.depends_on
        if isinstance(entity, ResolvedLine):
            parameters = {
                "start": list(entity.start), "end": list(entity.end), "length": entity.length,
                "direction": [entity.vector[0] / entity.length, entity.vector[1] / entity.length],
            }
            fallback_role = "boundary"
        elif isinstance(entity, ResolvedCircle):
            parameters = {"center": list(entity.center), "radius": entity.radius, "diameter": entity.radius * 2.0}
            fallback_role = "feature"
        elif isinstance(entity, ResolvedArc):
            parameters = {
                "center": list(entity.center), "radius": entity.radius,
                "start_angle_deg": entity.start_angle_deg, "end_angle_deg": entity.end_angle_deg,
            }
            fallback_role = "boundary"
        elif isinstance(entity, ResolvedText):
            parameters = {
                "insert": list(entity.insert), "value": entity.value,
                "height": entity.height, "rotation_deg": entity.rotation_deg,
            }
            fallback_role = "annotation"
        else:
            parameters = {
                "first": list(entity.first), "second": list(entity.second), "base": list(entity.base),
                "measurement": entity.measurement, "dimension_kind": entity.dimension_kind,
                "style_name": entity.style_name, "dimension_purpose": entity.dimension_purpose,
            }
            fallback_role = "annotation"
        objects.append(SemanticObject(
            entity.id, entity.type, "2d", entity.purpose, entity.reasoning, dependencies,
            tuple(entity.anchor), parameters,
            {"plan_space": "2d", "object_id": entity.id, "sequence": len(objects) + 1, "cad_layer": entity.layer},
            entity.roles or _roles(raw, fallback_role), entity.editable,
        ))
        for index, constraint in enumerate(entity.constraints, 1):
            relations.append(SemanticRelation(
                f"R_{entity.id}_{index:03d}", str(constraint.get("kind")), _relation_members(entity.id, constraint),
                f"Validate {constraint.get('kind')} for {entity.id}", True, constraint.get("value"),
                plan.tolerance, {"object_id": entity.id, "constraint_index": index - 1},
            ))
        known.add(entity.id)
    drawing = data["drawing"]
    document_id = str(drawing.get("id") or f"DOC_{plan.source_hash[:12].upper()}")
    return SemanticDocument(
        document_id, plan.name, "2d", domain, plan.units, tuple(plan.origin), plan.tolerance,
        plan.source_hash, tuple(objects), tuple(relations), tuple(drawing.get("locks", [])),
        _review_policy(drawing.get("review_policy")),
    )


def _profile_parameters(profile: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": profile.kind, "center": list(profile.center), "area": profile.area, "bounds": list(profile.bounds)}
    for name in ("width", "height", "radius", "count", "bolt_circle_radius", "start_angle_deg"):
        value = getattr(profile, name)
        if value is not None:
            payload[name] = value
    if profile.primitives:
        payload["primitives"] = [{"center": list(item.center), "radius": item.radius} for item in profile.primitives]
    return payload


def _semantic_from_3d(data: dict[str, Any], domain: str) -> SemanticDocument:
    plan = compile_plan3d(data)
    raw_by_id = {str(item.get("id")): item for item in data["features"] if isinstance(item, dict)}
    objects: list[SemanticObject] = []
    relations: list[SemanticRelation] = []
    for feature in plan.features:
        raw = raw_by_id[feature.id]
        parameters = {
            "profile": _profile_parameters(feature.profile), "depth": feature.depth,
            "end_condition": feature.end_condition, "support_feature": feature.support_feature,
            "support_top_z": feature.support_top_z, "resulting_top_z": feature.resulting_top_z,
            "expected_volume_before": feature.expected_volume_before,
            "expected_volume_after": feature.expected_volume_after,
            "expected_volume_delta": feature.expected_volume_delta,
            "expected_bbox": list(feature.expected_bbox), "expected_body_count": feature.expected_body_count,
        }
        objects.append(SemanticObject(
            feature.id, feature.type, "3d", feature.purpose, feature.reasoning, feature.depends_on,
            (feature.profile.center[0], feature.profile.center[1], feature.support_top_z), parameters,
            {"plan_space": "3d", "object_id": feature.id, "sequence": len(objects) + 1, "domain": plan.domain},
            feature.roles or _roles(raw, "feature"), feature.editable,
        ))
        for index, constraint in enumerate(feature.constraints, 1):
            relations.append(SemanticRelation(
                f"R_{feature.id}_{index:03d}", str(constraint.get("kind")), _relation_members(feature.id, constraint),
                f"Validate {constraint.get('kind')} for {feature.id}", True, constraint.get("value"),
                plan.tolerance, {"object_id": feature.id, "constraint_index": index - 1},
            ))
    part = data["part"]
    document_id = str(part.get("id") or f"DOC_{plan.source_hash[:12].upper()}")
    return SemanticDocument(
        document_id, plan.name, "3d", domain, plan.units, tuple(plan.origin), plan.tolerance,
        plan.source_hash, tuple(objects), tuple(relations), tuple(part.get("locks", [])),
        _review_policy(part.get("review_policy")),
    )


def semantic_from_plan(data: dict[str, Any], space: str, domain: str = "general") -> SemanticDocument:
    if not isinstance(data, dict):
        raise PlanError("plan must be an object")
    if space not in {"2d", "3d"}:
        raise PlanError("space must be 2d or 3d")
    metadata = data.get("drawing") if space == "2d" else data.get("part")
    declared_domain = metadata.get("domain") if isinstance(metadata, dict) else None
    effective_domain = declared_domain if domain == "general" and isinstance(declared_domain, str) else domain
    _validate_domain(effective_domain)
    if space not in CORE_DOMAIN_PROFILES[effective_domain]["dimensions"]:
        raise PlanError(
            f"engineering domain {effective_domain!r} does not support {space}"
        )
    if isinstance(declared_domain, str) and declared_domain != effective_domain:
        raise PlanError(f"declared plan domain {declared_domain!r} conflicts with requested domain {effective_domain!r}")
    return _semantic_from_2d(data, effective_domain) if space == "2d" else _semantic_from_3d(data, effective_domain)


def _object_payload(item: SemanticObject) -> dict[str, Any]:
    return {
        "id": item.id, "kind": item.kind, "space": item.space, "purpose": item.purpose,
        "reasoning": item.reasoning, "depends_on": list(item.depends_on), "anchor": list(item.anchor),
        "parameters": item.parameters, "source": item.source, "roles": list(item.roles), "editable": item.editable,
    }


def _relation_payload(item: SemanticRelation) -> dict[str, Any]:
    return {
        "id": item.id, "kind": item.kind, "members": list(item.members), "purpose": item.purpose,
        "hard": item.hard, "value": item.value, "tolerance": item.tolerance, "source": item.source,
    }


def semantic_document_payload(document: SemanticDocument) -> dict[str, Any]:
    profile = CORE_DOMAIN_PROFILES[document.domain]
    maturity = assess_domain_maturity(document.domain)
    return {
        "schema_version": "1.0",
        "document": {
            "id": document.id, "name": document.name, "space": document.space, "domain": document.domain,
            "units": document.units, "origin": list(document.origin), "tolerance": document.tolerance,
            "source_sha256": document.source_hash, "locks": list(document.locks),
            "review_policy": document.review_policy,
        },
        "domain_profile": {
            "id": document.domain,
            **profile,
            "built_in": True,
            "maturity": maturity["effectiveMaturity"],
            "maturity_ceiling": maturity["codeCeiling"],
            "maturity_earned": maturity["earnedMaturity"],
            "maturity_evidence_sha256": maturity["evidenceClosure"]["fingerprint"],
            "maturity_issues": list(maturity["issues"]),
            "specialist_generation_blocked": maturity["specialistGenerationBlocked"],
            "production_release_blocked": True,
        },
        "objects": [_object_payload(item) for item in document.objects],
        "relations": [_relation_payload(item) for item in document.relations],
        "invariants": {
            "origin_anchored": bool(document.objects and document.objects[0].anchor == document.origin),
            "ordered_dependencies": True,
            "all_objects_explained": all(item.purpose and item.reasoning for item in document.objects),
            "review_only": document.review_policy["reviewOnly"],
            "accepted": document.review_policy["accepted"],
            "rule_enabled": document.review_policy["ruleEnabled"],
            "domain_gated": document.review_policy["domainGated"],
        },
    }


def validate_semantic_document(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise PlanError("semantic document schema_version must be '1.0'")
    document = data.get("document")
    if not isinstance(document, dict):
        raise PlanError("semantic document metadata is required")
    space = document.get("space")
    if space not in {"2d", "3d"}:
        raise PlanError("semantic document space must be 2d or 3d")
    dimension = 2 if space == "2d" else 3
    origin = document.get("origin")
    if not isinstance(origin, list) or len(origin) != dimension or any(float(value) != 0.0 for value in origin):
        raise PlanError(f"semantic document origin must be {[0] * dimension}")
    domain = document.get("domain", "general")
    if not isinstance(domain, str):
        raise PlanError("semantic document domain must be a string")
    _validate_domain(domain)
    if space not in CORE_DOMAIN_PROFILES[domain]["dimensions"]:
        raise PlanError(f"engineering domain {domain!r} does not support {space}")
    profile = data.get("domain_profile")
    if not isinstance(profile, dict):
        raise PlanError("semantic document domain_profile is required")
    maturity = assess_domain_maturity(domain)
    if profile.get("maturity") != maturity["effectiveMaturity"]:
        raise PlanError("semantic domain maturity must match the code-owned effective decision")
    if (
        profile.get("specialist_generation_blocked")
        is not maturity["specialistGenerationBlocked"]
    ):
        raise PlanError(
            "semantic specialist generation boundary must match effective maturity"
        )
    objects = data.get("objects")
    if not isinstance(objects, list) or not objects:
        raise PlanError("semantic document objects must be non-empty")
    known: set[str] = set()
    for index, item in enumerate(objects):
        if not isinstance(item, dict):
            raise PlanError(f"objects[{index}] must be an object")
        object_id = item.get("id")
        if not isinstance(object_id, str) or not ID_PATTERN.fullmatch(object_id) or object_id in known:
            raise PlanError(f"objects[{index}].id must be a unique ASCII ID")
        if item.get("space") != space:
            raise PlanError(f"{object_id}.space must match the document")
        if not isinstance(item.get("purpose"), str) or not item["purpose"].strip():
            raise PlanError(f"{object_id}.purpose is required")
        if not isinstance(item.get("reasoning"), str) or not item["reasoning"].strip():
            raise PlanError(f"{object_id}.reasoning is required")
        dependencies = item.get("depends_on", [])
        if not isinstance(dependencies, list) or any(value not in known for value in dependencies):
            raise PlanError(f"{object_id}.depends_on may only reference earlier objects")
        anchor = item.get("anchor")
        if not isinstance(anchor, list) or len(anchor) != dimension:
            raise PlanError(f"{object_id}.anchor must contain {dimension} coordinates")
        if index == 0 and any(abs(float(anchor[i]) - float(origin[i])) > float(document.get("tolerance", 1e-6)) for i in range(dimension)):
            raise PlanError("the first semantic object must be anchored at the origin")
        known.add(object_id)
    relation_ids: set[str] = set()
    for index, relation in enumerate(data.get("relations", [])):
        if not isinstance(relation, dict):
            raise PlanError(f"relations[{index}] must be an object")
        relation_id = relation.get("id")
        members = relation.get("members")
        if not isinstance(relation_id, str) or not ID_PATTERN.fullmatch(relation_id) or relation_id in relation_ids:
            raise PlanError(f"relations[{index}].id must be a unique ASCII ID")
        if not isinstance(members, list) or not members or any(member not in known for member in members):
            raise PlanError(f"{relation_id}.members must reference semantic objects")
        relation_ids.add(relation_id)
    policy = document.get("review_policy", {})
    if policy.get("reviewOnly") is not True or policy.get("accepted") is not False or policy.get("ruleEnabled") is not False:
        raise PlanError("semantic document must remain reviewOnly=true, accepted=false, ruleEnabled=false")
    return {
        "ok": True, "valid": True, "space": space, "domain": domain,
        "object_count": len(objects), "relation_count": len(data.get("relations", [])),
        "source_sha256": document.get("source_sha256"), "semantic_sha256": _canonical_hash(data),
    }


def describe_plan(data: dict[str, Any], space: str, domain: str = "general") -> dict[str, Any]:
    payload = semantic_document_payload(semantic_from_plan(data, space, domain))
    payload["validation"] = validate_semantic_document(payload)
    return payload


def domain_capabilities() -> dict[str, Any]:
    decisions = {
        domain: assess_domain_maturity(domain)
        for domain in sorted(REGISTERED_ENGINEERING_DOMAINS)
    }
    return {
        "core_is_domain_agnostic": True,
        "built_in_profiles": CORE_DOMAIN_PROFILES,
        "registered_domains": sorted(REGISTERED_ENGINEERING_DOMAINS),
        "domain_maturity": {
            domain: decision["effectiveMaturity"]
            for domain, decision in decisions.items()
        },
        "domain_maturity_ceiling": dict(DOMAIN_MATURITY_CEILINGS),
        "domain_maturity_decisions": {
            domain: {
                "earned_maturity": decision["earnedMaturity"],
                "effective_maturity": decision["effectiveMaturity"],
                "evidence_closure_sha256": decision["evidenceClosure"]["fingerprint"],
                "specialist_generation_blocked": decision["specialistGenerationBlocked"],
                "issues": list(decision["issues"]),
            }
            for domain, decision in decisions.items()
        },
        "custom_profile_ids_allowed": False,
        "unknown_domain_policy": "fail_closed",
        "production_release_granted": False,
        "rule_boundary": "domain profiles add requirements and QA; they do not replace origin, dependency, audit, or transaction gates",
    }
