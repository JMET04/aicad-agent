from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from .engine import PlanError, ResolvedLine, compile_plan
from .engine3d import compile_plan3d
from .semantic import CORE_DOMAIN_PROFILES, describe_plan


DOMAIN_RULE_PACKS: dict[str, dict[str, Any]] = {
    "general": {
        "role_kinds_2d": {}, "role_types_3d": {}, "canonical_layers": {}, "closed_roles": [],
        "manual_reviews": ["requirements", "manufacturability", "delivery"],
    },
    "mechanical": {
        "role_kinds_2d": {
            "datum": ["line"], "outline": ["line", "arc"], "hole": ["circle", "arc"],
            "mounting_hole": ["circle", "arc"], "shaft": ["circle", "line"], "center": ["line", "circle"],
        },
        "role_types_3d": {
            "body": ["base_extrude", "boss_extrude"], "boss": ["boss_extrude"],
            "hole": ["cut_extrude"], "mounting_hole": ["cut_extrude"], "pocket": ["cut_extrude"],
        },
        "canonical_layers": {"datum": ["DATUM", "CENTER"], "outline": ["OUTLINE"], "hole": ["HOLE"], "mounting_hole": ["HOLE"]},
        "closed_roles": ["outline"],
        "manual_reviews": ["datums", "fit", "wall_thickness", "interference", "tolerance"],
    },
    "electronics": {
        "role_kinds_2d": {
            "board_outline": ["line", "arc"], "keepout": ["line", "arc", "circle"],
            "mounting_hole": ["circle", "arc"], "pad": ["circle", "arc"], "connector": ["line", "arc", "circle"],
        },
        "role_types_3d": {
            "enclosure": ["base_extrude", "boss_extrude"], "connector": ["boss_extrude", "cut_extrude"],
            "mounting_hole": ["cut_extrude"], "cable_path": ["cut_extrude"],
        },
        "canonical_layers": {
            "board_outline": ["BOARD_OUTLINE"], "keepout": ["KEEP_OUT"], "mounting_hole": ["HOLE"],
            "pad": ["PAD"], "connector": ["CONNECTOR"],
        },
        "closed_roles": ["board_outline"],
        "manual_reviews": ["board_fit", "connector_access", "electrical_clearance", "thermal_path", "serviceability"],
    },
    "sheet_metal": {
        "role_kinds_2d": {
            "blank": ["line", "arc"], "bend": ["line", "arc"], "relief": ["line", "arc", "circle"],
            "hole": ["circle", "arc"], "seam": ["line", "arc"],
        },
        "role_types_3d": {
            "blank": ["base_extrude"], "flange": ["boss_extrude"], "hole": ["cut_extrude"],
            "relief": ["cut_extrude"],
        },
        "canonical_layers": {"blank": ["OUTLINE", "CUT"], "bend": ["BEND", "CREASE"], "relief": ["RELIEF"], "hole": ["HOLE"]},
        "closed_roles": ["blank"],
        "manual_reviews": ["bend_allowance", "minimum_radius", "relief", "flat_pattern", "collision", "tool_access"],
    },
    "architecture": {
        "role_kinds_2d": {
            "grid": ["line"], "grid_bubble": ["circle"], "wall": ["line", "arc"], "opening": ["line", "arc"],
            "room": ["line", "arc"], "column": ["circle", "line", "arc"], "route": ["line", "arc"],
        },
        "role_types_3d": {
            "slab": ["base_extrude", "boss_extrude"], "wall": ["base_extrude", "boss_extrude"],
            "column": ["boss_extrude"], "opening": ["cut_extrude"],
        },
        "canonical_layers": {"grid": ["GRID"], "grid_bubble": ["GRID_BUBBLE"], "wall": ["WALL"], "opening": ["OPENING"], "room": ["ROOM"], "column": ["COLUMN"], "route": ["ROUTE"]},
        "closed_roles": ["room"],
        "manual_reviews": ["egress", "accessibility", "fire_separation", "coordination", "code_compliance"],
    },
    "packaging": {
        "role_kinds_2d": {
            "cut": ["line", "arc"], "cut_edge": ["line", "arc"], "crease": ["line", "arc"],
            "fold_edge": ["line", "arc"], "slot": ["line", "arc"], "slot_end": ["line", "arc", "circle"],
            "glue": ["line", "arc"],
        },
        "role_types_3d": {
            "panel": ["base_extrude", "boss_extrude"], "tab": ["boss_extrude"],
            "slot": ["cut_extrude"], "opening": ["cut_extrude"],
        },
        "canonical_layers": {
            "cut": ["CUT"], "cut_edge": ["CUT"], "crease": ["CREASE"], "fold_edge": ["CREASE"],
            "slot": ["SLOT"], "slot_end": ["SLOT"], "glue": ["GLUE"],
        },
        "closed_roles": [],
        "manual_reviews": ["structure_identity", "closure", "fold_order", "clearance", "collision", "manufacturing"],
    },
}


