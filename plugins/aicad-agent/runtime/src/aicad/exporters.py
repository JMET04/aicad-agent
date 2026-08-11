from __future__ import annotations

import hashlib
import json
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .engine import CompiledPlan, ResolvedArc, ResolvedCircle, ResolvedEntity, ResolvedLine, ResolvedText


_ARCHITECTURE_LAYER_STYLES: dict[str, tuple[int, int, str]] = {
    "WALL": (7, 60, "CONTINUOUS"), "COLUMN": (7, 70, "CONTINUOUS"),
    "OPENING": (7, 30, "CONTINUOUS"), "ROOM": (7, 25, "CONTINUOUS"),
    "STAIR": (7, 25, "CONTINUOUS"), "FURNITURE": (7, 18, "CONTINUOUS"),
    "CASEWORK": (7, 18, "CONTINUOUS"), "SANITARY": (7, 18, "CONTINUOUS"),
    "APPLIANCE": (7, 18, "CONTINUOUS"), "ROUTE": (7, 18, "DASHED"),
    "GRID": (7, 13, "CENTER2"), "GRID_BUBBLE": (7, 18, "CONTINUOUS"),
    "GRID_TEXT": (7, 18, "CONTINUOUS"), "TAG_TEXT": (7, 18, "CONTINUOUS"),
    "DIMENSION": (7, 18, "CONTINUOUS"), "TEXT": (7, 18, "CONTINUOUS"),
    "OVERHEAD": (7, 18, "DASHED2"),
}

_LINETYPE_PATTERNS: dict[str, tuple[str, tuple[float, ...]]] = {
    "CONTINUOUS": ("Solid line", ()),
    "DASHED": ("Dashed __ __ __", (12.7, -6.35)),
    "DASHED2": ("Dashed half scale", (6.35, -3.175)),
    "CENTER2": ("Center half scale", (9.525, -3.175, 1.5875, -1.5875)),
}


def _layer_style(layer: str) -> dict[str, int | str]:
    color, lineweight, linetype = _ARCHITECTURE_LAYER_STYLES.get(layer.upper(), (7, 25, "CONTINUOUS"))
    return {"color": color, "lineweight": lineweight, "linetype": linetype}


def _fmt(value: float) -> str:
    text = format(value, ".12g")
    return "0" if text in {"-0", "-0.0"} else text


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _cad_text(value: str) -> str:
    return "".join(char if ord(char) < 128 else f"\\U+{ord(char):04X}" for char in value)


def write_execution(plan: CompiledPlan, path: Path) -> None:
    protocol = "1" if plan.schema_version == "1.0" else "3"
    records = [f"AICAD|{protocol}|{plan.units.upper()}|{_fmt(plan.tolerance)}|{plan.source_hash}"]
    for entity in plan.entities:
        hashes = [_text_hash(entity.purpose), _text_hash(entity.reasoning)]
        proof = [_fmt(plan.origin[0]), _fmt(plan.origin[1]), _fmt(entity.anchor[0] - plan.origin[0]), _fmt(entity.anchor[1] - plan.origin[1])]
        prefix = [entity.id] if protocol == "1" else [entity.id, entity.layer]
        if isinstance(entity, ResolvedLine):
            values = [_fmt(entity.start[0]), _fmt(entity.start[1]), _fmt(entity.end[0]), _fmt(entity.end[1])]
            records.append("|".join(["LINE", *prefix, *values, *hashes, *(proof if protocol == "3" else [])]))
        elif isinstance(entity, ResolvedCircle):
            values = [_fmt(entity.center[0]), _fmt(entity.center[1]), _fmt(entity.radius)]
            records.append("|".join(["CIRCLE", *prefix, *values, *hashes, *proof]))
        elif isinstance(entity, ResolvedArc):
            values = [_fmt(entity.center[0]), _fmt(entity.center[1]), _fmt(entity.radius), _fmt(entity.start_angle_deg), _fmt(entity.end_angle_deg)]
            records.append("|".join(["ARC", *prefix, *values, *hashes, *proof]))
        else:
            values = [_fmt(entity.insert[0]), _fmt(entity.insert[1]), _fmt(entity.height), _fmt(entity.rotation_deg), _cad_text(entity.value)]
            records.append("|".join(["TEXT", *prefix, *values, *hashes, *proof]))
    records.append(f"END|{len(plan.entities)}|{plan.source_hash}")
    path.write_text("\n".join(records) + "\n", encoding="ascii", newline="\n")

