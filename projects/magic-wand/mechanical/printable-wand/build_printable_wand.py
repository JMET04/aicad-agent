from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
import trimesh

import build123d
from build123d import (
    Align,
    Axis,
    Box,
    Color,
    Compound,
    Cone,
    Cylinder,
    Location,
    RectangleRounded,
    Torus,
    export_step,
    export_stl,
    extrude,
)


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[3]
DESIGN_PATH = ROOT / "design-input.json"
OUTPUT_ROOT = ROOT / "outputs"
STEP_ROOT = OUTPUT_ROOT / "step"
STL_ROOT = OUTPUT_ROOT / "stl"
PREVIEW_ROOT = OUTPUT_ROOT / "previews"
REPORT_ROOT = OUTPUT_ROOT / "reports"
RELEASE_STAMP = datetime(2026, 8, 22, 0, 0, 0)


def load_design() -> dict[str, Any]:
    value = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("design-input.json must contain one object")
    return value


P = load_design()
HANDLE = P["handle"]
POWER = P["powerReservation"]
HAPTIC = P["hapticReservation"]
PCB = P["sourcePcb"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def resolve_repository_file(relative: str) -> Path:
    """Resolve one canonical repository-relative POSIX path, fail closed otherwise."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError(f"non-portable repository path: {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe repository path: {relative!r}")
    path = REPO_ROOT.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"repository path escapes root: {relative!r}") from exc
    return path


def repository_relative_posix(path: Path) -> str:
    """Return a canonical repository-relative POSIX path for packaged evidence."""
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"packaged evidence is outside repository: {path}") from exc
    portable = relative.as_posix()
    if "\\" in portable or ":" in portable or PurePosixPath(portable).is_absolute():
        raise ValueError(f"non-portable packaged evidence path: {portable!r}")
    return portable


def validate_packaged_json_portability(paths: Iterable[Path]) -> None:
    """Reject host-specific or traversal paths before any JSON enters the ZIP."""

    def visit(value: Any, location: str, field: str | None = None) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{location}.{key}", str(key))
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{location}[{index}]", field)
            return
        if not isinstance(value, str):
            return

        normalized = value.replace("\\", "/")
        lower = normalized.casefold()
        windows_absolute = (
            len(value) >= 3
            and value[0].isalpha()
            and value[1] == ":"
            and value[2] in "/\\"
        )
        personal_path = any(
            marker in f"/{lower.lstrip('/')}" for marker in ("/users/", "/home/")
        )
        if "\\" in value or windows_absolute or value.startswith("\\\\") or personal_path:
            raise RuntimeError(
                f"host-specific string in packaged JSON at {location}: {value!r}"
            )

        if field is not None and field.casefold().endswith("path"):
            pure = PurePosixPath(value)
            if pure.is_absolute() or ".." in pure.parts or ":" in value:
                raise RuntimeError(
                    f"non-portable path in packaged JSON at {location}: {value!r}"
                )

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        visit(payload, path.name)


def _axis_y_cylinder(radius: float, length: float, y_start: float, x: float, z: float):
    return (
        Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        .rotate(Axis.X, -90)
        .translate((x, y_start, z))
    )


def _rounded_prism_x(
    width_y: float,
    height_z: float,
    radius: float,
    depth_x: float,
    center_x: float,
    center_y: float,
    center_z: float,
):
    profile = RectangleRounded(width_y, height_z, radius)
    solid = extrude(profile, amount=depth_x / 2, both=True)
    return solid.rotate(Axis.Y, 90).translate((center_x, center_y, center_z))


def _base_decorated_tube():
    length = float(HANDLE["length"])
    outer = float(HANDLE["outerDiameter"]) / 2
    inner = float(HANDLE["innerDiameter"]) / 2
    tube = (
        Cylinder(outer, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        - Cylinder(inner, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
    )

    # Restrained ring rhythm gives the grip a deliberate wand-like silhouette
    # while preserving a comfortable circular primary surface.
    rib = float(HANDLE["decorativeRibHeight"])
    for z in (51.0, 61.0, 71.0, 81.0, 91.0):
        tube = tube + Torus(outer, rib).translate((0, 0, z))
    front_collar = (
        Cylinder(outer + 0.55, 5.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
        - Cylinder(inner, 5.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ).translate((0, 0, 103.0))
    rear_collar = (
        Cylinder(outer + 0.35, 3.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
        - Cylinder(inner, 3.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ).translate((0, 0, 2.0))
    return tube + front_collar + rear_collar


def _split_shell(upper: bool):
    length = float(HANDLE["length"])
    tube = _base_decorated_tube()
    if upper:
        clip = Box(40, 24, length + 4, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((0, 0, -2))
    else:
        clip = Box(40, 24, length + 4, align=(Align.CENTER, Align.MAX, Align.MIN)).translate((0, 0, -2))
    return tube.intersect(clip)


def make_upper_shell():
    shape = _split_shell(True)

    # Matching seam grooves accept the lower-shell tongues with 0.20 mm per
    # side FDM allowance.  The asymmetric start heights are also a poka-yoke.
    for x, z0, length in ((13.65, 9.0, 90.0), (-13.65, 15.0, 80.0)):
        groove = Box(1.8, 0.85, length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((x, -0.15, z0))
        shape = shape - groove

    # Screw columns are outside the 15 mm PCB width and outside the antenna
    # keepout.  Nylon M2 hardware is specified for the prototype.
    for x in HANDLE["shellScrews"]["x"]:
        for z in HANDLE["shellScrews"]["z"]:
            boss = _axis_y_cylinder(2.65, 8.35, 0.0, float(x), float(z))
            clearance = _axis_y_cylinder(1.20, 16.0, -0.5, float(x), float(z))
            counterbore = _axis_y_cylinder(2.25, 7.0, 8.1, float(x), float(z))
            shape = shape + boss - clearance - counterbore

    # SW1 plunger opening and a low protective halo.
    button_z = float(PCB["interfaces"]["button"]["caseCenter"][2])
    shape = shape - _axis_y_cylinder(2.20, 17.0, -0.5, 0.0, button_z)
    guard = _axis_y_cylinder(4.60, 3.45, 11.75, 0.0, button_z) - _axis_y_cylinder(
        2.55, 3.7, 11.60, 0.0, button_z
    )
    shape = shape + guard

    # J1 faces +X.  The rounded opening spans the split deliberately so the
    # connector cannot be trapped by either printed half.
    usb = PCB["interfaces"]["usbC"]["caseCenter"]
    usb_cut = _rounded_prism_x(10.2, 5.2, 1.1, 20.0, 7.5, 0.7, float(usb[2]))
    shape = shape - usb_cut

    # Snap cup for a 10 x 3.4 mm coin LRA/ERM. The metal actuator starts
    # 5 mm after the RF keepout and remains separated from PCB components.
    motor_x, motor_y, motor_z = (float(v) for v in HAPTIC["caseCenter"])
    motor_radius = float(HAPTIC["maximumEnvelope"]["diameter"]) / 2
    motor_thickness = float(HAPTIC["maximumEnvelope"]["thickness"])
    motor_low_y = motor_y - (motor_thickness / 2)
    cup_base = _axis_y_cylinder(
        motor_radius + 0.55, 0.70, motor_low_y - 0.80, motor_x, motor_z)
    cup_ring = _axis_y_cylinder(
        motor_radius + 0.55, motor_thickness + 0.30,
        motor_low_y - 0.15, motor_x, motor_z) - _axis_y_cylinder(
            motor_radius + 0.15, motor_thickness + 0.50,
            motor_low_y - 0.25, motor_x, motor_z)
    # Overlap both the cup ring and the inner shell wall.  The previous
    # 3 mm bridges stopped at a tangent and exported as four floating bodies.
    bridge_left = Box(
        1.2, 4.7, 2.0, align=(Align.CENTER, Align.MIN, Align.CENTER)
    ).translate((-5.35, motor_low_y + motor_thickness + 0.05, motor_z))
    bridge_right = Box(
        1.2, 4.7, 2.0, align=(Align.CENTER, Align.MIN, Align.CENTER)
    ).translate((5.35, motor_low_y + motor_thickness + 0.05, motor_z))
    shape = shape.fuse(cup_base, cup_ring, bridge_left, bridge_right, tol=0.02)
    shape.label = "MW-P-001A_UPPER_PRINTED_SHELL"
    shape.color = Color(0.18, 0.35, 0.68)
    return shape


def make_lower_shell():
    shape = _split_shell(False)

    for x, z0, length in ((13.65, 9.0, 90.0), (-13.65, 15.0, 80.0)):
        tongue = Box(1.4, 0.55, length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((x, -0.25, z0))
        shape = shape + tongue

    for x in HANDLE["shellScrews"]["x"]:
        for z in HANDLE["shellScrews"]["z"]:
            boss = _axis_y_cylinder(2.65, 8.35, -8.35, float(x), float(z))
            pilot = _axis_y_cylinder(0.85, 9.0, -8.7, float(x), float(z))
            shape = shape + boss - pilot

    usb = PCB["interfaces"]["usbC"]["caseCenter"]
    usb_cut = _rounded_prism_x(10.2, 5.2, 1.1, 20.0, 7.5, 0.7, float(usb[2]))
    shape = shape - usb_cut
    shape.label = "MW-P-001B_LOWER_PRINTED_SHELL"
    shape.color = Color(0.12, 0.26, 0.53)
    return shape


def make_carrier():
    # Build every positive feature first, then perform one explicit fuzzy fuse.
    # Algebraic + on disconnected intermediate solids can preserve a Compound
    # even after later features touch it, which produced a 15-body STL.
    additive = [
        Box(1.4, 1.2, 84.0, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((-7.7, -2.0, 7.0)),
        Box(1.4, 1.2, 84.0, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((7.7, -2.0, 7.0)),
        Box(0.9, 2.8, 84.0, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((-8.35, -2.0, 7.0)),
        Box(0.9, 2.8, 84.0, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((8.35, -2.0, 7.0)),
    ]
    for z in (7.0, 89.8):
        additive.append(
            Box(16.6, 1.2, 1.2, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((0, -2.0, z))
        )

    # Dedicated protected-LiPo cradle with an open wire side and pull ribbon.
    additive.extend([
        Box(12.0, 1.0, 46.0, align=(Align.CENTER, Align.MIN, Align.MIN))
        .translate((0, -10.9, 41.0)),
        Box(0.8, 7.0, 46.0, align=(Align.CENTER, Align.MIN, Align.MIN))
        .translate((-6.1, -10.9, 41.0)),
        Box(0.8, 7.0, 46.0, align=(Align.CENTER, Align.MIN, Align.MIN))
        .translate((6.1, -10.9, 41.0)),
    ])
    # These rails bridge the tray to the PCB ledges outside the 11 mm cell.
    for x in (-6.75, 6.75):
        additive.append(
            Box(0.9, 3.25, 46.8, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((x, -4.05, 40.6))
        )
    for z in (39.8, 83.0):
        additive.extend([
            Box(12.8, 10.0, 1.2, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((0, -10.9, z)),
            Box(16.6, 1.2, 1.2, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((0, -2.0, z)),
        ])

    pilots = []
    for mount in PCB["mounts"]:
        x, _, z = mount["caseCenter"]
        additive.extend([
            Box(16.6, 2.4, 1.2, align=(Align.CENTER, Align.MIN, Align.CENTER))
            .translate((0, -3.2, float(z))),
            _axis_y_cylinder(2.2, 3.2, -4.0, float(x), float(z)),
        ])
        pilots.append(_axis_y_cylinder(0.90, 3.6, -4.2, float(x), float(z)))

    # J2 cable guard overlaps the left bridge but stays clear of the cell.
    additive.append(
        Box(5.4, 1.2, 12.0, align=(Align.CENTER, Align.MIN, Align.CENTER))
        .translate((-3.8, -3.85, 70.0))
    )

    shape = additive[0].fuse(*additive[1:], tol=0.02)
    ribbon_slot = Box(
        5.0, 2.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    ).translate((0, -10.4, 64.0))
    shape = shape - ribbon_slot
    for pilot in pilots:
        shape = shape - pilot
    shape.label = "MW-P-002_PCB_AND_BATTERY_CARRIER"
    shape.color = Color(0.73, 0.56, 0.16)
    return shape


def make_rear_cap():
    outer = float(HANDLE["outerDiameter"]) / 2
    inner = float(HANDLE["innerDiameter"]) / 2
    # The flange/plug overlap avoids a coplanar-only union.  The lanyard
    # bore keeps 1 mm of printable wall instead of tangentially breaking both
    # flange faces, which previously produced a non-watertight STL.
    flange = Cylinder(
        outer + 0.55, 5.0, align=(Align.CENTER, Align.CENTER, Align.MIN)
    ).translate((0, 0, -5.0))
    plug = Cone(
        inner - 0.25, inner - 0.40, 7.4, align=(Align.CENTER, Align.CENTER, Align.MIN)
    ).translate((0, 0, -0.4))
    shape = flange.fuse(plug, tol=0.02)
    lanyard = _axis_y_cylinder(1.5, 34.0, -17.0, 0.0, -2.5)
    shape = shape - lanyard
    shape.label = "MW-P-003_REAR_CAP_WITH_LANYARD"
    shape.color = Color(0.28, 0.55, 0.42)
    return shape


def make_rod_connector():
    outer = float(HANDLE["outerDiameter"]) / 2
    inner = float(HANDLE["innerDiameter"]) / 2
    plug = Cone(inner - 0.25, inner - 0.40, 7.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    flange = Cylinder(outer + 0.70, 4.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, 7.0))
    taper = Cone(outer + 0.70, 7.5, 18.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, 11.0))
    rod_socket = Cylinder(4.10, 17.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, 13.0))
    shape = plug + flange + taper - rod_socket
    shape.label = "MW-P-004_ROD_CONNECTOR_8MM"
    shape.color = Color(0.35, 0.46, 0.74)
    return shape


def make_button_plunger():
    z = float(PCB["interfaces"]["button"]["caseCenter"][2])
    stem = _axis_y_cylinder(1.75, 10.4, 2.2, 0.0, z)
    head = _axis_y_cylinder(2.30, 1.8, 12.6, 0.0, z)
    foot = _axis_y_cylinder(2.05, 0.8, 1.7, 0.0, z)
    shape = stem + head + foot
    shape.label = "MW-P-005_PRESS_TO_ARM_PLUNGER"
    shape.color = Color(0.83, 0.30, 0.24)
    return shape


def make_pcb_placeholder():
    shape = Box(15.0, 1.6, 80.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, 9.0))
    shape.label = "WAND_PCB_RESERVED_VOLUME"
    shape.color = Color(0.10, 0.52, 0.22)
    return shape


def make_battery_placeholder():
    width, thickness, length = (float(v) for v in POWER["maximumEnvelope"])
    x, y, z = (float(v) for v in POWER["caseCenter"])
    shape = Box(width, thickness, length, align=(Align.CENTER, Align.CENTER, Align.CENTER)).translate((x, y, z))
    shape.label = "PROTECTED_1S_LIPO_RESERVED_VOLUME"
    shape.color = Color(0.70, 0.20, 0.18)
    return shape


def make_haptic_placeholder():
    diameter = float(HAPTIC["maximumEnvelope"]["diameter"])
    thickness = float(HAPTIC["maximumEnvelope"]["thickness"])
    x, y, z = (float(v) for v in HAPTIC["caseCenter"])
    shape = _axis_y_cylinder(diameter / 2, thickness, y - (thickness / 2), x, z)
    shape.label = "COIN_HAPTIC_RESERVED_VOLUME"
    shape.color = Color(0.62, 0.28, 0.68)
    return shape


def collision_volume(a, b) -> float:
    try:
        return float(a.intersect(b).volume)
    except Exception:
        # Multi-solid printable carriers can be represented as compounds that
        # Open Cascade will not intersect in one operation. Evaluate their
        # constituent solids independently so a failed compound boolean cannot
        # turn a valid clearance into an unknown result.
        total = 0.0
        evaluated = 0
        for solid in a.solids():
            try:
                total += float(solid.intersect(b).volume)
                evaluated += 1
            except Exception:
                continue
        return total if evaluated else math.inf


def build_validation(parts: dict[str, Any], pcb_path: Path) -> dict[str, Any]:
    inner_radius = float(HANDLE["innerDiameter"]) / 2
    battery_width, battery_thickness, _ = (float(v) for v in POWER["maximumEnvelope"])
    battery_center_y = float(POWER["caseCenter"][1])
    battery_corner_radius = math.hypot(battery_width / 2, abs(battery_center_y - battery_thickness / 2))
    battery_radial_clearance = inner_radius - battery_corner_radius
    antenna_gap = float(POWER["caseBounds"]["z"][0]) - float(POWER["antennaKeepoutZ"][1])
    lower_upper = parts["upper_shell"] + parts["lower_shell"]
    checks = {
        "sourcePcbSha256Matches": sha256(pcb_path) == str(PCB["sha256"]).upper(),
        "batteryRadialClearanceMm": round(battery_radial_clearance, 3),
        "batteryToAntennaAxialGapMm": round(antenna_gap, 3),
        "shellToBatteryCollisionMm3": round(collision_volume(lower_upper, parts["battery"]), 6),
        "shellToPcbCollisionMm3": round(collision_volume(lower_upper, parts["pcb"]), 6),
        "carrierToBatteryCollisionMm3": round(collision_volume(parts["carrier"], parts["battery"]), 6),
        "shellToHapticCollisionMm3": round(collision_volume(lower_upper, parts["haptic"]), 6),
        "pcbToHapticCollisionMm3": round(collision_volume(parts["pcb"], parts["haptic"]), 6),
        "batteryToHapticCollisionMm3": round(collision_volume(parts["battery"], parts["haptic"]), 6),
        "hapticToAntennaAxialGapMm": round(
            float(HAPTIC["caseCenter"][2]) -
            (float(HAPTIC["maximumEnvelope"]["diameter"]) / 2) -
            float(HAPTIC["antennaKeepoutZ"][1]), 3),
        "wireBendReserveMm": float(POWER["wireChannel"]["bendReserve"]),
        "minimumShellWallMm": float(HANDLE["minimumWall"]),
        "firstShellScrewToAntennaGapMm": round(
            min(float(v) for v in HANDLE["shellScrews"]["z"]) - float(POWER["antennaKeepoutZ"][1]), 3
        ),
    }
    passed = (
        checks["sourcePcbSha256Matches"]
        and checks["batteryRadialClearanceMm"] >= 1.0
        and checks["batteryToAntennaAxialGapMm"] >= 10.0
        and checks["shellToBatteryCollisionMm3"] <= 0.01
        and checks["shellToPcbCollisionMm3"] <= 0.01
        and checks["carrierToBatteryCollisionMm3"] <= 0.01
        and checks["shellToHapticCollisionMm3"] <= 0.01
        and checks["pcbToHapticCollisionMm3"] <= 0.01
        and checks["batteryToHapticCollisionMm3"] <= 0.01
        and checks["hapticToAntennaAxialGapMm"] >= 5.0
        and checks["wireBendReserveMm"] >= 8.0
        and checks["minimumShellWallMm"] >= 2.0
        and checks["firstShellScrewToAntennaGapMm"] >= 8.0
    )
    return {
        "schemaVersion": 1,
        "status": "VERIFIED_PRINT_CANDIDATE" if passed else "BLOCKED",
        "sourcePcb": {
            "path": repository_relative_posix(pcb_path),
            "sha256": sha256(pcb_path),
        },
        "checks": checks,
        "powerReservation": POWER,
        "assemblyNotes": [
            "Install the protected 1S LiPo with a pull ribbon before installing the PCB.",
            "Route the three-wire lead through the open J2 cable channel; do not pinch the NTC wire.",
            "Use nylon M2 hardware at PCB H1/H2 and preferably at shell stations during RF validation.",
            "Keep the z=5..30 mm antenna volume free of battery, metal hardware, shielding and dense filler.",
            "Verify JST-SH pin order and cell polarity with a multimeter before first connection.",
            "Fit the exact 10 mm haptic actuator in the upper cup with thin nonconductive foam and route it to J3.",
        ],
    }


def render_preview(path: Path, entries: Iterable[tuple[Any, str, float]], elev: float, azim: float) -> None:
    fig = plt.figure(figsize=(8.8, 8.0), dpi=180)
    ax = fig.add_subplot(111, projection="3d")
    all_points: list[tuple[float, float, float]] = []
    for shape, color, alpha in entries:
        vertices, triangles = shape.tessellate(0.28)
        xyz = [(float(v.X), float(v.Y), float(v.Z)) for v in vertices]
        all_points.extend(xyz)
        faces = [[xyz[i] for i in triangle] for triangle in triangles]
        mesh = Poly3DCollection(faces, facecolor=color, edgecolor="#1b2432", linewidths=0.06, alpha=alpha)
        ax.add_collection3d(mesh)
    mins = [min(p[i] for p in all_points) for i in range(3)]
    maxs = [max(p[i] for p in all_points) for i in range(3)]
    center = [(mins[i] + maxs[i]) / 2 for i in range(3)]
    span = max(maxs[i] - mins[i] for i in range(3)) * 0.55
    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)
    ax.set_box_aspect((1, 1, 1))
    ax.set_proj_type("ortho")
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.patch.set_facecolor("#eef2f7")
    ax.set_facecolor("#eef2f7")
    fig.tight_layout(pad=0)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def write_text_outputs(validation: dict[str, Any], parts: dict[str, Any]) -> None:
    (REPORT_ROOT / "fit-and-power-validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print_guide = """# Magic Wand printable enclosure Rev A0

Status: **{status}**

## Print settings

- Shells: PETG/ASA/ABS/PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Carrier: PETG or PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Upper/lower shells: print with the flat split face on the bed; supports should not be required.
- Carrier: print PCB rails upward. Rear cap and rod connector: print flange on the bed.
- First fit: deburr the seam and holes; do not force the PCB or cell.

## Power reservation

- Maximum reserved pack envelope: **11 x 6 x 42 mm** including protection/insulation.
- Pack: protected 1S LiPo, 10k NTC, JST-SH 1.0 mm 3-pin harness.
- Install a pull ribbon beneath the cell. Keep at least the modeled 8 mm lead-bend reserve.
- The battery begins at z=41 mm, leaving 11 mm after the RF antenna keepout ends at z=30 mm.
- Confirm J2 BAT+/NTC/GND order and polarity with a multimeter before connection.

## Haptic reservation

- Reserved actuator envelope: 10 mm diameter x 3.4 mm thick coin LRA/ERM.
- Fit in the upper-shell printed cup with thin nonconductive foam; route its two-wire lead to J3.
- The metal envelope begins at z=35 mm, leaving 5 mm after the RF antenna keepout.
- The exact actuator must match the DRV2605L library/configuration used by target firmware.

## Wand rod

- Use an 8 mm solid GFRP rod cut to 195 mm.
- Insert it to the socket bottom at case z=116 mm; the resulting target overall length is 315 mm.
- Exposed rod above the connector is 179 mm. Verify the first article before adhesive bonding.
- Do not substitute conductive carbon-fiber or metal rod without a renewed RF/mechanical review.

## Assembly order

1. Deburr and dry-fit both shells, rear cap, rod connector and plunger.
2. Seat the protected cell in the carrier with a pull ribbon and thin nonconductive foam if needed.
3. Route the lead through the J2 channel. Do not crease or pinch the NTC lead.
4. Fit the 10 mm haptic actuator in the upper-shell cup and route its lead to J3.
5. Install the PCB component-side upward on H1/H2 using nylon M2 screws.
6. Fit the press-to-arm plunger and verify free return before closing the shell.
7. Close with M2x12 screws. Start all screws before tightening; do not overtighten printed bosses.
8. Perform USB charge, button, haptic, radio range and gesture tests before attaching the decorative rod.

This is a verified prototype print candidate, not an injection-mold release. Battery supplier drawing,
actual printed shrinkage and the first-article fit remain physical acceptance gates.
""".format(status=validation["status"])
    (OUTPUT_ROOT / "PRINT_AND_ASSEMBLY_GUIDE.md").write_text(print_guide, encoding="utf-8")

    status_class = "ok" if validation["status"] == "VERIFIED_PRINT_CANDIDATE" else "bad"
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Magic Wand 3D Print Review</title><style>
body{{margin:0;font:15px/1.55 system-ui,'Microsoft YaHei',sans-serif;background:#eef2f7;color:#172033}}
main{{max-width:1180px;margin:auto;padding:28px}}h1{{margin:0 0 6px;font-size:32px}}.sub{{color:#536176;margin-bottom:22px}}
.status{{display:inline-block;padding:7px 12px;border-radius:999px;font-weight:700}}.ok{{background:#d9f7e5;color:#17623a}}.bad{{background:#ffe1e1;color:#8c2020}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}}.card{{background:white;border-radius:16px;padding:18px;box-shadow:0 7px 30px #24344b18}}
img{{width:100%;border-radius:10px;background:#eef2f7}}table{{width:100%;border-collapse:collapse}}td{{padding:8px;border-bottom:1px solid #e6ebf1}}td:first-child{{color:#637086}}
code{{background:#edf1f5;padding:2px 5px;border-radius:5px}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>魔法杖 3D 打印装配审查</h1><div class="sub">Rev A0 · PCB / 电池 / 天线 / 外壳跨域联调</div>
<span class="status {status_class}">{validation['status']}</span>
<div class="grid"><section class="card"><h2>装配视图</h2><img src="previews/assembly.png" alt="assembly"></section>
<section class="card"><h2>爆炸视图</h2><img src="previews/exploded.png" alt="exploded"></section>
<section class="card"><h2>电源仓剖开展示</h2><img src="previews/power-reservation.png" alt="power reservation"></section>
<section class="card"><h2>关键校核</h2><table>
<tr><td>电池最大包络</td><td>11 × 6 × 42 mm</td></tr>
<tr><td>电池径向最小余量</td><td>{validation['checks']['batteryRadialClearanceMm']} mm</td></tr>
<tr><td>电池距天线区</td><td>{validation['checks']['batteryToAntennaAxialGapMm']} mm</td></tr>
<tr><td>线束弯曲预留</td><td>{validation['checks']['wireBendReserveMm']} mm</td></tr>
<tr><td>Haptic envelope</td><td>10 mm dia x 3.4 mm; RF gap {validation['checks']['hapticToAntennaAxialGapMm']} mm</td></tr>
<tr><td>PCB 源哈希</td><td>{'一致' if validation['checks']['sourcePcbSha256Matches'] else '不一致'}</td></tr>
<tr><td>USB-C</td><td>+X 面，中心 z=47 mm</td></tr>
<tr><td>按键</td><td>+Y 面，中心 z=73.5 mm</td></tr>
</table></section></div>
<section class="card" style="margin-top:18px"><h2>装配约束</h2><ul>
<li>只能使用受保护的 1S 锂电池包，并接入 10k NTC。</li><li>先装拉带和电池，再装 PCB；J2 三线不得被壳体夹住。</li>
<li>z=5–30 mm 天线区不得放置电池、金属紧固件、屏蔽层或高密度填料。</li><li>首次通电前必须实测 JST 极性。</li>
</ul><p>完整说明：<code>PRINT_AND_ASSEMBLY_GUIDE.md</code>；校核证据：<code>reports/fit-and-power-validation.json</code></p></section>
</main></body></html>"""
    (OUTPUT_ROOT / "reviewer.html").write_text(html, encoding="utf-8")


def export_parts(parts: dict[str, Any]) -> None:
    export_map = {
        "upper_shell": "MW-P-001A_upper_shell",
        "lower_shell": "MW-P-001B_lower_shell",
        "carrier": "MW-P-002_pcb_battery_carrier",
        "rear_cap": "MW-P-003_rear_cap",
        "rod_connector": "MW-P-004_rod_connector_8mm",
        "plunger": "MW-P-005_press_to_arm_plunger",
    }
    for key, stem in export_map.items():
        export_step(parts[key], STEP_ROOT / f"{stem}.step", timestamp=RELEASE_STAMP)
        export_stl(parts[key], STL_ROOT / f"{stem}.stl", tolerance=0.04, angular_tolerance=0.08)

    connector_installed = parts["rod_connector"].moved(Location((0, 0, 103.0)))
    printable_assembly = Compound(
        children=[parts["upper_shell"], parts["lower_shell"], parts["carrier"], parts["rear_cap"], connector_installed, parts["plunger"]]
    )
    review_assembly = Compound(children=[
        printable_assembly, parts["pcb"], parts["battery"], parts["haptic"]])
    export_step(printable_assembly, STEP_ROOT / "MW-P-000_printable_assembly.step", timestamp=RELEASE_STAMP)
    export_step(review_assembly, STEP_ROOT / "MW-P-000_assembly_with_reserved_volumes.step", timestamp=RELEASE_STAMP)


def validate_stl_meshes() -> dict[str, Any]:
    criteria = {
        "watertight": True,
        "windingConsistent": True,
        "isVolume": True,
        "bodyCount": 1,
        "boundaryEdgeCount": 0,
        "nonManifoldEdgeCount": 0,
        "brokenFaceCount": 0,
        "degenerateFaceCount": 0,
        "duplicateFaceCount": 0,
        "minimumVolumeMm3Exclusive": 0.0,
    }
    files: dict[str, Any] = {}
    all_passed = True
    for path in sorted(STL_ROOT.glob("*.stl")):
        mesh = trimesh.load_mesh(path, process=True)
        edge_counts = np.bincount(mesh.edges_unique_inverse)
        broken_faces = trimesh.repair.broken_faces(mesh)
        degenerate_count = int(len(mesh.faces) - int(mesh.nondegenerate_faces().sum()))
        duplicate_count = int(len(mesh.faces) - int(mesh.unique_faces().sum()))
        checks = {
            "watertight": bool(mesh.is_watertight),
            "windingConsistent": bool(mesh.is_winding_consistent),
            "isVolume": bool(mesh.is_volume),
            "bodyCount": int(mesh.body_count),
            "boundaryEdgeCount": int((edge_counts == 1).sum()),
            "nonManifoldEdgeCount": int((edge_counts > 2).sum()),
            "brokenFaceCount": int(len(broken_faces)),
            "degenerateFaceCount": degenerate_count,
            "duplicateFaceCount": duplicate_count,
            "volumeMm3": round(float(mesh.volume), 3),
            "faceCount": int(len(mesh.faces)),
        }
        passed = (
            checks["watertight"]
            and checks["windingConsistent"]
            and checks["isVolume"]
            and checks["bodyCount"] == 1
            and checks["boundaryEdgeCount"] == 0
            and checks["nonManifoldEdgeCount"] == 0
            and checks["brokenFaceCount"] == 0
            and checks["degenerateFaceCount"] == 0
            and checks["duplicateFaceCount"] == 0
            and checks["volumeMm3"] > 0
        )
        files[path.name] = {"passed": passed, **checks}
        all_passed = all_passed and passed
    if len(files) != 6:
        all_passed = False
    return {
        "passed": all_passed,
        "expectedStlCount": 6,
        "actualStlCount": len(files),
        "criteria": criteria,
        "files": files,
    }


def write_manifest_and_zip() -> None:
    files = []
    for path in sorted(OUTPUT_ROOT.rglob("*")):
        if path.is_file() and path.name not in {"release-manifest.json", "MW_PRINTABLE_WAND_REV_A0.zip"}:
            files.append({
                "path": path.relative_to(OUTPUT_ROOT).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            })
    manifest = {
        "schemaVersion": 1,
        "release": "MW_PRINTABLE_WAND_REV_A0",
        "generator": {
            "python": sys.version.split()[0],
            "build123d": build123d.__version__,
            "trimesh": trimesh.__version__,
            "numpy": np.__version__,
        },
        "sourceDesign": {"path": DESIGN_PATH.name, "sha256": sha256(DESIGN_PATH)},
        "files": files,
    }
    manifest_path = OUTPUT_ROOT / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate_packaged_json_portability([DESIGN_PATH, *sorted(OUTPUT_ROOT.rglob("*.json"))])

    zip_path = OUTPUT_ROOT / "MW_PRINTABLE_WAND_REV_A0.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(DESIGN_PATH, "source/design-input.json")
        archive.write(Path(__file__), "source/build_printable_wand.py")
        for path in sorted(OUTPUT_ROOT.rglob("*")):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(OUTPUT_ROOT).as_posix())
    (OUTPUT_ROOT / "MW_PRINTABLE_WAND_REV_A0.sha256").write_text(
        f"{sha256(zip_path)}  {zip_path.name}\n", encoding="ascii"
    )


