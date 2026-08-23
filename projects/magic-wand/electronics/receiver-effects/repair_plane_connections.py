#!/usr/bin/env python3
"""Connect the 3V3 inner plane and solid-connect MAX98357A ground pads."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.input.resolve(strict=True)))
    # Exact existing three-track junction; using the integer coordinate avoids
    # KiCad's track_not_centered_on_via diagnostic.
    via_xy = pcbnew.VECTOR2I(151_190_000, 99_942_100)
    has_via = any(
        isinstance(item, pcbnew.PCB_VIA)
        and item.GetNetname() == "3V3"
        and item.GetPosition() == via_xy
        for item in board.GetTracks()
    )
    if not has_via:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(via_xy)
        via.SetWidth(pcbnew.FromMM(0.60))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNetCode(board.FindNet("3V3").GetNetCode())
        board.Add(via)

    amp = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U4")
    solid_pads = 0
    for pad in amp.Pads():
        if pad.GetNetname() == "GND":
            pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
            solid_pads += 1

    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save plane-repair candidate")
    print(f"added_3v3_via={not has_via} u4_solid_ground_pads={solid_pads} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
