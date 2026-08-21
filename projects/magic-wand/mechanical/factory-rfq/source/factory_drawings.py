from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path
from typing import Any

import ezdxf
from build123d import Axis, Box, Compound, Location
from ezdxf.enums import TextEntityAlignment

from factory_geometry import (
    ASSEMBLY_PLACEMENTS,
    PART_BASENAMES,
    PART_FACTORIES,
    P,
    WAND_PART_NUMBERS,
    make_assembly,
    make_part,
    make_receiver_assembly,
)


SHEET_W = 420.0
SHEET_H = 297.0
MARGIN = 10.0
TEXT_FRAMES: list[dict[str, Any]] = []


LAYER_SPECS = {
    "BORDER": {"color": 7, "linetype": "CONTINUOUS", "lineweight": 50},
    "OUTLINE": {"color": 7, "linetype": "CONTINUOUS", "lineweight": 50},
    "VISIBLE": {"color": 7, "linetype": "CONTINUOUS", "lineweight": 35},
    "HIDDEN": {"color": 8, "linetype": "DASHED", "lineweight": 18},
    "CENTER": {"color": 4, "linetype": "CENTER", "lineweight": 13},
    "DIMENSION": {"color": 2, "linetype": "CONTINUOUS", "lineweight": 18},
    "SECTION": {"color": 1, "linetype": "CONTINUOUS", "lineweight": 70},
    "HATCH": {"color": 1, "linetype": "CONTINUOUS", "lineweight": 13},
    "NOTES": {"color": 7, "linetype": "CONTINUOUS", "lineweight": 18},
    "TITLE_BLOCK": {"color": 7, "linetype": "CONTINUOUS", "lineweight": 25},
    "KEEP_OUT": {"color": 6, "linetype": "DASHDOT", "lineweight": 25},
}


PART_DFM = {
    "MW-M-001A": {
        "datum": "A = inside rear axial stop; B = XZ split plane; C = side button axis",
        "wall": "2.0 NOM / 1.8 MIN after vendor tooling tune",
        "gate": "Vendor DFM: rear tab/fan gate, keep vestige off grip and RF zone",
        "ejector": "Internal pads only; no pins on hand-contact finish or antenna wall",
        "features": "TRUE BREP: Ø8.2 side aperture, 12.8 guard, 4x M2 clearances",
    },
    "MW-M-001B": {
        "datum": "A = inside rear axial stop; B = XZ split plane; C = carrier rail",
        "wall": "2.0 NOM / 1.8 MIN after vendor tooling tune",
        "gate": "Vendor DFM: rear tab/fan gate, balance against upper shell",
        "ejector": "Internal pads beside pilots; keep USB-C/debug sealing lands clean",
        "features": "TRUE BREP: rounded USB-C + debug windows, rail, 4x pilots",
    },
    "MW-M-002": {
        "datum": "A = PCB support ledges; B = rear stop; C = key groove center",
        "wall": "1.5-1.6 NOM; avoid >60% rib-to-wall ratio without vendor review",
        "gate": "Vendor DFM: end gate at cable-relief end; weld lines off PCB bosses",
        "ejector": "Base underside pads; no pins on PCB support or key groove",
        "features": "PCB rails, 4 heat-stake bosses, switch shelf, cable reliefs",
    },
    "MW-M-003": {
        "datum": "A = rear exterior plane; B = common axis; C = asymmetric key",
        "wall": "2.0 NOM; energy director steel-safe pending weld DOE",
        "gate": "Vendor DFM: center sprue/subgate on hidden axial face",
        "ejector": "Hidden plug face; protect exposed flange and RF material zone",
        "features": "Ø22.6 plug, Ø27 flange, RF nonconductive, energy director",
    },
    "MW-M-004": {
        "datum": "A = shell collar plane; B = common axis; C = key slot",
        "wall": "2.0 NOM around Ø7.4 adhesive bore; verify sink at collar",
        "gate": "Vendor DFM: collar subgate away from witness vent",
        "ejector": "Plug face pads; no pins in bore or adhesive grooves",
        "features": "Ø7.4 bore, 3 adhesive grooves, Ø1.2 witness vent",
    },
    "MW-M-005": {
        "datum": "A = switch-contact land; B = stem axis; C = anti-rotation flat",
        "wall": "Solid small molding; coring not required at RFQ size",
        "gate": "Vendor DFM: underside micro-tab gate, vestige off tactile head",
        "ejector": "Stem end only; protect tactile head and anti-rotation flat",
        "features": "Ø7.6 stem, Ø10.8 head, 1.2 travel target",
    },
    "MW-P-001": {
        "datum": "A = rear cut face; B = pultrusion axis",
        "wall": "N/A - solid pultruded GFRP",
        "gate": "N/A - supplier cut/seal both ends",
        "ejector": "N/A",
        "features": "Ø7.0 ±0.1 x 220 ±1; deburr and seal both ends",
    },
    "MW-M-101": {
        "datum": "A = PCB support plane; B = left PCB locator; C = rear locator",
        "wall": "2.0 NOM / 1.8 MIN; base floor 2.0",
        "gate": "Vendor DFM: hidden bottom fan gate, flow away from connector lands",
        "ejector": "Floor underside pads; keep PCB supports and connector lands clean",
        "features": "3-2-1 PCB datums; connector apertures bound to final PCB interface",
    },
    "MW-M-102": {
        "datum": "A = top exterior plane; B = skirt center; C = poka-yoke corner",
        "wall": "2.0 NOM / 1.8 MIN; 0.15 per-side skirt clearance",
        "gate": "Vendor DFM: hidden rear tab gate outside RF window",
        "ejector": "Skirt/internal pads; no witness on Class-A top or RF window",
        "features": "3x lid clearances; nonconductive RF window; asymmetric nib",
    },
}


