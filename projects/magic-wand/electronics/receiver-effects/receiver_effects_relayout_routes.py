"""Reviewed, deterministic signal groups for the 60 x 50 mm A1 relayout.

All coordinates are board-local.  Each group is added only after the previous
group has passed native KiCad DRC with zero geometry violations.
"""

from __future__ import annotations


def _seg(net: str, layer: str, start: tuple[float, float], end: tuple[float, float], width: float = 0.20) -> dict:
    return {"net": net, "layer": layer, "start": list(start), "end": list(end), "width": width}


def _via(net: str, x: float, y: float) -> dict:
    return {"net": net, "x": x, "y": y, "size": 0.60, "drill": 0.30}


def usb_data_group() -> tuple[list[dict], list[dict]]:
    """USB-C duplicate-pad escape, ESD pass-through, and NINA USB pads.

    This is USB Full Speed prototype geometry, not an impedance claim.  The
    RAW pair fans around the fixed low-inductance U3 GND via.  The protected
    pair stays paired on B.Cu and changes layers symmetrically outside U1.
    """
    s: list[dict] = []
    v: list[dict] = []

    # The GCT Type-C A/B data pads are interleaved. A6 is the main D+ path;
    # B6 uses one B.Cu crossover before rejoining immediately ahead of U3.
    s += [
        _seg("USB_DP_RAW", "F.Cu", (7.355, 27.75), (8.10, 27.75)),
        _seg("USB_DP_RAW", "F.Cu", (8.10, 27.75), (8.75, 27.10)),
        _seg("USB_DP_RAW", "F.Cu", (8.75, 27.10), (9.55, 27.10)),
        _seg("USB_DP_RAW", "F.Cu", (9.55, 27.10), (10.85, 27.05)),
        _seg("USB_DP_RAW", "F.Cu", (7.355, 28.75), (8.70, 28.75)),
        _seg("USB_DP_RAW", "B.Cu", (8.70, 28.75), (8.90, 28.00)),
        _seg("USB_DP_RAW", "B.Cu", (8.90, 28.00), (9.30, 27.45)),
        _seg("USB_DP_RAW", "F.Cu", (9.30, 27.45), (9.55, 27.10)),
    ]
    v += [_via("USB_DP_RAW", 8.70, 28.75), _via("USB_DP_RAW", 9.30, 27.45)]

    # D- joins outside the contact lands, changes layer before crossing the
    # remaining contact row, and returns to F.Cu only beside U3 pad 3.
    s += [
        _seg("USB_DM_RAW", "F.Cu", (7.355, 27.25), (5.80, 27.25)),
        _seg("USB_DM_RAW", "F.Cu", (7.355, 28.25), (5.80, 28.25)),
        _seg("USB_DM_RAW", "F.Cu", (5.80, 27.25), (5.80, 28.25)),
        _seg("USB_DM_RAW", "B.Cu", (5.80, 28.25), (6.20, 29.50)),
        _seg("USB_DM_RAW", "B.Cu", (6.20, 29.50), (9.20, 29.50)),
        _seg("USB_DM_RAW", "B.Cu", (9.20, 29.50), (9.60, 28.90)),
        _seg("USB_DM_RAW", "F.Cu", (9.60, 28.90), (10.85, 28.95)),
    ]
    v += [_via("USB_DM_RAW", 5.80, 28.25), _via("USB_DM_RAW", 9.60, 28.90)]

    # CC pull-downs stay on F.Cu and route outside the two VBUS entry vias.
    s += [
        _seg("USB_CC1", "F.Cu", (7.355, 26.75), (8.00, 26.75), 0.15),
        _seg("USB_CC1", "F.Cu", (8.00, 26.75), (8.25, 26.50), 0.15),
        _seg("USB_CC1", "F.Cu", (8.25, 26.50), (9.20, 26.50), 0.15),
        _seg("USB_CC1", "F.Cu", (9.20, 26.50), (9.20, 23.00), 0.15),
        _seg("USB_CC1", "F.Cu", (9.20, 23.00), (8.99, 23.00), 0.15),
        _seg("USB_CC2", "F.Cu", (7.355, 29.75), (9.20, 29.75), 0.15),
        _seg("USB_CC2", "F.Cu", (9.20, 29.75), (9.20, 31.20), 0.15),
        _seg("USB_CC2", "F.Cu", (9.20, 31.20), (8.99, 33.00), 0.15),
        # Shield ring is deliberately separate from GND until R_SH.
        _seg("USB_SHIELD", "B.Cu", (2.60, 23.68), (6.78, 23.68), 0.50),
        _seg("USB_SHIELD", "B.Cu", (2.60, 23.68), (2.60, 32.32), 0.50),
        _seg("USB_SHIELD", "B.Cu", (2.60, 32.32), (6.78, 32.32), 0.50),
        _seg("USB_SHIELD", "F.Cu", (6.78, 32.32), (7.00, 32.32), 0.50),
        _seg("USB_SHIELD", "F.Cu", (7.00, 32.32), (7.00, 34.50), 0.50),
        _seg("USB_SHIELD", "F.Cu", (7.00, 34.50), (10.50, 34.50), 0.50),
        _seg("USB_SHIELD", "F.Cu", (10.50, 34.50), (11.49, 32.00), 0.20),
    ]

    # Protected pair.  The U3 and U1 layer changes are symmetric.  All B.Cu
    # copper remains outside the NINA body; only short F.Cu fan-ins reach pads
    # 54/55.  In1 remains the continuous RF/USB reference plane.
    s += [
        _seg("USB_DP_PROT", "F.Cu", (13.15, 27.05), (15.60, 27.05)),
        _seg("USB_DM_PROT", "F.Cu", (13.15, 28.95), (15.60, 28.95)),
        _seg("USB_DP_PROT", "B.Cu", (15.60, 27.05), (20.00, 22.00)),
        _seg("USB_DP_PROT", "B.Cu", (20.00, 22.00), (35.00, 18.00)),
        _seg("USB_DP_PROT", "B.Cu", (35.00, 18.00), (44.00, 9.00)),
        _seg("USB_DP_PROT", "B.Cu", (44.00, 9.00), (49.00, 2.00)),
        _seg("USB_DM_PROT", "B.Cu", (15.60, 28.95), (20.00, 24.00)),
        _seg("USB_DM_PROT", "B.Cu", (20.00, 24.00), (35.00, 20.00)),
        _seg("USB_DM_PROT", "B.Cu", (35.00, 20.00), (43.00, 12.00)),
        _seg("USB_DM_PROT", "B.Cu", (43.00, 12.00), (48.00, 4.80)),
        _seg("USB_DP_PROT", "F.Cu", (49.00, 2.00), (51.50, 3.00)),
        _seg("USB_DP_PROT", "F.Cu", (51.50, 3.00), (51.50, 4.15)),
        _seg("USB_DM_PROT", "F.Cu", (48.00, 4.80), (49.20, 4.80)),
        _seg("USB_DM_PROT", "F.Cu", (49.20, 4.80), (50.50, 4.15)),
    ]
    v += [
        _via("USB_DP_PROT", 15.60, 27.05), _via("USB_DM_PROT", 15.60, 28.95),
        _via("USB_DP_PROT", 49.00, 2.00), _via("USB_DM_PROT", 48.00, 4.80),
    ]
    return s, v


