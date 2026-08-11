#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import ezdxf


EXPECTED_LAYERS: dict[str, tuple[int, str]] = {
    "WALL": (60, "CONTINUOUS"),
    "COLUMN": (70, "CONTINUOUS"),
    "OPENING": (30, "CONTINUOUS"),
    "ROOM": (25, "CONTINUOUS"),
    "STAIR": (25, "CONTINUOUS"),
    "FURNITURE": (18, "CONTINUOUS"),
    "ROUTE": (18, "DASHED"),
    "GRID": (13, "CENTER2"),
    "GRID_BUBBLE": (18, "CONTINUOUS"),
    "GRID_TEXT": (18, "CONTINUOUS"),
    "TAG_TEXT": (18, "CONTINUOUS"),
    "DIMENSION": (18, "CONTINUOUS"),
    "TEXT": (18, "CONTINUOUS"),
}
REQUIRED_ENTITY_LAYERS = {"WALL", "COLUMN", "OPENING", "FURNITURE", "ROUTE", "GRID", "GRID_BUBBLE", "GRID_TEXT", "TAG_TEXT", "DIMENSION"}
TOL = 1e-6


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _all_entities(doc: ezdxf.document.Drawing) -> list[Any]:
    entities = list(doc.modelspace())
    for block in doc.blocks:
        entities.extend(list(block))
    return entities


def _effective_linetype(doc: ezdxf.document.Drawing, entity: Any) -> str:
    name = str(entity.dxf.get("linetype", "BYLAYER")).upper()
    if name in {"BYLAYER", ""}:
        layer_name = str(entity.dxf.get("layer", "0"))
        if layer_name in doc.layers:
            name = str(doc.layers.get(layer_name).dxf.linetype).upper()
    return name


def _text_value(entity: Any) -> str:
    if entity.dxftype() == "MTEXT":
        return str(entity.plain_text()).strip()
    return str(entity.dxf.get("text", "")).strip()


def _xy(value: Any) -> tuple[float, float]:
    return float(value[0]), float(value[1])


def _axis_contexts(doc: ezdxf.document.Drawing) -> list[tuple[str, list[Any]]]:
    contexts: list[tuple[str, list[Any]]] = []
    modelspace = list(doc.modelspace())
    if any(str(entity.dxf.get("layer", "")) == "GRID_BUBBLE" for entity in modelspace):
        contexts.append(("MODELSPACE", modelspace))
    for block in doc.blocks:
        entities = list(block)
        if any(str(entity.dxf.get("layer", "")) == "GRID_BUBBLE" for entity in entities):
            contexts.append((str(block.name), entities))
    return contexts