HOST_CAPABILITIES: dict[str, dict[str, Any]] = {
    "portable_2d": {
        "supported": ["line", "circle", "arc", "ordered_dependencies", "layers", "utf8_audit", "ascii_execution"],
        "not_supported": ["native_dwg_persistence", "associative_dimensions", "native_bim_semantics", "pcb_netlist"],
    },
    "autocad_2025": {
        "supported": ["line", "circle", "arc", "scr_layers", "dxf_layers", "aicad_xdata_baseline"],
        "not_supported": ["per_entity_layer_in_aicad_protocol_v2", "native_bim_semantics", "pcb_netlist"],
    },
    "portable_3d": {
        "supported": ["base_extrude", "boss_extrude", "cut_extrude", "analytic_volume", "bbox", "dependency_graph", "review_views"],
        "profiles": ["center_rectangle", "circle", "circle_pattern"],
        "not_supported": ["exact_brep", "native_sheet_metal", "revolve", "sweep", "loft", "fillet", "chamfer"],
    },
    "solidworks": {
        "supported": ["base_extrude", "boss_extrude", "cut_extrude", "save_reopen", "persistent_support_reference", "fully_constrained_sketch_gate"],
        "profiles": ["center_rectangle", "circle", "circle_pattern"],
        "not_supported": ["native_sheet_metal", "revolve", "sweep", "loft", "fillet", "chamfer", "assembly_mates"],
    },
}


def _check(
    rule_id: str,
    status: str,
    severity: str,
    message: str,
    object_ids: Iterable[str] = (),
    evidence: dict[str, Any] | None = None,
    root_cause: str | None = None,
    prevention: str | None = None,
) -> dict[str, Any]:
    value = {
        "id": rule_id, "status": status, "severity": severity, "message": message,
        "object_ids": list(object_ids), "evidence": evidence or {},
    }
    if status in {"fail", "warning"}:
        value["root_cause"] = root_cause or "The semantic object did not satisfy the active domain rule."
        value["prevention_rule_candidate"] = {
            "status": "candidate", "ruleEnabled": False,
            "requirement": prevention or "Validate this relation before compiling domain artifacts.",
        }
    return value


def _point_key(point: tuple[float, float], tolerance: float) -> tuple[int, int]:
    return round(point[0] / tolerance), round(point[1] / tolerance)


def _closed_line_check(plan: Any, object_ids: set[str], tolerance: float) -> tuple[bool, dict[str, Any]]:
    lines = [entity for entity in plan.entities if entity.id in object_ids and isinstance(entity, ResolvedLine)]
    if len(lines) < 3:
        return True, {"applicable": False, "line_count": len(lines)}
    degrees: dict[tuple[int, int], int] = {}
    for line in lines:
        for point in (line.start, line.end):
            key = _point_key(point, tolerance)
            degrees[key] = degrees.get(key, 0) + 1
    invalid = {f"{key[0]}:{key[1]}": degree for key, degree in degrees.items() if degree != 2}
    return not invalid, {"applicable": True, "line_count": len(lines), "vertex_count": len(degrees), "invalid_vertex_degrees": invalid}