def display_spi_group() -> tuple[list[dict], list[dict]]:
    s = [
        _seg("TFT_SCK", "F.Cu", (25.625, 5.10), (25.625, 6.5), .15),
        _seg("TFT_SCK", "F.Cu", (25.625, 6.5), (27, 8.5), .15),
        _seg("TFT_SCK", "F.Cu", (27, 8.5), (29, 11), .15),
        _seg("TFT_SCK", "F.Cu", (29, 11), (31, 13), .15),
        _seg("TFT_SCK", "F.Cu", (31, 13), (31.8, 14.8), .15),
        _seg("TFT_SCK", "F.Cu", (31.8, 14.8), (45.8, 14.8), .15),
        _seg("TFT_SCK", "F.Cu", (45.8, 14.8), (45.8, 5.5), .15),
        _seg("TFT_SCK", "F.Cu", (45.8, 5.5), (45.8, .45), .15),
        _seg("TFT_SCK", "F.Cu", (45.8, .45), (53.5, .45), .15),
        _seg("TFT_SCK", "F.Cu", (53.5, .45), (53.5, 4.15), .15),
        _seg("TFT_CS_N", "F.Cu", (24.375, 5.10), (24.375, 14.6), .15),
        _seg("TFT_CS_N", "F.Cu", (24.375, 14.6), (24.6, 15.6), .15),
        _seg("TFT_CS_N", "F.Cu", (24.6, 15.6), (46.2, 15.6), .15),
        _seg("TFT_CS_N", "F.Cu", (46.2, 15.6), (46.2, 5.5), .15),
        _seg("TFT_CS_N", "F.Cu", (46.2, 5.5), (46.2, .85), .15),
        _seg("TFT_CS_N", "F.Cu", (46.2, .85), (52.8, .85), .15),
        _seg("TFT_CS_N", "F.Cu", (52.8, .85), (52.8, 1.85), .15),
        _seg("TFT_CS_N", "B.Cu", (52.8, 1.85), (54.5, 1.85), .15),
        _seg("TFT_CS_N", "F.Cu", (54.5, 1.85), (54.5, 4.15), .15),
        _seg("TFT_MOSI", "F.Cu", (26.875, 5.10), (26.875, 6.2), .15),
        _seg("TFT_MOSI", "B.Cu", (26.875, 6.2), (26.875, 16.4), .15),
        _seg("TFT_MOSI", "B.Cu", (26.875, 16.4), (34, 16.4), .15),
        _seg("TFT_MOSI", "F.Cu", (34, 16.4), (46.6, 16.4), .15),
        _seg("TFT_MOSI", "F.Cu", (46.6, 16.4), (46.6, 5.5), .15),
        _seg("TFT_MOSI", "F.Cu", (46.6, 5.5), (46.6, 1.25), .15),
        _seg("TFT_MOSI", "F.Cu", (46.6, 1.25), (52, 1.25), .15),
        _seg("TFT_MOSI", "F.Cu", (52, 1.25), (52, 2.50), .15),
        _seg("TFT_MOSI", "B.Cu", (52, 2.50), (55.5, 2.50), .15),
        _seg("TFT_MOSI", "F.Cu", (55.5, 2.50), (55.5, 4.15), .15),
        _seg("TFT_RESET_N", "F.Cu", (21.875, 5.1), (21.4, 6), .15),
        _seg("TFT_RESET_N", "F.Cu", (21.4, 6), (21.4, 16.5), .15),
        _seg("TFT_RESET_N", "F.Cu", (21.4, 16.5), (22.1, 17.2), .15),
        _seg("TFT_RESET_N", "F.Cu", (22.1, 17.2), (23.8, 17.2), .15),
        _seg("TFT_RESET_N", "B.Cu", (23.8, 17.2), (33.5, 17.2), .15),
        _seg("TFT_RESET_N", "F.Cu", (33.5, 17.2), (47, 17.2), .15),
        _seg("TFT_RESET_N", "F.Cu", (47, 17.2), (47, 3.2), .15),
        _seg("TFT_RESET_N", "F.Cu", (47, 3.2), (49.7, 3.2), .15),
        _seg("TFT_RESET_N", "B.Cu", (49.7, 3.2), (50.2, 1.25), .15),
        _seg("TFT_RESET_N", "B.Cu", (50.2, 1.25), (56.5, 1.25), .15),
        _seg("TFT_RESET_N", "F.Cu", (56.5, 1.25), (56.5, 4.15), .15),
        _seg("TFT_DC", "F.Cu", (23.125, 5.1), (23.125, 6.5), .15),
        _seg("TFT_DC", "B.Cu", (23.125, 6.5), (23.125, 18), .15),
        _seg("TFT_DC", "B.Cu", (23.125, 18), (31.5, 18), .15),
        _seg("TFT_DC", "F.Cu", (31.5, 18), (47.4, 18), .15),
        _seg("TFT_DC", "F.Cu", (47.4, 18), (47.4, 5.8), .15),
        _seg("TFT_DC", "F.Cu", (47.4, 5.8), (49, 5.8), .15),
        _seg("TFT_DC", "B.Cu", (49, 5.8), (48.70, 5.00), .15),
        _seg("TFT_DC", "B.Cu", (48.70, 5.00), (49.50, 3.90), .15),
        _seg("TFT_DC", "B.Cu", (49.50, 3.90), (51, 3.90), .15),
        _seg("TFT_DC", "B.Cu", (51, 3.90), (56.0, 3.90), .15),
        _seg("TFT_DC", "B.Cu", (56.0, 3.90), (56.0, 3.00), .15),
        _seg("TFT_DC", "B.Cu", (56.0, 3.00), (57.5, 3.00), .15),
        _seg("TFT_DC", "F.Cu", (57.5, 3.0), (57.5, 4.15), .15),
    ]
    v = [
        _via("TFT_MOSI", 26.875, 6.2),
        _via("TFT_MOSI", 34, 16.4),
        _via("TFT_MOSI", 52, 2.50),
        _via("TFT_MOSI", 55.5, 2.50),
        _via("TFT_CS_N", 52.8, 1.85),
        _via("TFT_CS_N", 54.5, 1.85),
        _via("TFT_RESET_N", 23.8, 17.2),
        _via("TFT_RESET_N", 33.5, 17.2),
        _via("TFT_RESET_N", 49.7, 3.2),
        _via("TFT_RESET_N", 56.5, 1.25),
        _via("TFT_DC", 23.125, 6.5),
        _via("TFT_DC", 31.5, 18),
        _via("TFT_DC", 49, 5.8),
        _via("TFT_DC", 57.5, 3.0),
    ]
    s += [
        _seg("TFT_BL_3V3", "F.Cu", (20.625, 5.1), (20.625, 4), .15),
        _seg("TFT_BL_3V3", "B.Cu", (20.625, 4), (34, 4), .15),
        _seg("TFT_BL_3V3", "F.Cu", (34, 4), (35.5, 5), .15),
        _seg("TFT_BL_3V3", "F.Cu", (35.5, 5), (36.4375, 7.5), .15),
        _seg("TFT_BL_GATE_CTRL", "F.Cu", (58.5, 4.15), (58.5, .65), .15),
        _seg("TFT_BL_GATE_CTRL", "B.Cu", (58.5, .65), (33, .65), .15),
        _seg("TFT_BL_GATE_CTRL", "F.Cu", (33, .65), (33, 5.5), .15),
        _seg("TFT_BL_GATE_CTRL", "F.Cu", (33, 5.5), (31.5, 7.0), .15),
        _seg("TFT_BL_GATE_CTRL", "F.Cu", (31.5, 7.0), (31.5, 8.8), .15),
        _seg("TFT_BL_GATE_CTRL", "F.Cu", (31.5, 8.8), (32.49, 10), .15),
        _seg("TFT_BL_GATE", "F.Cu", (34.5625, 6.55), (33.5, 6.55), .15),
        _seg("TFT_BL_GATE", "F.Cu", (33.5, 6.55), (32.4, 7.6), .15),
        _seg("TFT_BL_GATE", "F.Cu", (32.4, 7.6), (32.4, 8.8), .15),
        _seg("TFT_BL_GATE", "F.Cu", (32.4, 8.8), (33.51, 10), .15),
        _seg("TFT_BL_GATE", "F.Cu", (36.01, 10), (36.01, 9.3), .15),
        _seg("TFT_BL_GATE", "F.Cu", (36.01, 9.3), (33.51, 9.3), .15),
        _seg("TFT_BL_GATE", "F.Cu", (33.51, 9.3), (33.51, 10), .15),
    ]
    v += [
        _via("TFT_BL_3V3", 20.625, 4),
        _via("TFT_BL_3V3", 34, 4),
        _via("TFT_BL_GATE_CTRL", 58.5, .65),
        _via("TFT_BL_GATE_CTRL", 33, .65),
    ]
    return s, v


