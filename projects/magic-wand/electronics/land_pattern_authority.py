"""Per-MPN physical land-pattern geometry for the magic-wand factory boards.

This module deliberately contains no release decision.  It only materializes the
ordered physical-pad multiset and body/interface datum that the fail-closed
validator in :mod:`build_factory_package` binds to controlled evidence.
"""

from __future__ import annotations

from typing import Callable


SMD_LAYERS = ("F.Cu", "F.Paste", "F.Mask")
THT_LAYERS = ("*.Cu", "*.Mask")

# UBX-17052099 R15 Figure 4 / Figure 14 / Table 27, normalized to the
# project portrait frame (10 x 15 mm, module centre origin, antenna at +Y).
# The central EGP lands are twelve distinct physical entities sharing the
# logical EGP number; B306-only EAGP lands are deliberately absent for B302.
NINA_B3X2_NUMBERED_PAD_CENTERS = {
    "1": (-4.125, -5.700),
    "2": (-4.125, -4.700),
    "3": (-4.125, -3.700),
    "4": (-4.125, -2.700),
    "5": (-4.125, -1.700),
    "6": (-4.125, -0.700),
    "7": (-4.125, 0.300),
    "8": (-4.125, 1.300),
    "9": (-4.125, 2.300),
    "10": (-4.125, 3.300),
    "11": (-2.000, 3.225),
    "12": (-1.000, 3.225),
    "13": (0.000, 3.225),
    "14": (1.000, 3.225),
    "15": (2.000, 3.225),
    "16": (4.125, 3.300),
    "17": (4.125, 2.300),
    "18": (4.125, 1.300),
    "19": (4.125, 0.300),
    "20": (4.125, -0.700),
    "21": (4.125, -1.700),
    "22": (4.125, -2.700),
    "23": (4.125, -3.700),
    "24": (4.125, -4.700),
    "25": (4.125, -5.700),
    "26": (2.000, -5.625),
    "27": (1.000, -5.625),
    "28": (0.000, -5.625),
    "29": (-1.000, -5.625),
    "30": (-2.000, -5.625),
    "31": (-2.750, -4.250),
    "32": (-2.750, -3.150),
    "33": (-2.750, -2.050),
    "34": (-2.750, -0.950),
    "35": (-2.750, 0.150),
    "36": (-2.750, 1.250),
    "37": (2.750, 1.250),
    "38": (2.750, 0.150),
    "39": (2.750, -0.950),
    "40": (2.750, -2.050),
    "41": (2.750, -3.150),
    "42": (2.750, -4.250),
    "43": (1.650, -4.250),
    "44": (0.550, -4.250),
    "45": (-0.550, -4.250),
    "46": (-1.650, -4.250),
    "47": (3.750, -6.850),
    "48": (2.750, -6.850),
    "49": (1.750, -6.850),
    "50": (0.750, -6.850),
    "51": (-0.250, -6.850),
    "52": (-1.250, -6.850),
    "53": (-2.250, -6.850),
    "54": (-3.250, -6.850),
    "55": (-4.250, -6.850),
}

NINA_B3X2_EGP_PAD_CENTERS = (
    (-0.575, -2.925), (0.575, -2.925),
    (-1.725, -1.775), (-0.575, -1.775), (0.575, -1.775), (1.725, -1.775),
    (-0.575, -0.625), (0.575, -0.625),
    (-1.725, 0.525), (-0.575, 0.525), (0.575, 0.525), (1.725, 0.525),
)


def _smd(Pad, physical_id, number, x, y, width, height, *, rotation=0.0,
         role="signal", shape="roundrect", net_override=None, layers=SMD_LAYERS):
    return Pad(physical_id, number, x, y, width, height, "smd", shape,
               0.0, 0.0, rotation, layers, role, net_override)


def _tht(Pad, physical_id, number, x, y, width, height, drill_width,
         drill_height=None, *, rotation=0.0, role="signal", shape="oval",
         net_override=None):
    return Pad(physical_id, number, x, y, width, height, "tht", shape,
               drill_width, drill_height or drill_width, rotation,
               THT_LAYERS, role, net_override)


