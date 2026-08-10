from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .engine import CompiledPlan, ResolvedArc, ResolvedCircle, ResolvedEntity, ResolvedLine


def _fmt(value: float) -> str:
    text = format(value, ".12g")
    return "0" if text in {"-0", "-0.0"} else text


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def write_execution(plan: CompiledPlan, path: Path) -> None:
    protocol = "1" if plan.schema_version == "1.0" else "2"
    records = [f"AICAD|{protocol}|{plan.units.upper()}|{_fmt(plan.tolerance)}|{plan.source_hash}"]
    for entity in plan.entities:
        common = [entity.id, _text_hash(entity.purpose), _text_hash(entity.reasoning)]
        proof = [_fmt(plan.origin[0]), _fmt(plan.origin[1]), _fmt(entity.anchor[0] - plan.origin[0]), _fmt(entity.anchor[1] - plan.origin[1])]
        if isinstance(entity, ResolvedLine):
            values = [_fmt(entity.start[0]), _fmt(entity.start[1]), _fmt(entity.end[0]), _fmt(entity.end[1])]
            records.append("|".join(["LINE", entity.id, *values, *common[1:], *(proof if protocol == "2" else [])]))
        elif isinstance(entity, ResolvedCircle):
            values = [_fmt(entity.center[0]), _fmt(entity.center[1]), _fmt(entity.radius)]
            records.append("|".join(["CIRCLE", entity.id, *values, *common[1:], *proof]))
        else:
            values = [
                _fmt(entity.center[0]), _fmt(entity.center[1]), _fmt(entity.radius),
                _fmt(entity.start_angle_deg), _fmt(entity.end_angle_deg),
            ]
            records.append("|".join(["ARC", entity.id, *values, *common[1:], *proof]))
    records.append(f"END|{len(plan.entities)}|{plan.source_hash}")
    path.write_text("\n".join(records) + "\n", encoding="ascii", newline="\n")


def write_script(plan: CompiledPlan, path: Path) -> None:
    lines = ["_.UNDO", "_Begin"]
    for entity in plan.entities:
        if isinstance(entity, ResolvedLine):
            lines.extend(["_.LINE", f"{_fmt(entity.start[0])},{_fmt(entity.start[1])}", f"{_fmt(entity.end[0])},{_fmt(entity.end[1])}", ""])
        elif isinstance(entity, ResolvedCircle):
            lines.extend(["_.CIRCLE", f"{_fmt(entity.center[0])},{_fmt(entity.center[1])}", _fmt(entity.radius)])
        else:
            lines.extend([
                "_.ARC", "_C", f"{_fmt(entity.center[0])},{_fmt(entity.center[1])}",
                f"{_fmt(entity.start[0])},{_fmt(entity.start[1])}", "_A",
                _fmt((entity.end_angle_deg - entity.start_angle_deg) % 360),
            ])
    lines.extend(["_.UNDO", "_End", "_.ZOOM", "_Extents", ""])
    path.write_text("\n".join(lines), encoding="ascii", newline="\n")


def _dxf_pair(code: int, value: str | int | float) -> str:
    return f"{code}\n{value}\n"


def write_dxf(plan: CompiledPlan, path: Path) -> None:
    content = [_dxf_pair(0, "SECTION"), _dxf_pair(2, "HEADER"), _dxf_pair(0, "ENDSEC")]
    content.extend([_dxf_pair(0, "SECTION"), _dxf_pair(2, "ENTITIES")])
    for entity in plan.entities:
        common = [_dxf_pair(8, "AICAD_GEOMETRY")]
        if isinstance(entity, ResolvedLine):
            content.extend([
                _dxf_pair(0, "LINE"), *common,
                _dxf_pair(10, _fmt(entity.start[0])), _dxf_pair(20, _fmt(entity.start[1])), _dxf_pair(30, "0"),
                _dxf_pair(11, _fmt(entity.end[0])), _dxf_pair(21, _fmt(entity.end[1])), _dxf_pair(31, "0"),
            ])
        elif isinstance(entity, ResolvedCircle):
            content.extend([
                _dxf_pair(0, "CIRCLE"), *common,
                _dxf_pair(10, _fmt(entity.center[0])), _dxf_pair(20, _fmt(entity.center[1])), _dxf_pair(30, "0"),
                _dxf_pair(40, _fmt(entity.radius)),
            ])
        else:
            content.extend([
                _dxf_pair(0, "ARC"), *common,
                _dxf_pair(10, _fmt(entity.center[0])), _dxf_pair(20, _fmt(entity.center[1])), _dxf_pair(30, "0"),
                _dxf_pair(40, _fmt(entity.radius)), _dxf_pair(50, _fmt(entity.start_angle_deg)),
                _dxf_pair(51, _fmt(entity.end_angle_deg)),
            ])
    content.extend([_dxf_pair(0, "ENDSEC"), _dxf_pair(0, "EOF")])
    path.write_text("".join(content), encoding="ascii", newline="\n")


