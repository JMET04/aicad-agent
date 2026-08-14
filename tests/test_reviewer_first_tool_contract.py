from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agent-plugin/aicad-agent/scripts/aicad_agent.py"


def load_agent_module():
    spec = importlib.util.spec_from_file_location("aicad_agent_reviewer_first_contract", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load agent plugin script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewerFirstToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent_module()

    def test_tool_schema_fails_closed_by_default(self) -> None:
        tool = next(item for item in self.agent.TOOLS if item["name"] == "aicad_open_review_request")
        schema = tool["inputSchema"]
        self.assertEqual(schema["required"], ["review_html"])
        self.assertFalse(schema["properties"]["open_native_cad"]["default"])
        self.assertEqual(schema["properties"]["review_launch"]["default"], "always")
        self.assertEqual(schema["properties"]["review_launch"]["enum"], ["auto", "always"])
        self.assertIn("only after the modifier", tool["description"])

    def test_dispatch_does_not_infer_native_intent_from_cad_path(self) -> None:
        with patch.object(self.agent, "open_review_request", return_value={"ok": True}) as opener:
            result = self.agent._dispatch_tool(
                "aicad_open_review_request",
                {"review_html": "review.html", "cad_path": "drawing.dwg"},
            )
        self.assertEqual(result, {"ok": True})
        opener.assert_called_once_with(
            "review.html",
            cad_path="drawing.dwg",
            open_native_cad=False,
            review_mode="always",
        )

    def test_cli_requires_an_explicit_switch_for_native_cad(self) -> None:
        args = self.agent._parser().parse_args(
            ["open-review", "--review-html", "drawing.modifier.html", "--cad-path", "drawing.dwg"]
        )
        self.assertFalse(args.open_native_cad)
        self.assertEqual(args.review_launch, "always")


if __name__ == "__main__":
    unittest.main()