def _audit_axis_groups(doc: ezdxf.document.Drawing) -> tuple[dict[str, bool], dict[str, Any]]:
    contexts = _axis_contexts(doc)
    details: dict[str, Any] = {}
    complete = centered_all = tangent_all = identifiers_all = xdata_all = bool(contexts)
    for name, entities in contexts:
        circles = [e for e in entities if e.dxftype() == "CIRCLE" and e.dxf.layer == "GRID_BUBBLE"]
        texts = [e for e in entities if e.dxftype() in {"TEXT", "MTEXT"} and e.dxf.layer == "GRID_TEXT"]
        lines = [e for e in entities if e.dxftype() == "LINE" and e.dxf.layer == "GRID"]
        rows: list[dict[str, Any]] = []
        for circle in circles:
            center, radius = _xy(circle.dxf.center), float(circle.dxf.radius)
            centered = [text for text in texts if math.dist(center, _xy(text.dxf.insert)) <= TOL]
            label = _text_value(centered[0]) if len(centered) == 1 else ""
            tangent = False
            for line in lines:
                start, end = _xy(line.dxf.start), _xy(line.dxf.end)
                vertical = abs(start[0] - end[0]) <= TOL and abs(center[0] - start[0]) <= TOL
                horizontal = abs(start[1] - end[1]) <= TOL and abs(center[1] - start[1]) <= TOL
                if (vertical or horizontal) and any(abs(math.dist(center, point) - radius) <= TOL for point in (start, end)):
                    tangent = True
                    break
            rows.append({
                "center": list(center), "radius": radius, "label": label,
                "centeredTextCount": len(centered), "tangentToGridEndpoint": tangent,
                "hasAicadXData": bool(circle.has_xdata("AICAD")),
            })
        label_counts = Counter(row["label"] for row in rows)
        well_formed = all(label and (label.isdigit() or (label.isalpha() and label.isupper())) for label in label_counts)
        paired = bool(label_counts) and all(count == 2 for count in label_counts.values())
        orientation_ok = True
        for label in label_counts:
            centers = [row["center"] for row in rows if row["label"] == label]
            coordinate_index = 0 if label.isdigit() else 1
            orientation_ok = orientation_ok and len({round(center[coordinate_index], 6) for center in centers}) == 1
        context_complete = len(circles) > 0 and len(circles) == len(texts) and len(lines) == len(label_counts) and paired and well_formed and orientation_ok
        context_centered = bool(rows) and all(row["centeredTextCount"] == 1 for row in rows)
        context_tangent = bool(rows) and all(row["tangentToGridEndpoint"] for row in rows)
        context_xdata = bool(rows) and all(row["hasAicadXData"] for row in rows)
        complete = complete and context_complete
        centered_all = centered_all and context_centered
        tangent_all = tangent_all and context_tangent
        identifiers_all = identifiers_all and paired and well_formed and orientation_ok
        xdata_all = xdata_all and context_xdata
        details[name] = {
            "gridLines": len(lines), "axisBubbles": len(circles), "axisTexts": len(texts),
            "identifierCounts": dict(sorted(label_counts.items())), "complete": context_complete,
            "centered": context_centered, "tangent": context_tangent, "xdataBound": context_xdata,
            "circles": rows,
        }
    return {
        "axis_groups_complete": complete,
        "axis_identifiers_centered": centered_all,
        "axis_lines_tangent_to_bubbles": tangent_all,
        "axis_identifiers_unique_and_paired": identifiers_all,
        "axis_bubbles_preserve_aicad_xdata": xdata_all,
    }, details


