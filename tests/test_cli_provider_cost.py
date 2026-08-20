from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aicad.cli import _parser, main


class CliProviderCostTests(unittest.TestCase):
    def test_deepseek_is_a_controlled_cli_provider(self) -> None:
        args = _parser().parse_args(["natural", "request.txt", "--out", "out", "--provider", "deepseek"])
        self.assertEqual(args.provider, "deepseek")

    def test_offline_natural_run_writes_nonfiction_cost_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.txt"
            request.write_text("120×80板，中心直径20孔", encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(["natural", str(request), "--out", str(root / "out"), "--provider", "offline"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            ledger_path = Path(payload["provider_run"])
            self.assertTrue(ledger_path.is_file())
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(ledger["cost"]["amount"], "0.00000000")
            self.assertIsNone(ledger["usage"]["inputTokens"])
            self.assertFalse(ledger["promptStored"])
            self.assertNotIn("120×80", ledger_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
