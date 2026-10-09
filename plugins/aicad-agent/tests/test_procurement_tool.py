import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("procurement_agent_under_test", ROOT / "scripts/aicad_agent.py")
AGENT = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(AGENT)


class ProcurementToolTests(unittest.TestCase):
    def test_discoverable_read_only_mcp_surface(self):
        tool = next(t for t in AGENT.TOOLS if t["name"] == "aicad_validate_procurement_preflight")
        self.assertEqual(tool["inputSchema"]["required"], ["contract"])
        cap = AGENT.capabilities()["procurement_preflight"]
        self.assertFalse(cap["can_order_pay_or_consume_coupon"])
        self.assertFalse(cap["native_drc_proves_function"])
        schema = json.loads(Path(cap["schema"]).read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema"]["const"], "aicad_procurement_preflight_v1")

    def test_missing_budget_never_defaults_to_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = AGENT._dispatch_tool("aicad_validate_procurement_preflight", {
                "contract": {"schema": "aicad_procurement_preflight_v1", "projectId": "TEST",
                             "projectState": "terminated", "action": "submit_order"},
                "evidence_root": temporary,
            })
            self.assertFalse(report["ok"])
            self.assertFalse(report["purchaseAuthorized"])
            self.assertIn("PROJECT_STOPPED", {b["code"] for b in report["blockers"]})

    def test_packaged_cli_exits_nonzero_with_parseable_blockers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps({"schema": "aicad_procurement_preflight_v1", "projectId": "TEST",
                                        "projectState": "terminated", "action": "submit_order"}), encoding="utf-8")
            completed = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/aicad_agent.py"),
                                        "procurement-preflight", "--contract", str(path)], capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(json.loads(completed.stdout)["orderPreflightPassed"])


if __name__ == "__main__":
    unittest.main()