def _constraint_summary(entity: ResolvedEntity) -> str:
    parts: list[str] = []
    for constraint in entity.constraints:
        kind = str(constraint["kind"])
        if "target" in constraint:
            detail = str(constraint["target"])
            if "dx" in constraint or "dy" in constraint:
                detail += f" + ({constraint.get('dx', 0)}, {constraint.get('dy', 0)})"
        else:
            detail = constraint.get("value")
        parts.append(f"{kind}={detail}" if detail is not None else kind)
    return "; ".join(parts)


def _geometry(entity: ResolvedEntity) -> str:
    if isinstance(entity, ResolvedLine):
        return f"({_fmt(entity.start[0])}, {_fmt(entity.start[1])}) -> ({_fmt(entity.end[0])}, {_fmt(entity.end[1])}); L={_fmt(entity.length)}"
    if isinstance(entity, ResolvedCircle):
        return f"C=({_fmt(entity.center[0])}, {_fmt(entity.center[1])}); R={_fmt(entity.radius)}"
    return f"C=({_fmt(entity.center[0])}, {_fmt(entity.center[1])}); R={_fmt(entity.radius)}; A={_fmt(entity.start_angle_deg)}..{_fmt(entity.end_angle_deg)}"


def write_audit(plan: CompiledPlan, path: Path) -> None:
    rows = [
        f"# {plan.name} - AI CAD audit", "", f"- Schema: `{plan.schema_version}`", f"- Units: `{plan.units}`",
        "- Origin: `(0, 0)`", f"- Tolerance: `{plan.tolerance:g}`", f"- Source SHA-256: `{plan.source_hash}`",
        f"- Entity count: `{len(plan.entities)}`", "",
        "| # | ID | Type | Purpose | Geometry | Constraints | Reasoning |",
        "|---:|---|---|---|---|---|---|",
    ]
    clean = lambda text: text.replace("|", "\\|").replace("\n", " ")
    for index, entity in enumerate(plan.entities, 1):
        rows.append(
            f"| {index} | `{entity.id}` | `{entity.type}` | {clean(entity.purpose)} | `{_geometry(entity)}` | "
            f"{clean(_constraint_summary(entity))} | {clean(entity.reasoning)} |"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_manifest(plan: CompiledPlan, output_dir: Path, stem: str) -> None:
    payload = {
        "schema_version": plan.schema_version, "name": plan.name, "source_sha256": plan.source_hash,
        "units": plan.units, "origin": list(plan.origin), "tolerance": plan.tolerance,
        "entity_count": len(plan.entities),
        "entity_types": {kind: sum(entity.type == kind for entity in plan.entities) for kind in ("line", "circle", "arc")},
        "artifacts": [f"{stem}.aicad", f"{stem}.scr", f"{stem}.dxf", f"{stem}.audit.md"],
    }
    (output_dir / f"{stem}.manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_all(plan: CompiledPlan, output_dir: Path, stem: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "execution": output_dir / f"{stem}.aicad", "script": output_dir / f"{stem}.scr",
        "dxf": output_dir / f"{stem}.dxf", "audit": output_dir / f"{stem}.audit.md",
    }
    write_execution(plan, paths["execution"])
    write_script(plan, paths["script"])
    write_dxf(plan, paths["dxf"])
    write_audit(plan, paths["audit"])
    write_manifest(plan, output_dir, stem)
    return [*paths.values(), output_dir / f"{stem}.manifest.json"]
