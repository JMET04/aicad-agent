from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

import ezdxf


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "projects" / "magic-wand" / "mechanical"
sys.path.insert(0, str(REPO_ROOT / "src"))

from aicad.engine import PlanError, compile_plan


PART_NAMES = ("handle_shell", "internal_carrier", "rear_end_cap", "rod_connector")
DRAWING_NAMES = (*PART_NAMES, "wand_general_arrangement")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} does not contain an object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MagicWandMechanicalPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.params = load_json(PACKAGE / "design-parameters.json")
        cls.layout = load_json(PACKAGE / "assembly-layout.json")

    def test_printable_release_json_and_zip_paths_are_portable(self) -> None:
        printable = PACKAGE / "printable-wand"
        outputs = printable / "outputs"
        expected_pcb = "projects/magic-wand/electronics/wand/wand.kicad_pcb"

        def assert_portable_json(value, label: str, field: str | None = None) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    assert_portable_json(child, f"{label}.{key}", str(key))
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    assert_portable_json(child, f"{label}[{index}]", field)
                return
            if not isinstance(value, str):
                return

            normalized = value.replace("\\", "/")
            lower = normalized.casefold()
            windows_absolute = (
                len(value) >= 3
                and value[0].isalpha()
                and value[1] == ":"
                and value[2] in "/\\"
            )
            self.assertNotIn("\\", value, label)
            self.assertFalse(windows_absolute, label)
            self.assertNotIn("/" + "users/", f"/{lower.lstrip('/')}", label)
            self.assertNotIn("/" + "home/", f"/{lower.lstrip('/')}", label)
            if field is not None and field.casefold().endswith("path"):
                pure = PurePosixPath(value)
                self.assertFalse(pure.is_absolute(), label)
                self.assertNotIn("..", pure.parts, label)
                self.assertNotIn(":", value, label)

        design = load_json(printable / "design-input.json")
        report = load_json(outputs / "reports" / "fit-and-power-validation.json")
        self.assertEqual(design["sourcePcb"]["path"], expected_pcb)
        self.assertEqual(report["sourcePcb"]["path"], expected_pcb)
        for path in [printable / "design-input.json", *sorted(outputs.rglob("*.json"))]:
            assert_portable_json(json.loads(path.read_text(encoding="utf-8")), path.as_posix())

        archive_path = outputs / "MW_PRINTABLE_WAND_REV_A0.zip"
        with zipfile.ZipFile(archive_path) as archive:
            json_members = []
            for member in archive.namelist():
                pure = PurePosixPath(member)
                self.assertNotIn("\\", member, member)
                self.assertNotIn(":", member, member)
                self.assertFalse(pure.is_absolute(), member)
                self.assertNotIn("..", pure.parts, member)
                if member.endswith(".json"):
                    json_members.append(member)
                    payload = json.loads(archive.read(member).decode("utf-8"))
                    assert_portable_json(payload, f"ZIP:{member}")
            self.assertEqual(
                set(json_members),
                {
                    "source/design-input.json",
                    "source/wand-factory-design.json",
                    "release-manifest.json",
                    "reports/fit-and-power-validation.json",
                },
            )

    def test_printable_json_gate_rejects_host_specific_and_traversal_paths(self) -> None:
        printable = PACKAGE / "printable-wand"
        generator = load_module(
            printable / "build_printable_wand.py",
            "mw_printable_portability_test",
        )
        bad_paths = (
            "C:\\" + r"Users\alice\private.json",
            "C:/" + "Users/alice/private.json",
            "/" + "home/alice/private.json",
            "/tmp/private.json",
            "../private.json",
            r"\\server\share\private.json",
        )
        with tempfile.TemporaryDirectory() as raw:
            fixture = Path(raw) / "candidate.json"
            for index, value in enumerate(bad_paths):
                with self.subTest(index=index, value=value):
                    fixture.write_text(json.dumps({"path": value}), encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "packaged JSON"):
                        generator.validate_packaged_json_portability([fixture])

    def test_single_parameter_source_controls_envelope_and_safety_locks(self) -> None:
        p = self.params
        stack = (
            p["rear_end_cap"]["exposed_length"]
            + p["handle_shell"]["length"]
            + p["rod_connector"]["exposed_length"]
            + p["gfrp_spine"]["exposed_length"]
        )
        self.assertEqual(p["units"], "mm")
        self.assertAlmostEqual(stack, 315.0)
        self.assertAlmostEqual(stack, p["envelope"]["overall_length"])
        self.assertAlmostEqual(
            p["rear_end_cap"]["exposed_length"] + p["handle_shell"]["length"],
            p["envelope"]["grip_segment_length"],
        )
        self.assertAlmostEqual(p["handle_shell"]["outer_diameter"], 27.0)
        self.assertAlmostEqual(p["gfrp_spine"]["nominal_diameter"], 7.0)
        self.assertAlmostEqual(p["gfrp_spine"]["exposed_length"], 190.0)
        locks = p["safety_locks"]
        self.assertTrue(locks["reviewOnly"])
        self.assertTrue(locks["human_engineering_review_required"])
        for key in (
            "accepted", "technicalPackageReady", "manufacturingAuthorized",
            "fabricationAuthorized", "productionReleaseEligible",
        ):
            self.assertFalse(locks[key], key)

    def test_wall_thickness_and_interface_clearances_are_positive_and_consistent(self) -> None:
        p = self.params
        shell = p["handle_shell"]
        carrier = p["internal_carrier"]
        self.assertAlmostEqual((shell["outer_diameter"] - shell["inner_diameter"]) / 2, shell["wall_thickness"])
        self.assertAlmostEqual((carrier["outer_width"] - carrier["inner_width"]) / 2, carrier["wall_thickness"])
        self.assertAlmostEqual((carrier["outer_height"] - carrier["inner_height"]) / 2, carrier["wall_thickness"])
        radial_clearance = (shell["inner_diameter"] - math.hypot(carrier["outer_width"], carrier["outer_height"])) / 2
        self.assertGreaterEqual(radial_clearance, carrier["minimum_corner_clearance_to_shell_id"])
        self.assertAlmostEqual(radial_clearance, self.layout["derived_checks"]["carrier_minimum_radial_corner_clearance_mm"], places=6)
        for key in ("rear_end_cap", "rod_connector"):
            self.assertAlmostEqual(shell["inner_diameter"] - p[key]["plug_diameter"], p[key]["diametral_clearance_to_shell"])
        self.assertAlmostEqual(
            p["rod_connector"]["spine_bore_diameter"] - p["gfrp_spine"]["nominal_diameter"],
            p["rod_connector"]["spine_bore_nominal_clearance"],
        )

    def test_press_to_arm_location_is_controlled_and_missing_side_cut_is_not_hidden(self) -> None:
        press = self.params["press_to_arm"]
        self.assertEqual(press["center_z_from_rear_outer_datum"], self.layout["functional_datums"]["press_to_arm_center_z"])
        self.assertGreater(press["center_z_from_rear_outer_datum"], 0)
        self.assertLess(press["center_z_from_rear_outer_datum"], self.params["envelope"]["grip_segment_length"])
        self.assertGreater(press["actuator_aperture_diameter"], 0)
        self.assertGreaterEqual(press["minimum_recess_below_guard_surface"], 0.6)
        self.assertEqual(press["3d_representation"], "datum_only_blocked_side_plane_feature")
        blockers = load_json(PACKAGE / "CAPABILITY_BLOCKERS.json")
        self.assertIn("MW-BLK-001", {row["id"] for row in blockers["blockers"]})
        blocker_text = json.dumps(blockers, ensure_ascii=False).casefold()
        self.assertIn("side aperture", blocker_text)
        self.assertIn("z=72", blocker_text)

    def test_antenna_keepout_is_nonconductive_and_separated_from_battery_and_spine(self) -> None:
        keepout = self.params["antenna_keepout"]
        functional = self.layout["functional_datums"]
        self.assertEqual(functional["antenna_keepout"]["global_z_min"], keepout["axial_start_z"])
        self.assertEqual(functional["antenna_keepout"]["global_z_max"], keepout["axial_end_z"])
        self.assertGreater(keepout["axial_end_z"], keepout["axial_start_z"])
        self.assertGreaterEqual(
            functional["provisional_battery_z"][0] - keepout["axial_end_z"],
            keepout["minimum_clearance_to_battery"],
        )
        spine = next(row for row in self.layout["placements"] if row["part_number"] == "MW-P-001")
        self.assertGreaterEqual(spine["global_z_min"] - keepout["axial_end_z"], keepout["minimum_clearance_to_gfrp_spine"])
        self.assertTrue({"metal_fastener", "battery_cell", "gfrp_spine"}.issubset(keepout["forbidden_item_classes"]))
        self.assertIn("nonconductive", self.params["rear_end_cap"]["prototype_material"].casefold())
        rf_closure = load_json(PACKAGE / "CAPABILITY_BLOCKERS.json")["blockers"][3]["required_closure"].casefold()
        self.assertIn("nina-b302 integration authority", rf_closure)

    def test_generated_sources_are_current_and_hash_bound_to_parameters(self) -> None:
        generator = load_module(PACKAGE / "build_package.py", "mw_build_package_test")
        generated = generator.generate(check=True)
        self.assertEqual(len(generated), 14)
        manifest = load_json(PACKAGE / "generated-source-manifest.json")
        source = manifest["parameterSource"]
        self.assertEqual(source["sha256"], sha256_file(PACKAGE / source["path"]))
        for row in manifest["files"]:
            path = PACKAGE / row["path"]
            self.assertEqual(path.stat().st_size, row["size"], row["path"])
            self.assertEqual(sha256_file(path), row["sha256"], row["path"])

    def test_3d_part_plans_encode_the_declared_axial_interfaces(self) -> None:
        plans = {name: load_json(PACKAGE / "plans3d" / f"{name}.plan.json") for name in PART_NAMES}
        for name, plan in plans.items():
            self.assertEqual(plan["part"]["domain"], "mechanical", name)
            self.assertTrue(plan["part"]["review_policy"]["reviewOnly"], name)
            self.assertFalse(plan["part"]["review_policy"]["accepted"], name)
            self.assertEqual(plan["engineering_normative_preflight"]["contractId"], "MW_MECHANICAL_CONTROLLED_GENERATION_PREFLIGHT_A")
        shell_features = {row["id"]: row for row in plans["handle_shell"]["features"]}
        self.assertEqual(shell_features["F001"]["profile"]["radius"], 13.5)
        self.assertEqual(shell_features["F002"]["profile"]["radius"], 11.5)
        self.assertEqual(shell_features["F001"]["depth"], 110.0)
        connector = {row["id"]: row for row in plans["rod_connector"]["features"]}
        self.assertEqual(connector["F003"]["profile"]["radius"] * 2, self.params["rod_connector"]["spine_bore_diameter"])

    def test_notes_are_centered_inside_closed_frames_in_every_drawing_plan(self) -> None:
        for name in DRAWING_NAMES:
            with self.subTest(drawing=name):
                plan = load_json(PACKAGE / "drawings2d" / f"{name}.drawing.plan.json")
                steps = {row["id"]: row for row in plan["steps"]}
                self.assertTrue({"N1", "N2", "N3", "N4", "NT"}.issubset(steps))
                x0, y0 = steps["N1"]["start"]["point"]
                x1, y1 = steps["N2"]["construction"]["target"]["point"]
                tx, ty = steps["NT"]["insert"]["point"]
                self.assertLess(x0, tx)
                self.assertLess(tx, x1)
                self.assertLess(y0, ty)
                self.assertLess(ty, y1)
                self.assertEqual(steps["N4"]["constraints"][-1], {"kind": "end_coincident", "target": "N1.start"})
                self.assertEqual(steps["NT"]["layer"], "NOTES")
                self.assertGreater(len(steps["NT"]["value"]), 5)
                compile_plan(plan)

    def test_dxf_layers_are_visually_differentiated_by_the_local_profile(self) -> None:
        profile = load_json(PACKAGE / "drawing-style-profile.json")["layers"]
        style_module = load_module(PACKAGE / "apply_drawing_styles.py", "mw_apply_styles_test")
        result = style_module.run(check=True)
        self.assertEqual(result["status"], "passed")
        for name in DRAWING_NAMES:
            with self.subTest(drawing=name):
                path = PACKAGE / "artifacts" / "2d" / name / f"{name}.dxf"
                document = ezdxf.readfile(path)
                outline = document.layers.get("OUTLINE")
                center = document.layers.get("CENTER")
                self.assertEqual(outline.dxf.lineweight, profile["OUTLINE"]["lineweight"])
                self.assertEqual(center.dxf.lineweight, profile["CENTER"]["lineweight"])
                self.assertGreater(outline.dxf.lineweight, center.dxf.lineweight)
                self.assertEqual(center.dxf.linetype.upper(), "CENTER2")
                if "HIDDEN" in document.layers:
                    self.assertEqual(document.layers.get("HIDDEN").dxf.linetype.upper(), "DASHED2")
                if "KEEP_OUT" in document.layers:
                    self.assertEqual(document.layers.get("KEEP_OUT").dxf.linetype.upper(), "DASHED")

    def test_native_part_artifacts_pass_save_reopen_and_hash_verification(self) -> None:
        for name in PART_NAMES:
            with self.subTest(part=name):
                directory = PACKAGE / "artifacts" / "3d" / name
                manifest = load_json(directory / f"{name}.3d.manifest.json")
                native = manifest["native_host_validation"]
                expected_prefix = f"projects/magic-wand/mechanical/artifacts/3d/{name}/"
                expected_artifact_keys = {"source", "execution", "audit", "sldprt", "step", "host_report", "reopen_report"}
                self.assertEqual(set(manifest["artifacts"]), expected_artifact_keys)
                for artifact_path in manifest["artifacts"].values():
                    self.assertFalse(Path(artifact_path).is_absolute(), artifact_path)
                    self.assertNotIn("\\", artifact_path)
                    self.assertTrue(artifact_path.startswith(expected_prefix), artifact_path)
                    resolved = REPO_ROOT / artifact_path
                    self.assertTrue(resolved.is_file(), resolved)

                self.assertEqual(native["status"], "passed")
                self.assertTrue(native["native_topology_authority"])
                self.assertEqual(native["unresolved_required_reference_count"], 0)
                file_map = {
                    "sldprt": directory / f"{name}.SLDPRT",
                    "step": directory / f"{name}.step",
                    "solidworks_report": directory / f"{name}.solidworks-report.json",
                    "reopen_report": directory / f"{name}.reopen-report.json",
                }
                for key, path in file_map.items():
                    self.assertTrue(path.is_file(), path)
                    self.assertGreater(path.stat().st_size, 0, path)
                    self.assertEqual(sha256_file(path), native["file_sha256"][key], key)

    def test_preflight_and_bom_remain_review_only(self) -> None:
        preflight = load_json(PACKAGE / "evidence" / "preflight-report.json")
        self.assertEqual(preflight["status"], "pass")
        self.assertEqual(preflight["counts"]["canonicalGates"], 54)
        self.assertEqual(preflight["counts"]["contractGates"], 54)
        self.assertEqual(preflight["counts"]["unresolvedGates"], 0)
        self.assertFalse(preflight["locks"]["manufacturingAuthorized"])
        bom = load_json(PACKAGE / "bom.json")
        self.assertEqual(bom["status"], "prototype_quote_only_not_release")
        self.assertEqual({row["part_number"] for row in bom["rows"]}, {"MW-M-001", "MW-M-002", "MW-M-003", "MW-M-004", "MW-P-001", "MW-C-001"})
        self.assertTrue(all(row["quantity"] > 0 for row in bom["rows"]))
        self.assertFalse(bom["release_locks"]["productionReleaseEligible"])

    def test_system_rev_b_traces_to_current_printable_geometry_and_locks(self) -> None:
        system = load_json(REPO_ROOT / "projects" / "magic-wand" / "system-requirements.json")
        status = load_json(REPO_ROOT / "projects" / "magic-wand" / "integration" / "CURRENT_SYSTEM_STATUS.json")
        printable = load_json(PACKAGE / "printable-wand" / "design-input.json")
        requirements = {row["id"]: row for row in system["requirements"]}

        self.assertEqual(set(requirements), {f"SYS-{index:03d}" for index in range(1, 13)})
        self.assertEqual(system["projectId"], self.params["project_id"])
        self.assertEqual(system["revision"], "B")
        self.assertEqual(self.params["revision"], "A")
        self.assertEqual(printable["design"], "Magic Wand printable enclosure Rev A0")
        self.assertEqual(system["authoritativeStatus"], "integration/CURRENT_SYSTEM_STATUS.json")
        self.assertEqual(status["schema"], "magic-wand.current-system-status.v2")

        sys001 = requirements["SYS-001"]
        overall = printable["rod"]["assembledOverallLength"]
        grip = printable["handle"]["outerDiameter"]
        exposed = printable["rod"]["exposedAboveConnector"]
        self.assertEqual((overall, grip, exposed), (316.0, 30.0, 179.0))
        self.assertEqual(sys001["category"], "mechanical")
        for value in (overall, grip, exposed):
            self.assertIn(str(int(value)), sys001["acceptance"])
        self.assertEqual(
            sys001["status"],
            "digital_geometry_and_mesh_verified_physical_first_article_pending",
        )
        self.assertEqual(status["printableEnclosure"]["handleOuterDiameterMm"], grip)
        self.assertEqual(status["printableEnclosure"]["rod"]["targetOverallLengthMm"], overall)
        self.assertEqual(status["printableEnclosure"]["meshGate"]["status"], "PASSED")

        sys002 = requirements["SYS-002"]
        self.assertIn("continuously held", sys002["requirement"].casefold())
        self.assertTrue(status["firmware"]["physicalArmGate"])
        self.assertEqual(status["systemInterfaces"]["pressToArm"], "+Y face at case z=73.5 mm")
        button = printable["sourcePcb"]["interfaces"]["button"]
        self.assertEqual(button["openingFace"], "+Y")
        self.assertEqual(button["caseCenter"][2], 73.5)
        self.assertIn("pending", sys002["status"])

        sys007 = requirements["SYS-007"]
        self.assertIn("nina-b302", sys007["requirement"].casefold())
        self.assertIn("nonconductive", sys007["requirement"].casefold())
        self.assertEqual(printable["powerReservation"]["antennaKeepoutZ"], [5.0, 30.0])
        self.assertIn("conductive", printable["rod"]["prohibitedMaterialNearAntenna"])
        self.assertEqual(status["printableEnclosure"]["batteryToAntennaGapMm"], 11.0)
        self.assertEqual(
            sys007["status"],
            "pcb_and_enclosure_keepout_verified_physical_rf_test_pending",
        )

        sys012 = requirements["SYS-012"]
        self.assertEqual(sys012["status"], "prototype_and_production_locks_separated")
        self.assertIn("owner-authorized prototype bare-pcb", sys012["acceptance"].casefold())
        locks = system["releaseLocks"]
        for key in (
            "prototypeOnly", "wandBarePcbTechnicalPackageReady",
            "printableEnclosureTechnicalPackageReady",
            "prototypeBarePcbFabricationAuthorized", "prototype3dPrintingAuthorized",
            "humanEngineeringReviewRequiredForProduction",
        ):
            self.assertTrue(locks[key], key)
        for key in (
            "systemAccepted", "pcbaOrderAuthorized", "targetFirmwareReleaseEligible",
            "productionReleaseEligible",
        ):
            self.assertFalse(locks[key], key)
        self.assertTrue(status["releaseLocks"]["prototypeBarePcbFabricationAuthorizedByOwner"])
        self.assertTrue(status["releaseLocks"]["prototype3dPrintingAuthorizedByOwner"])
        self.assertFalse(status["releaseLocks"]["pcbaOrderAuthorized"])
        self.assertFalse(status["releaseLocks"]["targetFirmwareReleaseEligible"])
        self.assertFalse(status["releaseLocks"]["productionReleaseEligible"])
    def test_known_bad_dimension_offset_and_duplicate_boundary_are_regression_locked(self) -> None:
        plan = load_json(PACKAGE / "drawings2d" / "wand_general_arrangement.drawing.plan.json")
        bad_offset = copy.deepcopy(plan)
        d3 = next(row for row in bad_offset["steps"] if row["id"] == "D3")
        offset = next(row for row in d3["constraints"] if row["kind"] == "base_offset")
        offset["dx"] = self.params["envelope"]["grip_segment_length"]
        with self.assertRaises(PlanError):
            compile_plan(bad_offset)
        duplicate = copy.deepcopy(plan)
        duplicate["steps"].append({
            "id": "BAD_DUPLICATE",
            "type": "line",
            "purpose": "negative regression fixture",
            "reasoning": "must not duplicate the existing grip lower edge",
            "start": {"ref": "G1.start"},
            "construction": {"kind": "to_point", "target": {"ref": "G1.end"}},
            "constraints": [{"kind": "horizontal"}],
            "depends_on": ["G1"],
            "layer": "OUTLINE",
            "role": "outline",
        })
        with self.assertRaisesRegex(PlanError, "duplicates G1"):
            compile_plan(duplicate)

    def test_capability_blockers_forbid_factory_ready_claims(self) -> None:
        blockers = load_json(PACKAGE / "CAPABILITY_BLOCKERS.json")
        self.assertEqual({row["id"] for row in blockers["blockers"]}, {f"MW-BLK-{index:03d}" for index in range(1, 7)})
        self.assertTrue(all(row["severity"] == "blocker" for row in blockers["blockers"]))
        self.assertTrue(blockers["locks"]["reviewOnly"])
        for key in ("accepted", "technicalPackageReady", "manufacturingAuthorized", "fabricationAuthorized", "productionReleaseEligible"):
            self.assertFalse(blockers["locks"][key])


if __name__ == "__main__":
    unittest.main()
