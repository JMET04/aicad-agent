#!/usr/bin/env python3
"""Generate the single clean receiver-effects A1 relayout candidate.

This deliberately emits only the reviewed power/return skeleton.  Signal
routing is a separate, one-shot stage after native KiCad DRC proves that this
skeleton has no copper shorts or clearance errors.  Coordinates are board
local; factory_emit centres the board on the KiCad A4 worksheet.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ELECTRONICS = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(ELECTRONICS) not in sys.path:
    sys.path.insert(0, str(ELECTRONICS))

import pcbnew

from build_factory_package import absolute_pads
from factory_emit import write_bom_cpl, write_pcb, write_project, write_schematic
from generate_receiver_effects import (
    assign_3v3_power_flag,
    make_board,
    normalize_project_vias,
)
from receiver_effects_parity import align_root_labels, set_board_fields
from receiver_effects_relayout_routes import audio_group, display_spi_group, rgb_group, usb_data_group


OUT = HERE / "verification" / "relayout-a1"


PLACEMENTS: dict[str, tuple[float, float, float | None]] = {
    # External interfaces and the radio module.
    "J1": (3.675, 28.00, 270.0),
    "J2": (25.00, 3.25, 180.0),
    "J3": (54.70, 37.00, 90.0),
    "U1": (54.75, 11.00, 0.0),
    # USB protection and the compact RAW -> buck power corridor.
    "U3": (12.00, 28.00, 0.0),
    "F1": (15.00, 36.00, 0.0),
    "U2": (20.00, 36.00, 0.0),
    "L1": (23.80, 36.00, 0.0),
    "C_USB_RAW": (10.50, 35.50, 0.0),
    "C_BUCK_IN": (19.00, 32.50, 0.0),
    "C_BUCK_OUT": (27.80, 36.00, 0.0),
    "R_PG": (25.50, 31.50, 0.0),
    # Display/backlight and discrete RGB status indicator.
    "Q1": (35.50, 7.50, 0.0),
    "R_BL_SER": (33.00, 10.00, 0.0),
    "R_BL_PU": (35.50, 10.00, 0.0),
    "D1": (57.50, 22.50, 0.0),
    "R_LED_R": (55.00, 20.50, 0.0),
    "R_LED_G": (55.00, 22.00, 0.0),
    "R_LED_B": (55.00, 23.50, 0.0),
    # NINA decoupling.
    "C_NINA_HF": (49.00, 20.00, 0.0),
    "C_NINA_BULK": (52.00, 20.50, 0.0),
    # Audio island and its local control/decoupling.
    "U4": (44.00, 36.00, 0.0),
    "R_SD": (39.00, 31.50, 0.0),
    "R_SD_PD": (36.00, 34.00, 180.0),
    "R_GAIN": (39.00, 34.70, 180.0),
    "C_AUDIO_HF": (42.00, 40.50, 0.0),
    "C_AUDIO_10U": (44.50, 42.50, 0.0),
    "C_AUDIO_BULK": (48.00, 44.00, 0.0),
    # USB configuration parts remain close to the connector.
    "R_CC1": (9.50, 23.00, 0.0),
    "R_CC2": (9.50, 33.00, 0.0),
    "R_SH": (12.00, 32.00, 0.0),
    # Test access.  SWD is the guaranteed wired programming path.
    "TP1": (8.00, 43.00, 0.0),
    "TP2": (11.00, 20.00, 0.0),
    "TP3": (14.00, 43.00, 0.0),
    "TP4": (17.00, 46.00, 0.0),
    "TP5": (20.00, 46.00, 0.0),
    "TP6": (23.00, 46.00, 0.0),
    "TP7": (31.00, 13.00, 0.0),
    "TP8": (35.00, 28.00, 0.0),
    "TP9": (52.00, 45.00, 0.0),
    "TP10": (52.00, 29.00, 0.0),
    # Non-plated mechanical holes.
    "H1": (3.00, 3.00, 0.0),
    "H2": (39.00, 3.00, 0.0),
    "H3": (3.00, 47.00, 0.0),
    "H4": (57.00, 47.00, 0.0),
}


def seg(net: str, layer: str, start: tuple[float, float], end: tuple[float, float], width: float) -> dict:
    return {"net": net, "layer": layer, "start": list(start), "end": list(end), "width": width}


def via(net: str, x: float, y: float, size: float = 0.60) -> dict:
    return {"net": net, "x": x, "y": y, "size": size, "drill": 0.30}


def relayout_board():
    board = make_board()
    board.title = "Magic Wand Receiver Effects A1"
    board.width = 60.0
    board.height = 50.0
    by_ref = {part.ref: part for part in board.parts}
    if set(by_ref) != set(PLACEMENTS):
        missing = sorted(set(by_ref) - set(PLACEMENTS))
        extra = sorted(set(PLACEMENTS) - set(by_ref))
        raise RuntimeError(f"placement map mismatch: missing={missing}, extra={extra}")
    for ref, (x, y, rotation) in PLACEMENTS.items():
        part = by_ref[ref]
        part.x, part.y = x, y
        if rotation is not None:
            part.rotation = rotation
    # Exact LCSC matches verified against the stated MPN.  L1 and C_USB_RAW
    # deliberately remain unresolved and therefore keep the PCBA gate open.
    for ref, lcsc in {
        "C_AUDIO_10U": "C77073", "C_BUCK_IN": "C77073",
        "C_NINA_BULK": "C77073", "C_AUDIO_BULK": "C441864",
        "C_BUCK_OUT": "C77071",
    }.items():
        by_ref[ref].lcsc = lcsc
    board.plane_requirements = [
        {"name": "CONTINUOUS_GROUND", "net": "GND", "layers": ["In1.Cu"], "fullGround": True},
        {"name": "SPLIT_POWER_PLANE", "nets": ["3V3", "USB_VBUS_5V"], "layers": ["In2.Cu"],
         "split": {"3V3_y_mm": [0.30, 24.75], "USB_VBUS_5V_y_mm": [25.25, 49.70]}},
        {"name": "NINA_FULL_GROUND_UNDER_MODULE", "ref": "U1", "net": "GND", "layers": ["In1.Cu"],
         "polygon": [[49.75, 3.50], [59.75, 3.50], [59.75, 18.50], [49.75, 18.50]],
         "fullGround": True, "viaStitchingRequired": True},
    ]
    board.mechanical_keepouts = [{
        "name": "NINA_ANTENNA_PROJECTION_OUTSIDE_BOARD",
        "polygon": [[59.75, 3.50], [70.00, 3.50], [70.00, 18.50], [59.75, 18.50]],
        "rule": "No enclosure metal, speaker magnet, wiring, or display cable in antenna projection",
    }]
    return board


def power_skeleton() -> tuple[list[dict], list[dict]]:
    s: list[dict] = []
    v: list[dict] = []

    # USB-C VBUS pads need bounded 0.25 mm escapes.  Both enter a 0.8 mm B.Cu
    # trunk, then return to F.Cu immediately before the PTC input pad.
    for y in (25.60, 30.40):
        s.append(seg("USB_VBUS_RAW", "F.Cu", (7.355, y), (8.30, y), 0.25))
        v.append(via("USB_VBUS_RAW", 8.30, y))
    s += [
        # Upper and lower VBUS contacts route around, rather than across, the
        # interleaved USB2 data escape corridor. Both branches stay 0.8 mm.
        seg("USB_VBUS_RAW", "B.Cu", (8.30, 25.60), (10.20, 25.60), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (10.20, 25.60), (10.20, 22.30), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (10.20, 22.30), (13.00, 22.30), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (13.00, 22.30), (13.00, 33.00), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (13.00, 33.00), (11.80, 36.00), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (8.30, 30.40), (10.00, 30.40), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (10.00, 30.40), (10.00, 33.00), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (10.00, 33.00), (9.00, 34.00), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (9.00, 34.00), (11.80, 36.00), 0.80),
        seg("USB_VBUS_RAW", "F.Cu", (11.80, 36.00), (12.8625, 36.00), 0.80),
    ]
    v.append(via("USB_VBUS_RAW", 11.80, 36.00))

    # PTC output to buck VIN.  Only the two WSON fan-outs are narrow, each
    # shorter than 1 mm; the common trunk remains 0.8 mm.
    s += [
        seg("USB_VBUS_5V", "F.Cu", (17.1375, 36.00), (18.15, 36.00), 0.80),
        seg("USB_VBUS_5V", "F.Cu", (18.15, 36.00), (19.05, 35.75), 0.25),
        seg("USB_VBUS_5V", "F.Cu", (18.15, 36.00), (19.05, 36.25), 0.25),
        seg("USB_VBUS_5V", "F.Cu", (17.40, 36.00), (17.40, 38.00), 0.80),
    ]
    v.append(via("USB_VBUS_5V", 17.40, 38.00, 0.70))

    # USB ESD reference supply gets a direct, short entry into the 5 V plane.
    s.append(seg("USB_VBUS_5V", "F.Cu", (13.15, 28.00), (14.20, 28.00), 0.80))
    v.append(via("USB_VBUS_5V", 14.20, 28.00, 0.70))

    # Buck switch node is compact and all-front-layer.  VOS uses a short
    # Kelvin-style escape before joining the 3V3 output trunk.
    s += [
        seg("BUCK_SW", "F.Cu", (20.95, 35.75), (21.70, 35.75), 0.25),
        seg("BUCK_SW", "F.Cu", (21.70, 35.75), (22.525, 36.00), 0.50),
        seg("3V3", "F.Cu", (25.075, 36.00), (25.20, 24.00), 0.50),
    ]
    v.append(via("3V3", 25.20, 24.00, 0.70))

    # Display and NINA 3V3 plane entries.
    s += [
        seg("3V3", "F.Cu", (29.375, 5.10), (29.375, 7.00), 0.50),
        seg("3V3", "F.Cu", (50.625, 13.30), (49.60, 13.30), 0.50),
        seg("3V3", "F.Cu", (50.625, 14.30), (49.60, 14.30), 0.50),
        seg("3V3", "F.Cu", (49.60, 13.30), (49.60, 14.30), 0.50),
    ]
    v += [via("3V3", 29.375, 7.00), via("3V3", 49.60, 13.80, 0.70)]

    # NINA VBUS uses the proven top escape geometry, but the narrow portion is
    # now <=1 mm.  A dedicated 0.8 mm B.Cu feeder reaches the lower 5V plane.
    s += [
        seg("USB_VBUS_5V", "F.Cu", (52.00, 6.75), (51.90, 5.80), 0.25),
        seg("USB_VBUS_5V", "B.Cu", (51.90, 5.80), (51.90, 26.50), 0.80),
    ]
    v += [via("USB_VBUS_5V", 51.90, 5.80), via("USB_VBUS_5V", 51.90, 26.50, 0.70)]

    # MAX98357A VDD fan-out and a local power-plane entry.  Each 0.25 mm neck
    # is under 1 mm; the common segment is 0.8 mm.
    s += [
        seg("USB_VBUS_5V", "F.Cu", (44.25, 37.4375), (44.40, 38.25), 0.25),
        seg("USB_VBUS_5V", "F.Cu", (44.75, 37.4375), (45.20, 38.25), 0.25),
    ]
    v += [via("USB_VBUS_5V", 44.40, 38.25), via("USB_VBUS_5V", 45.20, 38.25)]

    # Speaker pair: bounded pad necks fan apart before the 0.6 mm trunks.
    s += [
        seg("SPK_PLUS", "F.Cu", (45.4375, 36.75), (46.0375, 37.55), 0.25),
        seg("SPK_PLUS", "F.Cu", (46.0375, 37.55), (48.00, 38.00), 0.60),
        seg("SPK_PLUS", "F.Cu", (48.00, 38.00), (51.85, 38.00), 0.60),
        seg("SPK_PLUS", "F.Cu", (48.00, 38.00), (52.00, 45.00), 0.60),
        seg("SPK_MINUS", "F.Cu", (45.4375, 36.25), (46.3875, 36.25), 0.25),
        seg("SPK_MINUS", "F.Cu", (46.3875, 36.25), (48.00, 36.00), 0.60),
        seg("SPK_MINUS", "F.Cu", (48.00, 36.00), (51.85, 36.00), 0.60),
        seg("SPK_MINUS", "F.Cu", (48.00, 36.00), (52.00, 29.00), 0.60),
    ]

    # Close every load-bearing 3V3 branch before signal routing.  U2 pad 6 is
    # the Kelvin VOS sense pin: its 0.20 mm B.Cu branch carries no load current.
    s += [
        seg("3V3", "F.Cu", (25.075, 36.00), (26.85, 36.00), 0.50),
        seg("3V3", "F.Cu", (20.95, 36.25), (21.56, 36.25), 0.15),
        seg("3V3", "F.Cu", (21.56, 36.25), (21.56, 37.60), 0.15),
        seg("3V3", "B.Cu", (21.56, 37.60), (26.00, 37.60), 0.20),
        seg("3V3", "F.Cu", (26.00, 37.60), (26.00, 36.00), 0.20),
        seg("3V3", "F.Cu", (11.00, 20.00), (12.00, 20.00), 0.50),
        seg("3V3", "F.Cu", (34.5625, 8.45), (33.00, 8.45), 0.50),
        seg("3V3", "F.Cu", (34.99, 10.00), (34.99, 11.50), 0.50),
        seg("3V3", "F.Cu", (57.075, 23.225), (56.40, 24.10), 0.50),
        seg("3V3", "F.Cu", (48.52, 20.00), (47.50, 21.50), 0.50),
        seg("3V3", "F.Cu", (51.05, 20.50), (50.50, 21.50), 0.50),
        seg("3V3", "F.Cu", (50.50, 21.50), (48.00, 22.50), 0.50),
    ]
    v += [
        via("3V3", 21.56, 37.60), via("3V3", 26.00, 37.60),
        via("3V3", 12.00, 20.00), via("3V3", 33.00, 8.45),
        via("3V3", 34.99, 11.50), via("3V3", 56.40, 24.10),
        via("3V3", 47.50, 21.50), via("3V3", 48.00, 22.50),
    ]

    # Local 5V plane entries close the input and amplifier decoupling loops;
    # TP1 lands directly in the 5V half of In2.
    s += [
        seg("USB_VBUS_5V", "F.Cu", (8.00, 43.00), (9.50, 43.00), 0.80),
        seg("USB_VBUS_5V", "F.Cu", (18.05, 32.50), (17.00, 32.50), 0.80),
        seg("USB_VBUS_5V", "F.Cu", (41.52, 40.50), (40.50, 40.50), 0.80),
        seg("USB_VBUS_5V", "F.Cu", (43.55, 42.50), (42.00, 42.50), 0.80),
        seg("USB_VBUS_5V", "F.Cu", (47.05, 44.00), (45.80, 44.00), 0.80),
    ]
    v += [
        via("USB_VBUS_5V", 9.50, 43.00, 0.70),
        via("USB_VBUS_5V", 17.00, 32.50, 0.70),
        via("USB_VBUS_5V", 40.50, 40.50, 0.70),
        via("USB_VBUS_5V", 42.00, 42.50, 0.70),
        via("USB_VBUS_5V", 45.80, 44.00, 0.70),
    ]

    # RAW input capacitor joins the existing B.Cu trunk without passing its
    # adjacent ground pad.  TP9/TP10 are placed directly on the SPK trunks.
    s += [
        seg("USB_VBUS_RAW", "F.Cu", (10.02, 35.50), (9.10, 35.50), 0.80),
        seg("USB_VBUS_RAW", "B.Cu", (9.10, 35.50), (9.00, 34.00), 0.80),
    ]
    v.append(via("USB_VBUS_RAW", 9.10, 35.50))

    # Tie the otherwise isolated U1 pad-26 F.Cu ground island straight into
    # the continuous In1 reference plane.  This is a GND-only stitch beneath
    # the B302 module, consistent with the SIM R15 full-ground requirement.
    s.append(seg("GND", "F.Cu", (56.75, 5.375), (57.75, 5.375), 0.50))
    v.append(via("GND", 57.75, 5.375))

    # Dense local return stitching.  No via is placed inside a WSON/TQFN EP.
    for x, y in [
        (12.00, 30.50),                        # U3 ESD clamp return, 2.75 mm from pad 2
        (21.00, 32.50), (29.00, 38.00),       # buck input/output grounds
        (19.50, 38.00), (21.50, 33.50),       # U2 local return, both <3 mm
        (12.00, 25.50),                        # second U3 clamp return, <3 mm
        (8.50, 24.00),                         # J1 top GND-contact return, 1.31 mm
        (42.00, 38.00), (44.00, 33.00), (46.00, 34.20),  # U4 EP/pad return
        (53.20, 19.00),                        # NINA local return
        (52.80, 3.20),                         # U1 pads 30/53 F.Cu island to In1; clear of SPI lanes/paste pads
        (29.40, 7.80),                        # display connector return
        (15.00, 24.00), (30.00, 24.00), (40.00, 24.00),  # plane/route return spine
        (15.00, 40.00), (30.00, 40.00), (40.00, 45.00),
    ]:
        v.append(via("GND", x, y))

    return s, v


def add_surface_and_split_zones(path: Path, board, net_ids: dict[str, int]) -> None:
    text = path.read_text(encoding="utf-8")
    ox = (297.0 - board.width) / 2.0
    oy = (210.0 - board.height) / 2.0
    marker = f'  (zone (net {net_ids["3V3"]}) (net_name "3V3") (layer "In2.Cu")'
    start = text.index(marker)
    next_section = text.index("  (gr_line", start)
    text = text[:start] + text[next_section:]

    def zone(name: str, layer: str, points: list[tuple[float, float]], suffix: str) -> str:
        import hashlib
        uid0 = hashlib.sha256(f"receiver-effects-a1/{suffix}".encode()).hexdigest()[:8]
        uuid_text = f"{uid0}-0000-4000-8000-{uid0}{uid0[:4]}"
        pts = " ".join(f"(xy {ox + x:.3f} {oy + y:.3f})" for x, y in points)
        return (
            f'  (zone (net {net_ids[name]}) (net_name "{name}") (layer "{layer}") (uuid {uuid_text})\n'
            "    (hatch edge 0.5) (connect_pads (clearance 0.20)) (min_thickness 0.15)\n"
            "    (fill yes (thermal_gap 0.30) (thermal_bridge_width 0.30))\n"
            f"    (polygon (pts {pts})))\n"
        )

    full = [(0.30, 0.30), (board.width - 0.30, 0.30),
            (board.width - 0.30, board.height - 0.30), (0.30, board.height - 0.30)]
    insert = zone("GND", "F.Cu", full, "gnd-f")
    insert += zone("GND", "B.Cu", full, "gnd-b")
    insert += zone("3V3", "In2.Cu", [(0.30, 0.30), (board.width - 0.30, 0.30),
                                      (board.width - 0.30, 24.75), (0.30, 24.75)], "3v3-in2")
    insert += zone("USB_VBUS_5V", "In2.Cu", [(0.30, 25.25), (board.width - 0.30, 25.25),
                                              (board.width - 0.30, board.height - 0.30),
                                              (0.30, board.height - 0.30)], "5v-in2")
    path.write_text(text[:-2] + insert + ")\n", encoding="utf-8", newline="\n")


def set_project_rules(project_path: Path) -> None:
    project = json.loads(project_path.read_text(encoding="utf-8"))
    classes = {row["name"]: row for row in project["net_settings"]["classes"]}
    # These are routing defaults; bounded pad neck-downs are checked separately.
    for name, width, clearance in [
        ("Default", 0.20, 0.20), ("POWER", 0.50, 0.20),
        ("LOAD_1A", 0.80, 0.20), ("USB2_90R", 0.20, 0.20),
    ]:
        classes[name]["track_width"] = width
        classes[name]["clearance"] = clearance
        classes[name]["via_diameter"] = 0.70 if name == "LOAD_1A" else 0.60
        classes[name]["via_drill"] = 0.30
    assignments = project["net_settings"]["netclass_assignments"]
    assignments.update({
        "USB_VBUS_RAW": "LOAD_1A", "USB_VBUS_5V": "LOAD_1A",
        "3V3": "POWER", "BUCK_SW": "POWER", "GND": "POWER",
        "SPK_PLUS": "POWER", "SPK_MINUS": "POWER",
    })
    project["board"]["design_settings"]["rules"]["min_clearance"] = 0.20
    project["board"]["design_settings"]["rules"]["min_via_diameter"] = 0.60
    project["text_variables"]["REVISION"] = "A1"
    project["text_variables"]["PROJECT_STATUS"] = "RELAYOUT_POWER_SKELETON_ONLY"
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8", newline="\n")
    # GCT USB4105 Rev B4 fixes its two NPTH locators 0.1885 mm from the
    # duplicated GND contact lands. Keep the 0.20 mm board rule everywhere
    # else and bound this official same-footprint exception to J1 only.
    dru_path = project_path.with_suffix(".kicad_dru")
    dru_text = dru_path.read_text(encoding="utf-8")
    if 'rule "GCT USB4105 official locator clearance"' not in dru_text:
        dru_text += (
            '\n(rule "GCT USB4105 official locator clearance"\n'
            '  (condition "A.Reference == \'J1\' && B.Reference == \'J1\'")\n'
            '  (constraint hole_clearance (min 0.18mm)))\n'
        )
        dru_path.write_text(dru_text, encoding="utf-8", newline="\n")


def lock_and_fill(path: Path, model) -> None:
    board = pcbnew.LoadBoard(str(path))
    set_board_fields(board, model.parts)
    for item in board.GetTracks():
        item.SetLocked(True)
    for zone in board.Zones():
        if zone.GetNetname() == "GND":
            zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetLocked(True)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=("power", "usb", "spi", "audio", "rgb"), default="power")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    board = relayout_board()
    pads = absolute_pads(board, require_controlled=False)
    segments, vias = power_skeleton()
    power_segment_count, power_via_count = len(segments), len(vias)
    if args.stage in ("usb", "spi", "audio", "rgb"):
        signal_segments, signal_vias = usb_data_group()
        segments.extend(signal_segments)
        vias.extend(signal_vias)
    if args.stage in ("spi", "audio", "rgb"):
        signal_segments, signal_vias = display_spi_group()
        segments.extend(signal_segments)
        vias.extend(signal_vias)
    if args.stage in ("audio", "rgb"):
        signal_segments, signal_vias = audio_group()
        segments.extend(signal_segments)
        vias.extend(signal_vias)
    if args.stage == "rgb":
        signal_segments, signal_vias = rgb_group()
        segments.extend(signal_segments)
        vias.extend(signal_vias)
    project = write_project(board, OUT)
    normalize_project_vias(project)
    set_project_rules(project)
    schematic = write_schematic(board, OUT)
    assign_3v3_power_flag(schematic)
    global_labels = align_root_labels(schematic)
    pcb = write_pcb(board, OUT, pads, segments, vias)
    net_names = sorted({p["net"] for p in pads if p.get("net") and p["net"] != "NC"})
    add_surface_and_split_zones(pcb, board, {name: i + 1 for i, name in enumerate(net_names)})
    write_bom_cpl(board, OUT)
    lock_and_fill(pcb, board)
    manifest = {
        "schema": "magic_wand_receiver_effects_clean_relayout_v1",
        "status": f"{args.stage.upper()}_STAGE_NOT_FABRICATION_RELEASED",
        "revision": "A1",
        "dimensions_mm": [board.width, board.height],
        "layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        "components": len(board.parts), "pads": len(pads),
        "power_segments": power_segment_count, "power_and_return_vias": power_via_count,
        "signal_segments": len(segments) - power_segment_count,
        "signal_vias": len(vias) - power_via_count,
        "power_nets_locked": True,
        "global_labels_aligned": global_labels,
        "next_gate": "native KiCad DRC: zero geometry violations before adding the next signal group",
        "usb_data_status": "UNVERIFIED_USB_FS_HIL_OPEN",
        "fabrication_authorized": False,
    }
    (OUT / "relayout-a1-stage.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**manifest, "pcb": str(pcb), "schematic": str(schematic)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