def _new_doc() -> tuple[Any, Any]:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add("DASHED", pattern=[0.75, 0.5, -0.25], description="hidden")
    if "CENTER" not in doc.linetypes:
        doc.linetypes.add("CENTER", pattern=[1.25, 0.7, -0.15, 0.15, -0.15], description="center")
    if "DASHDOT" not in doc.linetypes:
        doc.linetypes.add("DASHDOT", pattern=[1.5, 0.8, -0.2, 0.2, -0.2, 0.1, -0.2], description="keepout")
    for name, spec in LAYER_SPECS.items():
        if name not in doc.layers:
            doc.layers.add(name, **spec)
    if "AICAD" not in doc.appids:
        doc.appids.add("AICAD")
    return doc, doc.modelspace()


def _rect(msp, x0: float, y0: float, x1: float, y1: float, layer: str):
    return msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": layer},
    )


def _fit_lines(text: str, width: float, height: float, preferred_height: float) -> tuple[list[str], float]:
    h = preferred_height
    while h >= 1.35:
        max_chars = max(8, int(width / (0.62 * h)))
        lines: list[str] = []
        for raw in text.splitlines() or [""]:
            lines.extend(textwrap.wrap(raw, width=max_chars, break_long_words=False) or [""])
        if len(lines) * h * 1.28 <= height:
            return lines, h
        h -= 0.15
    max_chars = max(8, int(width / (0.62 * 1.35)))
    lines = []
    for raw in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(raw, width=max_chars, break_long_words=True) or [""])
    return lines[: max(1, int(height / 1.73))], 1.35


