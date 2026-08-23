#!/usr/bin/env python3
"""Machine-check receiver-effects current capacity and local return paths."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
TARGET_WIDTH_MM = {
    "USB_VBUS_RAW": 0.80,
    "USB_VBUS_5V": 0.80,
    "SPK_PLUS": 0.60,
    "SPK_MINUS": 0.60,
    "3V3": 0.50,
    "BUCK_SW": 0.50,
}
FINE_REFS = {"J1", "U1", "U2", "U3", "U4"}
MAX_NECK_MM = 1.00


def mm(pcbnew, value):
    return pcbnew.ToMM(value)


def distance_mm(pcbnew, a, b):
    return math.hypot(mm(pcbnew, a.x - b.x), mm(pcbnew, a.y - b.y))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    fine_pads = [pad for ref, fp in fps.items() if ref in FINE_REFS
                 for pad in fp.Pads() if pad.GetNetname() in TARGET_WIDTH_MM]
    failures = []
    nets = {}
    all_vias = []

    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA):
            all_vias.append(item)
            continue
        net = item.GetNetname()
        if net not in TARGET_WIDTH_MM:
            continue
        width = mm(pcbnew, item.GetWidth())
        length = mm(pcbnew, item.GetLength())
        row = nets.setdefault(net, {"target_width_mm": TARGET_WIDTH_MM[net],
                                   "segment_count": 0, "total_length_mm": 0.0,
                                   "wide_length_mm": 0.0, "neckdowns": []})
        row["segment_count"] += 1
        row["total_length_mm"] += length
        if width + 1e-6 >= TARGET_WIDTH_MM[net]:
            row["wide_length_mm"] += length
            continue
        hits = []
        for pad in fine_pads:
            if pad.GetNetname() != net:
                continue
            if pad.HitTest(item.GetStart(), 0, item.GetLayer()) or pad.HitTest(item.GetEnd(), 0, item.GetLayer()):
                hits.append(f"{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}")
        neck = {"width_mm": round(width, 4), "length_mm": round(length, 4),
                "pad_hits": sorted(set(hits)),
                "start_mm": [round(mm(pcbnew, item.GetStart().x), 4), round(mm(pcbnew, item.GetStart().y), 4)],
                "end_mm": [round(mm(pcbnew, item.GetEnd().x), 4), round(mm(pcbnew, item.GetEnd().y), 4)]}
        row["neckdowns"].append(neck)
        if length > MAX_NECK_MM + 1e-6:
            failures.append(f"{net}: neckdown {length:.3f}mm exceeds {MAX_NECK_MM:.2f}mm")
        if not hits:
            failures.append(f"{net}: narrow segment does not terminate at an allowed fine-pitch pad")

    for net, target in TARGET_WIDTH_MM.items():
        row = nets.setdefault(net, {"target_width_mm": target, "segment_count": 0,
                                   "total_length_mm": 0.0, "wide_length_mm": 0.0,
                                   "neckdowns": []})
        total = row["total_length_mm"]
        neck_total = sum(item["length_mm"] for item in row["neckdowns"])
        row["neckdown_total_mm"] = round(neck_total, 4)
        row["neckdown_count"] = len(row["neckdowns"])
        row["neckdown_max_mm"] = round(max((item["length_mm"] for item in row["neckdowns"]), default=0.0), 4)
        row["total_length_mm"] = round(total, 4)
        row["wide_length_mm"] = round(row["wide_length_mm"], 4)
        row["wide_ratio"] = round(row["wide_length_mm"] / total, 4) if total else 0.0
        minimum_ratio = 0.30 if net == "BUCK_SW" else 0.60
        if total <= 0:
            failures.append(f"{net}: no routed copper segments")
        elif row["wide_ratio"] + 1e-6 < minimum_ratio:
            failures.append(f"{net}: contract-width trunk ratio {row['wide_ratio']:.3f} below {minimum_ratio:.2f}")

    vias = []
    for via in all_vias:
        entry = {"net": via.GetNetname(),
                 "at_mm": [round(mm(pcbnew, via.GetPosition().x), 4), round(mm(pcbnew, via.GetPosition().y), 4)],
                 "diameter_mm": round(mm(pcbnew, via.GetWidth(pcbnew.F_Cu)), 4),
                 "drill_mm": round(mm(pcbnew, via.GetDrillValue()), 4)}
        vias.append(entry)
        if entry["drill_mm"] + 1e-6 < 0.30:
            failures.append(f"via {entry['net']} at {entry['at_mm']} drill below 0.30mm")

    plane_entries = {
        "USB_VBUS_5V_lower_In2": [v for v in vias if v["net"] == "USB_VBUS_5V" and 106.0 <= v["at_mm"][1] <= 125.7],
        "3V3_upper_In2": [v for v in vias if v["net"] == "3V3" and 84.3 <= v["at_mm"][1] <= 105.5],
    }
    for name, entries in plane_entries.items():
        if len(entries) < 2:
            failures.append(f"{name}: requires at least 2 plane-entry vias, found {len(entries)}")

    gnd_vias = [via for via in all_vias if via.GetNetname() == "GND"]
    return_checks = {}
    for ref, minimum_count in (("U3", 2), ("U4", 3), ("U2", 2), ("J1", 1)):
        center = fps[ref].GetPosition()
        distances = sorted(distance_mm(pcbnew, center, via.GetPosition()) for via in gnd_vias)
        within = [d for d in distances if d <= 3.0 + 1e-6]
        return_checks[ref] = {"minimum_distance_mm": round(distances[0], 4) if distances else None,
                              "gnd_vias_within_3mm": len(within), "required_within_3mm": minimum_count}
        if len(within) < minimum_count:
            failures.append(f"{ref}: needs {minimum_count} GND vias within 3mm, found {len(within)}")

    edges = board.GetBoardEdgesBoundingBox()
    payload = {
        "schema": "magic-wand.receiver-effects.power-return-audit.v1",
        "board": str(args.board),
        "board_size_mm": [round(mm(pcbnew, edges.GetWidth()), 4), round(mm(pcbnew, edges.GetHeight()), 4)],
        "copper_layers": board.GetCopperLayerCount(),
        "requirements": {"max_neckdown_mm": MAX_NECK_MM, "minimum_via_drill_mm": 0.30,
                         "minimum_trunk_ratio": 0.60, "buck_minimum_trunk_ratio": 0.30},
        "nets": nets,
        "via_count": len(vias),
        "gnd_via_count": len(gnd_vias),
        "plane_entries": plane_entries,
        "local_return_paths": return_checks,
        "failure_count": len(failures),
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": not failures, "failure_count": len(failures),
                      "gnd_via_count": len(gnd_vias),
                      "plane_entries": {key: len(value) for key, value in plane_entries.items()},
                      "output": str(args.output)}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
