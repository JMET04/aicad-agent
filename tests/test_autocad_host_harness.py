from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutoCadHostHarnessTests(unittest.TestCase):
    def test_default_python_command_is_resolved_through_get_command_source(self) -> None:
        harness = (ROOT / "scripts" / "test-autocad.ps1").read_text(encoding="utf-8")
        self.assertIn("$pythonCommand = Get-Command $PythonExe", harness)
        self.assertIn("Test-Path -LiteralPath $PythonExe -PathType Leaf", harness)
        self.assertIn("$pythonCommand.Source", harness)
        self.assertNotIn('$env:AICAD_PYTHON = (Resolve-Path -LiteralPath $PythonExe).Path', harness)


if __name__ == "__main__":
    unittest.main()