def write_script(plan: CompiledPlan, path: Path) -> None:
    layers = sorted({entity.layer for entity in plan.entities})
    lines = ["_.UNDO", "_Begin"]
    for linetype in sorted({_layer_style(layer)["linetype"] for layer in layers} - {"CONTINUOUS"}):
        lines.extend(["_.-LINETYPE", "_Load", str(linetype), "acadiso.lin", ""])
    for layer in layers:
        style = _layer_style(layer)
        lines.extend(["_.-LAYER", "_Make", layer, "_Color", str(style["color"]), layer, "_Ltype", str(style["linetype"]), layer, "_Lweight", f"{int(style['lineweight']) / 100:.2f}", layer, ""])
    current_layer: str | None = None
    for entity in plan.entities:
        if entity.layer != current_layer:
            lines.extend(["_.-LAYER", "_Set", entity.layer, ""])
            current_layer = entity.layer
        if isinstance(entity, ResolvedLine):
            lines.extend(["_.LINE", f"{_fmt(entity.start[0])},{_fmt(entity.start[1])}", f"{_fmt(entity.end[0])},{_fmt(entity.end[1])}", ""])
        elif isinstance(entity, ResolvedCircle):
            lines.extend(["_.CIRCLE", f"{_fmt(entity.center[0])},{_fmt(entity.center[1])}", _fmt(entity.radius)])
        elif isinstance(entity, ResolvedArc):
            lines.extend(["_.ARC", "_C", f"{_fmt(entity.center[0])},{_fmt(entity.center[1])}", f"{_fmt(entity.start[0])},{_fmt(entity.start[1])}", "_A", _fmt((entity.end_angle_deg - entity.start_angle_deg) % 360)])
        else:
            lines.extend(["_.-TEXT", "_Justify", "_MC", f"{_fmt(entity.insert[0])},{_fmt(entity.insert[1])}", _fmt(entity.height), _fmt(entity.rotation_deg), _cad_text(entity.value)])
    lines.extend(["_.UNDO", "_End", "_.ZOOM", "_Extents", ""])
    path.write_text("\n".join(lines), encoding="ascii", newline="\n")

def _dxf_pair(code: int, value: str | int | float) -> str:
    return f"{code}\n{value}\n"