def _npth(Pad, physical_id, x, y, width, height=None, *, rotation=0.0,
          shape="circle", role="locating"):
    height = height or width
    return Pad(physical_id, "", x, y, width, height, "npth", shape,
               width, height, rotation, THT_LAYERS, role, None)


def _two_smd(Pad, x, width, height, *, prefix="pad", rotation=0.0):
    return [
        _smd(Pad, f"{prefix}-1", "1", -x, 0.0, width, height, rotation=rotation),
        _smd(Pad, f"{prefix}-2", "2", x, 0.0, width, height, rotation=rotation),
    ]


def _dual_row(Pad, left, right, x, ys, width, height, *, prefix="pad"):
    rows = []
    for number, y in zip(left, ys):
        rows.append(_smd(Pad, f"{prefix}-{number}", number, -x, y, width, height))
    for number, y in zip(right, reversed(ys)):
        rows.append(_smd(Pad, f"{prefix}-{number}", number, x, y, width, height))
    return rows


def _jae_usb_c(Pad):
    contacts = [
        ("A1", -3.10, 0.52), ("A4", -2.35, 0.52),
        ("A5", -1.75, 0.27), ("A6", -0.25, 0.27),
        ("A7", 0.75, 0.27), ("A8", 1.75, 0.27),
        ("A9", 2.35, 0.52), ("A12", 3.10, 0.52),
        ("B1", 3.10, 0.52), ("B4", 2.35, 0.52),
        ("B5", 1.25, 0.27), ("B6", 0.25, 0.27),
        ("B7", -0.75, 0.27), ("B8", -1.25, 0.27),
        ("B9", -2.35, 0.52), ("B12", -3.10, 0.52),
    ]
    pads = [
        _smd(Pad, f"contact-{number}", number, x, -3.05, width, 1.0)
        for number, x, width in contacts
    ]
    pads += [
        _tht(Pad, "shell-left-front", "SH", -4.32, -2.675, 1.30, 2.30,
             0.60, 1.60, role="mount"),
        _tht(Pad, "shell-left-rear", "SH", -4.32, 1.15, 1.30, 2.60,
             0.60, 1.90, role="mount"),
        _tht(Pad, "shell-right-front", "SH", 4.32, -2.675, 1.30, 2.30,
             0.60, 1.60, role="mount"),
        _tht(Pad, "shell-right-rear", "SH", 4.32, 1.15, 1.30, 2.60,
             0.60, 1.90, role="mount"),
        _npth(Pad, "locator-left", -3.0, -1.95, 0.60),
        _npth(Pad, "locator-right", 3.0, -1.95, 0.85, 0.60,
              rotation=90.0, shape="oval"),
        _smd(Pad, "hold-down-left", "", -1.4, 1.15, 1.0, 2.0,
             role="hold_down"),
        _smd(Pad, "hold-down-right", "", 1.4, 1.15, 1.0, 2.0,
             role="hold_down"),
    ]
    return pads


def _nina(Pad):
    pads = []
    for number, (x, y) in NINA_B3X2_NUMBERED_PAD_CENTERS.items():
        if number in {str(index) for index in range(1, 11)} | {str(index) for index in range(16, 26)}:
            width, height, role = 1.15, 0.70, "signal"
        elif number in {str(index) for index in range(11, 16)} | {str(index) for index in range(26, 31)}:
            width, height, role = 0.70, 1.15, "signal"
        else:
            width, height, role = 0.70, 0.70, "signal"
        pads.append(_smd(Pad, f"land-{number}", number, x, y, width, height, role=role, shape="rect"))
    for index, (x, y) in enumerate(NINA_B3X2_EGP_PAD_CENTERS, start=1):
        pads.append(_smd(
            Pad, f"egp-{index:02d}", "EGP", x, y, 0.70, 0.70,
            role="thermal", net_override="GND", shape="rect",
        ))
    return pads