def audio_group() -> tuple[list[dict], list[dict]]:
    """I2S, software shutdown, hardware-mode strap, and gain selection.

    The four NINA audio outputs fan left, away from the B302 antenna. In1 is
    never used for signals and remains the continuous ground reference plane.
    MAX98357A OUTP/OUTN are already routed only to the floating BTL connector
    by the locked power skeleton; this group never touches either output net.
    """
    s: list[dict] = []
    v: list[dict] = []

    # BCLK changes to B.Cu immediately outside pad 1 and follows the module's
    # left edge before returning to F.Cu for TP8 and U4 pin 16.
    s += [
        _seg("I2S_BCLK", "F.Cu", (50.625, 5.30), (49.70, 5.30), .15),
        _seg("I2S_BCLK", "B.Cu", (49.70, 5.30), (49.60, 6.00), .15),
        _seg("I2S_BCLK", "B.Cu", (49.60, 6.00), (49.60, 12.80), .15),
        _seg("I2S_BCLK", "B.Cu", (49.60, 12.80), (50.40, 13.20), .15),
        _seg("I2S_BCLK", "B.Cu", (50.40, 13.20), (50.40, 14.40), .15),
        _seg("I2S_BCLK", "B.Cu", (50.40, 14.40), (49.60, 14.80), .15),
        _seg("I2S_BCLK", "B.Cu", (49.60, 14.80), (49.60, 23.50), .15),
        _seg("I2S_BCLK", "F.Cu", (49.60, 23.50), (47.50, 24.00), .15),
        _seg("I2S_BCLK", "F.Cu", (47.50, 24.00), (42.00, 26.00), .15),
        _seg("I2S_BCLK", "F.Cu", (42.00, 26.00), (35.00, 28.00), .15),
        _seg("I2S_BCLK", "F.Cu", (35.00, 28.00), (37.00, 27.50), .15),
        _seg("I2S_BCLK", "F.Cu", (37.00, 27.50), (39.50, 28.50), .15),
        _seg("I2S_BCLK", "F.Cu", (39.50, 28.50), (41.50, 31.50), .15),
        _seg("I2S_BCLK", "F.Cu", (41.50, 31.50), (43.40, 33.20), .15),
        _seg("I2S_BCLK", "F.Cu", (43.40, 33.20), (43.25, 34.5625), .15),
    ]
    v += [
        _via("I2S_BCLK", 49.70, 5.30), _via("I2S_BCLK", 49.60, 23.50),
    ]

    # LRCLK changes layer just outside pad 2, never in the LGA land itself.
    s += [
        _seg("I2S_LRCLK", "F.Cu", (50.625, 6.30), (48.90, 6.80), .15),
        _seg("I2S_LRCLK", "B.Cu", (48.90, 6.80), (48.90, 24.50), .15),
        _seg("I2S_LRCLK", "B.Cu", (48.90, 24.50), (47.50, 28.50), .15),
        _seg("I2S_LRCLK", "B.Cu", (47.50, 28.50), (45.00, 33.00), .15),
        _seg("I2S_LRCLK", "F.Cu", (45.00, 33.00), (44.25, 33.70), .15),
        _seg("I2S_LRCLK", "F.Cu", (44.25, 33.70), (44.25, 34.5625), .15),
    ]
    v += [_via("I2S_LRCLK", 48.90, 6.80), _via("I2S_LRCLK", 45.00, 33.00)]

    # Serial data remains on B.Cu for the long run and has no pad/via overlap.
    s += [
        _seg("I2S_DOUT", "F.Cu", (50.625, 7.30), (48.30, 7.80), .15),
        _seg("I2S_DOUT", "B.Cu", (48.30, 7.80), (47.20, 8.40), .15),
        _seg("I2S_DOUT", "B.Cu", (47.20, 8.40), (47.20, 20.40), .15),
        _seg("I2S_DOUT", "B.Cu", (47.20, 20.40), (46.50, 21.00), .15),
        _seg("I2S_DOUT", "B.Cu", (46.50, 21.00), (46.50, 25.00), .15),
        _seg("I2S_DOUT", "B.Cu", (46.50, 25.00), (44.00, 29.00), .15),
        _seg("I2S_DOUT", "B.Cu", (44.00, 29.00), (42.5625, 33.30), .15),
        _seg("I2S_DOUT", "F.Cu", (42.5625, 33.30), (42.5625, 35.25), .15),
    ]
    v += [_via("I2S_DOUT", 48.30, 7.80), _via("I2S_DOUT", 42.5625, 33.30)]

    # Software shutdown/control exits B.Cu to the right of the TFT_DC lane,
    # then rounds its endpoint on F.Cu with explicit clearance.
    s += [
        _seg("AUDIO_SD_CTRL", "F.Cu", (50.625, 8.30), (48.00, 8.80), .15),
        _seg("AUDIO_SD_CTRL", "B.Cu", (48.00, 8.80), (48.00, 16.80), .15),
        _seg("AUDIO_SD_CTRL", "B.Cu", (48.00, 16.80), (48.20, 17.50), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (48.20, 17.50), (48.60, 18.40), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (48.60, 18.40), (48.60, 19.00), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (48.60, 19.00), (46.00, 19.50), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (46.00, 19.50), (40.00, 21.00), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (40.00, 21.00), (34.00, 23.00), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (34.00, 23.00), (32.00, 26.00), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (32.00, 26.00), (32.00, 31.50), .15),
        _seg("AUDIO_SD_CTRL", "F.Cu", (32.00, 31.50), (38.49, 31.50), .15),
    ]
    v += [_via("AUDIO_SD_CTRL", 48.00, 8.80), _via("AUDIO_SD_CTRL", 48.20, 17.50)]

    # The hardware shutdown-mode pull-down remains present even if firmware
    # crashes; the series control resistor and both U4/R_PD branches join here.
    s += [
        _seg("AUDIO_SD_MODE", "F.Cu", (39.51, 31.50), (40.70, 31.50), .15),
        _seg("AUDIO_SD_MODE", "F.Cu", (40.70, 31.50), (40.70, 36.75), .15),
        _seg("AUDIO_SD_MODE", "F.Cu", (40.70, 33.80), (38.00, 33.80), .15),
        _seg("AUDIO_SD_MODE", "F.Cu", (38.00, 33.80), (36.51, 34.00), .15),
        _seg("AUDIO_SD_MODE", "F.Cu", (40.70, 36.75), (42.5625, 36.75), .15),
    ]

    # Gain selection crosses the SD_MODE trunk only on B.Cu, with ordinary
    # 0.60/0.30 mm vias placed clear of both 0402 and U4 paste lands.
    s += [
        _seg("AUDIO_GAIN_SLOT", "F.Cu", (39.51, 34.70), (39.70, 34.70), .15),
        _seg("AUDIO_GAIN_SLOT", "B.Cu", (39.70, 34.70), (41.40, 35.75), .15),
        _seg("AUDIO_GAIN_SLOT", "F.Cu", (41.40, 35.75), (42.5625, 35.75), .15),
    ]
    v += [_via("AUDIO_GAIN_SLOT", 39.70, 34.70), _via("AUDIO_GAIN_SLOT", 41.40, 35.75)]
    return s, v


