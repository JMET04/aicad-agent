#!/usr/bin/env python3
"""Single-process board filter for locked-power signal routing."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
POWER_NETS = {"USB_VBUS_RAW", "USB_VBUS_5V", "3V3", "BUCK_SW", "SPK_PLUS", "SPK_MINUS"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--remove-zones", action="store_true")
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.input.resolve(strict=True)))
    tracks = list(board.GetTracks())
    zones = list(board.Zones())
    retained = [item for item in tracks if item.GetNetname() in POWER_NETS or
                (isinstance(item, pcbnew.PCB_VIA) and item.GetNetname() == "GND")]
    removed = [item for item in tracks if item not in retained]
    for item in retained:
        item.SetLocked(True)
    if args.remove_zones:
        for zone in zones:
            board.Remove(zone)
    for item in removed:
        board.Remove(item)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError(f"failed to save {args.output}")
    print(f"retained={len(retained)} removed={len(removed)} zones_removed={len(zones) if args.remove_zones else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
