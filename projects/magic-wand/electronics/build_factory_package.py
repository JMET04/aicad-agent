#!/usr/bin/env python3
"""Build the reproducible two-board magic-wand electronics factory review pack.

The generated KiCad sources and CAM files are real, parseable engineering
artifacts.  They remain RELEASE_CANDIDATE_ONLY until native KiCad ERC/DRC and
manufacturer land-pattern overlays are closed; the builder never turns those
missing gates into a synthetic PASS.
"""

from __future__ import annotations

import csv
import hashlib
import heapq
import html
import json
import math
import os
import shutil
import sys
import textwrap
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from land_pattern_authority import (
    NINA_B3X2_EGP_PAD_CENTERS,
    NINA_B3X2_NUMBERED_PAD_CENTERS,
    configure_body_and_datum,
    physical_pads_for_part,
)


ROOT = Path(__file__).resolve().parent
GENERATOR_VERSION = "1.2.0"
GRID_MM = 0.25
AUTHORITY_FINAL_INVENTORY = ROOT / "evidence" / "authority" / "land-pattern-authority-inventory-final.json"
AUTHORITY_EVIDENCE_PREFIX = "electronics/evidence/authority/"
AUTHORITY_SOURCE_KINDS = {
    "manufacturerDrawing",
    "manufacturerDrawingExtract",
    "controlledKiCadLibrary",
    "designAuthority",
}
EDGE_MARGIN_MM = 0.50


def uid(*parts: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "aicad://magic-wand/" + "/".join(map(str, parts))))


def q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Pin:
    number: str
    name: str
    net: str
    electrical_type: str = "passive"

@dataclass(frozen=True)
class PhysicalPad:
    """One physical land; duplicate and empty KiCad pad numbers are valid."""

    physical_id: str
    number: str
    x: float
    y: float
    width: float
    height: float
    kind: str = "smd"
    shape: str = "roundrect"
    drill_width: float = 0.0
    drill_height: float = 0.0
    rotation: float = 0.0
    layers: tuple[str, ...] = ("F.Cu", "F.Paste", "F.Mask")
    role: str = "signal"
    net_override: str | None = None



@dataclass
class Part:
    ref: str
    value: str
    manufacturer: str
    mpn: str
    footprint: str
    x: float
    y: float
    width: float
    height: float
    pins: list[Pin]
    rotation: float = 0.0
    assembly: str = "SMT_TOP"
    package: str = "custom"
    dnp: bool = False
    notes: str = ""
    datasheet: str = ""
    lcsc: str = ""
    exact_land_pattern: bool = False
    pad_positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    physical_pads: list[PhysicalPad] = field(default_factory=list)
    land_pattern_authority: dict = field(default_factory=dict)
    fab_bounds: tuple[float, float, float, float] | None = None
    courtyard_bounds: tuple[float, float, float, float] | None = None
    body_height_mm: float = 0.0
    interface_datum: dict = field(default_factory=dict)
    exclude_from_bom: bool = False
    exclude_from_cpl: bool = False



@dataclass
class Board:
    name: str
    title: str
    width: float
    height: float
    keepouts: list[dict]
    parts: list[Part]
    high_current_nets: set[str]
    differential_pairs: list[tuple[str, str]]
    isolated_nets: set[str] = field(default_factory=set)
    load_voltage_max_v: float = 5.0
    plane_requirements: list[dict] = field(default_factory=list)
    mechanical_keepouts: list[dict] = field(default_factory=list)


def pins(mapping: dict[str, tuple[str, str, str] | tuple[str, str]]) -> list[Pin]:
    result: list[Pin] = []
    for number, spec in mapping.items():
        if len(spec) == 2:
            name, net = spec
            kind = "passive"
        else:
            name, net, kind = spec
        result.append(Pin(str(number), str(name), str(net), str(kind)))
    return result

def physical_pad_rows(pads: list[PhysicalPad]) -> list[dict]:
    """Canonical ordered physical-pad multiset used by authority and route gates."""
    return [
        {
            "physicalPadId": pad.physical_id,
            "padNumber": pad.number,
            "xMm": pad.x,
            "yMm": pad.y,
            "widthMm": pad.width,
            "heightMm": pad.height,
            "kind": pad.kind,
            "shape": pad.shape,
            "drillWidthMm": pad.drill_width,
            "drillHeightMm": pad.drill_height or pad.drill_width,
            "rotationDeg": pad.rotation,
            "layers": list(pad.layers),
            "role": pad.role,
            "netOverride": pad.net_override,
        }
        for pad in pads
    ]


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def physical_pad_fingerprint(pads: list[PhysicalPad]) -> str:
    return _canonical_sha(physical_pad_rows(pads))


def body_datum_payload(part: Part) -> dict:
    body = part.fab_bounds or (-part.width / 2, -part.height / 2, part.width / 2, part.height / 2)
    courtyard = part.courtyard_bounds or body
    return {
        "bodyBoundsLocalMm": list(body),
        "fabBoundsLocalMm": list(body),
        "courtyardBoundsLocalMm": list(courtyard),
        "bodyHeightMm": part.body_height_mm,
        "interfaceDatum": part.interface_datum,
    }


def body_datum_fingerprint(part: Part) -> str:
    return _canonical_sha(body_datum_payload(part))


def _validate_authority_evidence_ref(value: object) -> tuple[list[str], dict | None]:
    failures: list[str] = []
    if not isinstance(value, dict):
        return ["authority evidence must be an artifact reference"], None
    path = value.get("path")
    kind = value.get("kind")
    size = value.get("size")
    sha256 = value.get("sha256")
    if kind != "land_pattern_authority":
        failures.append("authority evidence kind must be land_pattern_authority")
    if not isinstance(path, str) or not path or chr(92) in path:
        return ["authority evidence path must be canonical POSIX"], None
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or not path.startswith("electronics/evidence/authority/"):
        return ["authority evidence path must stay under electronics/evidence/authority"], None
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        failures.append("authority evidence size must be positive")
    if not isinstance(sha256, str) or len(sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in sha256):
        failures.append("authority evidence sha256 must be exact")
    artifact = (ROOT.parent / relative).resolve()
    try:
        artifact.relative_to(ROOT.parent.resolve())
    except ValueError:
        failures.append("authority evidence escapes project root")
        return failures, None
    if artifact.is_symlink() or not artifact.is_file():
        failures.append("authority evidence is not a regular file")
        return failures, None
    payload = artifact.read_bytes()
    if isinstance(size, int) and len(payload) != size:
        failures.append("authority evidence size mismatch")
    if isinstance(sha256, str) and hashlib.sha256(payload).hexdigest().upper() != sha256.upper():
        failures.append("authority evidence sha256 mismatch")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        failures.append("authority evidence is not controlled JSON")
        return failures, None
    return failures, data


def _load_final_authority_rows() -> dict[tuple[str, str], dict]:
    """Load the immutable reviewed ledger; never synthesize authority at import."""
    if not AUTHORITY_FINAL_INVENTORY.is_file():
        return {}
    payload = AUTHORITY_FINAL_INVENTORY.read_bytes()
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid final land-pattern inventory: {exc}") from exc
    if document.get("schema") != "aicad_land_pattern_authority_inventory_v1" or document.get("status") != "CONTROLLED":
        raise RuntimeError("final land-pattern inventory is not a CONTROLLED v1 ledger")
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("final land-pattern inventory rows are missing")
    summary = document.get("summary", {})
    policy = document.get("policy", {})
    if len(rows) != 92 or summary.get("totalRefs") != 92 or summary.get("controlledRefs") != 92 or summary.get("releaseBlockedRefs") != 0:
        raise RuntimeError("final land-pattern inventory does not close 92/92 with zero blockers")
    if sum(1 for row in rows if isinstance(row, dict) and row.get("board") == "wand") != 46:
        raise RuntimeError("final land-pattern inventory must contain exactly 46 wand refs")
    if sum(1 for row in rows if isinstance(row, dict) and row.get("board") == "receiver") != 46:
        raise RuntimeError("final land-pattern inventory must contain exactly 46 receiver refs")
    if policy.get("packageNameWhitelistAccepted") is not False or policy.get("selfSignedGeometryAccepted") is not False:
        raise RuntimeError("final land-pattern inventory policy does not reject package/self-signed authority")
    evidence = {
        "path": AUTHORITY_FINAL_INVENTORY.relative_to(ROOT.parent).as_posix(),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
        "kind": "land_pattern_authority",
    }
    result: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("final land-pattern inventory contains a non-object row")
        board_name = row.get("board")
        ref = row.get("ref")
        authority = row.get("authority", row)
        if not isinstance(board_name, str) or not isinstance(ref, str) or not isinstance(authority, dict):
            raise RuntimeError("final land-pattern inventory row lacks board/ref/authority")
        key = (board_name, ref)
        if key in result:
            raise RuntimeError(f"duplicate final land-pattern authority row: {board_name}/{ref}")
        controlled = dict(authority)
        for metadata_key in ("board", "ref", "historical", "supersedes", "sourceDesignSha256"):
            controlled.pop(metadata_key, None)
        expected_authority_id = f"magic-wand:{board_name}:{ref}:{controlled.get('mpn')}"
        if controlled.get("authorityId") != expected_authority_id:
            raise RuntimeError(f"final authorityId is misbound: {board_name}/{ref}")
        if controlled.get("status") != "CONTROLLED":
            raise RuntimeError(f"final authority row is not CONTROLLED: {board_name}/{ref}")
        controlled["evidence"] = dict(evidence)
        result[key] = controlled
    return result


