from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_agent():
    path = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_provider_cost", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AgentProviderCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent()

    def test_generate_tool_exposes_deepseek_and_offline_run_ledger(self) -> None:
        tool = next(row for row in self.agent.TOOLS if row["name"] == "aicad_generate")
        self.assertIn("deepseek", tool["inputSchema"]["properties"]["provider"]["enum"])
        with tempfile.TemporaryDirectory() as temporary:
            result = self.agent.generate(
                "120×80板，中心直径20孔", temporary, "offline-cost", "offline", "never"
            )
            ledger_path = Path(result["provider_run"])
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(result["cost"]["amount"], "0.00000000")
            self.assertIsNone(result["usage"]["inputTokens"])
            self.assertFalse(ledger["promptStored"])
            self.assertIn(str(ledger_path.resolve()), result["artifacts"])


if __name__ == "__main__":
    unittest.main()
