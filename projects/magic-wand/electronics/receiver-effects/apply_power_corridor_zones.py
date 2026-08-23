#!/usr/bin/env python3
"""Convert verified thin power topology into self-clearing copper corridors."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
ZONE_NETS = {"USB_VBUS_RAW": 0.80, "USB_VBUS_5V": 0.80, "3V3": 0.50}
TRACK_NETS = {"BUCK_SW": 0.50, "SPK_PLUS": 0.60, "SPK_MINUS": 0.60}
POWER_NETS = set(ZONE_NETS) | set(TRACK_NETS)


def corridor(start, end, width):
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return []
    radius = width / 2.0
    ux, uy = dx / length * radius, dy / length * radius
    nx, ny = -dy / length * radius, dx / length * radius
    return [(x1 - ux + nx, y1 - uy + ny),
            (x2 + ux + nx, y2 + uy + ny),
            (x2 + ux - nx, y2 + uy - ny),
            (x1 - ux - nx, y1 - uy - ny)]


def zone_text(net, layer, points, key):
    uid = hashlib.sha256(key.encode()).hexdigest()[:8]
    uuid = f"{uid}-0000-4000-8000-{uid}{uid[:4]}"
    pts = " ".join(f"(xy {x:.4f} {y:.4f})" for x, y in points)
    return (
        f'\t(zone\n\t\t(net "{net}")\n\t\t(layer "{layer}")\n'
        f'\t\t(uuid "{uuid}")\n\t\t(priority 10)\n\t\t(hatch edge 0.5)\n'
        '\t\t(connect_pads (clearance 0.2))\n\t\t(min_thickness 0.15)\n'
        '\t\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))\n'
        f'\t\t(polygon (pts {pts}))\n\t)\n')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.input.resolve(strict=True)))
    net_codes = {name: board.FindNet(name).GetNetCode() for name in POWER_NETS | {"GND"}}
    originals = []
    for item in list(board.GetTracks()):
        if item.GetNetname() not in POWER_NETS:
            continue
        if isinstance(item, pcbnew.PCB_VIA):
            originals.append({"kind": "via", "net": item.GetNetname(),
                              "at": (pcbnew.ToMM(item.GetPosition().x), pcbnew.ToMM(item.GetPosition().y)),
                              "diameter": pcbnew.ToMM(item.GetWidth(pcbnew.F_Cu)),
                              "drill": pcbnew.ToMM(item.GetDrillValue())})
        else:
            originals.append({"kind": "track", "net": item.GetNetname(),
                              "layer": pcbnew.LayerName(item.GetLayer()),
                              "start": (pcbnew.ToMM(item.GetStart().x), pcbnew.ToMM(item.GetStart().y)),
                              "end": (pcbnew.ToMM(item.GetEnd().x), pcbnew.ToMM(item.GetEnd().y))})
        board.Remove(item)

    def point(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))

    def add_track(net, layer, start, end, width):
        track = pcbnew.PCB_TRACK(board)
        track.SetNetCode(net_codes[net])
        track.SetLayer(layer)
        track.SetWidth(pcbnew.FromMM(width))
        track.SetStart(point(*start))
        track.SetEnd(point(*end))
        board.Add(track)

    def add_via(net, at, diameter=0.60):
        via = pcbnew.PCB_VIA(board)
        via.SetNetCode(net_codes[net])
        via.SetPosition(point(*at))
        via.SetWidth(pcbnew.FromMM(diameter))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        board.Add(via)

    zone_specs = []
    restored_vias = 0
    restored_tracks = 0
    for index, item in enumerate(originals):
        if item["kind"] == "via":
            add_via(item["net"], item["at"], max(0.60, item["diameter"]))
            restored_vias += 1
        elif item["net"] in ZONE_NETS:
            points = corridor(item["start"], item["end"], ZONE_NETS[item["net"]])
            if points:
                zone_specs.append((item["net"], item["layer"], points, f"corridor/{item['net']}/{index}"))
        else:
            if item["net"] == "BUCK_SW":
                continue
            width = TRACK_NETS[item["net"]]
            if item["net"] == "SPK_PLUS" and item["start"] == (160.9375, 113.75):
                width = 0.25
            if item["net"] == "SPK_MINUS" and item["start"] == (160.9375, 113.25):
                width = 0.25
            add_track(item["net"], getattr(pcbnew, item["layer"].replace(".", "_")),
                      item["start"], item["end"], width)
            restored_tracks += 1

    # Replace the long U2 switch-pad segment with one bounded neck and a 0.5mm trunk.
    add_track("BUCK_SW", pcbnew.F_Cu, (140.45, 100.75), (141.20, 100.75), 0.25)
    add_track("BUCK_SW", pcbnew.F_Cu, (141.20, 100.75), (142.225, 101.0), 0.50)

    # Legal inner-plane entries and reviewed local return locations.
    for at, diameter in (((136.0, 109.0), 0.60), ((160.0, 115.5), 0.80)):
        add_via("USB_VBUS_5V", at, diameter)
    for at in ((160.52, 99.9421), (150.5, 90.75), (137.25, 104.75)):
        add_via("3V3", at, 0.60)
    for at in ((132.75, 109.0), (157.5, 114.5), (161.0, 111.5),
               (139.5, 99.75), (140.25, 98.0), (148.95, 102.0)):
        add_via("GND", at, 0.60)

    # Short same-net copper corridors bind new entries to the preserved topology.
    for index, (net, layer, start, end, width) in enumerate((
        ("USB_VBUS_5V", "F.Cu", (136.0, 109.0), (134.65, 107.0), 0.80),
        ("USB_VBUS_5V", "F.Cu", (160.0, 115.5), (159.75, 114.9653), 0.80),
        ("3V3", "F.Cu", (160.52, 99.9421), (160.52, 99.9421), 0.50),
        ("3V3", "F.Cu", (150.5, 90.75), (149.6289, 90.8539), 0.50),
        ("3V3", "F.Cu", (137.25, 104.75), (137.7982, 104.6082), 0.50),
    )):
        points = corridor(start, end, width)
        if points:
            zone_specs.append((net, layer, points, f"entry/{net}/{index}"))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save zone corridor candidate")
    text = args.output.read_text(encoding="utf-8").rstrip()
    if not text.endswith(")"):
        raise RuntimeError("unexpected KiCad PCB ending")
    insert = "".join(zone_text(*spec) for spec in zone_specs)
    args.output.write_text(text[:-1] + insert + ")\n", encoding="utf-8", newline="\n")
    print(f"original_power_items={len(originals)} corridor_zones={len(zone_specs)} "
          f"restored_vias={restored_vias} restored_tracks={restored_tracks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