def _boxed_text(
    msp,
    frame_id: str,
    text: str,
    box: tuple[float, float, float, float],
    layer: str = "NOTES",
    preferred_height: float = 2.4,
    align: str = "left",
):
    x0, y0, x1, y1 = box
    _rect(msp, x0, y0, x1, y1, "TITLE_BLOCK" if layer == "TITLE_BLOCK" else layer)
    pad = 1.4
    lines, h = _fit_lines(text, x1 - x0 - 2 * pad, y1 - y0 - 2 * pad, preferred_height)
    top = y1 - pad - h
    entities = []
    for index, line in enumerate(lines):
        y = top - index * h * 1.28
        if align == "center":
            entity = msp.add_text(line, dxfattribs={"height": h, "layer": layer})
            entity.set_placement(((x0 + x1) / 2, y), align=TextEntityAlignment.MIDDLE_CENTER)
            estimated = (x0 + pad, y - h / 2, x1 - pad, y + h / 2)
        else:
            entity = msp.add_text(line, dxfattribs={"height": h, "layer": layer})
            entity.set_placement((x0 + pad, y), align=TextEntityAlignment.MIDDLE_LEFT)
            estimated = (x0 + pad, y - h / 2, min(x1 - pad, x0 + pad + len(line) * h * 0.62), y + h / 2)
        entity.set_xdata("AICAD", [(1000, frame_id), (1000, "text-in-frame")])
        entities.append(entity)
        TEXT_FRAMES.append(
            {
                "frame_id": frame_id,
                "frame_bbox": [x0, y0, x1, y1],
                "text": line,
                "text_bbox_estimate": [round(v, 3) for v in estimated],
                "overflow": not (
                    estimated[0] >= x0 and estimated[1] >= y0 and estimated[2] <= x1 and estimated[3] <= y1
                ),
            }
        )
    return entities


def _poly_points(edge, count: int = 24) -> list[tuple[float, float]]:
    try:
        return [
            (float(edge.position_at(index / (count - 1)).X), float(edge.position_at(index / (count - 1)).Y))
            for index in range(count)
        ]
    except Exception:
        return [(float(vertex.X), float(vertex.Y)) for vertex in edge.vertices()]


def _project(shape, camera: tuple[float, float, float], up: tuple[float, float, float]):
    visible, hidden = shape.project_to_viewport(camera, up)
    return [(edge, "VISIBLE") for edge in visible] + [(edge, "HIDDEN") for edge in hidden]


def _draw_view(
    msp,
    shape,
    view_id: str,
    title: str,
    cell: tuple[float, float, float, float],
    camera: tuple[float, float, float],
    up: tuple[float, float, float],
):
    x0, y0, x1, y1 = cell
    projected = _project(shape, camera, up)
    sampled = [(edge, layer, _poly_points(edge)) for edge, layer in projected]
    points = [point for _, _, edge_points in sampled for point in edge_points]
    if not points:
        return
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    scale = min((x1 - x0 - 8) / max(max_x - min_x, 0.1), (y1 - y0 - 10) / max(max_y - min_y, 0.1))
    tx = (x0 + x1) / 2 - (min_x + max_x) * scale / 2
    ty = (y0 + y1) / 2 - (min_y + max_y) * scale / 2 + 2
    entity_index = 0
    for _, layer, edge_points in sampled:
        transformed = [(px * scale + tx, py * scale + ty) for px, py in edge_points]
        if len(transformed) >= 2:
            entity = msp.add_lwpolyline(transformed, dxfattribs={"layer": layer})
            entity.set_xdata("AICAD", [(1000, view_id), (1000, f"{view_id}:edge:{entity_index}")])
            entity_index += 1
    center_x = (min_x + max_x) * scale / 2 + tx
    center_y = (min_y + max_y) * scale / 2 + ty
    msp.add_line((x0 + 2, center_y), (x1 - 2, center_y), dxfattribs={"layer": "CENTER"})
    msp.add_line((center_x, y0 + 3), (center_x, y1 - 3), dxfattribs={"layer": "CENTER"})
    _boxed_text(msp, f"{view_id}:label", title, (x0 + 2, y0, x1 - 2, y0 + 6), "TITLE_BLOCK", 2.2, "center")


def _arrow(msp, point: tuple[float, float], angle: float):
    x, y = point
    length = 2.2
    wing = 0.8
    ux = math.cos(angle)
    uy = math.sin(angle)
    nx = -uy
    ny = ux
    msp.add_lwpolyline(
        [(x, y), (x + length * ux + wing * nx, y + length * uy + wing * ny), (x + length * ux - wing * nx, y + length * uy - wing * ny)],
        close=True,
        dxfattribs={"layer": "DIMENSION"},
    )


