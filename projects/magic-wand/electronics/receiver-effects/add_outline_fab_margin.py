#!/usr/bin/env python3
"""Add 0.30 mm bare-board margin at the routed top and right edges.

The NINA perimeter pads leave no legal channel for a 0.20 mm trace between
0.15 mm pad clearance and the original 0.30 mm copper-to-edge rule.  Rather
than reduce a manufacturing rule or route beneath the radio module, enlarge
the 50.0 x 42.0 mm outline to 50.3 x 42.3 mm on only those two sides.
"""

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
    mm = pcbnew.FromMM
    old_left, old_top, old_right, old_bottom = map(mm, (123.5, 84.0, 173.5, 126.0))
    new_top, new_right = mm(83.7), mm(173.8)
    changed = 0
    for item in board.GetDrawings():
        if item.GetLayer() != pcbnew.Edge_Cuts or not isinstance(item, pcbnew.PCB_SHAPE):
            continue
        start, end = item.GetStart(), item.GetEnd()
        if start.y == old_top and end.y == old_top:
            item.SetStart(pcbnew.VECTOR2I(old_left, new_top))
            item.SetEnd(pcbnew.VECTOR2I(new_right, new_top))
            changed += 1
        elif start.x == old_right and end.x == old_right:
            item.SetStart(pcbnew.VECTOR2I(new_right, new_top))
            item.SetEnd(pcbnew.VECTOR2I(new_right, old_bottom))
            changed += 1
        elif start.y == old_bottom and end.y == old_bottom:
            item.SetStart(pcbnew.VECTOR2I(new_right, old_bottom))
            item.SetEnd(pcbnew.VECTOR2I(old_left, old_bottom))
            changed += 1
        elif start.x == old_left and end.x == old_left:
            item.SetStart(pcbnew.VECTOR2I(old_left, old_bottom))
            item.SetEnd(pcbnew.VECTOR2I(old_left, new_top))
            changed += 1
    if changed != 4:
        raise RuntimeError(f"expected four rectangular Edge.Cuts segments, changed={changed}")
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save outline-margin candidate")
    print(f"edge_segments_changed={changed} outline_mm=50.3x42.3 output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
