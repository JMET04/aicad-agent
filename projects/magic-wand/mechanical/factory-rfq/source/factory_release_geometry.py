from __future__ import annotations

"""Release geometry facade for the factory RFQ package.

The earlier geometry module is retained as an auditable construction history.
This facade applies the assembly-verified button guard relief and owns every
shape used by the final STEP, DXF, section and review artifacts.
"""

from typing import Any

from build123d import Align, Box, Color, Compound, Location

import factory_geometry as base


P = base.P
PART_BASENAMES = base.PART_BASENAMES
ASSEMBLY_PLACEMENTS = base.ASSEMBLY_PLACEMENTS
EXPLODED_PLACEMENTS = base.EXPLODED_PLACEMENTS
WAND_PART_NUMBERS = base.WAND_PART_NUMBERS
RECEIVER_PART_NUMBERS = base.RECEIVER_PART_NUMBERS
geometry_summary = base.geometry_summary


def make_upper_shell():
    """Return the shell with an assembly-clear guard-head counter-relief.

    The molded through aperture remains the controlled diameter from the design
    input.  A second, exterior-only tapered BREP cut clears the larger plunger
    head by 0.40 mm diametrically and leaves the raised guard intact.
    """
    shell = P["interfaces"]["shell"]
    button = P["interfaces"]["press_to_arm"]
    local_button_z = button["global_center_z"] - shell["assembly_z_start"]
    shape = base.make_upper_shell()
    pocket_radius = button["head_diameter"] / 2 + 0.20
    pocket = base._axis_y_cone(
        pocket_radius,
        pocket_radius + 0.08,
        4.2,
        11.35,
        0.0,
        local_button_z,
    )
    shape = shape - pocket
    shape.label = "MW-M-001A_UPPER_GRIP_SHELL"

    shape.color = Color(0.25, 0.48, 0.73)
    return shape