def _validate_source_artifact_ref(value: object, evidence_path: str) -> tuple[list[str], str | None]:
    failures: list[str] = []
    if not isinstance(value, dict):
        return ["sourceArtifact must be an artifact reference"], None
    path = value.get("path")
    kind = value.get("kind")
    size = value.get("size")
    sha256 = value.get("sha256")
    if kind not in AUTHORITY_SOURCE_KINDS:
        failures.append("sourceArtifact kind is not controlled")
    if not isinstance(path, str) or not path or chr(92) in path:
        return failures + ["sourceArtifact path must be canonical POSIX"], None
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or not path.startswith(AUTHORITY_EVIDENCE_PREFIX):
        return failures + ["sourceArtifact path must stay under electronics/evidence/authority"], None
    if path == evidence_path:
        failures.append("sourceArtifact cannot self-reference the authority evidence")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        failures.append("sourceArtifact size must be positive")
    if not isinstance(sha256, str) or len(sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in sha256):
        failures.append("sourceArtifact sha256 must be exact")
        sha256 = None
    artifact = (ROOT.parent / relative).resolve()
    try:
        artifact.relative_to(ROOT.parent.resolve())
    except ValueError:
        failures.append("sourceArtifact escapes project root")
        return failures, sha256
    if artifact.is_symlink() or not artifact.is_file():
        failures.append("sourceArtifact is not a regular file")
        return failures, sha256
    payload = artifact.read_bytes()
    if isinstance(size, int) and len(payload) != size:
        failures.append("sourceArtifact size mismatch")
    actual_sha = hashlib.sha256(payload).hexdigest().upper()
    if isinstance(sha256, str) and actual_sha != sha256.upper():
        failures.append("sourceArtifact sha256 mismatch")
    return failures, actual_sha


def _validate_external_source_closure(part: Part, authority: dict, evidence_path: str) -> list[str]:
    failures: list[str] = []
    sources = authority.get("sourceArtifacts")
    extraction = authority.get("extractionEvidence")
    if not isinstance(sources, list) or not sources:
        return [f"{part.ref}: sourceArtifacts must be a non-empty list"]
    source_hashes: set[str] = set()
    source_kinds: set[str] = set()
    for index, source in enumerate(sources):
        source_failures, actual_sha = _validate_source_artifact_ref(source, evidence_path)
        failures.extend(f"{part.ref}: sourceArtifacts[{index}] {failure}" for failure in source_failures)
        if isinstance(source, dict) and isinstance(source.get("kind"), str):
            source_kinds.add(source["kind"])
        if actual_sha:
            source_hashes.add(actual_sha.upper())
    authoritative_kinds = {"manufacturerDrawing", "manufacturerDrawingExtract", "controlledKiCadLibrary"}
    if not (source_kinds & authoritative_kinds):
        if not (part.assembly in {"NPTH", "BARE_PAD"} and source_kinds == {"designAuthority"}):
            failures.append(f"{part.ref}: no manufacturer/KiCad sourceArtifact")
    if not isinstance(extraction, list) or not extraction:
        return failures + [f"{part.ref}: extractionEvidence must be a non-empty list"]
    covered_fields: set[str] = set()
    for index, row in enumerate(extraction):
        prefix = f"{part.ref}: extractionEvidence[{index}]"
        if not isinstance(row, dict):
            failures.append(f"{prefix} must be an object")
            continue
        for field_name in ("documentNumber", "page", "section", "sourceArtifactSha256", "extractedFields"):
            if field_name not in row:
                failures.append(f"{prefix} missing {field_name}")
        source_sha = row.get("sourceArtifactSha256")
        if not isinstance(source_sha, str) or source_sha.upper() not in source_hashes:
            failures.append(f"{prefix} sourceArtifactSha256 is not bound to a verified source")
        fields = row.get("extractedFields")
        if not isinstance(fields, list) or not fields or any(not isinstance(item, str) or not item for item in fields):
            failures.append(f"{prefix} extractedFields must be non-empty strings")
        else:
            covered_fields.update(fields)
        if not isinstance(row.get("documentNumber"), str) or not row.get("documentNumber"):
            failures.append(f"{prefix} documentNumber is empty")
        if not isinstance(row.get("section"), str) or not row.get("section"):
            failures.append(f"{prefix} section is empty")
        if not isinstance(row.get("page"), (str, int)) or isinstance(row.get("page"), bool) or row.get("page") == "":
            failures.append(f"{prefix} page is empty")
    for field_name in ("physicalPads", "bodyDatum"):
        if field_name not in covered_fields:
            failures.append(f"{part.ref}: extractionEvidence does not cover {field_name}")
    return failures
def validate_land_pattern_authority(part: Part) -> list[str]:
    """Return every fail-closed authority defect for one fitted/design feature."""
    failures: list[str] = []
    authority = part.land_pattern_authority
    if not isinstance(authority, dict) or not authority:
        return [f"{part.ref}: missing per-reference land-pattern authority"]
    required = {
        "authorityId", "status", "manufacturer", "mpn", "sourceKind", "documentNumber",
        "revision", "sourceCoordinateFrame", "evidence", "physicalPads",
        "physicalPadFingerprint", "bodyDatum", "bodyDatumFingerprint", "sourceArtifacts", "extractionEvidence",
    }
    missing = sorted(required - set(authority))
    if missing:
        failures.append(f"{part.ref}: authority missing fields {missing}")
    if authority.get("status") != "CONTROLLED":
        failures.append(f"{part.ref}: authority is not CONTROLLED")
    if authority.get("manufacturer") != part.manufacturer or authority.get("mpn") != part.mpn:
        failures.append(f"{part.ref}: authority manufacturer/MPN mismatch")
    if authority.get("sourceKind") not in {
        "manufacturerDrawing", "controlledKiCadLibrary",
        "manufacturerDrawing+controlledKiCadLibrary", "designAuthority",
    }:
        failures.append(f"{part.ref}: unsupported authority sourceKind")
    if not isinstance(authority.get("documentNumber"), str) or not authority.get("documentNumber"):
        failures.append(f"{part.ref}: authority documentNumber is missing")
    if not isinstance(authority.get("revision"), str) or not authority.get("revision"):
        failures.append(f"{part.ref}: authority revision is missing")
    if not isinstance(authority.get("sourceCoordinateFrame"), dict) or not authority.get("sourceCoordinateFrame"):
        failures.append(f"{part.ref}: authority sourceCoordinateFrame is missing")
    if not part.physical_pads:
        failures.append(f"{part.ref}: explicit physical-pad multiset is empty")
    ids = [pad.physical_id for pad in part.physical_pads]
    if len(ids) != len(set(ids)):
        failures.append(f"{part.ref}: physicalPadId values are not unique")
    actual_pads = physical_pad_rows(part.physical_pads)
    if authority.get("physicalPads") != actual_pads:
        failures.append(f"{part.ref}: authority physical-pad multiset mismatch")
    if authority.get("physicalPadFingerprint") != physical_pad_fingerprint(part.physical_pads):
        failures.append(f"{part.ref}: physical-pad fingerprint mismatch")
    actual_body = body_datum_payload(part)
    if authority.get("bodyDatum") != actual_body:
        failures.append(f"{part.ref}: authority body/datum payload mismatch")
    if authority.get("bodyDatumFingerprint") != body_datum_fingerprint(part):
        failures.append(f"{part.ref}: body/datum fingerprint mismatch")
    evidence_failures, evidence_data = _validate_authority_evidence_ref(authority.get("evidence"))
    failures.extend(f"{part.ref}: {failure}" for failure in evidence_failures)
    evidence_path = authority.get("evidence", {}).get("path", "") if isinstance(authority.get("evidence"), dict) else ""
    failures.extend(_validate_external_source_closure(part, authority, evidence_path))
    if evidence_data is not None:
        if evidence_data.get("status") != "CONTROLLED":
            failures.append(f"{part.ref}: evidence status is not CONTROLLED")
        evidence_record: dict | None = None
        schema = evidence_data.get("schema")
        if schema == "aicad_land_pattern_authority_inventory_v1":
            rows = evidence_data.get("rows")
            if not isinstance(rows, list):
                failures.append(f"{part.ref}: evidence inventory rows missing")
            else:
                matches = [row for row in rows if isinstance(row, dict) and
                           (row.get("authority", row)).get("authorityId") == authority.get("authorityId")]
                if len(matches) != 1:
                    failures.append(f"{part.ref}: evidence inventory authorityId is not unique")
                else:
                    candidate = matches[0].get("authority", matches[0])
                    evidence_record = candidate if isinstance(candidate, dict) else None
        elif schema == "aicad_land_pattern_authority_v1":
            evidence_record = evidence_data
        else:
            failures.append(f"{part.ref}: evidence schema mismatch")
        if evidence_record is not None:
            for field_name in sorted(required - {"evidence"}):
                if evidence_record.get(field_name) != authority.get(field_name):
                    failures.append(f"{part.ref}: evidence {field_name} mismatch")
            if evidence_record.get("manufacturer") != part.manufacturer or evidence_record.get("mpn") != part.mpn:
                failures.append(f"{part.ref}: evidence manufacturer/MPN mismatch")
            if evidence_record.get("physicalPads") != actual_pads:
                failures.append(f"{part.ref}: evidence physical-pad multiset mismatch")
            if evidence_record.get("bodyDatum") != actual_body:
                failures.append(f"{part.ref}: evidence body/datum mismatch")
    logical_numbers = {pin.number for pin in part.pins}
    for pad in part.physical_pads:
        if pad.number and pad.number not in logical_numbers and pad.role not in {"mount", "locating", "hold_down"}:
            failures.append(f"{part.ref}: physical pad {pad.physical_id} lacks a logical pin")
    return failures


