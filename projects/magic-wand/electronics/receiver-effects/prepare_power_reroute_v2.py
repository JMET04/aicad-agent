#!/usr/bin/env python3
"""Prepare a constrained power reroute around accepted signal routing.

Signal routing is retained in the Specctra input. Contract-width power tracks
are removed, except for at most 0.80 mm of 0.25 mm fine-pitch breakout. Zones
are removed before track mutation to avoid KiCad SWIG ownership invalidation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"

POWER_WIDTHS = {
    "USB_VBUS_RAW": 0.80,
    "USB_VBUS_5V": 0.80,
    "SPK_PLUS": 0.60,
    "SPK_MINUS": 0.60,
    "3V3": 0.50,
    "BUCK_SW": 0.50,
}
FINE_REFS = {"J1", "U1", "U2", "U3", "U4"}
BREAKOUT_MM = 0.80


def clone_stub(pcbnew, board, item, pad_at_start: bool):
    start, end = item.GetStart(), item.GetEnd()
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy)
    limit = pcbnew.FromMM(BREAKOUT_MM)
    stub = pcbnew.PCB_TRACK(board)
    stub.SetLayer(item.GetLayer())
    stub.SetNetCode(item.GetNetCode())
    stub.SetWidth(pcbnew.FromMM(0.25))
    if length <= limit:
        stub.SetStart(start)
        stub.SetEnd(end)
    elif pad_at_start:
        ratio = limit / length
        stub.SetStart(start)
        stub.SetEnd(pcbnew.VECTOR2I(round(start.x + dx * ratio), round(start.y + dy * ratio)))
    else:
        ratio = limit / length
        stub.SetStart(end)
        stub.SetEnd(pcbnew.VECTOR2I(round(end.x - dx * ratio), round(end.y - dy * ratio)))
    return stub


def update_project(path_in: Path, path_out: Path) -> None:
    project = json.loads(path_in.read_text(encoding="utf-8"))
    classes = project["net_settings"]["classes"]
    template = next(item for item in classes if item["name"] == "Default")
    classes[:] = [item for item in classes if item["name"] not in
                  {"VBUS_800", "SPK_600", "PWR_500"}]
    for name, width, via_dia in (
        ("VBUS_800", 0.80, 0.80),
        ("SPK_600", 0.60, 0.70),
        ("PWR_500", 0.50, 0.60),
    ):
        item = dict(template)
        item.update({"name": name, "track_width": width,
                     "via_diameter": via_dia, "via_drill": 0.30,
                     "clearance": 0.15})
        classes.append(item)
    assignments = project["net_settings"]["netclass_assignments"]
    for net in ("USB_VBUS_RAW", "USB_VBUS_5V"):
        assignments[net] = "VBUS_800"
    for net in ("SPK_PLUS", "SPK_MINUS"):
        assignments[net] = "SPK_600"
    for net in ("3V3", "BUCK_SW"):
        assignments[net] = "PWR_500"
    project["board"]["design_settings"]["via_dimensions"] = [
        {"diameter": 0.60, "drill": 0.30},
        {"diameter": 0.70, "drill": 0.30},
        {"diameter": 0.80, "drill": 0.30},
    ]
    path_out.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--route-board", type=Path, required=True)
    ap.add_argument("--base-board", type=Path, required=True)
    ap.add_argument("--route-project", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    route = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    zone_count = len(list(route.Zones()))
    for zone in list(route.Zones()):
        route.Remove(zone)
    fine_pads = [pad for fp in route.GetFootprints() if fp.GetReference() in FINE_REFS
                 for pad in fp.Pads() if pad.GetNetname() in POWER_WIDTHS]
    stubs = []
    removed = 0
    for item in list(route.GetTracks()):
        if item.GetNetname() not in POWER_WIDTHS:
            continue
        if not isinstance(item, pcbnew.PCB_VIA):
            start_hits = [pad for pad in fine_pads if pad.GetNetname() == item.GetNetname()
                          and pad.HitTest(item.GetStart(), 0, item.GetLayer())]
            end_hits = [pad for pad in fine_pads if pad.GetNetname() == item.GetNetname()
                        and pad.HitTest(item.GetEnd(), 0, item.GetLayer())]
            if start_hits:
                stubs.append(clone_stub(pcbnew, route, item, True))
            if end_hits and not start_hits:
                stubs.append(clone_stub(pcbnew, route, item, False))
        route.Remove(item)
        removed += 1
    for stub in stubs:
        route.Add(stub)

    base = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    base_removed = len(list(base.GetTracks()))
    for item in list(base.GetTracks()):
        base.Remove(item)

    args.route_board.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.route_board.resolve()), route):
        raise RuntimeError("failed to save power-route board")
    if not pcbnew.SaveBoard(str(args.base_board.resolve()), base):
        raise RuntimeError("failed to save zone base board")
    update_project(args.project, args.route_project)
    print(f"power_items_removed={removed} breakout_stubs={len(stubs)} zones_removed={zone_count} "
          f"base_tracks_removed={base_removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