def _dimension_h(msp, x0: float, x1: float, object_y: float, dim_y: float, label: str, frame_id: str):
    msp.add_line((x0, object_y), (x0, dim_y), dxfattribs={"layer": "DIMENSION"})
    msp.add_line((x1, object_y), (x1, dim_y), dxfattribs={"layer": "DIMENSION"})
    msp.add_line((x0, dim_y), (x1, dim_y), dxfattribs={"layer": "DIMENSION"})
    _arrow(msp, (x0, dim_y), 0)
    _arrow(msp, (x1, dim_y), math.pi)
    box_w = max(13.0, len(label) * 2.0)
    _boxed_text(msp, frame_id, label, ((x0 + x1 - box_w) / 2, dim_y - 3.2, (x0 + x1 + box_w) / 2, dim_y + 3.2), "DIMENSION", 2.2, "center")


def _sheet_frame(msp, drawing_number: str, title: str, revision: str, status: str):
    _rect(msp, MARGIN, MARGIN, SHEET_W - MARGIN, SHEET_H - MARGIN, "BORDER")
    _boxed_text(msp, f"{drawing_number}:header", f"{drawing_number}  |  {title}", (12, 278, 408, 286), "TITLE_BLOCK", 3.2, "center")
    title_x = 258
    _boxed_text(msp, f"{drawing_number}:title", title, (title_x, 10, 408, 30), "TITLE_BLOCK", 3.0, "center")
    _boxed_text(msp, f"{drawing_number}:number", f"DWG: {drawing_number}", (title_x, 30, 333, 42), "TITLE_BLOCK", 2.4)
    _boxed_text(msp, f"{drawing_number}:rev", f"REV: {revision}", (333, 30, 370, 42), "TITLE_BLOCK", 2.4)
    _boxed_text(msp, f"{drawing_number}:sheet", "SHEET 1/1", (370, 30, 408, 42), "TITLE_BLOCK", 2.2)
    _boxed_text(msp, f"{drawing_number}:stage", status, (title_x, 42, 408, 55), "TITLE_BLOCK", 2.3, "center")


def _part_notes(part_number: str) -> str:
    part = P["parts"][part_number]
    dfm = PART_DFM[part_number]
    molding = P["molding_defaults"]
    return "\n".join(
        [
            f"1 MATERIAL: {part['material']}",
            f"2 PROCESS: {part['process']}; FINISH: {molding['surface']}",
            f"3 DRAFT: {part.get('mold_pull', 'N/A')} / {molding['general_draft_deg']} deg general",
            f"4 WALL: {dfm['wall']}",
            f"5 PARTING: {part.get('parting_line', 'supplier / drawing specific')}",
            f"6 GATE: {dfm['gate']}",
            f"7 EJECTOR: {dfm['ejector']}",
            f"8 DATUMS: {dfm['datum']}",
            f"9 FEATURES: {dfm['features']}",
            "10 GENERAL: ISO 2768-m only where invoked; ISO 13715 break 0.2-0.4.",
            "11 RFQ/DFM INPUT ONLY. NOT TOOL-STEEL-CUT OR PRODUCTION RELEASE.",
        ]
    )


