#!/usr/bin/env python3
"""Apply the reviewed, minimal post-router fixes to the v3 candidate.

The autorouter completed every ratsnest connection but placed two signal paths
too close to the top/right outline.  This script moves only those identified
vertices inward, ties the otherwise isolated 3V3 inner plane to an existing
3V3 track junction, and uses solid zone connections on the MAX98357A ground
pads.  It is idempotent and intentionally does not touch placement or nets.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"


def point(pcbnew, x_mm: float, y_mm: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.input.resolve(strict=True)))
    fixes = {
        # RESET_N: keep the NINA pad endpoint, pull the outward dogleg/via in.
        "2ee5a75c-a18d-403e-8587-69a6e25b78ff": ((172.7000, 95.3000), (172.7000, 88.6743)),
        "35ce1d51-848a-44c0-acc2-33a03e8d68f5": ((172.3750, 95.3000), (172.7000, 95.3000)),
        "9d2a6cfa-8c75-470f-9bad-655e08afeb8e": ((172.7000, 88.6743), (172.7000, 88.4981)),
        "5f2a7296-66cc-4adc-9450-763dbf582058": ((172.7000, 88.4981), (172.7000, 88.4981)),
        "3bd41400-ed87-40c1-bc8d-8c77463cc2b2": ((162.1421, 112.5686), (172.7000, 101.6852)),
        "3f0029b9-559c-46c5-8278-0d906c525be4": ((172.7000, 101.6852), (172.7000, 88.4981)),
        # TFT_DC: move the long top-edge channel from y=84.2781 to y=84.5000.
        "0eb06ca7-0de3-440f-b97b-2b1b1529be8c": ((167.7298, 84.5000), (145.7410, 84.5000)),
        "86596bd3-021e-430c-9dbe-64f4207b454b": ((145.7410, 84.5000), (141.6250, 88.3941)),
        "95f30e09-80a7-48c3-b7a2-d912daef6645": ((171.0000, 87.5483), (167.7298, 84.5000)),
    }

    seen: set[str] = set()
    for item in board.GetTracks():
        uid = item.m_Uuid.AsString()
        if uid not in fixes:
            continue
        start, end = fixes[uid]
        item.SetStart(point(pcbnew, *start))
        item.SetEnd(point(pcbnew, *end))
        seen.add(uid)
    missing = sorted(set(fixes) - seen)
    if missing:
        raise RuntimeError(f"expected router UUIDs missing: {missing}")

    # Tie In2.Cu 3V3 to the existing F.Cu 3V3 junction at this safe location.
    via_xy = point(pcbnew, 151.1900, 99.9420)
    has_plane_via = any(
        isinstance(item, pcbnew.PCB_VIA)
        and item.GetNetname() == "3V3"
        and item.GetPosition() == via_xy
        for item in board.GetTracks()
    )
    if not has_plane_via:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(via_xy)
        via.SetWidth(pcbnew.FromMM(0.60))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNetCode(board.FindNet("3V3").GetNetCode())
        board.Add(via)

    # The exposed/return pads need low-inductance ground, not thermal relief.
    amp = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U4")
    for pad in amp.Pads():
        if pad.GetNetname() == "GND":
            pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.output.resolve()), board):
        raise RuntimeError("failed to save finalized routed candidate")
    print(f"moved_router_items={len(seen)} added_3v3_plane_via={not has_plane_via} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
