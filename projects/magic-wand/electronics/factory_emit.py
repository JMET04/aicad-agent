#!/usr/bin/env python3
"""Emit deterministic KiCad sources and assembly tables for both boards."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import textwrap
from dataclasses import asdict
from pathlib import Path

from build_factory_package import (
    BOARDS,
    Board,
    Part,
    body_datum_payload,
    absolute_pads,
    derive_pad_positions,
    net_width,
    q,
    require_land_pattern_authority,
    rotate_point,
    route_board,
    uid,
)


ROOT = Path(__file__).resolve().parent


def factory_fpid(board: Board, part: Part) -> str:
    return f"MW_FACTORY:{board.name}_{part.ref}"


def route_source_design(board: Board, pads: list[dict]) -> dict:
    """Return the exact source/placement fingerprint frozen routes must bind."""
    for part in board.parts:
        require_land_pattern_authority(part)
    component_rows = [
        {
            "ref": part.ref,
            "manufacturer": part.manufacturer,
            "mpn": part.mpn,
            "footprint": factory_fpid(board, part),
            "emittedFootprint": factory_fpid(board, part),
            "sourceLibraryFootprint": part.footprint,
            "package": part.package,
            "assembly": part.assembly,
            "positionMm": [part.x, part.y],
            "rotationDeg": part.rotation,
            "bodyMm": [part.width, part.height, part.body_height_mm],
            "bodyDatum": body_datum_payload(part),
            "authority": part.land_pattern_authority,
            "exactLandPattern": part.exact_land_pattern,
        }
        for part in sorted(board.parts, key=lambda item: item.ref)
    ]
    pad_rows = [
        {
            "physicalPadId": pad["physical_id"],
            "ref": pad["ref"],
            "number": pad["number"],
            "net": pad.get("net", ""),
            "positionMm": [pad["x"], pad["y"]],
            "localPositionMm": [pad.get("local_x"), pad.get("local_y")],
            "sizeMm": [pad["width"], pad["height"]],
            "drillWidthMm": pad.get("drill_width", 0.0),
            "drillHeightMm": pad.get("drill_height", 0.0),
            "kind": pad["kind"],
            "shape": pad.get("shape"),
            "layers": pad.get("layers", []),
            "role": pad.get("role"),
            "globalRotationDeg": pad.get("rotation", 0.0),
            "localRotationDeg": pad.get("local_rotation", 0.0),
        }
        for pad in sorted(
            pads,
            key=lambda item: (
                item["ref"], item["physical_id"], item["number"], item["x"], item["y"],
                item["width"], item["height"], item.get("role", ""),
            ),
        )
    ]
    authority = {
        "schema": "aicad.pcb-route-source-design.v2",
        "board": board.name,
        "boardDimensionsMm": [board.width, board.height, 1.6],
        "stackup": {
            "copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
            "finishedThicknessMm": 1.6,
        },
        "routingRules": {
            "netWidthsMm": {net: net_width(board, net) for net in sorted({pad["net"] for pad in pads if pad.get("net")})},
            "minimumClearanceMm": 0.15,
            "powerClearanceMm": 0.20,
            "loadClearanceMm": 0.25,
            "copperToEdgeMm": 0.30,
            "viaGeometriesMm": [{"size": 0.70, "drill": 0.45}, {"size": 0.80, "drill": 0.45}, {"size": 1.00, "drill": 0.50}],
            "highCurrentNets": sorted(board.high_current_nets),
            "differentialPairs": [list(pair) for pair in board.differential_pairs],
            "isolatedNets": sorted(board.isolated_nets),
        },
        "keepouts": board.keepouts,
        "planeRequirements": board.plane_requirements,
        "mechanicalKeepouts": board.mechanical_keepouts,
        "components": component_rows,
        "pads": pad_rows,
    }
    canonical = json.dumps(authority, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    critical_refs = {part.ref for part in board.parts if part.exact_land_pattern}
    return {
        "schema": "aicad.pcb-route-source-binding.v2",
        "algorithm": "SHA-256",
        "sha256": hashlib.sha256(canonical).hexdigest().upper(),
        "design": authority,
        "criticalComponents": [row for row in component_rows if row["ref"] in critical_refs],
        "criticalPads": [row for row in pad_rows if row["ref"] in critical_refs],
    }


def resolved_routes(board: Board, pads: list[dict]) -> tuple[list[dict], list[dict], list[str], dict]:
    fixture = ROOT / board.name / f"{board.name}-frozen-routes.json"
    if not fixture.exists():
        segments, vias, failures = route_board(board, pads)
        return segments, vias, failures, {"kind": "deterministic_grid_router", "path": None}
    data = json.loads(fixture.read_text(encoding="utf-8"))
    if data.get("schema") != "aicad.frozen-pcb-routes.v1":
        raise ValueError(f"unsupported frozen route schema: {fixture}")
    if data.get("status") != "DRC_FROZEN" or data.get("board") != board.name:
        raise ValueError(f"unfrozen or wrong-board route fixture: {fixture}")

    def validate_artifact_ref(value: object, label: str) -> dict:
        if not isinstance(value, dict):
            raise ValueError(f"route fixture {label} must be an artifact reference: {fixture}")
        release_root = ROOT.parent.resolve()
        path = value.get("path")
        size = value.get("size")
        sha256 = value.get("sha256")
        if not isinstance(path, str) or not path or chr(92) in path or any(token in path.lower() for token in ("probe", "wip", "temp")):
            raise ValueError(f"route fixture {label}.path is missing or non-canonical: {fixture}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError(f"route fixture {label}.size must be a positive integer: {fixture}")
        if not isinstance(sha256, str) or len(sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in sha256):
            raise ValueError(f"route fixture {label}.sha256 must be an exact SHA-256: {fixture}")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"route fixture {label}.path must be a controlled relative path: {fixture}")
        artifact = (release_root / relative).resolve()
        try:
            artifact.relative_to(release_root)
        except ValueError as exc:
            raise ValueError(f"route fixture {label}.path escapes the release root: {fixture}") from exc
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError(f"route fixture {label}.path is not a regular release file: {artifact}")
        payload = artifact.read_bytes()
        if len(payload) != size or hashlib.sha256(payload).hexdigest().upper() != sha256.upper():
            raise ValueError(f"route fixture {label} size/SHA disagree with the release file: {artifact}")
        return value

    source_board = validate_artifact_ref(data.get("sourceBoard"), "sourceBoard")
    native_drc = validate_artifact_ref(data.get("nativeDrc"), "nativeDrc")
    if source_board["path"] != f"electronics/{board.name}/{board.name}.kicad_pcb":
        raise ValueError(f"route fixture sourceBoard must reference the canonical board: {fixture}")
    if native_drc["path"] != f"electronics/{board.name}/{board.name}-native-drc.rpt":
        raise ValueError(f"route fixture nativeDrc must reference the canonical report: {fixture}")
    if any(native_drc.get(name) != 0 for name in ("violations", "unconnected", "footprintErrors")):
        raise ValueError(f"route fixture nativeDrc counts must all be zero: {fixture}")
    if native_drc.get("exclusions") != 0 or native_drc.get("suppressions") != 0:
        raise ValueError(f"route fixture nativeDrc exclusions/suppressions must be zero: {fixture}")
    dimensions = data.get("boardDimensionsMm", [])
    if len(dimensions) != 3 or [float(v) for v in dimensions] != [board.width, board.height, 1.6]:
        raise ValueError(f"route fixture dimensions disagree with board authority: {fixture}")
    expected_source = route_source_design(board, pads)
    if data.get("sourceDesign") != expected_source:
        raise ValueError(f"route fixture source geometry/pad authority fingerprint disagrees with board source: {fixture}")
    segments = data.get("routes")
    vias = data.get("vias")
    if not isinstance(segments, list) or not isinstance(vias, list) or not segments:
        raise ValueError(f"route fixture is incomplete: {fixture}")
    return segments, vias, [], {
        "kind": "native_drc_frozen_fixture",
        "path": fixture.relative_to(ROOT).as_posix(),
        "revision": data.get("revision"),
        "sourceBoard": data.get("sourceBoard"),
        "nativeDrc": data.get("nativeDrc"),
    }


def effects(size: float = 1.0, hide: bool = False) -> str:
    return f"(effects (font (size {size:.2f} {size:.2f})){' hide' if hide else ''})"

def emit_kicad_pad(
    board: Board,
    part: Part,
    pad: dict,
    dx: float,
    dy: float,
    net_id: dict[str, int] | None,
    *,
    rotation_deg: float | None = None,
) -> str:
    """Emit one exact physical pad while preserving duplicates and empty numbers."""
    local_rotation = float(pad.get("local_rotation", 0.0))
    emitted_rotation = local_rotation if rotation_deg is None else float(rotation_deg) % 360.0
    at_clause = f"(at {dx:.4f} {dy:.4f}" + (f" {emitted_rotation:.4f}" if emitted_rotation else "") + ")"
    layers = " ".join(q(layer) for layer in pad.get("layers", []))
    shape = pad.get("shape", "roundrect")
    kind = pad["kind"]
    pad_type = "np_thru_hole" if kind == "npth" else "thru_hole" if kind == "tht" else "smd"
    drill_width = float(pad.get("drill_width", pad.get("drill", 0.0)))
    drill_height = float(pad.get("drill_height", drill_width))
    drill_clause = ""
    if kind in {"npth", "tht"}:
        drill_clause = (
            f"(drill oval {drill_width:.3f} {drill_height:.3f})"
            if abs(drill_width - drill_height) > 1e-9
            else f"(drill {drill_width:.3f})"
        )
    net_clause = (
        f" (net {net_id[pad['net']]} {q(pad['net'])})"
        if net_id is not None and pad.get("net") and pad["net"] != "NC"
        else ""
    )
    pin = pad.get("pin")
    pin_clause = (
        f" (pinfunction {q(pin.name)}) (pintype {q(pin.electrical_type)})"
        if pin is not None
        else ""
    )
    roundrect_clause = " (roundrect_rratio 0.20)" if shape == "roundrect" else ""
    mechanical_clause = (
        " (property pad_prop_mechanical)" if pad.get("role") == "mount" and kind == "tht" else ""
    )
    return (
        f"    (pad {q(pad['number'])} {pad_type} {shape} {at_clause} "
        f"(size {pad['width']:.3f} {pad['height']:.3f}) {drill_clause} "
        f"(layers {layers}){roundrect_clause}{mechanical_clause}{net_clause}{pin_clause} "
        f"(uuid {uid(board.name, 'pad', part.ref, pad['physical_id'])}))"
    )


def _footprint_attr(part: Part) -> str:
    if part.package == "USB-C-16P":
        return ""
    if part.assembly == "THT":
        return "    (attr through_hole)"
    if part.assembly == "NPTH":
        return "    (attr board_only exclude_from_pos_files exclude_from_bom)"
    if part.assembly == "BARE_PAD":
        return "    (attr smd exclude_from_pos_files exclude_from_bom)"
    return "    (attr smd)"


def write_footprint_library(board: Board, out_dir: Path, pads: list[dict]) -> Path:
    """Rebuild the exact self-contained footprint library from physical pads."""
    pretty = out_dir / "MW_FACTORY.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    expected = {f"{board.name}_{part.ref}.kicad_mod" for part in board.parts}
    for existing in sorted(pretty.glob("*.kicad_mod")):
        if existing.name not in expected:
            existing.unlink()
    pads_by_ref: dict[str, list[dict]] = {}
    for pad in pads:
        pads_by_ref.setdefault(pad["ref"], []).append(pad)
    for part in board.parts:
        name = f"{board.name}_{part.ref}"
        fab_x1, fab_y1, fab_x2, fab_y2 = part.fab_bounds or (
            -part.width / 2, -part.height / 2, part.width / 2, part.height / 2,
        )
        cr_x1, cr_y1, cr_x2, cr_y2 = part.courtyard_bounds or (
            fab_x1 - 0.25, fab_y1 - 0.25, fab_x2 + 0.25, fab_y2 + 0.25,
        )
        lines = [
            f"(footprint {q(name)}",
            "  (version 20241229)",
            '  (generator "pcbnew")',
            '  (generator_version "10.0")',
            '  (layer "F.Cu")',
            f"  (descr {q('Controlled per-reference footprint for ' + part.manufacturer + ' ' + part.mpn)})",
            f"  (tags {q('aicad controlled ' + part.package)})",
            f"  (property \"Reference\" \"REF**\" (at 0 {-part.height / 2 - 1:.3f} 0) (layer \"F.SilkS\") {effects(.8)})",
            f"  (property \"Value\" {q(part.value)} (at 0 {part.height / 2 + 1:.3f} 0) (layer \"F.Fab\") {effects(.7)})",
            f"  (property \"Manufacturer\" {q(part.manufacturer)} (at 0 0 0) (layer \"F.Fab\") hide {effects(.6)})",
            f"  (property \"MPN\" {q(part.mpn)} (at 0 0 0) (layer \"F.Fab\") hide {effects(.6)})",
            _footprint_attr(part),
            f"  (fp_rect (start {fab_x1:.3f} {fab_y1:.3f}) (end {fab_x2:.3f} {fab_y2:.3f}) (stroke (width 0.10) (type solid)) (fill none) (layer \"F.Fab\") (uuid {uid(board.name, 'fab', part.ref)}))",
            f"  (fp_rect (start {cr_x1:.3f} {cr_y1:.3f}) (end {cr_x2:.3f} {cr_y2:.3f}) (stroke (width 0.05) (type solid)) (fill none) (layer \"F.CrtYd\") (uuid {uid(board.name, 'crtyd', part.ref)}))",
        ]
        for pad in pads_by_ref.get(part.ref, []):
            lines.append(
                f"  (property {q('PhysicalPadRole.' + pad['physical_id'])} {q(pad.get('role', 'signal'))} "
                f"(at 0 0 0) (layer \"F.Fab\") hide {effects(.4)})"
            )
        for pad in pads_by_ref.get(part.ref, []):
            lines.append(emit_kicad_pad(
                board, part, pad, float(pad["local_x"]), float(pad["local_y"]), None,
            ).lstrip())
        lines.append(")")
        (pretty / f"{name}.kicad_mod").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline="\n",
        )
    (pretty / "PROVENANCE.txt").write_text(
        "Generated from the per-reference authority physical-pad multiset.\n"
        "Standard geometry provenance: KiCad footprints 10.0.5 (GPL-3.0-or-later);\n"
        "manufacturer drawings remain reference-only and are not redistributed.\n",
        encoding="utf-8", newline="\n",
    )
    return pretty


def write_symbol_library(board: Board, out_dir: Path) -> Path:
    """Write a local symbol library matching every embedded MW_FACTORY symbol."""
    lines = [
        "(kicad_symbol_lib",
        "  (version 20231120)",
        '  (generator "kicad_symbol_editor")',
        '  (generator_version "10.0")',
    ]
    for part in board.parts:
        if part.assembly == "NPTH":
            continue
        local_name = f"{part.ref}_{part.package.replace(' ', '_')}"
        prefix = "".join(ch for ch in part.ref if ch.isalpha()) or "U"
        offsets = schematic_pin_offsets(part)
        in_bom = not (part.dnp or part.exclude_from_bom or part.assembly == "BARE_PAD")
        exclude_from_sim = part.assembly == "BARE_PAD"
        lines += [
            f"  (symbol {q(local_name)}",
            "    (pin_names (offset 0.70))",
            "    (exclude_from_sim yes)" if exclude_from_sim else "    (exclude_from_sim no)",
            "    (in_bom yes)" if in_bom else "    (in_bom no)",
            "    (on_board yes)",
            f"    (property \"Reference\" {q(prefix)} (at 0 2.54 0) {effects()})",
            f"    (property \"Value\" {q(part.value)} (at 0 0 0) {effects()})",
            f"    (property \"Footprint\" {q(factory_fpid(board, part))} (at 0 -2.54 0) {effects(.8, True)})",
            f"    (property \"Datasheet\" {q(part.datasheet or '~')} (at 0 -5.08 0) {effects(.8, True)})",
            f"    (property \"Description\" {q(part.notes or part.package)} (at 0 -7.62 0) {effects(.8, True)})",
            f"    (symbol {q(local_name + '_0_1')}",
            "      (rectangle (start -5.46 3.81) (end 5.46 -3.81) (stroke (width 0) (type solid)) (fill (type background)))",
            "    )",
            f"    (symbol {q(local_name + '_1_1')}",
        ]
        for pin in part.pins:
            dx, dy, angle = offsets[pin.number]
            etype = pin.electrical_type if pin.electrical_type in {
                "input", "output", "bidirectional", "tri_state", "passive", "free",
                "unspecified", "power_in", "power_out", "open_collector",
                "open_emitter", "no_connect",
            } else "passive"
            lines.append(
                f"      (pin {etype} line (at {dx:.3f} {dy:.3f} {angle:.1f}) (length 2.54) "
                f"(name {q(pin.name)} {effects(.75)}) (number {q(pin.number)} {effects(.75)}))"
            )
        lines += ["    )", "  )"]
    lines.append(")")
    path = out_dir / "MW_FACTORY.kicad_sym"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path

def schematic_pin_offsets(part: Part) -> dict[str, tuple[float, float, float]]:
    split = math.ceil(len(part.pins) / 2)
    left, right = part.pins[:split], part.pins[split:]
    spacing = max(1.27, min(2.54, 22.0 / max(1, len(left))))
    result: dict[str, tuple[float, float, float]] = {}
    for members, x, angle in ((left, -8.0, 0.0), (right, 8.0, 180.0)):
        for index, pin in enumerate(members):
            result[pin.number] = (x, (index - (len(members) - 1) / 2) * spacing, angle)
    return result


def write_schematic(board: Board, out_dir: Path) -> Path:
    root_uuid = uid(board.name, "schematic-root")
    lines = [
        "(kicad_sch", "  (version 20231120)", "  (generator eeschema)",
        '  (generator_version "8.0")', f"  (uuid {root_uuid})", '  (paper "A3")', "  (lib_symbols",
    ]
    for part in board.parts:
        if part.assembly == "NPTH":
            continue
        in_bom = not (part.dnp or part.exclude_from_bom or part.assembly == "BARE_PAD")
        exclude_from_sim = part.assembly == "BARE_PAD"
        lib_name = f"MW_FACTORY:{part.ref}_{part.package.replace(' ', '_')}"
        local_name = lib_name.split(":", 1)[1]
        prefix = "".join(ch for ch in part.ref if ch.isalpha()) or "U"
        offsets = schematic_pin_offsets(part)
        lines += [
            f"    (symbol {q(lib_name)}", "      (pin_names (offset 0.70))",
            "      (exclude_from_sim yes)" if exclude_from_sim else "      (exclude_from_sim no)",
            "      (in_bom yes)" if in_bom else "      (in_bom no)", "      (on_board yes)",
            f"      (property \"Reference\" {q(prefix)} (at 0 2.54 0) {effects()})",
            f"      (property \"Value\" {q(part.value)} (at 0 0 0) {effects()})",
            f"      (property \"Footprint\" {q(factory_fpid(board, part))} (at 0 -2.54 0) {effects(.8, True)})",
            f"      (property \"Datasheet\" {q(part.datasheet or '~')} (at 0 -5.08 0) {effects(.8, True)})",
            f"      (property \"Description\" {q(part.notes or part.package)} (at 0 -7.62 0) {effects(.8, True)})",
            f"      (property \"Manufacturer\" {q(part.manufacturer)} (at 0 -10.16 0) {effects(.8, True)})",
            f"      (property \"MPN\" {q(part.mpn)} (at 0 -12.70 0) {effects(.8, True)})",
            f"      (property \"LCSC\" {q(part.lcsc)} (at 0 -15.24 0) {effects(.8, True)})",
            f"      (property \"BOM Comments\" {q(part.notes)} (at 0 -17.78 0) {effects(.8, True)})",
            f"      (symbol {q(local_name + '_0_1')}",
            "        (rectangle (start -5.46 3.81) (end 5.46 -3.81) (stroke (width 0) (type solid)) (fill (type background)))",
            "      )", f"      (symbol {q(local_name + '_1_1')}",
        ]
        for pin in part.pins:
            dx, dy, angle = offsets[pin.number]
            etype = pin.electrical_type if pin.electrical_type in {
                "input", "output", "bidirectional", "tri_state", "passive", "free", "unspecified",
                "power_in", "power_out", "open_collector", "open_emitter", "no_connect"
            } else "passive"
            lines.append(
                f"        (pin {etype} line (at {dx:.3f} {dy:.3f} {angle:.1f}) (length 2.54) "
                f"(name {q(pin.name)} {effects(.75)}) (number {q(pin.number)} {effects(.75)}))"
            )
        lines += ["      )", "    )"]
    lines.append("  )")

    cols = 3 if board.name == "wand" else 4
    placed = 0
    labels: list[str] = []
    no_connects: list[str] = []
    for part in board.parts:
        if part.assembly == "NPTH":
            continue
        in_bom = not (part.dnp or part.exclude_from_bom or part.assembly == "BARE_PAD")
        exclude_from_sim = part.assembly == "BARE_PAD"
        sx, sy = 35.0 + (placed % cols) * 75.0, 30.0 + (placed // cols) * 48.0
        placed += 1
        lib_name = f"MW_FACTORY:{part.ref}_{part.package.replace(' ', '_')}"
        symbol_uuid = uid(board.name, "sch", part.ref)
        lines += [
            "  (symbol", f"    (lib_id {q(lib_name)})", f"    (at {sx:.3f} {sy:.3f} 0)", "    (unit 1)",
            "    (exclude_from_sim yes)" if exclude_from_sim else "    (exclude_from_sim no)",
            "    (in_bom yes)" if in_bom else "    (in_bom no)", "    (on_board yes)",
            "    (dnp yes)" if part.dnp else "    (dnp no)", f"    (uuid {symbol_uuid})",
            f"    (property \"Reference\" {q(part.ref)} (at {sx:.3f} {sy - 5.2:.3f} 0) {effects()})",
            f"    (property \"Value\" {q(part.value)} (at {sx:.3f} {sy + 5.2:.3f} 0) {effects(.85)})",
            f"    (property \"Footprint\" {q(factory_fpid(board, part))} (at {sx:.3f} {sy + 7.2:.3f} 0) {effects(.7, True)})",
            f"    (property \"Datasheet\" {q(part.datasheet or '~')} (at {sx:.3f} {sy + 9.2:.3f} 0) {effects(.7, True)})",
            f"    (property \"Manufacturer\" {q(part.manufacturer)} (at {sx:.3f} {sy + 11.2:.3f} 0) {effects(.7, True)})",
            f"    (property \"MPN\" {q(part.mpn)} (at {sx:.3f} {sy + 13.2:.3f} 0) {effects(.7, True)})",
            f"    (property \"LCSC\" {q(part.lcsc)} (at {sx:.3f} {sy + 15.2:.3f} 0) {effects(.7, True)})",
            f"    (property \"BOM Comments\" {q(part.notes)} (at {sx:.3f} {sy + 17.2:.3f} 0) {effects(.7, True)})",
        ]
        for pin in part.pins:
            lines.append(f"    (pin {q(pin.number)} (uuid {uid(board.name, 'sch-pin', part.ref, pin.number)}))")
        lines += [
            "    (instances", f"      (project {q('magic-wand-' + board.name)}",
            f"        (path {q('/' + root_uuid + '/' + symbol_uuid)} (reference {q(part.ref)}) (unit 1))",
            "      )", "    )", "  )",
        ]
        offsets = schematic_pin_offsets(part)
        for pin in part.pins:
            dx, dy, _ = offsets[pin.number]
            px, py = sx + dx, sy - dy
            if pin.net == "NC" or pin.electrical_type == "no_connect":
                no_connects.append(f"  (no_connect (at {px:.3f} {py:.3f}) (uuid {uid(board.name, 'nc', part.ref, pin.number)}))")
            else:
                labels.append(f"  (label {q(pin.net)} (at {px:.3f} {py:.3f} 0) {effects(.8)} (uuid {uid(board.name, 'label', part.ref, pin.number)}))")
    lines += labels + no_connects + [
        "  (text_box \"FACTORY REVIEW SOURCE\\nNative KiCad ERC pending; do not fabricate until release gate closes.\"",
        "    (exclude_from_sim no) (at 15 12 0) (size 110 12) (stroke (width 0.3) (type solid))",
        "    (fill (type none)) (effects (font (size 1.5 1.5)) (justify left top)))",
        "  (sheet_instances (path \"/\" (page \"1\")))", ")",
    ]
    path = out_dir / f"{board.name}.kicad_sch"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    write_symbol_library(board, out_dir)
    return path


def write_project(board: Board, out_dir: Path) -> Path:
    class_defs = [
        ("Default", .15, .20, .45, .20, .20, .20), ("POWER", .20, .25, .55, .25, .25, .20),
        ("LOAD_1A", .25, 1.00, .70, .30, 1.00, .25), ("USB2_90R", .15, .20, .45, .20, .20, .20),
    ]
    classes = [{"bus_width": 12, "clearance": c, "diff_pair_gap": dg, "diff_pair_via_gap": .25,
                "diff_pair_width": dw, "line_style": 0, "microvia_diameter": .3, "microvia_drill": .1,
                "name": n, "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
                "track_width": w, "via_diameter": vd, "via_drill": dr, "wire_width": 6}
               for n, c, w, vd, dr, dw, dg in class_defs]
    all_nets = sorted({pin.net for part in board.parts for pin in part.pins if pin.net not in {"", "NC"}})
    assignments = {net: ("LOAD_1A" if net in {"LOAD_SUPPLY_5_12V", "LOAD_DRAIN"} else
                         "POWER" if net in board.high_current_nets else "USB2_90R" if net.startswith("USB_D") else "Default")
                   for net in all_nets}
    strict_drc_severities = {
        "footprint_filters_mismatch": "error",
        "footprint_type_mismatch": "error",
        "lib_footprint_issues": "error",
        "malformed_courtyard": "error",
        "missing_courtyard": "error",
        "track_not_centered_on_via": "error",
        "tuning_profile_track_geometries": "error",
    }
    data = {
        "board": {"design_settings": {"defaults": {"board_outline_line_width": .1, "copper_line_width": .2,
                                                       "courtyard_line_width": .05, "fab_line_width": .1,
                                                       "silk_line_width": .15, "silk_text_size_h": 1.0, "silk_text_size_v": 1.0},
                                          "diff_pair_dimensions": [{"gap": .2, "via_gap": .25, "width": .2}],
                                          "drc_exclusions": [], "meta": {"version": 2},
                                          "rule_severities": strict_drc_severities,
                                          "rules": {"allow_blind_buried_vias": False, "allow_microvias": False,
                                                    "max_error": .005, "min_clearance": .15,
                                                    "min_copper_edge_clearance": .30, "min_hole_clearance": .25,
                                                    "min_hole_to_hole": .25, "min_silk_clearance": .15,
                                                    "min_text_height": .80, "min_text_thickness": .15,
                                                    "min_through_hole_diameter": .20, "min_track_width": .15,
                                                    "min_via_annular_width": .125, "min_via_diameter": .45,
                                                    "solder_mask_clearance": 0.0, "solder_mask_min_width": .10},
                                          "track_widths": [.15, .20, .50, 1.00],
                                          "via_dimensions": [{"diameter": .45, "drill": .20},
                                                             {"diameter": .55, "drill": .25},
                                                             {"diameter": .70, "drill": .30},
                                                             {"diameter": .80, "drill": .45},
                                                             {"diameter": 1.00, "drill": .50}]},
                  "layer_presets": [], "viewports": []},
        "boards": [], "cvpcb": {}, "erc": {"erc_exclusions": [], "meta": {"version": 0}, "rule_severities": {}},
        "libraries": {}, "meta": {"filename": f"{board.name}.kicad_pro", "version": 1},
        "net_settings": {"classes": classes, "meta": {"version": 3}, "net_colors": None,
                         "netclass_assignments": assignments, "netclass_patterns": []},
        "pcbnew": {}, "schematic": {"annotate_start_num": 0, "bom_fmt_presets": [], "bom_fmt_settings": {},
                                      "bom_presets": [], "bom_settings": {}, "connection_grid_size": 50.0,
                                      "drawing": {}, "legacy_lib_dir": "", "legacy_lib_list": []},
        "text_variables": {"PROJECT_STATUS": "RELEASE_CANDIDATE_ONLY", "REVISION": "A0"},
    }
    path = out_dir / f"{board.name}.kicad_pro"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (out_dir / f"{board.name}.kicad_dru").write_text(textwrap.dedent("""\
        (version 1)
        (rule "Global manufacturing track width"
          (condition "A.Type == 'track'")
          (constraint track_width (min 0.15mm)))
        (rule "Global manufacturing clearance"
          (condition "A.Type == 'track' && B.Type == 'track' && A.Net != B.Net")
          (constraint clearance (min 0.15mm)))
        (rule "Board edge copper clearance"
          (condition "A.Type == 'track' && B.Layer == 'Edge.Cuts'")
          (constraint clearance (min 0.30mm)))
        (rule "Receiver load copper"
          (condition "A.NetName == 'LOAD_DRAIN' || A.NetName == 'LOAD_SUPPLY_5_12V'")
          (constraint track_width (min 1.00mm))
          (constraint clearance (min 0.25mm)))
        (rule "Manufacturer fine-pitch same-footprint pads"
          (condition "A.Reference == B.Reference && (A.Reference == 'U3' || A.Reference == 'U4')")
          (constraint clearance (min 0.15mm)))
        # JAE SJ121837 intentionally places contacts 0.175 mm from an internal
        # precision locator.  This applies only inside the exact J1 footprint;
        # board-edge and all external clearances remain at the global minima.
        (rule "JAE SJ121837 internal locator geometry"
          (condition "A.Reference == 'J1' && B.Reference == 'J1'")
          (constraint hole_clearance (min 0.15mm))
          (constraint edge_clearance (min 0.15mm)))
        """), encoding="utf-8", newline="\n")
    (out_dir / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        "    (version 7)\n"
        "    (lib (name \"MW_FACTORY\") (type \"KiCad\") (uri \"${KIPRJMOD}/MW_FACTORY.pretty\") "
        "(options \"\") (descr \"Self-contained factory footprints generated from the reviewed board\"))\n"
        ")\n", encoding="utf-8", newline="\n"
    )
    (out_dir / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        "    (version 7)\n"
        "    (lib (name \"MW_FACTORY\") (type \"KiCad\") (uri \"${KIPRJMOD}/MW_FACTORY.kicad_sym\") (options \"\") (descr \"Self-contained reviewed symbols\"))\n"
        ")\n", encoding="utf-8", newline="\n"
    )
    # Local symbol table is now closed; return the project path.
    return path


def worksheet_board_origin(board: Board) -> tuple[float, float]:
    """Center the board on KiCad's landscape A4 worksheet.

    Design and factory coordinates remain board-local.  This translation is
    applied only when serializing the native PCB, so relative geometry stays
    unchanged and the generated CPL remains board-local.
    """
    return ((297.0 - board.width) / 2.0, (210.0 - board.height) / 2.0)


def write_pcb(board: Board, out_dir: Path, pads: list[dict], segments: list[dict], vias: list[dict]) -> Path:
    nets = sorted({pad["net"] for pad in pads if pad.get("net") and pad["net"] != "NC"})
    net_id = {name: index + 1 for index, name in enumerate(nets)}
    origin_x, origin_y = worksheet_board_origin(board)
    lines = [
        "(kicad_pcb", "  (version 20241229)", '  (generator "pcbnew")',
        '  (generator_version "10.0")',
        "  (general (thickness 1.6) (legacy_teardrops no))", '  (paper "A4")', "  (layers",
        '    (0 "F.Cu" signal)', '    (4 "In1.Cu" power)', '    (6 "In2.Cu" power)', '    (2 "B.Cu" signal)',
        '    (9 "F.Adhes" user "F.Adhesive")', '    (11 "B.Adhes" user "B.Adhesive")',
        '    (13 "F.Paste" user)', '    (15 "B.Paste" user)',
        '    (5 "F.SilkS" user "F.Silkscreen")', '    (7 "B.SilkS" user "B.Silkscreen")',
        '    (1 "F.Mask" user)', '    (3 "B.Mask" user)',
        '    (17 "Dwgs.User" user "User.Drawings")', '    (19 "Cmts.User" user "User.Comments")',
        '    (21 "Eco1.User" user "User.Eco1")', '    (23 "Eco2.User" user "User.Eco2")',
        '    (25 "Edge.Cuts" user)', '    (27 "Margin" user)',
        '    (31 "F.CrtYd" user "F.Courtyard")', '    (29 "B.CrtYd" user "B.Courtyard")',
        '    (35 "F.Fab" user)', '    (33 "B.Fab" user)', "  )",
        "  (setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no) (tenting front back)",
        "    (pcbplotparams (layerselection 0x00010fc_ffffffff) (plot_on_all_layers_selection 0x0000000_00000000)",
        "      (disableapertmacros no) (usegerberextensions yes) (usegerberattributes yes) (usegerberadvancedattributes yes)",
        "      (creategerberjobfile yes) (svgprecision 4) (plotframeref no) (viasonmask no) (mode 1)",
        "      (useauxorigin false) (plot_black_and_white true) (plotreference true) (plotvalue true)",
        "      (plotfptext true) (plotpadnumbers false) (subtractmaskfromsilk true) (outputformat 1)",
        "      (mirror false) (drillshape 1) (scaleselection 1) (outputdirectory \"cam/\")))", '  (net 0 "")',
    ]
    lines += [f"  (net {net_id[name]} {q(name)})" for name in nets]
    pads_by_ref: dict[str, list[dict]] = {}
    for pad in pads:
        pads_by_ref.setdefault(pad["ref"], []).append(pad)
    for part in board.parts:
        local_pad_bounds = []
        for pad in pads_by_ref.get(part.ref, []):
            pdx, pdy = rotate_point(pad["x"] - part.x, pad["y"] - part.y, -part.rotation)
            local_pad_bounds.append((pdx - pad["width"] / 2, pdy - pad["height"] / 2,
                                     pdx + pad["width"] / 2, pdy + pad["height"] / 2))
        fab_x1, fab_y1, fab_x2, fab_y2 = part.fab_bounds or (
            -part.width / 2, -part.height / 2, part.width / 2, part.height / 2,
        )
        if part.courtyard_bounds:
            bound_x1, bound_y1, bound_x2, bound_y2 = part.courtyard_bounds
        else:
            bound_x1 = min([fab_x1] + [item[0] for item in local_pad_bounds]) - 0.25
            bound_y1 = min([fab_y1] + [item[1] for item in local_pad_bounds]) - 0.25
            bound_x2 = max([fab_x2] + [item[2] for item in local_pad_bounds]) + 0.25
            bound_y2 = max([fab_y2] + [item[3] for item in local_pad_bounds]) + 0.25
        lines += [
            f"  (footprint {q(factory_fpid(board, part))}", '    (layer "F.Cu")', f"    (uuid {uid(board.name, 'fp', part.ref)})",
            f"    (at {part.x + origin_x:.4f} {part.y + origin_y:.4f} {part.rotation:.1f})",
            f"    (property \"Reference\" {q(part.ref)} (at 0 {-part.height/2 - 1:.3f} {part.rotation:.1f}) (layer \"F.Fab\") {effects(.8, True)})",
            f"    (property \"Value\" {q(part.value)} (at 0 {part.height/2 + 1:.3f} {part.rotation:.1f}) (layer \"F.Fab\") {effects(.7)})",
            f"    (property \"Manufacturer\" {q(part.manufacturer)} (at 0 0 {part.rotation:.1f}) (layer \"F.Fab\") {effects(.6, True)})",
            f"    (property \"MPN\" {q(part.mpn)} (at 0 0 {part.rotation:.1f}) (layer \"F.Fab\") {effects(.6, True)})",
            _footprint_attr(part),
            f"    (fp_rect (start {fab_x1:.3f} {fab_y1:.3f}) (end {fab_x2:.3f} {fab_y2:.3f}) "
            f"(stroke (width 0.10) (type solid)) (fill none) (layer \"F.Fab\") (uuid {uid(board.name, 'fab', part.ref)}))",
            f"    (fp_rect (start {bound_x1:.3f} {bound_y1:.3f}) (end {bound_x2:.3f} {bound_y2:.3f}) "
            f"(stroke (width 0.05) (type solid)) (fill none) (layer \"F.CrtYd\") (uuid {uid(board.name, 'crtyd', part.ref)}))",
        ]
        for pad in pads_by_ref.get(part.ref, []):
            lines.append(
                f"    (property {q('PhysicalPadRole.' + pad['physical_id'])} {q(pad.get('role', 'signal'))} "
                f"(at 0 0 0) (layer \"F.Fab\") hide {effects(.4)})"
            )
        for pad in pads_by_ref.get(part.ref, []):
            dx, dy = rotate_point(pad["x"] - part.x, pad["y"] - part.y, -part.rotation)
            lines.append(emit_kicad_pad(
                board, part, pad, dx, dy, net_id,
                rotation_deg=float(pad.get("rotation", 0.0)),
            ))
        lines.append("  )")
    for index, segment in enumerate(segments):
        if segment["net"] in net_id:
            lines.append(f"  (segment (start {segment['start'][0] + origin_x:.4f} {segment['start'][1] + origin_y:.4f}) "
                         f"(end {segment['end'][0] + origin_x:.4f} {segment['end'][1] + origin_y:.4f}) "
                         f"(width {segment['width']:.3f}) (layer {q(segment['layer'])}) (net {net_id[segment['net']]}) (uuid {uid(board.name, 'seg', index)}))")
    for index, via in enumerate(vias):
        if via["net"] in net_id:
            lines.append(f"  (via (at {via['x'] + origin_x:.4f} {via['y'] + origin_y:.4f}) (size {via['size']:.3f}) (drill {via['drill']:.3f}) "
                         f"(layers \"F.Cu\" \"B.Cu\") (net {net_id[via['net']]}) (uuid {uid(board.name, 'via', index)}))")
    lines += [
        f"  (zone (net {net_id.get('GND', 0)}) (net_name \"GND\") (layer \"In1.Cu\") (uuid {uid(board.name, 'gnd-zone')})",
        "    (hatch edge 0.5) (connect_pads (clearance 0.20)) (min_thickness 0.15)",
        "    (fill yes (thermal_gap 0.30) (thermal_bridge_width 0.30))",
        f"    (polygon (pts (xy {origin_x + .30:.3f} {origin_y + .30:.3f}) "
        f"(xy {origin_x + board.width - .30:.3f} {origin_y + .30:.3f}) "
        f"(xy {origin_x + board.width - .30:.3f} {origin_y + board.height - .30:.3f}) "
        f"(xy {origin_x + .30:.3f} {origin_y + board.height - .30:.3f}))))",
        f"  (zone (net {net_id.get('3V3', 0)}) (net_name \"3V3\") (layer \"In2.Cu\") (uuid {uid(board.name, '3v3-zone')})",
        "    (hatch edge 0.5) (connect_pads (clearance 0.20)) (min_thickness 0.15)",
        "    (fill yes (thermal_gap 0.30) (thermal_bridge_width 0.30))",
        f"    (polygon (pts (xy {origin_x + .30:.3f} {origin_y + .30:.3f}) "
        f"(xy {origin_x + board.width - .30:.3f} {origin_y + .30:.3f}) "
        f"(xy {origin_x + board.width - .30:.3f} {origin_y + board.height - .30:.3f}) "
        f"(xy {origin_x + .30:.3f} {origin_y + board.height - .30:.3f}))))",
    ]
    for ko_index, ko in enumerate(board.keepouts):
        lines += [
            f"  (gr_rect (start {ko['x1'] + origin_x:.3f} {ko['y1'] + origin_y:.3f}) "
            f"(end {ko['x2'] + origin_x:.3f} {ko['y2'] + origin_y:.3f}) "
            f"(stroke (width 0.20) (type dash)) (fill none) (layer \"Dwgs.User\") (uuid {uid(board.name, 'keepout-outline', ko_index)}))",
            f"  (gr_text {q(ko['name'])} (at {(ko['x1']+ko['x2'])/2 + origin_x:.3f} {(ko['y1']+ko['y2'])/2 + origin_y:.3f}) (layer \"Dwgs.User\") "
            f"(effects (font (size 0.75 0.75) (thickness 0.12))) (uuid {uid(board.name, 'keepout-label', ko_index)}))",
        ]
    lines += [
        f"  (gr_line (start {origin_x:.3f} {origin_y:.3f}) (end {origin_x + board.width:.3f} {origin_y:.3f}) (stroke (width 0.10) (type solid)) (layer \"Edge.Cuts\") (uuid {uid(board.name, 'edge', 1)}))",
        f"  (gr_line (start {origin_x + board.width:.3f} {origin_y:.3f}) (end {origin_x + board.width:.3f} {origin_y + board.height:.3f}) (stroke (width 0.10) (type solid)) (layer \"Edge.Cuts\") (uuid {uid(board.name, 'edge', 2)}))",
        f"  (gr_line (start {origin_x + board.width:.3f} {origin_y + board.height:.3f}) (end {origin_x:.3f} {origin_y + board.height:.3f}) (stroke (width 0.10) (type solid)) (layer \"Edge.Cuts\") (uuid {uid(board.name, 'edge', 3)}))",
        f"  (gr_line (start {origin_x:.3f} {origin_y + board.height:.3f}) (end {origin_x:.3f} {origin_y:.3f}) (stroke (width 0.10) (type solid)) (layer \"Edge.Cuts\") (uuid {uid(board.name, 'edge', 4)}))",
        f"  (gr_text {q(board.title + ' / REV A0 / REVIEW ONLY')} (at {origin_x + board.width/2:.3f} {origin_y + board.height-1.2:.3f}) (layer \"F.Fab\") "
        f"(effects (font (size 0.80 0.80) (thickness 0.15))) (uuid {uid(board.name, 'board-title')}))",
        ")",
    ]
    path = out_dir / f"{board.name}.kicad_pcb"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    write_footprint_library(board, out_dir, pads)
    return path


def write_bom_cpl(board: Board, out_dir: Path) -> tuple[Path, Path]:
    bom = out_dir / f"{board.name}-bom.csv"
    with bom.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "Comment", "Designator", "Footprint", "Manufacturer", "MPN", "LCSC Part #", "DNP", "Assembly Notes"
        ])
        writer.writeheader()
        for part in sorted((p for p in board.parts if not p.exclude_from_bom and not p.dnp and p.assembly not in {"NPTH", "BARE_PAD"}), key=lambda p: p.ref):
            writer.writerow({"Comment": part.value, "Designator": part.ref, "Footprint": factory_fpid(board, part),
                             "Manufacturer": part.manufacturer, "MPN": part.mpn, "LCSC Part #": part.lcsc,
                             "DNP": "YES" if part.dnp else "NO", "Assembly Notes": part.notes})
    cpl = out_dir / f"{board.name}-cpl.csv"
    with cpl.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Designator", "Mid X", "Mid Y", "Rotation", "Layer"])
        writer.writeheader()
        for part in sorted((p for p in board.parts if p.assembly == "SMT_TOP" and not p.dnp and not p.exclude_from_cpl), key=lambda p: p.ref):
            writer.writerow({"Designator": part.ref, "Mid X": f"{part.x:.3f}mm", "Mid Y": f"{part.y:.3f}mm",
                             "Rotation": f"{part.rotation:.1f}", "Layer": "Top"})
    return bom, cpl


def emit_board(board: Board) -> dict:
    out_dir = ROOT / board.name
    out_dir.mkdir(parents=True, exist_ok=True)
    pads = absolute_pads(board)
    segments, vias, failures, routing_source = resolved_routes(board, pads)
    write_project(board, out_dir)
    write_schematic(board, out_dir)
    write_pcb(board, out_dir, pads, segments, vias)
    write_bom_cpl(board, out_dir)
    design = {
        "schema": "aicad.factory-board.v1", "status": "RELEASE_CANDIDATE_ONLY", "board": board.name,
        "title": board.title, "dimensions_mm": [board.width, board.height], "layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        "finished_thickness_mm": 1.6, "copper_oz": 1, "surface_finish": "ENIG_CANDIDATE",
        "keepouts": board.keepouts, "differential_pairs": board.differential_pairs,
        "plane_requirements": board.plane_requirements,
        "mechanical_keepouts": board.mechanical_keepouts,
        "high_current_nets": sorted(board.high_current_nets), "isolated_nets": sorted(board.isolated_nets),
        "load_voltage_max_v": board.load_voltage_max_v,
        "components": [
            {
                **asdict(part),
                "sourceLibraryFootprint": part.footprint,
                "footprint": factory_fpid(board, part),
                "emittedFootprint": factory_fpid(board, part),
            }
            for part in board.parts
        ],
        "pads": [{k: v for k, v in pad.items() if k not in {"part", "pin"}} for pad in pads],
        "routes": segments, "vias": vias, "router_failures": failures, "routing_source": routing_source,
        "release_gates": {"native_kicad_erc": "NOT_RUN", "native_kicad_drc": "NOT_RUN",
                          "manufacturer_land_pattern_overlay": "OPEN", "fabrication_authorized": False},
    }
    (out_dir / f"{board.name}-factory-design.json").write_text(
        json.dumps(design, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return design


def main() -> int:
    reports = []
    for board in BOARDS:
        reports.append(emit_board(board))
    summary = {"generator": "factory_emit.py", "boards": [d["board"] for d in reports],
               "router_failures": {d["board"]: d["router_failures"] for d in reports},
               "native_gate": "NOT_RUN"}
    (ROOT / "factory-source-build.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    return 0 if not any(d["router_failures"] for d in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())

