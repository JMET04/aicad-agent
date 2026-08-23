"""Topology-preserving KiCad schematic/PCB parity alignment for receiver-effects."""

from __future__ import annotations

import re
from pathlib import Path

import pcbnew


def align_root_labels(schematic_path: Path) -> int:
    """Make root-sheet net names global so KiCad does not prefix them with '/'."""
    text = schematic_path.read_text(encoding="utf-8")
    text, count = re.subn(
        r'^  \(label ("[^"\r\n]+") ',
        r'  (global_label \1 (shape bidirectional) ',
        text,
        flags=re.MULTILINE,
    )
    if count == 0:
        raise RuntimeError("no root-sheet labels converted")
    schematic_path.write_text(text, encoding="utf-8", newline="\n")
    return count


def set_board_fields(board: pcbnew.BOARD, parts: list) -> int:
    """Mirror controlled assembly metadata into every PCB footprint."""
    by_ref = {part.ref: part for part in parts}
    count = 0
    for footprint in board.GetFootprints():
        part = by_ref.get(footprint.GetReference())
        if part is None:
            continue
        values = {
            "LCSC": part.lcsc,
            "BOM Comments": part.notes,
            "Datasheet": part.datasheet,
        }
        for field_name, value in values.items():
            footprint.SetField(field_name, value)
            field = footprint.GetField(field_name)
            field.SetVisible(False)
            field.SetLayer(pcbnew.F_Fab)
            field.SetPosition(footprint.GetPosition())
        count += 1
    if count != len(parts):
        raise RuntimeError(f"expected {len(parts)} footprint field sets, wrote {count}")
    return count

