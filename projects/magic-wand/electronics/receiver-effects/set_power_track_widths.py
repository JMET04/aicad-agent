#!/usr/bin/env python3
"""Set receiver-effects power/audio copper to the electrical width contract."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"

TARGET_MM = {
    "USB_VBUS_RAW": 0.80,
    "USB_VBUS_5V": 0.80,
    "SPK_PLUS": 0.60,
    "SPK_MINUS": 0.60,
    "3V3": 0.50,
    "BUCK_SW": 0.50,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.input.resolve(strict=True)))
    counts = {net: 0 for net in TARGET_MM}
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA):
            continue
        net = item.GetNetname()
        if net in TARGET_MM:
            item.SetWidth(pcbnew.FromMM(TARGET_MM[net]))
            counts[net] += 1
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save power-width candidate")
    print(" ".join(f"{net}={counts[net]}x{TARGET_MM[net]:.2f}mm" for net in TARGET_MM))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