def require_land_pattern_authority(part: Part) -> None:
    failures = validate_land_pattern_authority(part)
    if failures:
        raise ValueError("; ".join(failures))



def two_pin(
    ref: str,
    value: str,
    manufacturer: str,
    mpn: str,
    net1: str,
    net2: str,
    x: float,
    y: float,
    *,
    package: str = "0402",
    assembly: str = "SMT_TOP",
    notes: str = "",
    dnp: bool = False,
) -> Part:
    size = {"0402": (1.0, 0.55), "0603": (1.6, 0.8), "0805": (2.0, 1.25), "SOD-123": (3.7, 1.8)}.get(package, (2.0, 1.0))
    prefix = (
        "R" if ref.startswith("R") else
        "C" if ref.startswith("C") else
        "D" if ref.startswith("D") else
        "F" if ref.startswith("F") else
        "L"
    )
    footprint = {
        "R": f"Resistor_SMD:R_{package}_HandSolder",
        "C": f"Capacitor_SMD:C_{package}_HandSolder",
        "D": f"Diode_SMD:D_{package}",
        "F": f"Fuse_SMD:Fuse_{package}_1608Metric",
        "L": "Inductor_SMD:L_4.0x4.0mm_H2.0mm",
    }[prefix]
    return Part(
        ref, value, manufacturer, mpn, footprint, x, y, size[0], size[1],
        pins({"1": ("1", net1), "2": ("2", net2)}), assembly=assembly,
        package=package, notes=notes, dnp=dnp,
    )


def testpoint(ref: str, net: str, x: float, y: float) -> Part:
    return Part(
        ref, net, "PCB FABRICATION", "BARE_PAD_D1.5", "MW_FACTORY:TestPoint_Pad_D1.5mm",
        x, y, 1.5, 1.5, pins({"1": (net, net)}), assembly="BARE_PAD", package="TESTPOINT_PAD_D1.5",
        notes="Production bare PCB probe feature; no fitted component",
        exclude_from_bom=True, exclude_from_cpl=True,
    )


def mounting_hole(ref: str, x: float, y: float, drill: float = 2.2) -> Part:
    return Part(
        ref, f"MountingHole_{drill:.1f}mm", "MECHANICAL", "NPTH", f"MountingHole:MountingHole_{drill:.1f}mm",
        x, y, drill + 1.0, drill + 1.0, [], assembly="NPTH", package="NPTH",
        notes="Non-plated mechanical hole", exclude_from_bom=True, exclude_from_cpl=True,
    )


def nina_pins(wand: bool) -> list[Pin]:
    used: dict[str, tuple[str, str, str]] = {
        "6": ("GND", "GND", "power_in"), "8": ("SWO", "SWO", "output"),
        "9": ("VCC_IO", "3V3", "power_in"), "10": ("VCC", "3V3", "power_in"),
        "11": ("SWDCLK", "SWDCLK", "input"), "12": ("GND", "GND", "power_in"),
        "13": ("ANT", "NC", "no_connect"), "14": ("GND", "GND", "power_in"),
        "15": ("SWDIO", "SWDIO", "bidirectional"), "19": ("RESET_N", "RESET_N", "input"),
        "26": ("GND", "GND", "power_in"), "30": ("GND", "GND", "power_in"),
        "31": ("VBUS", "USB_VBUS_5V", "input"), "53": ("GND", "GND", "power_in"),
        "54": ("USB_DP", "USB_DP_PROT", "bidirectional"), "55": ("USB_DM", "USB_DM_PROT", "bidirectional"),
    }
    if wand:
        used.update({
            "5": ("P0.24", "CHG_STAT1_N", "input"), "7": ("P0.25", "CHG_STAT2_N", "input"),
            "32": ("P0.11", "I2C_SCL", "bidirectional"), "33": ("P1.09", "I2C_SDA", "bidirectional"),
            "42": ("P0.26", "IMU_INT1", "input"), "43": ("P0.06", "ARM_N", "input"),
            "44": ("P0.27", "HAPTIC_EN", "output"),
        })
    else:
        used.update({
            "32": ("P0.11", "UART_TX_3V3", "output"), "33": ("P1.09", "UART_RX_3V3", "input"),
            "42": ("P0.26", "PWM_3V3", "output"), "43": ("P0.06", "OPTO_DRV", "output"),
            "44": ("P0.27", "LOAD_GATE_CTL", "output"), "46": ("P0.12", "PWR_GOOD_N", "input"),
        })
    result = []
    for index in range(1, 56):
        name, net, kind = used.get(str(index), (f"GPIO_UNUSED_{index}", "NC", "no_connect"))
        result.append(Pin(str(index), name, net, kind))
    result.append(Pin("EGP", "EXPOSED_GROUND", "GND", "power_in"))
    return result


def usb_c_pins() -> list[Pin]:
    mapping = {
        "A1": ("GND", "GND"), "A4": ("VBUS", "USB_VBUS_RAW"), "A5": ("CC1", "USB_CC1"),
        "A6": ("D+", "USB_DP_RAW"), "A7": ("D-", "USB_DM_RAW"), "A9": ("VBUS", "USB_VBUS_RAW"),
        "A12": ("GND", "GND"), "B1": ("GND", "GND"), "B4": ("VBUS", "USB_VBUS_RAW"),
        "B5": ("CC2", "USB_CC2"), "B6": ("D+", "USB_DP_RAW"), "B7": ("D-", "USB_DM_RAW"),
        "B9": ("VBUS", "USB_VBUS_RAW"), "B12": ("GND", "GND"),
        "A8": ("SBU1", "NC", "no_connect"), "B8": ("SBU2", "NC", "no_connect"),
        "SH": ("SHIELD", "USB_SHIELD", "passive"),
    }
    return pins(mapping)