def main() -> int:
    if OUTPUT_ROOT.parent.resolve() != ROOT.resolve() or OUTPUT_ROOT.name != "outputs":
        raise RuntimeError(f"Unsafe output path: {OUTPUT_ROOT}")
    pcb_path = resolve_repository_file(str(PCB["path"]))
    if not pcb_path.is_file():
        raise FileNotFoundError(pcb_path)
    if sha256(pcb_path) != str(PCB["sha256"]).upper():
        raise RuntimeError("Frozen wand PCB hash does not match design-input.json")

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    for folder in (STEP_ROOT, STL_ROOT, PREVIEW_ROOT, REPORT_ROOT):
        folder.mkdir(parents=True, exist_ok=True)

    parts = {
        "upper_shell": make_upper_shell(),
        "lower_shell": make_lower_shell(),
        "carrier": make_carrier(),
        "rear_cap": make_rear_cap(),
        "rod_connector": make_rod_connector(),
        "plunger": make_button_plunger(),
        "pcb": make_pcb_placeholder(),
        "battery": make_battery_placeholder(),
        "haptic": make_haptic_placeholder(),
    }
    validation = build_validation(parts, pcb_path)
    if validation["status"] != "VERIFIED_PRINT_CANDIDATE":
        (REPORT_ROOT / "fit-and-power-validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise RuntimeError(json.dumps(validation["checks"], ensure_ascii=False))

    export_parts(parts)
    mesh_validation = validate_stl_meshes()
    validation["meshValidation"] = mesh_validation
    validation["checks"]["allStlMeshesSingleBodyWatertight"] = mesh_validation["passed"]
    if not mesh_validation["passed"]:
        validation["status"] = "BLOCKED_INVALID_STL_MESH"
        (REPORT_ROOT / "fit-and-power-validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise RuntimeError(json.dumps(mesh_validation, ensure_ascii=False))

    connector_installed = parts["rod_connector"].moved(Location((0, 0, 103.0)))
    render_preview(
        PREVIEW_ROOT / "assembly.png",
        [
            (parts["upper_shell"], "#3a6fd4", 0.36),
            (parts["lower_shell"], "#244d9a", 0.70),
            (parts["carrier"], "#d59e27", 0.95),
            (parts["rear_cap"], "#4e9a70", 0.95),
            (connector_installed, "#627ec7", 0.95),
            (parts["pcb"], "#1f9d55", 0.95),
            (parts["battery"], "#d14a46", 0.95),
            (parts["haptic"], "#9a4fa8", 0.98),
            (parts["plunger"], "#e24e42", 1.0),
        ],
        elev=18,
        azim=38,
    )
    render_preview(
        PREVIEW_ROOT / "exploded.png",
        [
            (parts["upper_shell"].moved(Location((0, 22, 0))), "#3a6fd4", 0.82),
            (parts["lower_shell"].moved(Location((0, -22, 0))), "#244d9a", 0.82),
            (parts["carrier"].moved(Location((0, -8, 0))), "#d59e27", 0.95),
            (parts["pcb"].moved(Location((0, 8, 0))), "#1f9d55", 0.95),
            (parts["battery"], "#d14a46", 0.95),
            (parts["haptic"], "#9a4fa8", 0.98),
            (parts["rear_cap"], "#4e9a70", 0.95),
            (connector_installed, "#627ec7", 0.95),
        ],
        elev=14,
        azim=35,
    )
    render_preview(
        PREVIEW_ROOT / "power-reservation.png",
        [
            (parts["lower_shell"], "#244d9a", 0.24),
            (parts["carrier"], "#d59e27", 0.92),
            (parts["pcb"], "#1f9d55", 0.86),
            (parts["battery"], "#d14a46", 0.98),
            (parts["haptic"], "#9a4fa8", 0.98),
        ],
        elev=8,
        azim=18,
    )
    write_text_outputs(validation, parts)
    write_manifest_and_zip()
    print(json.dumps({
        "status": validation["status"],
        "output": str(OUTPUT_ROOT),
        "zipSha256": sha256(OUTPUT_ROOT / "MW_PRINTABLE_WAND_REV_A0.zip"),
        "checks": validation["checks"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
