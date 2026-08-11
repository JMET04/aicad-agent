from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.review_launch import launch_review


class AutomaticReviewLaunchTests(unittest.TestCase):
    def test_always_launches_existing_local_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.html"
            review.write_text("<html><body>review</body></html>", encoding="utf-8")
            opened: list[Path] = []
            with patch.dict(os.environ, {"AICAD_REVIEW_LAUNCH": ""}, clear=False):
                result = launch_review(review, "always", opener=opened.append)
            self.assertEqual(result["status"], "launched")
            self.assertEqual(opened, [review.resolve()])

    def test_auto_skips_in_ci_but_keeps_review_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.html"
            review.write_text("<html><body>review</body></html>", encoding="utf-8")
            with patch.dict(os.environ, {"CI": "true", "AICAD_REVIEW_LAUNCH": ""}, clear=False):
                result = launch_review(review, "auto", opener=lambda _: self.fail("must not open in CI"))
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "CI")
            self.assertEqual(result["review_html"], str(review.resolve()))

    def test_never_is_explicit_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.html"
            review.write_text("<html></html>", encoding="utf-8")
            with patch.dict(os.environ, {"AICAD_REVIEW_LAUNCH": ""}, clear=False):
                result = launch_review(review, "never")
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "disabled")


if __name__ == "__main__":
    unittest.main()
