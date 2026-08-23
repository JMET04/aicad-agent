#!/usr/bin/env python3
"""Generate the independent Magic Wand receiver-effects A0 KiCad project.

This generator deliberately reuses only the deterministic data model and native
KiCad serializers from the reviewed magic-wand electronics framework.  It does
not import, regenerate, or modify either the wand PCB or the legacy receiver.
Native ERC/DRC and the separately written fabrication gate remain authoritative.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ELECTRONICS = HERE.parent
sys.path.insert(0, str(ELECTRONICS))

from build_factory_package import (  # noqa: E402
    Board,
    Part,
    PhysicalPad,
    absolute_pads,
    mounting_hole,
    nina_pins,
    pins,
    route_board,
    testpoint,
    two_pin,
)
from factory_emit import (  # noqa: E402
    write_bom_cpl,
    write_pcb,
    write_project,
    write_schematic,
)
from land_pattern_authority import (  # noqa: E402
    configure_body_and_datum,
    physical_pads_for_part,
)


GENERATOR_VERSION = "1.0.0"


def smd(pid: str, number: str, x: float, y: float, width: float, height: float,
        *, rotation: float = 0.0, role: str = "signal", net: str | None = None) -> PhysicalPad:
    return PhysicalPad(pid, number, x, y, width, height, rotation=rotation,
                       role=role, net_override=net)


def make_nina_pins():
    result = nina_pins(False)
    overrides = {
        "1": ("P0.13", "I2S_BCLK", "output"),
        "2": ("P0.14", "I2S_LRCLK", "output"),
        "3": ("P0.15", "I2S_DOUT", "output"),
        "4": ("P0.16", "AUDIO_SD_CTRL", "output"),
        "5": ("P0.24", "RGB_R_N", "output"),
        "7": ("P0.25", "RGB_G_N", "output"),
        "8": ("P1.00", "RGB_B_N", "output"),
        "25": ("P0.04", "NC", "no_connect"),
        "32": ("P0.11", "NC", "no_connect"),
        "33": ("P1.09", "NC", "no_connect"),
        "42": ("P0.26", "NC", "no_connect"),
        "43": ("P0.06", "NC", "no_connect"),
        "44": ("P0.27", "NC", "no_connect"),
        "47": ("P0.23", "TFT_BL_GATE_CTRL", "output"),
        "48": ("P0.21", "TFT_DC", "output"),
        "49": ("P0.22", "TFT_RESET_N", "output"),
        "50": ("P0.20", "TFT_MOSI", "output"),
        "51": ("P0.17", "TFT_CS_N", "output"),
        "52": ("P0.19", "TFT_SCK", "output"),
    }
    for pin in result:
        if pin.number in overrides:
            pin.name, pin.net, pin.electrical_type = overrides[pin.number]
    return result


def set_custom_geometry(part: Part, pads: list[PhysicalPad], *, body: tuple[float, float, float],
                        courtyard: tuple[float, float, float, float] | None = None) -> Part:
    part.physical_pads = pads
    part.width, part.height, part.body_height_mm = body
    part.fab_bounds = (-body[0] / 2, -body[1] / 2, body[0] / 2, body[1] / 2)
    part.courtyard_bounds = courtyard or (-body[0] / 2 - .25, -body[1] / 2 - .25,
                                           body[0] / 2 + .25, body[1] / 2 + .25)
    part.interface_datum = {
        "anchor": "footprint-origin",
        "sourceAxes": {"x": "right", "y": "down", "units": "mm"},
        "placementRotationDeg": part.rotation,
    }
    part.exact_land_pattern = True
    return part


def make_board() -> Board:
    p: list[Part] = []

    p.append(Part(
        "U1", "NINA-B302-00B-00", "u-blox", "NINA-B302-00B-00",
        "MW_FACTORY:NINA-B302_LGA55", 44.75, 11.0, 10.0, 15.0,
        make_nina_pins(), package="LGA-55", lcsc="C6335962",
        notes="Module antenna points toward +X/right board edge; keep all enclosure metal and cables out of the antenna projection",
        datasheet="https://content.u-blox.com/sites/default/files/NINA-B3_DataSheet_UBX-17052099.pdf",
    ))

    # USB-C power and USB 2.0 service path.  The 5 V source is external and
    # must be rated 2 A; no PD/QC negotiation or source mode is implemented.
    usb_pins = pins({
        "A1": ("GND", "GND"), "A4": ("VBUS", "USB_VBUS_RAW"),
        "A5": ("CC1", "USB_CC1"), "A6": ("D+", "USB_DP_RAW"),
        "A7": ("D-", "USB_DM_RAW"), "A8": ("SBU1", "NC", "no_connect"),
        "A9": ("VBUS", "USB_VBUS_RAW"), "A12": ("GND", "GND"),
        "B1": ("GND", "GND"), "B4": ("VBUS", "USB_VBUS_RAW"),
        "B5": ("CC2", "USB_CC2"), "B6": ("D+", "USB_DP_RAW"),
        "B7": ("D-", "USB_DM_RAW"), "B8": ("SBU2", "NC", "no_connect"),
        "B9": ("VBUS", "USB_VBUS_RAW"), "B12": ("GND", "GND"),
        "SH": ("SHIELD", "USB_SHIELD"),
    })
    p.append(Part(
        "J1", "USB-C 5V INPUT", "GCT", "USB4105-GF-A-120",
        "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
        3.675, 21.0, 8.94, 7.35,
        usb_pins, rotation=270.0, package="USB4105-16P", lcsc="C5184243",
        notes="5V sink/service only; use an externally qualified 5V/2A source; no USB-PD or QC",
        datasheet="https://gct.co/files/drawings/usb4105.pdf",
    ))
    p.append(Part(
        "U3", "USBLC6-2SC6", "STMicroelectronics", "USBLC6-2SC6",
        "Package_TO_SOT_SMD:SOT-23-6", 10.0, 23.0, 3.0, 1.7,
        pins({
            "1": ("I/O1_RAW", "USB_DP_RAW"), "2": ("GND", "GND", "power_in"),
            "3": ("I/O2_RAW", "USB_DM_RAW"), "4": ("I/O2_PROT", "USB_DM_PROT"),
            "5": ("VBUS", "USB_VBUS_5V", "power_in"), "6": ("I/O1_PROT", "USB_DP_PROT"),
        }), package="SOT-23-6", lcsc="C7519",
        datasheet="https://www.st.com/resource/en/datasheet/usblc6-2.pdf",
    ))
    # Local USB_VBUS_5V decoupling at the ESD clamp (U3), 0402.
    p.append(two_pin("C_BUS", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D",
                     "USB_VBUS_5V", "GND", 14.70, 28.00, package="0402"))
    p[-1].lcsc = "C1525"
    p[-1].datasheet = "https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM155R71C104KA88-01.pdf"

    p.append(two_pin("F1", "1.5A PTC", "Bourns", "MF-MSMF150/24X-2",
                     "USB_VBUS_RAW", "USB_VBUS_5V", 11.0, 13.5, package="1812",
                     notes="6V resettable fuse; Bourns MF-MSMF150/24X-2 (LCSC C78695); hold/trip and enclosure-temperature HIL remain a gate"))
    p[-1].footprint = "Fuse:Fuse_1812_4532Metric"
    p[-1].lcsc = "C78695"
    p[-1].datasheet = "https://www.bourns.com/docs/product-datasheets/mf-msmf.pdf"
    set_custom_geometry(p[-1], [
        smd("terminal-1", "1", -2.390, 0, 1.68, 2.95),
        smd("terminal-2", "2", 2.390, 0, 1.68, 2.95),
    ], body=(4.5, 3.2, 1.2), courtyard=(-2.75, -1.95, 2.75, 1.95))

    p.append(Part(
        "U2", "TPS62162DSGR", "Texas Instruments", "TPS62162DSGR",
        "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm",
        16.0, 17.0, 2.0, 2.0,
        pins({
            "1": ("PGND", "GND", "power_in"), "2": ("VIN", "USB_VBUS_5V", "power_in"),
            "3": ("EN", "USB_VBUS_5V", "input"), "4": ("AGND", "GND", "power_in"),
            "5": ("FB", "GND", "input"), "6": ("VOS", "3V3", "input"),
            "7": ("SW", "BUCK_SW", "power_out"), "8": ("PG", "PWR_GOOD_N", "open_collector"),
            "EP": ("THERMAL_PAD", "GND", "power_in"),
        }), package="WSON-8-EP", lcsc="C40256",
        notes="Fixed 3.3V / 1A buck; 3-17V input rating does not authorize >5V board input",
        datasheet="https://www.ti.com/lit/ds/symlink/tps62162.pdf",
    ))
    set_custom_geometry(p[-1], [
        smd("pad-1", "1", -0.95, -0.75, 0.50, 0.25),
        smd("pad-2", "2", -0.95, -0.25, 0.50, 0.25),
        smd("pad-3", "3", -0.95, 0.25, 0.50, 0.25),
        smd("pad-4", "4", -0.95, 0.75, 0.50, 0.25),
        smd("pad-5", "5", 0.95, 0.75, 0.50, 0.25),
        smd("pad-6", "6", 0.95, 0.25, 0.50, 0.25),
        smd("pad-7", "7", 0.95, -0.25, 0.50, 0.25),
        smd("pad-8", "8", 0.95, -0.75, 0.50, 0.25),
        smd("thermal-ep", "EP", 0.0, 0.0, 0.90, 1.60, role="thermal"),
    ], body=(2.0, 2.0, 0.9), courtyard=(-1.25, -1.25, 1.25, 1.25))
    p.append(two_pin("L1", "2.2uH", "Murata", "LQH32PN2R2NN0L",
                     "BUCK_SW", "3V3", 20.0, 17.0, package="L_4x4"))
    p[-1].footprint = "Inductor_SMD:L_1210_3225Metric"
    p[-1].datasheet = "https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/LQH32PN2R2NN0-01.pdf"

    # Exact external module: Waveshare 1.28inch LCD Module SKU 19192. Keep the
    # official straight-through order VCC/GND/DIN/CLK/CS/DC/RST/BL.
    j2 = Part(
        "J2", "GC9A01A 1.28in SPI", "JST", "SM08B-GHS-TB(LF)(SN)",
        "Connector_JST:JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
        20.0, 3.25, 13.25, 4.05,
        pins({
            "1": ("VCC", "3V3", "passive"), "2": ("GND", "GND", "power_in"),
            "3": ("DIN/MOSI", "TFT_MOSI", "input"), "4": ("CLK/SCK", "TFT_SCK", "input"),
            "5": ("CS", "TFT_CS_N", "input"), "6": ("DC", "TFT_DC", "input"),
            "7": ("RST", "TFT_RESET_N", "input"), "8": ("BL", "TFT_BL_3V3", "power_in"),
        }), rotation=180.0, package="JST-GH-8", lcsc="C265111",
        notes="External Waveshare SKU19192 via straight-through JST-GH-to-PH2.0 harness; 3.3V SPI, no MISO; order VCC/GND/DIN/CLK/CS/DC/RST/BL",
        datasheet="https://www.jst-mfg.com/product/pdf/eng/eGH.pdf",
    )
    set_custom_geometry(j2, [
        *[smd(f"contact-{n}", str(n), -4.375 + 1.25 * (n - 1), -1.85, .6, 1.7)
          for n in range(1, 9)],
        smd("mount-left", "", -6.225, 1.35, 1.0, 2.7, role="mount"),
        smd("mount-right", "", 6.225, 1.35, 1.0, 2.7, role="mount"),
    ], body=(13.25, 4.05, 4.0), courtyard=(-7.23, -3.20, 7.23, 3.20))
    j2.interface_datum.update({"matingAxis": "toward top board edge", "connectorOrder": [
        "VCC", "GND", "DIN", "CLK", "CS", "DC", "RST", "BL"]})
    p.append(j2)

    q1 = Part(
        "Q1", "AO3401A", "Alpha & Omega Semiconductor", "AO3401A",
        "Package_TO_SOT_SMD:SOT-23", 28.2, 9.2, 3.0, 1.4,
        pins({"1": ("GATE", "TFT_BL_GATE", "input"),
              "2": ("SOURCE", "3V3", "passive"),
              "3": ("DRAIN", "TFT_BL_3V3", "power_out")}),
        package="SOT-23", lcsc="C15127",
        notes="P-channel high-side backlight switch; firmware PWM is active-low; 100k pull-up defaults off",
    )
    set_custom_geometry(q1, [
        smd("gate", "1", -.9375, -.95, 1.475, .6),
        smd("source", "2", -.9375, .95, 1.475, .6),
        smd("drain", "3", .9375, 0, 1.475, .6),
    ], body=(2.9, 1.3, 1.1), courtyard=(-1.95, -1.65, 1.95, 1.65))
    p.append(q1)

    # MAX98357A: BTL speaker outputs are never referenced to ground.
    u4 = Part(
        "U4", "MAX98357AETE+T", "Analog Devices", "MAX98357AETE+T",
        "Package_DFN_QFN:TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm",
        36.0, 29.0, 3.0, 3.0,
        pins({
            "1": ("DIN", "I2S_DOUT", "input"), "2": ("GAIN_SLOT", "AUDIO_GAIN_SLOT", "input"),
            "3": ("GND", "GND", "power_in"), "4": ("SD_MODE", "AUDIO_SD_MODE", "input"),
            "5": ("NC", "NC", "no_connect"), "6": ("NC", "NC", "no_connect"),
            "7": ("VDD", "USB_VBUS_5V", "power_in"), "8": ("VDD", "USB_VBUS_5V", "power_in"),
            "9": ("OUTP", "SPK_PLUS", "power_out"), "10": ("OUTN", "SPK_MINUS", "power_out"),
            "11": ("GND", "GND", "power_in"), "12": ("NC", "NC", "no_connect"),
            "13": ("NC", "NC", "no_connect"), "14": ("LRCLK", "I2S_LRCLK", "input"),
            "15": ("GND", "GND", "power_in"), "16": ("BCLK", "I2S_BCLK", "input"),
            "17": ("EP", "GND", "power_in"),
        }), package="TQFN-16-EP", lcsc="C910544",
        notes="5V BTL mono amp; GAIN_SLOT=GND gives 12dB gain; SD_MODE hardware-low at reset; speaker 4ohm >=3W",
        datasheet="https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf",
    )
    tqfn_pads = []
    for n, y in zip(range(1, 5), (-.75, -.25, .25, .75)):
        tqfn_pads.append(smd(f"land-{n}", str(n), -1.425, y, .80, .30))
    for n, x in zip(range(5, 9), (-.75, -.25, .25, .75)):
        tqfn_pads.append(smd(f"land-{n}", str(n), x, 1.425, .30, .80))
    for n, y in zip(range(9, 13), (.75, .25, -.25, -.75)):
        tqfn_pads.append(smd(f"land-{n}", str(n), 1.425, y, .80, .30))
    for n, x in zip(range(13, 17), (.75, .25, -.25, -.75)):
        tqfn_pads.append(smd(f"land-{n}", str(n), x, -1.425, .30, .80))
    tqfn_pads.append(smd("exposed-pad", "17", 0, 0, 1.23, 1.23, role="thermal"))
    set_custom_geometry(u4, tqfn_pads, body=(3.0, 3.0, .8), courtyard=(-2.1, -2.1, 2.1, 2.1))
    p.append(u4)

    j3 = Part(
        "J3", "4OHM BTL SPEAKER", "JST", "S2B-PH-SM4-TB(LF)(SN)",
        "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
        44.3, 34.5, 7.9, 7.6,
        pins({"1": ("SPK_PLUS", "SPK_PLUS", "passive"),
              "2": ("SPK_MINUS", "SPK_MINUS", "passive")}),
        rotation=90.0, package="JST-PH-2", lcsc="C295747",
        notes="BTL 4ohm speaker only, rated >=3W; neither terminal may connect to chassis or GND",
        datasheet="https://www.jst-mfg.com/product/pdf/eng/ePH.pdf",
    )
    set_custom_geometry(j3, [
        smd("contact-1", "1", -1, -2.85, 1.0, 3.5),
        smd("contact-2", "2", 1, -2.85, 1.0, 3.5),
        smd("mount-left", "", -3.35, 2.9, 1.5, 3.4, role="mount"),
        smd("mount-right", "", 3.35, 2.9, 1.5, 3.4, role="mount"),
    ], body=(7.9, 7.6, 4.5), courtyard=(-4.60, -5.10, 4.60, 5.10))
    j3.interface_datum.update({"matingAxis": "toward right board edge", "btldifferential": True})
    p.append(j3)

    led = Part(
        "D1", "RGB COMMON ANODE", "Lite-On", "LTST-C19HE1WT",
        "LED_SMD:LED_LiteOn_LTST-C19HE1WT", 31.8, 5.1, 1.6, 1.6,
        pins({"1": ("RED_K", "RGB_R_LED", "passive"),
              "2": ("GREEN_K", "RGB_G_LED", "passive"),
              "3": ("BLUE_K", "RGB_B_LED", "passive"),
              "4": ("COMMON_ANODE", "3V3", "passive")}),
        package="LED-RGB-2020", lcsc="C458749",
        notes="Discrete common-anode 3.3V status LED; all channels active-low through individual resistors",
        datasheet="https://optoelectronics.liteon.com/upload/download/DS22-2008-0044/LTST-C19HE1WT_20210326.PDF",
    )
    set_custom_geometry(led, [
        smd("red", "1", -.425, -.725, .65, .85),
        smd("green", "2", .425, -.725, .65, .85),
        smd("blue", "3", .425, .725, .65, .85),
        smd("common", "4", -.425, .725, .65, .85),
    ], body=(1.6, 1.6, .55), courtyard=(-1.05, -1.40, 1.05, 1.40))
    p.append(led)

    # Passive networks.  LCSC IDs are assigned only where the exact MPN/code
    # pairing has been captured; empty IDs remain visible procurement gates.
    passive_specs = [
        ("R_CC1", "5.1k", "Yageo", "RC0402FR-075K1L", "USB_CC1", "GND", 6.0, 12.5, "C25905"),
        ("R_CC2", "5.1k", "Yageo", "RC0402FR-075K1L", "USB_CC2", "GND", 7.4, 28.0, "C25905"),
        ("R_SH", "0R", "Yageo", "RC0402JR-070RL", "USB_SHIELD", "GND", 9.0, 25.3, "C17168"),
        ("R_PG", "10k", "Yageo", "RC0402FR-0710KL", "3V3", "PWR_GOOD_N", 14.2, 20.0, "C25744"),
        ("R_BL_SER", "100R", "Yageo", "RC0402FR-07100RL", "TFT_BL_GATE_CTRL", "TFT_BL_GATE", 25.2, 9.2, "C25076"),
        ("R_BL_PU", "100k", "Yageo", "RC0402FR-07100KL", "3V3", "TFT_BL_GATE", 28.2, 12.0, "C25741"),
        ("R_SD", "2.2k", "Yageo", "RC0402FR-072K2L", "AUDIO_SD_CTRL", "AUDIO_SD_MODE", 31.0, 27.0, "C25879"),
        ("R_SD_PD", "100k", "Yageo", "RC0402FR-07100KL", "AUDIO_SD_MODE", "GND", 31.0, 29.0, "C25741"),
        ("R_GAIN", "0R", "Yageo", "RC0402JR-070RL", "AUDIO_GAIN_SLOT", "GND", 30.5, 32.5, "C17168"),
        ("R_LED_R", "330R", "Yageo", "RC0402FR-07330RL", "RGB_R_N", "RGB_R_LED", 28.8, 6.0, "C25104"),
        ("R_LED_G", "150R", "Yageo", "RC0402FR-07150RL", "RGB_G_N", "RGB_G_LED", 31.8, 7.4, "C25082"),
        ("R_LED_B", "150R", "Yageo", "RC0402FR-07150RL", "RGB_B_N", "RGB_B_LED", 34.2, 7.1, "C25082"),
        ("C_USB_RAW", "1uF 10V X7R", "Murata", "GRM155R71A105KE15D", "USB_VBUS_RAW", "GND", 10.5, 9.5, ""),
        ("C_BUCK_IN", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "USB_VBUS_5V", "GND", 15.8, 13.0, ""),
        ("C_BUCK_OUT", "22uF 6.3V X5R", "Murata", "GRM21BR60J226ME39L", "3V3", "GND", 24.5, 17.0, ""),
        ("C_NINA_HF", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "3V3", "GND", 37.5, 20.0, "C1525"),
        ("C_NINA_BULK", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "3V3", "GND", 41.0, 20.0, ""),
        ("C_AUDIO_HF", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "USB_VBUS_5V", "GND", 36.0, 25.5, "C1525"),
        ("C_AUDIO_10U", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "USB_VBUS_5V", "GND", 40.0, 24.0, ""),
        ("C_AUDIO_BULK", "22uF 10V X5R", "Murata", "GRM21BR61A226ME44L", "USB_VBUS_5V", "GND", 44.0, 24.0, ""),
    ]
    for ref, value, manufacturer, mpn, net1, net2, x, y, lcsc in passive_specs:
        package = "0805" if value.startswith(("10uF", "22uF")) else "0402"
        p.append(two_pin(ref, value, manufacturer, mpn, net1, net2, x, y, package=package))
        p[-1].lcsc = lcsc

    for ref, net, x, y in [
        ("TP1", "USB_VBUS_5V", 11.0, 28.0), ("TP2", "3V3", 14.0, 28.0),
        ("TP3", "GND", 17.0, 28.0), ("TP4", "SWDIO", 20.0, 28.0),
        ("TP5", "SWDCLK", 23.0, 28.0), ("TP6", "RESET_N", 26.0, 28.0),
        ("TP7", "TFT_SCK", 20.0, 10.0), ("TP8", "I2S_BCLK", 29.0, 24.0),
        ("TP9", "SPK_PLUS", 37.8, 33.0), ("TP10", "SPK_MINUS", 37.8, 36.0),
    ]:
        p.append(testpoint(ref, net, x, y))

    p.extend([
        mounting_hole("H1", 3.0, 3.0, 2.4), mounting_hole("H2", 35.0, 3.0, 2.4),
        mounting_hole("H3", 3.0, 39.0, 2.4), mounting_hole("H4", 31.0, 39.0, 2.4),
    ])

    board = Board(
        "receiver-effects", "Magic Wand Receiver Effects A0", 50.0, 42.0,
        [], p,
        {"USB_VBUS_RAW", "USB_VBUS_5V", "BUCK_SW", "3V3", "SPK_PLUS", "SPK_MINUS", "GND"},
        [("USB_DP_RAW", "USB_DM_RAW"), ("USB_DP_PROT", "USB_DM_PROT")],
        load_voltage_max_v=5.25,
        plane_requirements=[
            {"name": "CONTINUOUS_GROUND", "net": "GND", "layers": ["In1.Cu"], "fullGround": True},
            {"name": "SPLIT_POWER_PLANE", "nets": ["USB_VBUS_5V", "3V3"], "layers": ["In2.Cu"]},
            {"name": "NINA_FULL_GROUND_UNDER_MODULE", "ref": "U1", "net": "GND", "layers": ["In1.Cu"],
             "polygon": [[39.75, 3.5], [49.75, 3.5], [49.75, 18.5], [39.75, 18.5]],
             "fullGround": True, "viaStitchingRequired": True},
        ],
        mechanical_keepouts=[{
            "name": "NINA_ANTENNA_PROJECTION_OUTSIDE_BOARD",
            "polygon": [[49.75, 3.5], [60.0, 3.5], [60.0, 18.5], [49.75, 18.5]],
            "rule": "No enclosure metal, speaker magnet, wiring, or display cable in antenna projection",
        }],
    )

    for part in board.parts:
        if not part.physical_pads:
            part.physical_pads = physical_pads_for_part(
                board.name, part, PhysicalPad,
                __import__("build_factory_package").derive_pad_positions,
            )
            configure_body_and_datum(board.name, part)
            part.exact_land_pattern = True
    return board

def normalize_project_vias(path: Path) -> None:
    """Constrain every through-via choice to JLC coupon-safe 0.60/0.30 mm."""
    project = json.loads(path.read_text(encoding="utf-8"))
    rules = project["board"]["design_settings"]["rules"]
    rules["min_via_diameter"] = 0.60
    project["board"]["design_settings"]["via_dimensions"] = [
        {"diameter": 0.60, "drill": 0.30},
        {"diameter": 0.70, "drill": 0.30},
    ]
    for netclass in project["net_settings"]["classes"]:
        netclass["via_diameter"] = 0.70 if netclass["name"] == "LOAD_1A" else 0.60
        netclass["via_drill"] = 0.30
    path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8", newline="\n")






def add_surface_ground_and_power_split(path: Path, board: Board, net_ids: dict[str, int]) -> None:
    """Add F/B GND pours and replace In2 with explicit 5V/3V3 split regions."""
    text = path.read_text(encoding="utf-8")
    ox = (297.0 - board.width) / 2.0
    oy = (210.0 - board.height) / 2.0
    old = (
        f'  (zone (net {net_ids["3V3"]}) (net_name "3V3") (layer "In2.Cu")'
    )
    start = text.index(old)
    next_section = text.index("  (gr_line", start)
    text = text[:start] + text[next_section:]

    def zone(name: str, layer: str, points: list[tuple[float, float]], suffix: str) -> str:
        pts = " ".join(f"(xy {ox + x:.3f} {oy + y:.3f})" for x, y in points)
        uid = hashlib.sha256(f"receiver-effects/{suffix}".encode()).hexdigest()[:8]
        # UUID remains RFC4122-looking and deterministic.
        uuid_text = f"{uid}-0000-4000-8000-{uid}{uid[:4]}"
        return (
            f'  (zone (net {net_ids[name]}) (net_name "{name}") (layer "{layer}") (uuid {uuid_text})\n'
            "    (hatch edge 0.5) (connect_pads (clearance 0.20)) (min_thickness 0.15)\n"
            "    (fill yes (thermal_gap 0.30) (thermal_bridge_width 0.30))\n"
            f"    (polygon (pts {pts})))\n"
        )

    insert = ""
    full = [(.30, .30), (49.70, .30), (49.70, 41.70), (.30, 41.70)]
    insert += zone("GND", "F.Cu", full, "gnd-f")
    insert += zone("GND", "B.Cu", full, "gnd-b")
    # Non-overlapping horizontal split leaves a 0.50 mm keepout channel.
    insert += zone("3V3", "In2.Cu", [(.30, .30), (49.70, .30),
                                      (49.70, 21.50), (.30, 21.50)], "3v3-in2")
    insert += zone("USB_VBUS_5V", "In2.Cu", [(.30, 22.00), (49.70, 22.00),
                                              (49.70, 41.70), (.30, 41.70)], "5v-in2")

    text = text[:-2] + insert + ")\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def assign_3v3_power_flag(path: Path) -> None:
    """Reuse the emitter's third ERC source marker for the regulated rail.

    USB_SHIELD is already tied to GND through R_SH and needs no source marker;
    3V3 is sourced through a passive inductor, which ERC cannot infer.
    """
    text = path.read_text(encoding="utf-8")
    old = '  (label "USB_SHIELD" (at 215.900 15.240 0)'
    new = '  (label "3V3" (at 215.900 15.240 0)'
    if text.count(old) != 1:
        raise RuntimeError("expected exactly one #FLG03 USB_SHIELD label")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def write_design(board: Board, pads: list[dict], segments: list[dict], vias: list[dict], failures: list[str]) -> None:
    design = {
        "schema": "magic_wand_receiver_effects_factory_design_v1",
        "generator": {"path": HERE.name + "/generate_receiver_effects.py", "version": GENERATOR_VERSION},
        "status": "RELEASE_CANDIDATE_GATES_APPLY",
        "board": board.name,
        "revision": "A0",
        "dimensions_mm": [board.width, board.height],
        "layer_stack": ["F.Cu signal/GND pour", "In1.Cu continuous GND", "In2.Cu split 5V/3V3", "B.Cu signal/GND pour"],
        "components": [asdict(part) for part in board.parts],
        "pads": [{k: v for k, v in pad.items() if k not in {"part", "pin"}} for pad in pads],
        "routes": segments,
        "vias": vias,
        "router_failures": failures,
        "plane_requirements": board.plane_requirements,
        "mechanical_keepouts": board.mechanical_keepouts,
        "pin_contract": {
            "display": {"SCK": 52, "MOSI": 50, "CS": 51, "DC": 48, "RESET": 49, "BACKLIGHT": 47},
            "audio": {"BCLK": 1, "LRCLK": 2, "DOUT": 3, "SD_MODE": 4},
            "rgb": {"RED": 5, "GREEN": 7, "BLUE": 8},
        },
        "selected_external_peripherals": {
            "display": {
                "manufacturer": "Waveshare", "sku": "19192",
                "description": "1.28inch LCD Module, GC9A01, 240x240, 3.3V, approximately 31.2mA",
                "assembly": "external; not JLC PCBA", "harness": "straight-through JST-GH-8 to PH2.0-8",
            },
            "speaker": {
                "manufacturer": "XHXDZ", "mpn": "30MM-4Ω3W-TFHM", "lcsc": "C50387216",
                "description": "30mm, 4ohm, 3W prototype speaker",
                "assembly": "external; not JLC PCBA", "harness": "JST-PH2.0 two-wire; BTL, neither conductor grounded",
            },
        },
        "fab_policy": {"quantity": 5, "max_coupon_outline_mm": [100, 100], "layers": 4,
                       "soldermask_default": "green", "black_only_if_zero_cost": True},
    }
    (HERE / "receiver-effects-factory-design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    board = make_board()
    pads = absolute_pads(board, require_controlled=False)
    segments, vias, failures = route_board(board, pads)
    # JLCPCB free-prototype policy requires finished drill >=0.30 mm.  Normalize
    # every autorouter via before adding any manual stitching or fan-out vias.
    for via in vias:
        via.update({"size": .60, "drill": .30})
    width_by_net = {
        "USB_VBUS_RAW": .80, "USB_VBUS_5V": .80, "3V3": .50,
        "BUCK_SW": .50, "SPK_PLUS": .60, "SPK_MINUS": .60,
    }
    for segment in segments:
        segment["width"] = width_by_net.get(segment["net"], segment["width"])

    # The deterministic grid router cannot escape the dense top-edge TFT clock
    # pads. This reviewed fan-out moves it to B.Cu without a via-in-pad.
    if any(item.startswith("TFT_SCK:") for item in failures):
        segments.extend([
            {"net": "TFT_SCK", "layer": "F.Cu", "start": [21.875, 5.10], "end": [21.875, 7.00], "width": .20},
            {"net": "TFT_SCK", "layer": "B.Cu", "start": [21.875, 7.00], "end": [43.50, 3.30], "width": .20},
            {"net": "TFT_SCK", "layer": "F.Cu", "start": [43.50, 3.30], "end": [43.50, 4.15], "width": .20},
            {"net": "TFT_SCK", "layer": "B.Cu", "start": [21.875, 7.00], "end": [20.00, 10.00], "width": .20},
        ])
        vias.extend([
            {"net": "TFT_SCK", "x": 21.875, "y": 7.00, "size": .60, "drill": .30},
            {"net": "TFT_SCK", "x": 43.50, "y": 3.30, "size": .60, "drill": .30},
            {"net": "TFT_SCK", "x": 20.00, "y": 10.00, "size": .60, "drill": .30},
        ])
        failures = [item for item in failures if not item.startswith("TFT_SCK:")]

    # GND plane stitching plus local thermal/return stitching around U1/U4/U2.
    stitching = [
        (2.0, 10.0), (6.0, 10.0), (10.0, 10.0), (14.0, 10.0), (18.0, 10.0),
        (22.0, 10.0), (26.0, 10.0), (30.0, 10.0), (34.0, 10.0), (38.0, 10.0),
        (2.0, 32.0), (6.0, 32.0), (10.0, 32.0), (14.0, 32.0), (18.0, 32.0),
        (22.0, 32.0), (26.0, 32.0), (30.0, 32.0), (34.0, 32.0),
        (39.0, 5.0), (39.0, 9.0), (39.0, 13.0), (39.0, 17.0),
        (36.0, 26.4), (33.8, 29.0), (36.0, 31.6), (38.2, 29.0),
        (13.0, 15.0), (15.4, 15.0), (13.0, 19.0), (15.4, 19.0),
    ]
    vias.extend({"net": "GND", "x": x, "y": y, "size": .60, "drill": .30} for x, y in stitching)

    project = write_project(board, HERE)
    normalize_project_vias(project)
    sch = write_schematic(board, HERE)
    assign_3v3_power_flag(sch)
    pcb = write_pcb(board, HERE, pads, segments, vias)
    write_bom_cpl(board, HERE)
    net_names = sorted({pad["net"] for pad in pads if pad.get("net") and pad["net"] != "NC"})
    add_surface_ground_and_power_split(pcb, board, {name: i + 1 for i, name in enumerate(net_names)})
    write_design(board, pads, segments, vias, failures)

    # Preserve the honest state until native gates are run by the verification script.
    print(json.dumps({
        "schematic": str(sch), "pcb": str(pcb), "components": len(board.parts),
        "pads": len(pads), "segments": len(segments), "vias": len(vias),
        "router_failures": failures,
    }, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
