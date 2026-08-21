from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from build123d import (
    Align,
    Axis,
    Box,
    Color,
    Compound,
    Cone,
    Cylinder,
    GeomType,
    Location,
    Polygon,
    RectangleRounded,
    Torus,
    extrude,
    fillet,
)


ROOT = Path(__file__).resolve().parents[1]
PARAMETERS_PATH = ROOT / "factory-design-input.json"


def load_parameters() -> dict[str, Any]:
    value = json.loads(PARAMETERS_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("factory-design-input.json must contain one object")
    return value


P = load_parameters()


def _axis_y_cylinder(radius: float, length: float, y_start: float, x: float, z: float):
    return (
        Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        .rotate(Axis.X, -90)
        .translate((x, y_start, z))
    )


def _axis_y_cone(
    start_radius: float,
    end_radius: float,
    length: float,
    y_start: float,
    x: float,
    z: float,
):
    return (
        Cone(start_radius, end_radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        .rotate(Axis.X, -90)
        .translate((x, y_start, z))
    )


def _axis_x_cylinder(radius: float, length: float, x_start: float, y: float, z: float):
    return (
        Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        .rotate(Axis.Y, 90)
        .translate((x_start, y, z))
    )


def _rounded_prism_y(
    width_x: float,
    height_z: float,
    corner_radius: float,
    depth_y: float,
    y_center: float,
    z_center: float,
    taper_deg: float = 0.0,
):
    profile = RectangleRounded(width_x, height_z, corner_radius)
    solid = extrude(profile, amount=depth_y / 2, both=True, taper=taper_deg)
    return solid.rotate(Axis.X, 90).translate((0, y_center, z_center))


def _rounded_prism_x(
    width_y: float,
    height_z: float,
    corner_radius: float,
    depth_x: float,
    x_center: float,
    y_center: float,
    z_center: float,
    taper_deg: float = 0.0,
):
    profile = RectangleRounded(width_y, height_z, corner_radius)
    solid = extrude(profile, amount=depth_x / 2, both=True, taper=taper_deg)
    return solid.rotate(Axis.Y, 90).translate((x_center, y_center, z_center))


def _rounded_prism_z(width_x: float, width_y: float, corner_radius: float, height_z: float, z_start: float = 0.0):
    profile = RectangleRounded(width_x, width_y, corner_radius)
    return extrude(profile, amount=height_z).translate((0, 0, z_start))


def _axis_z_cone(start_radius: float, end_radius: float, length: float, z_start: float, x: float, y: float):
    return Cone(
        start_radius,
        end_radius,
        length,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    ).translate((x, y, z_start))


def _axis_z_cylinder(radius: float, length: float, z_start: float, x: float, y: float):
    return Cylinder(
        radius,
        length,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    ).translate((x, y, z_start))


def _safe_fillet(shape, edges, radius: float):
    selected = list(edges)
    if not selected:
        return shape
    try:
        return fillet(selected, radius)
    except Exception:
        return shape


def _base_split_shell(upper: bool):
    shell = P["interfaces"]["shell"]
    outer = shell["outer_diameter"] / 2
    inner = shell["inner_diameter"] / 2
    length = shell["length"]
    tube = (
        Cylinder(outer, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        - Cylinder(inner, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
    )
    if upper:
        clip = Box(40, 20, length, align=(Align.CENTER, Align.MIN, Align.MIN))
    else:
        clip = Box(40, 20, length, align=(Align.CENTER, Align.MAX, Align.MIN))
    half = tube.intersect(clip)
    return _safe_fillet(half, half.edges().filter_by(Axis.Z), 0.40)


def make_upper_shell():
    shell = P["interfaces"]["shell"]
    button = P["interfaces"]["press_to_arm"]
    screws = P["interfaces"]["shell_screws"]
    local_button_z = button["global_center_z"] - shell["assembly_z_start"]
    shape = _base_split_shell(True)

    # Long seam tongue.  It crosses the XZ parting plane by 0.55 mm and is
    # intentionally asymmetric so the two shells cannot be swapped or rotated.
    tongue = Box(
        shell["seam_tongue_width"],
        shell["seam_tongue_depth"],
        96.0,
        align=(Align.CENTER, Align.MAX, Align.MIN),
    ).translate((12.0, 0.0, 7.0))
    rear_key = Box(1.0, 0.35, 18.0, align=(Align.CENTER, Align.MAX, Align.MIN)).translate((-12.0, 0.0, 14.0))
    shape = shape + tongue + rear_key

    # The side aperture is a true tapered radial BREP cut.  The larger radius
    # is at the exterior side-action entry to supply 1.5 degree release.
    button_cut = _axis_y_cone(
        button["aperture_finished_diameter"] / 2 - 0.08,
        button["aperture_finished_diameter"] / 2 + 0.08,
        16.0,
        -0.5,
        0.0,
        local_button_z,
    )
    shape = shape - button_cut

    # Raised guard is fused into the shell and leaves the plunger head 0.6 mm
    # below its top surface in the nominal assembled position.
    guard_outer = _axis_y_cylinder(button["guard_outer_diameter"] / 2, 3.5, 11.8, 0.0, local_button_z)
    guard_inner = _axis_y_cone(
        button["aperture_finished_diameter"] / 2,
        button["aperture_finished_diameter"] / 2 + 0.08,
        3.8,
        11.6,
        0.0,
        local_button_z,
    )
    guard = guard_outer - guard_inner
    shape = shape + guard

    # Four M2 clearance/counterbore stations.  All are outside the RF keepout.
    for x in screws["x_positions"]:
        for global_z in screws["global_z_positions"]:
            local_z = global_z - shell["assembly_z_start"]
            clearance = _axis_y_cylinder(screws["upper_clearance_diameter"] / 2, 9.0, -0.5, x, local_z)
            counterbore = _axis_y_cylinder(
                screws["upper_counterbore_diameter"] / 2,
                3.3,
                3.8,
                x,
                local_z,
            )
            shape = shape - clearance - counterbore

    shape.label = "MW-M-001A_UPPER_GRIP_SHELL"
    shape.color = Color(0.25, 0.48, 0.73)
    return shape


def make_lower_shell():
    shell = P["interfaces"]["shell"]
    screws = P["interfaces"]["shell_screws"]
    service = P["interfaces"]["service_openings"]
    carrier = P["interfaces"]["carrier"]
    shape = _base_split_shell(False)

    # Matching seam grooves include 0.10 mm per-side nominal assembly clearance.
    groove = Box(1.4, 0.70, 97.0, align=(Align.CENTER, Align.MAX, Align.MIN)).translate((12.0, 0.0, 6.5))
    rear_key_groove = Box(1.2, 0.50, 19.0, align=(Align.CENTER, Align.MAX, Align.MIN)).translate((-12.0, 0.0, 13.5))
    shape = shape - groove - rear_key_groove

    # Tapered thread-forming pilots.  Entry diameter is larger at the parting
    # plane; final screw series and pilot are a T0/fastener-supplier decision.
    for x in screws["x_positions"]:
        for global_z in screws["global_z_positions"]:
            local_z = global_z - shell["assembly_z_start"]
            pilot = _axis_y_cone(
                screws["lower_pilot_root_diameter"] / 2,
                screws["lower_pilot_entry_diameter"] / 2,
                7.2,
                -7.0,
                x,
                local_z,
            )
            shape = shape - pilot

    # Rounded, 1.5 degree tapered service openings are true BREP voids.
    for opening in (service["usb_c"], service["debug"]):
        local_z = opening["global_center_z"] - shell["assembly_z_start"]
        cutter = _rounded_prism_y(
            opening["width_x"],
            opening["height_z"],
            opening["corner_radius"],
            7.0,
            -13.0,
            local_z,
            taper_deg=1.5,
        )
        shape = shape - cutter

    # Drafted carrier key rail.  The trapezoid narrows by 0.30 mm toward the
    # rail tip and can be released with the lower shell mold half.
    rail_profile = Polygon(
        (-carrier["shell_key_rail_width"] / 2, -11.55),
        (carrier["shell_key_rail_width"] / 2, -11.55),
        (1.35, carrier["shell_key_rail_tip_y"]),
        (-1.35, carrier["shell_key_rail_tip_y"]),
        align=None,
    )
    rail = extrude(rail_profile, amount=94.0).translate((0.0, 0.0, 8.0))
    shape = shape + rail

    shape.label = "MW-M-001B_LOWER_GRIP_SHELL"
    shape.color = Color(0.20, 0.40, 0.64)
    return shape


def make_internal_carrier():
    c = P["interfaces"]["carrier"]
    width = c["outer_width"]
    height = c["outer_height"]
    length = c["length"]
    base_wall = c["base_wall"]
    side_wall = c["side_wall"]
    y_bottom = -height / 2

    base = Box(width, base_wall, length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((0, y_bottom, 0))
    # Wall cross-sections taper 1.2-1.5 degrees toward the open top.
    left_profile = Polygon(
        (-width / 2, y_bottom),
        (-width / 2 + side_wall, y_bottom),
        (-width / 2 + side_wall + 0.30, height / 2),
        (-width / 2 + 0.30, height / 2),
        align=None,
    )
    right_profile = Polygon(
        (width / 2 - side_wall, y_bottom),
        (width / 2, y_bottom),
        (width / 2 - 0.30, height / 2),
        (width / 2 - side_wall - 0.30, height / 2),
        align=None,
    )
    walls = extrude(left_profile, amount=length) + extrude(right_profile, amount=length)
    shape = base + walls

    # Longitudinal PCB support ledges and four heat-stake bosses.
    ledge_left = Box(1.2, 1.2, 80.0, align=(Align.MIN, Align.MIN, Align.MIN)).translate((-7.3, -1.2, 5.0))
    ledge_right = Box(1.2, 1.2, 80.0, align=(Align.MAX, Align.MIN, Align.MIN)).translate((7.3, -1.2, 5.0))
    shape = shape + ledge_left + ledge_right
    for x in (-5.5, 5.5):
        for z in (22.0, 68.0):
            boss = _axis_y_cone(2.1, 1.9, 3.0, y_bottom + base_wall - 0.1, x, z)
            pilot = _axis_y_cone(0.65, 0.75, 3.2, y_bottom + base_wall - 0.2, x, z)
            shape = shape + boss - pilot

    # Button-switch support shelf and a rear asymmetric poka-yoke stop.
    switch_shelf = Box(15.0, 1.8, 8.0, align=(Align.CENTER, Align.MIN, Align.CENTER)).translate((0, 3.6, 63.0))
    rear_key = Box(3.3, 2.0, 5.0, align=(Align.MIN, Align.MIN, Align.MIN)).translate((-7.6, -4.7, 2.0))
    shape = shape + switch_shelf + rear_key

    # Bottom key groove leaves 0.8 mm residual wall and matches the shell rail
    # with 0.2 mm nominal width clearance.
    key_cut = Box(c["key_groove_width"], c["key_groove_depth"] + 0.1, length + 2, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((0, y_bottom - 0.05, -1))
    shape = shape - key_cut

    # End cable reliefs are open in the pull direction and avoid trapped cores.
    rear_relief = _rounded_prism_y(6.0, 4.0, 1.0, 16.0, 0.0, 1.0)
    front_relief = _rounded_prism_y(8.0, 4.0, 1.0, 16.0, 0.0, length - 1.0)
    shape = shape - rear_relief - front_relief

    shape = _safe_fillet(shape, shape.edges().filter_by(Axis.Z), 0.5)
    shape.label = "MW-M-002_INTERNAL_ELECTRONICS_CARRIER"
    shape.color = Color(0.72, 0.62, 0.25)
    return shape


def make_rear_end_cap():
    cap = P["interfaces"]["rear_cap"]
    flange = Cylinder(cap["flange_diameter"] / 2, cap["exposed_length"], align=(Align.CENTER, Align.CENTER, Align.MIN))
    flange = _safe_fillet(flange, flange.edges().filter_by(GeomType.CIRCLE), 0.8)
    plug = Cone(
        cap["plug_diameter"] / 2,
        cap["plug_diameter"] / 2 - 0.08,
        cap["plug_length"],
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    ).translate((0, 0, cap["exposed_length"]))
    shape = flange + plug

    # Asymmetric rail clearance prevents rotated insertion.
    key_slot = Box(3.4, 5.3, cap["plug_length"] + 1.0, align=(Align.CENTER, Align.MAX, Align.MIN)).translate((0, -6.3, cap["exposed_length"] - 0.2))
    shape = shape - key_slot

    # Round-section energy director is a conservative RFQ placeholder.  Mold
    # maker must convert it to the approved triangular weld profile after DOE.
    director = Torus(11.30, cap["energy_director_height"], align=(Align.CENTER, Align.CENTER, Align.CENTER)).translate((0, 0, cap["exposed_length"] + 0.35))
    shape = shape + director
    shape.label = "MW-M-003_REAR_RF_END_CAP"
    shape.color = Color(0.40, 0.67, 0.50)
    return shape


def make_rod_connector():
    conn = P["interfaces"]["rod_connector"]
    plug = Cone(
        conn["plug_diameter"] / 2 - 0.05,
        conn["plug_diameter"] / 2 - 0.12,
        conn["plug_length"],
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    collar = Cylinder(conn["collar_diameter"] / 2, conn["collar_length"], align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, conn["plug_length"]))
    collar = _safe_fillet(collar, collar.edges().filter_by(GeomType.CIRCLE), 0.8)
    shape = plug + collar
    bore = Cylinder(conn["spine_bore_diameter"] / 2, conn["plug_length"] + conn["collar_length"] + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, -1))
    shape = shape - bore

    # Three actual circumferential adhesive relief grooves intersect the bore.
    for z in (4.0, 10.0, 18.0):
        groove = Torus(conn["spine_bore_diameter"] / 2 + 0.18, conn["adhesive_groove_depth"]).translate((0, 0, z))
        shape = shape - groove

    key_slot = Box(3.4, 5.3, conn["plug_length"] + 0.5, align=(Align.CENTER, Align.MAX, Align.MIN)).translate((0, -6.3, -0.2))
    shape = shape - key_slot

    # Ø1.2 witness/adhesive vent through the collar is modeled as a true radial cut.
    vent = _axis_x_cylinder(0.6, 30.0, -15.0, 0.0, 20.0)
    shape = shape - vent
    shape.label = "MW-M-004_ROD_CONNECTOR"
    shape.color = Color(0.68, 0.43, 0.24)
    return shape


def make_button_plunger():
    button = P["interfaces"]["press_to_arm"]
    stem_length = 7.3
    stem = _axis_y_cone(button["plunger_stem_diameter"] / 2 - 0.04, button["plunger_stem_diameter"] / 2, stem_length, 0.0, 0.0, 0.0)
    head = _axis_y_cylinder(button["head_diameter"] / 2, button["head_thickness"], stem_length, 0.0, 0.0)
    head = _safe_fillet(head, head.edges().filter_by(GeomType.CIRCLE), 0.45)
    shape = stem + head
    # Flat removes 0.5 mm from one stem side and provides rotational poka-yoke.
    flat = Box(2.0, stem_length + 0.4, 10.0, align=(Align.MIN, Align.MIN, Align.CENTER)).translate((3.3, -0.2, 0.0))
    shape = shape - flat
    shape.label = "MW-M-005_PRESS_TO_ARM_PLUNGER"
    shape.color = Color(0.86, 0.24, 0.19)
    return shape


def make_gfrp_spine():
    gfrp = P["interfaces"]["gfrp"]
    shape = Cylinder(gfrp["diameter"] / 2, gfrp["purchase_length"], align=(Align.CENTER, Align.CENTER, Align.MIN))
    shape = _safe_fillet(shape, shape.edges().filter_by(GeomType.CIRCLE), 0.35)
    shape.label = "MW-P-001_GFRP_SPINE"
    shape.color = Color(0.35, 0.55, 0.35)
    return shape


def _receiver_interface(require_frozen: bool = False) -> dict[str, Any]:
    interface = P["interfaces"]["receiver_enclosure"]
    if require_frozen and interface["interface_status"] != "frozen_electronics_native_drc":
        raise RuntimeError(
            "receiver connector and mount geometry is not frozen; bind the final electronics interface before release export"
        )
    return interface


def make_receiver_base():
    interface = _receiver_interface(False)
    case = interface["case"]
    screws = interface["case_screws"]
    board = interface["board"]
    floor = case["base_floor"]
    height = case["base_height"]
    wall = case["wall_nominal"]
    outer = _rounded_prism_z(case["outer_x"], case["outer_y"], case["corner_radius"], height)
    inner = _rounded_prism_z(
        case["outer_x"] - 2 * wall,
        case["outer_y"] - 2 * wall,
        max(case["corner_radius"] - wall, 1.0),
        height - floor + 0.1,
        floor,
    )
    shape = outer - inner

    # Three asymmetric case screw towers omit the RF-side fourth corner.
    for x, y in screws["positions"]:
        boss = _axis_z_cone(3.2, 2.8, height - floor, floor - 0.05, x, y)
        pilot = _axis_z_cone(
            screws["pilot_root_diameter"] / 2,
            screws["pilot_entry_diameter"] / 2,
            height - floor + 0.5,
            floor,
            x,
            y,
        )
        shape = shape + boss - pilot

    # Mount posts are only generated from the frozen electronics interface.
    for hole in board["mount_holes"]:
        x = float(hole["x"]) - board["outline_x"] / 2
        y = float(hole["y"]) - board["outline_y"] / 2
        support_h = board["bottom_z"] - floor
        post = _axis_z_cone(2.8, 2.5, support_h, floor, x, y)
        bore = _axis_z_cylinder(float(hole["finished_diameter"]) / 2 + 0.20, support_h + 0.4, floor, x, y)
        shape = shape + post - bore

    # Edge datums establish a 3-2-1 fit even if the PCB uses no mount holes.
    pcb_x = board["outline_x"]
    pcb_y = board["outline_y"]
    pcb_z = board["bottom_z"]
    for y in (-pcb_y / 2 + 6.0, pcb_y / 2 - 6.0):
        shape = shape + Box(1.2, 4.0, 3.0, align=(Align.MIN, Align.CENTER, Align.MIN)).translate((-pcb_x / 2 - 0.2, y, floor))
    shape = shape + Box(8.0, 1.2, 3.0, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((0.0, -pcb_y / 2 - 0.2, floor))
    shape = shape + Box(10.0, 6.0, max(pcb_z - floor, 0.8), align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0.0, 0.0, floor))

    # Connector apertures are driven by the bound interface table and cut as
    # tapered rounded BREP voids.
    for opening in interface["connector_openings"]:
        axis = opening["wall_axis"]
        center = opening["mechanical_center"]
        if axis in ("-X", "+X"):
            cutter = _rounded_prism_x(
                opening["panel_width"], opening["panel_height"], opening["corner_radius"],
                wall + 4.0, (-1 if axis == "-X" else 1) * case["outer_x"] / 2,
                center[1], center[2], taper_deg=case["general_draft_deg"],
            )
        elif axis in ("-Y", "+Y"):
            cutter = _rounded_prism_y(
                opening["panel_width"], opening["panel_height"], opening["corner_radius"],
                wall + 4.0, (-1 if axis == "-Y" else 1) * case["outer_y"] / 2,
                center[2], taper_deg=case["general_draft_deg"],
            ).translate((center[0], 0.0, 0.0))
        else:
            raise ValueError(f"unsupported receiver opening wall_axis: {axis}")
        shape = shape - cutter

    shape = _safe_fillet(shape, shape.edges().filter_by(Axis.Z), 0.55)
    shape.label = "MW-M-101_RECEIVER_ENCLOSURE_BASE"
    shape.color = Color(0.23, 0.52, 0.42)
    return shape


def make_receiver_lid():
    interface = _receiver_interface(False)
    case = interface["case"]
    screws = interface["case_screws"]
    wall = case["wall_nominal"]
    height = case["lid_height"]
    clearance = case["skirt_clearance_per_side"]
    outer = _rounded_prism_z(case["outer_x"] + 0.4, case["outer_y"] + 0.4, case["corner_radius"] + 0.2, height)
    inner = _rounded_prism_z(
        case["outer_x"] - 2 * wall - 2 * clearance,
        case["outer_y"] - 2 * wall - 2 * clearance,
        max(case["corner_radius"] - wall - clearance, 1.0),
        height - wall + 0.1,
        -0.05,
    )
    shape = outer - inner
    for x, y in screws["positions"]:
        shape = shape - _axis_z_cylinder(screws["lid_clearance_diameter"] / 2, height + 0.4, -0.2, x, y)
        shape = shape - _axis_z_cylinder(screws["lid_counterbore_diameter"] / 2, 2.0, height - 1.6, x, y)
    nib = Box(4.0, 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((-24.0, -26.0, 0.0))
    shape = shape + nib
    shape = _safe_fillet(shape, shape.edges().filter_by(Axis.Z), 0.65)
    shape.label = "MW-M-102_RECEIVER_ENCLOSURE_LID"
    shape.color = Color(0.29, 0.63, 0.50)
    return shape


PART_FACTORIES = {
    "MW-M-001A": make_upper_shell,
    "MW-M-001B": make_lower_shell,
    "MW-M-002": make_internal_carrier,
    "MW-M-003": make_rear_end_cap,
    "MW-M-004": make_rod_connector,
    "MW-M-005": make_button_plunger,
    "MW-P-001": make_gfrp_spine,
    "MW-M-101": make_receiver_base,
    "MW-M-102": make_receiver_lid,
}


PART_BASENAMES = {
    "MW-M-001A": "MW-M-001A_upper_grip_shell",
    "MW-M-001B": "MW-M-001B_lower_grip_shell",
    "MW-M-002": "MW-M-002_internal_carrier",
    "MW-M-003": "MW-M-003_rear_end_cap",
    "MW-M-004": "MW-M-004_rod_connector",
    "MW-M-005": "MW-M-005_press_to_arm_plunger",
    "MW-P-001": "MW-P-001_gfrp_spine",
    "MW-M-101": "MW-M-101_receiver_enclosure_base",
    "MW-M-102": "MW-M-102_receiver_enclosure_lid",
}


WAND_PART_NUMBERS = tuple(part_number for part_number in PART_FACTORIES if not part_number.startswith("MW-M-10"))
RECEIVER_PART_NUMBERS = ("MW-M-101", "MW-M-102")


ASSEMBLY_PLACEMENTS = {
    "MW-M-001A": Location((0, 0, 5.0)),
    "MW-M-001B": Location((0, 0, 5.0)),
    "MW-M-002": Location((0, 0, 9.0)),
    "MW-M-003": Location((0, 0, 0.0)),
    "MW-M-004": Location((0, 0, 100.0)),
    "MW-M-005": Location((0, 6.2, 72.0)),
    "MW-P-001": Location((0, 0, 95.0)),
    "MW-M-101": Location((90.0, 0, 0.0)),
    "MW-M-102": Location((90.0, 0, 10.0)),
}


EXPLODED_PLACEMENTS = {
    "MW-M-001A": Location((0, 24.0, 5.0)),
    "MW-M-001B": Location((0, -24.0, 5.0)),
    "MW-M-002": Location((30.0, 0, 9.0)),
    "MW-M-003": Location((0, 0, -18.0)),
    "MW-M-004": Location((0, 0, 130.0)),
    "MW-M-005": Location((0, 40.0, 72.0)),
    "MW-P-001": Location((0, 0, 175.0)),
    "MW-M-101": Location((90.0, 0, 0.0)),
    "MW-M-102": Location((90.0, 0, 35.0)),
}


def make_part(part_number: str):
    if part_number not in PART_FACTORIES:
        raise KeyError(part_number)
    return PART_FACTORIES[part_number]()


def positioned_parts(exploded: bool = False, part_numbers: tuple[str, ...] | None = None) -> dict[str, Any]:
    placements = EXPLODED_PLACEMENTS if exploded else ASSEMBLY_PLACEMENTS
    selected = part_numbers or tuple(PART_FACTORIES)
    return {part_number: make_part(part_number).moved(placements[part_number]) for part_number in selected}


def make_assembly(exploded: bool = False):
    children = list(positioned_parts(exploded=exploded, part_numbers=WAND_PART_NUMBERS).values())
    assembly = Compound(label="MW-A-001_MAGIC_WAND_EXPLODED" if exploded else "MW-A-001_MAGIC_WAND_ASSEMBLY", children=children)
    return assembly


def make_receiver_assembly(exploded: bool = False):
    children = list(positioned_parts(exploded=exploded, part_numbers=RECEIVER_PART_NUMBERS).values())
    return Compound(
        label="MW-A-101_RECEIVER_ENCLOSURE_EXPLODED" if exploded else "MW-A-101_RECEIVER_ENCLOSURE_ASSEMBLY",
        children=children,
    )


def make_product_assembly():
    return Compound(label="MW-A-900_COMPLETE_PRODUCT_SET", children=list(positioned_parts(False).values()))


def gen_step():
    """CAD-skill entrypoint: build the positioned assembly STEP."""
    return make_assembly(False)


def geometry_summary(shape) -> dict[str, Any]:
    bbox = shape.bounding_box(optimal=True)
    solids = list(shape.solids())
    valid_attr = shape.is_valid
    valid = bool(valid_attr() if callable(valid_attr) else valid_attr)
    return {
        "valid": valid,
        "solid_count": len(solids),
        "volume_mm3": round(sum(float(s.volume) for s in solids), 6),
        "bbox": {
            "min": [round(bbox.min.X, 6), round(bbox.min.Y, 6), round(bbox.min.Z, 6)],
            "max": [round(bbox.max.X, 6), round(bbox.max.Y, 6), round(bbox.max.Z, 6)],
            "size": [round(bbox.size.X, 6), round(bbox.size.Y, 6), round(bbox.size.Z, 6)],
        },
        "edge_count": len(list(shape.edges())),
        "face_count": len(list(shape.faces())),
    }


def assembly_interference_rows() -> list[dict[str, Any]]:
    parts = positioned_parts(False, part_numbers=WAND_PART_NUMBERS)
    expected_intent = {
        tuple(sorted(("MW-M-001A", "MW-M-001B"))): "parting-plane/tongue-groove locating contact; no positive-volume overlap allowed",
        tuple(sorted(("MW-M-001A", "MW-M-003"))): "rear energy-director interference is intentional and requires weld DOE",
        tuple(sorted(("MW-M-001B", "MW-M-003"))): "rear energy-director interference is intentional and requires weld DOE",
        tuple(sorted(("MW-M-004", "MW-P-001"))): "nominal adhesive annulus; no positive-volume overlap allowed",
    }
    rows: list[dict[str, Any]] = []
    keys = list(parts)
    for index, first_id in enumerate(keys):
        for second_id in keys[index + 1 :]:
            first = parts[first_id]
            second = parts[second_id]
            common = first.intersect(second)
            if common is None:
                volume = 0.0
            else:
                volume = sum(float(s.volume) for s in common.solids())
            distance = float(first.distance_to(second))
            key = tuple(sorted((first_id, second_id)))
            intent = expected_intent.get(key, "clearance relationship")
            classification = "clear"
            if volume > 1e-5:
                if "energy-director interference is intentional" in intent:
                    classification = "intended_process_interference"
                else:
                    classification = "unexpected_interference"
            elif distance <= 1e-5:
                classification = "contact_no_positive_volume"
            rows.append(
                {
                    "first": first_id,
                    "second": second_id,
                    "minimum_distance_mm": round(distance, 6),
                    "intersection_volume_mm3": round(volume, 6),
                    "classification": classification,
                    "design_intent": intent,
                }
            )
    return rows


def feature_probe_report() -> dict[str, Any]:
    shell = P["interfaces"]["shell"]
    button = P["interfaces"]["press_to_arm"]
    service = P["interfaces"]["service_openings"]
    upper_before = _base_split_shell(True)
    upper_after = make_upper_shell()
    lower_before = _base_split_shell(False)
    lower_after = make_lower_shell()
    local_button_z = button["global_center_z"] - shell["assembly_z_start"]
    button_probe = _axis_y_cylinder(button["aperture_finished_diameter"] / 2 - 0.20, 14.0, 0.0, 0.0, local_button_z)
    button_pre_volume = sum(float(s.volume) for s in upper_before.intersect(button_probe).solids())
    button_post_volume = sum(float(s.volume) for s in upper_after.intersect(button_probe).solids())
    service_rows = []
    for name, opening in service.items():
        local_z = opening["global_center_z"] - shell["assembly_z_start"]
        probe = _rounded_prism_y(opening["width_x"] - 1.2, opening["height_z"] - 1.2, max(opening["corner_radius"] - 0.6, 0.2), 3.0, -13.0, local_z)
        pre_volume = sum(float(s.volume) for s in lower_before.intersect(probe).solids())
        post_volume = sum(float(s.volume) for s in lower_after.intersect(probe).solids())
        service_rows.append(
            {
                "feature": name,
                "pre_cut_intersection_mm3": round(pre_volume, 6),
                "post_cut_intersection_mm3": round(post_volume, 6),
                "brep_void_proven": pre_volume > 1.0 and post_volume < 1.0 and post_volume / pre_volume < 0.02,
            }
        )
    return {
        "schema": "aicad_magic_wand_factory_feature_probe_v1",
        "button_aperture": {
            "pre_cut_intersection_mm3": round(button_pre_volume, 6),
            "post_cut_intersection_mm3": round(button_post_volume, 6),
            "brep_void_proven": button_pre_volume > 1.0 and button_post_volume < 1e-4,
        },
        "service_openings": service_rows,
    }


def clone_parameters() -> dict[str, Any]:
    return copy.deepcopy(P)

