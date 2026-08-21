from __future__ import annotations

import copy
import csv
import hashlib
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
                    "J1": (12.5, 38.0, 90.0),
                    "SW1": (7.5, 63.0, 90.0),
                    "U1": (7.5, 10.5, 0.0),
                },
                "holes": {"H1": (7.5, 19.5, 2.4), "H2": (7.5, 77.0, 2.4)},
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
