from __future__ import annotations

import ast
import copy
import csv
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT / "projects" / "magic-wand"
ELECTRONICS_ROOT = PROJECT_ROOT / "electronics"
RECEIVER_EFFECTS_ROOT = ELECTRONICS_ROOT / "receiver-effects"
RECEIVER_EFFECTS_GENERATOR = RECEIVER_EFFECTS_ROOT / "generate_receiver_effects.py"
RECEIVER_EFFECTS_RELAYOUT = (
    RECEIVER_EFFECTS_ROOT / "generate_receiver_effects_relayout.py"
)
RECEIVER_EFFECTS_ROUTES = (
    RECEIVER_EFFECTS_ROOT / "receiver_effects_relayout_routes.py"
)
TPS62162_SOURCE_EXTRACT = (
    ELECTRONICS_ROOT
    / "evidence"
    / "authority"
    / "source-catalog"
    / "tps62162-dsg-extract.json"
)
BUILD_SCRIPT = ELECTRONICS_ROOT / "build_factory_package.py"
BASELINE_INVENTORY = (
    ELECTRONICS_ROOT
    / "evidence"
    / "authority"
    / "land-pattern-authority-inventory-baseline.json"
)
FINAL_INVENTORY = (
    ELECTRONICS_ROOT
    / "evidence"
    / "authority"
    / "land-pattern-authority-inventory-final.json"
)

sys.path.insert(0, str(ELECTRONICS_ROOT))

import build_factory_package as build  # noqa: E402
import factory_emit  # noqa: E402
import land_pattern_authority  # noqa: E402


def _load_receiver_effects_generator():
    spec = importlib.util.spec_from_file_location(
        "magic_wand_receiver_effects_generator",
        RECEIVER_EFFECTS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import receiver-effects generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


receiver_effects = _load_receiver_effects_generator()


AUTHORITY_FIELDS = {
    "authorityId",
    "status",
    "manufacturer",
    "mpn",
    "sourceKind",
    "evidence",
    "documentNumber",
    "revision",
    "sourceCoordinateFrame",
    "physicalPads",
    "physicalPadFingerprint",
    "bodyDatum",
    "bodyDatumFingerprint",
    "sourceArtifacts", "extractionEvidence",
}
EVIDENCE_FIELDS = {"kind", "size", "sha256"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _board(name: str):
    return next(board for board in build.BOARDS if board.name == name)


def _part(board_name: str, ref: str):
    return next(part for part in _board(board_name).parts if part.ref == ref)


def _parts_by_key() -> dict[tuple[str, str], object]:
    return {
        (board.name, part.ref): part
        for board in build.BOARDS
        for part in board.parts
    }


def _rows(document: dict) -> list[dict]:
    for key in ("rows", "entries", "authorities"):
        value = document.get(key)
        if isinstance(value, list):
            return value
    raise AssertionError("authority inventory has no rows/entries/authorities list")


def _net_for_physical_pad(part, pad) -> str:
    if pad.net_override is not None:
        return pad.net_override
    return next((pin.net for pin in part.pins if pin.number == pad.number), "")


def _artifact_reference(path: Path, relative: str) -> dict:
    payload = path.read_bytes()
    return {
        "path": relative,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
    }


def _pad_signature(pad) -> tuple:
    return (
        pad.number,
        pad.x,
        pad.y,
        pad.width,
        pad.height,
        pad.kind,
        pad.shape,
        pad.drill_width,
        pad.drill_height,
        pad.rotation,
        pad.layers,
        pad.role,
        pad.net_override,
    )


def _literal_assignment(path: Path, name: str):
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets
            ):
                return ast.literal_eval(statement.value)
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            return ast.literal_eval(statement.value)
    raise AssertionError(f"{path.name} has no literal {name} assignment")


def _source_functions(path: Path, *names: str) -> dict[str, object]:
    """Load selected pure functions without importing KiCad's pcbnew module."""
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = set(names)
    definitions = [
        statement
        for statement in module.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name in wanted
    ]
    found = {statement.name for statement in definitions}
    if found != wanted:
        raise AssertionError(
            f"{path.name} missing source functions {sorted(wanted - found)}"
        )
    namespace: dict[str, object] = {}
    selected = ast.Module(body=definitions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(selected), str(path), "exec"), namespace)
    return {name: namespace[name] for name in names}