def make_wand() -> Board:
    p: list[Part] = []
    p.append(Part("U1", "NINA-B302-00B-00", "u-blox", "NINA-B302-00B-00", "MW_FACTORY:NINA-B302_LGA55",
                  7.5, 10.5, 10.0, 15.0, nina_pins(True), package="LGA-55", notes="Internal PIFA faces board end",
                  datasheet="https://content.u-blox.com/sites/default/files/NINA-B3_DataSheet_UBX-17052099.pdf"))
    p.append(Part("U2", "LSM6DSV16XTR", "STMicroelectronics", "LSM6DSV16XTR", "Package_LGA:LGA-14_2.5x3mm_P0.5mm",
                  3.0, 25.0, 3.0, 2.5, pins({
                      "1": ("SDO/SA0", "GND", "input"), "2": ("SDx", "GND", "input"), "3": ("SCx", "GND", "input"),
                      "4": ("INT1", "IMU_INT1", "output"), "5": ("VDD_IO", "3V3", "power_in"), "6": ("GND", "GND", "power_in"),
                      "7": ("GND", "GND", "power_in"), "8": ("VDD", "3V3", "power_in"), "9": ("INT2", "TP_IMU_INT2", "output"),
                      "10": ("OCS_Aux", "3V3", "input"), "11": ("SDO_Aux", "3V3", "input"), "12": ("CS", "3V3", "input"),
                      "13": ("SCL", "I2C_SCL", "input"), "14": ("SDA", "I2C_SDA", "bidirectional")}), package="LGA-14",
                  datasheet="https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf"))
    p.append(Part("U5", "DRV2605LDGSR", "Texas Instruments", "DRV2605LDGSR", "Package_SO:MSOP-10_3x3mm_P0.5mm",
                  11.5, 25.0, 5.0, 3.0, pins({
                      "1": ("REG", "HAPTIC_REG", "output"), "2": ("SCL", "I2C_SCL", "input"), "3": ("SDA", "I2C_SDA", "bidirectional"),
                      "4": ("IN/TRIG", "GND", "input"), "5": ("EN", "HAPTIC_EN", "input"), "6": ("VDD/NC", "3V3", "power_in"),
                      "7": ("OUT+", "HAPTIC_P", "output"), "8": ("GND", "GND", "power_in"), "9": ("OUT-", "HAPTIC_N", "output"),
                      "10": ("VDD", "3V3", "power_in")}), package="VSSOP-10",
                  datasheet="https://www.ti.com/lit/ds/symlink/drv2605l.pdf"))
    p.append(Part("U4", "TPS63900DSKR", "Texas Instruments", "TPS63900DSKR", "Package_SON:Texas_DSK0010A_WSON-10-1EP_2.5x2.5mm_P0.5mm_EP1.2x2mm",
                  7.5, 30.0, 3.0, 3.0, pins({
                      "1": ("EN", "SYS_RAIL", "input"), "2": ("SEL", "GND", "input"), "3": ("CFG1", "R_CFG1_NODE", "input"),
                      "4": ("CFG2", "GND", "input"), "5": ("CFG3", "R_CFG3_NODE", "input"), "6": ("VOUT", "3V3", "power_out"),
                      "7": ("LX2", "LX2", "power_out"), "8": ("GND", "GND", "power_in"), "9": ("LX1", "LX1", "power_out"),
                      "10": ("VIN", "SYS_RAIL", "power_in"), "EP": ("THERMAL_PAD", "GND", "power_in")}), package="WSON-10-EP",
                  datasheet="https://www.ti.com/lit/ds/symlink/tps63900.pdf"))
    p.append(two_pin("L1", "2.2uH", "Coilcraft", "XFL4020-222MEC", "LX1", "LX2", 6.4, 34.0, package="L_4x4"))
    p.append(Part("U3", "BQ25185DLHR", "Texas Instruments", "BQ25185DLHR", "Package_SON:Texas_DLH0010A_WSON-10-1EP_2x2mm_P0.4mm_EP0.9x1.5mm",
                  7.5, 46.0, 3.0, 3.0, pins({
                      "1": ("SYS", "SYS_RAIL", "power_out"), "2": ("BAT", "BAT_POS", "bidirectional"), "3": ("STAT2", "CHG_STAT2_N", "open_collector"),
                      "4": ("/CE", "GND", "input"), "5": ("GND", "GND", "power_in"), "6": ("TS/MR", "BAT_NTC", "input"),
                      "7": ("ILIM/VSET", "R_ILIM_NODE", "input"), "8": ("ISET", "R_ISET_NODE", "input"),
                      "9": ("STAT1", "CHG_STAT1_N", "open_collector"), "10": ("IN", "USB_VBUS_5V", "power_in"),
                      "EP": ("THERMAL_PAD", "GND", "power_in")}), package="WSON-10-EP",
                  datasheet="https://www.ti.com/lit/ds/symlink/bq25185.pdf"))
    p.append(Part("J2", "SM03B-SRSS-TB", "JST", "SM03B-SRSS-TB(LF)(SN)", "Connector_JST:JST_SH_SM03B-SRSS-TB_1x03-1MP_P1.00mm_Horizontal",
                  3.0, 57.0, 5.0, 4.0, pins({"1": ("BAT+", "BAT_POS"), "2": ("NTC", "BAT_NTC"), "3": ("GND", "GND")}), package="JST-SH-3"))
    p.append(Part("SW1", "PRESS_TO_ARM", "ALPS Alpine", "SKQGAFE010", "Button_Switch_SMD:SW_SPST_SKQG_WithoutStem",
                  7.5, 63.0, 5.2, 5.2, pins({"1": ("ARM_SWITCH", "ARM_SW"), "2": ("GND", "GND")}), rotation=90.0, package="SKQG"))
    p.append(Part("J3", "SM02B-SRSS-TB", "JST", "SM02B-SRSS-TB(LF)(SN)", "Connector_JST:JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal",
                  3.0, 72.0, 4.0, 4.0, pins({"1": ("HAPTIC+", "HAPTIC_P"), "2": ("HAPTIC-", "HAPTIC_N")}), package="JST-SH-2"))
    p.append(Part("U6", "USBLC6-2SC6", "STMicroelectronics", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
                  6.5, 38.0, 3.0, 3.0, pins({
                      "1": ("I/O1_RAW", "USB_DP_RAW"), "2": ("GND", "GND"), "3": ("I/O2_RAW", "USB_DM_RAW"),
                      "4": ("I/O2_PROT", "USB_DM_PROT"), "5": ("VBUS", "USB_VBUS_5V"), "6": ("I/O1_PROT", "USB_DP_PROT")}), package="SOT-23-6",
                  datasheet="https://www.st.com/resource/en/datasheet/usblc6-2.pdf"))
    p.append(two_pin("F1", "500mA PTC", "Bourns", "MF-FSMF050X-2", "USB_VBUS_RAW", "USB_VBUS_5V", 3.0, 38.0, package="0603"))
    p.append(Part("J1", "USB-C-16P", "JAE", "DX07S016JA1R1500", "Connector_USB:USB_C_Receptacle_USB2.0_16P",
                  12.5, 38.0, 9.0, 7.0, usb_c_pins(), rotation=90.0, package="USB-C-16P", notes="Intentional 2.0 mm board-edge overhang; mechanical radial opening datum"))

    passive_specs = [
        ("R_CC1", "5.1k", "Yageo", "RC0402FR-075K1L", "USB_CC1", "GND", 10.5, 32.5),
        ("R_CC2", "5.1k", "Yageo", "RC0402FR-075K1L", "USB_CC2", "GND", 10.8, 43.0),
        ("R_I2C_SCL", "4.7k", "Yageo", "RC0402FR-074K7L", "3V3", "I2C_SCL", 2.2, 29.0),
        ("R_I2C_SDA", "4.7k", "Yageo", "RC0402FR-074K7L", "3V3", "I2C_SDA", 12.8, 29.0),
        ("R_ARM", "100k", "Yageo", "RC0402FR-07100KL", "3V3", "ARM_N", 9.5, 60.0),
        ("R_ARM_SER", "1k", "Yageo", "RC0402FR-071KL", "ARM_SW", "ARM_N", 12.5, 59.0),
        ("R_HAPTIC_EN", "100k", "Yageo", "RC0402FR-07100KL", "HAPTIC_EN", "GND", 11.0, 20.5),
        ("R_STAT1", "10k", "Yageo", "RC0402FR-0710KL", "3V3", "CHG_STAT1_N", 2.2, 44.0),
        ("R_STAT2", "10k", "Yageo", "RC0402FR-0710KL", "3V3", "CHG_STAT2_N", 12.8, 44.0),
        ("R_ISET", "1.00k", "Yageo", "RC0402FR-071KL", "R_ISET_NODE", "GND", 2.2, 48.0),
        ("R_ILIM", "18.0k", "Yageo", "RC0402FR-0718KL", "R_ILIM_NODE", "GND", 12.8, 48.0),
        ("R_CFG1", "36.5k", "Yageo", "RC0402FR-0736K5L", "R_CFG1_NODE", "GND", 2.2, 32.0),
        ("R_CFG2", "0R", "Yageo", "RC0402JR-070RL", "GND", "GND", 7.5, 32.0),
        ("R_CFG3", "16.2k", "Yageo", "RC0402FR-0716K2L", "R_CFG3_NODE", "GND", 12.8, 32.0),
        ("C_USB", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "USB_VBUS_5V", "GND", 7.0, 41.5),
        ("C_CHG_IN", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "USB_VBUS_5V", "GND", 4.5, 43.0),
        ("C_SYS", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "SYS_RAIL", "GND", 5.0, 49.0),
        ("C_BAT", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "BAT_POS", "GND", 10.0, 49.0),
        ("C_BUCK_IN", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "SYS_RAIL", "GND", 3.0, 34.5),
        ("C_BUCK_OUT", "22uF 6.3V X5R", "Murata", "GRM21BR60J226ME39L", "3V3", "GND", 12.0, 27.8),
        ("C_IMU_VDD", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "3V3", "GND", 2.2, 22.0),
        ("C_IMU_IO", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "3V3", "GND", 4.8, 22.0),
        ("C_HAPTIC_REG", "1uF 10V X7R", "Murata", "GRM155R71A105KE15D", "HAPTIC_REG", "GND", 10.2, 22.0),
        ("C_HAPTIC_VDD", "1uF 10V X7R", "Murata", "GRM155R71A105KE15D", "3V3", "GND", 12.8, 22.0),
    ]
    for spec in passive_specs:
        package = "0805" if spec[0] in {"C_USB", "C_CHG_IN", "C_SYS", "C_BAT", "C_BUCK_IN", "C_BUCK_OUT"} else "0402"
        p.append(two_pin(*spec, package=package))
    for ref, net, x, y in [
        ("TP3", "SWDIO", 2.0, 51.5), ("TP4", "SWDCLK", 4.5, 51.5),
        ("TP5", "RESET_N", 7.0, 51.5), ("TP6", "SWO", 9.5, 51.5),
        ("TP1", "3V3", 12.5, 51.5), ("TP2", "GND", 2.0, 54.5),
        ("TP7", "TP_IMU_INT2", 5.0, 54.5), ("TP8", "SYS_RAIL", 8.0, 54.5),
    ]:
        p.append(testpoint(ref, net, x, y))
    p.extend([mounting_hole("H1", 7.5, 19.5, 2.4), mounting_hole("H2", 7.5, 77.0, 2.4)])
    return Board(
        "wand", "Magic Wand Controller PCB", 15.0, 80.0,
        [], p,
        {"USB_VBUS_RAW", "USB_VBUS_5V", "SYS_RAIL", "BAT_POS", "LX1", "LX2", "HAPTIC_P", "HAPTIC_N"},
        [("USB_DP_RAW", "USB_DM_RAW"), ("USB_DP_PROT", "USB_DM_PROT")], load_voltage_max_v=5.0,
        plane_requirements=[{
            "name": "NINA_B302_FULL_GROUND_UNDER_MODULE", "ref": "U1", "net": "GND", "layers": ["In1.Cu"],
            "polygon": [[2.5, 3.0], [12.5, 3.0], [12.5, 18.0], [2.5, 18.0]],
            "fullGround": True, "viaStitchingRequired": True,
        }],
        mechanical_keepouts=[{
            "name": "NINA_B302_ANTENNA_MECHANICAL_KEEP_OUT", "ref": "U1", "kind": "component_metal_enclosure",
            "polygonMm": [[0.0, 0.0], [15.0, 0.0], [15.0, 18.8], [0.0, 18.8]],
            "antennaDirection": "source -Y / outward", "minMetalOrLargeComponentClearanceMm": 10.0,
            "minEnclosureClearanceMm": 5.0, "allowedRefs": ["U1", "H1_NONMETALLIC_ONLY"],
        }],
    )


