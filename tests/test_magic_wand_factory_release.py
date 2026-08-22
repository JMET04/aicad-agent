from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "projects" / "magic-wand" / "factory-release" / "build_factory_release.py"
SPEC = importlib.util.spec_from_file_location("magic_wand_factory_release", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import magic-wand factory-release builder")
factory_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(factory_release)


def _write(path: Path, payload: str | bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    path.write_bytes(data)
    return {
        "path": path.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _artifact(path: str, kind: str, digest_character: str = "a") -> dict[str, Any]:
    return {
        "path": path,
        "size": 1,
        "sha256": digest_character * 64,
        "kind": kind,
    }


def _wand_ref(
    ref: str,
    source: tuple[float, float],
    *,
    manufacturer: str,
    mpn: str,
    body: list[float] | None = None,
    maximum_height: float = 1.0,
    geometry: Any = None,
) -> dict[str, Any]:
    x, y = source
    return {
        "ref": ref,
        "manufacturer": manufacturer,
        "mpn": mpn,
        "authorityEvidence": _artifact(f"electronics/authority/{ref}.json", "land_pattern_authority"),
        "sourceCenterMm": [x, y],
        "caseCenterMm": [x - 7.5, 1.6, y + 9.0],
        "rotationDeg": 0.0,
        "bodyEnvelopeMm": body or [1.0, 1.0, 1.0],
        "maximumHeightMm": maximum_height,
        "padOrHoleGeometry": geometry if geometry is not None else {"physicalCount": 1},
        "roundTripCoordinateEvidence": {"passed": True, "toleranceMm": 1e-6},
    }


def _valid_wand_interface() -> dict[str, Any]:
    board = _artifact("electronics/wand/wand.kicad_pcb", "kicad_board", "b")
    routes = {
        **_artifact("electronics/wand/wand-frozen-routes.json", "frozen_routes", "c"),
        "sourceBoard": copy.deepcopy(board),
    }
    drc = {
        **_artifact("electronics/wand/wand-native-drc.rpt", "native_drc_report", "d"),
        "violations": 0,
        "unconnected": 0,
        "footprintErrors": 0,
        "exclusions": 0,
        "suppressions": 0,
        "ignoredRules": [],
    }

    switch_pads = [{"physicalId": str(index + 1)} for index in range(4)]
    sw1 = _wand_ref(
        "SW1", (7.5, 63.0),
        manufacturer="ALPS Alpine", mpn="SKQGAFE010",
        body=[5.2, 5.2, 1.5], maximum_height=1.5,
        geometry=switch_pads,
    )
    sw1.update({
        "rotationDeg": 90.0,
        "freeHeightMm": 1.5,
        "travelMm": 0.25,
        "forceN": 1.6,
        "actuatorCenterCaseMm": [0.0, 3.1, 72.0],
        "actuationNormal": "+Y",
        "fourPhysicalPadGeometry": copy.deepcopy(switch_pads),
        "logicalTerminalPairMap": [["1A", "1B"], ["2A", "2B"]],
        "allowedPreloadMm": 0.05,
        "allowedOvertravelMm": 0.05,
    })

    contact_names = [
        "A1", "B12", "A4", "B9", "A5", "B5", "A6", "B6",
        "A7", "B7", "A8", "B8", "A9", "B4", "A12", "B1",
    ]
    contacts = [{"name": name} for name in contact_names]
    stakes = [{"physicalId": str(index + 1), "type": "DIP"} for index in range(4)]
    locators = [{"physicalId": "L1"}, {"physicalId": "L2"}]
    j1 = _wand_ref(
        "J1", (12.5, 38.0),
        manufacturer="JAE", mpn="DX07S016JA1R1500",
        body=[10.0, 5.0, 3.0], maximum_height=3.0,
        geometry={
            "contactPads": contacts,
            "shellDipStakes": stakes,
            "locatingHoles": locators,
        },
    )
    panel_opening = {
        "ref": "J1",
        "wallAxis": "+X",
        "caseCenterMm": [5.0, 1.6, 47.0],
        "widthMm": 10.0,
        "heightMm": 4.0,
        "cornerRadiusMm": 1.0,
        "cutDepthMm": 3.0,
        "tolerancesMm": {"width": 0.1, "height": 0.1},
        "matingDirection": "+X",
        "authoritySha256": j1["authorityEvidence"]["sha256"],
    }
    j1.update({
        "rotationDeg": 90.0,
        "officialDrawingNumber": "SJ121837",
        "sixteenContactPads": copy.deepcopy(contacts),
        "fourShellDipStakes": copy.deepcopy(stakes),
        "locatingHoles": copy.deepcopy(locators),
        "matingFaceMm": [5.0, 1.6, 47.0],
        "matingDirection": "+X",
        "matingEnvelopeMm": [10.0, 5.0, 8.0],
        "unmateClearanceMm": 10.0,
        "panelOpening": copy.deepcopy(panel_opening),
    })

    j2_geometry = {
        "signalPads": [{"id": str(index + 1)} for index in range(3)],
        "reinforcementPads": [{"id": "MP1"}, {"id": "MP2"}],
    }
    j2 = _wand_ref(
        "J2", (2.5, 50.0),
        manufacturer="JST", mpn="SM03B-SRSS-TB(LF)(SN)",
        geometry=j2_geometry,
    )
    j2["matingDirection"] = "-Z"
    j3_geometry = {
        "signalPads": [{"id": str(index + 1)} for index in range(2)],
        "reinforcementPads": [{"id": "MP1"}, {"id": "MP2"}],
    }
    j3 = _wand_ref(
        "J3", (12.5, 50.0),
        manufacturer="JST", mpn="SM02B-SRSS-TB(LF)(SN)",
        geometry=j3_geometry,
    )
    j3["matingDirection"] = "-Z"

    u1 = _wand_ref(
        "U1", (7.5, 10.5),
        manufacturer="u-blox", mpn="NINA-B302-00B-00",
        body=[10.0, 15.0, 4.23], maximum_height=4.23,
    )
    keepout = _artifact("electronics/wand/nina-mechanical-keepout.json", "mechanical_keepout", "e")
    u1.update({
        "antennaFeedCorner": "board_top_edge",
        "antennaDirection": "-Z_outward",
        "fullGroundEvidence": _artifact("electronics/wand/nina-full-ground.json", "ground_evidence", "f"),
        "mechanicalKeepoutSolid": copy.deepcopy(keepout),
        "caseClearanceEvidence": _artifact("electronics/wand/nina-case-clearance.json", "clearance_evidence", "1"),
    })

    l1 = _wand_ref(
        "L1", (7.5, 30.0),
        manufacturer="Coilcraft", mpn="XFL4020-222MEC",
        body=[4.3, 4.3, 2.1], maximum_height=2.1,
    )
    f1 = _wand_ref(
        "F1", (7.5, 35.0),
        manufacturer="Bourns", mpn="MF-FSMF050X-2",
        body=[1.85, 1.05, 1.0], maximum_height=1.0,
    )
    holes = []
    for ref, source in (("H1", (7.5, 19.5)), ("H2", (7.5, 77.0))):
        hole_geometry = {"type": "NPTH", "finishedDiameterMm": 2.4}
        row = _wand_ref(
            ref, source,
            manufacturer="PCB feature", mpn=f"{ref}-NPTH-2.4",
            body=[2.4, 2.4, 1.6], maximum_height=0.0,
            geometry=hole_geometry,
        )
        row.update({"finishedDiameterMm": 2.4, "type": "NPTH", "plating": False})
        holes.append(row)

    requirements = {
        "rearCapChangeRequired": True,
        "pcbRetentionProcess": {
            "type": "nonmetallic_heat_stake",
            "holeRefs": ["H1", "H2"],
            "metallicFastenersAllowed": False,
            "minimumAntennaMetalClearanceMm": 10.0,
            "supplierProcessValidationRequired": True,
        },
        "buttonStack": {
            "switchRef": "SW1",
            "actuatorCenterCaseMm": [0.0, 3.1, 72.0],
            "actuationNormal": "+Y",
            "switchFreeTopCaseYmm": 3.1,
            "switchTravelMm": 0.25,
            "allowedPreloadMm": 0.05,
            "allowedOvertravelMm": 0.05,
            "independentHardStopRequired": True,
            "bottomStopClearanceRequired": True,
        },
        "boardChannel": {
            "boardEnvelopeMm": [15.0, 80.0, 1.6],
            "bCuSupportYmm": 0.0,
            "fCuYmm": 1.6,
            "caseZStartMm": 9.0,
            "datumScheme": "one_side_width_datum_opposite_clearance_one_axial_stop",
            "minimumNominalWidthClearancePerSideMm": 0.1,
            "minimumNominalAxialClearanceMm": 0.2,
            "positiveWorstCaseClearanceRequired": True,
        },
        "j1PanelOpening": copy.deepcopy(panel_opening),
        "ninaMechanicalKeepout": {
            "ref": "U1",
            "artifact": copy.deepcopy(keepout),
            "minimumHighLargeMetalClearanceMm": 10.0,
            "minimumCasingClearanceMm": 5.0,
            "forbiddenClasses": [
                "metal_fastener", "conductive_coating", "battery_cell",
                "shield_can", "cable_bundle", "GFRP_spine",
            ],
            "fullGroundRequired": True,
            "rearCapIntersectionRequiresChange": True,
        },
    }
    return {
        "schema": "aicad_wand_electromechanical_interface_v1",
        "status": "FROZEN",
        "revision": "R1",
        "authorityReleaseBlockedRefs": 0,
        "sourceBoard": board,
        "sourceRoutes": routes,
        "nativeDrc": drc,
        "coordinateContract": {
            "source": {
                "origin": "top-left", "xAxis": "right", "yAxis": "down",
                "units": "mm", "boardWidthMm": 15.0, "boardHeightMm": 80.0,
            },
            "forwardTransform": {
                "X": "x_source-7.5", "Y": "heightFromBCu", "Z": "y_source+9.0",
            },
            "inverseTransform": {
                "x_source": "X+7.5", "y_source": "Z-9.0", "heightFromBCu": "Y",
            },
            "requiredRoundTripToleranceMm": 1e-6,
            "roundTripTests": [{
                "name": "board-origin",
                "sourceCenterMm": [0.0, 0.0],
                "caseCenterMm": [-7.5, 0.0, 9.0],
                "passed": True,
            }],
        },
        "boardDimensionsMm": {
            "width": 15.0, "height": 80.0, "thickness": 1.6,
            "tolerances": {"width": 0.1, "height": 0.1, "thickness": 0.1},
        },
        "refs": [sw1, j1, j2, j3, u1, l1, f1, *holes],
        "absentRefs": ["H3", "H4"],
        "consistencyEvidence": {
            "boardShaMatchesRoutes": True,
            "roundTripCoordinateTests": True,
            "authorityHashClosure": True,
            "mechanicalRequirementMirrorChecks": True,
        },
        "mechanicalRequirements": requirements,
    }

class FactoryReleaseUnitTests(unittest.TestCase):
    def test_expected_subject_and_four_layer_closure_is_exact(self) -> None:
        self.assertEqual(len(factory_release.EXPECTED_PART_IDS), 9)
        self.assertEqual(factory_release.EXPECTED_ASSEMBLY_IDS, {"MW-A-001", "MW-A-101"})
        self.assertEqual(
            factory_release.EXPECTED_FABRICATION_LAYERS,
            {
                "F.Cu", "In1.Cu", "In2.Cu", "B.Cu",
                "F.Paste", "B.Paste", "F.Mask", "B.Mask",
                "F.SilkS", "B.SilkS", "Edge.Cuts",
            },
        )

    def test_nonportable_probe_wip_temp_and_session_paths_fail_closed(self) -> None:
        invalid = [
            "C:/factory/part.step",
            "/factory/part.step",
            "../factory/part.step",
            "electronics/probe-wand/board.kicad_pcb",
            "electronics/wip-final/board.kicad_pcb",
            "electronics/temp/board.kicad_pcb",
            "electronics/wand/wand.kicad_prl",
            "electronics\\wand\\board.kicad_pcb",
        ]
        for path in invalid:
            with self.subTest(path=path), self.assertRaises(factory_release.ReleaseBuildError):
                factory_release._safe_relative(path, "test")

    def test_artifact_mutation_is_rejected_against_frozen_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "evidence.bin"
            reference = _write(path, b"frozen factory evidence")
            old_root = factory_release.PROJECT_ROOT
            factory_release.PROJECT_ROOT = root
            try:
                factory_release.verify_artifact_reference(reference, location="artifact")
                path.write_bytes(path.read_bytes() + b" mutated")
                with self.assertRaisesRegex(factory_release.ReleaseBuildError, "mutation/stale lock"):
                    factory_release.verify_artifact_reference(reference, location="artifact")
            finally:
                factory_release.PROJECT_ROOT = old_root

    def test_native_kicad_report_parser_requires_zero_erc_drc_and_unconnected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            erc = _write(
                root / "erc.rpt",
                "** ERC messages: 0  Errors 0  Warnings 0\n",
            )
            drc = _write(
                root / "drc.rpt",
                "** Found 0 DRC violations **\n** Found 0 unconnected pads **\n** Found 0 Footprint errors **\n** End of Report **\n",
            )
            old_root = factory_release.PROJECT_ROOT
            factory_release.PROJECT_ROOT = root
            try:
                factory_release._validate_native_gate_reports(
                    {"ercReport": erc, "drcReport": drc}, "board"
                )
                bad_drc = _write(
                    root / "drc.rpt",
                    "** Found 0 DRC violations **\n** Found 1 unconnected pads **\n[unconnected_items]: open net\n",
                )
                with self.assertRaisesRegex(factory_release.ReleaseBuildError, "unconnected"):
                    factory_release._validate_native_gate_reports(
                        {"ercReport": erc, "drcReport": bad_drc}, "board"
                    )
            finally:
                factory_release.PROJECT_ROOT = old_root

    def test_receiver_coordinate_transform_is_recomputed_bidirectionally(self) -> None:
        interface = {
            "status": "frozen_electronics_native_drc",
            "coordinateContract": {
                "source": {
                    "id": "KICAD_BOARD_XY", "origin": "top-left",
                    "x": "right", "y": "down", "units": "mm",
                },
                "intermediate": {
                    "id": "PCB_BOTTOM_LEFT_XY", "origin": "bottom-left",
                    "x": "right", "y": "up", "units": "mm",
                },
                "target": {
                    "id": "RECEIVER_CASE_XY", "origin": "case-center",
                    "x": "right", "y": "up", "units": "mm",
                },
                "boardSizeMm": [50, 42, 1.6],
                "equations": [
                    "x_board=x_k", "y_board=42-y_k",
                    "x_case=x_board-25", "y_case=y_board-21",
                ],
                "caseShiftMm": [-25, -21],
                "transformVerified": True,
            },
            "holes": [{
                "id": "H1", "sourceKicadXY": [5, 10],
                "boardBottomLeftXY": [5, 32], "caseMechanicalXY": [-20, 11],
                "diameterMm": 3.2, "transformMatch": True,
            }],
            "connectors": [{
                "ref": "J1", "sourceKicadXY": [45, 4],
                "boardBottomLeftXY": [45, 38], "caseMechanicalXY": [20, 17],
                "panel": "right", "panelNormal": "+X", "tangentCenterMm": 17,
                "zCenterMm": 4, "openingWidthMm": 10, "openingHeightMm": 4,
                "cornerRadiusMm": 1, "cutDepthMm": 3, "transformMatch": True,
            }],
            "rfKeepout": {
                "sourceKicadPolygon": [[0, 0], [10, 0], [10, 10]],
                "boardBottomLeftPolygon": [[0, 42], [10, 42], [10, 32]],
                "caseMechanicalPolygon": [[-25, 21], [-15, 21], [-15, 11]],
                "transformMatch": True,
            },
        }
        result = factory_release.validate_receiver_coordinate_contract(interface)
        self.assertEqual(len(result["holes"]), 1)
        self.assertEqual(len(result["connectors"]), 1)
        broken = copy.deepcopy(interface)
        broken["holes"][0]["boardBottomLeftXY"] = [5, 31.5]
        with self.assertRaisesRegex(ValueError, "transform mismatch"):
            factory_release.validate_receiver_coordinate_contract(broken)

    def test_formal_nested_probe_and_wip_paths_fail_closed(self) -> None:
        invalid = [
            "electronics/evidence/native/probe-receiver-v232/receiver.kicad_pcb",
            "electronics/receiver/final-WIP/receiver.kicad_pcb",
            "electronics/receiver/temp-output/receiver.kicad_pcb",
        ]
        for path in invalid:
            with self.subTest(path=path), self.assertRaisesRegex(
                factory_release.ReleaseBuildError, "probe/WIP/temp"
            ):
                factory_release._assert_no_banned_path_strings(
                    {"sourceBoard": {"path": path}}, "formal"
                )

    def test_mechanical_primary_and_compatibility_manifests_may_only_differ_by_schema(self) -> None:
        primary = {
            "schema": "aicad_magic_wand_mechanical_factory_delivery_manifest_v1",
            "status": "frozen",
            "parts": [{"partId": "MW-M-001A"}],
        }
        compatibility = {
            **copy.deepcopy(primary),
            "schema": "aicad_magic_wand_mechanical_source_manifest_v1",
        }
        self.assertTrue(
            factory_release.manifests_equivalent(primary, compatibility)
        )
        compatibility["parts"][0]["partId"] = "MUTATED"
        self.assertFalse(
            factory_release.manifests_equivalent(primary, compatibility)
        )


    def test_wand_frozen_contract_positive_is_semantically_closed(self) -> None:
        interface = _valid_wand_interface()
        semantics = factory_release.wand_interface_semantics(interface)
        self.assertEqual(semantics["schema"], "aicad_wand_electromechanical_interface_v1")
        self.assertEqual(semantics["status"], "FROZEN")
        self.assertEqual(semantics["authorityReleaseBlockedRefs"], 0)
        self.assertEqual({row["ref"] for row in semantics["refs"]}, {
            "SW1", "J1", "J2", "J3", "U1", "L1", "F1", "H1", "H2",
        })
        self.assertEqual(set(semantics["absentRefs"]), {"H3", "H4"})

    def test_wand_release_gate_coordinate_and_kind_mutations_fail_closed(self) -> None:
        broken = _valid_wand_interface()
        broken["status"] = "candidate"
        with self.assertRaisesRegex(ValueError, "exactly FROZEN"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        broken["authorityReleaseBlockedRefs"] = 1
        with self.assertRaisesRegex(ValueError, "integer 0"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        next(row for row in broken["refs"] if row["ref"] == "SW1")["caseCenterMm"][2] += 0.1
        with self.assertRaisesRegex(ValueError, "transform mismatch"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        broken["sourceRoutes"]["sourceBoard"].pop("kind")
        with self.assertRaisesRegex(ValueError, "kind"):
            factory_release.wand_interface_semantics(broken)

    def test_wand_switch_usb_hole_and_button_mutations_fail_closed(self) -> None:
        broken = _valid_wand_interface()
        next(row for row in broken["refs"] if row["ref"] == "SW1")[
            "fourPhysicalPadGeometry"
        ].pop()
        with self.assertRaisesRegex(ValueError, "four physical pads"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        next(row for row in broken["refs"] if row["ref"] == "J1")[
            "sixteenContactPads"
        ].pop()
        with self.assertRaisesRegex(ValueError, "sixteen-contact"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        next(row for row in broken["refs"] if row["ref"] == "H1")["plating"] = True
        with self.assertRaisesRegex(ValueError, "non-plated NPTH"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        broken["mechanicalRequirements"]["buttonStack"]["independentHardStopRequired"] = False
        with self.assertRaisesRegex(ValueError, "hard stop"):
            factory_release.wand_interface_semantics(broken)

    def test_wand_nina_channel_and_mirror_mutations_fail_closed(self) -> None:
        broken = _valid_wand_interface()
        broken["mechanicalRequirements"]["ninaMechanicalKeepout"][
            "minimumCasingClearanceMm"
        ] = 4.99
        with self.assertRaisesRegex(ValueError, "NINA"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        broken["mechanicalRequirements"]["boardChannel"][
            "minimumNominalWidthClearancePerSideMm"
        ] = 0.0
        with self.assertRaisesRegex(ValueError, "positive-clearance"):
            factory_release.wand_interface_semantics(broken)

        broken = _valid_wand_interface()
        broken["consistencyEvidence"]["mechanicalRequirementMirrorChecks"] = False
        with self.assertRaisesRegex(ValueError, "mechanicalRequirementMirrorChecks"):
            factory_release.wand_interface_semantics(broken)

    def test_wand_nested_probe_wip_temp_and_absolute_paths_fail_closed(self) -> None:
        invalid = [
            "electronics/probe-wand/wand.kicad_pcb",
            "electronics/wand/WIP/wand.kicad_pcb",
            "electronics/wand/temp-routes/wand-frozen-routes.json",
            "C:/" + "Users/operator/wand-native-drc.rpt",
        ]
        for path in invalid:
            broken = _valid_wand_interface()
            broken["sourceRoutes"]["sourceBoard"]["path"] = path
            with self.subTest(path=path), self.assertRaises(
                factory_release.ReleaseBuildError
            ):
                factory_release._assert_no_banned_path_strings(
                    broken, "wandInterface"
                )

LOCK_PATH = REPO_ROOT / "projects" / "magic-wand" / "factory-release" / "source-lock.json"


@unittest.skipUnless(LOCK_PATH.is_file(), "upstream final source manifests are not frozen yet")
class FactoryReleaseFrozenIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock, cls.package = factory_release._load_locked_package()
        cls.report = factory_release.validate_manufacturing_release_package(
            cls.package, factory_release.PROJECT_ROOT
        )
        cls.built = factory_release.PROJECT_ROOT / "factory-release" / "built"

    def test_package_subject_role_preview_and_readiness_closure(self) -> None:
        self.assertEqual(self.package["schema"], "aicad_manufacturing_release_package_v1")
        self.assertEqual(
            {row["partId"] for row in self.package["mechanical"]["parts"]},
            factory_release.EXPECTED_PART_IDS,
        )
        self.assertEqual(
            {row["assemblyId"] for row in self.package["mechanical"]["assemblies"]},
            factory_release.EXPECTED_ASSEMBLY_IDS,
        )
        self.assertEqual(len(self.package["electronics"]["pcbs"]), 2)
        self.assertTrue(self.report["factoryRfqCandidateReady"])
        self.assertTrue(self.report["prototypeFabricationCandidateReady"])
        self.assertTrue(self.report["digitalPackageReady"])
        self.assertFalse(self.report["factoryHandoffReady"])
        self.assertFalse(self.report["productionReady"])
        self.assertFalse(self.report["toolSteelCutAuthorized"])
        self.assertFalse(self.report["massProductionAuthorized"])
        self.assertEqual(self.report["counts"]["mechanicalSubjects"], 11)
        self.assertEqual(self.report["counts"]["pcbs"], 2)
        self.assertEqual(self.report["counts"]["actualPreviewsExpected"], 32)
        self.assertEqual(self.report["counts"]["actualPreviewsVerified"], 32)

    def test_all_package_and_lock_references_are_exact_and_portable(self) -> None:
        references = [
            *factory_release._walk_evidence_refs(self.package),
            *factory_release._walk_evidence_refs(self.lock),
        ]
        self.assertGreater(len(references), 100)
        for location, reference in references:
            path_text = reference["path"]
            with self.subTest(location=location, path=path_text):
                factory_release._safe_relative(path_text, location)
                self.assertNotRegex(path_text.casefold(), r"(?:^|/)(?:probe|wip|temp|tmp)(?:[-_/]|$)")
                self.assertNotIn(".kicad_prl", path_text.casefold())
                factory_release.verify_artifact_reference(reference, location=location)

    def test_receiver_interface_sha_is_identical_and_mechanically_consumed(self) -> None:
        closure = self.lock["receiverInterface"]
        reference = closure["artifact"]
        self.assertEqual(reference["sha256"], closure["consumedSha256"])
        path = factory_release.verify_artifact_reference(
            reference, location="sourceLock.receiverInterface.artifact"
        )
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), closure["consumedSha256"])
        board = factory_release.verify_artifact_reference(
            closure["sourceBoard"], location="sourceLock.receiverInterface.sourceBoard"
        )
        self.assertEqual(hashlib.sha256(board.read_bytes()).hexdigest(), closure["sourceBoard"]["sha256"])
        routes_path = factory_release.verify_artifact_reference(
            closure["frozenRoutes"], location="sourceLock.receiverInterface.frozenRoutes"
        )
        routes = json.loads(routes_path.read_text(encoding="utf-8"))
        self.assertEqual(
            routes["coordinateSystem"],
            {"origin": "board_top_left", "x": "right", "y": "down", "units": "mm"},
        )
        self.assertEqual(routes["sourceBoard"]["sha256"], closure["sourceBoard"]["sha256"])
        self.assertEqual(
            closure["coordinateContract"]["equations"],
            ["x_board=x_k", "y_board=42-y_k", "x_case=x_board-25", "y_case=y_board-21"],
        )
        self.assertEqual(closure["coordinateContract"]["caseShiftMm"], [-25, -21])
        self.assertGreater(closure["holeCount"], 0)
        self.assertGreater(closure["connectorCount"], 0)
        self.assertGreaterEqual(closure["rfKeepoutVertexCount"], 3)


    def test_wand_interface_board_routes_drc_and_mechanical_consumption_close(self) -> None:
        closure = self.lock["wandInterface"]
        self.assertEqual(closure["schema"], "aicad_wand_electromechanical_interface_v1")
        self.assertEqual(closure["status"], "FROZEN")
        self.assertEqual(closure["authorityReleaseBlockedRefs"], 0)
        self.assertEqual(closure["artifact"]["sha256"], closure["consumedSha256"])
        self.assertEqual(closure["artifact"]["path"], factory_release.WAND_INTERFACE_REL)
        interface_path = factory_release.verify_artifact_reference(
            closure["artifact"], location="sourceLock.wandInterface.artifact"
        )
        self.assertEqual(
            hashlib.sha256(interface_path.read_bytes()).hexdigest(),
            closure["consumedSha256"],
        )

        board_path = factory_release.verify_artifact_reference(
            closure["sourceBoard"], location="sourceLock.wandInterface.sourceBoard"
        )
        routes_path = factory_release.verify_artifact_reference(
            closure["sourceRoutes"], location="sourceLock.wandInterface.sourceRoutes"
        )
        native_drc_path = factory_release.verify_artifact_reference(
            closure["nativeDrc"], location="sourceLock.wandInterface.nativeDrc"
        )
        routes = json.loads(routes_path.read_text(encoding="utf-8"))
        self.assertEqual(
            routes["coordinateSystem"],
            {"origin": "board_top_left", "x": "right", "y": "down", "units": "mm"},
        )
        self.assertEqual(routes["boardDimensionsMm"], [15.0, 80.0, 1.6])
        self.assertEqual(
            hashlib.sha256(board_path.read_bytes()).hexdigest(),
            routes["sourceBoard"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(native_drc_path.read_bytes()).hexdigest(),
            closure["nativeDrc"]["sha256"],
        )
        self.assertEqual(closure["boardHashClosureDeclarations"], 6)
        semantic = closure["semanticClosure"]
        self.assertEqual(semantic["switch"]["travelMm"], 0.25)
        self.assertEqual(semantic["switch"]["physicalPadCount"], 4)
        self.assertTrue(semantic["switch"]["buttonStack"]["independentHardStopRequired"])
        self.assertEqual(semantic["usb"]["matingDirection"], "+X")
        self.assertEqual(semantic["usb"]["contactCount"], 16)
        self.assertEqual(semantic["usb"]["shellDipStakeCount"], 4)
        self.assertEqual(semantic["usb"]["locatingHoleCount"], 2)
        self.assertEqual(
            {(row["ref"], row["finishedDiameterMm"], row["type"], row["plating"])
             for row in semantic["mountHoles"]},
            {("H1", 2.4, "NPTH", False), ("H2", 2.4, "NPTH", False)},
        )
        self.assertEqual(set(semantic["absentRefs"]), {"H3", "H4"})
        self.assertTrue(semantic["nina"]["requirements"]["fullGroundRequired"])
        self.assertGreaterEqual(
            semantic["nina"]["requirements"]["minimumHighLargeMetalClearanceMm"], 10.0
        )
        self.assertGreaterEqual(
            semantic["nina"]["requirements"]["minimumCasingClearanceMm"], 5.0
        )

    def test_both_pcb_native_gate_assertions_are_exact_zero(self) -> None:
        assertions = self.lock["gateAssertions"]
        self.assertEqual(len(assertions), 2)
        for pcb_id, row in assertions.items():
            with self.subTest(pcb_id=pcb_id):
                self.assertEqual(
                    {key: row[key] for key in factory_release.ZERO_GATE_KEYS},
                    {key: 0 for key in factory_release.ZERO_GATE_KEYS},
                )
                factory_release._validate_native_gate_reports(row, pcb_id)

    def test_built_reviewer_dom_and_portable_public_reports_close(self) -> None:
        review = self.built / "magic-wand-factory-release.review.html"
        validation = self.built / "magic-wand-factory-release.validation.json"
        delivery = self.built / "magic-wand-factory-release.delivery-manifest.json"
        self.assertTrue(review.is_file())
        self.assertTrue(validation.is_file())
        self.assertTrue(delivery.is_file())
        page = review.read_text(encoding="utf-8")
        contract = factory_release.validate_manufacturing_release_review_html(page)
        self.assertTrue(contract["actualPreviewClosurePass"])
        self.assertEqual(contract["subjectCount"], 13)
        self.assertEqual(contract["actualPreviewRendered"], 32)
        self.assertEqual(page.count('<article class="subject-card"'), 26)
        self.assertIn('data-view-mode="2d"', page)
        self.assertIn('data-view-mode="3d"', page)
        self.assertIn('data-text-box="true"', page)
        self.assertIn('data-legend-only="true"', page)
        public_text = validation.read_text(encoding="utf-8") + page
        self.assertNotIn("resolvedPath", public_text)
        self.assertNotRegex(public_text, r"(?i)[A-Z]:[\\/]|file://|users[\\/]")

    def test_delivery_manifest_hashes_and_safety_locks_are_exact(self) -> None:
        path = self.built / "magic-wand-factory-release.delivery-manifest.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "aicad_magic_wand_factory_delivery_manifest_v1")
        readiness = document["readiness"]
        self.assertTrue(readiness["factoryRfqCandidateReady"])
        self.assertTrue(readiness["prototypeFabricationCandidateReady"])
        self.assertTrue(readiness["digitalPackageReady"])
        for key in (
            "factoryHandoffReady", "productionReady", "productionReleaseAuthorized",
            "toolSteelCutAuthorized", "massProductionAuthorized",
        ):
            self.assertFalse(readiness[key])
        for row in document["files"]:
            target = factory_release.PROJECT_ROOT.joinpath(*PurePosixPath(row["path"]).parts)
            with self.subTest(path=row["path"]):
                self.assertTrue(target.is_file())
                self.assertEqual(target.stat().st_size, row["size"])
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), row["sha256"])

    def test_package_reference_mutation_fails_without_touching_real_evidence(self) -> None:
        reference = next(
            reference
            for _, reference in factory_release._walk_evidence_refs(self.package)
            if reference["path"].endswith(".step")
        )
        source = factory_release._resolved_project_file(reference["path"], "source")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root.joinpath(*PurePosixPath(reference["path"]).parts)
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes() + b"mutation")
            old_root = factory_release.PROJECT_ROOT
            factory_release.PROJECT_ROOT = root
            try:
                with self.assertRaisesRegex(factory_release.ReleaseBuildError, "mutation/stale lock"):
                    factory_release.verify_artifact_reference(reference, location="mutated")
            finally:
                factory_release.PROJECT_ROOT = old_root


if __name__ == "__main__":
    unittest.main()