class LandPatternAuthorityPolicyTests(unittest.TestCase):
    def test_package_names_can_never_grant_exact_land_pattern(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("OFFICIAL_LAND_PATTERN_PACKAGES", source)
        self.assertNotRegex(
            source,
            r"(?s)if\s+[^:\n]*\.package[^:]*:.*?exact_land_pattern\s*=\s*True",
        )

        unknown = build.Part(
            ref="X_UNKNOWN",
            value="unknown",
            manufacturer="Unknown",
            mpn="UNKNOWN-MPN",
            footprint="Resistor_SMD:R_0402_1005Metric",
            x=1.0,
            y=1.0,
            width=1.0,
            height=0.5,
            pins=build.pins({"1": ("1", "GND"), "2": ("2", "GND")}),
            package="0402",
            physical_pads=[
                build.PhysicalPad("X_UNKNOWN:001", "1", -0.5, 0.0, 0.5, 0.5),
                build.PhysicalPad("X_UNKNOWN:002", "2", 0.5, 0.0, 0.5, 0.5),
            ],
        )
        probe_board = copy.deepcopy(_board("wand"))
        probe_board.parts = [unknown]
        build.bind_land_patterns(probe_board)
        self.assertFalse(unknown.exact_land_pattern)
        self.assertTrue(build.validate_land_pattern_authority(unknown))

    def test_baseline_and_final_inventories_close_the_same_92_refs(self) -> None:
        source_keys = set(_parts_by_key())
        self.assertEqual(len(source_keys), 92)
        self.assertEqual(
            Counter(board for board, _ in source_keys),
            Counter({"wand": 46, "receiver": 46}),
        )

        baseline = json.loads(BASELINE_INVENTORY.read_text(encoding="utf-8"))
        baseline_rows = _rows(baseline)
        baseline_keys = {(row["board"], row["ref"]) for row in baseline_rows}
        self.assertEqual(len(baseline_rows), 92)
        self.assertEqual(len(baseline_keys), 92)
        self.assertEqual(baseline_keys, source_keys)
        self.assertEqual(baseline["summary"]["totalRefs"], 92)
        self.assertFalse(baseline["policy"]["packageNameWhitelistAccepted"])

        self.assertTrue(FINAL_INVENTORY.is_file(), "final authority inventory is required")
        final = json.loads(FINAL_INVENTORY.read_text(encoding="utf-8"))
        final_rows = _rows(final)
        final_keys = {(row["board"], row["ref"]) for row in final_rows}
        self.assertEqual(len(final_rows), 92)
        self.assertEqual(len(final_keys), 92)
        self.assertEqual(final_keys, source_keys)
        self.assertEqual(final.get("status"), "CONTROLLED")

    def test_every_ref_has_complete_verified_controlled_authority(self) -> None:
        for (board_name, ref), part in sorted(_parts_by_key().items()):
            with self.subTest(board=board_name, ref=ref):
                authority = part.land_pattern_authority
                self.assertIsInstance(authority, dict)
                self.assertFalse(AUTHORITY_FIELDS - authority.keys())
                self.assertEqual(authority["status"], "CONTROLLED")
                self.assertEqual(authority["manufacturer"], part.manufacturer)
                self.assertEqual(authority["mpn"], part.mpn)
                self.assertTrue(authority["authorityId"])
                self.assertTrue(authority["documentNumber"])
                self.assertTrue(authority["revision"])
                self.assertIsInstance(authority["sourceCoordinateFrame"], dict)
                self.assertTrue(authority["sourceCoordinateFrame"])
                self.assertEqual(authority["physicalPads"], build.physical_pad_rows(part.physical_pads))
                self.assertEqual(
                    authority["physicalPadFingerprint"],
                    build.physical_pad_fingerprint(part.physical_pads),
                )
                self.assertEqual(authority["bodyDatum"], build.body_datum_payload(part))
                self.assertEqual(
                    authority["bodyDatumFingerprint"],
                    build.body_datum_fingerprint(part),
                )
                self.assertRegex(authority["physicalPadFingerprint"], SHA256_RE)
                self.assertRegex(authority["bodyDatumFingerprint"], SHA256_RE)
                self.assertEqual(build.validate_land_pattern_authority(part), [])
                self.assertTrue(part.exact_land_pattern)
                self._assert_controlled_source(authority)

    def _assert_controlled_source(self, authority: dict) -> None:
        evidence = authority["evidence"]
        self.assertIsInstance(evidence, dict)
        self.assertFalse(EVIDENCE_FIELDS - evidence.keys())
        self.assertIsInstance(evidence["size"], int)
        self.assertNotIsInstance(evidence["size"], bool)
        self.assertGreater(evidence["size"], 0)
        self.assertRegex(evidence["sha256"], SHA256_RE)
        self.assertTrue(evidence["kind"])

        path_text = evidence.get("path")
        url_text = evidence.get("url") or evidence.get("officialUrl")
        self.assertTrue(bool(path_text) ^ bool(url_text), "authority needs one controlled path or official URL")
        if path_text:
            self.assertNotIn("\\", path_text)
            relative = PurePosixPath(path_text)
            self.assertFalse(relative.is_absolute())
            self.assertNotIn("..", relative.parts)
            self.assertEqual(relative.parts[:3], ("electronics", "evidence", "authority"))
            target = PROJECT_ROOT.joinpath(*relative.parts)
            self.assertTrue(target.is_file())
            payload = target.read_bytes()
            self.assertEqual(len(payload), evidence["size"])
            self.assertEqual(
                hashlib.sha256(payload).hexdigest().upper(),
                evidence["sha256"].upper(),
            )
        else:
            parsed = urlparse(url_text)
            self.assertEqual(parsed.scheme, "https")
            self.assertTrue(parsed.netloc)
            self.assertNotRegex(parsed.netloc.casefold(), r"(?:example|localhost)")
            self.assertIn("OFFICIAL", authority["sourceKind"].upper())

    def test_missing_authority_or_evidence_field_fails_closed(self) -> None:
        original = _board("receiver")
        for field in sorted(AUTHORITY_FIELDS):
            candidate = copy.deepcopy(original)
            part = next(row for row in candidate.parts if row.ref == "Q1")
            part.land_pattern_authority.pop(field, None)
            build.bind_land_patterns(candidate)
            with self.subTest(field=field):
                self.assertFalse(part.exact_land_pattern)
                self.assertTrue(build.validate_land_pattern_authority(part))
                with self.assertRaises(ValueError):
                    build.require_land_pattern_authority(part)
                with self.assertRaises(ValueError):
                    factory_emit.route_source_design(candidate, [])

        for field in sorted(EVIDENCE_FIELDS | {"path"}):
            candidate = copy.deepcopy(original)
            part = next(row for row in candidate.parts if row.ref == "Q1")
            part.land_pattern_authority["evidence"].pop(field, None)
            build.bind_land_patterns(candidate)
            with self.subTest(evidence_field=field):
                self.assertFalse(part.exact_land_pattern)
                self.assertTrue(build.validate_land_pattern_authority(part))
                with self.assertRaises(ValueError):
                    factory_emit.route_source_design(candidate, [])

        bad_source = copy.deepcopy(original)
        source_part = next(row for row in bad_source.parts if row.ref == "Q1")
        source_part.land_pattern_authority["sourceArtifacts"][0]["size"] += 1
        build.bind_land_patterns(bad_source)
        self.assertFalse(source_part.exact_land_pattern)
        self.assertTrue(build.validate_land_pattern_authority(source_part))
        with self.assertRaises(ValueError):
            factory_emit.route_source_design(bad_source, [])

        bad_extraction = copy.deepcopy(original)
        extraction_part = next(row for row in bad_extraction.parts if row.ref == "Q1")
        extraction_part.land_pattern_authority["extractionEvidence"][0]["sourceArtifactSha256"] = "0" * 64
        build.bind_land_patterns(bad_extraction)
        self.assertFalse(extraction_part.exact_land_pattern)
        self.assertTrue(build.validate_land_pattern_authority(extraction_part))
        with self.assertRaises(ValueError):
            factory_emit.route_source_design(bad_extraction, [])

    def test_unknown_and_unverified_authority_cannot_be_placed_or_routed(self) -> None:
        unknown = copy.deepcopy(_board("wand"))
        unknown_part = next(part for part in unknown.parts if part.ref == "R_CC1")
        unknown_part.land_pattern_authority = {}
        build.bind_land_patterns(unknown)
        self.assertFalse(unknown_part.exact_land_pattern)
        with self.assertRaises(ValueError):
            build.absolute_pads(unknown)
        with self.assertRaises(ValueError):
            factory_emit.route_source_design(unknown, [])

        unverified = copy.deepcopy(_board("wand"))
        unverified_part = next(part for part in unverified.parts if part.ref == "R_CC1")
        unverified_part.land_pattern_authority["status"] = "UNVERIFIED"
        build.bind_land_patterns(unverified)
        self.assertFalse(unverified_part.exact_land_pattern)
        with self.assertRaises(ValueError):
            build.absolute_pads(unverified)
        with self.assertRaises(ValueError):
            factory_emit.route_source_design(unverified, [])

    def test_pad_and_body_fingerprints_preserve_duplicate_and_empty_entities(self) -> None:
        part = _part("wand", "J1")
        original_pad_hash = build.physical_pad_fingerprint(part.physical_pads)
        original_body_hash = build.body_datum_fingerprint(part)

        removed_duplicate = copy.deepcopy(part.physical_pads)
        removed_duplicate.pop(next(i for i, pad in enumerate(removed_duplicate) if pad.number == "SH"))
        self.assertNotEqual(original_pad_hash, build.physical_pad_fingerprint(removed_duplicate))

        changed_empty = copy.deepcopy(part.physical_pads)
        empty_index = next(i for i, pad in enumerate(changed_empty) if pad.number == "")
        changed_empty[empty_index] = replace(
            changed_empty[empty_index],
            physical_id=changed_empty[empty_index].physical_id + "-MUTATED",
        )
        self.assertNotEqual(original_pad_hash, build.physical_pad_fingerprint(changed_empty))

        body_changed = copy.deepcopy(part)
        body_changed.body_height_mm += 0.01
        self.assertNotEqual(original_body_hash, build.body_datum_fingerprint(body_changed))
        datum_changed = copy.deepcopy(part)
        datum_changed.interface_datum["mutationProbe"] = 0.01
        self.assertNotEqual(original_body_hash, build.body_datum_fingerprint(datum_changed))


class LandPatternEntityRegressionTests(unittest.TestCase):
    def test_both_jae_j1_have_all_24_physical_entities(self) -> None:
        contacts = {
            "A1", "A4", "A5", "A6", "A7", "A8", "A9", "A12",
            "B1", "B4", "B5", "B6", "B7", "B8", "B9", "B12",
        }
        for board_name in ("wand", "receiver"):
            part = _part(board_name, "J1")
            numbers = Counter(pad.number for pad in part.physical_pads)
            with self.subTest(board=board_name):
                self.assertEqual(len(part.physical_pads), 24)
                self.assertEqual({number for number in numbers if number in contacts}, contacts)
                self.assertTrue(all(numbers[number] == 1 for number in contacts))
                self.assertEqual(numbers["SH"], 4)
                self.assertEqual(numbers[""], 4)
                self.assertTrue(all(pad.kind == "tht" for pad in part.physical_pads if pad.number == "SH"))
                self.assertEqual(
                    Counter(pad.kind for pad in part.physical_pads if pad.number == ""),
                    Counter({"npth": 2, "smd": 2}),
                )
                ids = [pad.physical_id for pad in part.physical_pads]
                self.assertEqual(len(ids), len(set(ids)))

    def test_wand_j1_remains_frozen_jae_dx07_geometry(self) -> None:
        part = _part("wand", "J1")
        self.assertEqual(
            (part.manufacturer, part.mpn, part.footprint, part.package),
            (
                "JAE",
                "DX07S016JA1R1500",
                "Connector_USB:USB_C_Receptacle_USB2.0_16P",
                "USB-C-16P",
            ),
        )
        self.assertEqual((part.x, part.y, part.rotation), (12.25, 38.0, 90.0))
        self.assertEqual((part.width, part.height, part.body_height_mm), (8.94, 6.90, 3.60))
        self.assertEqual(part.fab_bounds, (-4.47, -3.45, 4.47, 3.45))
        self.assertEqual(part.interface_datum["drawingNumber"], "SJ121837")

        smd_layers = ("F.Cu", "F.Paste", "F.Mask")
        tht_layers = ("*.Cu", "*.Mask")
        contacts = (
            ("A1", -3.10, 0.52), ("A4", -2.35, 0.52),
            ("A5", -1.75, 0.27), ("A6", -0.25, 0.27),
            ("A7", 0.75, 0.27), ("A8", 1.75, 0.27),
            ("A9", 2.35, 0.52), ("A12", 3.10, 0.52),
            ("B1", 3.10, 0.52), ("B4", 2.35, 0.52),
            ("B5", 1.25, 0.27), ("B6", 0.25, 0.27),
            ("B7", -0.75, 0.27), ("B8", -1.25, 0.27),
            ("B9", -2.35, 0.52), ("B12", -3.10, 0.52),
        )
        expected = {
            f"contact-{number}": (
                number, x, -3.05, width, 1.0, "smd", "roundrect",
                0.0, 0.0, 0.0, smd_layers, "signal", None,
            )
            for number, x, width in contacts
        }
        expected.update({
            "shell-left-front": (
                "SH", -4.32, -2.675, 1.30, 2.30, "tht", "oval",
                0.60, 1.60, 0.0, tht_layers, "mount", None,
            ),
            "shell-left-rear": (
                "SH", -4.32, 1.15, 1.30, 2.60, "tht", "oval",
                0.60, 1.90, 0.0, tht_layers, "mount", None,
            ),
            "shell-right-front": (
                "SH", 4.32, -2.675, 1.30, 2.30, "tht", "oval",
                0.60, 1.60, 0.0, tht_layers, "mount", None,
            ),
            "shell-right-rear": (
                "SH", 4.32, 1.15, 1.30, 2.60, "tht", "oval",
                0.60, 1.90, 0.0, tht_layers, "mount", None,
            ),
            "locator-left": (
                "", -3.0, -1.95, 0.60, 0.60, "npth", "circle",
                0.60, 0.60, 0.0, tht_layers, "locating", None,
            ),
            "locator-right": (
                "", 3.0, -1.95, 0.85, 0.60, "npth", "oval",
                0.85, 0.60, 90.0, tht_layers, "locating", None,
            ),
            "hold-down-left": (
                "", -1.4, 1.15, 1.0, 2.0, "smd", "roundrect",
                0.0, 0.0, 0.0, smd_layers, "hold_down", None,
            ),
            "hold-down-right": (
                "", 1.4, 1.15, 1.0, 2.0, "smd", "roundrect",
                0.0, 0.0, 0.0, smd_layers, "hold_down", None,
            ),
        })
        self.assertEqual(
            {pad.physical_id: _pad_signature(pad) for pad in part.physical_pads},
            expected,
        )

    def test_receiver_effects_j1_uses_official_gct_usb4105_geometry(self) -> None:
        board = receiver_effects.make_board()
        part = next(row for row in board.parts if row.ref == "J1")
        self.assertEqual(
            (
                part.manufacturer,
                part.mpn,
                part.lcsc,
                part.footprint,
                part.package,
            ),
            (
                "GCT",
                "USB4105-GF-A-120",
                "C5184243",
                "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
                "USB4105-16P",
            ),
        )
        self.assertEqual((part.x, part.y, part.rotation), (3.675, 21.0, 270.0))
        self.assertEqual((part.width, part.height, part.body_height_mm), (8.94, 7.35, 3.31))
        self.assertEqual(part.fab_bounds, (-4.47, -3.675, 4.47, 3.675))
        self.assertEqual(part.courtyard_bounds, (-5.32, -4.76, 5.32, 4.18))
        self.assertEqual(part.interface_datum["boardEdgeLocalYmm"], 3.675)
        self.assertEqual(part.interface_datum["placementRotationDeg"], 270.0)
        self.assertEqual(part.interface_datum["shellStakeLengthMm"], 1.20)

        metadata = land_pattern_authority.authority_metadata(part)
        self.assertEqual(metadata["documentNumber"], "USB4105")
        self.assertEqual(metadata["revision"], "B4")
        self.assertEqual(metadata["officialUrl"], "https://gct.co/files/drawings/usb4105.pdf")

        logical_contacts = {
            "A1", "A4", "A5", "A6", "A7", "A8", "A9", "A12",
            "B1", "B4", "B5", "B6", "B7", "B8", "B9", "B12",
        }
        contact_pads = [pad for pad in part.physical_pads if pad.number in logical_contacts]
        shell_pads = [pad for pad in part.physical_pads if pad.number == "SH"]
        locating_pads = [pad for pad in part.physical_pads if pad.kind == "npth"]
        self.assertEqual(len(part.physical_pads), 22)
        self.assertEqual(len(contact_pads), 16)
        self.assertEqual(Counter(pad.number for pad in contact_pads), Counter(logical_contacts))
        self.assertEqual(len({(pad.x, pad.y) for pad in contact_pads}), 12)
        self.assertEqual(len(shell_pads), 4)
        self.assertEqual(len(locating_pads), 2)
        self.assertTrue(all("F.Paste" in pad.layers for pad in shell_pads))

        smd_layers = ("F.Cu", "F.Paste", "F.Mask")
        shell_layers = ("*.Cu", "*.Mask", "F.Paste")
        tht_layers = ("*.Cu", "*.Mask")
        contacts = (
            ("A1", -3.20, 0.60), ("A4", -2.40, 0.60),
            ("A5", -1.25, 0.30), ("A6", -0.25, 0.30),
            ("A7", 0.25, 0.30), ("A8", 1.25, 0.30),
            ("A9", 2.40, 0.60), ("A12", 3.20, 0.60),
            ("B1", 3.20, 0.60), ("B4", 2.40, 0.60),
            ("B5", 1.75, 0.30), ("B6", 0.75, 0.30),
            ("B7", -0.75, 0.30), ("B8", -1.75, 0.30),
            ("B9", -2.40, 0.60), ("B12", -3.20, 0.60),
        )
        expected = {
            f"contact-{number}": (
                number, x, -3.68, width, 1.15, "smd", "roundrect",
                0.0, 0.0, 0.0, smd_layers, "signal", None,
            )
            for number, x, width in contacts
        }
        expected.update({
            "shell-left-front": (
                "SH", -4.32, -3.105, 1.00, 2.10, "tht", "oval",
                0.60, 1.70, 0.0, shell_layers, "mount", None,
            ),
            "shell-left-rear": (
                "SH", -4.32, 1.075, 1.00, 1.80, "tht", "oval",
                0.60, 1.40, 0.0, shell_layers, "mount", None,
            ),
            "shell-right-front": (
                "SH", 4.32, -3.105, 1.00, 2.10, "tht", "oval",
                0.60, 1.70, 0.0, shell_layers, "mount", None,
            ),
            "shell-right-rear": (
                "SH", 4.32, 1.075, 1.00, 1.80, "tht", "oval",
                0.60, 1.40, 0.0, shell_layers, "mount", None,
            ),
            "locator-left": (
                "", -2.89, -2.605, 0.65, 0.65, "npth", "circle",
                0.65, 0.65, 0.0, tht_layers, "locating", None,
            ),
            "locator-right": (
                "", 2.89, -2.605, 0.65, 0.65, "npth", "circle",
                0.65, 0.65, 0.0, tht_layers, "locating", None,
            ),
        })
        self.assertEqual(
            {pad.physical_id: _pad_signature(pad) for pad in part.physical_pads},
            expected,
        )

    def test_receiver_effects_a1_relayout_preserves_board_edge_mapping(self) -> None:
        placements = _literal_assignment(RECEIVER_EFFECTS_RELAYOUT, "PLACEMENTS")
        self.assertEqual(placements["J1"], (3.675, 28.0, 270.0))

        board = receiver_effects.make_board()
        board.width, board.height = 60.0, 50.0
        part = next(row for row in board.parts if row.ref == "J1")
        part.x, part.y, part.rotation = placements["J1"]
        edge_local_y = part.interface_datum["boardEdgeLocalYmm"]
        edge_dx, edge_dy = build.rotate_point(0.0, edge_local_y, part.rotation)
        self.assertAlmostEqual(part.x + edge_dx, 0.0, places=9)
        self.assertAlmostEqual(part.y + edge_dy, 28.0, places=9)

        pads = build.absolute_pads(board, require_controlled=False)
        contact_centers = {
            (pad["x"], pad["y"])
            for pad in pads
            if pad["ref"] == "J1" and pad["number"] not in {"", "SH"}
        }
        self.assertEqual(
            contact_centers,
            {
                (7.355, 24.8), (7.355, 25.6), (7.355, 26.25),
                (7.355, 26.75), (7.355, 27.25), (7.355, 27.75),
                (7.355, 28.25), (7.355, 28.75), (7.355, 29.25),
                (7.355, 29.75), (7.355, 30.4), (7.355, 31.2),
            },
        )

        origin_x, origin_y = factory_emit.worksheet_board_origin(board)
        self.assertEqual((origin_x, origin_y), (118.5, 80.0))
        self.assertEqual((origin_x + part.x, origin_y + part.y), (122.175, 108.0))
        self.assertAlmostEqual(origin_x + part.x + edge_dx, 118.5, places=9)
        self.assertAlmostEqual(origin_y + part.y + edge_dy, 108.0, places=9)

    def test_receiver_effects_f1_uses_current_bourns_style2_authority(self) -> None:
        board = receiver_effects.make_board()
        part = next(row for row in board.parts if row.ref == "F1")
        self.assertEqual(
            (part.manufacturer, part.mpn, part.lcsc, part.package, part.footprint),
            (
                "Bourns",
                "MF-MSMF150/24X-2",
                "C78695",
                "1812",
                "Fuse:Fuse_1812_4532Metric",
            ),
        )
        self.assertEqual(
            [(pin.number, pin.net) for pin in part.pins],
            [("1", "USB_VBUS_RAW"), ("2", "USB_VBUS_5V")],
        )
        self.assertEqual(
            [
                (pad.physical_id, pad.number, pad.x, pad.y, pad.width, pad.height)
                for pad in part.physical_pads
            ],
            [
                ("terminal-1", "1", -2.390, 0.0, 1.68, 2.95),
                ("terminal-2", "2", 2.390, 0.0, 1.68, 2.95),
            ],
        )
        metadata = land_pattern_authority.authority_metadata(part)
        self.assertEqual(metadata["documentNumber"], "MF-MSMF")
        self.assertEqual(
            metadata["officialUrl"],
            "https://www.bourns.com/docs/product-datasheets/mf-msmf.pdf",
        )
        self.assertEqual(
            metadata["sourceKind"],
            "manufacturerDrawing+controlledKiCadLibrary",
        )
        self.assertEqual(part.datasheet, metadata["officialUrl"])

    def test_receiver_effects_u2_matches_ti_dsg0008a_source_extract(self) -> None:
        board = receiver_effects.make_board()
        part = next(row for row in board.parts if row.ref == "U2")
        expected = {
            "1": (-0.95, -0.75, 0.50, 0.25),
            "2": (-0.95, -0.25, 0.50, 0.25),
            "3": (-0.95, 0.25, 0.50, 0.25),
            "4": (-0.95, 0.75, 0.50, 0.25),
            "5": (0.95, 0.75, 0.50, 0.25),
            "6": (0.95, 0.25, 0.50, 0.25),
            "7": (0.95, -0.25, 0.50, 0.25),
            "8": (0.95, -0.75, 0.50, 0.25),
            "EP": (0.0, 0.0, 0.90, 1.60),
        }
        self.assertEqual(
            {
                pad.number: (pad.x, pad.y, pad.width, pad.height)
                for pad in part.physical_pads
            },
            expected,
        )
        self.assertEqual(len(part.physical_pads), 9)
        self.assertTrue(
            all(
                pad.role == "signal"
                for pad in part.physical_pads
                if pad.number != "EP"
            )
        )
        ep = next(pad for pad in part.physical_pads if pad.number == "EP")
        self.assertEqual((ep.physical_id, ep.role), ("thermal-ep", "thermal"))

        extract = json.loads(TPS62162_SOURCE_EXTRACT.read_text(encoding="utf-8"))
        self.assertEqual(extract["manufacturer"], "Texas Instruments")
        self.assertEqual(extract["coveredMpns"], ["TPS62162DSGR"])
        self.assertEqual(extract["documentNumber"], "SLVSAM2E / DSG0008A")
        self.assertEqual(extract["revision"], "E")
        self.assertEqual(extract["page"], "39-40")
        self.assertEqual(
            extract["originalOfficialUrl"],
            "https://www.ti.com/lit/ds/symlink/tps62160.pdf",
        )
        self.assertEqual(
            extract["geometry"]["physicalPads"],
            {
                "signalCount": 8,
                "pitchMm": 0.5,
                "signalLandMm": [0.50, 0.25],
                "exposedLandMm": [0.90, 1.60],
            },
        )
        metadata = land_pattern_authority.authority_metadata(part)
        self.assertEqual(metadata["documentNumber"], extract["documentNumber"])
        self.assertEqual(metadata["revision"], extract["revision"])
        self.assertEqual(metadata["officialUrl"], extract["originalOfficialUrl"])

    def test_receiver_effects_u3_has_local_vbus_decoupling_at_a1(self) -> None:
        placements = _literal_assignment(RECEIVER_EFFECTS_RELAYOUT, "PLACEMENTS")
        self.assertIn("C_BUS", placements)
        self.assertEqual(placements["C_BUS"], (14.70, 28.00, 0.0))

        board = receiver_effects.make_board()
        by_ref = {part.ref: part for part in board.parts}
        self.assertIn("C_BUS", by_ref)
        c_bus = by_ref["C_BUS"]
        self.assertEqual(
            (
                c_bus.value,
                c_bus.manufacturer,
                c_bus.mpn,
                c_bus.lcsc,
                c_bus.package,
            ),
            (
                "100nF 16V X7R",
                "Murata",
                "GRM155R71C104KA88D",
                "C1525",
                "0402",
            ),
        )
        self.assertEqual(
            [(pin.number, pin.net) for pin in c_bus.pins],
            [("1", "USB_VBUS_5V"), ("2", "GND")],
        )

        for ref, (x, y, rotation) in placements.items():
            part = by_ref[ref]
            part.x, part.y = x, y
            if rotation is not None:
                part.rotation = rotation
        pads = build.absolute_pads(board, require_controlled=False)
        c_bus_pads = {
            pad["number"]: (
                pad["x"],
                pad["y"],
                pad["width"],
                pad["height"],
                pad["net"],
            )
            for pad in pads
            if pad["ref"] == "C_BUS"
        }
        self.assertEqual(
            c_bus_pads,
            {
                "1": (14.22, 28.00, 0.56, 0.62, "USB_VBUS_5V"),
                "2": (15.18, 28.00, 0.56, 0.62, "GND"),
            },
        )
        u3_vbus = next(
            pad
            for pad in pads
            if pad["ref"] == "U3" and pad["number"] == "5"
        )
        self.assertEqual(
            (u3_vbus["x"], u3_vbus["y"], u3_vbus["net"]),
            (13.15, 28.00, "USB_VBUS_5V"),
        )

        power = _source_functions(
            RECEIVER_EFFECTS_RELAYOUT, "seg", "via", "power_skeleton"
        )
        usb = _source_functions(
            RECEIVER_EFFECTS_ROUTES, "_seg", "_via", "usb_data_group"
        )
        segments, vias = power["power_skeleton"]()
        usb_segments, usb_vias = usb["usb_data_group"]()
        segments += usb_segments
        vias += usb_vias
        segment_signatures = {
            (
                row["net"],
                row["layer"],
                tuple(row["start"]),
                tuple(row["end"]),
                row["width"],
            )
            for row in segments
        }
        self.assertIn(
            (
                "USB_VBUS_5V",
                "F.Cu",
                (13.15, 28.00),
                (14.22, 28.00),
                0.40,
            ),
            segment_signatures,
        )
        self.assertIn(
            ("GND", "F.Cu", (15.18, 28.00), (15.60, 28.00), 0.30),
            segment_signatures,
        )
        self.assertIn(
            ("GND", 15.60, 28.00, 0.60, 0.30),
            {
                (row["net"], row["x"], row["y"], row["size"], row["drill"])
                for row in vias
            },
        )

    def test_receiver_effects_u4_matches_adi_90_0031_land_pattern(self) -> None:
        board = receiver_effects.make_board()
        part = next(row for row in board.parts if row.ref == "U4")
        self.assertEqual(
            (part.manufacturer, part.mpn, part.package, part.footprint),
            (
                "Analog Devices",
                "MAX98357AETE+T",
                "TQFN-16-EP",
                "Package_DFN_QFN:TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm",
            ),
        )
        expected = {
            "1": (-1.425, -0.75, 0.80, 0.30),
            "2": (-1.425, -0.25, 0.80, 0.30),
            "3": (-1.425, 0.25, 0.80, 0.30),
            "4": (-1.425, 0.75, 0.80, 0.30),
            "5": (-0.75, 1.425, 0.30, 0.80),
            "6": (-0.25, 1.425, 0.30, 0.80),
            "7": (0.25, 1.425, 0.30, 0.80),
            "8": (0.75, 1.425, 0.30, 0.80),
            "9": (1.425, 0.75, 0.80, 0.30),
            "10": (1.425, 0.25, 0.80, 0.30),
            "11": (1.425, -0.25, 0.80, 0.30),
            "12": (1.425, -0.75, 0.80, 0.30),
            "13": (0.75, -1.425, 0.30, 0.80),
            "14": (0.25, -1.425, 0.30, 0.80),
            "15": (-0.25, -1.425, 0.30, 0.80),
            "16": (-0.75, -1.425, 0.30, 0.80),
            "17": (0.0, 0.0, 1.23, 1.23),
        }
        self.assertEqual(len(part.physical_pads), 17)
        self.assertEqual(
            {
                pad.number: (pad.x, pad.y, pad.width, pad.height)
                for pad in part.physical_pads
            },
            expected,
        )
        self.assertTrue(
            all(
                pad.role == "signal"
                for pad in part.physical_pads
                if pad.number != "17"
            )
        )
        ep = next(pad for pad in part.physical_pads if pad.number == "17")
        self.assertEqual((ep.physical_id, ep.role), ("exposed-pad", "thermal"))
        metadata = land_pattern_authority.authority_metadata(part)
        self.assertEqual(metadata["documentNumber"], "90-0031")
        self.assertEqual(
            metadata["officialUrl"],
            (
                "https://www.analog.com/media/en/package-pcb-resources/"
                "land-pattern/90-0031.pdf"
            ),
        )

    def test_wand_jst_connectors_include_both_mount_pads(self) -> None:
        expectations = {
            "J2": Counter({"1": 1, "2": 1, "3": 1, "MP": 2}),
            "J3": Counter({"1": 1, "2": 1, "MP": 2}),
        }
        for ref, expected_numbers in expectations.items():
            part = _part("wand", ref)
            with self.subTest(ref=ref):
                self.assertEqual(len(part.physical_pads), sum(expected_numbers.values()))
                self.assertEqual(Counter(pad.number for pad in part.physical_pads), expected_numbers)
                mounts = [pad for pad in part.physical_pads if pad.number == "MP"]
                self.assertEqual(len(mounts), 2)
                self.assertTrue(all(pad.role in {"mount", "hold_down"} for pad in mounts))

    def test_skqg_switch_keeps_four_physical_pads_and_duplicate_numbers(self) -> None:
        part = _part("wand", "SW1")
        self.assertEqual(len(part.physical_pads), 4)
        self.assertEqual(Counter(pad.number for pad in part.physical_pads), Counter({"1": 2, "2": 2}))
        self.assertEqual(Counter(_net_for_physical_pad(part, pad) for pad in part.physical_pads), Counter({"ARM_SW": 2, "GND": 2}))
        self.assertEqual(len({pad.physical_id for pad in part.physical_pads}), 4)

    def test_csd17313q2_dqk_has_all_eight_pads_on_the_correct_nets(self) -> None:
        part = _part("receiver", "Q1")
        self.assertEqual(part.mpn, "CSD17313Q2")
        self.assertEqual(part.package, "Texas_DQK")
        self.assertEqual(len(part.physical_pads), 8)
        expected = {
            "1": "LOAD_DRAIN",
            "2": "LOAD_DRAIN",
            "3": "LOAD_GATE",
            "4": "GND",
            "5": "LOAD_DRAIN",
            "6": "LOAD_DRAIN",
            "7": "GND",
            "8": "LOAD_DRAIN",
        }
        self.assertEqual(
            {pad.number: _net_for_physical_pad(part, pad) for pad in part.physical_pads},
            expected,
        )

    def test_smb_diodes_and_dedicated_0603_fuses_are_not_generic_packages(self) -> None:
        for ref in ("D1", "D2"):
            part = _part("receiver", ref)
            with self.subTest(ref=ref):
                self.assertEqual(part.package, "SMB")
                self.assertRegex(part.footprint, r"^Diode_SMD:D_SMB")
                self.assertEqual(len(part.physical_pads), 2)

        for board_name in ("wand", "receiver"):
            part = _part(board_name, "F1")
            with self.subTest(board=board_name):
                self.assertEqual(part.package, "0603")
                self.assertRegex(part.footprint, r"^Fuse_SMD:Fuse_0603")
                self.assertNotRegex(part.footprint, r"Inductor|(?:^|:)L_")
                self.assertEqual(len(part.physical_pads), 2)

    def test_resistor_and_capacitor_0402_0805_families_stay_split(self) -> None:
        expected_c0402 = {
            ("wand", "C_HAPTIC_REG"), ("wand", "C_HAPTIC_VDD"),
            ("wand", "C_IMU_IO"), ("wand", "C_IMU_VDD"),
            ("receiver", "C_U3A"), ("receiver", "C_U3B"),
            ("receiver", "C_U4A"), ("receiver", "C_U4B"),
        }
        expected_c0805 = {
            ("wand", "C_BAT"), ("wand", "C_BUCK_IN"), ("wand", "C_BUCK_OUT"),
            ("wand", "C_CHG_IN"), ("wand", "C_SYS"), ("wand", "C_USB"),
            ("receiver", "C_BUCK_IN"), ("receiver", "C_BUCK_OUT"),
            ("receiver", "C_U1"), ("receiver", "C_USB"),
        }
        parts = _parts_by_key()
        actual_c0402 = {key for key, part in parts.items() if part.ref.startswith("C") and part.package == "0402"}
        actual_c0805 = {key for key, part in parts.items() if part.ref.startswith("C") and part.package == "0805"}
        self.assertEqual(actual_c0402, expected_c0402)
        self.assertEqual(actual_c0805, expected_c0805)
        for (board_name, ref), part in sorted(parts.items()):
            if ref.startswith("R"):
                with self.subTest(board=board_name, ref=ref):
                    self.assertEqual(part.package, "0402")
                    self.assertRegex(part.footprint, r"^Resistor_SMD:R_0402")
            if ref.startswith("C"):
                with self.subTest(board=board_name, ref=ref):
                    self.assertRegex(part.footprint, rf"^Capacitor_SMD:C_{part.package}")

    def test_testpoints_are_bare_pads_excluded_from_bom_and_cpl(self) -> None:
        for board in build.BOARDS:
            testpoints = [part for part in board.parts if part.ref.startswith("TP")]
            self.assertEqual(len(testpoints), 8)
            for part in testpoints:
                with self.subTest(board=board.name, ref=part.ref):
                    self.assertEqual(part.assembly, "BARE_PAD")
                    self.assertTrue(part.exclude_from_bom)
                    self.assertTrue(part.exclude_from_cpl)
                    self.assertNotIn("Plated_Hole", part.footprint)
                    self.assertEqual(len(part.physical_pads), 1)
                    self.assertEqual(part.physical_pads[0].role, "testpoint")
                    self.assertEqual(part.physical_pads[0].layers, ("F.Cu", "F.Mask"))
                    self.assertNotIn("F.Paste", part.physical_pads[0].layers)

            with tempfile.TemporaryDirectory() as temporary:
                bom_path, cpl_path = factory_emit.write_bom_cpl(board, Path(temporary))
                with bom_path.open(encoding="utf-8", newline="") as handle:
                    bom_refs = {row["Designator"] for row in csv.DictReader(handle)}
                with cpl_path.open(encoding="utf-8", newline="") as handle:
                    cpl_refs = {row["Designator"] for row in csv.DictReader(handle)}
                for part in testpoints:
                    self.assertNotIn(part.ref, bom_refs)
                    self.assertNotIn(part.ref, cpl_refs)

    def test_two_board_placement_hole_and_keepout_contracts_are_exact(self) -> None:
        expected = {
            "wand": {
                "size": (15.0, 80.0),
                "placements": {
                    "J1": (12.25, 38.0, 90.0),
                    "SW1": (7.5, 64.5, 90.0),
                    "U1": (7.5, 10.5, 0.0),
                },
                "holes": {"H1": (7.5, 20.25, 2.4), "H2": (7.5, 77.0, 2.4)},
            },
            "receiver": {
                "size": (50.0, 42.0),
                "placements": {
                    "J1": (3.0, 19.0, 270.0),
                    "U1": (42.25, 11.0, 270.0),
                },
                "holes": {
                    "H1": (3.0, 3.0, 2.4), "H2": (47.0, 3.0, 2.4),
                    "H3": (15.0, 39.0, 2.4), "H4": (37.0, 39.0, 2.4),
                },
            },
        }
        for board_name, contract in expected.items():
            board = _board(board_name)
            with self.subTest(board=board_name):
                self.assertEqual((board.width, board.height), contract["size"])
                self.assertEqual(
                    {part.ref for part in board.parts if part.assembly == "NPTH"},
                    set(contract["holes"]),
                )
            for ref, placement in contract["placements"].items():
                part = next(row for row in board.parts if row.ref == ref)
                with self.subTest(board=board_name, ref=ref):
                    self.assertEqual((part.x, part.y, part.rotation), placement)
                    self.assertTrue(part.interface_datum)
            for ref, (x, y, drill) in contract["holes"].items():
                part = next(row for row in board.parts if row.ref == ref)
                with self.subTest(board=board_name, hole=ref):
                    self.assertEqual((part.x, part.y), (x, y))
                    self.assertEqual(part.assembly, "NPTH")
                    self.assertEqual(len(part.physical_pads), 1)
                    self.assertEqual(part.physical_pads[0].kind, "npth")
                    self.assertEqual(part.physical_pads[0].drill_width, drill)
                    self.assertEqual(part.physical_pads[0].drill_height, drill)

            electrical_by_name = {row["name"]: row for row in board.keepouts}
            self.assertFalse(any("NINA" in name for name in electrical_by_name))
            if board_name == "wand":
                self.assertEqual(electrical_by_name, {})
            else:
                self.assertEqual(set(electrical_by_name), {"LOW_VOLTAGE_ISOLATION_MOAT"})
                moat = electrical_by_name["LOW_VOLTAGE_ISOLATION_MOAT"]
                self.assertEqual(
                    (moat["x1"], moat["y1"], moat["x2"], moat["y2"]),
                    (38.0, 23.0, 40.5, 40.5),
                )
                self.assertEqual(set(moat["layers"]), {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"})

            planes = [row for row in board.plane_requirements if row.get("ref") == "U1"]
            self.assertEqual(len(planes), 1)
            plane = planes[0]
            self.assertEqual(plane["net"], "GND")
            self.assertEqual(plane["layers"], ["In1.Cu"])
            self.assertIs(plane["fullGround"], True)
            self.assertIs(plane["viaStitchingRequired"], True)
            self.assertEqual(len(plane["polygon"]), 4)
            if board_name == "wand":
                self.assertEqual(
                    plane["polygon"],
                    [[2.5, 3.0], [12.5, 3.0], [12.5, 18.0], [2.5, 18.0]],
                )

            mechanical = [row for row in board.mechanical_keepouts if row.get("ref") == "U1"]
            self.assertEqual(len(mechanical), 1)
            nina_keepout = mechanical[0]
            self.assertGreaterEqual(nina_keepout["minMetalOrLargeComponentClearanceMm"], 10.0)
            self.assertGreaterEqual(nina_keepout["minEnclosureClearanceMm"], 5.0)
            self.assertIn("outward", nina_keepout["antennaDirection"].casefold())
            self.assertIn("U1", nina_keepout["allowedRefs"])
            if board_name == "wand":
                self.assertEqual(nina_keepout["antennaDirection"], "source -Y / outward")
            else:
                self.assertEqual(nina_keepout["antennaDirection"], "source +X / outward")

    def test_both_nina_modules_preserve_every_ground_land(self) -> None:
        expected_ground_numbers = {"6", "12", "14", "26", "30", "53", "EGP"}
        expected_numbered = {
            str(number): (-4.125, round(-5.700 + number - 1, 3))
            for number in range(1, 11)
        }
        expected_numbered.update({
            str(number): (round(-2.000 + number - 11, 3), 3.225)
            for number in range(11, 16)
        })
        expected_numbered.update({
            str(number): (4.125, round(3.300 - (number - 16), 3))
            for number in range(16, 26)
        })
        expected_numbered.update({
            "26": (2.000, -5.625), "27": (1.000, -5.625), "28": (0.000, -5.625),
            "29": (-1.000, -5.625), "30": (-2.000, -5.625),
        })
        expected_numbered.update({
            str(number): (-2.750, round(-4.250 + (number - 31) * 1.10, 3))
            for number in range(31, 37)
        })
        expected_numbered.update({
            str(number): (2.750, round(1.250 - (number - 37) * 1.10, 3))
            for number in range(37, 43)
        })
        expected_numbered.update({
            str(number): (round(1.650 - (number - 43) * 1.10, 3), -4.250)
            for number in range(43, 47)
        })
        expected_numbered.update({
            str(number): (round(-4.250 + (55 - number), 3), -6.850)
            for number in range(47, 56)
        })
        expected_egp = (
            (-0.575, -2.925), (0.575, -2.925),
            (-1.725, -1.775), (-0.575, -1.775), (0.575, -1.775), (1.725, -1.775),
            (-0.575, -0.625), (0.575, -0.625),
            (-1.725, 0.525), (-0.575, 0.525), (0.575, 0.525), (1.725, 0.525),
        )
        for board_name in ("wand", "receiver"):
            part = _part(board_name, "U1")
            numbered_centers = {
                pad.number: (pad.x, pad.y)
                for pad in part.physical_pads
                if pad.number.isdigit()
            }
            egp_pads = [pad for pad in part.physical_pads if pad.number == "EGP"]
            ground_pins = {pin.number for pin in part.pins if pin.net == "GND"}
            physical_ground = {
                pad.number
                for pad in part.physical_pads
                if _net_for_physical_pad(part, pad) == "GND"
            }
            with self.subTest(board=board_name):
                self.assertEqual(part.mpn, "NINA-B302-00B-00")
                self.assertTrue(all(pad.shape == "rect" for pad in part.physical_pads))
                for number in ("26", "27", "28", "29", "30"):
                    pad = next(row for row in part.physical_pads if row.number == number)
                    self.assertEqual((pad.width, pad.height), (0.70, 1.15))
                self.assertEqual(len(part.physical_pads), 67)
                self.assertEqual(len({pad.physical_id for pad in part.physical_pads}), 67)
                self.assertEqual(numbered_centers, expected_numbered)
                self.assertEqual(
                    [(pad.physical_id, pad.x, pad.y) for pad in egp_pads],
                    [(f"egp-{index:02d}", x, y)
                     for index, (x, y) in enumerate(expected_egp, start=1)],
                )
                self.assertTrue(all(pad.width == 0.70 and pad.height == 0.70 for pad in egp_pads))
                self.assertTrue(all(pad.layers == ("F.Cu", "F.Paste", "F.Mask") for pad in egp_pads))
                self.assertTrue(all(pad.role == "thermal" for pad in egp_pads))
                self.assertTrue(all(_net_for_physical_pad(part, pad) == "GND" for pad in egp_pads))
                self.assertNotIn("EAGP", {pad.number for pad in part.physical_pads})
                self.assertEqual(part.body_height_mm, 4.23)
                self.assertEqual(part.interface_datum["moduleVariant"], "B3x2")
                self.assertEqual(part.interface_datum["antennaType"], "PIFA")
                self.assertIs(part.interface_datum["eagpRequired"], False)
                self.assertEqual(ground_pins, expected_ground_numbers)
                self.assertTrue(expected_ground_numbers <= physical_ground)
                self.assertEqual(Counter(pad.number for pad in part.physical_pads)["EGP"], 12)


class FactoryTableAndPcbEmissionTests(unittest.TestCase):
    def test_bom_and_cpl_exclude_every_nonfitted_or_explicitly_excluded_ref(self) -> None:
        for board in build.BOARDS:
            expected_bom = {
                part.ref
                for part in board.parts
                if not part.dnp
                and not part.exclude_from_bom
                and part.assembly not in {"NPTH", "BARE_PAD"}
            }
            expected_cpl = {
                part.ref
                for part in board.parts
                if part.assembly == "SMT_TOP"
                and not part.dnp
                and not part.exclude_from_cpl
            }
            with tempfile.TemporaryDirectory() as temporary:
                bom_path, cpl_path = factory_emit.write_bom_cpl(board, Path(temporary))
                with bom_path.open(encoding="utf-8", newline="") as handle:
                    bom_rows = list(csv.DictReader(handle))
                    actual_bom = {row["Designator"] for row in bom_rows}
                with cpl_path.open(encoding="utf-8", newline="") as handle:
                    actual_cpl = {row["Designator"] for row in csv.DictReader(handle)}
            with self.subTest(board=board.name, table="BOM"):
                self.assertEqual(actual_bom, expected_bom)
                by_ref = {part.ref: part for part in board.parts}
                for row in bom_rows:
                    self.assertEqual(
                        row["Footprint"],
                        factory_emit.factory_fpid(board, by_ref[row["Designator"]]),
                    )
            with self.subTest(board=board.name, table="CPL"):
                self.assertEqual(actual_cpl, expected_cpl)

        receiver = copy.deepcopy(_board("receiver"))
        explicitly_excluded = next(part for part in receiver.parts if part.ref == "U6")
        explicitly_excluded.exclude_from_bom = True
        explicitly_excluded.exclude_from_cpl = True
        with tempfile.TemporaryDirectory() as temporary:
            bom_path, cpl_path = factory_emit.write_bom_cpl(receiver, Path(temporary))
            with bom_path.open(encoding="utf-8", newline="") as handle:
                self.assertNotIn("U6", {row["Designator"] for row in csv.DictReader(handle)})
            with cpl_path.open(encoding="utf-8", newline="") as handle:
                self.assertNotIn("U6", {row["Designator"] for row in csv.DictReader(handle)})

    def test_write_pcb_emits_every_physical_entity_with_unique_uuid_and_geometry(self) -> None:
        for board in build.BOARDS:
            pads = build.absolute_pads(board)
            with tempfile.TemporaryDirectory() as temporary:
                pcb_path = factory_emit.write_pcb(board, Path(temporary), pads, [], [])
                pcb_text = pcb_path.read_text(encoding="utf-8")
            pad_lines = [
                line.strip()
                for line in pcb_text.splitlines()
                if line.lstrip().startswith("(pad ")
            ]
            self.assertEqual(len(pad_lines), len(pads))
            emitted_uuids: list[str] = []
            saw_oval_drill = False
            saw_local_rotation = False
            for pad in pads:
                physical_id = pad["physical_id"]
                expected_uuid = build.uid(board.name, "pad", pad["ref"], physical_id)
                matches = [line for line in pad_lines if f"(uuid {expected_uuid})" in line]
                with self.subTest(board=board.name, physical_id=physical_id):
                    self.assertEqual(len(matches), 1)
                    line = matches[0]
                    emitted_uuids.append(expected_uuid)
                    self.assertIn(f" {pad['shape']} ", line)
                    quoted_layers = " ".join(f'"{layer}"' for layer in pad["layers"])
                    self.assertIn(f"(layers {quoted_layers})", line)
                    at_match = re.search(r"\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", line)
                    self.assertIsNotNone(at_match)
                    self.assertAlmostEqual(float(at_match.group(1)), pad["local_x"], places=4)
                    self.assertAlmostEqual(float(at_match.group(2)), pad["local_y"], places=4)
                    if pad["rotation"]:
                        saw_local_rotation = True
                        self.assertIn(f" {pad['rotation']:.4f})", line)
                    if pad["drill_width"]:
                        if pad["drill_width"] != pad["drill_height"]:
                            saw_oval_drill = True
                            self.assertIn(
                                f"(drill oval {pad['drill_width']:.3f} {pad['drill_height']:.3f})",
                                line,
                            )
                        else:
                            self.assertIn(f"(drill {pad['drill_width']:.3f})", line)
                    role_property = f'"PhysicalPadRole.{physical_id}" "{pad["role"]}"'
                    self.assertIn(role_property, pcb_text)
            self.assertEqual(len(emitted_uuids), len(set(emitted_uuids)))
            self.assertTrue(saw_oval_drill, f"{board.name} must exercise oval drill width/height")
            self.assertTrue(saw_local_rotation, f"{board.name} must exercise local pad rotation")

    def test_receiver_effects_usb4105_footprint_model_and_dru_are_board_specific(self) -> None:
        receiver = receiver_effects.make_board()
        receiver_pads = build.absolute_pads(receiver, require_controlled=False)
        model_path = (
            "${KICAD10_3DMODEL_DIR}/Connector_USB.3dshapes/"
            "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.step"
        )
        jae_rule = '(rule "JAE SJ121837 internal locator geometry"'

        with tempfile.TemporaryDirectory() as temporary:
            receiver_out = Path(temporary) / "receiver-effects"
            receiver_out.mkdir()
            factory_emit.write_project(receiver, receiver_out)
            pcb_path = factory_emit.write_pcb(
                receiver, receiver_out, receiver_pads, [], []
            )
            footprint_path = (
                receiver_out
                / "MW_FACTORY.pretty"
                / "receiver-effects_J1.kicad_mod"
            )
            footprint_text = footprint_path.read_text(encoding="utf-8")
            pcb_text = pcb_path.read_text(encoding="utf-8")
            receiver_dru = (receiver_out / "receiver-effects.kicad_dru").read_text(
                encoding="utf-8"
            )
            fp_table = (receiver_out / "fp-lib-table").read_text(encoding="utf-8")

        self.assertIn("${KIPRJMOD}/MW_FACTORY.pretty", fp_table)
        self.assertEqual(footprint_text.count(f'(model "{model_path}"'), 1)
        self.assertEqual(pcb_text.count(f'(model "{model_path}"'), 1)
        self.assertEqual(
            len([
                line
                for line in footprint_text.splitlines()
                if line.lstrip().startswith("(pad ")
            ]),
            22,
        )
        self.assertNotIn(jae_rule, receiver_dru)
        self.assertNotIn("DX07S016JA1R1500", receiver_dru)

        with tempfile.TemporaryDirectory() as temporary:
            wand_out = Path(temporary) / "wand"
            wand_out.mkdir()
            factory_emit.write_project(_board("wand"), wand_out)
            wand_dru = (wand_out / "wand.kicad_dru").read_text(encoding="utf-8")
        self.assertIn(jae_rule, wand_dru)

    def test_wand_factory_placement_matches_native_drc_legalized_authority(self) -> None:
        wand = _board("wand")
        expected = {
            "L1": (11.5, 29.8), "J2": (3.3, 57.0), "SW1": (7.5, 64.5),
            "U6": (6.15, 38.0), "F1": (2.6, 38.0), "J1": (12.25, 38.0),
            "R_CC1": (2.0, 35.0), "R_CC2": (2.0, 43.0),
            "R_I2C_SDA": (2.0, 27.2), "R_ARM": (13.0, 62.0),
            "R_HAPTIC_EN": (10.7, 20.0), "R_STAT1": (13.5, 48.5),
            "R_STAT2": (5.0, 43.2), "R_CFG2": (1.2, 31.5),
            "C_USB": (1.8, 41.0), "C_CHG_IN": (11.7, 46.0),
            "C_BUCK_IN": (6.2, 26.6), "C_IMU_VDD": (1.3, 21.0),
            "C_IMU_IO": (3.8, 21.0), "C_HAPTIC_REG": (13.2, 20.0),
            "TP2": (13.0, 54.5), "TP7": (10.5, 54.5), "H1": (7.5, 20.25),
        }
        actual = {part.ref: (part.x, part.y) for part in wand.parts}
        for ref, coordinate in expected.items():
            with self.subTest(ref=ref):
                self.assertEqual(actual[ref], coordinate)
        rotations = {part.ref: part.rotation for part in wand.parts}
        self.assertEqual(rotations["L1"], 270.0)
        self.assertEqual(rotations["R_ISET"], 270.0)
        self.assertEqual(rotations["C_BUCK_IN"], 90.0)
        self.assertEqual(rotations["C_BUCK_OUT"], 270.0)

    def test_wand_haptic_enable_uses_outer_nina_gpio(self) -> None:
        wand = _board("wand")
        u1 = next(part for part in wand.parts if part.ref == "U1")
        pins = {pin.number: pin for pin in u1.pins}
        self.assertEqual(
            (pins["1"].name, pins["1"].net, pins["1"].electrical_type),
            ("P0.13", "HAPTIC_EN", "output"),
        )
        self.assertEqual((pins["44"].net, pins["44"].electrical_type), ("NC", "no_connect"))

    def test_project_rules_allow_jlcpcb_standard_small_vias(self) -> None:
        wand = _board("wand")
        with tempfile.TemporaryDirectory() as temporary:
            project = json.loads(
                factory_emit.write_project(wand, Path(temporary)).read_text(encoding="utf-8")
            )
        rules = project["board"]["design_settings"]["rules"]
        self.assertEqual(rules["min_through_hole_diameter"], 0.15)
        self.assertEqual(rules["min_via_diameter"], 0.30)
        self.assertEqual(rules["min_via_annular_width"], 0.075)
        self.assertEqual(rules["min_hole_clearance"], 0.20)
        classes = {row["name"]: row for row in project["net_settings"]["classes"]}
        self.assertEqual(
            (classes["Default"]["via_diameter"], classes["Default"]["via_drill"]),
            (0.45, 0.20),
        )
        self.assertEqual(
            (classes["POWER"]["via_diameter"], classes["POWER"]["via_drill"]),
            (0.55, 0.25),
        )

    def test_native_pcb_is_centered_on_a4_without_mutating_board_local_geometry(self) -> None:
        for board in build.BOARDS:
            pads = build.absolute_pads(board)
            original_parts = [(part.ref, part.x, part.y) for part in board.parts]
            original_keepouts = copy.deepcopy(board.keepouts)
            net = next(pad["net"] for pad in pads if pad.get("net") not in {"", "NC"})
            segments = [{"net": net, "start": [1.0, 2.0], "end": [3.0, 4.0], "width": 0.2, "layer": "F.Cu"}]
            vias = [{"net": net, "x": 2.0, "y": 3.0, "size": 0.55, "drill": 0.25}]
            with tempfile.TemporaryDirectory() as temporary:
                pcb_text = factory_emit.write_pcb(
                    board, Path(temporary), pads, segments, vias
                ).read_text(encoding="utf-8")
            origin_x, origin_y = factory_emit.worksheet_board_origin(board)
            self.assertAlmostEqual(origin_x + board.width / 2.0, 297.0 / 2.0)
            self.assertAlmostEqual(origin_y + board.height / 2.0, 210.0 / 2.0)
            self.assertIn(
                f"(start {origin_x:.3f} {origin_y:.3f}) (end {origin_x + board.width:.3f} {origin_y:.3f})",
                pcb_text,
            )
            self.assertIn(
                f"(segment (start {origin_x + 1.0:.4f} {origin_y + 2.0:.4f}) (end {origin_x + 3.0:.4f} {origin_y + 4.0:.4f})",
                pcb_text,
            )
            self.assertIn(f"(via (at {origin_x + 2.0:.4f} {origin_y + 3.0:.4f})", pcb_text)
            self.assertEqual(original_parts, [(part.ref, part.x, part.y) for part in board.parts])
            self.assertEqual(original_keepouts, board.keepouts)


class RouteAuthorityBindingTests(unittest.TestCase):
    def test_route_source_design_binds_authority_layers_roles_and_physical_ids(self) -> None:
        for board in build.BOARDS:
            pads = build.absolute_pads(board)
            binding = factory_emit.route_source_design(board, pads)
            components = {row["ref"]: row for row in binding["criticalComponents"]}
            bound_pads = binding["criticalPads"]
            with self.subTest(board=board.name):
                self.assertEqual(set(components), {part.ref for part in board.parts})
                self.assertEqual(len(bound_pads), len(pads))
                self.assertEqual(
                    Counter((row["ref"], row["physicalPadId"]) for row in bound_pads),
                    Counter((row["ref"], row["physical_id"]) for row in pads),
                )
            for part in board.parts:
                row = components[part.ref]
                with self.subTest(board=board.name, ref=part.ref):
                    self.assertEqual(row["authority"], part.land_pattern_authority)
                    self.assertEqual(row["bodyDatum"], build.body_datum_payload(part))
            expected_by_id = {(pad["ref"], pad["physical_id"]): pad for pad in pads}
            for row in bound_pads:
                expected_pad = expected_by_id[(row["ref"], row["physicalPadId"])]
                with self.subTest(board=board.name, ref=row["ref"], physicalPadId=row["physicalPadId"]):
                    self.assertEqual(row["layers"], expected_pad["layers"])
                    self.assertEqual(row["role"], expected_pad["role"])
                    self.assertEqual(row["localPositionMm"], [expected_pad["local_x"], expected_pad["local_y"]])
                    self.assertEqual(row["localRotationDeg"], expected_pad["local_rotation"])

            reversed_binding = factory_emit.route_source_design(board, list(reversed(pads)))
            self.assertEqual(reversed_binding, binding)

            plane_mutation = copy.deepcopy(board)
            plane_mutation.plane_requirements[0]["fullGround"] = False
            self.assertNotEqual(
                factory_emit.route_source_design(
                    plane_mutation, build.absolute_pads(plane_mutation)
                )["sha256"],
                binding["sha256"],
            )
            mechanical_mutation = copy.deepcopy(board)
            mechanical_mutation.mechanical_keepouts[0][
                "minMetalOrLargeComponentClearanceMm"
            ] += 0.01
            self.assertNotEqual(
                factory_emit.route_source_design(
                    mechanical_mutation, build.absolute_pads(mechanical_mutation)
                )["sha256"],
                binding["sha256"],
            )

    def test_frozen_route_fixture_rejects_authority_pad_body_and_datum_mutations(self) -> None:
        clean = copy.deepcopy(_board("wand"))
        clean_pads = build.absolute_pads(clean)
        source_design = factory_emit.route_source_design(clean, clean_pads)

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "magic-wand"
            electronics = project / "electronics"
            board_dir = electronics / "wand"
            board_dir.mkdir(parents=True)
            board_path = board_dir / "wand.kicad_pcb"
            report_path = board_dir / "wand-native-drc.rpt"
            fixture_path = board_dir / "wand-frozen-routes.json"
            board_path.write_bytes(b"controlled board source\n")
            report_path.write_bytes(
                b"Found 0 DRC violations\nFound 0 unconnected pads\nFound 0 Footprint errors\n"
            )
            fixture = {
                "schema": "aicad.frozen-pcb-routes.v1",
                "status": "DRC_FROZEN",
                "revision": "LAND-PATTERN-AUTHORITY-TEST",
                "board": "wand",
                "boardDimensionsMm": [clean.width, clean.height, 1.6],
                "sourceDesign": source_design,
                "sourceBoard": _artifact_reference(board_path, "electronics/wand/wand.kicad_pcb"),
                "nativeDrc": {
                    **_artifact_reference(report_path, "electronics/wand/wand-native-drc.rpt"),
                    "violations": 0,
                    "unconnected": 0,
                    "footprintErrors": 0,
                    "exclusions": 0,
                    "suppressions": 0,
                },
                "routes": [{"net": "GND", "layer": "F.Cu", "width": 0.2, "points": [[1, 1], [2, 2]]}],
                "vias": [],
            }
            fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

            old_root = factory_emit.ROOT
            factory_emit.ROOT = electronics
            try:
                factory_emit.resolved_routes(clean, clean_pads)
                mutations = {
                    "authority": self._mutate_authority,
                    "physical-pad-id": self._mutate_pad,
                    "body": self._mutate_body,
                    "datum": self._mutate_datum,
                }
                for label, mutate in mutations.items():
                    candidate = copy.deepcopy(clean)
                    mutate(candidate)
                    with self.subTest(mutation=label), self.assertRaises(ValueError):
                        candidate_pads = build.absolute_pads(candidate)
                        factory_emit.resolved_routes(candidate, candidate_pads)
            finally:
                factory_emit.ROOT = old_root

    @staticmethod
    def _mutate_authority(board) -> None:
        part = next(row for row in board.parts if row.ref == "J1")
        part.land_pattern_authority["revision"] += "-MUTATED"

    @staticmethod
    def _mutate_pad(board) -> None:
        part = next(row for row in board.parts if row.ref == "J1")
        part.physical_pads[0] = replace(
            part.physical_pads[0],
            physical_id=part.physical_pads[0].physical_id + "-MUTATED",
        )
        part.land_pattern_authority["physicalPads"] = build.physical_pad_rows(part.physical_pads)
        part.land_pattern_authority["physicalPadFingerprint"] = build.physical_pad_fingerprint(part.physical_pads)

    @staticmethod
    def _mutate_body(board) -> None:
        part = next(row for row in board.parts if row.ref == "J1")
        bounds = part.fab_bounds or (-part.width / 2, -part.height / 2, part.width / 2, part.height / 2)
        part.fab_bounds = (bounds[0], bounds[1], bounds[2] + 0.01, bounds[3])
        part.land_pattern_authority["bodyDatum"] = build.body_datum_payload(part)
        part.land_pattern_authority["bodyDatumFingerprint"] = build.body_datum_fingerprint(part)

    @staticmethod
    def _mutate_datum(board) -> None:
        part = next(row for row in board.parts if row.ref == "J1")
        part.interface_datum["mutationProbe"] = 0.01
        part.land_pattern_authority["bodyDatum"] = build.body_datum_payload(part)
        part.land_pattern_authority["bodyDatumFingerprint"] = build.body_datum_fingerprint(part)


if __name__ == "__main__":
    unittest.main()