def audit_dxf(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    doc = ezdxf.readfile(source)
    entities = _all_entities(doc)
    counts = Counter(str(entity.dxf.get("layer", "0")) for entity in entities)
    layer_results: dict[str, Any] = {}
    for name, (expected_weight, expected_type) in EXPECTED_LAYERS.items():
        if name not in doc.layers:
            layer_results[name] = {"pass": False, "reason": "missing layer"}
            continue
        layer = doc.layers.get(name)
        actual_weight = int(layer.dxf.lineweight)
        actual_type = str(layer.dxf.linetype).upper()
        layer_results[name] = {
            "pass": actual_weight == expected_weight and actual_type == expected_type,
            "expectedLineweight": expected_weight,
            "actualLineweight": actual_weight,
            "expectedLinetype": expected_type,
            "actualLinetype": actual_type,
            "entityCount": counts.get(name, 0),
        }

    line_entities = [entity for entity in entities if entity.dxftype() in {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE"}]
    effective_types = Counter(_effective_linetype(doc, entity) for entity in line_entities)
    weights = {name: result.get("actualLineweight", -999) for name, result in layer_results.items()}
    hierarchy_ok = (
        min(weights.get("WALL", -999), weights.get("COLUMN", -999))
        > max(weights.get("OPENING", 999), weights.get("ROOM", 999), weights.get("STAIR", 999))
        > max(weights.get("FURNITURE", 999), weights.get("ROUTE", 999), weights.get("GRID", 999), weights.get("DIMENSION", 999))
    )
    effective_distinction = (
        effective_types.get("CONTINUOUS", 0) > 0
        and sum(value for name, value in effective_types.items() if name.startswith("DASHED")) > 0
        and sum(value for name, value in effective_types.items() if name.startswith("CENTER")) > 0
    )

    dimensions = [entity for entity in entities if entity.dxftype() == "DIMENSION" and entity.dxf.layer == "DIMENSION"]
    dimension_text_native = all(str(entity.dxf.get("text", "<>")) in {"", "<>"} for entity in dimensions)
    dimstyle_ok = False
    dimstyle_values: dict[str, Any] = {}
    if "AICAD_ARCH" in doc.dimstyles:
        style = doc.dimstyles.get("AICAD_ARCH")
        names = ("dimtxt", "dimasz", "dimtsz", "dimexo", "dimexe", "dimgap", "dimtad", "dimdec", "dimzin", "dimlunit")
        dimstyle_values = {name: getattr(style.dxf, name) for name in names}
        dimstyle_ok = (
            float(dimstyle_values["dimtxt"]) >= 250.0
            and float(dimstyle_values["dimtsz"]) > 0.0
            and float(dimstyle_values["dimexo"]) > 0.0
            and float(dimstyle_values["dimexe"]) > 0.0
            and int(dimstyle_values["dimtad"]) == 1
            and int(dimstyle_values["dimdec"]) == 0
            and int(dimstyle_values["dimlunit"]) == 2
        )

    axis_checks, axis_details = _audit_axis_groups(doc)
    tag_values = [
        _text_value(entity)
        for entity in entities
        if entity.dxftype() in {"TEXT", "MTEXT"} and entity.dxf.layer == "TAG_TEXT"
    ]
    annotation_classes = {
        "doorTag": any(__import__("re").fullmatch(r"D\d+", value) for value in tag_values),
        "windowTag": any(__import__("re").fullmatch(r"W\d+", value) for value in tag_values),
        "stairDirection": any(value.startswith("UP") or "上" in value for value in tag_values),
        "levelDatum": any(value.startswith("标高") for value in tag_values),
        "northIndicator": any(value.startswith("N") and "↑" in value for value in tag_values),
    }
    header = {
        "measurement": int(doc.header.get("$MEASUREMENT", 0)),
        "insunits": int(doc.header.get("$INSUNITS", 0)),
        "ltscale": float(doc.header.get("$LTSCALE", 1.0)),
        "psltscale": int(doc.header.get("$PSLTSCALE", 0)),
    }
    checks = {
        "required_layers_present_and_used": all(name in doc.layers and counts.get(name, 0) > 0 for name in REQUIRED_ENTITY_LAYERS),
        "layer_profile_exact": all(result["pass"] for result in layer_results.values()),
        "cut_projection_annotation_hierarchy": hierarchy_ok,
        "effective_solid_dashed_center_distinction": effective_distinction,
        "native_dimensions_present": len(dimensions) > 0,
        "native_dimension_text_not_overridden": dimension_text_native,
        "architectural_dimstyle_persisted": dimstyle_ok,
        "millimetre_units_and_visible_linetype_scale": header["measurement"] == 1 and header["insunits"] == 4 and 1.0 <= header["ltscale"] <= 1000.0,
        **axis_checks,
        "concept_annotation_classes_present": all(annotation_classes.values()),
    }
    status = "pass" if all(checks.values()) else "failed"
    return {
        "schema": "aicad_architectural_drafting_validation_v2",
        "status": status,
        "source": {"path": str(source), "sha256": _sha256(source)},
        "checks": checks,
        "layers": layer_results,
        "entityCounts": dict(sorted(counts.items())),
        "effectiveLinetypes": dict(sorted(effective_types.items())),
        "nativeDimensionCount": len(dimensions),
        "dimensionStyle": {"name": "AICAD_ARCH", "values": dimstyle_values},
        "axisGrid": axis_details,
        "annotationCompleteness": {"classes": annotation_classes, "tagValues": tag_values},
        "header": header,
        "rootCause": {
            "causeClass": "drafting_semantics_or_annotation_identity_not_propagated",
            "explanation": "Valid geometry is insufficient when linetype, lineweight, DIMSTYLE or complete axis identity groups are absent from any output renderer.",
        },
        "preventionRule": {
            "status": "candidate",
            "ruleEnabled": False,
            "rules": [f"ARCH-D{i:03d}" for i in range(1, 14)],
        },
        "reviewPolicy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit architectural DXF line hierarchy, native dimensions and complete axis groups.")
    parser.add_argument("dxf", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_dxf(args.dxf)
    output = args.output or args.dxf.with_suffix(".architecture-qa.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["status"] == "pass", "status": result["status"], "output": str(output.resolve())}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
