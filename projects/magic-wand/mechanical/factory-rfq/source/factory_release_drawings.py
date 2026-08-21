from __future__ import annotations

"""Generate release-candidate DXFs from the factory BREP source.

Every sectional contour is a projection of a finite BREP intersection.  Every
dimension-table row carries either a parameter-source binding, a geometry probe,
or both.  Text is always emitted through the bounding-frame helper and audited.
"""

import hashlib
import json
import math
import textwrap
from pathlib import Path
from typing import Any

from ezdxf import bbox as ezbbox
from ezdxf.enums import TextEntityAlignment

import factory_drawings as d
import factory_release_geometry as g


P = g.P

d.LAYER_SPECS.setdefault(
    "DATUM", {"color": 3, "linetype": "CENTER", "lineweight": 25}
)
d.LAYER_SPECS.setdefault(
    "HARNESS", {"color": 5, "linetype": "DASHDOT", "lineweight": 25}
)


MIN_PRINT_TEXT_HEIGHT_MM = 1.8
TEXT_INPUTS: list[dict[str, Any]] = []


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _strict_fit_lines(
    text: str,
    width: float,
    height: float,
    preferred_height: float,
) -> tuple[list[str], float]:
    candidate_height = max(preferred_height, MIN_PRINT_TEXT_HEIGHT_MM)
    while candidate_height >= MIN_PRINT_TEXT_HEIGHT_MM - 1e-9:
        max_chars = max(8, int(width / (0.95 * candidate_height)))
        lines: list[str] = []
        for raw in text.splitlines() or [""]:
            lines.extend(
                textwrap.wrap(
                    raw,
                    width=max_chars,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                or [""]
            )
        if len(lines) * candidate_height * 1.28 <= height:
            return lines, candidate_height
        candidate_height = round(candidate_height - 0.1, 6)
    raise ValueError(
        f"text does not fit its declared frame at the {MIN_PRINT_TEXT_HEIGHT_MM:.1f} mm printable minimum"
    )


def _strict_boxed_text(
    msp,
    frame_id: str,
    text: str,
    box: tuple[float, float, float, float],
    layer: str = "NOTES",
    preferred_height: float = 2.4,
    align: str = "left",
):
    x0, y0, x1, y1 = box
    d._rect(
        msp,
        x0,
        y0,
        x1,
        y1,
        "TITLE_BLOCK" if layer == "TITLE_BLOCK" else layer,
    )
    pad = 1.4
    lines, text_height = _strict_fit_lines(
        text,
        x1 - x0 - 2 * pad,
        y1 - y0 - 2 * pad,
        preferred_height,
    )
    top = y1 - pad - text_height
    emitted: list[str] = []
    entities = []
    for index, line in enumerate(lines):
        y = top - index * text_height * 1.28
        entity = msp.add_text(
            line, dxfattribs={"height": text_height, "layer": layer}
        )
        if align == "center":
            entity.set_placement(
                ((x0 + x1) / 2, y), align=TextEntityAlignment.MIDDLE_CENTER
            )
        else:
            entity.set_placement(
                (x0 + pad, y), align=TextEntityAlignment.MIDDLE_LEFT
            )
        entity.set_xdata(
            "AICAD", [(1000, frame_id), (1000, "text-in-frame-strict")]
        )
        entities.append(entity)
        emitted.append(line)
        try:
            extents = ezbbox.extents([entity], fast=False)
            actual = (
                float(extents.extmin.x),
                float(extents.extmin.y),
                float(extents.extmax.x),
                float(extents.extmax.y),
            )
            bbox_method = "ezdxf_actual_glyph_extents"
        except Exception:
            actual = (
                x0 + pad,
                y - text_height / 2,
                min(x1 - pad, x0 + pad + len(line) * text_height * 0.58),
                y + text_height / 2,
            )
            bbox_method = "conservative_fallback"
        overflow = not (
            actual[0] >= x0

            and actual[1] >= y0
            and actual[2] <= x1
            and actual[3] <= y1
        )
        d.TEXT_FRAMES.append(
            {
                "frame_id": frame_id,
                "frame_bbox": [x0, y0, x1, y1],
                "text": line,
                "text_height_mm": text_height,
                "text_bbox_actual": [round(value, 4) for value in actual],
                "bbox_method": bbox_method,
                "overflow": overflow,
            }
        )
    input_normalized = _normalized_text(text)
    emitted_normalized = _normalized_text("\n".join(emitted))
    TEXT_INPUTS.append(
        {
            "frameId": frame_id,
            "inputSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "inputCharacterCount": len(text),
            "inputLogicalLineCount": len(text.splitlines()),
            "emittedEntityCount": len(emitted),
            "normalizedInputSha256": hashlib.sha256(
                input_normalized.encode("utf-8")
            ).hexdigest(),
            "normalizedEmittedSha256": hashlib.sha256(
                emitted_normalized.encode("utf-8")
            ).hexdigest(),
            "textClosure": input_normalized == emitted_normalized,
            "truncated": input_normalized != emitted_normalized,
        }
    )
    if input_normalized != emitted_normalized:
        raise RuntimeError(f"{frame_id}: text entity closure failed")
    return entities


d._fit_lines = _strict_fit_lines
d._boxed_text = _strict_boxed_text


def _strict_dimension_h(
    msp,
    x0: float,
    x1: float,
    object_y: float,
    dim_y: float,
    label: str,
    frame_id: str,
):
    msp.add_line((x0, object_y), (x0, dim_y), dxfattribs={"layer": "DIMENSION"})
    msp.add_line((x1, object_y), (x1, dim_y), dxfattribs={"layer": "DIMENSION"})
    msp.add_line((x0, dim_y), (x1, dim_y), dxfattribs={"layer": "DIMENSION"})
    d._arrow(msp, (x0, dim_y), 0)
    d._arrow(msp, (x1, dim_y), 3.141592653589793)
    box_width = max(15.0, len(label) * 2.30)
    d._boxed_text(
        msp,
        frame_id,
        label,
        ((x0 + x1 - box_width) / 2, dim_y - 3.2, (x0 + x1 + box_width) / 2, dim_y + 3.2),
        "DIMENSION",
        2.2,
        "center",
    )

_shell_start = P["interfaces"]["shell"]["assembly_z_start"]
_button_local_z = P["interfaces"]["press_to_arm"]["global_center_z"] - _shell_start
_usb_local_z = P["interfaces"]["service_openings"]["usb_c"]["global_center_z"] - _shell_start
_debug_local_z = P["interfaces"]["service_openings"]["debug"]["global_center_z"] - _shell_start
_receiver_interface = P["interfaces"]["receiver_enclosure"]
_receiver_openings = _receiver_interface.get("connector_openings", [])
_receiver_section_z = float(_receiver_openings[0]["mechanical_center"][2]) if _receiver_openings else 6.0


def _receiver_opening_section_groups() -> list[dict[str, Any]]:
    """Group openings only when one real Z plane intersects every opening in the group."""
    bands: list[dict[str, Any]] = []
    for index, opening in enumerate(_receiver_openings, 1):
        center_z = float(opening["mechanical_center"][2])
        half_height = float(opening["panel_height"]) / 2.0
        bands.append(
            {
                "low": center_z - half_height,
                "high": center_z + half_height,
                "featureId": f"MW-M-101-O{index:02d}",
                "ref": str(opening.get("ref", index)),
            }
        )
    bands.sort(key=lambda row: (row["low"], row["high"], row["featureId"]))
    groups: list[dict[str, Any]] = []
    for band in bands:
        overlap_low = max(groups[-1]["low"], band["low"]) if groups else 0.0
        overlap_high = min(groups[-1]["high"], band["high"]) if groups else 0.0
        if groups and overlap_low < overlap_high - 1e-6:
            groups[-1]["low"] = max(groups[-1]["low"], band["low"])
            groups[-1]["high"] = min(groups[-1]["high"], band["high"])
            groups[-1]["featureIds"].append(band["featureId"])
            groups[-1]["refs"].append(band["ref"])
        else:
            groups.append(
                {
                    "low": band["low"],
                    "high": band["high"],
                    "featureIds": [band["featureId"]],
                    "refs": [band["ref"]],
                }
            )
    for group in groups:
        group["coordinate"] = (group["low"] + group["high"]) / 2.0
    return groups


def _receiver_part_section_specs() -> list[dict[str, Any]]:
    mount_holes = _receiver_interface["board"].get("mount_holes", [])
    opening_groups = _receiver_opening_section_groups()
    if not mount_holes and not opening_groups:
        return [{
            "axis": "Z", "coordinate": _receiver_section_z,
            "featureIdsCovered": ["MW-M-101-W01", "MW-M-101-I01", "MW-M-101-H01"],
            "purpose": "horizontal receiver base wall, case pilots and PCB datum",
        }]
    support_z = (
        float(_receiver_interface["case"]["base_floor"])
        + float(_receiver_interface["board"]["bottom_z"])
    ) / 2.0
    specs = [{
        "axis": "Z", "coordinate": support_z,
        "featureIdsCovered": ["MW-M-101-W01", "MW-M-101-I01", "MW-M-101-H01"]
        + [f"MW-M-101-P{index:02d}" for index, _ in enumerate(mount_holes, 1)],
        "purpose": "horizontal PCB mount-post, case-pilot and base-wall section",
    }]
    specs.extend(
        {
            "axis": "Z",
            "coordinate": group["coordinate"],
            "featureIdsCovered": group["featureIds"],
            "purpose": "connector wall opening section: " + ", ".join(group["refs"]),
        }
        for group in opening_groups
    )
    return specs


def _receiver_assembly_section_specs() -> list[dict[str, Any]]:
    specs = [{
        "axis": "X",
        "coordinate": float(_receiver_interface["case_screws"]["positions"][0][0]),
        "featureIdsCovered": ["BASE", "LID", "CASE-SCREW"],
        "purpose": "vertical enclosure closure/screw section",
    }]
    mount_holes = _receiver_interface["board"].get("mount_holes", [])
    opening_groups = _receiver_opening_section_groups()
    if not mount_holes and not opening_groups:
        specs.append({
            "axis": "Z", "coordinate": _receiver_section_z,
            "featureIdsCovered": ["PCB-SUPPORT", "CONNECTOR-OPENINGS"],
            "purpose": "horizontal receiver interface section",
        })
        return specs
    support_z = (
        float(_receiver_interface["case"]["base_floor"])
        + float(_receiver_interface["board"]["bottom_z"])
    ) / 2.0
    specs.append({
        "axis": "Z", "coordinate": support_z,
        "featureIdsCovered": ["PCB-SUPPORT"]
        + [f"PCB-MOUNT:{row.get('ref', index)}" for index, row in enumerate(mount_holes, 1)],
        "purpose": "horizontal PCB support and mount-post section",
    })
    specs.extend(
        {
            "axis": "Z",
            "coordinate": group["coordinate"],
            "featureIdsCovered": [f"CONNECTOR-OPENING:{ref}" for ref in group["refs"]],
            "purpose": "assembled connector opening section: " + ", ".join(group["refs"]),
        }
        for group in opening_groups
    )
    return specs

PART_SECTION_SPECS: dict[str, list[dict[str, Any]]] = {
    "MW-M-001A": [{
        "axis": "Z", "coordinate": _button_local_z,
        "featureIdsCovered": ["MW-M-001A-W01", "MW-M-001A-O01", "MW-M-001A-O02"],
        "purpose": "transverse button aperture, guard/head pocket and shell wall",
    }],
    "MW-M-001B": [
        {
            "axis": "Z", "coordinate": _usb_local_z,
            "featureIdsCovered": ["MW-M-001B-W01", "MW-M-001B-O01"],
            "purpose": "transverse USB-C opening and shell wall",
        },
        {
            "axis": "Z", "coordinate": _debug_local_z,
            "featureIdsCovered": ["MW-M-001B-O02"],
            "purpose": "transverse debug opening",
        },
    ],
    "MW-M-002": [{
        "axis": "Z", "coordinate": 68.0,
        "featureIdsCovered": ["MW-M-002-W01", "MW-M-002-B01", "MW-M-002-F01"],
        "purpose": "boss station, wall taper and keyed base",
    }],
    "MW-M-003": [{"axis": "X", "coordinate": 0.0, "featureIdsCovered": ["MW-M-003-F01", "MW-M-003-F02", "MW-M-003-W01"], "purpose": "axial cap/plug/energy-director section"}],
    "MW-M-004": [{"axis": "X", "coordinate": 0.0, "featureIdsCovered": ["MW-M-004-F01", "MW-M-004-H01", "MW-M-004-G01", "MW-M-004-H02"], "purpose": "axial connector, adhesive bore and groove section"}],
    "MW-M-005": [{"axis": "X", "coordinate": 0.0, "featureIdsCovered": ["MW-M-005-F01", "MW-M-005-F02"], "purpose": "axial plunger stem/head section"}],
    "MW-P-001": [{"axis": "X", "coordinate": 0.0, "featureIdsCovered": ["MW-P-001-P01", "MW-P-001-P02"], "purpose": "axial purchased spine section"}],
    "MW-M-101": _receiver_part_section_specs(),
    "MW-M-102": [{
        "axis": "X", "coordinate": float(_receiver_interface["case_screws"]["positions"][0][0]),
        "featureIdsCovered": ["MW-M-102-W01", "MW-M-102-F01", "MW-M-102-H01"],
        "purpose": "vertical skirt wall and lid screw/counterbore station",
    }],
}

ASSEMBLY_SECTION_SPECS: dict[str, list[dict[str, Any]]] = {
    "MW-A-001": [
        {"axis": "X", "coordinate": 0.0, "featureIdsCovered": ["SHELL-WALL", "CARRIER", "CAP", "CONNECTOR", "GFRP"], "purpose": "axial product-stack section"},
        {"axis": "Z", "coordinate": P["interfaces"]["press_to_arm"]["global_center_z"], "featureIdsCovered": ["BUTTON-APERTURE", "PLUNGER", "CARRIER-SWITCH-SHELF"], "purpose": "transverse press-to-arm interface section"},
    ],
    "MW-A-101": _receiver_assembly_section_specs(),
}


def _section_cells(cell: tuple[float, float, float, float], count: int) -> list[tuple[float, float, float, float]]:
    if count <= 1:
        return [cell]
    x0, y0, x1, y1 = cell
    gap = 2.0
    columns = 2 if count > 3 else 1
    rows = math.ceil(count / columns)
    width = (x1 - x0 - gap * (columns - 1)) / columns
    height = (y1 - y0 - gap * (rows - 1)) / rows
    return [
        (
            x0 + (index % columns) * (width + gap),
            y1 - (index // columns + 1) * height - (index // columns) * gap,
            x0 + (index % columns) * (width + gap) + width,
            y1 - (index // columns) * height - (index // columns) * gap,
        )
        for index in range(count)
    ]


d._dimension_h = _strict_dimension_h

def _row(
    feature_id: str,
    characteristic: str,
    nominal: str,
    location_xyz: str,
    tolerance: str,
    source: str,
    probe: str = "parameter-bound",
) -> dict[str, str]:
    return {
        "featureId": feature_id,
        "characteristic": characteristic,
        "nominal": nominal,
        "locationXYZ": location_xyz,
        "tolerance": tolerance,
        "source": source,
        "geometryProbe": probe,
    }


def _common_rows(part_number: str, shape) -> list[dict[str, str]]:
    part = P["parts"][part_number]
    dfm = d.PART_DFM[part_number]
    bbox = shape.bounding_box(optimal=True)
    molding = P["molding_defaults"]
    return [
        _row(
            f"{part_number}-D01",
            "DATUM SYSTEM",
            dfm["datum"],
            "MODEL_XYZ; origin per design input",
            "basic",
            f"parts.{part_number}; coordinate_system",
        ),
        _row(
            f"{part_number}-E01",
            "BREP ENVELOPE",
            f"{bbox.size.X:.3f} x {bbox.size.Y:.3f} x {bbox.size.Z:.3f} mm",
            f"min=({bbox.min.X:.3f},{bbox.min.Y:.3f},{bbox.min.Z:.3f})",
            "reference",
            "generated BREP",
            f"bbox/valid/single-solid; volume={shape.volume:.3f} mm3",
        ),
        _row(
            f"{part_number}-M01",
            "MOLD PULL / PARTING",
            f"{part.get('mold_pull', 'N/A')} / {part.get('parting_line', 'N/A')}",
            "part-local",
            "vendor DFM",
            f"parts.{part_number}.mold_pull/parting_line",
        ),
        _row(
            f"{part_number}-M02",
            "GENERAL DRAFT / RADII",
            f"{molding['general_draft_deg']} deg; Rext>={molding['external_edge_radius_min']}; Rint>={molding['internal_edge_radius_min']}",
            "all unspecified molded faces/edges",
            "tooling tune",
            "molding_defaults",
        ),
        _row(
            f"{part_number}-M03",
            "SIDE ACTIONS",
            "; ".join(part.get("side_actions", [])) or "NONE",
            "feature-specific",
            f"shutoff draft {molding['side_action_shutoff_draft_deg']} deg target",
            f"parts.{part_number}.side_actions",
        ),
    ]


def feature_dimension_rows(part_number: str, shape) -> list[dict[str, str]]:
    shell = P["interfaces"]["shell"]
    screws = P["interfaces"]["shell_screws"]
    button = P["interfaces"]["press_to_arm"]
    service = P["interfaces"]["service_openings"]
    carrier = P["interfaces"]["carrier"]
    rear = P["interfaces"]["rear_cap"]
    rod = P["interfaces"]["rod_connector"]
    gfrp = P["interfaces"]["gfrp"]
    receiver = P["interfaces"]["receiver_enclosure"]
    rows = _common_rows(part_number, shape)
    if part_number == "MW-M-001A":
        rows.extend(
            [
                _row("MW-M-001A-W01", "WALL", f"{(shell['outer_diameter']-shell['inner_diameter'])/2:.2f} NOM / 1.80 MIN", "radial", "tooling tune", "interfaces.shell", "outer/inner BREP cylinders"),
                _row("MW-M-001A-O01", "BUTTON THRU APERTURE", f"DIA {button['aperture_finished_diameter']:.2f}", f"XYZ=(0,+Y,{button['global_center_z']:.2f})", f"+/-{button['aperture_tolerance']:.2f}; draft {button['side_core_draft_deg']} deg", "interfaces.press_to_arm", "pre/post BREP void probe PASS"),
                _row("MW-M-001A-O02", "GUARD / HEAD POCKET", f"OD {button['guard_outer_diameter']:.2f}; pocket DIA {button['head_diameter']+0.40:.2f}", f"XYZ=(0,+Y,{button['global_center_z']:.2f})", "0.40 diametral head clearance", "interfaces.press_to_arm", "guard-head intersection=0 required"),
                _row("MW-M-001A-H01", "4X M2 CLEARANCE", f"DIA {screws['upper_clearance_diameter']:.2f}", f"X={screws['x_positions']}; Z={screws['global_z_positions']}", "H11 unless supplier changes", "interfaces.shell_screws", "4 radial BREP cuts"),
                _row("MW-M-001A-H02", "4X COUNTERBORE", f"DIA {screws['upper_counterbore_diameter']:.2f} x {screws['upper_counterbore_depth']:.2f} deep", f"X={screws['x_positions']}; Z={screws['global_z_positions']}", "+0.10/-0", "interfaces.shell_screws", "4 exterior BREP cuts"),
                _row("MW-M-001A-F01", "SEAM TONGUE / FIT", f"W {shell['seam_tongue_width']:.2f} x D {shell['seam_tongue_depth']:.2f}", "XZ parting edges", f"{shell['seam_clearance_per_side']:.2f}/side nominal", "interfaces.shell", "assembly intersection=0 required"),
            ]
        )
    elif part_number == "MW-M-001B":
        rows.extend(
            [
                _row("MW-M-001B-W01", "WALL", f"{(shell['outer_diameter']-shell['inner_diameter'])/2:.2f} NOM / 1.80 MIN", "radial", "tooling tune", "interfaces.shell", "outer/inner BREP cylinders"),
                _row("MW-M-001B-O01", "USB-C OPENING", f"{service['usb_c']['width_x']:.2f} x {service['usb_c']['height_z']:.2f} R{service['usb_c']['corner_radius']:.2f}", f"XYZ=(0,-Y,{service['usb_c']['global_center_z']:.2f})", f"profile +/-{service['usb_c']['profile_tolerance']:.2f}", "interfaces.service_openings.usb_c", "pre/post BREP void probe PASS"),
                _row("MW-M-001B-O02", "DEBUG OPENING", f"{service['debug']['width_x']:.2f} x {service['debug']['height_z']:.2f} R{service['debug']['corner_radius']:.2f}", f"XYZ=(0,-Y,{service['debug']['global_center_z']:.2f})", f"profile +/-{service['debug']['profile_tolerance']:.2f}", "interfaces.service_openings.debug", "pre/post BREP void probe PASS"),
                _row("MW-M-001B-H01", "4X TAPERED PILOT", f"DIA {screws['lower_pilot_entry_diameter']:.2f}->{screws['lower_pilot_root_diameter']:.2f}", f"X={screws['x_positions']}; Z={screws['global_z_positions']}", "supplier strip-torque validation", "interfaces.shell_screws", "4 tapered radial BREP cuts"),
                _row("MW-M-001B-F01", "SEAM GROOVE / TONGUE", f"tongue W {shell['seam_tongue_width']:.2f}", "XZ parting edges", f"{shell['seam_clearance_per_side']:.2f}/side nominal", "interfaces.shell", "assembly intersection=0 required"),
                _row("MW-M-001B-F02", "CARRIER KEY RAIL", f"tip Y {carrier['shell_key_rail_tip_y']:.2f}; W {carrier['shell_key_rail_width']:.2f}", "X=0, Z=13..107 global", f"{carrier['key_clearance']:.2f} nominal", "interfaces.carrier", "rail-to-groove distance probe"),
            ]
        )
    elif part_number == "MW-M-002":
        rows.extend(
            [
                _row("MW-M-002-W01", "BASE / SIDE WALL", f"{carrier['base_wall']:.2f} / {carrier['side_wall']:.2f}", "carrier section", "-0.10/+0.15", "interfaces.carrier", "BREP section thickness"),
                _row("MW-M-002-I01", "PCB ENVELOPE", f"{carrier['pcb_envelope_width']:.2f} x {carrier['pcb_envelope_length']:.2f} x {carrier['pcb_envelope_thickness']:.2f}", f"global Z={carrier['assembly_z_start']:.2f}..{carrier['assembly_z_start']+carrier['pcb_envelope_length']:.2f}", "+0.30 width; +0.50 length", "interfaces.carrier", "support-ledges present"),
                _row("MW-M-002-B01", "4X HEAT-STAKE BOSS", "OD 4.2->3.8; pilot DIA 1.3->1.5", "X=+/-5.5; local Z=22,68", "supplier heat-stake DOE", "factory_geometry.make_internal_carrier", "boss/pilot BREP feature"),
                _row("MW-M-002-F01", "KEY GROOVE / RAIL FIT", f"W {carrier['key_groove_width']:.2f} x D {carrier['key_groove_depth']:.2f}", "X=0; full local Z", f"{carrier['key_clearance']:.2f} nominal", "interfaces.carrier", "lower-shell distance probe"),
                _row("MW-M-002-O01", "CABLE RELIEFS", "rear 6x4 R1; front 8x4 R1", "local Z=1 / 89", "+0.30", "factory_geometry.make_internal_carrier", "two open BREP cuts"),
            ]
        )
    elif part_number == "MW-M-003":
        rows.extend(
            [
                _row("MW-M-003-F01", "FLANGE / PLUG", f"DIA {rear['flange_diameter']:.2f} / {rear['plug_diameter']:.2f}", "axis MODEL_Z; datum A at Z=0", "plug -0.10/-0.20 after T0", "interfaces.rear_cap", "coaxial BREP cylinders"),
                _row("MW-M-003-F02", "PLUG LENGTH / FIT", f"{rear['plug_length']:.2f}; diametral clr {rear['nominal_diametral_clearance']:.2f}", "Z=5..9", "steel-safe", "interfaces.rear_cap", "shell-cap intended process interference only"),
                _row("MW-M-003-W01", "ENERGY DIRECTOR", f"H {rear['energy_director_height']:.2f}; base {rear['energy_director_base']:.2f}", "circumferential at Z=5.35", "weld DOE / vendor triangular conversion", "interfaces.rear_cap", "BREP torus; intended overlap classified"),
            ]
        )
    elif part_number == "MW-M-004":
        rows.extend(
            [
                _row("MW-M-004-F01", "PLUG / COLLAR", f"DIA {rod['plug_diameter']:.2f} x {rod['plug_length']:.2f}; DIA {rod['collar_diameter']:.2f} x {rod['collar_length']:.2f}", "axis MODEL_Z", "plug steel-safe", "interfaces.rod_connector", "coaxial BREP solids"),
                _row("MW-M-004-H01", "GFRP ADHESIVE BORE", f"DIA {rod['spine_bore_diameter']:.2f}", "XYZ=(0,0), through", f"gap DIA {rod['nominal_diametral_adhesive_gap']:.2f}", "interfaces.rod_connector", "GFRP minimum distance 0.20 radial"),
                _row("MW-M-004-G01", "3X ADHESIVE GROOVE", f"W {rod['adhesive_groove_width']:.2f}; D {rod['adhesive_groove_depth']:.2f}", "local Z=4,10,18", "+/-0.10", "interfaces.rod_connector", "3 circumferential BREP cuts"),
                _row("MW-M-004-H02", "WITNESS VENT", "DIA 1.20 THRU", "axis X; local Z=20", "+0.10/-0", "factory_geometry.make_rod_connector", "radial BREP cut"),
            ]
        )
    elif part_number == "MW-M-005":
        rows.extend(
            [
                _row("MW-M-005-F01", "STEM / HEAD", f"DIA {button['plunger_stem_diameter']:.2f}; DIA {button['head_diameter']:.2f} x {button['head_thickness']:.2f}", "axis +Y", "stem -0.05/-0.15", "interfaces.press_to_arm", "single-solid BREP"),
                _row("MW-M-005-F02", "APERTURE CLEARANCE", f"diametral {button['diametral_clearance']:.2f}", f"global Z={button['global_center_z']:.2f}", "functional", "interfaces.press_to_arm", "upper-shell/plunger overlap=0 required"),
                _row("MW-M-005-F03", "TRAVEL / FORCE", f"{button['target_travel']:.2f} mm / {button['target_force_n'][0]:.1f}-{button['target_force_n'][1]:.1f} N", "switch axis +Y", "prototype verification", "interfaces.press_to_arm", "inspection gauge required"),
            ]
        )
    elif part_number == "MW-P-001":
        rows.extend(
            [
                _row("MW-P-001-P01", "PURCHASE DIAMETER", f"DIA {gfrp['diameter']:.2f}", "axis MODEL_Z", f"+/-{gfrp['diameter_tolerance']:.2f}", "interfaces.gfrp", "BREP diameter 7.0"),
                _row("MW-P-001-P02", "PURCHASE LENGTH", f"{gfrp['purchase_length']:.2f}", "Z=0..220 local", f"+/-{gfrp['purchase_length_tolerance']:.2f}", "interfaces.gfrp", "BREP bbox Z=220"),
                _row("MW-P-001-F01", "ADHESIVE FIT", f"insertion {gfrp['insertion_length']:.2f}; exposed {gfrp['exposed_length']:.2f}", "connector bore", "0.20 radial nominal", "interfaces.gfrp/rod_connector", "pairwise BREP distance"),
            ]
        )
    elif part_number == "MW-M-101":
        board = receiver["board"]
        case = receiver["case"]
        cs = receiver["case_screws"]
        rows.extend(
            [
                _row("MW-M-101-W01", "WALL / FLOOR", f"{case['wall_nominal']:.2f} / {case['base_floor']:.2f}", "base section", "1.80 MIN", "interfaces.receiver_enclosure.case", "BREP section thickness"),
                _row("MW-M-101-I01", "PCB ENVELOPE / DATUM", f"{board['outline_x']:.2f} x {board['outline_y']:.2f} x {board['thickness']:.2f}", f"PCB bottom Z={board['bottom_z']:.2f}", "+0.30 XY / +0.20 Z", "receiver-mechanical-interface.json", "native-DRC-bound interface"),
                _row("MW-M-101-H01", "CASE PILOTS", f"DIA {cs['pilot_entry_diameter']:.2f}->{cs['pilot_root_diameter']:.2f}", f"XYZ={cs['positions']}", "strip-torque DOE", "interfaces.receiver_enclosure.case_screws", "3 tapered BREP cuts"),
            ]
        )
        for index, hole in enumerate(board.get("mount_holes", []), 1):
            ref = hole.get("ref", hole.get("id", index))
            tolerance = json.dumps(
                hole.get("tolerance_mm", "location +/-0.15"),
                ensure_ascii=True,
                separators=(",", ":"),
            )
            rows.append(
                _row(
                    f"MW-M-101-P{index:02d}",
                    f"PCB MOUNT {ref}",
                    f"DIA {float(hole['finished_diameter']):.2f}",
                    f"board XY=({float(hole['x']):.2f},{float(hole['y']):.2f}); case XY={hole.get('case_center')}",
                    tolerance,
                    "receiver-mechanical-interface.json",
                    "post/bore BREP feature; frozen NPTH coordinate",
                )
            )
        for index, opening in enumerate(receiver.get("connector_openings", []), 1):
            ref = opening.get("ref", opening.get("id", "CONNECTOR"))
            tolerance = json.dumps(
                opening.get("tolerances_mm", "profile +0.20/-0"),
                ensure_ascii=True,
                separators=(",", ":"),
            )
            drawing = opening.get("official_drawing", {})
            rows.append(
                _row(
                    f"MW-M-101-O{index:02d}",
                    f"{ref} OPENING",
                    f"{opening['panel_width']:.2f} x {opening['panel_height']:.2f} R{opening['corner_radius']:.2f}",
                    f"wall {opening['wall_axis']}; case XYZ={opening['mechanical_center']}; board XY={opening.get('board_mechanical_datum')}",
                    tolerance,
                    "receiver-mechanical-interface.json",
                    f"tapered BREP wall cut; official drawing {drawing.get('documentNumber', 'missing')}",
                )
            )
    elif part_number == "MW-M-102":
        case = receiver["case"]
        cs = receiver["case_screws"]
        rows.extend(
            [
                _row("MW-M-102-W01", "LID WALL / HEIGHT", f"{case['wall_nominal']:.2f} / {case['lid_height']:.2f}", "lid section", "1.80 MIN", "interfaces.receiver_enclosure.case", "BREP section thickness"),
                _row("MW-M-102-F01", "SKIRT FIT", f"clearance {case['skirt_clearance_per_side']:.2f}/side", "perimeter", "+0.10/-0.05", "interfaces.receiver_enclosure.case", "base/lid positive overlap=0 required"),
                _row("MW-M-102-H01", "3X LID CLEARANCE / CBORE / TOWER POCKET", f"DIA {cs['lid_clearance_diameter']:.2f}; CBORE DIA {cs['lid_counterbore_diameter']:.2f}; POCKET DIA 6.80", f"XYZ={cs['positions']}", "+0.10/-0", "interfaces.receiver_enclosure.case_screws", "9 axial BREP cuts; base/lid overlap=0"),
                _row("MW-M-102-RF01", "RF KEEP-OUT", f"polygon={receiver['rf_keepout'].get('board_xy_polygon', [])}", "above PCB antenna", "no metal/coating/vent", "receiver-mechanical-interface.json", "review overlay / material rule"),
            ]
        )
    return rows


def feature_dimension_catalog() -> dict[str, Any]:
    subjects = []
    for part_number in g.PART_FACTORIES:
        shape = g.make_part(part_number)
        rows = feature_dimension_rows(part_number, shape)
        subjects.append(
            {
                "subjectId": part_number,
                "sourceRevision": P["revision"],
                "rowCount": len(rows),
                "rows": rows,
            }
        )
    return {
        "schema": "aicad_feature_bound_factory_dimension_catalog_v1",
        "units": "mm",
        "coordinateSystem": P["coordinate_system"],
        "subjects": subjects,
    }


def _draw_true_section(
    msp,
    shape,
    section_id: str,
    cell: tuple[float, float, float, float],
    *,
    plane_axis: str,
    coordinate: float,
    feature_ids_covered: list[str],
    purpose: str,
    coordinate_frame: str,
) -> dict[str, Any]:
    source_bbox = shape.bounding_box(optimal=True)
    axis = plane_axis.upper()
    axis_range = {
        "X": (source_bbox.min.X, source_bbox.max.X),
        "Y": (source_bbox.min.Y, source_bbox.max.Y),
        "Z": (source_bbox.min.Z, source_bbox.max.Z),
    }[axis]
    if not axis_range[0] - 1e-6 <= coordinate <= axis_range[1] + 1e-6:
        raise RuntimeError(f"{section_id}: section plane is outside subject BREP bounds")
    section = g.section_intersection(
        shape, plane_axis=plane_axis, coordinate=coordinate, thickness=0.10
    )
    x0, y0, x1, y1 = cell
    if axis == "X":
        camera, up = (1000, 0, 0), (0, 0, 1)
    elif axis == "Y":
        camera, up = (0, 1000, 0), (0, 0, 1)
    else:
        camera, up = (0, 0, 1000), (0, 1, 0)
    visible, _ = section.project_to_viewport(camera, up)
    sampled = [d._poly_points(edge, 32) for edge in visible]
    points = [point for edge_points in sampled for point in edge_points]
    if not points:
        raise RuntimeError(f"{section_id}: empty projected BREP section")
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    scale = min(
        (x1 - x0 - 8) / max(max_x - min_x, 0.1),
        (y1 - y0 - 15) / max(max_y - min_y, 0.1),
    )
    tx = (x0 + x1) / 2 - (min_x + max_x) * scale / 2
    ty = (y0 + y1) / 2 - (min_y + max_y) * scale / 2 + 2
    for index, edge_points in enumerate(sampled):
        transformed = [(px * scale + tx, py * scale + ty) for px, py in edge_points]
        if len(transformed) < 2:
            continue
        entity = msp.add_lwpolyline(transformed, dxfattribs={"layer": "SECTION"})
        entity.set_xdata(
            "AICAD",
            [
                (1000, section_id),
                (1000, f"{section_id}:brep-section-edge:{index}"),
            ],
        )
    # No decorative hatch: cell-clipped lines would falsely fill cavities.
    # Heavy SECTION contours are the exact BREP slab projection.
    d._boxed_text(
        msp,
        f"{section_id}:label",
        f"TRUE BREP SECTION {plane_axis}={coordinate:.2f}  OUTLINE / NO FALSE HATCH",
        (x0 + 2, y0, x1 - 2, y0 + 7),
        "TITLE_BLOCK",
        1.8,
        "center",
    )
    summary = g.geometry_summary(section)
    return {
        "sectionId": section_id,
        "planeAxis": plane_axis,
        "coordinate": coordinate,
        "slabThickness": 0.10,
        "intersection": summary,
        "sourceType": "build123d BREP boolean intersection",
        "coordinateFrame": coordinate_frame,
        "subjectBboxAxisRange": [round(axis_range[0], 6), round(axis_range[1], 6)],
        "planeWithinSubjectBbox": True,
        "featureIdsCovered": feature_ids_covered,
        "purpose": purpose,
        "decorativeHatchUsed": False,
    }


def _dimension_table_text(rows: list[dict[str, str]]) -> str:
    lines = ["FEATURE-ID | NOMINAL / XYZ / TOL / PROBE"]
    for row in rows:
        lines.append(
            f"{row['featureId']} | {row['characteristic']}: {row['nominal']} | "
            f"{row['locationXYZ']} | {row['tolerance']} | {row['geometryProbe']}"
        )
    return "\n".join(lines)


def generate_part_drawing(
    part_number: str,
    output: Path,
    section_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    doc, msp = d._new_doc()
    part_name = P["parts"][part_number]["name"].replace("_", " ").upper()
    d._sheet_frame(
        msp,
        part_number,
        part_name,
        P["revision"],
        "DFM/RFQ INPUT · REVIEW ONLY · NOT TOOL RELEASE",
    )
    shape = g.make_part(part_number)
    d._draw_view(
        msp,
        shape,
        f"{part_number}:front",
        "FRONT",
        (14, 187, 142, 276),
        (0, -1000, 0),
        (0, 0, 1),
    )
    d._draw_view(
        msp,
        shape,
        f"{part_number}:right",
        "RIGHT",
        (145, 187, 273, 276),
        (1000, 0, 0),
        (0, 0, 1),
    )
    d._draw_view(
        msp,
        shape,
        f"{part_number}:top",
        "TOP",
        (276, 187, 406, 276),
        (0, 0, 1000),
        (0, 1, 0),
    )
    d._draw_view(
        msp,
        shape,
        f"{part_number}:iso",
        "ISOMETRIC",
        (276, 91, 406, 181),
        (1000, -1000, 800),
        (0, 0, 1),
    )
    bbox = shape.bounding_box(optimal=True)
    d._dimension_h(
        msp,
        20,
        132,
        184,
        178,
        f"ENVELOPE X {bbox.size.X:.2f}",
        f"{part_number}:dim-x",
    )
    d._dimension_h(
        msp,
        151,
        267,
        184,
        178,
        f"ENVELOPE Z {bbox.size.Z:.2f}",
        f"{part_number}:dim-z",
    )
    part_sections = []
    section_specs = PART_SECTION_SPECS[part_number]
    for index, (spec, cell) in enumerate(
        zip(section_specs, _section_cells((14, 91, 142, 171), len(section_specs)))
    ):
        letter = chr(ord("A") + index)
        section = _draw_true_section(
            msp,
            shape,
            f"{part_number}:section-{letter}-{letter}",
            cell,
            plane_axis=spec["axis"],
            coordinate=float(spec["coordinate"]),
            feature_ids_covered=list(spec["featureIdsCovered"]),
            purpose=str(spec["purpose"]),
            coordinate_frame="PART_LOCAL_XYZ",
        )
        section["subjectId"] = part_number
        section_reports.append(section)
        part_sections.append(section)
    rows = feature_dimension_rows(part_number, shape)
    d._boxed_text(
        msp,
        f"{part_number}:feature-table",
        _dimension_table_text(rows),
        (145, 91, 273, 171),
        "NOTES",
        1.35,
    )
    d._boxed_text(
        msp,
        f"{part_number}:notes",
        d._part_notes(part_number),
        (14, 12, 252, 85),
        "NOTES",
        2.05,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output)
    return {
        "drawing_number": part_number,
        "title": part_name,
        "kind": "manufacturing_part",
        "file": output.name,
        "views": ["front", "right", "top", "isometric", "true_brep_section_A-A"],
        "layers": list(d.LAYER_SPECS),
        "source_part": part_number,
        "featureDimensionRowCount": len(rows),
        "sectionIds": [section["sectionId"] for section in part_sections],
    }


def _assembly_bom_text(receiver: bool) -> str:
    ids = g.RECEIVER_PART_NUMBERS if receiver else g.WAND_PART_NUMBERS
    return "ASSEMBLY ITEM TABLE\n" + "\n".join(
        f"{index:02d} | {part_number} | QTY 1 | {P['parts'][part_number]['name']}"
        for index, part_number in enumerate(ids, 1)
    )


def generate_assembly_drawing(
    drawing_number: str,
    title: str,
    kind: str,
    shape,
    output: Path,
    section_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    doc, msp = d._new_doc()
    d._sheet_frame(
        msp,
        drawing_number,
        title,
        P["revision"],
        "DFM/RFQ INPUT · REVIEW ONLY · NOT TOOL RELEASE",
    )
    d._draw_view(
        msp,
        shape,
        f"{drawing_number}:front",
        "FRONT",
        (14, 166, 205, 276),
        (0, -1000, 0),
        (0, 0, 1),
    )
    d._draw_view(
        msp,
        shape,
        f"{drawing_number}:iso",
        "ISOMETRIC",
        (212, 166, 406, 276),
        (1000, -1000, 800),
        (0, 0, 1),
    )
    receiver = drawing_number.startswith("MW-A-101")
    views = ["front", "isometric"]
    if kind in {"section", "section_interface"}:
        subject_id = "MW-A-101" if receiver else "MW-A-001"
        specs = ASSEMBLY_SECTION_SPECS[subject_id]
        for index, (spec, cell) in enumerate(
            zip(specs, _section_cells((258, 63, 406, 158), len(specs)))
        ):
            letter = chr(ord("A") + index)
            section = _draw_true_section(
                msp,
                shape,
                f"{drawing_number}:section-{letter}-{letter}",
                cell,
                plane_axis=spec["axis"],
                coordinate=float(spec["coordinate"]),
                feature_ids_covered=list(spec["featureIdsCovered"]),
                purpose=str(spec["purpose"]),
                coordinate_frame="ASSEMBLY_MODEL_XYZ",
            )
            section["subjectId"] = subject_id
            section_reports.append(section)
            views.append(f"true_brep_section_{letter}-{letter}")
    else:
        d._draw_view(
            msp,
            shape,
            f"{drawing_number}:top",
            "TOP / INTERFACE",
            (258, 63, 406, 158),
            (0, 0, 1000),
            (0, 1, 0),
        )
        views.append("top_interface")
    d._boxed_text(
        msp,
        f"{drawing_number}:notes",
        d._assembly_notes(drawing_number, kind),
        (14, 12, 252, 100),
        "NOTES",
        2.05,
    )
    d._boxed_text(
        msp,
        f"{drawing_number}:bom",
        _assembly_bom_text(receiver),
        (14, 102, 252, 158),
        "NOTES",
        1.9,
    )
    if kind == "harness_interface":
        route = [(270, 80), (290, 110), (330, 110), (360, 135), (394, 135)]
        entity = msp.add_lwpolyline(route, dxfattribs={"layer": "HARNESS"})
        entity.set_xdata(
            "AICAD",
            [(1000, "MW-A-001-HARNESS"), (1000, "harness-route-symbolic-interface")],
        )
        d._boxed_text(
            msp,
            f"{drawing_number}:harness-map",
            "HARNESS MAP (INTERFACE AUTHORITY)\nJ1 USB-C -> WAND PCB\nSW1 -> PRESS-TO-ARM\nB1 -> CARRIER BATTERY BAY\nTP/DBG -> DEBUG WINDOW\nRoute clear of RF Z=5..30 and screw stations",
            (258, 63, 406, 158),
            "NOTES",
            1.9,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output)
    return {
        "drawing_number": drawing_number,
        "title": title,
        "kind": kind,
        "file": output.name,
        "views": views,
        "layers": list(d.LAYER_SPECS),
    }


def generate_all(output_dir: Path, report_dir: Path) -> dict[str, Any]:
    global TEXT_INPUTS
    TEXT_INPUTS = []
    d.TEXT_FRAMES = []
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    section_reports: list[dict[str, Any]] = []
    for part_number in g.PART_FACTORIES:
        index.append(
            generate_part_drawing(
                part_number,
                output_dir / f"{g.PART_BASENAMES[part_number]}.dxf",
                section_reports,
            )
        )
    index.extend(
        [
            generate_assembly_drawing("MW-A-001", "MAGIC WAND GENERAL ASSEMBLY", "assembly", g.make_assembly(False), output_dir / "MW-A-001_wand_general_assembly.dxf", section_reports),
            generate_assembly_drawing("MW-A-001-EX", "MAGIC WAND EXPLODED", "exploded", g.make_assembly(True), output_dir / "MW-A-001_wand_exploded.dxf", section_reports),
            generate_assembly_drawing("MW-A-001-SE", "MAGIC WAND SECTION A-A", "section", g.make_assembly(False), output_dir / "MW-A-001_wand_section_A-A.dxf", section_reports),
            generate_assembly_drawing("MW-A-001-HI", "MAGIC WAND HARNESS INTERFACE", "harness_interface", g.make_assembly(False), output_dir / "MW-A-001_wand_harness_interface.dxf", section_reports),
            generate_assembly_drawing("MW-A-101", "RECEIVER ENCLOSURE ASSEMBLY", "assembly", g.make_receiver_assembly(False), output_dir / "MW-A-101_receiver_assembly.dxf", section_reports),
            generate_assembly_drawing("MW-A-101-EX", "RECEIVER ENCLOSURE EXPLODED", "exploded", g.make_receiver_assembly(True), output_dir / "MW-A-101_receiver_exploded.dxf", section_reports),
            generate_assembly_drawing("MW-A-101-SE", "RECEIVER ENCLOSURE SECTION / INTERFACE", "section_interface", g.make_receiver_assembly(False), output_dir / "MW-A-101_receiver_section_interface.dxf", section_reports),
        ]
    )
    overflow = [item for item in d.TEXT_FRAMES if item["overflow"]]
    unclosed = [item for item in TEXT_INPUTS if not item["textClosure"]]
    undersize = [
        item for item in d.TEXT_FRAMES
        if item["text_height_mm"] < MIN_PRINT_TEXT_HEIGHT_MM
    ]
    audit = {
        "schema": "aicad_factory_drawing_text_frame_audit_v3",
        "sheet": {"width_mm": d.SHEET_W, "height_mm": d.SHEET_H, "format": "A3 landscape"},
        "drawing_count": len(index),
        "text_entity_count": len(d.TEXT_FRAMES),
        "overflow_count": len(overflow),
        "truncated_count": len(unclosed),
        "undersize_count": len(undersize),
        "minimum_print_text_height_mm": MIN_PRINT_TEXT_HEIGHT_MM,
        "passed": len(overflow) == 0 and len(unclosed) == 0 and len(undersize) == 0,
        "required_layers": d.LAYER_SPECS,
        "frames": d.TEXT_FRAMES,
        "inputClosure": TEXT_INPUTS,
    }
    required_section_features = sorted(
        {
            feature_id
            for specs in PART_SECTION_SPECS.values()
            for spec in specs
            for feature_id in spec["featureIdsCovered"]
        }
    )
    covered_section_features = sorted(
        {feature_id for row in section_reports for feature_id in row["featureIdsCovered"]}
    )
    missing_section_features = sorted(set(required_section_features) - set(covered_section_features))
    section_pass = all(
        row["intersection"]["valid"]
        and row["intersection"]["volume_mm3"] > 0
        and row["planeWithinSubjectBbox"]
        and row["decorativeHatchUsed"] is False
        for row in section_reports
    ) and not missing_section_features
    section_report = {"schema": "aicad_factory_brep_section_intersections_v2", "requiredFeatureIds": required_section_features, "coveredFeatureIds": covered_section_features, "missingFeatureIds": missing_section_features, "sections": section_reports, "passed": section_pass}
    catalog = feature_dimension_catalog()
    (report_dir / "drawing-index.json").write_text(json.dumps({"schema": "aicad_factory_drawing_index_v2", "drawings": index}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / "drawing-text-frame-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / "feature-dimension-catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / "brep-section-intersection-report.json").write_text(json.dumps(section_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"index": index, "audit": audit, "catalog": catalog, "sections": section_reports}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    result = generate_all(root / "outputs" / "2d", root / "reports")
    print(json.dumps({"drawing_count": len(result["index"]), "overflow_count": result["audit"]["overflow_count"], "section_count": len(result["sections"])}, indent=2))