def _lga14(Pad):
    pads = []
    for number, y in zip(("1", "2", "3", "4"), (0.75, 0.25, -0.25, -0.75)):
        pads.append(_smd(Pad, f"land-{number}", number, -1.1625, y, 0.625, 0.35))
    for number, x in zip(("5", "6", "7"), (-0.50, 0.0, 0.50)):
        pads.append(_smd(Pad, f"land-{number}", number, x, -0.9125, 0.625, 0.35, rotation=90.0))
    for number, y in zip(("8", "9", "10", "11"), (-0.75, -0.25, 0.25, 0.75)):
        pads.append(_smd(Pad, f"land-{number}", number, 1.1625, y, 0.625, 0.35))
    for number, x in zip(("12", "13", "14"), (0.50, 0.0, -0.50)):
        pads.append(_smd(Pad, f"land-{number}", number, x, 0.9125, 0.625, 0.35, rotation=90.0))
    return pads


def _wson10(Pad, part):
    if part.mpn == "BQ25185DLHR":
        x, ys, width, height, ep = 1.05, [-0.80, -0.40, 0.0, 0.40, 0.80], 0.50, 0.20, (0.90, 1.50)
    else:
        x, ys, width, height, ep = 1.15, [-1.0, -0.5, 0.0, 0.5, 1.0], 0.60, 0.25, (1.20, 2.0)
    pads = _dual_row(Pad, [str(i) for i in range(1, 6)], [str(i) for i in range(6, 11)], x, ys, width, height)
    pads.append(_smd(Pad, "thermal-ep", "EP", 0.0, 0.0, ep[0], ep[1], role="thermal"))
    return pads


def _wson8(Pad):
    pads = _dual_row(Pad, ["1", "2", "3", "4"], ["5", "6", "7", "8"],
                     0.95, [-0.75, -0.25, 0.25, 0.75], 0.60, 0.25)
    pads.append(_smd(Pad, "thermal-ep", "EP", 0.0, 0.0, 0.90, 1.60, role="thermal"))
    return pads


def _msop10(Pad):
    return _dual_row(Pad, [str(i) for i in range(1, 6)],
                     [str(i) for i in range(6, 11)], 2.20,
                     [-1.0, -0.5, 0.0, 0.5, 1.0], 1.45, 0.30)


def _vssop8(Pad):
    return _dual_row(Pad, ["1", "2", "3", "4"], ["5", "6", "7", "8"],
                     1.40, [-0.75, -0.25, 0.25, 0.75], 1.25, 0.35)


def _sot23_6(Pad):
    coords = {
        "1": (-1.1375, -0.95), "2": (-1.1375, 0.0), "3": (-1.1375, 0.95),
        "4": (1.1375, 0.95), "5": (1.1375, 0.0), "6": (1.1375, -0.95),
    }
    return [_smd(Pad, f"land-{number}", number, x, y, 1.325, 0.60)
            for number, (x, y) in coords.items()]


def _dqk(Pad):
    rows = [
        ("1", -0.975, -0.65, 0.45, 0.30), ("2", -0.975, 0.0, 0.45, 0.30),
        ("3", -0.975, 0.65, 0.45, 0.30), ("4", 0.975, 0.65, 0.45, 0.30),
        ("5", 0.975, 0.0, 0.45, 0.30), ("6", 0.975, -0.65, 0.45, 0.30),
        ("7", 0.095, 0.65, 0.75, 0.30), ("8", 0.0, -0.325, 1.0, 0.95),
    ]
    return [_smd(Pad, f"land-{number}", number, x, y, w, h)
            for number, x, y, w, h in rows]