def make_receiver_lid():
    """Return an outside top plate with a cavity-fitting internal skirt."""
    interface = P["interfaces"]["receiver_enclosure"]
    case = interface["case"]
    screws = interface["case_screws"]
    wall = case["wall_nominal"]
    height = case["lid_height"]
    clearance = case["skirt_clearance_per_side"]
    top = base._rounded_prism_z(
        case["outer_x"] + 0.4,
        case["outer_y"] + 0.4,
        case["corner_radius"] + 0.2,
        wall,
        height - wall,
    )
    skirt_x = case["outer_x"] - 2 * wall - 2 * clearance
    skirt_y = case["outer_y"] - 2 * wall - 2 * clearance
    skirt_outer = base._rounded_prism_z(
        skirt_x,
        skirt_y,
        max(case["corner_radius"] - wall + 0.40, 1.0),
        height - wall + 0.05,
    )
    skirt_inner = base._rounded_prism_z(
        skirt_x - 2 * wall,
        skirt_y - 2 * wall,
        max(case["corner_radius"] - 2 * wall + 0.40, 0.8),
        height - wall + 0.20,
        -0.05,
    )
    shape = top + (skirt_outer - skirt_inner)
    for x, y in screws["positions"]:
        shape = shape - base._axis_z_cylinder(
            screws["lid_clearance_diameter"] / 2, height + 0.4, -0.2, x, y
        )
        shape = shape - base._axis_z_cylinder(
            screws["lid_counterbore_diameter"] / 2, 2.0, height - 1.6, x, y
        )
        shape = shape - base._axis_z_cylinder(
            3.4, height - wall + 0.35, -0.2, x, y
        )
    nib = Box(4.0, 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((-20.0, -23.4, 0.0))
    shape = shape + nib
    shape = base._safe_fillet(shape, shape.edges().filter_by(base.Axis.Z), 0.55)
    shape.label = "MW-M-102_RECEIVER_ENCLOSURE_LID"
    shape.color = Color(0.29, 0.63, 0.50)
    return shape


def make_gfrp_spine():
    """Return the supplier-cut nominal cylinder without cosmetic end fillets.

    End deburr and sealing remain controlled drawing operations. Keeping the
    purchased body nominal prevents STEP healing from adding a native body.
    """
    gfrp = P["interfaces"]["gfrp"]
    shape = base.Cylinder(
        gfrp["diameter"] / 2,
        gfrp["purchase_length"],
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    shape.label = "MW-P-001_GFRP_SPINE"
    shape.color = Color(0.35, 0.55, 0.35)
    return shape


PART_FACTORIES = dict(base.PART_FACTORIES)
PART_FACTORIES["MW-M-001A"] = make_upper_shell
PART_FACTORIES["MW-M-102"] = make_receiver_lid
PART_FACTORIES["MW-P-001"] = make_gfrp_spine

def make_part(part_number: str):
    if part_number not in PART_FACTORIES:
        raise KeyError(part_number)
    return PART_FACTORIES[part_number]()


def positioned_parts(
    exploded: bool = False,
    part_numbers: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    placements = EXPLODED_PLACEMENTS if exploded else ASSEMBLY_PLACEMENTS
    selected = part_numbers or tuple(PART_FACTORIES)
    return {
        part_number: make_part(part_number).moved(placements[part_number])
        for part_number in selected
    }


def make_assembly(exploded: bool = False):
    children = list(
        positioned_parts(exploded=exploded, part_numbers=WAND_PART_NUMBERS).values()
    )
    return Compound(
        label="MW-A-001_MAGIC_WAND_EXPLODED"
        if exploded
        else "MW-A-001_MAGIC_WAND_ASSEMBLY",
        children=children,
    )


def make_receiver_assembly(exploded: bool = False):
    receiver_placements = {
        "MW-M-101": Location((0.0, 0.0, 0.0)),
        "MW-M-102": Location((0.0, 0.0, 35.0 if exploded else P["interfaces"]["receiver_enclosure"]["case"]["lid_assembly_z"])),
    }
    children = [make_part(part_number).moved(receiver_placements[part_number]) for part_number in RECEIVER_PART_NUMBERS]
    return Compound(
        label="MW-A-101_RECEIVER_ENCLOSURE_EXPLODED"
        if exploded
        else "MW-A-101_RECEIVER_ENCLOSURE_ASSEMBLY",
        children=children,
    )


def make_product_assembly():
    return Compound(
        label="MW-A-900_COMPLETE_PRODUCT_SET",
        children=list(positioned_parts(False).values()),
    )


def _intersection_row(
    first_id: str,
    first,
    second_id: str,
    second,
    intent: str,
    intentional_process_interference: bool = False,
) -> dict[str, Any]:
    common = first.intersect(second)
    volume = (
        sum(float(solid.volume) for solid in common.solids())
        if common is not None
        else 0.0
    )
    distance = float(first.distance_to(second))
    classification = "clear"
    if volume > 1e-5:
        classification = (
            "intended_process_interference"
            if intentional_process_interference
            else "unexpected_interference"
        )
    elif distance <= 1e-5:
        classification = "contact_no_positive_volume"
    return {
        "first": first_id,
        "second": second_id,
        "minimum_distance_mm": round(distance, 6),
        "intersection_volume_mm3": round(volume, 6),
        "classification": classification,
        "design_intent": intent,
    }


def assembly_interference_rows() -> list[dict[str, Any]]:
    parts = positioned_parts(False, part_numbers=WAND_PART_NUMBERS)
    expected_intent = {
        tuple(sorted(("MW-M-001A", "MW-M-001B"))): (
            "parting-plane/tongue-groove locating contact; no positive-volume overlap allowed"
        ),
        tuple(sorted(("MW-M-001A", "MW-M-003"))): (
            "rear energy-director interference is intentional and requires weld DOE"
        ),
        tuple(sorted(("MW-M-001B", "MW-M-003"))): (
            "rear energy-director interference is intentional and requires weld DOE"
        ),
        tuple(sorted(("MW-M-004", "MW-P-001"))): (
            "nominal adhesive annulus; no positive-volume overlap allowed"
        ),
    }
    rows: list[dict[str, Any]] = []
    ids = list(parts)
    for index, first_id in enumerate(ids):
        for second_id in ids[index + 1 :]:
            key = tuple(sorted((first_id, second_id)))
            intent = expected_intent.get(key, "clearance relationship")
            rows.append(
                _intersection_row(
                    first_id,
                    parts[first_id],
                    second_id,
                    parts[second_id],
                    intent,
                    "energy-director interference is intentional" in intent,
                )
            )
    return rows


def receiver_assembly_interference_rows() -> list[dict[str, Any]]:
    parts = {
        "MW-M-101": make_part("MW-M-101"),
        "MW-M-102": make_part("MW-M-102").moved(Location((0.0, 0.0, P["interfaces"]["receiver_enclosure"]["case"]["lid_assembly_z"]))),
    }
    return [
        _intersection_row(
            "MW-M-101",
            parts["MW-M-101"],
            "MW-M-102",
            parts["MW-M-102"],
            "0.15 mm per-side skirt fit; no positive-volume overlap",
        )
    ]


def section_intersection(
    shape,
    *,
    plane_axis: str = "X",
    coordinate: float = 0.0,
    thickness: float = 0.10,
):
    """Return an actual finite BREP slab intersection for a drawing section."""
    bbox = shape.bounding_box(optimal=True)
    padding = 20.0
    axis = plane_axis.upper()
    if axis == "X":
        slab = Box(
            thickness,
            bbox.size.Y + padding,
            bbox.size.Z + padding,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        ).translate(
            (
                coordinate,
                (bbox.min.Y + bbox.max.Y) / 2,
                (bbox.min.Z + bbox.max.Z) / 2,
            )
        )
    elif axis == "Y":
        slab = Box(
            bbox.size.X + padding,
            thickness,
            bbox.size.Z + padding,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        ).translate(
            (
                (bbox.min.X + bbox.max.X) / 2,
                coordinate,
                (bbox.min.Z + bbox.max.Z) / 2,
            )
        )
    elif axis == "Z":
        slab = Box(
            bbox.size.X + padding,
            bbox.size.Y + padding,
            thickness,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        ).translate(
            (
                (bbox.min.X + bbox.max.X) / 2,
                (bbox.min.Y + bbox.max.Y) / 2,
                coordinate,
            )
        )
    else:
        raise ValueError(f"unsupported section plane axis: {plane_axis}")
    pieces = []
    for source_solid in shape.solids():
        cut = source_solid.intersect(slab)
        if cut is not None:
            pieces.extend(list(cut.solids()))
    if not pieces:
        raise RuntimeError(
            f"section plane {plane_axis}={coordinate} did not intersect the BREP"
        )
    section = pieces[0] if len(pieces) == 1 else Compound(
        label=f"BREP_SECTION_{plane_axis}_{coordinate:.3f}", children=pieces
    )
    return section


def feature_probe_report() -> dict[str, Any]:
    shell = P["interfaces"]["shell"]
    button = P["interfaces"]["press_to_arm"]
    service = P["interfaces"]["service_openings"]
    upper_before = base._base_split_shell(True)
    upper_after = make_upper_shell()
    lower_before = base._base_split_shell(False)
    lower_after = make_part("MW-M-001B")
    local_button_z = button["global_center_z"] - shell["assembly_z_start"]
    button_probe = base._axis_y_cylinder(
        button["aperture_finished_diameter"] / 2 - 0.20,
        14.0,
        0.0,
        0.0,
        local_button_z,
    )
    button_pre = sum(
        float(solid.volume) for solid in upper_before.intersect(button_probe).solids()
    )
    button_post = sum(
        float(solid.volume) for solid in upper_after.intersect(button_probe).solids()
    )
    service_rows = []
    for name, opening in service.items():
        local_z = opening["global_center_z"] - shell["assembly_z_start"]
        probe = base._rounded_prism_y(
            opening["width_x"] - 1.2,
            opening["height_z"] - 1.2,
            max(opening["corner_radius"] - 0.6, 0.2),
            3.0,
            -13.0,
            local_z,
        )
        pre = sum(
            float(solid.volume)
            for solid in lower_before.intersect(probe).solids()
        )
        post = sum(
            float(solid.volume)
            for solid in lower_after.intersect(probe).solids()
        )
        service_rows.append(
            {
                "feature": name,
                "pre_cut_intersection_mm3": round(pre, 6),
                "post_cut_intersection_mm3": round(post, 6),
                "brep_void_proven": pre > 1.0 and post < 1.0 and post / pre < 0.02,
            }
        )
    return {
        "schema": "aicad_magic_wand_factory_feature_probe_v2",
        "button_aperture": {
            "pre_cut_intersection_mm3": round(button_pre, 6),
            "post_cut_intersection_mm3": round(button_post, 6),
            "brep_void_proven": button_pre > 1.0 and button_post < 1e-4,
        },
        "guard_head_pocket": {
            "through_aperture_diameter_mm": button["aperture_finished_diameter"],
            "head_pocket_diameter_mm": button["head_diameter"] + 0.40,
            "plunger_head_diameter_mm": button["head_diameter"],
            "diametral_clearance_mm": 0.40,
        },
        "service_openings": service_rows,
    }


def gen_step():
    return make_assembly(False)
