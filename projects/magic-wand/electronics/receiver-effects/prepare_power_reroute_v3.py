#!/usr/bin/env python3
"""Cache KiCad objects before mutations, then prepare a power reroute."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from prepare_power_reroute_v2 import (
    FINE_REFS,
    KICAD_BIN,
    KICAD_SITE,
    POWER_WIDTHS,
    clone_stub,
    update_project,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--route-board", type=Path, required=True)
    ap.add_argument("--base-board", type=Path, required=True)
    ap.add_argument("--route-project", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    route = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    fine_pads = [pad for fp in route.GetFootprints() if fp.GetReference() in FINE_REFS
                 for pad in fp.Pads() if pad.GetNetname() in POWER_WIDTHS]
    all_tracks = list(route.GetTracks())
    all_zones = list(route.Zones())
    power_items = []
    stubs = []
    for item in all_tracks:
        if item.GetNetname() not in POWER_WIDTHS:
            continue
        power_items.append(item)
        if isinstance(item, pcbnew.PCB_VIA):
            continue
        start_hits = [pad for pad in fine_pads if pad.GetNetname() == item.GetNetname()
                      and pad.HitTest(item.GetStart(), 0, item.GetLayer())]
        end_hits = [pad for pad in fine_pads if pad.GetNetname() == item.GetNetname()
                    and pad.HitTest(item.GetEnd(), 0, item.GetLayer())]
        if start_hits:
            stubs.append(clone_stub(pcbnew, route, item, True))
        if end_hits and not start_hits:
            stubs.append(clone_stub(pcbnew, route, item, False))

    # No board queries after the first removal: KiCad 10's Windows SWIG wrapper
    # can invalidate later container traversals after BOARD.Remove().
    for zone in all_zones:
        route.Remove(zone)
    for item in power_items:
        route.Remove(item)
    for stub in stubs:
        route.Add(stub)

    base = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    base_tracks = list(base.GetTracks())
    for item in base_tracks:
        base.Remove(item)

    args.route_board.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.route_board.resolve()), route):
        raise RuntimeError("failed to save power-route board")
    if not pcbnew.SaveBoard(str(args.base_board.resolve()), base):
        raise RuntimeError("failed to save zone base board")
    update_project(args.project, args.route_project)
    print(f"power_items_removed={len(power_items)} breakout_stubs={len(stubs)} "
          f"zones_removed={len(all_zones)} base_tracks_removed={len(base_tracks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
