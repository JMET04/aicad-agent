from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]
MAGIC_WAND = REPO_ROOT / "projects" / "magic-wand"
PACKAGE = MAGIC_WAND / "integration"
XHTML_NS = "http://www.w3.org/1999/xhtml"
SVG_NS = "http://www.w3.org/2000/svg"

def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("magic_wand_integration_builder_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def markdown_blocker_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return set(re.findall(r"\b(?:BLK|FW-BLK|ENV)-[A-Z0-9-]+\b", path.read_text(encoding="utf-8")))


class MagicWandIntegrationPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.trace = load_json(PACKAGE / "current-system-traceability.json")
        cls.status = load_json(PACKAGE / "CURRENT_SYSTEM_STATUS.json")
        cls.contract = load_json(PACKAGE / "system-design-contract.json")
        cls.qa = load_json(PACKAGE / "system-design-qa-report.json")
        cls.blockers = load_json(PACKAGE / "system-blockers.json")

    def test_top_level_entry_identifies_current_rev_b_authority_and_open_release_gates(self) -> None:
        entry = MAGIC_WAND / "README.md"
        self.assertTrue(entry.is_file())
        text = entry.read_text(encoding="utf-8")
        self.assertIn("Rev B", text)
        self.assertIn("prototype bare-PCB", text)
        self.assertIn("prototype 3D printing", text)
        self.assertIn("PCBA", text)
        self.assertIn("production", text.casefold())
        linked = (
            "mechanical/printable-wand/", "electronics/manufacturing/jlcpcb-wand-rev-a0/", "integration/README.md",
            "integration/CURRENT_SYSTEM_STATUS.json", "integration/SYSTEM_ENGINEERING_HANDOFF.md",
            "integration/RECEIVER_EFFECTS_SYSTEM_HANDOFF.md",
            "integration/current-system-traceability.json", "integration/current-delivery-manifest.json",
            "electronics/receiver-effects/", "firmware/gesture-host-evidence.json",
            "firmware/host-review-evidence.json",
        )
        for relative in linked:
            with self.subTest(relative=relative):
                self.assertIn(f"]({relative})", text)
                self.assertTrue((MAGIC_WAND / PurePosixPath(relative)).exists())
        legacy_readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("legacy Rev A", legacy_readme)
        self.assertIn("superseded", legacy_readme.casefold())
        self.assertIn("delivery-manifest.json", legacy_readme)

    def test_receiver_effects_current_status_and_host_evidence_are_explicit(self) -> None:
        self.assertEqual(self.contract["revision"], "2026-08-23-prototype-contract-2")
        receiver = self.status["receiverEffects"]
        self.assertEqual(receiver["topology"], "DIRECT_PAIRED_BLE_ENDPOINT_WITH_OWN_NINA_B302_NOT_A_RELAY")
        self.assertEqual(receiver["authority"], "MEDIA_ONLY_NO_IMPLICIT_DANGEROUS_OUTPUT_AUTHORITY")
        self.assertEqual(receiver["logicalSlots"], 8)
        self.assertEqual(
            [(row["channel"], row["gesture"], row["effect"]) for row in receiver["effects"]],
            [
                (0, "TAP", "EXPLOSION"),
                (1, "TWIST_CW", "FIRE"),
                (2, "TWIST_CCW", "ICE"),
                (3, "SWISH_LEFT", "LIGHTNING"),
                (4, "SWISH_RIGHT", "SHIELD"),
                (5, "THRUST", "ARCANE"),
                (6, "CIRCLE_CW", "HEAL"),
                (7, "CIRCLE_CCW", "PORTAL"),
            ],
        )
        self.assertEqual(receiver["pcb"]["sizeMm"], [60.0, 50.0])
        self.assertEqual(receiver["pcb"]["layers"], 4)
        self.assertEqual(receiver["pcb"]["status"], "RELAYOUT_A1_DEBUG_STAGE_DRC_CLEAN")
        self.assertEqual(receiver["pcb"]["previousCamStatus"], "REJECTED")
        self.assertFalse(receiver["pcb"]["currentBareBoardUploadCandidate"])
        self.assertFalse(receiver["pcb"]["pcbaIncluded"])
        self.assertEqual(
            {row["mpn"] for row in receiver["coreIcs"]},
            {"NINA-B302-00B-00", "TPS62162DSGR", "USBLC6-2SC6", "MAX98357AETE+T"},
        )
        self.assertEqual(receiver["displayAccessory"]["sku"], "19192")
        self.assertEqual(receiver["displayAccessory"]["controller"], "GC9A01")
        self.assertFalse(receiver["displayAccessory"]["pcbaComponent"])
        self.assertEqual(receiver["speakerAccessory"]["model"], "30MM-4Ω3W-TFHM")
        self.assertEqual(receiver["speakerAccessory"]["lcsc"], "C50387216")
        self.assertFalse(receiver["speakerAccessory"]["pcbaComponent"])

        profiles = self.status["firmware"]["gestureEventProfiles"]
        self.assertEqual(profiles["legacyV1"]["payloadBytes"], 2)
        self.assertEqual(profiles["legacyV1"]["allowedLogicalChannels"], [0])
        self.assertEqual(profiles["multichannelV2"]["payloadBytes"], 14)
        self.assertEqual(profiles["multichannelV2"]["allowedLogicalChannels"], list(range(8)))
        self.assertTrue(profiles["multichannelV2"]["requiresArmActive"])
        self.assertTrue(profiles["multichannelV2"]["requiresOuterAndPayloadDeviceSessionBinding"])

        host = self.status["firmware"]["receiverRuntimeHostEvidence"]
        self.assertEqual(host["buildSteps"], {"passed": 34, "failed": 0})
        self.assertEqual(host["ctest"], {"passed": 10, "failed": 0})
        self.assertEqual(host["cppcheckFiles"], {"passed": 9, "failed": 0, "findings": 0})
        self.assertEqual(host["sourceHashInventory"], {"matched": 52, "mismatched": 0})
        evidence = {row["id"]: row for row in self.contract["evidenceBindings"]}
        self.assertEqual(evidence["EVID-RECEIVER-FW-HOST"]["size"], 10345)
        self.assertEqual(
            evidence["EVID-RECEIVER-FW-HOST"]["sha256"],
            "33732F037D6485F475AD754BE1D40490260DA120C90E8CBE6226E470F74FD681",
        )
        gates = {row["id"]: row for row in self.contract["verificationGates"]}
        self.assertEqual(gates["GATE-RECEIVER-FW-HOST-001"]["status"], "passed")
        self.assertEqual(gates["GATE-RECEIVER-PCB-001"]["status"], "open")
        self.assertEqual(gates["GATE-RECEIVER-001"]["status"], "open")

    def test_current_evidence_and_system_qa_are_reproducible(self) -> None:
        module = load_module(PACKAGE / "build_current_evidence.py")
        self.assertEqual(module.generate(check=True), [])
        qa_module = load_module(
            REPO_ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_system_engineering_qa.py"
        )
        self.assertEqual(qa_module.validate_contract(self.contract, REPO_ROOT), self.qa)
        self.assertTrue(self.qa["ok"])
        self.assertEqual(self.qa["errors"], [])
        self.assertIn("SYS-PROTOTYPE-001", {row["code"] for row in self.qa["warnings"]})
        self.assertFalse(self.qa["productionReleaseEligible"])
        self.assertIn("does not", self.qa["claimBoundary"])

    def test_sys_001_through_012_are_exactly_and_source_faithfully_traced(self) -> None:
        system = load_json(MAGIC_WAND / "system-requirements.json")
        expected = {row["id"]: row for row in system["requirements"]}
        observed = {row["id"]: row for row in self.trace["requirements"]}
        self.assertEqual(set(expected), {f"SYS-{index:03d}" for index in range(1, 13)})
        self.assertEqual(set(observed), set(expected))
        self.assertEqual(self.trace["coverage"]["required"], 12)
        self.assertEqual(self.trace["coverage"]["mapped"], 12)
        self.assertEqual(self.trace["coverage"]["missing"], [])
        self.assertEqual(set(self.trace["coverage"]["verificationOpen"]), set(expected))
        contract_requirements = {row["id"] for row in self.contract["requirements"]}
        contract_gates = {row["id"]: row for row in self.contract["verificationGates"]}
        evidence = {row["id"]: row for row in self.contract["evidenceBindings"]}
        for requirement_id, source in expected.items():
            with self.subTest(requirement=requirement_id):
                row = observed[requirement_id]
                for field in ("category", "requirement", "acceptance", "verification"):
                    self.assertEqual(row[field], source[field])
                self.assertEqual(row["sourceStatus"], source["status"])
                self.assertTrue(set(row["contractRequirementIds"]).issubset(contract_requirements))
                self.assertTrue(set(row["gateIds"]).issubset(contract_gates))
                self.assertEqual(
                    row["gateStatuses"],
                    {gate_id: contract_gates[gate_id]["status"] for gate_id in row["gateIds"]},
                )
                self.assertEqual(
                    row["verificationClosed"],
                    all(value == "passed" for value in row["gateStatuses"].values()),
                )
                self.assertEqual(
                    row["evidencePaths"],
                    [evidence[evidence_id]["path"] for evidence_id in row["evidenceIds"]],
                )
                for path_text in row["evidencePaths"]:
                    portable = PurePosixPath(path_text)
                    self.assertFalse(portable.is_absolute())
                    self.assertNotIn("..", portable.parts)
                    self.assertNotIn("\\", path_text)
                    self.assertTrue((REPO_ROOT / portable).is_file(), path_text)
        self.assertIn("315 mm", observed["SYS-001"]["requirement"])
        self.assertIn("30 mm", observed["SYS-001"]["requirement"])
        self.assertIn("179 mm", observed["SYS-001"]["requirement"])
        self.assertEqual(len(self.status["firmware"]["recognizedGestures"]), 8)
        self.assertIn("eight_class_host_pipeline_verified", observed["SYS-004"]["sourceStatus"])
        self.assertIn("GATE-PRODUCTION-001", observed["SYS-012"]["gateIds"])

    def test_combined_bom_has_unique_rows_and_null_unknown_prices(self) -> None:
        bom = load_json(PACKAGE / "combined-bom.json")
        rows = bom["rows"]
        uids = [row["uid"].casefold() for row in rows]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertTrue(all(row["quantity"] > 0 for row in rows))
        self.assertTrue(all(row["unitPriceCny"] is None for row in rows))
        self.assertTrue(all(row["extendedPriceCny"] is None for row in rows))
        self.assertEqual({row["domain"] for row in rows}, {"mechanical", "electronics"})
        with (PACKAGE / "combined-bom.csv").open("r", encoding="utf-8", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        self.assertEqual([row["uid"] for row in csv_rows], [row["uid"] for row in rows])
        self.assertTrue(all(row["unit_price_cny"] == "" and row["extended_price_cny"] == "" for row in csv_rows))

    def test_current_authorities_keep_prototype_and_production_locks_separate(self) -> None:
        self.assertEqual(
            self.status["releaseLocks"],
            {
                "prototypeBarePcbFabricationAuthorizedByOwner": True,
                "prototype3dPrintingAuthorizedByOwner": True,
                "pcbaOrderAuthorized": False,
                "targetFirmwareReleaseEligible": False,
                "productionReleaseEligible": False,
            },
        )
        self.assertEqual(
            self.contract["releaseLocks"],
            {
                "reviewOnly": True,
                "technicalReady": False,
                "physicalVerified": False,
                "productionReleaseEligible": False,
            },
        )
        requirements = load_json(MAGIC_WAND / "system-requirements.json")
        self.assertTrue(requirements["releaseLocks"]["prototypeOnly"])
        self.assertFalse(requirements["releaseLocks"]["systemAccepted"])
        self.assertTrue(requirements["releaseLocks"]["prototypeBarePcbFabricationAuthorized"])
        self.assertTrue(requirements["releaseLocks"]["prototype3dPrintingAuthorized"])
        self.assertFalse(requirements["releaseLocks"]["pcbaOrderAuthorized"])
        self.assertFalse(requirements["releaseLocks"]["targetFirmwareReleaseEligible"])
        self.assertFalse(requirements["releaseLocks"]["productionReleaseEligible"])
        self.assertTrue(requirements["releaseLocks"]["humanEngineeringReviewRequiredForProduction"])
        self.assertFalse(self.qa["technicalReady"])
        self.assertFalse(self.qa["physicalVerified"])
        self.assertFalse(self.qa["productionReleaseEligible"])

    def test_current_manifest_binds_real_files_by_path_size_and_sha256(self) -> None:
        manifest = load_json(PACKAGE / "current-delivery-manifest.json")
        self.assertTrue(manifest["selfHashPolicy"]["currentDeliveryManifestExcluded"])
        self.assertTrue(manifest["sourceFiles"])
        self.assertTrue(manifest["evidenceFiles"])
        self.assertEqual(manifest["counts"]["sourceFiles"], len(manifest["sourceFiles"]))
        self.assertEqual(manifest["counts"]["evidenceFiles"], len(manifest["evidenceFiles"]))
        self.assertEqual(
            manifest["counts"]["totalBoundFiles"],
            len(manifest["sourceFiles"]) + len(manifest["evidenceFiles"]),
        )
        paths: set[str] = set()
        for row in [*manifest["sourceFiles"], *manifest["evidenceFiles"]]:
            with self.subTest(path=row["path"]):
                self.assertNotIn(row["path"].casefold(), paths)
                paths.add(row["path"].casefold())
                path = REPO_ROOT / row["path"]
                self.assertNotRegex(row["path"], r"^[A-Za-z]:")
                self.assertNotIn("\\", row["path"])
                portable = PurePosixPath(row["path"])
                self.assertFalse(portable.is_absolute())
                self.assertNotIn("..", portable.parts)
                self.assertTrue(path.is_file(), path)
                self.assertGreater(path.stat().st_size, 0)
                self.assertEqual(path.stat().st_size, row["size"])
                self.assertEqual(sha256_file(path).upper(), row["sha256"])
        expected_sources = {
            "projects/magic-wand/README.md",
            "projects/magic-wand/integration/README.md",
            "projects/magic-wand/system-requirements.json",
            "projects/magic-wand/integration/CURRENT_SYSTEM_STATUS.json",
            "projects/magic-wand/integration/system-design-contract.json",
            "projects/magic-wand/integration/system-design-qa-report.json",
            "projects/magic-wand/integration/system-design-qa-report.md",
            "projects/magic-wand/integration/SYSTEM_ENGINEERING_HANDOFF.md",
            "projects/magic-wand/integration/RECEIVER_EFFECTS_SYSTEM_HANDOFF.md",
            "projects/magic-wand/integration/current-system-traceability.json",
            "projects/magic-wand/integration/build_current_evidence.py",
        }
        self.assertEqual({row["path"] for row in manifest["sourceFiles"]}, expected_sources)
        expected_evidence = {
            "EVID-PCB-SOURCE": "projects/magic-wand/electronics/wand/wand.kicad_pcb",
            "EVID-JLC-BARE-ZIP": "projects/magic-wand/electronics/manufacturing/jlcpcb-wand-rev-a0/JLCPCB_WAND_REV_A0_GERBER_DRILL.zip",
            "EVID-PRINT-PACKAGE": "projects/magic-wand/mechanical/printable-wand/outputs/MW_PRINTABLE_WAND_REV_A0.zip",
            "EVID-FW-HOST": "projects/magic-wand/firmware/gesture-host-evidence.json",
            "EVID-RECEIVER-FW-HOST": "projects/magic-wand/firmware/host-review-evidence.json",
        }
        self.assertEqual(
            {row["evidenceId"]: row["path"] for row in manifest["evidenceFiles"]},
            expected_evidence,
        )
        self.assertEqual(manifest["openReleaseGates"], self.qa["summary"]["openGates"])
        self.assertTrue(manifest["releaseLocks"]["prototypeBarePcbFabricationAuthorizedByOwner"])
        self.assertTrue(manifest["releaseLocks"]["prototype3dPrintingAuthorizedByOwner"])
        self.assertFalse(manifest["releaseLocks"]["pcbaOrderAuthorized"])
        self.assertFalse(manifest["readiness"]["productionReleaseEligible"])

    def test_svg_text_is_inside_frames_and_line_semantics_are_distinct(self) -> None:
        path = PACKAGE / "system-review-overview.svg"
        root = ET.parse(path).getroot()
        nodes = root.findall(f".//{{{SVG_NS}}}g[@data-node-id]")
        self.assertGreaterEqual(len(nodes), 15)
        for node in nodes:
            with self.subTest(node=node.attrib["data-node-id"]):
                rects = node.findall(f"{{{SVG_NS}}}rect")
                foreign = node.findall(f"{{{SVG_NS}}}foreignObject")
                self.assertEqual(len(rects), 1)
                self.assertEqual(len(foreign), 1)
                rect, text_box = rects[0], foreign[0]
                rx, ry = float(rect.attrib["x"]), float(rect.attrib["y"])
                rw, rh = float(rect.attrib["width"]), float(rect.attrib["height"])
                tx, ty = float(text_box.attrib["x"]), float(text_box.attrib["y"])
                tw, th = float(text_box.attrib["width"]), float(text_box.attrib["height"])
                self.assertGreaterEqual(tx, rx)
                self.assertGreaterEqual(ty, ry)
                self.assertLessEqual(tx + tw, rx + rw)
                self.assertLessEqual(ty + th, ry + rh)
                self.assertTrue("".join(text_box.itertext()).strip())
                children = list(text_box)
                self.assertEqual(len(children), 1)
                xhtml_div = children[0]
                self.assertEqual(xhtml_div.tag, f"{{{XHTML_NS}}}div")
                for descendant in xhtml_div.iter():
                    self.assertTrue(
                        descendant.tag.startswith(f"{{{XHTML_NS}}}"),
                        f"{node.attrib['data-node-id']} contains non-XHTML child {descendant.tag}",
                    )
        svg = path.read_text(encoding="utf-8")
        self.assertIn('padding:4px 8px', svg)
        self.assertIn('.boxtext strong { font-size:20px; }', svg)
        self.assertIn('.small { font-size:15px; line-height:1.18; }', svg)
        minimum_text_heights = {"MECH": 88.0, "ARM": 88.0, "POWER": 98.0, "MAINS": 94.0, "DRONE": 94.0}
        for node_id, minimum_height in minimum_text_heights.items():
            node = root.find(f".//{{{SVG_NS}}}g[@data-node-id='{node_id}']")
            self.assertIsNotNone(node, node_id)
            text_box = node.find(f"{{{SVG_NS}}}foreignObject")
            self.assertGreaterEqual(float(text_box.attrib["height"]), minimum_height, node_id)
        expected_styles = {
            "power": ("stroke-width:7", None),
            "rf": ("stroke-width:5", "stroke-dasharray:16 9"),
            "safety": ("stroke-width:6", "stroke-dasharray:14 6 3 6"),
            "signal": ("stroke-width:3", None),
            "mechanical-link": ("stroke-width:4", "stroke-dasharray:3 7"),
        }
        for class_name, declarations in expected_styles.items():
            self.assertRegex(svg, rf"\.{re.escape(class_name)}\s*\{{[^}}]*{re.escape(declarations[0])}")
            if declarations[1]:
                self.assertIn(declarations[1], svg)
            self.assertIn(f'class="path {class_name}"', svg)

    def test_source_blockers_survive_system_merge_and_none_are_closed(self) -> None:
        integrated = {row["id"]: row for row in self.blockers["blockers"]}
        mechanical = load_json(MAGIC_WAND / "mechanical" / "CAPABILITY_BLOCKERS.json")
        source_ids = {row["id"] for row in mechanical["blockers"]}
        for path in [*(MAGIC_WAND / "electronics").rglob("*"), *(MAGIC_WAND / "firmware").rglob("*")]:
            if path.is_file() and path.suffix.casefold() == ".md":
                source_ids |= markdown_blocker_ids(path)
            elif path.is_file() and path.suffix.casefold() == ".json":
                value = load_json(path)
                if isinstance(value.get("blockers"), list):
                    source_ids |= {row["id"] for row in value["blockers"] if isinstance(row, dict) and isinstance(row.get("id"), str)}
        self.assertTrue(source_ids.issubset(integrated), source_ids - set(integrated))
        self.assertTrue({f"INT-BLK-{index:03d}" for index in range(1, 7)}.issubset(integrated))
        self.assertTrue(all(row["status"] == "open" and row["closed"] is False for row in integrated.values()))

    def test_fmea_covers_all_requirements_and_never_marks_risk_closed(self) -> None:
        fmea = load_json(PACKAGE / "system-fmea.json")
        linked = {requirement for row in fmea["rows"] for requirement in row["linkedRequirements"]}
        self.assertEqual(linked, {f"SYS-{index:03d}" for index in range(1, 13)})
        self.assertGreaterEqual(len(fmea["rows"]), 20)
        for row in fmea["rows"]:
            self.assertEqual(row["rpn"], row["severity"] * row["occurrence"] * row["detectability"])
            self.assertEqual(row["status"], "open")
            self.assertFalse(row["closed"])

    def test_evt_dvt_pvt_gates_and_fabrication_block_are_explicit(self) -> None:
        plan = load_json(PACKAGE / "evt-dvt-pvt-plan.json")
        self.assertEqual([row["stage"] for row in plan["stages"]], ["EVT", "DVT", "PVT"])
        items = [item for stage in plan["stages"] for item in stage["items"]]
        self.assertTrue(all(item["closed"] is False for item in items))
        self.assertTrue(all(item["status"] in {"open", "blocked"} for item in items))
        self.assertTrue(plan["factoryQuotation"]["mechanicalQuoteOnly"])
        self.assertFalse(plan["factoryQuotation"]["electronicsFabricationAllowed"])
        for path_text in plan["factoryQuotation"]["mechanicalReferencePaths"]:
            self.assertTrue((REPO_ROOT / path_text).is_file(), path_text)

    def test_cost_math_has_three_phases_models_snapshot_and_exclusions(self) -> None:
        cost = load_json(PACKAGE / "rough-cost-estimate.json")
        self.assertEqual(cost["snapshotDate"], "2026-08-21")
        self.assertEqual({row["phase"] for row in cost["phases"]}, {"mechanical_drawings", "electronics_and_firmware", "system_integration"})
        self.assertEqual(cost["providers"]["openai"]["model"], "gpt-5.6-terra")
        self.assertEqual(cost["providers"]["openai"]["pricingUrl"], "https://developers.openai.com/api/docs/models/gpt-5.6-terra")
        self.assertEqual(cost["providers"]["openai"]["cachedInputUsdPerMillion"], 0.2)
        self.assertEqual(cost["providers"]["deepseek"]["model"], "deepseek-v4-pro")
        self.assertIn("not actual platform usage", cost["estimateType"])
        self.assertGreaterEqual(len(cost["excluded"]), 6)
        self.assertEqual(cost["totals"]["estimatedInputTokens"], sum(row["estimatedInputTokens"] for row in cost["phases"]))
        self.assertEqual(cost["totals"]["estimatedOutputTokens"], sum(row["estimatedOutputTokens"] for row in cost["phases"]))
        for bucket in ("humanOnlyCostCny", "requiredHumanReviewAfterAiCostCny"):
            for bound in ("low", "high"):
                self.assertEqual(
                    cost["totals"][bucket][bound],
                    sum(row[bucket][bound] for row in cost["phases"]),
                )
        for row in cost["phases"]:
            self.assertEqual(
                row["humanOnlyCostCny"],
                {bound: row["humanOnlyHours"][bound] * row["humanHourlyRateCny"] for bound in ("low", "high")},
            )
            self.assertEqual(
                row["requiredHumanReviewAfterAiCostCny"],
                {bound: row["requiredHumanReviewAfterAiHours"][bound] * row["humanHourlyRateCny"] for bound in ("low", "high")},
            )
        for provider in cost["providers"]:
            self.assertAlmostEqual(cost["totals"]["apiTokenOnlyCostCny"][provider], sum(row["apiTokenOnlyCost"][provider]["cny"] for row in cost["phases"]), places=2)
        for row in cost["phases"]:
            for provider, pricing in cost["providers"].items():
                expected_usd = row["estimatedInputTokens"] / 1_000_000 * pricing["inputUsdPerMillion"] + row["estimatedOutputTokens"] / 1_000_000 * pricing["outputUsdPerMillion"]
                self.assertAlmostEqual(row["apiTokenOnlyCost"][provider]["usd"], expected_usd, places=6)
                self.assertAlmostEqual(row["apiTokenOnlyCost"][provider]["cny"], round(expected_usd * cost["usdToCnyPlanningRate"], 2), places=2)
            self.assertGreater(row["requiredHumanReviewAfterAiCostCny"]["low"], row["apiTokenOnlyCost"]["openai"]["cny"])


if __name__ == "__main__":
    unittest.main()
