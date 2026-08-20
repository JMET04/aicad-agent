from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_agent():
    path = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_cli_surface", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AgentCliSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent()

    def test_parser_exposes_deepseek_experience_and_evidence_root(self) -> None:
        generated = self.agent._parser().parse_args([
            "generate", "--request", "line", "--provider", "deepseek",
        ])
        self.assertEqual(generated.provider, "deepseek")
        validated = self.agent._parser().parse_args([
            "validate", "--plan", "plan.json", "--evidence-root", "evidence",
        ])
        self.assertEqual(validated.evidence_root, "evidence")
        recalled = self.agent._parser().parse_args([
            "experience-recall", "--context", "context.json", "--max-cards", "5",
        ])
        self.assertEqual(recalled.max_cards, 5)

    def test_registry_and_experience_schema_cli_emit_json(self) -> None:
        for command, expected in (
            ("domain-registry", "registry"),
            ("experience-context-schema", "schema"),
            ("review-coverage-schema", "schema"),
        ):
            with self.subTest(command=command):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = self.agent.main([command])
                self.assertEqual(code, 0)
                self.assertIn(expected, json.loads(stdout.getvalue()))


if __name__ == "__main__":
    unittest.main()