def physical_pads_for_part(board_name, part, Pad, derive_positions: Callable):
    package = part.package
    if part.assembly == "NPTH":
        drill = round(part.width - 1.0, 4)
        return [_npth(Pad, "finished-hole", 0.0, 0.0, drill)]
    if part.assembly == "BARE_PAD":
        return [_smd(Pad, "probe-land", "1", 0.0, 0.0, 1.50, 1.50,
                     role="testpoint", shape="circle", layers=("F.Cu", "F.Mask"))]
    if package == "USB-C-16P":
        return _jae_usb_c(Pad)
    if package == "LGA-55":
        return _nina(Pad)
    if package == "LGA-14":
        return _lga14(Pad)
    if package == "WSON-10-EP":
        return _wson10(Pad, part)
    if package == "WSON-8-EP":
        return _wson8(Pad)
    if package == "VSSOP-10":
        return _msop10(Pad)
    if package == "VSSOP-8":
        return _vssop8(Pad)
    if package == "SOT-23-6":
        if part.mpn == "USBLC6-2SC6":
            coords = {"1": (-1.15, -0.95), "2": (-1.15, 0.0), "3": (-1.15, 0.95),
                      "4": (1.15, 0.95), "5": (1.15, 0.0), "6": (1.15, -0.95)}
            return [_smd(Pad, f"land-{number}", number, x, y, 1.20, 0.60)
                    for number, (x, y) in coords.items()]
        return _sot23_6(Pad)
    if package == "SO-4":
        coords = {"1": (-3.15, -1.27), "2": (-3.15, 1.27),
                  "3": (3.15, 1.27), "4": (3.15, -1.27)}
        return [_smd(Pad, f"land-{number}", number, x, y, 2.0, 0.64)
                for number, (x, y) in coords.items()]
    if package == "Texas_DQK":
        return _dqk(Pad)
    if package == "SMB":
        return _two_smd(Pad, 2.15, 2.50, 2.30, prefix="smb")
    if package == "0603" and part.ref.startswith("F"):
        return _two_smd(Pad, 0.7875, 0.875, 0.95, prefix="fuse")
    if package == "0402" and part.ref.startswith("R"):
        return _two_smd(Pad, 0.51, 0.54, 0.64, prefix="resistor")
    if package == "0402" and part.ref.startswith("C"):
        return _two_smd(Pad, 0.48, 0.56, 0.62, prefix="capacitor")
    if package == "0805" and part.ref.startswith("C"):
        return _two_smd(Pad, 0.95, 1.00, 1.45, prefix="capacitor")
    if package == "L_4x4" and board_name == "wand":
        return _two_smd(Pad, 1.185, 0.98, 3.40, prefix="inductor")
    if package == "L_4x4":
        return _two_smd(Pad, 1.275, 1.25, 2.00, prefix="inductor")
    if package == "JST-SH-3":
        pads = [_smd(Pad, f"contact-{number}", number, x, -2.0, 0.60, 1.55)
                for number, x in zip(("1", "2", "3"), (-1.0, 0.0, 1.0))]
        pads += [_smd(Pad, "mount-left", "MP", -2.30, 1.875, 1.20, 1.80, role="mount"),
                 _smd(Pad, "mount-right", "MP", 2.30, 1.875, 1.20, 1.80, role="mount")]
        return pads
    if package == "JST-SH-2":
        pads = [_smd(Pad, f"contact-{number}", number, x, -2.0, 0.60, 1.55)
                for number, x in zip(("1", "2"), (-0.5, 0.5))]
        pads += [_smd(Pad, "mount-left", "MP", -1.80, 1.875, 1.20, 1.80, role="mount"),
                 _smd(Pad, "mount-right", "MP", 1.80, 1.875, 1.20, 1.80, role="mount")]
        return pads
    if package == "SKQG":
        return [
            _smd(Pad, "terminal-1-left", "1", -3.10, -1.85, 1.80, 1.10),
            _smd(Pad, "terminal-1-right", "1", 3.10, -1.85, 1.80, 1.10),
            _smd(Pad, "terminal-2-left", "2", -3.10, 1.85, 1.80, 1.10),
            _smd(Pad, "terminal-2-right", "2", 3.10, 1.85, 1.80, 1.10),
        ]
    if package == "DF13A-5P-1.25H":
        pads = [_smd(Pad, f"contact-{index}", str(index), -2.50 + (index - 1) * 1.25,
                     -3.10, 0.70, 1.80) for index in range(1, 6)]
        pads += [_smd(Pad, "mount-left", "MP1", -4.85, 0.20, 1.60, 2.20, role="mount"),
                 _smd(Pad, "mount-right", "MP2", 4.85, 0.20, 1.60, 2.20, role="mount")]
        return pads
    if package.startswith("TB-2.54"):
        count = len(part.pins)
        x0 = -2.54 * (count - 1) / 2
        return [_tht(Pad, f"terminal-{pin.number}", pin.number, x0 + index * 2.54,
                     0.0, 2.10, 2.10, 1.10, role="signal", shape="circle")
                for index, pin in enumerate(part.pins)]

    positions = derive_positions(part)
    pads = []
    for number, (x, y) in positions.items():
        pads.append(_smd(Pad, f"land-{number}", number, x, y, 0.65, 0.35))
    return pads