def evaluate_domain_plan(data: dict[str, Any], space: str, domain: str = "general") -> dict[str, Any]:
    semantic = describe_plan(data, space, domain)
    active_domain = semantic["document"]["domain"]
    pack = DOMAIN_RULE_PACKS.get(active_domain, DOMAIN_RULE_PACKS["general"])
    known_roles = set(CORE_DOMAIN_PROFILES.get(active_domain, {}).get("object_roles", []))
    checks: list[dict[str, Any]] = []

    checks.append(_check(
        "DOMAIN.G001", "pass", "hard", "The plan compiled and its ordered semantic dependency graph is valid.",
        evidence={"object_count": len(semantic["objects"]), "relation_count": len(semantic["relations"])},
    ))

    role_kind = pack["role_kinds_2d"] if space == "2d" else pack["role_types_3d"]
    for item in semantic["objects"]:
        object_id, kind, roles = item["id"], item["kind"], item["roles"]
        unknown = [role for role in roles if known_roles and role not in known_roles and role not in role_kind]
        if unknown:
            checks.append(_check(
                "DOMAIN.G002", "warning", "advisory", f"{object_id} uses roles outside the built-in {active_domain} vocabulary.",
                [object_id], {"roles": roles, "unknown_roles": unknown},
                "The generator introduced a role without binding it to the active domain profile.",
                "Require every generated role to be declared by the active domain rule pack or explicitly registered as a reviewed extension.",
            ))
        for role in roles:
            allowed = role_kind.get(role)
            if allowed is not None and kind not in allowed:
                checks.append(_check(
                    "DOMAIN.G003", "fail", "hard", f"{object_id} role {role!r} is incompatible with {kind!r}.",
                    [object_id], {"role": role, "actual_kind": kind, "allowed_kinds": allowed},
                    "The semantic role was assigned after geometry selection without checking the role-to-geometry contract.",
                    "Filter candidate geometry types by the selected semantic role before inserting the object into the ordered plan.",
                ))

    if space == "2d":
        plan = compile_plan(data)
        by_id = {entity.id: entity for entity in plan.entities}
        canonical_layers = pack["canonical_layers"]
        for item in semantic["objects"]:
            entity = by_id[item["id"]]
            for role in item["roles"]:
                allowed_layers = canonical_layers.get(role)
                if allowed_layers is not None and entity.layer not in allowed_layers:
                    checks.append(_check(
                        "DOMAIN.2D.001", "fail", "hard", f"{entity.id} is on {entity.layer}, not a canonical layer for role {role}.",
                        [entity.id], {"role": role, "actual_layer": entity.layer, "allowed_layers": allowed_layers},
                        "The role and CAD layer were generated independently, so the semantic classification did not reach the deliverable.",
                        "Derive the CAD layer from the selected role in one transaction and reject role-layer mismatches before DXF/SCR export.",
                    ))
        for role in pack["closed_roles"]:
            ids = {item["id"] for item in semantic["objects"] if role in item["roles"]}
            valid, evidence = _closed_line_check(plan, ids, plan.tolerance)
            if evidence["applicable"]:
                checks.append(_check(
                    f"DOMAIN.2D.CLOSED.{role.upper()}", "pass" if valid else "fail", "hard",
                    f"The {role} line set is {'closed' if valid else 'open or branched'}.", sorted(ids), evidence,
                    "The outline was drawn line by line without a final vertex-degree closure proof.",
                    "For every closed semantic role, require every tolerance-clustered vertex to have degree two before artifact generation.",
                ))
        host = {"portable": HOST_CAPABILITIES["portable_2d"], "native": HOST_CAPABILITIES["autocad_2025"]}
    else:
        plan3d = compile_plan3d(data)
        final = plan3d.features[-1]
        checks.append(_check(
            "DOMAIN.3D.001", "pass", "hard", "Every feature transaction preserves a valid single solid and analytic state.",
            [feature.id for feature in plan3d.features],
            {"final_volume_mm3": final.expected_volume_after, "final_bbox_mm": list(final.expected_bbox), "body_count": final.expected_body_count},
        ))
        host = {"portable": HOST_CAPABILITIES["portable_3d"], "native": HOST_CAPABILITIES["solidworks"]}

    failures = sum(item["status"] == "fail" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    status = "failed" if failures else ("passed_with_warnings" if warnings else "passed")
    return {
        "schema_version": "1.0", "status": status, "space": space, "domain": active_domain,
        "source_sha256": semantic["document"]["source_sha256"],
        "summary": {"checks": len(checks), "failures": failures, "warnings": warnings, "manual_review_required": True},
        "checks": checks,
        "manual_review_queue": list(pack["manual_reviews"]),
        "capability_boundary": host,
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
    }


def write_domain_validation(data: dict[str, Any], space: str, output_dir: Path, stem: str, domain: str = "general") -> dict[str, str]:
    report = evaluate_domain_plan(data, space, domain)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.domain-validation.json"
    markdown_path = output_dir / f"{stem}.domain-validation.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = [
        f"# {stem} - AICAD domain validation", "", f"- Status: `{report['status']}`",
        f"- Domain / space: `{report['domain']}` / `{report['space']}`",
        f"- Failures / warnings: `{report['summary']['failures']}` / `{report['summary']['warnings']}`", "",
        "| Rule | Status | Severity | Objects | Result |", "|---|---|---|---|---|",
    ]
    clean = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    for item in report["checks"]:
        rows.append(f"| `{item['id']}` | `{item['status']}` | `{item['severity']}` | {', '.join(item['object_ids']) or '-'} | {clean(item['message'])} |")
        if item["status"] in {"fail", "warning"}:
            rows.extend([
                f"  - Root cause: {clean(item['root_cause'])}",
                f"  - Prevention candidate (disabled): {clean(item['prevention_rule_candidate']['requirement'])}",
            ])
    rows.extend(["", "## Manual review queue", "", *[f"- {item}" for item in report["manual_review_queue"]]])
    markdown_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"validation": str(json_path.resolve()), "audit": str(markdown_path.resolve()), "status": report["status"]}
