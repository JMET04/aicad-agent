from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aicad.procurement import canonical_sha256, validate_procurement_preflight


NOW = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)


class ProcurementPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.design = self.write("design.txt", "synthetic native design, not a real product")
        self.inventory = {
            "schema": "aicad_procurement_inventory_v1", "projectId": "TEST",
            "deliverable": "complete_system", "quantity": 2,
            "items": [
                {"id": category, "category": category, "need": 2, "mpn": ""}
                for category in ("pcb", "components", "accessories", "mechanical", "assembly", "shipping", "tax", "tools")
            ],
            "scenarios": [{"id": "GESTURE", "level": "host_logic", "criterion": "eight synthetic routes",
                           "checks": [{"id": "routes", "operator": "eq", "expected": 8}],
                           "physicalValidationRequired": True}],
        }
        self.inventory["items"][1]["mpn"] = "FROZEN-MPN"
        self.contract = {
            "schema": "aicad_procurement_preflight_v1", "projectId": "TEST", "projectState": "active",
            "action": "submit_order", "design": [{"id": "native", **self.design}],
            "inventory": self.write("inventory.json", self.inventory), "quotes": [], "tests": [],
        }
        for item in self.inventory["items"]:
            quote = {
                "itemId": item["id"], "mpn": item["mpn"], "status": "in_stock", "stock": 100,
                "purchaseQty": 2, "moq": 1, "multiple": 1, "unitCny": "1.25", "taxIncluded": True,
                "quotedAt": "2026-10-08T00:00:00Z", "validUntil": "2026-10-10T00:00:00Z",
                "source": "https://supplier.example.test/quote", "qualification": None,
            }
            quote["evidence"] = self.write(item["id"] + ".quote.json", quote)
            self.contract["quotes"].append(quote)
        self.rebind()

    def write(self, name, value):
        path = self.root / name
        data = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        path.write_text(data, encoding="utf-8")
        raw = path.read_bytes()
        return {"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def rebind(self, budget="100.00"):
        for quote in self.contract["quotes"]:
            clean = {key: value for key, value in quote.items() if key != "evidence"}
            quote["evidence"] = self.write(quote["itemId"] + ".quote.json", clean)
        self.contract["inventory"] = self.write("inventory.json", self.inventory)
        self.design_sha = canonical_sha256(self.contract["design"])
        inventory_sha = self.contract["inventory"]["sha256"]
        self.quote_sha = canonical_sha256(self.contract["quotes"])
        self.contract["tests"] = []
        for scenario in self.inventory["scenarios"]:
            result = {"schema": "aicad_functional_evidence_v1", "scenarioId": scenario["id"],
                      "level": scenario["level"], "designSha256": self.design_sha,
                      "inventorySha256": inventory_sha, "outcome": "pass", "measurements": {"routes": 8},
                      "limitations": "Synthetic host test; no radio, charging or physical proof."}
            self.contract["tests"].append({"scenarioId": scenario["id"], "evidence": self.write("test.json", result)})
        acceptance = {"schema": "aicad_budget_acceptance_v1", "projectId": "TEST", "actor": "human",
                      "confirmed": True, "action": self.contract["action"], "designSha256": self.design_sha,
                      "inventorySha256": inventory_sha, "quoteSetSha256": self.quote_sha,
                      "budgetCny": budget, "validUntil": "2026-10-10T00:00:00Z"}
        self.contract["approval"] = self.write("approval.json", acceptance)

    def run_gate(self):
        return validate_procurement_preflight(self.contract, self.root, now=NOW)

    def assert_blocked(self, code):
        report = self.run_gate()
        self.assertFalse(report["orderPreflightPassed"], report)
        self.assertIn(code, {row["code"] for row in report["blockers"]}, report)
        self.assertFalse(report["purchaseAuthorized"])

    def test_complete_budget_pass_is_not_purchase_or_real_hardware_authorization(self):
        report = self.run_gate()
        self.assertTrue(report["orderPreflightPassed"], report)
        self.assertEqual(report["quotedTotalCny"], "20.00")
        self.assertFalse(report["purchaseAuthorized"])
        self.assertFalse(report["realHardwareFunctionProven"])
        self.assertEqual(report["physicalValidationPending"], ["GESTURE"])
        self.assertTrue(report["externalEvidenceAuthenticityRequired"])

    def test_zero_pcb_cost_does_not_hide_missing_other_costs(self):
        self.contract["quotes"][0]["unitCny"] = "0"
        self.contract["quotes"].pop(2)
        self.rebind()
        self.assert_blocked("COST_COVERAGE")

    def test_terminated_project_cannot_be_rearmed_by_valid_approval(self):
        self.contract["projectState"] = "terminated"
        self.assert_blocked("PROJECT_STOPPED")

    def test_budget_unknown_or_blank_is_not_zero(self):
        self.rebind(budget="")
        self.assert_blocked("BUDGET_APPROVAL")

    def test_budget_overrun_blocks_even_free_pcb(self):
        self.contract["quotes"][0]["unitCny"] = "0"
        self.rebind(budget="1.00")
        self.assert_blocked("BUDGET_OVERRUN")

    def test_approval_is_required_even_for_zero_total(self):
        for quote in self.contract["quotes"]:
            quote["unitCny"] = "0"
        self.rebind()
        del self.contract["approval"]
        self.assert_blocked("BUDGET_APPROVAL")

    def test_full_system_cannot_omit_accessories_category(self):
        self.inventory["items"] = [item for item in self.inventory["items"] if item["category"] != "accessories"]
        self.contract["quotes"] = [quote for quote in self.contract["quotes"] if quote["itemId"] != "accessories"]
        self.rebind()
        self.assert_blocked("INVENTORY_SCOPE")

    def test_explicit_bare_board_scope_does_not_require_unrelated_finished_product(self):
        self.inventory["deliverable"] = "bare_pcb"
        self.inventory["items"] = [item for item in self.inventory["items"] if item["category"] in {"pcb", "shipping", "tax"}]
        self.inventory["scenarios"] = []
        self.contract["quotes"] = [quote for quote in self.contract["quotes"] if quote["itemId"] in {"pcb", "shipping", "tax"}]
        self.rebind()
        self.assertTrue(self.run_gate()["orderPreflightPassed"])

    def test_all_costs_include_real_moq_not_only_consumption(self):
        self.contract["quotes"][1].update(purchaseQty=100, moq=100, multiple=100)
        self.rebind(budget="1000")
        self.assertEqual(self.run_gate()["quotedTotalCny"], "142.50")

    def test_moq_multiple_and_boolean_quantities_fail_closed(self):
        for change in ({"purchaseQty": 0}, {"purchaseQty": True}, {"multiple": 3}, {"moq": 3}):
            with self.subTest(change=change):
                saved = copy.deepcopy(self.contract["quotes"][1])
                self.contract["quotes"][1].update(change)
                self.rebind()
                self.assert_blocked("QUOTE_INVALID")
                self.contract["quotes"][1] = saved

    def test_negative_nan_infinite_and_non_numeric_prices_are_rejected(self):
        for value in ("-1", "NaN", "Infinity", "unknown", True):
            with self.subTest(value=value):
                self.contract["quotes"][1]["unitCny"] = value
                self.rebind()
                self.assert_blocked("QUOTE_INVALID")

    def test_stale_or_future_snapshot_is_not_executable_quote(self):
        for change in ({"validUntil": "2026-10-08T23:59:59Z"}, {"quotedAt": "2026-10-09T01:00:00Z"}):
            with self.subTest(change=change):
                self.contract["quotes"][1].update(change)
                self.rebind()
                self.assert_blocked("QUOTE_INVALID")

    def test_out_of_stock_is_not_buyable_from_displayed_price(self):
        self.contract["quotes"][1]["stock"] = 1
        self.rebind()
        self.assert_blocked("QUOTE_INVALID")

    def test_unqualified_cheaper_mpn_cannot_lower_budget(self):
        self.contract["quotes"][1]["mpn"] = "CHEAP-DIFFERENT-FOOTPRINT"
        self.rebind()
        self.assert_blocked("SUBSTITUTION_UNQUALIFIED")

    def test_quote_snapshot_tampering_blocks(self):
        self.contract["quotes"][1]["unitCny"] = "0.01"
        self.assert_blocked("QUOTE_INVALID")

    def test_approval_is_invalidated_when_quote_design_or_scope_changes(self):
        self.contract["quotes"][1]["unitCny"] = "2.00"
        quote = self.contract["quotes"][1]
        quote["evidence"] = self.write("components.quote.json", {k: v for k, v in quote.items() if k != "evidence"})
        self.assert_blocked("BUDGET_APPROVAL")

    def test_drc_cannot_replace_function_simulation(self):
        self.inventory["scenarios"][0]["level"] = "native_drc"
        self.rebind()
        self.assert_blocked("INVENTORY_SCOPE")

    def test_host_logic_cannot_replace_required_analog_simulation(self):
        self.inventory["scenarios"][0]["level"] = "analog_simulation"
        self.rebind()
        result = json.loads((self.root / "test.json").read_text())
        result["level"] = "host_logic"
        self.contract["tests"][0]["evidence"] = self.write("test.json", result)
        self.assert_blocked("FUNCTION_EVIDENCE")

    def test_failed_measured_effect_blocks(self):
        result = json.loads((self.root / "test.json").read_text())
        result["measurements"]["routes"] = 7
        self.contract["tests"][0]["evidence"] = self.write("test.json", result)
        self.assert_blocked("FUNCTION_EVIDENCE")

    def test_missing_or_stale_test_evidence_blocks(self):
        self.contract["tests"] = []
        self.assert_blocked("FUNCTION_COVERAGE")

    def test_frozen_source_modified_after_simulation_blocks(self):
        (self.root / "design.txt").write_text("a different design", encoding="utf-8")
        self.assert_blocked("DESIGN_EVIDENCE")

    def test_actual_disabled_radio_is_not_overridden_by_passing_host_test(self):
        config = self.write("prj.conf", "CONFIG_BT=n\n")
        self.contract["design"].append({"id": "firmware-config", **config})
        self.inventory["scenarios"][0]["sourceChecks"] = [
            {"designId": "firmware-config", "format": "kconfig", "setting": "CONFIG_BT", "expected": "y"}
        ]
        self.rebind()
        self.assert_blocked("FUNCTION_CONFIGURATION")

    def test_source_setting_is_checked_from_bound_file_not_report_text(self):
        config = self.write("prj.conf", "# CONFIG_BT=y is only a comment\nCONFIG_BT=y\n")
        self.contract["design"].append({"id": "firmware-config", **config})
        self.inventory["scenarios"][0]["sourceChecks"] = [
            {"designId": "firmware-config", "format": "kconfig", "setting": "CONFIG_BT", "expected": "y"}
        ]
        self.rebind()
        self.assertTrue(self.run_gate()["orderPreflightPassed"])

    def test_conflicting_frozen_config_assignments_fail_closed(self):
        config = self.write("prj.conf", "CONFIG_BT=y\nCONFIG_BT=n\n")
        self.contract["design"].append({"id": "firmware-config", **config})
        self.inventory["scenarios"][0]["sourceChecks"] = [
            {"designId": "firmware-config", "format": "kconfig", "setting": "CONFIG_BT", "expected": "y"}
        ]
        self.rebind()
        self.assert_blocked("FUNCTION_CONFIGURATION")

    def test_unsafe_evidence_paths_block(self):
        self.contract["inventory"]["path"] = "../outside.json"
        self.assert_blocked("INVENTORY_EVIDENCE")

    def test_quote_duplicates_do_not_satisfy_missing_items(self):
        self.contract["quotes"].append(copy.deepcopy(self.contract["quotes"][0]))
        self.rebind()
        self.assert_blocked("COST_COVERAGE")


if __name__ == "__main__":
    unittest.main()
