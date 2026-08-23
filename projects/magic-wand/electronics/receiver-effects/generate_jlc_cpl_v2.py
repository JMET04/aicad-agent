#!/usr/bin/env python3
"""Generate JLC CPL from Edge.Cuts centerline origin, not stroked bbox."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
AUDIT_REFS = ("U1", "U4", "J1", "R_SD")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edge_extents(board, pcbnew):
    xs, ys = [], []
    for item in board.GetDrawings():
        if item.GetLayer() != pcbnew.Edge_Cuts:
            continue
        for getter in ("GetStart", "GetEnd"):
            if hasattr(item, getter):
                point = getattr(item, getter)()
                xs.append(pcbnew.ToMM(point.x))
                ys.append(pcbnew.ToMM(point.y))
    if not xs:
        raise RuntimeError("no Edge.Cuts endpoints found")
    return min(xs), min(ys), max(xs), max(ys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--bom", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--audit", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    min_x, min_y, max_x, max_y = edge_extents(board, pcbnew)
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    with args.bom.open(newline="", encoding="utf-8-sig") as handle:
        bom_rows = list(csv.DictReader(handle))
    refs = sorted(row["Designator"] for row in bom_rows if row.get("DNP", "").upper() != "YES")
    rows, audit_points = [], {}
    for ref in refs:
        if ref not in footprints:
            raise RuntimeError(f"BOM reference absent from PCB: {ref}")
        fp = footprints[ref]
        position = fp.GetPosition()
        abs_x, abs_y = pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)
        rel_x, rel_y = abs_x - min_x, abs_y - min_y
        layer = "Bottom" if fp.GetLayer() == pcbnew.B_Cu else "Top"
        rows.append([ref, f"{rel_x:.3f}mm", f"{rel_y:.3f}mm",
                     f"{fp.GetOrientationDegrees():.1f}", layer])
        if ref in AUDIT_REFS:
            audit_points[ref] = {"absolute_mm": [round(abs_x, 4), round(abs_y, 4)],
                                 "origin_mm": [round(min_x, 4), round(min_y, 4)],
                                 "derived_cpl_mm": [round(rel_x, 4), round(rel_y, 4)],
                                 "rotation_deg": round(fp.GetOrientationDegrees(), 1), "layer": layer}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["Designator", "Mid X", "Mid Y", "Rotation", "Layer"])
        writer.writerows(rows)
    checks = {"edge_centerline_origin_used": True, "all_bom_refs_present": len(rows) == len(refs),
              "required_audit_refs_present": all(ref in audit_points for ref in AUDIT_REFS),
              "expected_mechanical_size_50_3_by_42_3":
                  abs((max_x - min_x) - 50.3) < 1e-6 and abs((max_y - min_y) - 42.3) < 1e-6}
    audit = {"schema": "magic-wand.receiver-effects.cpl-origin-audit.v2",
             "board": str(args.board), "board_sha256": sha256(args.board),
             "cpl": str(args.output), "cpl_sha256": sha256(args.output),
             "edge_centerline_origin_mm": [round(min_x, 4), round(min_y, 4)],
             "board_size_mm": [round(max_x - min_x, 4), round(max_y - min_y, 4)],
             "row_count": len(rows), "audit_points": audit_points, "checks": checks,
             "passed": all(checks.values())}
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "origin_mm": audit["edge_centerline_origin_mm"],
                      "board_size_mm": audit["board_size_mm"], "passed": audit["passed"]}))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