def rgb_group() -> tuple[list[dict], list[dict]]:
    """Three discrete 3.3 V RGB cathode channels and local LED resistors.

    The NINA fan-out stays west of the module antenna section, changes to
    B.Cu only after the LGA pad row, and returns to F.Cu below the module.
    The common-anode 3V3 connection remains part of the locked power skeleton.
    """
    s = [
        # Blue exits first; green and red follow after the earlier F.Cu lane
        # has already changed layers, so no same-layer lane crossing occurs.
        _seg("RGB_B_N", "F.Cu", (50.625, 12.30), (48.80, 12.30), .15),
        _seg("RGB_B_N", "F.Cu", (48.80, 12.30), (48.80, 15.20), .15),
        _seg("RGB_B_N", "F.Cu", (48.80, 15.20), (51.00, 15.20), .15),
        _seg("RGB_B_N", "B.Cu", (51.00, 15.20), (51.225, 15.60), .15),
        _seg("RGB_B_N", "B.Cu", (51.225, 15.60), (51.225, 26.10), .15),
        _seg("RGB_B_N", "B.Cu", (51.225, 26.10), (51.00, 26.50), .15),
        _seg("RGB_B_N", "F.Cu", (51.00, 26.50), (51.00, 27.50), .15),
        _seg("RGB_B_N", "F.Cu", (51.00, 27.50), (54.49, 27.50), .15),
        _seg("RGB_B_N", "F.Cu", (54.49, 27.50), (54.49, 23.50), .15),
        _seg("RGB_G_N", "F.Cu", (50.625, 11.30), (48.30, 11.30), .15),
        _seg("RGB_G_N", "F.Cu", (48.30, 11.30), (48.30, 16.00), .15),
        _seg("RGB_G_N", "F.Cu", (48.30, 16.00), (50.60, 16.00), .15),
        _seg("RGB_G_N", "B.Cu", (50.60, 16.00), (50.825, 16.40), .15),
        _seg("RGB_G_N", "B.Cu", (50.825, 16.40), (50.825, 25.10), .15),
        _seg("RGB_G_N", "B.Cu", (50.825, 25.10), (50.60, 25.50), .15),
        _seg("RGB_G_N", "F.Cu", (50.60, 25.50), (52.80, 25.50), .15),
        _seg("RGB_G_N", "F.Cu", (52.80, 25.50), (54.49, 22.00), .15),
        _seg("RGB_R_N", "F.Cu", (50.625, 9.30), (49.20, 9.60), .15),
        _seg("RGB_R_N", "F.Cu", (49.20, 9.60), (47.80, 9.60), .15),
        _seg("RGB_R_N", "F.Cu", (47.80, 9.60), (47.80, 16.80), .15),
        _seg("RGB_R_N", "F.Cu", (47.80, 16.80), (50.20, 16.80), .15),
        _seg("RGB_R_N", "B.Cu", (50.20, 16.80), (50.20, 24.50), .15),
        _seg("RGB_R_N", "F.Cu", (50.20, 24.50), (50.20, 23.20), .15),
        _seg("RGB_R_N", "F.Cu", (50.20, 23.20), (52.50, 22.80), .15),
        _seg("RGB_R_N", "F.Cu", (52.50, 22.80), (54.49, 20.50), .15),
        # Resistor-to-die copper is short and stays on F.Cu.  Blue approaches
        # pad 3 from above so it cannot cross the adjacent 3V3 common pad.
        _seg("RGB_R_LED", "F.Cu", (55.51, 20.50), (56.20, 21.20), .15),
        _seg("RGB_R_LED", "F.Cu", (56.20, 21.20), (56.20, 21.775), .15),
        _seg("RGB_R_LED", "F.Cu", (56.20, 21.775), (57.075, 21.775), .15),
        _seg("RGB_G_LED", "F.Cu", (55.51, 22.00), (55.80, 22.50), .15),
        _seg("RGB_G_LED", "F.Cu", (55.80, 22.50), (58.60, 22.50), .15),
        _seg("RGB_G_LED", "F.Cu", (58.60, 22.50), (58.60, 21.775), .15),
        _seg("RGB_G_LED", "F.Cu", (58.60, 21.775), (57.925, 21.775), .15),
        _seg("RGB_B_LED", "F.Cu", (55.51, 23.50), (55.50, 25.00), .15),
        _seg("RGB_B_LED", "F.Cu", (55.50, 25.00), (58.60, 25.00), .15),
        _seg("RGB_B_LED", "F.Cu", (58.60, 25.00), (58.60, 23.225), .15),
        _seg("RGB_B_LED", "F.Cu", (58.60, 23.225), (57.925, 23.225), .15),
    ]
    v = [
        _via("RGB_B_N", 51.00, 15.20), _via("RGB_B_N", 51.00, 26.50),
        _via("RGB_G_N", 50.60, 16.00), _via("RGB_G_N", 50.60, 25.50),
        _via("RGB_R_N", 50.20, 16.80), _via("RGB_R_N", 50.20, 24.50),
    ]
    return s, v
