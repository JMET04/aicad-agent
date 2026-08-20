from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_agent():
    path = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_domain_gate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def intent_plan(domain: str) -> dict:
    return {
        "schema_version": "2.0",
        "drawing": {"name": "intent", "domain": domain, "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
        "steps": [{
            "id": "L001", "type": "line", "purpose": "intent baseline", "reasoning": "origin datum",
            "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 100, "dy": 0},
            "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 100}],
            "layer": "INTENT", "role": "annotation",
        }],
    }


class AgentDomainGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent()

    def test_foundation_domain_is_blocked_before_artifact_directory_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "structural-output"
            with self.assertRaisesRegex(self.agent.PlanError, "DOMAIN.G000"):
                self.agent.compile_plan_value(intent_plan("structural"), str(output), "fake-structure")
            self.assertFalse(output.exists())

    def test_general_plan_attaches_automatic_domain_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.agent.compile_plan_value(intent_plan("general"), temporary, "general-intent")
        self.assertIn(result["domain_validation"]["status"], {"passed", "passed_with_warnings"})
        self.assertEqual(result["domain_validation"]["domain"], "general")


if __name__ == "__main__":
    unittest.main()