def write_dxf(plan: CompiledPlan, path: Path) -> None:
    """Write a standards-valid AutoCAD 2004 DXF with semantic layer styles.

    ezdxf owns the mandatory modern table/header structure.  This is essential
    because layer lineweight group 370 is illegal in R12 or an unspecified DXF.
    All non-ASCII text is explicitly escaped before writing, so the execution
    artifact remains ASCII while AutoCAD still reconstructs Unicode TEXT.
    """
    document = ezdxf.new("R2004", setup=False)
    document.units = 4  # millimetres
    document.header["$LWDISPLAY"] = 1
    layers = sorted({entity.layer for entity in plan.entities})
    for linetype in sorted({str(_layer_style(layer)["linetype"]) for layer in layers} - {"CONTINUOUS"}):
        if linetype not in document.linetypes:
            description, segments = _LINETYPE_PATTERNS[linetype]
            document.linetypes.add(linetype, pattern=[sum(abs(value) for value in segments), *segments], description=description)
    for layer in layers:
        style = _layer_style(layer)
        if layer in document.layers:
            record = document.layers.get(layer)
            record.dxf.color = int(style["color"])
            record.dxf.linetype = str(style["linetype"])
            record.dxf.lineweight = int(style["lineweight"])
        else:
            document.layers.add(
                layer,
                color=int(style["color"]),
                linetype=str(style["linetype"]),
                lineweight=int(style["lineweight"]),
            )
    modelspace = document.modelspace()
    for entity in plan.entities:
        attributes = {"layer": entity.layer}
        if isinstance(entity, ResolvedLine):
            modelspace.add_line(entity.start, entity.end, dxfattribs=attributes)
        elif isinstance(entity, ResolvedCircle):
            modelspace.add_circle(entity.center, entity.radius, dxfattribs=attributes)
        elif isinstance(entity, ResolvedArc):
            modelspace.add_arc(entity.center, entity.radius, entity.start_angle_deg, entity.end_angle_deg, dxfattribs=attributes)
        else:
            text = modelspace.add_text(
                _cad_text(entity.value),
                height=entity.height,
                rotation=entity.rotation_deg,
                dxfattribs={**attributes, "style": "Standard"},
            )
            text.set_placement(entity.insert, align=TextEntityAlignment.MIDDLE_CENTER)
    document.saveas(path, encoding="ascii", fmt="asc")
    path.read_bytes().decode("ascii")


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
    if isinstance(entity, ResolvedArc):
        return f"C=({_fmt(entity.center[0])}, {_fmt(entity.center[1])}); R={_fmt(entity.radius)}; A={_fmt(entity.start_angle_deg)}..{_fmt(entity.end_angle_deg)}"
    return f"P=({_fmt(entity.insert[0])}, {_fmt(entity.insert[1])}); H={_fmt(entity.height)}; R={_fmt(entity.rotation_deg)}; TEXT={entity.value}"


def write_audit(plan: CompiledPlan, path: Path) -> None:
    rows = [
        f"# {plan.name} - AI CAD audit", "", f"- Schema: `{plan.schema_version}`", f"- Domain: `{plan.domain}`", f"- Units: `{plan.units}`",
        "- Origin: `(0, 0)`", f"- Tolerance: `{plan.tolerance:g}`", f"- Source SHA-256: `{plan.source_hash}`",
        f"- Entity count: `{len(plan.entities)}`", "",
        "| # | ID | Type | Layer | Roles | Depends on | Editable | Purpose | Geometry | Constraints | Reasoning |",
        "|---:|---|---|---|---|---|---|---|---|---|---|",
    ]
    clean = lambda text: text.replace("|", "\\|").replace("\n", " ")
    for index, entity in enumerate(plan.entities, 1):
        rows.append(
            f"| {index} | `{entity.id}` | `{entity.type}` | `{entity.layer}` | {clean(', '.join(entity.roles) or '-')} | "
            f"{clean(', '.join(entity.depends_on) or 'origin')} | `{str(entity.editable).lower()}` | {clean(entity.purpose)} | `{_geometry(entity)}` | "
            f"{clean(_constraint_summary(entity))} | {clean(entity.reasoning)} |"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_manifest(plan: CompiledPlan, output_dir: Path, stem: str) -> None:
    payload = {
        "schema_version": plan.schema_version, "name": plan.name, "domain": plan.domain, "source_sha256": plan.source_hash,
        "units": plan.units, "origin": list(plan.origin), "tolerance": plan.tolerance,
        "entity_count": len(plan.entities),
        "entity_types": {kind: sum(entity.type == kind for entity in plan.entities) for kind in ("line", "circle", "arc", "text")},
        "layers": {layer: sum(entity.layer == layer for entity in plan.entities) for layer in sorted({entity.layer for entity in plan.entities})},
        "roles": {role: sum(role in entity.roles for entity in plan.entities) for role in sorted({role for entity in plan.entities for role in entity.roles})},
        "editable_entities": sum(entity.editable for entity in plan.entities),
        "dependency_edges": sum(len(entity.depends_on) for entity in plan.entities),
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
