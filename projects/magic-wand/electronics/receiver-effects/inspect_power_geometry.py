#!/usr/bin/env python3
"""Dump power pads, zones, and existing routing for deterministic repair."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
POWER_NETS = {"USB_VBUS_RAW", "USB_VBUS_5V", "3V3", "BUCK_SW", "SPK_PLUS", "SPK_MINUS", "GND"}


def xy(pcbnew, point):
    return [round(pcbnew.ToMM(point.x), 4), round(pcbnew.ToMM(point.y), 4)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() not in POWER_NETS:
                continue
            pads.append({
                "ref": fp.GetReference(),
                "pad": pad.GetNumber(),
                "net": pad.GetNetname(),
                "at_mm": xy(pcbnew, pad.GetPosition()),
                "size_mm": xy(pcbnew, pad.GetSize()),
                "layers": sorted(pcbnew.LayerName(layer) for layer in pad.GetLayerSet().Seq()),
            })

    tracks = []
    for item in board.GetTracks():
        if item.GetNetname() not in POWER_NETS:
            continue
        row = {"net": item.GetNetname(), "start_mm": xy(pcbnew, item.GetStart()),
               "end_mm": xy(pcbnew, item.GetEnd()), "layer": pcbnew.LayerName(item.GetLayer())}
        if isinstance(item, pcbnew.PCB_VIA):
            row.update({"kind": "via", "diameter_mm": round(pcbnew.ToMM(item.GetWidth(pcbnew.F_Cu)), 4),
                        "drill_mm": round(pcbnew.ToMM(item.GetDrillValue()), 4)})
        else:
            row.update({"kind": "track", "width_mm": round(pcbnew.ToMM(item.GetWidth()), 4),
                        "length_mm": round(pcbnew.ToMM(item.GetLength()), 4)})
        tracks.append(row)

    zones = []
    for zone in board.Zones():
        outline = zone.Outline()
        points = []
        for index in range(outline.TotalVertices()):
            points.append(xy(pcbnew, outline.CVertex(index)))
        zones.append({"net": zone.GetNetname(), "layer": pcbnew.LayerName(zone.GetLayer()),
                      "points_mm": points})

    payload = {"board": str(args.board), "pads": pads, "tracks": tracks, "zones": zones}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"pads={len(pads)} tracks_vias={len(tracks)} zones={len(zones)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
