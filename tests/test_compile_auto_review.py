from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"
PLAN = ROOT / "examples" / "rectangle.plan.json"


class CompileAutomaticReviewTests(unittest.TestCase):
    def test_compile_always_writes_review_and_can_disable_window_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable, str(CLI), "compile", "--plan", str(PLAN),
                    "--out", directory, "--name", "auto-review", "--review-launch", "never",
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["review_launch"]["status"], "skipped")
            self.assertEqual(payload["review_launch"]["reason"], "disabled")
            review = Path(payload["review"]["artifacts"]["review_html"])
            self.assertTrue(review.is_file())
            self.assertIn("几何审查与修改器", review.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