def make_receiver() -> Board:
    p: list[Part] = []
    p.append(Part("U1", "NINA-B302-00B-00", "u-blox", "NINA-B302-00B-00", "MW_FACTORY:NINA-B302_LGA55",
                  42.25, 11.0, 10.0, 15.0, nina_pins(False), rotation=270.0, package="LGA-55", notes="Internal PIFA faces right nonconductive enclosure edge",
                  datasheet="https://content.u-blox.com/sites/default/files/NINA-B3_DataSheet_UBX-17052099.pdf"))
    p.append(Part("J1", "USB-C-16P", "JAE", "DX07S016JA1R1500", "Connector_USB:USB_C_Receptacle_USB2.0_16P",
                  3.0, 19.0, 7.0, 9.0, usb_c_pins(), rotation=270.0, package="USB-C-16P", notes="USB power/service only"))
    p.append(Part("U6", "USBLC6-2SC6", "STMicroelectronics", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
                  10.0, 19.0, 3.0, 3.0, pins({"1": ("I/O1_RAW", "USB_DP_RAW"), "2": ("GND", "GND"), "3": ("I/O2_RAW", "USB_DM_RAW"),
                                                     "4": ("I/O2_PROT", "USB_DM_PROT"), "5": ("VBUS", "USB_VBUS_5V"), "6": ("I/O1_PROT", "USB_DP_PROT")}), package="SOT-23-6"))
    p.append(two_pin("F1", "500mA PTC", "Bourns", "MF-FSMF050X-2", "USB_VBUS_RAW", "USB_VBUS_5V", 10.0, 14.0, package="0603"))
    p.append(Part("U2", "TPS62162DSGR", "Texas Instruments", "TPS62162DSGR", "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm",
                  15.0, 14.0, 2.2, 2.2, pins({
                      "1": ("PGND", "GND", "power_in"), "2": ("VIN", "USB_VBUS_5V", "power_in"), "3": ("EN", "USB_VBUS_5V", "input"),
                      "4": ("AGND", "GND", "power_in"), "5": ("FB", "GND", "input"), "6": ("VOS", "3V3", "input"),
                      "7": ("SW", "BUCK_SW", "power_out"), "8": ("PG", "PWR_GOOD_N", "open_collector"), "EP": ("THERMAL_PAD", "GND", "power_in")}),
                  package="WSON-8-EP", datasheet="https://www.ti.com/product/TPS62162"))
    p.append(two_pin("L1", "2.2uH", "Murata", "LQH32PN2R2NN0L", "BUCK_SW", "3V3", 19.25, 14.0, package="L_4x4"))
    translator_pins_ab = pins({"1": ("VCCA", "3V3", "power_in"), "2": ("A1", "UART_TX_3V3", "input"), "3": ("A2", "PWM_3V3", "input"),
                                "4": ("GND", "GND", "power_in"), "5": ("DIR", "3V3", "input"), "6": ("B2", "PWM_XLAT", "output"),
                                "7": ("B1", "UART_TX_XLAT", "output"), "8": ("VCCB", "VREF_IO", "power_in")})
    translator_pins_ba = pins({"1": ("VCCA", "3V3", "power_in"), "2": ("A1", "UART_RX_3V3", "output"), "3": ("A2", "NC", "no_connect"),
                                "4": ("GND", "GND", "power_in"), "5": ("DIR", "GND", "input"), "6": ("B2", "GND", "input"),
                                "7": ("B1", "UART_RX_VREF", "input"), "8": ("VCCB", "VREF_IO", "power_in")})
    p.append(Part("U3", "SN74LVC2T45DCUR", "Texas Instruments", "SN74LVC2T45DCUR", "Package_SO:VSSOP-8_2.3x2mm_P0.5mm",
                  25.0, 16.0, 2.3, 2.0, translator_pins_ab, package="VSSOP-8"))
    p.append(Part("U4", "SN74LVC2T45DCUR", "Texas Instruments", "SN74LVC2T45DCUR", "Package_SO:VSSOP-8_2.3x2mm_P0.5mm",
                  25.0, 24.0, 2.3, 2.0, translator_pins_ba, package="VSSOP-8"))
    p.append(Part("J2", "DF13A-5P-1.25H(51)", "Hirose Electric", "DF13A-5P-1.25H(51)",
                  "MW_FACTORY:Hirose_DF13A-5P-1.25H_1x05_P1.25mm_Horizontal",
                  25.0, 39.5, 10.9, 5.0, pins({
                      "1": ("GND", "GND"), "2": ("VREF_IO", "VREF_IO"),
                      "3": ("UART_TX", "UART_TX_VREF"), "4": ("UART_RX", "UART_RX_VREF"),
                      "5": ("PWM_AUX", "PWM_VREF"),
                      "MP1": ("MOUNT", "NC", "no_connect"), "MP2": ("MOUNT", "NC", "no_connect"),
                  }), package="DF13A-5P-1.25H",
                  notes="Current gold-plated 5-position right-angle SMT header; mates DF13-5S-1.25C with DF13-2630SCFA(05) AWG26-30 contacts; mating direction +Y toward receiver board edge",
                  datasheet="https://www.hirose.com/en/product/p/CL0536-0304-6-51"))
    p.append(Part("U5", "TLP291(SE)", "Toshiba", "TLP291(GB-TP,SE)", "Package_SO:SO-4_4.4x3.6mm_P2.54mm",
                  35.0, 31.0, 4.4, 3.6, pins({"1": ("ANODE", "OPTO_ANODE", "input"), "2": ("CATHODE", "GND", "power_in"),
                                                       "3": ("EMITTER", "ISO_OC_EMIT", "open_emitter"), "4": ("COLLECTOR", "ISO_OC_COL", "open_collector")}),
                  package="SO-4", notes="Low-voltage signal isolation only"))
    p.append(Part("J3", "ISO_OC_2P", "TE Connectivity", "282834-2",
                  "TerminalBlock_TE-Connectivity:TerminalBlock_TE_282834-2_1x02_P2.54mm_Horizontal",
                  47.0, 32.0, 5.54, 6.50, pins({"1": ("ISO_OC_COL", "ISO_OC_COL"), "2": ("ISO_OC_EMIT", "ISO_OC_EMIT")}),
                  rotation=90.0, assembly="THT", package="TB-2.54-2",
                  notes="3.3-24V target, 10mA max; side wire entry faces receiver +X/right edge; no mains",
                  datasheet="https://www.te.com/en/product-282834-2.html"))
    p.append(Part("Q1", "CSD17313Q2", "Texas Instruments", "CSD17313Q2", "Package_SON:Texas_DQK",
                  15.0, 31.0, 2.0, 2.0, pins({
                      "1": ("DRAIN", "LOAD_DRAIN", "power_out"), "2": ("DRAIN", "LOAD_DRAIN", "power_out"), "3": ("GATE", "LOAD_GATE", "input"), "4": ("SOURCE", "GND", "power_in"),
                      "5": ("DRAIN", "LOAD_DRAIN", "power_out"), "6": ("DRAIN", "LOAD_DRAIN", "power_out"), "7": ("SOURCE", "GND", "power_in"), "8": ("DRAIN", "LOAD_DRAIN", "power_out"),
                  }), package="Texas_DQK", datasheet="https://www.ti.com/lit/ds/symlink/csd17313q2.pdf"))
    p.append(Part("J4", "LOAD_OUT_3P", "TE Connectivity", "282834-3",
                  "TerminalBlock_TE-Connectivity:TerminalBlock_TE_282834-3_1x03_P2.54mm_Horizontal",
                  5.0, 38.5, 8.08, 6.50, pins({"1": ("LOAD_SUPPLY", "LOAD_SUPPLY_5_12V"), "2": ("LOAD_DRAIN", "LOAD_DRAIN"), "3": ("LOAD_GND", "GND")}),
                  assembly="THT", package="TB-2.54-3",
                  notes="5-12V SELV only; 1A continuous EVT limit; side wire entry faces source +Y / mechanical bottom edge",
                  datasheet="https://www.te.com/en/product-282834-3.html"))
    p.append(two_pin("D1", "SS24 flyback", "Diodes Inc.", "SS24-13-F", "LOAD_DRAIN", "LOAD_SUPPLY_5_12V", 9.0, 32.0, package="SMB"))
    p.append(two_pin("D2", "SMBJ15A TVS", "Littelfuse", "SMBJ15A", "GND", "LOAD_SUPPLY_5_12V", 13.0, 27.0, package="SMB", dnp=True,
                     notes="DNP until actual load transient review"))
    passive_specs = [
        ("R_CC1", "5.1k", "Yageo", "RC0402FR-075K1L", "USB_CC1", "GND", 4.0, 13.0),
        ("R_CC2", "5.1k", "Yageo", "RC0402FR-075K1L", "USB_CC2", "GND", 4.0, 25.0),
        ("R_PG", "10k", "Yageo", "RC0402FR-0710KL", "3V3", "PWR_GOOD_N", 17.0, 18.0),
        ("R_TX", "33R", "Yageo", "RC0402FR-0733RL", "UART_TX_XLAT", "UART_TX_VREF", 29.0, 16.0),
        ("R_PWM", "33R", "Yageo", "RC0402FR-0733RL", "PWM_XLAT", "PWM_VREF", 29.0, 19.0),
        ("R_TX_PD", "100k", "Yageo", "RC0402FR-07100KL", "UART_TX_3V3", "GND", 21.0, 18.0),
        ("R_PWM_PD", "100k", "Yageo", "RC0402FR-07100KL", "PWM_3V3", "GND", 21.0, 21.0),
        ("R_RX_PD", "100k", "Yageo", "RC0402FR-07100KL", "UART_RX_VREF", "GND", 29.0, 24.0),
        ("R_OPTO", "430R", "Yageo", "RC0402FR-07430RL", "OPTO_DRV", "OPTO_ANODE", 29.5, 31.0),
        ("R_GATE", "33R", "Yageo", "RC0402FR-0733RL", "LOAD_GATE_CTL", "LOAD_GATE", 19.0, 31.0),
        ("R_GATE_PD", "100k", "Yageo", "RC0402FR-07100KL", "LOAD_GATE", "GND", 17.0, 34.0),
        ("C_USB", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "USB_VBUS_5V", "GND", 10.0, 12.0),
        ("C_BUCK_IN", "10uF 10V X5R", "Murata", "GRM21BR61A106KE19L", "USB_VBUS_5V", "GND", 13.0, 10.0),
        ("C_BUCK_OUT", "22uF 6.3V X5R", "Murata", "GRM21BR60J226ME39L", "3V3", "GND", 21.0, 11.0),
        ("C_U1", "10uF 6.3V X5R", "Murata", "GRM21BR60J106KE19L", "3V3", "GND", 37.0, 18.0),
        ("C_U3A", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "3V3", "GND", 24.0, 13.0),
        ("C_U3B", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "VREF_IO", "GND", 27.0, 13.0),
        ("C_U4A", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "3V3", "GND", 23.0, 27.0),
        ("C_U4B", "100nF 16V X7R", "Murata", "GRM155R71C104KA88D", "VREF_IO", "GND", 27.0, 27.0),
    ]
    for spec in passive_specs:
        package = "0805" if spec[0] in {"C_USB", "C_BUCK_IN", "C_BUCK_OUT", "C_U1"} else "0402"
        p.append(two_pin(*spec, package=package))
    for ref, net, x, y in [
        ("TP1", "3V3", 13.0, 22.0), ("TP2", "GND", 17.0, 22.0), ("TP3", "SWDIO", 34.0, 20.0),
        ("TP4", "SWDCLK", 39.0, 20.5), ("TP5", "RESET_N", 42.0, 20.5), ("TP6", "SWO", 45.0, 20.5),
        ("TP7", "VREF_IO", 31.0, 26.0), ("TP8", "LOAD_DRAIN", 21.0, 34.0),
    ]:
        p.append(testpoint(ref, net, x, y))
    p.extend([mounting_hole("H1", 3.0, 3.0, 2.4), mounting_hole("H2", 47.0, 3.0, 2.4), mounting_hole("H3", 15.0, 39.0, 2.4), mounting_hole("H4", 37.0, 39.0, 2.4)])
    return Board(
        "receiver", "Magic Wand Low-Voltage Receiver PCB", 50.0, 42.0,
        [
            {"name": "LOW_VOLTAGE_ISOLATION_MOAT", "x1": 38.0, "y1": 23.0, "x2": 40.5, "y2": 40.5,
             "layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], "allow_refs": []},
        ], p,
        {"USB_VBUS_RAW", "USB_VBUS_5V", "BUCK_SW", "LOAD_SUPPLY_5_12V", "LOAD_DRAIN", "GND"},
        [("USB_DP_RAW", "USB_DM_RAW"), ("USB_DP_PROT", "USB_DM_PROT")],
        isolated_nets={"ISO_OC_COL", "ISO_OC_EMIT"}, load_voltage_max_v=12.0,
        plane_requirements=[{
            "name": "NINA_B302_FULL_GROUND_UNDER_MODULE", "ref": "U1", "net": "GND", "layers": ["In1.Cu"],
            "polygon": [[34.75, 6.0], [49.75, 6.0], [49.75, 16.0], [34.75, 16.0]],
            "fullGround": True, "viaStitchingRequired": True,
        }],
        mechanical_keepouts=[{
            "name": "NINA_B302_ANTENNA_MECHANICAL_KEEP_OUT", "ref": "U1", "kind": "component_metal_enclosure",
            "polygonMm": [[33.9, 0.0], [50.0, 0.0], [50.0, 22.0], [33.9, 22.0]],
            "antennaDirection": "source +X / outward", "minMetalOrLargeComponentClearanceMm": 10.0,
            "minEnclosureClearanceMm": 5.0, "allowedRefs": ["U1"],
        }],
    )


def rotate_point(dx: float, dy: float, angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    return dx * math.cos(rad) + dy * math.sin(rad), -dx * math.sin(rad) + dy * math.cos(rad)




def _dual_row(numbers_left: list[str], numbers_right: list[str], x: float, pitch: float) -> dict[str, tuple[float, float]]:
    y0 = -pitch * (max(len(numbers_left), len(numbers_right)) - 1) / 2
    result = {number: (-x, y0 + index * pitch) for index, number in enumerate(numbers_left)}
    result.update({number: (x, y0 + index * pitch) for index, number in enumerate(reversed(numbers_right))})
    return result


def derive_pad_positions(part: Part) -> dict[str, tuple[float, float]]:
    if part.pad_positions:
        return dict(part.pad_positions)
    if part.assembly == "NPTH":
        return {"NPTH": (0.0, 0.0)}
    count = len(part.pins)
    if not count:
        return {}
    numbers = [pin.number for pin in part.pins]
    if part.package == "LGA-55":
        positions = dict(NINA_B3X2_NUMBERED_PAD_CENTERS)
        positions.update({
            f"EGP{index:02d}": center
            for index, center in enumerate(NINA_B3X2_EGP_PAD_CENTERS, start=1)
        })
        return positions
    if part.package == "LGA-14":
        return _dual_row([str(i) for i in range(1, 8)], [str(i) for i in range(8, 15)], 1.30, 0.50)
    if part.package == "WSON-10-EP":
        result = _dual_row([str(i) for i in range(1, 6)], [str(i) for i in range(6, 11)], 1.35, 0.50)
        result["EP"] = (0.0, 0.0)
        return result
    if part.package == "WSON-8-EP":
        result = _dual_row([str(i) for i in range(1, 5)], [str(i) for i in range(5, 9)], 1.15, 0.50)
        result["EP"] = (0.0, 0.0)
        return result
    if part.package == "VSSOP-10":
        return _dual_row([str(i) for i in range(1, 6)], [str(i) for i in range(6, 11)], 2.15, 0.50)
    if part.package == "VSSOP-8":
        return _dual_row([str(i) for i in range(1, 5)], [str(i) for i in range(5, 9)], 1.90, 0.50)
    if part.package == "SO-4":
        return {"1": (-3.05, -1.27), "2": (-3.05, 1.27), "3": (3.05, 1.27), "4": (3.05, -1.27)}
    if part.package == "SON-2x2":
        return {"1": (-1.10, -0.65), "2": (-1.10, 0.65), "3": (1.10, 0.0)}
    if part.package == "SOT-23-6":
        return {"1": (-1.25, -0.95), "2": (-1.25, 0.0), "3": (-1.25, 0.95),
                "4": (1.25, 0.95), "5": (1.25, 0.0), "6": (1.25, -0.95)}
    if part.package == "USB-C-16P":
        order = ["A1", "B12", "A4", "B9", "A5", "B5", "A6", "B6", "A7", "B7", "A9", "B4", "A12", "B1"]
        positions = {number: (-3.25 + index * 0.50, -3.20) for index, number in enumerate(order)}
        positions["SH"] = (-4.00, 0.75)
        return positions
    if part.package == "DF13A-5P-1.25H":
        # Hirose drawing EDCX-162444-51-08 / document 0000995752, page 1.
        # Origin is the 10.9 x 5.0 mm body centre.  The signal row is 3.10 mm
        # behind it; the two recommended reinforcement-pad centres are 3.30 mm
        # toward the mating face from the signal row and 9.70 mm apart.
        result = {str(index + 1): (-2.50 + index * 1.25, -3.10) for index in range(5)}
        result.update({"MP1": (-4.85, 0.20), "MP2": (4.85, 0.20)})
        return result
    if part.package in {"JST-SH-3", "JST-SH-2"}:
        pitch = 1.0
        start = -pitch * (count - 1) / 2
        return {pin.number: (start + index * pitch, 0.0) for index, pin in enumerate(part.pins)}
    if part.assembly in {"THT", "TESTPOINT"}:
        if count == 1:
            return {part.pins[0].number: (0.0, 0.0)}
        pitch = 2.54 if "2.54" in part.package or part.package.startswith("TB") else 1.27
        start = -pitch * (count - 1) / 2
        return {pin.number: (start + index * pitch, 0.0) for index, pin in enumerate(part.pins)}
    if count == 2:
        half_pitch = {"0402": 0.35, "0603": 0.55, "0805": 0.70, "SOD-123": 1.30, "L_4x4": 1.45}.get(part.package, max(0.35, part.width / 2 - 0.2))
        return {part.pins[0].number: (-half_pitch, 0.0), part.pins[1].number: (half_pitch, 0.0)}
    split = math.ceil(count / 2)
    return _dual_row(numbers[:split], numbers[split:], max(0.4, part.width / 2),
                     max(0.50, part.height / (max(1, split - 1))))


def pad_geometry(part: Part, number: str) -> tuple[float, float, float, str]:
    if part.assembly in {"THT", "TESTPOINT"}:
        if part.package.startswith("TB-2.54"):
            # TE drawing 282834 rev D, recommended PCB layout: 2.10 mm pad,
            # finished hole diameter 1.10 +0.10/-0.00 mm.
            return (2.10, 2.10, 1.10, "tht")
        return ((1.8, 1.8, 1.0, "tht") if part.assembly == "THT" else (2.0, 2.0, 1.1, "tht"))
    if part.package == "LGA-55":
        if number == "EGP":
            return (0.70, 0.70, 0.0, "smd")
        if number in ({str(i) for i in range(1, 11)} | {str(i) for i in range(16, 26)}):
            width, height = 1.15, 0.70
        elif number in ({str(i) for i in range(11, 16)} | {str(i) for i in range(26, 31)}):
            width, height = 0.70, 1.15
        else:
            return (0.70, 0.70, 0.0, "smd")
        return ((height, width, 0.0, "smd") if int(round(part.rotation)) % 180 else (width, height, 0.0, "smd"))
    if part.package == "LGA-14":
        return (0.75, 0.30, 0.0, "smd")
    if part.package == "WSON-10-EP":
        return ((1.40, 1.45, 0.0, "smd") if number == "EP" else (0.80, 0.30, 0.0, "smd"))
    if part.package == "WSON-8-EP":
        return ((0.90, 1.30, 0.0, "smd") if number == "EP" else (0.80, 0.30, 0.0, "smd"))
    if part.package in {"VSSOP-10", "VSSOP-8"}:
        return (1.20, 0.30, 0.0, "smd")
    if part.package == "SO-4":
        return (1.60, 0.70, 0.0, "smd")
    if part.package == "SON-2x2":
        return ((0.70, 0.55, 0.0, "smd") if number in {"1", "2"} else (1.15, 1.35, 0.0, "smd"))
    if part.package == "SOT-23-6":
        return (1.05, 0.60, 0.0, "smd")
    if part.package == "USB-C-16P":
        return ((1.00, 1.60, 0.0, "smd") if number.startswith("SH") else (1.00, 0.25, 0.0, "smd"))
    if part.package == "DF13A-5P-1.25H":
        return ((1.60, 2.20, 0.0, "smd") if number.startswith("MP") else
                (0.70, 1.80, 0.0, "smd"))
    if part.package.startswith("JST-SH"):
        return (0.60, 1.35, 0.0, "smd")
    if len(part.pins) == 2:
        sizes = {"0402": (0.40, 0.50), "0603": (0.60, 0.75), "0805": (0.70, 1.10), "SOD-123": (1.20, 1.40), "L_4x4": (1.40, 2.20)}
        width, height = sizes.get(part.package, (max(0.50, part.width * 0.35), max(0.45, part.height * 0.65)))
        return (width, height, 0.0, "smd")
    return (0.65, 0.35, 0.0, "smd")


def absolute_pads(board: Board, *, require_controlled: bool = True) -> list[dict]:
    pads: list[dict] = []
    for part in board.parts:
        by_number = {pin.number: pin for pin in part.pins}
        if require_controlled:
            require_land_pattern_authority(part)
        if part.physical_pads:
            for spec in part.physical_pads:
                rdx, rdy = rotate_point(spec.x, spec.y, part.rotation)
                pin = by_number.get(spec.number)
                net = spec.net_override if spec.net_override is not None else (pin.net if pin else "")
                pads.append({
                    "physical_id": spec.physical_id,
                    "ref": part.ref,
                    "number": spec.number,
                    "net": net,
                    "x": round(part.x + rdx, 4),
                    "y": round(part.y + rdy, 4),
                    "local_x": spec.x,
                    "local_y": spec.y,
                    "kind": spec.kind,
                    "shape": spec.shape,
                    "width": spec.width,
                    "height": spec.height,
                    "drill": spec.drill_width,
                    "drill_width": spec.drill_width,
                    "drill_height": spec.drill_height or spec.drill_width,
                    "rotation": (part.rotation + spec.rotation) % 360,
                    "local_rotation": spec.rotation,
                    "layers": list(spec.layers),
                    "role": spec.role,
                    "part": part,
                    "pin": pin,
                })
            continue
        rel = derive_pad_positions(part)
        if part.assembly == "NPTH":
            pads.append({"physical_id": f"{part.ref}:NPTH", "ref": part.ref, "number": "", "net": "",
                         "x": part.x, "y": part.y, "kind": "npth", "width": part.width - 1.0,
                         "height": part.height - 1.0, "drill": part.width - 1.0,
                         "drill_width": part.width - 1.0, "drill_height": part.height - 1.0,
                         "shape": "circle", "rotation": part.rotation, "local_rotation": 0.0,
                         "layers": ["*.Cu", "*.Mask"], "role": "locating", "part": part})
            continue
        for number, (dx, dy) in rel.items():
            rdx, rdy = rotate_point(dx, dy, part.rotation)
            pin = by_number[number]
            pad_w, pad_h, drill, kind = pad_geometry(part, number)
            pads.append({"physical_id": f"{part.ref}:{number}", "ref": part.ref, "number": number,
                         "net": pin.net, "x": round(part.x + rdx, 4), "y": round(part.y + rdy, 4),
                         "kind": kind, "width": pad_w, "height": pad_h, "drill": drill,
                         "drill_width": drill, "drill_height": drill,
                         "shape": "circle" if kind in {"tht", "npth"} else "roundrect",
                         "rotation": part.rotation, "local_rotation": 0.0,
                         "layers": ["*.Cu", "*.Mask"] if kind in {"tht", "npth"} else ["F.Cu", "F.Paste", "F.Mask"],
                         "role": "signal", "part": part, "pin": pin})
    return pads




def net_width(board: Board, net: str) -> float:
    if net in {"LOAD_SUPPLY_5_12V", "LOAD_DRAIN"}:
        return 1.0
    if net in board.high_current_nets:
        return 0.25
    if net.startswith("USB_D"):
        return 0.20
    return 0.20


def inside_keepout(board: Board, x: float, y: float) -> bool:
    for ko in board.keepouts:
        if ko["x1"] <= x <= ko["x2"] and ko["y1"] <= y <= ko["y2"]:
            return True
    return False


def to_grid(value: float) -> int:
    return int(round(value / GRID_MM))


def from_grid(value: int) -> float:
    return round(value * GRID_MM, 4)


def route_board(board: Board, pads: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Deterministic two-layer grid router used for review geometry.

    It is intentionally independent from KiCad.  Its success is structural
    evidence only; native DRC remains a separate release gate.
    """
    by_net: dict[str, list[dict]] = {}
    for pad in pads:
        if pad.get("net") and pad["net"] not in {"NC", "GND", "USB_SHIELD"}:
            by_net.setdefault(pad["net"], []).append(pad)
    routed_cells: dict[int, dict[tuple[int, int], str]] = {0: {}, 1: {}}
    pad_cells_f: dict[tuple[int, int], str] = {}
    pad_cells_b: dict[tuple[int, int], str] = {}
    for pad in pads:
        if not pad.get("net") or pad["net"] == "NC":
            continue
        cell = (to_grid(pad["x"]), to_grid(pad["y"]))
        pad_cells_f[cell] = pad["net"]
        if pad["kind"] == "tht":
            pad_cells_b[cell] = pad["net"]
    min_x, max_x = to_grid(EDGE_MARGIN_MM), to_grid(board.width - EDGE_MARGIN_MM)
    min_y, max_y = to_grid(EDGE_MARGIN_MM), to_grid(board.height - EDGE_MARGIN_MM)
    keepout_cells: set[tuple[int, int]] = set()
    for ko in board.keepouts:
        for gx in range(to_grid(ko["x1"]), to_grid(ko["x2"]) + 1):
            for gy in range(to_grid(ko["y1"]), to_grid(ko["y2"]) + 1):
                keepout_cells.add((gx, gy))

    segments: list[dict] = []
    vias: list[dict] = []
    failures: list[str] = []

    critical_order: list[str] = []
    for pair in board.differential_pairs:
        critical_order.extend(pair)
    critical_order.extend(sorted(board.high_current_nets))
    remaining = sorted(by_net, key=lambda net: (len(by_net[net]), net))
    net_order = []
    for net in critical_order + remaining:
        if net in by_net and net not in net_order:
            net_order.append(net)

    def blocked(state: tuple[int, int, int], net: str, allowed: set[tuple[int, int, int]]) -> bool:
        gx, gy, layer = state
        if not (min_x <= gx <= max_x and min_y <= gy <= max_y):
            return True
        if (gx, gy) in keepout_cells:
            return True
        if state in allowed:
            return False
        owner = routed_cells[layer].get((gx, gy))
        if owner and owner != net:
            return True
        pad_owner = (pad_cells_f if layer == 0 else pad_cells_b).get((gx, gy))
        return bool(pad_owner and pad_owner != net)

    def astar(start: tuple[int, int, int], goal: tuple[int, int, int], net: str, front_only: bool) -> list[tuple[int, int, int]] | None:
        allowed = {start, goal}
        queue: list[tuple[float, float, tuple[int, int, int]]] = []
        heapq.heappush(queue, (0.0, 0.0, start))
        came: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        cost = {start: 0.0}
        while queue:
            _, current_cost, current = heapq.heappop(queue)
            if current == goal:
                path = [current]
                while current in came:
                    current = came[current]
                    path.append(current)
                return list(reversed(path))
            gx, gy, layer = current
            neighbours = [(gx + 1, gy, layer), (gx - 1, gy, layer), (gx, gy + 1, layer), (gx, gy - 1, layer)]
            if not front_only:
                neighbours.append((gx, gy, 1 - layer))
            for nxt in neighbours:
                if blocked(nxt, net, allowed):
                    continue
                step = 10.0 if nxt[2] != layer else 1.0
                new_cost = current_cost + step
                if new_cost >= cost.get(nxt, float("inf")):
                    continue
                cost[nxt] = new_cost
                came[nxt] = current
                h = abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1]) + (0 if nxt[2] == goal[2] else 8)
                heapq.heappush(queue, (new_cost + h, new_cost, nxt))
        return None

    for net in net_order:
        terminals = by_net[net]
        if len(terminals) < 2:
            continue
        base = terminals[0]
        connected = [base]
        for terminal in terminals[1:]:
            goal_pad = min(connected, key=lambda item: abs(item["x"] - terminal["x"]) + abs(item["y"] - terminal["y"]))
            start = (to_grid(terminal["x"]), to_grid(terminal["y"]), 0)
            goal = (to_grid(goal_pad["x"]), to_grid(goal_pad["y"]), 0)
            front_only = net.startswith("USB_D")
            path = astar(start, goal, net, front_only)
            if path is None and front_only:
                path = astar(start, goal, net, False)
            if path is None:
                failures.append(f"{net}:{terminal['ref']}.{terminal['number']}->{goal_pad['ref']}.{goal_pad['number']}")
                continue
            connected.append(terminal)
            for state in path:
                routed_cells[state[2]][(state[0], state[1])] = net
            run_start = path[0]
            previous = path[0]
            for index in range(1, len(path)):
                current = path[index]
                layer_changed = current[2] != previous[2]
                direction_changed = index > 1 and (current[0] - previous[0], current[1] - previous[1], current[2]) != (
                    previous[0] - path[index - 2][0], previous[1] - path[index - 2][1], previous[2])
                if layer_changed or direction_changed:
                    if previous != run_start:
                        segments.append({"net": net, "layer": "F.Cu" if run_start[2] == 0 else "B.Cu",
                                         "start": [from_grid(run_start[0]), from_grid(run_start[1])],
                                         "end": [from_grid(previous[0]), from_grid(previous[1])], "width": net_width(board, net)})
                    run_start = current if layer_changed else previous
                if layer_changed:
                    vias.append({"net": net, "x": from_grid(previous[0]), "y": from_grid(previous[1]), "size": 0.55, "drill": 0.25})
                previous = current
            if previous != run_start:
                segments.append({"net": net, "layer": "F.Cu" if run_start[2] == 0 else "B.Cu",
                                 "start": [from_grid(run_start[0]), from_grid(run_start[1])],
                                 "end": [from_grid(previous[0]), from_grid(previous[1])], "width": net_width(board, net)})
    return segments, vias, failures


def bind_land_patterns(board: Board, *, load_reviewed: bool = False) -> Board:
    """Populate geometry, then attach only pre-existing immutable reviewed authority."""
    reviewed = _load_final_authority_rows() if load_reviewed else {}
    for part in board.parts:
        positions = derive_pad_positions(part)
        part.physical_pads = physical_pads_for_part(board.name, part, PhysicalPad, derive_pad_positions)
        configure_body_and_datum(board.name, part)
        if not part.land_pattern_authority:
            controlled = reviewed.get((board.name, part.ref))
            if controlled is not None:
                part.land_pattern_authority = controlled
        if positions:
            part.pad_positions = positions
        part.exact_land_pattern = not validate_land_pattern_authority(part)
    return board


BOARDS = [bind_land_patterns(make_wand(), load_reviewed=True), bind_land_patterns(make_receiver(), load_reviewed=True)]
