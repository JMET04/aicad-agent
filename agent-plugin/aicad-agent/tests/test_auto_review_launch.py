from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" / "src" if (ROOT / "runtime" / "src").is_dir() else ROOT.parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from aicad.review_launch import launch_review


class PackagedAutomaticReviewLaunchTests(unittest.TestCase):
    def test_existing_local_review_can_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.html"
            review.write_text("<html><body>review</body></html>", encoding="utf-8")
            opened: list[Path] = []
            with patch.dict(os.environ, {"AICAD_REVIEW_LAUNCH": ""}, clear=False):
                result = launch_review(review, "always", opener=opened.append)
            self.assertEqual(result["status"], "launched")
            self.assertEqual(opened, [review.resolve()])

    def test_compile_writes_review_when_launch_is_disabled(self) -> None:
        script = ROOT / "scripts" / "aicad_agent.py"
        plan = ROOT / "runtime" / "examples" / "rectangle.plan.json"
        if not plan.is_file():
            plan = ROOT.parents[1] / "examples" / "rectangle.plan.json"
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, str(script), "compile", "--plan", str(plan), "--out", directory, "--name", "packaged-review", "--review-launch", "never"],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["review_launch"]["reason"], "disabled")
            review = Path(payload["review"]["artifacts"]["review_html"])
            self.assertTrue(review.is_file())
            html = review.read_text(encoding="utf-8")
            self.assertIn('id="coordinateToggle"', html)
            self.assertIn("aicad.coordinate-system.visible", html)
