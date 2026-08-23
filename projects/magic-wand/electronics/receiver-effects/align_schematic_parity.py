#!/usr/bin/env python3
"""Align root-sheet label scope and LCSC fields for KiCad parity checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board-in", type=Path, required=True)
    ap.add_argument("--board-out", type=Path, required=True)
    ap.add_argument("--sch-in", type=Path, required=True)
    ap.add_argument("--sch-out", type=Path, required=True)
    ap.add_argument("--design", type=Path, required=True)
    args = ap.parse_args()

    design = json.loads(args.design.read_text(encoding="utf-8"))
    lcsc_by_ref = {part["ref"]: part.get("lcsc", "") for part in design["components"]}
    notes_by_ref = {part["ref"]: part.get("notes", "") for part in design["components"]}
    datasheet_by_ref = {part["ref"]: part.get("datasheet", "") for part in design["components"]}

    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.board_in.resolve(strict=True)))
    fields = 0
    for footprint in board.GetFootprints():
        ref = footprint.GetReference()
        if ref in lcsc_by_ref:
            footprint.SetField("LCSC", lcsc_by_ref[ref])
            footprint.SetField("BOM Comments", notes_by_ref[ref])
            footprint.SetField("Datasheet", datasheet_by_ref[ref])
            for field_name in ("LCSC", "BOM Comments", "Datasheet"):
                field = footprint.GetField(field_name)
                field.SetVisible(False)
                field.SetLayer(pcbnew.F_Fab)
                field.SetPosition(footprint.GetPosition())
            fields += 1
    if fields != len(lcsc_by_ref):
        raise RuntimeError(f"expected {len(lcsc_by_ref)} LCSC fields, wrote {fields}")
    if not pcbnew.SaveBoard(str(args.board_out.resolve()), board):
        raise RuntimeError("failed to save parity-aligned board")

    schematic = args.sch_in.read_text(encoding="utf-8")
    schematic, labels = re.subn(
        r'^  \(label ("[^"\r\n]+") ',
        r'  (global_label \1 (shape bidirectional) ',
        schematic,
        flags=re.MULTILINE,
    )
    if labels == 0:
        raise RuntimeError("no root-sheet labels converted")
    args.sch_out.write_text(schematic, encoding="utf-8", newline="\n")
    print(f"global_labels={labels} lcsc_fields={fields} board={args.board_out} sch={args.sch_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
