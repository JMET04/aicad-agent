from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
import zipfile
from pathlib import Path

from build123d import import_step


ROOT = Path(__file__).resolve().parent
GENERATOR = ROOT / "build_printable_wand.py"
OUTPUT_ROOT = ROOT / "outputs"


def load_generator():
    spec = importlib.util.spec_from_file_location("printable_wand_build_under_test", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load printable wand generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class PrintableWandGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.m = load_generator()
        cls.factory_design_path, factory_design = cls.m.load_frozen_factory_design()
        component_envelopes, component_envelope_records = (
            cls.m.make_pcb_component_envelopes(factory_design)
        )
        fastener_tool_sweeps, fastener_tool_sweep_records = (
            cls.m.make_fastener_tool_sweeps()
        )
        cls.parts = {
            "upper_shell": cls.m.make_upper_shell(),
            "lower_shell": cls.m.make_lower_shell(),
            "carrier": cls.m.make_carrier(),
            "rear_cap": cls.m.make_rear_cap(),
            "rod_connector": cls.m.make_rod_connector(),
            "plunger": cls.m.make_button_plunger(),
            "plunger_retainer": cls.m.make_button_retainer(),
            "pcb": cls.m.make_pcb_placeholder(),
            "battery": cls.m.make_battery_placeholder(),
            "haptic": cls.m.make_haptic_placeholder(),
            "switch": cls.m.make_switch_placeholder(),
            "rod": cls.m.make_rod_placeholder(),
            "usb_plug_sweep": cls.m.make_usb_plug_sweep(),
            "pcb_component_envelopes": component_envelopes,
            "pcb_component_envelope_records": component_envelope_records,
            "fastener_tool_sweeps": fastener_tool_sweeps,
            "fastener_tool_sweep_records": fastener_tool_sweep_records,
        }
        pcb_path = cls.m.resolve_repository_file(str(cls.m.PCB["path"]))
        cls.validation = cls.m.build_validation(
            cls.parts, pcb_path, cls.factory_design_path
        )
        cls.checks = cls.validation["checks"]

    def test_frozen_electromechanical_contract(self) -> None:
        self.assertEqual(self.m.HANDLE["outerDiameter"], 30.0)
        self.assertEqual(self.m.HANDLE["length"], 110.0)
        self.assertEqual(
            self.m.PCB["sha256"],
            "37A1C04E8D6853818B9986AA8F82979D658341A8BA4A3B3FC5CB4FCB19B23AF9",
        )
        mounts = {item["ref"]: item["caseCenter"] for item in self.m.PCB["mounts"]}
        self.assertEqual(mounts, {"H1": [0.0, 0.0, 29.25], "H2": [0.0, 0.0, 86.0]})
        interfaces = self.m.PCB["interfaces"]
        self.assertEqual(interfaces["usbC"]["caseCenter"], [4.75, 0.0, 47.0])
        self.assertEqual(interfaces["button"]["caseCenter"], [0.0, 0.0, 73.5])
        self.assertEqual(self.m.BUTTON["plunger"]["headRadius"], 2.3)
        self.assertEqual(self.m.BUTTON["plunger"]["headLength"], 1.8)

    def test_geometry_closure_is_passed_but_physical_gates_stay_open(self) -> None:
        self.assertTrue(self.validation["geometryChecksPassed"])
        self.assertEqual(
            self.validation["status"],
            "GEOMETRY_VERIFIED_PHYSICAL_GATES_OPEN",
        )
        self.assertFalse(self.validation["physicalAcceptanceGates"]["allClosed"])
        gates = self.validation["physicalAcceptanceGates"]
        self.assertFalse(gates["pcbComponentEnvelopeVerified"])
        self.assertFalse(gates["fastenerToolSweepVerified"])
        self.assertNotEqual(self.validation["status"], "VERIFIED_PRINT_CANDIDATE")

    def test_carrier_clearance_and_retention(self) -> None:
        self.assertEqual(self.checks["carrierSolidCount"], 1)
        self.assertAlmostEqual(self.checks["carrierBossReliefRadiusMm"], 2.95, places=3)
        self.assertGreaterEqual(self.checks["carrierAxialStopClearanceMm"], 0.30)
        self.assertGreaterEqual(self.checks["carrierLateralKeyClearanceMm"], 0.30)
        self.assertLessEqual(self.checks["upperShellToCarrierCollisionMm3"], 0.01)
        self.assertLessEqual(self.checks["lowerShellToCarrierCollisionMm3"], 0.01)

    def test_real_component_envelopes_and_fastener_service_sweeps(self) -> None:
        self.assertTrue(self.checks["sourceFactoryDesignSha256Matches"])
        self.assertEqual(self.checks["pcbComponentEnvelopeCount"], 36)
        self.assertEqual(
            self.checks["pcbComponentEnvelopeCount"],
            self.checks["pcbComponentEnvelopeExpectedCount"],
        )
        self.assertEqual(self.checks["pcbComponentEnvelopeCollisionReferences"], [])
        self.assertLessEqual(
            self.checks["shellToPcbComponentEnvelopeCollisionMm3"], 0.01
        )
        self.assertLessEqual(
            self.checks["carrierToPcbComponentEnvelopeCollisionMm3"], 0.01
        )
        self.assertEqual(self.checks["fastenerToolSweepCount"], 4)
        self.assertGreaterEqual(
            self.checks["fastenerToolSweepRadialClearanceMm"], 0.20
        )
        self.assertLessEqual(
            self.checks["fastenerToolSweepToUpperShellCollisionMm3"], 0.01
        )
        self.assertLessEqual(
            self.checks["fastenerToolSweepToInternalReservedVolumeCollisionMm3"],
            0.01,
        )

    def test_battery_maximum_envelope_has_service_clearance(self) -> None:
        self.assertEqual(self.m.POWER["maximumEnvelope"], [11.0, 6.0, 42.0])
        self.assertGreaterEqual(self.checks["batterySideClearancePerSideMm"], 0.35)
        self.assertGreaterEqual(self.checks["batteryAxialClearancePerEndMm"], 0.30)
        self.assertTrue(self.checks["batteryRetentionStrategyPresent"])
        self.assertGreaterEqual(self.checks["wireBendReserveMm"], 8.0)
        self.assertLessEqual(self.checks["carrierToBatteryCollisionMm3"], 0.01)

    def test_button_released_pressed_retained_and_hard_stopped(self) -> None:
        for key in (
            "upperShellToPlungerReleasedCollisionMm3",
            "upperShellToPlungerPressedCollisionMm3",
            "upperShellToRetainerReleasedCollisionMm3",
            "upperShellToRetainerPressedCollisionMm3",
            "plungerToRetainerCollisionMm3",
            "switchBodyToShellCollisionMm3",
            "switchBodyToCarrierCollisionMm3",
        ):
            self.assertLessEqual(self.checks[key], 0.01, key)
        self.assertGreater(self.checks["buttonReleasedSwitchGapMm"], 0.0)
        self.assertGreater(self.checks["buttonPressedActuationMm"], 0.0)
        self.assertLessEqual(
            self.checks["buttonPressedActuationMm"],
            self.checks["buttonMaximumSwitchTravelMm"],
        )
        self.assertAlmostEqual(self.checks["buttonHardStopTravelMm"], 0.25, places=3)
        self.assertGreater(self.checks["buttonRetainerRadialCaptureMm"], 0.0)

    def test_usb_service_sweep_and_unchanged_opening(self) -> None:
        self.assertEqual(self.m.USB["externalOpeningSize"], [10.2, 5.2])
        self.assertAlmostEqual(self.checks["usbRecessMm"], 6.634, places=3)
        self.assertGreaterEqual(self.checks["usbPlugLateralClearanceMm"], 0.30)
        self.assertGreaterEqual(self.checks["usbPlugVerticalClearanceMm"], 0.30)
        self.assertGreaterEqual(self.checks["usbReachMarginMm"], 0.0)
        self.assertLessEqual(self.checks["usbPlugSweepToShellCollisionMm3"], 0.01)

    def test_split_planes_and_full_length(self) -> None:
        self.assertLessEqual(self.checks["upperSplitFaceBelowY0Mm"], 0.01)
        self.assertLessEqual(self.checks["lowerSplitFaceAboveY0Mm"], 0.01)
        self.assertAlmostEqual(self.checks["completeAssemblyOverallLengthMm"], 316.0, places=3)
        self.assertAlmostEqual(self.checks["targetAssemblyOverallLengthMm"], 316.0, places=3)


class PrintableWandReleaseTests(unittest.TestCase):
    def test_release_outputs_and_hashes(self) -> None:
        manifest_path = OUTPUT_ROOT / "release-manifest.json"
        report_path = OUTPUT_ROOT / "reports" / "fit-and-power-validation.json"
        zip_path = OUTPUT_ROOT / "MW_PRINTABLE_WAND_REV_A0.zip"
        sidecar_path = OUTPUT_ROOT / "MW_PRINTABLE_WAND_REV_A0.sha256"
        for path in (manifest_path, report_path, zip_path, sidecar_path):
            self.assertTrue(path.is_file(), f"missing generated output: {path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "GEOMETRY_VERIFIED_PHYSICAL_GATES_OPEN")
        self.assertTrue(report["geometryChecksPassed"])
        self.assertTrue(report["meshValidation"]["passed"])
        self.assertIsNotNone(manifest["sourceTest"])
        self.assertEqual(
            manifest["sourceFactoryDesign"]["sha256"],
            "A0DBC115AEE2E0C3D3DC2949EB48A66F8CA304E8A973C279EBB7B0609E883687",
        )
        self.assertEqual(manifest["sourceTest"]["sha256"], file_sha256(Path(__file__)))

        expected_hash = sidecar_path.read_text(encoding="ascii").split()[0].upper()
        self.assertEqual(expected_hash, file_sha256(zip_path))
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            self.assertIn("source/design-input.json", names)
            self.assertIn("source/build_printable_wand.py", names)
            self.assertIn("source/test_printable_wand.py", names)
            self.assertIn("source/wand-factory-design.json", names)
            expected_time = (2026, 8, 22, 0, 0, 0)
            self.assertTrue(all(info.date_time == expected_time for info in archive.infolist()))

    def test_export_counts_and_step_reopen(self) -> None:
        stl_paths = sorted((OUTPUT_ROOT / "stl").glob("*.stl"))
        step_paths = sorted((OUTPUT_ROOT / "step").glob("*.step"))
        self.assertEqual(len(stl_paths), 7)
        self.assertEqual(len(step_paths), 9)
        printable_steps = [
            path
            for path in step_paths
            if path.name.startswith("MW-P-00") and "assembly" not in path.name
        ]
        self.assertEqual(len(printable_steps), 7)
        for path in printable_steps:
            reopened = import_step(path)
            self.assertEqual(len(reopened.solids()), 1, path.name)
            self.assertGreater(float(reopened.volume), 0.0, path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

