#!/usr/bin/env python3
"""Remove generated copper routes before an authoritative freerouting pass."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.input.resolve(strict=True)))
    tracks = list(board.GetTracks())
    for item in tracks:
        board.Remove(item)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save unrouted board")
    print(f"removed_tracks_and_vias={len(tracks)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