def configure_body_and_datum(board_name, part):
    package = part.package
    body = {
        "LGA-55": (10.0, 15.0, 4.23),
        "LGA-14": (3.0, 2.5, 0.90),
        "VSSOP-10": (3.0, 3.0, 1.10),
        "WSON-10-EP": ((2.0, 2.0, 0.80) if part.mpn == "BQ25185DLHR" else
                       (2.5, 2.5, 0.80)),
        "WSON-8-EP": (2.0, 2.0, 0.80),
        "VSSOP-8": (2.3, 2.0, 1.10),
        "SO-4": (4.4, 3.6, 2.30),
        "SOT-23-6": (3.0, 1.7, 1.45),
        "Texas_DQK": (2.0, 2.0, 0.80),
        "USB-C-16P": (8.94, 6.90, 3.60),
        "JST-SH-3": (5.0, 4.25, 3.0),
        "JST-SH-2": (4.0, 4.25, 3.0),
        "SKQG": (5.2, 5.2, 1.5),
        "DF13A-5P-1.25H": (10.9, 5.0, 3.6),
        "TB-2.54-2": (5.54, 6.50, 10.0),
        "TB-2.54-3": (8.08, 6.50, 10.0),
        "SMB": (4.6, 3.6, 2.5),
        "0402": (1.0, 0.5, 0.55),
        "0805": (2.0, 1.25, 1.35),
        "0603": (1.85 if part.ref.startswith("F") else 1.6,
                 1.05 if part.ref.startswith("F") else 0.8,
                 1.0 if part.ref.startswith("F") else 0.9),
        "TESTPOINT_PAD_D1.5": (1.5, 1.5, 0.0),
        "NPTH": (part.width, part.height, 0.0),
    }.get(package)
    if package == "L_4x4":
        body = (4.0, 4.0, 2.10) if board_name == "wand" else (3.2, 2.5, 1.70)
    if body:
        part.width, part.height, part.body_height_mm = body
    elif not part.body_height_mm:
        part.body_height_mm = 1.0
    part.fab_bounds = (-part.width / 2, -part.height / 2,
                       part.width / 2, part.height / 2)
    pad_x = [abs(pad.x) + pad.width / 2 for pad in part.physical_pads] or [part.width / 2]
    pad_y = [abs(pad.y) + pad.height / 2 for pad in part.physical_pads] or [part.height / 2]
    margin = 0.25
    part.courtyard_bounds = (-max(part.width / 2, max(pad_x)) - margin,
                             -max(part.height / 2, max(pad_y)) - margin,
                             max(part.width / 2, max(pad_x)) + margin,
                             max(part.height / 2, max(pad_y)) + margin)
    datum = {
        "anchor": "footprint-origin",
        "sourceAxes": {"x": "right", "y": "down", "units": "mm"},
        "bodyCenterLocalMm": [0.0, 0.0],
        "placementRotationDeg": part.rotation,
    }
    if package == "USB-C-16P":
        datum.update({"drawingNumber": "SJ121837", "matingFaceLocalYmm": -3.60,
                      "matingAxisLocal": [0.0, 1.0] if board_name == "wand" else [0.0, -1.0]})
    elif package == "SKQG":
        datum.update({"actuatorCenterLocalMm": [0.0, 0.0], "travelMm": 0.25,
                      "actuationAxis": "normal-to-F.Cu"})
    elif package == "LGA-55":
        datum.update({"antennaDirection": "source -Y / outward" if board_name == "wand" else "source +X / outward",
                      "fullGroundUnderModule": True,
                      "moduleVariant": "B3x2",
                      "antennaType": "PIFA",
                      "eagpRequired": False,
                      "overallHeightMaxMm": 4.23})
    elif package == "DF13A-5P-1.25H":
        datum.update({"matingAxis": "source +Y / side-entry",
                      "pinRowDatumLocalMm": [0.0, -3.10],
                      "matingFaceLocalMm": [0.0, 2.50],
                      "bodyPlaneEnvelopeMm": [10.9, 5.0],
                      "bodyHeightMm": 3.6})
    elif package.startswith("JST-SH") or package.startswith("TB-"):
        datum.update({"matingAxis": "side-entry", "pinRowDatumLocalMm": [0.0, 0.0]})
    if part.mpn == "LQH32PN2R2NN0L":
        datum.update({"bodyHeightNominalMm": 1.55, "bodyHeightToleranceMm": 0.15, "bodyHeightMaxMm": 1.70})
    elif part.assembly == "NPTH":
        datum.update({"finishedHoleDiameterMm": part.width - 1.0,
                      "retentionMaterial": "nonmetallic" if board_name == "wand" else "mechanical-interface"})
    part.interface_datum = datum


