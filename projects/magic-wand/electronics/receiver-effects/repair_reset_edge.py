#!/usr/bin/env python3
"""Move only the RESET_N edge dogleg inward while preserving connectivity."""

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
    p = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))
    fixes = {
        "35ce1d51-848a-44c0-acc2-33a03e8d68f5": (p(172.3750, 95.3000), p(173.1000, 95.3000)),
        "2ee5a75c-a18d-403e-8587-69a6e25b78ff": (p(173.1000, 95.3000), p(173.1000, 87.5000)),
        "9d2a6cfa-8c75-470f-9bad-655e08afeb8e": (p(173.1000, 87.5000), p(172.9000, 87.5000)),
        "5f2a7296-66cc-4adc-9450-763dbf582058": (p(172.9000, 87.5000), p(172.9000, 87.5000)),
        "3f0029b9-559c-46c5-8278-0d906c525be4": (p(173.0255, 101.6852), p(172.9000, 87.5000)),
    }
    seen = set()
    for item in board.GetTracks():
        uid = item.m_Uuid.AsString()
        if uid in fixes:
            item.SetStart(fixes[uid][0])
            item.SetEnd(fixes[uid][1])
            seen.add(uid)
    if seen != set(fixes):
        raise RuntimeError(f"RESET_N router UUID mismatch: {sorted(set(fixes)-seen)}")
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save RESET_N repair candidate")
    print(f"reset_items_moved={len(seen)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