def generate_part_drawing(part_number: str, output: Path) -> dict[str, Any]:
    doc, msp = _new_doc()
    part_name = P["parts"][part_number]["name"].replace("_", " ").upper()
    _sheet_frame(msp, part_number, part_name, P["revision"], "DFM/RFQ INPUT · REVIEW ONLY · NOT TOOL RELEASE")
    shape = make_part(part_number)
    _draw_view(msp, shape, f"{part_number}:front", "FRONT", (14, 187, 142, 276), (0, -1000, 0), (0, 0, 1))
    _draw_view(msp, shape, f"{part_number}:right", "RIGHT", (145, 187, 273, 276), (1000, 0, 0), (0, 0, 1))
    _draw_view(msp, shape, f"{part_number}:top", "TOP", (276, 187, 406, 276), (0, 0, 1000), (0, 1, 0))
    _draw_view(msp, shape, f"{part_number}:iso", "ISOMETRIC", (276, 91, 406, 181), (1000, -1000, 800), (0, 0, 1))
    bbox = shape.bounding_box(optimal=True)
    _dimension_h(msp, 20, 132, 184, 178, f"ENVELOPE X {bbox.size.X:.2f}", f"{part_number}:dim-x")
    _dimension_h(msp, 151, 267, 184, 178, f"ENVELOPE Z {bbox.size.Z:.2f}", f"{part_number}:dim-z")
    # A-A section graphic deliberately uses a separate heavy section profile
    # and thin hatch layer so the user can switch both independently.
    _rect(msp, 14, 91, 142, 171, "SECTION")
    for offset in range(-40, 160, 8):
        x_start = max(16.0, 16.0 + offset)
        y_start = 93.0
        x_end = min(140.0, x_start + 55.0)
        if x_start < 140:
            msp.add_line((x_start, y_start), (x_end, min(169.0, y_start + x_end - x_start)), dxfattribs={"layer": "HATCH"})
    _boxed_text(msp, f"{part_number}:section-label", "SECTION A-A · HATCH SCHEMATIC; USE STEP BREP FOR CUT GEOMETRY", (16, 93, 140, 101), "TITLE_BLOCK", 1.9, "center")
    _boxed_text(msp, f"{part_number}:notes", _part_notes(part_number), (14, 12, 252, 85), "NOTES", 2.15)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output)
    return {
        "drawing_number": part_number,
        "title": part_name,
        "kind": "manufacturing_part",
        "file": output.name,
        "views": ["front", "right", "top", "isometric", "section_A-A"],
        "layers": list(LAYER_SPECS),
        "source_part": part_number,
    }


def _assembly_notes(drawing_number: str, kind: str) -> str:
    if drawing_number.startswith("MW-A-101"):
        interface = P["interfaces"]["receiver_enclosure"]
        return "\n".join(
            [
                f"1 PCB ENVELOPE: {interface['board']['outline_x']} x {interface['board']['outline_y']} x {interface['board']['thickness']} mm.",
                f"2 INTERFACE STATUS: {interface['interface_status']}.",
                "3 CONNECTOR OPENINGS / MOUNT POSTS SHALL MATCH bound electronics interface JSON only.",
                "4 RF WINDOW: nonconductive resin; no metal fastener/coating/vent above keepout.",
                "5 ASSEMBLY: seat PCB to A/B/C datums, verify connectors, fit lid, install 3x M2.5.",
                "6 TORQUE: pending selected thread-forming screw supplier and strip-torque test.",
                "7 VERIFY 3D STEP FIT AND INTERFERENCE REPORT BEFORE RFQ RESPONSE.",
                "8 DFM/RFQ INPUT ONLY. NOT TOOL-STEEL-CUT OR PRODUCTION RELEASE.",
            ]
        )
    return "\n".join(
        [
            "1 DATUM A: rear-cap exterior plane. DATUM B: common longitudinal axis.",
            "2 ASSEMBLE carrier and PCB/harness before closing split shells.",
            "3 VERIFY USB-C/debug/button alignment before 4x M2 screws.",
            "4 KEEP FASTENERS, battery and harness outside declared RF keepout.",
            "5 BOND GFRP IN Ø7.4 connector bore; adhesive/process supplier pending.",
            "6 REAR CAP ENERGY DIRECTOR REQUIRES ULTRASONIC WELD DOE.",
            "7 CHECK BOM, work instruction and machine interference report.",
            f"8 VIEW TYPE: {kind}. DFM/RFQ INPUT ONLY; NOT TOOL RELEASE.",
        ]
    )


