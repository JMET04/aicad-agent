#!/usr/bin/env python3
"""Keep and lock factory power copper; remove only signal routing."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
POWER_NETS = {"USB_VBUS_RAW", "USB_VBUS_5V", "3V3", "BUCK_SW", "SPK_PLUS", "SPK_MINUS"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--route-board", type=Path, required=True)
    ap.add_argument("--route-project", type=Path, required=True)
    ap.add_argument("--base-board", type=Path, required=True)
    ap.add_argument("--base-project", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    def keep(item):
        return item.GetNetname() in POWER_NETS or (
            isinstance(item, pcbnew.PCB_VIA) and item.GetNetname() == "GND")

    def prepare(output: Path, remove_zones: bool):
        board = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
        tracks = list(board.GetTracks())
        zones = list(board.Zones())
        retained = [item for item in tracks if keep(item)]
        removed = [item for item in tracks if not keep(item)]
        for item in retained:
            item.SetLocked(True)
        if remove_zones:
            for zone in zones:
                board.Remove(zone)
        for item in removed:
            board.Remove(item)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not pcbnew.SaveBoard(str(output.resolve()), board):
            raise RuntimeError(f"failed to save {output}")
        return len(retained), len(removed), len(zones) if remove_zones else 0

    route_counts = prepare(args.route_board, True)
    base_counts = prepare(args.base_board, False)
    shutil.copyfile(args.project, args.route_project)
    shutil.copyfile(args.project, args.base_project)
    print(f"route_retained={route_counts[0]} route_removed={route_counts[1]} "
          f"route_zones_removed={route_counts[2]} base_retained={base_counts[0]} "
          f"base_removed={base_counts[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