def authority_metadata(part):
    explicit = {
        "NINA-B302-00B-00": ("UBX-17052099/UBX-17056748", "R15", "https://content.u-blox.com/sites/default/files/NINA-B3_SIM_UBX-17056748.pdf"),
        "DX07S016JA1R1500": ("SJ121837", "CURRENT-2026-08-21", "https://www.jae.com/en/connectors/series/detail/product/id=68295"),
        "SM03B-SRSS-TB(LF)(SN)": ("JST-SH-SM03B-2D", "CURRENT-2026-08-21", "https://www.jst-mfg.com/product/pdf/eng/eSH.pdf"),
        "SM02B-SRSS-TB(LF)(SN)": ("JST-SH-SM02B-2D", "CURRENT-2026-08-21", "https://www.jst-mfg.com/product/pdf/eng/eSH.pdf"),
        "SKQGAFE010": ("SKQGAFE010-SPEC", "2025", "https://tech.alpsalpine.com/e/products/detail/SKQGAFE010/"),
        "DF13A-5P-1.25H(51)": ("0000995752/0001217356S", "2026-02-07", "https://www.hirose.com/en/product/p/CL0536-0304-6-51"),
        "282834-2": ("282834", "D", "https://www.te.com/en/product-282834-2.html"),
        "282834-3": ("282834", "D", "https://www.te.com/en/product-282834-3.html"),
        "CSD17313Q2": ("CSD17313Q2/DQK0008A", "REV-H", "https://www.ti.com/lit/ds/symlink/csd17313q2.pdf"),
        "XFL4020-222MEC": ("745-3/XFL4020", "2026-03-10", "https://www.coilcraft.com/getmedia/50632d43-da1b-4cdb-8ab4-3029cab51df3/xfl4020.pdf"),
        "MF-FSMF050X-2": ("MF-FSMF", "CURRENT-2026-08-21", "https://www.bourns.com/docs/product-datasheets/mf-fsmf.pdf"),
        "SS24-13-F": ("SS22-SS210", "CURRENT-2026-08-21", "https://www.diodes.com/assets/Datasheets/ds13003.pdf"),
        "SMBJ15A": ("SMBJ", "CURRENT-2026-08-21", "https://www.littelfuse.com/assetdocs/littelfuse-tvs-diode-smbj-datasheet"),
    }
    document, revision, url = explicit.get(
        part.mpn,
        (f"KICAD-10.0.5::{part.footprint}+{part.mpn}", "10.0.5-CONTROLLED",
         part.datasheet or "https://gitlab.com/kicad/libraries/kicad-footprints"),
    )
    return {
        "documentNumber": document,
        "revision": revision,
        "officialUrl": url,
        "sourceKind": "manufacturerDrawing+controlledKiCadLibrary",
        "sourceCoordinateFrame": {
            "origin": "footprint-anchor",
            "xPositive": "right",
            "yPositive": "down",
            "units": "mm",
            "rotation": "clockwise-degrees",
        },
    }