def generate_assembly_drawing(
    drawing_number: str,
    title: str,
    kind: str,
    shape,
    output: Path,
) -> dict[str, Any]:
    doc, msp = _new_doc()
    _sheet_frame(msp, drawing_number, title, P["revision"], "DFM/RFQ INPUT · REVIEW ONLY · NOT TOOL RELEASE")
    _draw_view(msp, shape, f"{drawing_number}:front", "FRONT", (14, 166, 205, 276), (0, -1000, 0), (0, 0, 1))
    _draw_view(msp, shape, f"{drawing_number}:iso", "ISOMETRIC", (212, 166, 406, 276), (1000, -1000, 800), (0, 0, 1))
    _draw_view(msp, shape, f"{drawing_number}:top", "TOP / INTERFACE", (258, 63, 406, 158), (0, 0, 1000), (0, 1, 0))
    _boxed_text(msp, f"{drawing_number}:notes", _assembly_notes(drawing_number, kind), (14, 12, 252, 158), "NOTES", 2.25)
    if drawing_number.startswith("MW-A-101"):
        keepout = P["interfaces"]["receiver_enclosure"]["rf_keepout"]
        _boxed_text(
            msp,
            f"{drawing_number}:rf",
            "RF KEEP-OUT\n" + "\n".join(keepout["mechanical_rules"]),
            (258, 63, 330, 100),
            "KEEP_OUT",
            1.9,
        )
    else:
        _boxed_text(
            msp,
            f"{drawing_number}:harness",
            "HARNESS INTERFACE\nJ_USB-C -> PCB\nSW1 -> PRESS-TO-ARM\nBAT -> CARRIER BAY\nGFRP -> CONNECTOR BORE",
            (258, 104, 406, 158),
            "NOTES",
            2.0,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output)
    return {
        "drawing_number": drawing_number,
        "title": title,
        "kind": kind,
        "file": output.name,
        "views": ["front", "isometric", "top_interface"],
        "layers": list(LAYER_SPECS),
    }


def generate_all(output_dir: Path, report_dir: Path) -> dict[str, Any]:
    global TEXT_FRAMES
    TEXT_FRAMES = []
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    for part_number in PART_FACTORIES:
        index.append(generate_part_drawing(part_number, output_dir / f"{PART_BASENAMES[part_number]}.dxf"))
    index.extend(
        [
            generate_assembly_drawing("MW-A-001", "MAGIC WAND GENERAL ASSEMBLY", "assembly", make_assembly(False), output_dir / "MW-A-001_wand_general_assembly.dxf"),
            generate_assembly_drawing("MW-A-001-EX", "MAGIC WAND EXPLODED", "exploded", make_assembly(True), output_dir / "MW-A-001_wand_exploded.dxf"),
            generate_assembly_drawing("MW-A-001-SE", "MAGIC WAND SECTION A-A", "section", make_assembly(False), output_dir / "MW-A-001_wand_section_A-A.dxf"),
            generate_assembly_drawing("MW-A-001-HI", "MAGIC WAND HARNESS INTERFACE", "harness_interface", make_assembly(False), output_dir / "MW-A-001_wand_harness_interface.dxf"),
            generate_assembly_drawing("MW-A-101", "RECEIVER ENCLOSURE ASSEMBLY", "assembly", make_receiver_assembly(False), output_dir / "MW-A-101_receiver_assembly.dxf"),
            generate_assembly_drawing("MW-A-101-EX", "RECEIVER ENCLOSURE EXPLODED", "exploded", make_receiver_assembly(True), output_dir / "MW-A-101_receiver_exploded.dxf"),
            generate_assembly_drawing("MW-A-101-SE", "RECEIVER ENCLOSURE SECTION / INTERFACE", "section_interface", make_receiver_assembly(False), output_dir / "MW-A-101_receiver_section_interface.dxf"),
        ]
    )
    overflow = [item for item in TEXT_FRAMES if item["overflow"]]
    audit = {
        "schema": "aicad_factory_drawing_text_frame_audit_v1",
        "sheet": {"width_mm": SHEET_W, "height_mm": SHEET_H, "format": "A3 landscape"},
        "drawing_count": len(index),
        "text_entity_count": len(TEXT_FRAMES),
        "overflow_count": len(overflow),
        "passed": len(overflow) == 0,
        "required_layers": LAYER_SPECS,
        "frames": TEXT_FRAMES,
    }
    (report_dir / "drawing-index.json").write_text(json.dumps({"schema": "aicad_factory_drawing_index_v1", "drawings": index}, indent=2) + "\n", encoding="utf-8")
    (report_dir / "drawing-text-frame-audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return {"index": index, "audit": audit}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    result = generate_all(root / "outputs" / "2d", root / "reports")
    print(json.dumps({"drawing_count": len(result["index"]), "overflow_count": result["audit"]["overflow_count"]}, indent=2))

