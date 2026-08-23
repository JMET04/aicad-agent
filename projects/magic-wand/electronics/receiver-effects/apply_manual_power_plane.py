#!/usr/bin/env python3
"""Replace undersized power routes with deterministic planes and trunks."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from prepare_power_reroute_v2 import KICAD_BIN, KICAD_SITE, POWER_WIDTHS, update_project


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--output-board", type=Path, required=True)
    ap.add_argument("--output-project", type=Path, required=True)
    args = ap.parse_args()
    os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0, str(KICAD_SITE))
    import pcbnew  # type: ignore

    board = pcbnew.LoadBoard(str(args.board.resolve(strict=True)))
    net_codes = {name: board.FindNet(name).GetNetCode()
                 for name in set(POWER_WIDTHS) | {"GND"}}
    removed = 0
    for item in list(board.GetTracks()):
        if item.GetNetname() in POWER_WIDTHS:
            board.Remove(item)
            removed += 1

    def point(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))

    def add_track(net, layer, width, coordinates):
        code = net_codes[net]
        count = 0
        for start, end in zip(coordinates, coordinates[1:]):
            track = pcbnew.PCB_TRACK(board)
            track.SetNetCode(code)
            track.SetLayer(layer)
            track.SetWidth(pcbnew.FromMM(width))
            track.SetStart(point(*start))
            track.SetEnd(point(*end))
            board.Add(track)
            count += 1
        return count

    def add_via(net, coordinate, diameter=0.60):
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(point(*coordinate))
        via.SetWidth(pcbnew.FromMM(diameter))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNetCode(net_codes[net])
        board.Add(via)
        return 1

    track_count = 0
    via_count = 0

    # USB-C raw VBUS: fine pad exits to a wide, single B.Cu trunk.
    track_count += add_track("USB_VBUS_RAW", pcbnew.F_Cu, 0.25, [(130.0, 102.65), (129.2, 102.65)])
    track_count += add_track("USB_VBUS_RAW", pcbnew.F_Cu, 0.25, [(130.0, 107.35), (129.2, 107.35)])
    for coordinate in ((129.2, 102.65), (129.2, 107.35), (131.5, 97.5)):
        via_count += add_via("USB_VBUS_RAW", coordinate, 0.80)
    track_count += add_track("USB_VBUS_RAW", pcbnew.B_Cu, 0.80,
                             [(129.2, 107.35), (129.2, 102.65), (131.5, 100.35), (131.5, 97.5)])
    track_count += add_track("USB_VBUS_RAW", pcbnew.F_Cu, 0.80, [(131.5, 97.5), (132.3625, 97.5)])
    track_count += add_track("USB_VBUS_RAW", pcbnew.F_Cu, 0.80,
                             [(132.3625, 97.5), (133.52, 96.3425), (133.52, 93.5)])

    # Upper 5V source/buck cluster, then an In2 feeder into the lower 5V plane.
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.80,
                             [(136.6375, 97.5), (137.85, 97.5), (138.35, 97.0)])
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.80, [(136.6375, 97.5), (136.0, 99.5)])
    via_count += add_via("USB_VBUS_5V", (136.0, 99.5), 0.80)
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25,
                             [(138.55, 100.75), (137.75, 100.75)])
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25,
                             [(138.55, 101.25), (137.75, 101.25)])
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.80,
                             [(137.75, 100.75), (137.0, 101.0), (137.75, 101.25)])
    via_count += add_via("USB_VBUS_5V", (137.0, 101.0), 0.80)
    track_count += add_track("USB_VBUS_5V", pcbnew.In2_Cu, 0.80,
                             [(136.0, 99.5), (137.0, 101.0), (135.5, 105.0), (135.5, 106.5)])

    # NINA USB supply uses its own wide B.Cu branch to the lower 5V plane.
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25,
                             [(165.5, 90.75), (164.7, 90.75)])
    via_count += add_via("USB_VBUS_5V", (164.7, 90.75), 0.80)
    via_count += add_via("USB_VBUS_5V", (164.7119, 109.181), 0.80)
    track_count += add_track("USB_VBUS_5V", pcbnew.B_Cu, 0.80,
                             [(164.7, 90.75), (167.14, 93.19), (167.14, 106.7533), (164.7119, 109.181)])

    # Lower-plane load entries. Fine pads get one sub-1mm neck only.
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25, [(134.65, 107.0), (135.4, 107.0)])
    via_count += add_via("USB_VBUS_5V", (135.4, 107.0), 0.80)
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25,
                             [(159.75, 114.4375), (159.75, 115.17), (160.0, 115.17)])
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25,
                             [(160.25, 114.4375), (160.25, 115.17), (160.0, 115.17)])
    via_count += add_via("USB_VBUS_5V", (160.0, 115.17), 0.80)
    track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.25, [(159.02, 109.5), (158.32, 109.5)])
    via_count += add_via("USB_VBUS_5V", (158.32, 109.5), 0.80)
    for pad_xy, via_xy in (((162.55, 108.0), (162.55, 109.0)),
                           ((166.55, 108.0), (166.55, 109.0)),
                           ((134.5, 112.0), (135.5, 112.0))):
        track_count += add_track("USB_VBUS_5V", pcbnew.F_Cu, 0.80, [pad_xy, via_xy])
        via_count += add_via("USB_VBUS_5V", via_xy, 0.80)

    # 3V3: local drops into the upper In2 plane and a wide buck output trunk.
    track_count += add_track("3V3", pcbnew.F_Cu, 0.25, [(140.45, 101.25), (141.05, 101.25)])
    track_count += add_track("3V3", pcbnew.F_Cu, 0.50,
                             [(141.05, 101.25), (144.775, 101.0), (147.05, 101.0), (146.0, 102.0)])
    via_count += add_via("3V3", (146.0, 102.0), 0.60)
    drops_3v3 = (
        ((137.19, 104.0), (138.0, 104.0)),
        ((137.5, 112.0), (137.5, 104.8)),
        ((147.875, 89.1), (148.7, 89.1)),
        ((154.875, 89.825), (155.7, 89.825)),
        ((150.7625, 94.15), (150.0, 94.15)),
        ((151.19, 96.0), (151.19, 96.8)),
        ((160.52, 104.0), (159.8, 104.0)),
        ((163.55, 104.0), (162.7, 104.0)),
    )
    for pad_xy, via_xy in drops_3v3:
        track_count += add_track("3V3", pcbnew.F_Cu, 0.50, [pad_xy, via_xy])
        via_count += add_via("3V3", via_xy, 0.60)
    track_count += add_track("3V3", pcbnew.F_Cu, 0.50,
                             [(164.125, 97.3), (163.2, 97.8), (164.125, 98.3)])
    via_count += add_via("3V3", (163.2, 97.8), 0.60)

    # Buck switch node: only the U2 pad breakout is narrow.
    track_count += add_track("BUCK_SW", pcbnew.F_Cu, 0.25,
                             [(140.45, 100.75), (141.2, 100.75)])
    track_count += add_track("BUCK_SW", pcbnew.F_Cu, 0.50,
                             [(141.2, 100.75), (142.225, 101.0)])

    # BTL speaker outputs stay on F.Cu, with no vias or copper zones.
    track_count += add_track("SPK_MINUS", pcbnew.F_Cu, 0.25,
                             [(160.9375, 113.25), (161.3465, 113.25)])
    track_count += add_track("SPK_MINUS", pcbnew.F_Cu, 0.60,
                             [(161.3465, 113.25), (163.4163, 115.3198),
                              (163.4163, 117.5), (164.95, 117.5)])
    track_count += add_track("SPK_MINUS", pcbnew.F_Cu, 0.60,
                             [(163.4163, 117.5), (161.3, 120.0)])
    track_count += add_track("SPK_PLUS", pcbnew.F_Cu, 0.25,
                             [(160.9375, 113.75), (161.3, 114.1125)])
    track_count += add_track("SPK_PLUS", pcbnew.F_Cu, 0.60,
                             [(161.3, 114.1125), (161.3, 117.0), (160.2492, 118.0508),
                              (160.2492, 120.4589), (160.8583, 121.068),
                              (163.382, 121.068), (164.95, 119.5)])

    # Low-inductance GND returns around USB ESD, buck, amplifier and decoupling.
    ground_tracks = (
        ((132.35, 107.0), (131.35, 106.4)),
        ((132.35, 107.0), (131.35, 107.6)),
        ((158.0625, 113.25), (157.25, 113.25)),
        ((160.9375, 112.75), (161.75, 112.75)),
        ((159.25, 111.5625), (159.25, 110.65)),
        ((159.5, 113.0), (159.5, 113.0)),
        ((139.5, 101.0), (139.5, 101.0)),
        ((139.5, 101.0), (139.5, 103.0)),
        ((140.25, 97.0), (141.2, 97.0)),
        ((148.95, 101.0), (149.8, 101.0)),
        ((159.98, 109.5), (160.7, 109.5)),
        ((164.45, 108.0), (164.45, 109.0)),
        ((168.45, 108.0), (168.45, 109.0)),
    )
    for pad_xy, via_xy in ground_tracks:
        if pad_xy != via_xy:
            track_count += add_track("GND", pcbnew.F_Cu, 0.50, [pad_xy, via_xy])
        via_count += add_via("GND", via_xy, 0.60)

    args.output_board.parent.mkdir(parents=True, exist_ok=True)
    if not pcbnew.SaveBoard(str(args.output_board.resolve()), board):
        raise RuntimeError("failed to save manual power-plane candidate")
    update_project(args.project, args.output_project)
    print(f"removed={removed} added_tracks={track_count} added_vias={via_count} output={args.output_board}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
