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
CARRIER = P["carrier"]
BUTTON = P["buttonMechanism"]
USB = P["usbService"]
ROD = P["rod"]
PHYSICAL_GATES = P["physicalAcceptanceGates"]
COMPONENT_ENVELOPE = PCB["componentEnvelope"]
FASTENER_TOOL_SWEEP = HANDLE["shellScrews"]["driverSweep"]


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


def load_frozen_factory_design() -> tuple[Path, dict[str, Any]]:
    path = resolve_repository_file(str(COMPONENT_ENVELOPE["factoryDesignPath"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_hash = str(COMPONENT_ENVELOPE["factoryDesignSha256"]).upper()
    if sha256(path) != expected_hash:
        raise RuntimeError("Frozen wand factory-design hash does not match design-input.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("components"), list):
        raise ValueError("wand-factory-design.json must contain a components array")
    return path, value


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


def _usb_external_cut():
    usb = PCB["interfaces"]["usbC"]["caseCenter"]
    width_y, height_z = (float(value) for value in USB["externalOpeningSize"])
    return _rounded_prism_x(width_y, height_z, 1.1, 20.0, 7.5, float(USB["externalOpeningCenterY"]), float(usb[2]))


def _usb_internal_counterbore():
    width_y, height_z = (float(value) for value in USB["internalCounterboreSize"])
    depth = float(USB["internalCounterboreDepth"])
    usb = PCB["interfaces"]["usbC"]["caseCenter"]
    return _rounded_prism_x(width_y, height_z, 1.35, depth, float(USB["internalCounterboreCenterX"]), float(USB["externalOpeningCenterY"]), float(usb[2]))


def make_usb_plug_sweep():
    plug = USB["plugSweep"]
    usb = PCB["interfaces"]["usbC"]["caseCenter"]
    mating_x = float(usb[0]) + float(USB["receptacleMatingFaceOffsetX"])
    center_y = float(USB["externalOpeningCenterY"])
    outer_radius = float(HANDLE["outerDiameter"]) / 2
    outer_x = math.sqrt(max(0.0, outer_radius ** 2 - center_y ** 2))
    depth = float(plug["nominalReach"])
    shape = _rounded_prism_x(float(plug["widthY"]), float(plug["heightZ"]), float(plug["cornerRadius"]), depth, mating_x + depth / 2, center_y, float(usb[2]))
    shape.label = "USB_C_PARAMETERIZED_PLUG_SWEEP"
    shape.color = Color(0.16, 0.72, 0.78)
    return shape


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

    # Keep the complete split face on Y=0 so this half can sit flat on the bed.
    # Shell screw bosses provide registration without cross-plane seam keys.

    # Screw columns are outside the 15 mm PCB width and outside the antenna
    # keepout.  Nylon M2 hardware is specified for the prototype.
    for x in HANDLE["shellScrews"]["x"]:
        for z in HANDLE["shellScrews"]["z"]:
            boss = _axis_y_cylinder(float(HANDLE["shellScrews"]["bossRadius"]), 8.35, 0.0, float(x), float(z))
            clearance = _axis_y_cylinder(1.20, 16.0, -0.5, float(x), float(z))
            counterbore = _axis_y_cylinder(2.25, 7.0, 8.1, float(x), float(z))
            shape = shape + boss - clearance - counterbore

    # Stepped SW1 guide: the inner sleeve captures the removable C-retainer;
    # the counterbore shoulder at hardStopY limits inward motion to 0.25 mm.
    button_z = float(PCB["interfaces"]["button"]["caseCenter"][2])
    plunger = BUTTON["plunger"]
    guide_start = 11.85
    hard_stop_y = float(plunger["hardStopY"])
    shape = shape - _axis_y_cylinder(float(plunger["guideRadius"]), 17.0, -0.5, 0.0, button_z)
    guide = _axis_y_cylinder(float(plunger["guideOuterRadius"]), 1.60, guide_start, 0.0, button_z) - _axis_y_cylinder(float(plunger["guideRadius"]), 1.80, guide_start - 0.1, 0.0, button_z)
    shape = shape.fuse(guide, tol=0.02)
    shape = shape - _axis_y_cylinder(float(plunger["retainerOuterRadius"]), 4.6, hard_stop_y, 0.0, button_z)
    guard = _axis_y_cylinder(4.60, 3.45, 11.75, 0.0, button_z) - _axis_y_cylinder(float(plunger["retainerOuterRadius"]), 3.7, 11.60, 0.0, button_z)
    shape = shape.fuse(guard, tol=0.02)

    # J1 faces +X.  The rounded opening spans the split deliberately so the
    # connector cannot be trapped by either printed half.
    shape = shape - _usb_external_cut() - _usb_internal_counterbore()

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

    # No positive feature crosses Y=0; the lower split face remains printable.

    for x in HANDLE["shellScrews"]["x"]:
        for z in HANDLE["shellScrews"]["z"]:
            boss = _axis_y_cylinder(float(HANDLE["shellScrews"]["bossRadius"]), 8.35, -8.35, float(x), float(z))
            pilot = _axis_y_cylinder(0.85, 9.0, -8.7, float(x), float(z))
            shape = shape + boss - pilot

    axial_min, axial_max = (float(value) for value in CARRIER["axialBounds"])
    axial_clearance = float(CARRIER["axialStopClearance"])
    lateral_clearance = float(CARRIER["lateralKeyClearance"])
    rail_outer = 8.8
    retention_features = []
    for sign in (-1.0, 1.0):
        stop_center_x = sign * 10.45
        for z_start in (axial_min - axial_clearance - 0.6, axial_max + axial_clearance):
            retention_features.append(
                Box(5.5, 1.8, 0.6, align=(Align.CENTER, Align.MIN, Align.MIN))
                .translate((stop_center_x, -2.0, z_start))
            )
        key_inner = rail_outer + lateral_clearance
        key_width = 13.2 - key_inner
        key_center_x = sign * (key_inner + key_width / 2)
        for key_z in (18.0, 68.0):
            retention_features.append(
                Box(key_width, 1.8, 6.0, align=(Align.CENTER, Align.MIN, Align.MIN))
                .translate((key_center_x, -2.0, key_z))
            )
    shape = shape.fuse(*retention_features, tol=0.02)

    shape = shape - _usb_external_cut() - _usb_internal_counterbore()
    shape.label = "MW-P-001B_LOWER_PRINTED_SHELL"
    shape.color = Color(0.12, 0.26, 0.53)
    return shape


def make_carrier():
    # Build every positive feature first, then perform one explicit fuzzy fuse.
    # Algebraic + on disconnected intermediate solids can preserve a Compound
    # even after later features touch it, which produced a 15-body STL.
    axial_min, axial_max = (float(value) for value in CARRIER["axialBounds"])
    carrier_length = axial_max - axial_min
    boss_relief_radius = float(HANDLE["shellScrews"]["bossRadius"]) + float(CARRIER["shellBossClearance"])
    additive = [
        Box(1.4, 1.2, carrier_length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((-7.7, -2.0, axial_min)),
        Box(1.4, 1.2, carrier_length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((7.7, -2.0, axial_min)),
        Box(0.9, 2.8, carrier_length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((-8.35, -2.0, axial_min)),
        Box(0.9, 2.8, carrier_length, align=(Align.CENTER, Align.MIN, Align.MIN)).translate((8.35, -2.0, axial_min)),
    ]
    for sign in (-1.0, 1.0):
        additive.append(
            Box(2.4, 1.0, 8.0, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((sign * 7.0, -2.9, 34.0))
        )
    for z in (axial_min, axial_max - 1.2):
        additive.append(
            Box(16.6, 1.2, 1.2, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((0, -2.0, z))
        )

    fit = POWER["carrierFit"]
    battery_width, _, battery_length = (float(value) for value in POWER["maximumEnvelope"])
    battery_z_min, battery_z_max = (float(value) for value in POWER["caseBounds"]["z"])
    side_clearance = float(fit["sideClearancePerSide"])
    axial_clearance = float(fit["axialClearancePerEnd"])
    clip_thickness = float(fit["lateralClipThickness"])
    tray_z_min = battery_z_min - axial_clearance
    tray_z_max = battery_z_max + axial_clearance
    tray_length = battery_length + 2 * axial_clearance
    clip_inner = battery_width / 2 + side_clearance

    # Open cradle: floor datum, segmented upper clips, removable strap and pull ribbon.
    additive.append(
        Box(battery_width + 2 * side_clearance + 0.2, 1.0, tray_length, align=(Align.CENTER, Align.MIN, Align.MIN))
        .translate((0, -10.9, tray_z_min))
    )
    # These rails bridge the tray and clips to the PCB ledges.
    for x in (-6.75, 6.75):
        additive.append(
            Box(0.9, 3.25, 46.8, align=(Align.CENTER, Align.MIN, Align.MIN))
            .translate((x, -4.05, tray_z_min))
        )
    for sign in (-1.0, 1.0):
        clip_center_x = sign * (clip_inner + clip_thickness / 2)
        for clip_z in (44.0, 72.0):
            additive.append(
                Box(clip_thickness, 3.8, 8.0, align=(Align.CENTER, Align.MIN, Align.MIN))
                .translate((clip_center_x, -7.7, clip_z))
            )
    for z in (tray_z_min - 1.2, tray_z_max):
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
    first_screw_z = min(float(value) for value in HANDLE["shellScrews"]["z"])
    for screw_x in HANDLE["shellScrews"]["x"]:
        relief = _axis_y_cylinder(boss_relief_radius, 10.5, -9.0, float(screw_x), first_screw_z)
        shape = shape - relief
    ribbon_slot = Box(
        5.0, 2.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    ).translate((0, -10.4, 64.0))
    shape = shape - ribbon_slot
    for sign in (-1.0, 1.0):
        strap_slot = Box(
            float(fit["strapSlotLength"]), 2.0, float(fit["strapSlotWidth"]),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        ).translate((sign * 4.2, -10.4, 61.0))
        shape = shape - strap_slot
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
    cfg = BUTTON["plunger"]
    z = float(PCB["interfaces"]["button"]["caseCenter"][2])
    stem_y_start = float(cfg["stemReleasedYStart"])
    head_y_start = float(cfg["headReleasedYStart"])
    stem = _axis_y_cylinder(float(cfg["stemRadius"]), head_y_start - stem_y_start, stem_y_start, 0.0, z)
    head = _axis_y_cylinder(float(cfg["headRadius"]), float(cfg["headLength"]), head_y_start, 0.0, z)
    shape = stem.fuse(head, tol=0.02)
    groove = (
        _axis_y_cylinder(float(cfg["stemRadius"]) + 0.05, float(cfg["retainerLength"]), float(cfg["retainerReleasedYStart"]), 0.0, z)
        - _axis_y_cylinder(float(cfg["retainerInnerRadius"]), float(cfg["retainerLength"]) + 0.2, float(cfg["retainerReleasedYStart"]) - 0.1, 0.0, z)
    )
    shape = shape - groove
    shape.label = "MW-P-005_PRESS_TO_ARM_PLUNGER"
    shape.color = Color(0.83, 0.30, 0.24)
    return shape


def make_button_retainer():
    cfg = BUTTON["plunger"]
    z = float(PCB["interfaces"]["button"]["caseCenter"][2])
    y_start = float(cfg["retainerReleasedYStart"])
    ring = (
        _axis_y_cylinder(float(cfg["retainerOuterRadius"]), float(cfg["retainerLength"]), y_start, 0.0, z)
        - _axis_y_cylinder(float(cfg["retainerInnerRadius"]), float(cfg["retainerLength"]) + 0.2, y_start - 0.1, 0.0, z)
    )
    slit = Box(
        2.0, 1.0, 1.2, align=(Align.MIN, Align.MIN, Align.CENTER)
    ).translate((1.2, y_start - 0.2, z))
    shape = ring - slit
    shape.label = "MW-P-006_PLUNGER_C_RETAINER"
    shape.color = Color(0.95, 0.62, 0.16)
    return shape


def make_switch_placeholder():
    switch = BUTTON["switch"]
    x_size, z_size = (float(value) for value in switch["bodyPlanarSize"])
    z = float(PCB["interfaces"]["button"]["caseCenter"][2])
    shape = Box(x_size, float(switch["bodyHeight"]), z_size, align=(Align.CENTER, Align.MIN, Align.CENTER)).translate((0, float(switch["pcbComponentSurfaceCaseY"]), z))
    shape.label = "SKQGAFE010_CONSERVATIVE_BODY_VOLUME"
    shape.color = Color(0.24, 0.24, 0.28)
    return shape


def make_rod_placeholder():
    radius = float(ROD["diameter"]) / 2
    length = float(ROD["cutLength"])
    z = float(ROD["socketBottomCaseZ"])
    shape = Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, z))
    shape.label = "PURCHASED_8MM_GFRP_ROD_RESERVED_VOLUME"
    shape.color = Color(0.72, 0.63, 0.42)
    return shape


def make_pcb_placeholder():
    shape = Box(15.0, 1.6, 80.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).translate((0, 0, 9.0))
    shape.label = "WAND_PCB_RESERVED_VOLUME"
    shape.color = Color(0.10, 0.52, 0.22)
    return shape


def _rotated_planar_bounds(
    bounds: Iterable[float], rotation_degrees: float
) -> tuple[float, float, float, float]:
    values = [float(value) for value in bounds]
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError(f"invalid component body bounds: {values!r}")
    x_min, z_min, x_max, z_max = values
    if x_max <= x_min or z_max <= z_min:
        raise ValueError(f"non-positive component body bounds: {values!r}")
    angle = math.radians(float(rotation_degrees))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    corners = []
    for x_value in (x_min, x_max):
        for z_value in (z_min, z_max):
            corners.append((
                (x_value * cosine) - (z_value * sine),
                (x_value * sine) + (z_value * cosine),
            ))
    return (
        min(value[0] for value in corners),
        min(value[1] for value in corners),
        max(value[0] for value in corners),
        max(value[1] for value in corners),
    )


def make_pcb_component_envelopes(
    factory_design: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    included_assemblies = {
        str(value) for value in COMPONENT_ENVELOPE["includedAssemblies"]
    }
    planar_clearance = float(COMPONENT_ENVELOPE["planarClearancePerSide"])
    normal_clearance = float(COMPONENT_ENVELOPE["normalClearance"])
    transform = PCB["caseTransformMm"]
    x_offset = float(transform["xOffset"])
    z_offset = float(transform["zOffset"])
    y_min = float(transform["topSurfaceY"])
    records: list[dict[str, Any]] = []
    seen_references: set[str] = set()

    if planar_clearance < 0 or normal_clearance < 0:
        raise ValueError("component-envelope clearances must be non-negative")
    for component in factory_design["components"]:
        assembly = str(component.get("assembly", ""))
        height = float(component.get("body_height_mm", 0.0))
        if bool(component.get("dnp")) or assembly not in included_assemblies or height <= 0:
            continue
        reference = str(component.get("ref", "")).strip()
        if not reference or reference in seen_references:
            raise ValueError(f"missing or duplicate component reference: {reference!r}")
        seen_references.add(reference)
        local_x_min, local_z_min, local_x_max, local_z_max = _rotated_planar_bounds(
            component["fab_bounds"], float(component.get("rotation", 0.0))
        )
        x_min = float(component["x"]) + x_offset + local_x_min - planar_clearance
        x_max = float(component["x"]) + x_offset + local_x_max + planar_clearance
        z_min = float(component["y"]) + z_offset + local_z_min - planar_clearance
        z_max = float(component["y"]) + z_offset + local_z_max + planar_clearance
        y_max = y_min + height + normal_clearance
        shape = Box(
            x_max - x_min,
            y_max - y_min,
            z_max - z_min,
            align=(Align.CENTER, Align.MIN, Align.CENTER),
        ).translate(((x_min + x_max) / 2, y_min, (z_min + z_max) / 2))
        shape.label = f"{reference}_CONSERVATIVE_COMPONENT_ENVELOPE"
        shape.color = Color(0.36, 0.32, 0.50)
        records.append({
            "ref": reference,
            "assembly": assembly,
            "bodyHeightMm": round(height, 3),
            "caseBoundsMm": {
                "x": [round(x_min, 3), round(x_max, 3)],
                "y": [round(y_min, 3), round(y_max, 3)],
                "z": [round(z_min, 3), round(z_max, 3)],
            },
            "shape": shape,
        })
    if not records:
        raise RuntimeError("frozen factory design produced no component envelopes")
    return Compound(children=[record["shape"] for record in records]), records


def make_fastener_tool_sweeps() -> tuple[Any, list[dict[str, Any]]]:
    radius = float(FASTENER_TOOL_SWEEP["radius"])
    seat_y = float(FASTENER_TOOL_SWEEP["seatY"])
    entry_y = float(FASTENER_TOOL_SWEEP["entryY"])
    if radius <= 0 or entry_y <= seat_y:
        raise ValueError("invalid fastener driver-sweep dimensions")
    records: list[dict[str, Any]] = []
    for x_value in HANDLE["shellScrews"]["x"]:
        for z_value in HANDLE["shellScrews"]["z"]:
            x = float(x_value)
            z = float(z_value)
            shape = _axis_y_cylinder(radius, entry_y - seat_y, seat_y, x, z)
            shape.label = f"M2_DRIVER_SWEEP_X{x:.2f}_Z{z:.2f}"
            shape.color = Color(0.92, 0.55, 0.12)
            records.append({
                "caseCenterXZMm": [round(x, 3), round(z, 3)],
                "radiusMm": round(radius, 3),
                "seatYmm": round(seat_y, 3),
                "entryYmm": round(entry_y, 3),
                "shape": shape,
            })
    return Compound(children=[record["shape"] for record in records]), records


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


def _intersection_volume(value: Any) -> float:
    if value is None:
        return 0.0
    if hasattr(value, "volume"):
        return float(value.volume)
    try:
        return sum(float(item.volume) for item in value)
    except TypeError:
        return math.inf


def collision_volume(a, b) -> float:
    try:
        return _intersection_volume(a.intersect(b))
    except Exception:
        # Multi-solid printable carriers can be represented as compounds that
        # Open Cascade will not intersect in one operation. Evaluate their
        # constituent solids independently so a failed compound boolean cannot
        # turn a valid clearance into an unknown result.
        total = 0.0
        evaluated = 0
        for solid in a.solids():
            try:
                total += _intersection_volume(solid.intersect(b))
                evaluated += 1
            except Exception:
                continue
        return total if evaluated else math.inf


def build_validation(
    parts: dict[str, Any], pcb_path: Path, factory_design_path: Path
) -> dict[str, Any]:
    inner_radius = float(HANDLE["innerDiameter"]) / 2
    battery_width, battery_thickness, _ = (float(value) for value in POWER["maximumEnvelope"])
    battery_center_y = float(POWER["caseCenter"][1])
    battery_corner_radius = math.hypot(
        battery_width / 2, abs(battery_center_y - battery_thickness / 2)
    )
    battery_radial_clearance = inner_radius - battery_corner_radius
    antenna_gap = (
        float(POWER["caseBounds"]["z"][0])
        - float(POWER["antennaKeepoutZ"][1])
    )
    shell = parts["upper_shell"] + parts["lower_shell"]
    fit = POWER["carrierFit"]
    button = BUTTON["plunger"]
    switch = BUTTON["switch"]
    plug = USB["plugSweep"]
    component_records = parts["pcb_component_envelope_records"]
    tool_sweep_records = parts["fastener_tool_sweep_records"]

    component_shell_collisions = {
        record["ref"]: round(collision_volume(shell, record["shape"]), 6)
        for record in component_records
    }
    component_carrier_collisions = {
        record["ref"]: round(
            collision_volume(parts["carrier"], record["shape"]), 6
        )
        for record in component_records
    }
    component_collision_references = sorted({
        reference
        for reference in component_shell_collisions
        if component_shell_collisions[reference] > 0.01
        or component_carrier_collisions[reference] > 0.01
    })
    tool_shell_collision = sum(
        collision_volume(parts["upper_shell"], record["shape"])
        for record in tool_sweep_records
    )
    tool_internal_collision = sum(
        collision_volume(reserved, record["shape"])
        for record in tool_sweep_records
        for reserved in (
            parts["pcb"],
            parts["pcb_component_envelopes"],
            parts["battery"],
            parts["haptic"],
        )
    )
    tool_radial_clearance = (
        float(FASTENER_TOOL_SWEEP["counterboreRadius"])
        - float(FASTENER_TOOL_SWEEP["radius"])
    )

    pressed_travel = float(button["pressedTravel"])
    pressed_plunger = parts["plunger"].moved(Location((0, -pressed_travel, 0)))
    pressed_retainer = parts["plunger_retainer"].moved(
        Location((0, -pressed_travel, 0))
    )
    switch_top_y = (
        float(switch["pcbComponentSurfaceCaseY"])
        + float(switch["bodyHeight"])
    )
    released_tip_y = float(button["stemReleasedYStart"])
    pressed_tip_y = released_tip_y - pressed_travel
    released_switch_gap = released_tip_y - switch_top_y
    pressed_switch_actuation = max(0.0, switch_top_y - pressed_tip_y)
    hard_stop_travel = (
        float(button["headReleasedYStart"]) - float(button["hardStopY"])
    )
    retainer_capture = (
        float(button["retainerOuterRadius"]) - float(button["guideRadius"])
    )
    retainer_axial_clearance = (
        11.85
        - (
            float(button["retainerReleasedYStart"])
            + float(button["retainerLength"])
        )
    )

    external_width, external_height = (
        float(value) for value in USB["externalOpeningSize"]
    )
    usb = PCB["interfaces"]["usbC"]["caseCenter"]
    mating_x = float(usb[0]) + float(USB["receptacleMatingFaceOffsetX"])
    opening_y = float(USB["externalOpeningCenterY"])
    outer_radius = float(HANDLE["outerDiameter"]) / 2
    outer_x = math.sqrt(max(0.0, outer_radius ** 2 - opening_y ** 2))
    usb_recess = outer_x - mating_x
    usb_required_reach = usb_recess + float(plug["minimumProcessClearance"])
    usb_reach_margin = float(plug["nominalReach"]) - usb_required_reach
    usb_lateral_clearance = (external_width - float(plug["widthY"])) / 2
    usb_vertical_clearance = (external_height - float(plug["heightZ"])) / 2

    upper_bbox = parts["upper_shell"].bounding_box()
    lower_bbox = parts["lower_shell"].bounding_box()
    upper_split_below_plane = max(0.0, -float(upper_bbox.min.Y))
    lower_split_above_plane = max(0.0, float(lower_bbox.max.Y))

    full_assembly = Compound(
        children=[
            parts["upper_shell"],
            parts["lower_shell"],
            parts["carrier"],
            parts["rear_cap"],
            parts["rod_connector"].moved(Location((0, 0, 103.0))),
            parts["rod"],
            parts["plunger"],
            parts["plunger_retainer"],
        ]
    )
    full_bbox = full_assembly.bounding_box()
    overall_length = float(full_bbox.max.Z - full_bbox.min.Z)
    carrier_solid_count = len(parts["carrier"].solids())

    checks = {
        "sourcePcbSha256Matches": (
            sha256(pcb_path) == str(PCB["sha256"]).upper()
        ),
        "sourceFactoryDesignSha256Matches": (
            sha256(factory_design_path)
            == str(COMPONENT_ENVELOPE["factoryDesignSha256"]).upper()
        ),
        "pcbComponentEnvelopeCount": len(component_records),
        "pcbComponentEnvelopeExpectedCount": int(
            COMPONENT_ENVELOPE["expectedIncludedCount"]
        ),
        "shellToPcbComponentEnvelopeCollisionMm3": round(
            sum(component_shell_collisions.values()), 6
        ),
        "carrierToPcbComponentEnvelopeCollisionMm3": round(
            sum(component_carrier_collisions.values()), 6
        ),
        "pcbComponentEnvelopeCollisionReferences": component_collision_references,
        "fastenerToolSweepCount": len(tool_sweep_records),
        "fastenerToolSweepRadialClearanceMm": round(
            tool_radial_clearance, 3
        ),
        "fastenerToolSweepToUpperShellCollisionMm3": round(
            tool_shell_collision, 6
        ),
        "fastenerToolSweepToInternalReservedVolumeCollisionMm3": round(
            tool_internal_collision, 6
        ),
        "batteryRadialClearanceMm": round(battery_radial_clearance, 3),
        "batteryToAntennaAxialGapMm": round(antenna_gap, 3),
        "batterySideClearancePerSideMm": round(
            float(fit["sideClearancePerSide"]), 3
        ),
        "batteryAxialClearancePerEndMm": round(
            float(fit["axialClearancePerEnd"]), 3
        ),
        "batteryRetentionStrategyPresent": bool(
            fit.get("retention")
            and float(fit["strapSlotWidth"]) >= 3.0
            and float(fit["maximumStrapThickness"]) > 0
        ),
        "shellToBatteryCollisionMm3": round(
            collision_volume(shell, parts["battery"]), 6
        ),
        "shellToPcbCollisionMm3": round(
            collision_volume(shell, parts["pcb"]), 6
        ),
        "upperShellToCarrierCollisionMm3": round(
            collision_volume(parts["upper_shell"], parts["carrier"]), 6
        ),
        "lowerShellToCarrierCollisionMm3": round(
            collision_volume(parts["lower_shell"], parts["carrier"]), 6
        ),
        "carrierToBatteryCollisionMm3": round(
            collision_volume(parts["carrier"], parts["battery"]), 6
        ),
        "carrierSolidCount": carrier_solid_count,
        "carrierBossReliefRadiusMm": round(
            float(HANDLE["shellScrews"]["bossRadius"])
            + float(CARRIER["shellBossClearance"]),
            3,
        ),
        "carrierAxialStopClearanceMm": round(
            float(CARRIER["axialStopClearance"]), 3
        ),
        "carrierLateralKeyClearanceMm": round(
            float(CARRIER["lateralKeyClearance"]), 3
        ),
        "upperShellToPlungerReleasedCollisionMm3": round(
            collision_volume(parts["upper_shell"], parts["plunger"]), 6
        ),
        "upperShellToPlungerPressedCollisionMm3": round(
            collision_volume(parts["upper_shell"], pressed_plunger), 6
        ),
        "upperShellToRetainerReleasedCollisionMm3": round(
            collision_volume(parts["upper_shell"], parts["plunger_retainer"]), 6
        ),
        "upperShellToRetainerPressedCollisionMm3": round(
            collision_volume(parts["upper_shell"], pressed_retainer), 6
        ),
        "plungerToRetainerCollisionMm3": round(
            collision_volume(parts["plunger"], parts["plunger_retainer"]), 6
        ),
        "buttonReleasedSwitchGapMm": round(released_switch_gap, 3),
        "buttonPressedActuationMm": round(pressed_switch_actuation, 3),
        "buttonMaximumSwitchTravelMm": round(float(switch["travel"]), 3),
        "buttonHardStopTravelMm": round(hard_stop_travel, 3),
        "buttonRetainerRadialCaptureMm": round(retainer_capture, 3),
        "buttonRetainerAxialClearanceMm": round(
            retainer_axial_clearance, 3
        ),
        "switchBodyToShellCollisionMm3": round(
            collision_volume(shell, parts["switch"]), 6
        ),
        "switchBodyToCarrierCollisionMm3": round(
            collision_volume(parts["carrier"], parts["switch"]), 6
        ),
        "usbMatingFaceCaseXmm": round(mating_x, 3),
        "usbOuterSurfaceCaseXmm": round(outer_x, 3),
        "usbRecessMm": round(usb_recess, 3),
        "usbRequiredReachWithProcessClearanceMm": round(
            usb_required_reach, 3
        ),
        "usbNominalPlugSweepReachMm": round(
            float(plug["nominalReach"]), 3
        ),
        "usbReachMarginMm": round(usb_reach_margin, 3),
        "usbPlugLateralClearanceMm": round(usb_lateral_clearance, 3),
        "usbPlugVerticalClearanceMm": round(usb_vertical_clearance, 3),
        "usbPlugSweepToShellCollisionMm3": round(
            collision_volume(shell, parts["usb_plug_sweep"]), 6
        ),
        "upperSplitFaceBelowY0Mm": round(upper_split_below_plane, 6),
        "lowerSplitFaceAboveY0Mm": round(lower_split_above_plane, 6),
        "completeAssemblyOverallLengthMm": round(overall_length, 3),
        "targetAssemblyOverallLengthMm": float(ROD["assembledOverallLength"]),
        "shellToHapticCollisionMm3": round(
            collision_volume(shell, parts["haptic"]), 6
        ),
        "pcbToHapticCollisionMm3": round(
            collision_volume(parts["pcb"], parts["haptic"]), 6
        ),
        "batteryToHapticCollisionMm3": round(
            collision_volume(parts["battery"], parts["haptic"]), 6
        ),
        "hapticToAntennaAxialGapMm": round(
            float(HAPTIC["caseCenter"][2])
            - (float(HAPTIC["maximumEnvelope"]["diameter"]) / 2)
            - float(HAPTIC["antennaKeepoutZ"][1]),
            3,
        ),
        "wireBendReserveMm": float(POWER["wireChannel"]["bendReserve"]),
        "minimumShellWallMm": float(HANDLE["minimumWall"]),
        "firstShellScrewToAntennaGapMm": round(
            min(float(value) for value in HANDLE["shellScrews"]["z"])
            - float(POWER["antennaKeepoutZ"][1]),
            3,
        ),
    }

    min_process_clearance = float(plug["minimumProcessClearance"])
    geometry_passed = (
        checks["sourcePcbSha256Matches"]
        and checks["sourceFactoryDesignSha256Matches"]
        and checks["pcbComponentEnvelopeCount"]
        == checks["pcbComponentEnvelopeExpectedCount"]
        and checks["shellToPcbComponentEnvelopeCollisionMm3"] <= 0.01
        and checks["carrierToPcbComponentEnvelopeCollisionMm3"] <= 0.01
        and not checks["pcbComponentEnvelopeCollisionReferences"]
        and checks["fastenerToolSweepCount"] == 4
        and checks["fastenerToolSweepRadialClearanceMm"]
        >= float(FASTENER_TOOL_SWEEP["minimumRadialClearance"])
        and checks["fastenerToolSweepToUpperShellCollisionMm3"] <= 0.01
        and checks["fastenerToolSweepToInternalReservedVolumeCollisionMm3"] <= 0.01
        and checks["batteryRadialClearanceMm"] >= 1.0
        and checks["batteryToAntennaAxialGapMm"] >= 10.0
        and checks["batterySideClearancePerSideMm"] >= 0.35
        and checks["batteryAxialClearancePerEndMm"] >= 0.30
        and checks["batteryRetentionStrategyPresent"]
        and checks["shellToBatteryCollisionMm3"] <= 0.01
        and checks["shellToPcbCollisionMm3"] <= 0.01
        and checks["upperShellToCarrierCollisionMm3"] <= 0.01
        and checks["lowerShellToCarrierCollisionMm3"] <= 0.01
        and checks["carrierToBatteryCollisionMm3"] <= 0.01
        and checks["carrierSolidCount"] == 1
        and checks["carrierBossReliefRadiusMm"] >= 2.95
        and checks["carrierAxialStopClearanceMm"] >= 0.25
        and checks["carrierLateralKeyClearanceMm"] >= 0.25
        and checks["upperShellToPlungerReleasedCollisionMm3"] <= 0.01
        and checks["upperShellToPlungerPressedCollisionMm3"] <= 0.01
        and checks["upperShellToRetainerReleasedCollisionMm3"] <= 0.01
        and checks["upperShellToRetainerPressedCollisionMm3"] <= 0.01
        and checks["plungerToRetainerCollisionMm3"] <= 0.01
        and 0.04 <= checks["buttonReleasedSwitchGapMm"] <= 0.10
        and 0 < checks["buttonPressedActuationMm"]
        <= checks["buttonMaximumSwitchTravelMm"]
        and abs(
            checks["buttonHardStopTravelMm"] - pressed_travel
        ) <= 0.01
        and checks["buttonRetainerRadialCaptureMm"] >= 0.30
        and checks["buttonRetainerAxialClearanceMm"] >= 0.04
        and checks["switchBodyToShellCollisionMm3"] <= 0.01
        and checks["switchBodyToCarrierCollisionMm3"] <= 0.01
        and abs(checks["usbRecessMm"] - 6.63) <= 0.10
        and checks["usbReachMarginMm"] >= 0
        and checks["usbPlugLateralClearanceMm"] >= min_process_clearance
        and checks["usbPlugVerticalClearanceMm"] >= min_process_clearance
        and checks["usbPlugSweepToShellCollisionMm3"] <= 0.01
        and checks["upperSplitFaceBelowY0Mm"] <= 0.01
        and checks["lowerSplitFaceAboveY0Mm"] <= 0.01
        and abs(
            checks["completeAssemblyOverallLengthMm"]
            - checks["targetAssemblyOverallLengthMm"]
        ) <= 0.01
        and checks["shellToHapticCollisionMm3"] <= 0.01
        and checks["pcbToHapticCollisionMm3"] <= 0.01
        and checks["batteryToHapticCollisionMm3"] <= 0.01
        and checks["hapticToAntennaAxialGapMm"] >= 5.0
        and checks["wireBendReserveMm"] >= 8.0
        and checks["minimumShellWallMm"] >= 2.0
        and checks["firstShellScrewToAntennaGapMm"] >= 8.0
    )

    physical_gates = {
        **PHYSICAL_GATES,
        "actualUsbCableParameterSelected": bool(plug["actualCableSelected"]),
    }
    all_physical_gates_closed = all(bool(value) for value in physical_gates.values())
    if not geometry_passed:
        status = "BLOCKED_GEOMETRY"
    elif all_physical_gates_closed:
        status = "VERIFIED_PRINT_CANDIDATE"
    else:
        status = "GEOMETRY_VERIFIED_PHYSICAL_GATES_OPEN"

    return {
        "schemaVersion": 3,
        "status": status,
        "geometryChecksPassed": geometry_passed,
        "physicalAcceptanceGates": {
            **physical_gates,
            "allClosed": all_physical_gates_closed,
        },
        "sourcePcb": {
            "path": repository_relative_posix(pcb_path),
            "sha256": sha256(pcb_path),
        },
        "pcbComponentEnvelopeEvidence": {
            "source": {
                "path": repository_relative_posix(factory_design_path),
                "sha256": sha256(factory_design_path),
            },
            "includedAssemblies": COMPONENT_ENVELOPE["includedAssemblies"],
            "planarClearancePerSideMm": float(
                COMPONENT_ENVELOPE["planarClearancePerSide"]
            ),
            "normalClearanceMm": float(COMPONENT_ENVELOPE["normalClearance"]),
            "bodies": [
                {key: value for key, value in record.items() if key != "shape"}
                for record in component_records
            ],
        },
        "fastenerToolSweepEvidence": {
            "counterboreRadiusMm": float(
                FASTENER_TOOL_SWEEP["counterboreRadius"]
            ),
            "minimumRadialClearanceMm": float(
                FASTENER_TOOL_SWEEP["minimumRadialClearance"]
            ),
            "sweeps": [
                {key: value for key, value in record.items() if key != "shape"}
                for record in tool_sweep_records
            ],
        },
        "checks": checks,
        "powerReservation": POWER,
        "assemblyNotes": [
            "Install the pull ribbon and removable nonconductive strap before the protected 1S LiPo.",
            "Route the three-wire lead through the open J2 channel; do not pinch the NTC wire.",
            "Use nylon M2 hardware at PCB H1/H2 and preferably at shell stations during RF validation.",
            "Keep the z=5..30 mm antenna volume free of battery, metal hardware, shielding and dense filler.",
            "Insert the plunger from outside, snap MW-P-006 into its stem groove, then verify free return and the 0.25 mm hard stop.",
            "The parameterized USB sweep is a geometry gauge only; an actual cable and first article remain mandatory physical gates.",
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
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    open_gates = [
        name
        for name, closed in validation["physicalAcceptanceGates"].items()
        if name != "allClosed" and not closed
    ]
    physical_gate_lines = "\n".join(f"- [ ] {name}" for name in open_gates)
    checks = validation["checks"]
    print_guide = f"""# Magic Wand printable enclosure Rev A0.2

Status: **{validation["status"]}**

Computational geometry gates: **{"PASS" if validation["geometryChecksPassed"] else "FAIL"}**

## Mandatory physical gates still open

{physical_gate_lines}

This package is not a fully verified print candidate until the actual cable,
slicer layer review and physical first article close the gates above.

## Print settings

- Shells: PETG/ASA/ABS/PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Carrier: PETG or PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Place each flush Y=0 shell split face on the bed.
- Carrier: print PCB rails upward. Rear cap and rod connector: print flange on the bed.
- A real slicer first-layer review remains mandatory.

## Geometry closure

- Frozen factory-design component envelopes: {checks["pcbComponentEnvelopeCount"]}/{checks["pcbComponentEnvelopeExpectedCount"]} bodies, shell/carrier collision {checks["shellToPcbComponentEnvelopeCollisionMm3"]} / {checks["carrierToPcbComponentEnvelopeCollisionMm3"]} mm^3.
- M2 driver access: {checks["fastenerToolSweepCount"]} sweeps, {checks["fastenerToolSweepRadialClearanceMm"]} mm radial clearance, shell/internal collision {checks["fastenerToolSweepToUpperShellCollisionMm3"]} / {checks["fastenerToolSweepToInternalReservedVolumeCollisionMm3"]} mm^3.
- Shell/carrier collision: {checks["upperShellToCarrierCollisionMm3"]} / {checks["lowerShellToCarrierCollisionMm3"]} mm^3.
- Carrier shell-boss relief radius: {checks["carrierBossReliefRadiusMm"]} mm.
- Battery side/axial clearance: {checks["batterySideClearancePerSideMm"]} / {checks["batteryAxialClearancePerEndMm"]} mm.
- Plunger released/pressed collision: {checks["upperShellToPlungerReleasedCollisionMm3"]} / {checks["upperShellToPlungerPressedCollisionMm3"]} mm^3.
- USB recess and gauge reach margin: {checks["usbRecessMm"]} / {checks["usbReachMarginMm"]} mm.
- Complete reserved assembly length: {checks["completeAssemblyOverallLengthMm"]} mm.

## Power reservation and service

- Maximum protected pack envelope: **11 x 6 x 42 mm** including insulation.
- Thread a removable 3 mm nonconductive strap through both floor slots.
- Install a pull ribbon beneath the cell and retain the modeled 8 mm lead-bend reserve.
- Confirm J2 BAT+/NTC/GND order and polarity before connection.

## Press-to-arm button

- Placeholder: SKQGAFE010, 5.2 x 5.2 x 1.5 mm, 0.25 mm maximum travel.
- Insert MW-P-005 from outside and snap MW-P-006 into its internal groove.
- Verify free return and the printed 0.25 mm hard stop.
- External head remains 4.6 mm diameter x 1.8 mm long.

## USB-C

- J1 and the visible +X opening remain at the frozen coordinates.
- The enlarged feature is an internal-only stepped counterbore.
- The parameterized plug sweep is a geometry gauge, not a selected cable.
- Select and physically fit-test the real cable before release.

## Wand rod

- Use an 8 mm solid GFRP rod cut to 195 mm.
- Insert to case z=116 mm; complete reserved overall length is 316 mm.
- Do not substitute conductive carbon-fiber or metal rod without renewed RF review.

## Assembly order

1. Deburr and dry-fit the shells, cap, connector, plunger and C-retainer.
2. Thread the battery strap and pull ribbon into the carrier.
3. Seat the protected cell and close the strap without crushing the pouch.
4. Route the J2 lead, fit the haptic actuator, and install the PCB on H1/H2.
5. Insert MW-P-005 and snap MW-P-006 into its groove.
6. Verify return and hard-stop travel before closing with M2x12 screws.
7. Perform USB, charging, button, haptic and RF tests before bonding the rod.
"""
    (OUTPUT_ROOT / "PRINT_AND_ASSEMBLY_GUIDE.md").write_text(
        print_guide, encoding="utf-8"
    )

    if validation["status"] == "VERIFIED_PRINT_CANDIDATE":
        status_class = "ok"
    elif validation["geometryChecksPassed"]:
        status_class = "warn"
    else:
        status_class = "bad"
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Magic Wand 3D Print Review</title><style>
body{{margin:0;font:15px/1.55 system-ui,'Microsoft YaHei',sans-serif;background:#eef2f7;color:#172033}}
main{{max-width:1180px;margin:auto;padding:28px}}h1{{margin:0 0 6px;font-size:32px}}.sub{{color:#536176;margin-bottom:22px}}
.status{{display:inline-block;padding:7px 12px;border-radius:999px;font-weight:700}}.ok{{background:#d9f7e5;color:#17623a}}.warn{{background:#fff1bf;color:#775400}}.bad{{background:#ffe1e1;color:#8c2020}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}}.card{{background:white;border-radius:16px;padding:18px;box-shadow:0 7px 30px #24344b18}}
img{{width:100%;border-radius:10px;background:#eef2f7}}table{{width:100%;border-collapse:collapse}}td{{padding:8px;border-bottom:1px solid #e6ebf1}}td:first-child{{color:#637086}}
code{{background:#edf1f5;padding:2px 5px;border-radius:5px}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>魔法杖 3D 打印装配审查</h1><div class="sub">Rev A0.2 · PCB / 元件包络 / 电池 / 天线 / 外壳跨域联调</div>
<span class="status {status_class}">{validation['status']}</span>
<div class="grid"><section class="card"><h2>装配视图</h2><img src="previews/assembly.png" alt="assembly"></section>
<section class="card"><h2>爆炸视图</h2><img src="previews/exploded.png" alt="exploded"></section>
<section class="card"><h2>电源仓剖开展示</h2><img src="previews/power-reservation.png" alt="power reservation"></section>
<section class="card"><h2>元件与工具服务空间</h2><img src="previews/service-clearance.png" alt="component and tool clearance"></section>
<section class="card"><h2>关键校核</h2><table>
<tr><td>电池最大包络</td><td>11 × 6 × 42 mm</td></tr>
<tr><td>电池径向最小余量</td><td>{validation['checks']['batteryRadialClearanceMm']} mm</td></tr>
<tr><td>电池距天线区</td><td>{validation['checks']['batteryToAntennaAxialGapMm']} mm</td></tr>
<tr><td>线束弯曲预留</td><td>{validation['checks']['wireBendReserveMm']} mm</td></tr>
<tr><td>Haptic envelope</td><td>10 mm dia x 3.4 mm; RF gap {validation['checks']['hapticToAntennaAxialGapMm']} mm</td></tr>
<tr><td>PCB 源哈希</td><td>{'一致' if validation['checks']['sourcePcbSha256Matches'] else '不一致'}</td></tr>
<tr><td>元件包络源哈希</td><td>{'一致' if validation['checks']['sourceFactoryDesignSha256Matches'] else '不一致'}</td></tr>
<tr><td>受控 SMT 包络</td><td>{validation['checks']['pcbComponentEnvelopeCount']} / {validation['checks']['pcbComponentEnvelopeExpectedCount']}；碰撞 {validation['checks']['shellToPcbComponentEnvelopeCollisionMm3']} mm³</td></tr>
<tr><td>M2 工具扫掠</td><td>{validation['checks']['fastenerToolSweepCount']} 处；径向余量 {validation['checks']['fastenerToolSweepRadialClearanceMm']} mm</td></tr>
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
        "plunger_retainer": "MW-P-006_plunger_c_retainer",
    }
    for key, stem in export_map.items():
        export_step(parts[key], STEP_ROOT / f"{stem}.step", timestamp=RELEASE_STAMP)
        export_stl(parts[key], STL_ROOT / f"{stem}.stl", tolerance=0.04, angular_tolerance=0.08)

    connector_installed = parts["rod_connector"].moved(Location((0, 0, 103.0)))
    printable_assembly = Compound(
        children=[
            parts["upper_shell"], parts["lower_shell"], parts["carrier"],
            parts["rear_cap"], connector_installed, parts["plunger"],
            parts["plunger_retainer"],
        ]
    )
    review_assembly = Compound(
        children=[
            printable_assembly, parts["pcb"], parts["battery"], parts["haptic"],
            parts["switch"], parts["rod"], parts["usb_plug_sweep"],
            parts["pcb_component_envelopes"], parts["fastener_tool_sweeps"],
        ]
    )
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
    if len(files) != 7:
        all_passed = False
    return {
        "passed": all_passed,
        "expectedStlCount": 7,
        "actualStlCount": len(files),
        "criteria": criteria,
        "files": files,
    }


def _write_deterministic_zip_entry(
    archive: zipfile.ZipFile,
    path: Path,
    arcname: str,
) -> None:
    info = zipfile.ZipInfo(
        arcname,
        date_time=(
            RELEASE_STAMP.year,
            RELEASE_STAMP.month,
            RELEASE_STAMP.day,
            RELEASE_STAMP.hour,
            RELEASE_STAMP.minute,
            RELEASE_STAMP.second,
        ),
    )
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100644 & 0xFFFF) << 16
    archive.writestr(
        info,
        path.read_bytes(),
        compress_type=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    )


def write_manifest_and_zip() -> None:
    files = []
    for path in sorted(OUTPUT_ROOT.rglob("*")):
        if path.is_file() and path.name not in {"release-manifest.json", "MW_PRINTABLE_WAND_REV_A0.zip"}:
            files.append({
                "path": path.relative_to(OUTPUT_ROOT).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            })
    test_path = ROOT / "test_printable_wand.py"
    factory_design_path, _ = load_frozen_factory_design()
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
        "sourceFactoryDesign": {
            "path": factory_design_path.name,
            "sha256": sha256(factory_design_path),
        },
        "sourceGenerator": {"path": Path(__file__).name, "sha256": sha256(Path(__file__))},
        "sourceTest": (
            {"path": test_path.name, "sha256": sha256(test_path)}
            if test_path.is_file()
            else None
        ),
        "files": files,
    }
    manifest_path = OUTPUT_ROOT / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate_packaged_json_portability([DESIGN_PATH, *sorted(OUTPUT_ROOT.rglob("*.json"))])

    zip_path = OUTPUT_ROOT / "MW_PRINTABLE_WAND_REV_A0.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        _write_deterministic_zip_entry(archive, DESIGN_PATH, "source/design-input.json")
        _write_deterministic_zip_entry(
            archive,
            factory_design_path,
            "source/wand-factory-design.json",
        )
        _write_deterministic_zip_entry(archive, Path(__file__), "source/build_printable_wand.py")
        if test_path.is_file():
            _write_deterministic_zip_entry(archive, test_path, "source/test_printable_wand.py")
        for path in sorted(OUTPUT_ROOT.rglob("*")):
            if path.is_file() and path != zip_path:
                _write_deterministic_zip_entry(
                    archive,
                    path,
                    path.relative_to(OUTPUT_ROOT).as_posix(),
                )
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
    factory_design_path, factory_design = load_frozen_factory_design()

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    for folder in (STEP_ROOT, STL_ROOT, PREVIEW_ROOT, REPORT_ROOT):
        folder.mkdir(parents=True, exist_ok=True)

    component_envelopes, component_envelope_records = make_pcb_component_envelopes(
        factory_design
    )
    fastener_tool_sweeps, fastener_tool_sweep_records = make_fastener_tool_sweeps()
    parts = {
        "upper_shell": make_upper_shell(),
        "lower_shell": make_lower_shell(),
        "carrier": make_carrier(),
        "rear_cap": make_rear_cap(),
        "rod_connector": make_rod_connector(),
        "plunger": make_button_plunger(),
        "plunger_retainer": make_button_retainer(),
        "pcb": make_pcb_placeholder(),
        "battery": make_battery_placeholder(),
        "haptic": make_haptic_placeholder(),
        "switch": make_switch_placeholder(),
        "rod": make_rod_placeholder(),
        "usb_plug_sweep": make_usb_plug_sweep(),
        "pcb_component_envelopes": component_envelopes,
        "pcb_component_envelope_records": component_envelope_records,
        "fastener_tool_sweeps": fastener_tool_sweeps,
        "fastener_tool_sweep_records": fastener_tool_sweep_records,
    }
    validation = build_validation(parts, pcb_path, factory_design_path)
    if not validation["geometryChecksPassed"]:
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
            (parts["pcb_component_envelopes"], "#66558b", 0.55),
            (parts["battery"], "#d14a46", 0.95),
            (parts["haptic"], "#9a4fa8", 0.98),
            (parts["plunger"], "#e24e42", 1.0),
            (parts["plunger_retainer"], "#f0b33b", 1.0),
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
            (parts["pcb_component_envelopes"].moved(Location((0, 8, 0))), "#66558b", 0.55),
            (parts["battery"], "#d14a46", 0.95),
            (parts["haptic"], "#9a4fa8", 0.98),
            (parts["rear_cap"], "#4e9a70", 0.95),
            (connector_installed, "#627ec7", 0.95),
            (parts["plunger"].moved(Location((0, 20, 0))), "#e24e42", 1.0),
            (parts["plunger_retainer"].moved(Location((0, 17, 0))), "#f0b33b", 1.0),
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
            (parts["pcb_component_envelopes"], "#66558b", 0.55),
            (parts["battery"], "#d14a46", 0.98),
            (parts["haptic"], "#9a4fa8", 0.98),
        ],
        elev=8,
        azim=18,
    )
    render_preview(
        PREVIEW_ROOT / "service-clearance.png",
        [
            (parts["upper_shell"], "#3a6fd4", 0.20),
            (parts["lower_shell"], "#244d9a", 0.20),
            (parts["pcb"], "#1f9d55", 0.65),
            (parts["pcb_component_envelopes"], "#66558b", 0.82),
            (parts["fastener_tool_sweeps"], "#eb8d1d", 0.95),
        ],
        elev=7,
        azim=30,
    )
    render_preview(
        PREVIEW_ROOT / "full-assembly.png",
        [
            (parts["upper_shell"], "#3a6fd4", 0.36),
            (parts["lower_shell"], "#244d9a", 0.70),
            (parts["rear_cap"], "#4e9a70", 0.95),
            (connector_installed, "#627ec7", 0.95),
            (parts["rod"], "#b7c0ce", 0.92),
        ],
        elev=12,
        azim=34,
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
