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
    def test_existing_local_review_launches_persisted_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.html"
            review.write_text("<html><body>review</body></html>", encoding="utf-8")
            opened: list[Path] = []
            with patch.dict(
                os.environ,
                {"AICAD_REVIEW_LAUNCH": "", "AICAD_REVIEW_STAGE_DIR": str(root / "stage")},
                clear=False,
            ):
                result = launch_review(review, "always", opener=opened.append)
            self.assertEqual(result["status"], "launched")
            self.assertEqual(opened, [Path(str(result["review_html"]))])
            self.assertNotEqual(opened[0], review.resolve())
            self.assertEqual(opened[0].read_bytes(), review.read_bytes())

    def test_non_ascii_source_uses_ascii_compatibility_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory) / "中文目录"
            source_dir.mkdir()
            review = source_dir / "审核.html"
            review.write_text("<html><body>完整审核</body></html>", encoding="utf-8")
            stage = Path(directory) / "ascii-stage"
            opened: list[Path] = []
            with patch.dict(os.environ, {"AICAD_REVIEW_FORCE_STAGE": "true", "AICAD_REVIEW_STAGE_DIR": str(stage)}, clear=False):
                result = launch_review(review, "always", opener=opened.append)
            self.assertEqual(result["status"], "launched")
            self.assertTrue(result["staged_for_compatibility"])
            self.assertEqual(opened[0].name, "review.html")
            self.assertEqual(opened[0].read_bytes(), review.read_bytes())

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
