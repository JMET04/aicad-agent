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
    def test_always_launches_persisted_content_addressed_html(self) -> None:
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
            self.assertTrue(result["staged_for_persistence"])

    def test_non_ascii_source_uses_self_contained_ascii_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory) / "中文目录"
            source_dir.mkdir()
            review = source_dir / "审核.html"
            review.write_text("<html><body>完整审核</body></html>", encoding="utf-8")
            stage = Path(directory) / "ascii-stage"
            opened: list[Path] = []
            with patch.dict(
                os.environ,
                {
                    "AICAD_REVIEW_LAUNCH": "",
                    "AICAD_REVIEW_FORCE_STAGE": "true",
                    "AICAD_REVIEW_STAGE_DIR": str(stage),
                },
                clear=False,
            ):
                result = launch_review(review, "always", opener=opened.append)
            self.assertEqual(result["status"], "launched")
            self.assertTrue(result["staged_for_compatibility"])
            self.assertEqual(result["source_review_html"], str(review.resolve()))
            self.assertEqual(len(opened), 1)
            self.assertEqual(opened[0].name, "review.html")
            self.assertEqual(opened[0].read_text(encoding="utf-8"), "<html><body>完整审核</body></html>")

    def test_ascii_temporary_source_survives_source_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            opened: list[Path] = []
            with tempfile.TemporaryDirectory(dir=root) as source_directory:
                review = Path(source_directory) / "part.review.html"
                review.write_text("<html><body>persistent review</body></html>", encoding="utf-8")
                with patch.dict(
                    os.environ,
                    {"AICAD_REVIEW_LAUNCH": "", "AICAD_REVIEW_STAGE_DIR": str(stage)},
                    clear=False,
                ):
                    result = launch_review(review, "always", opener=opened.append)
                source_path = review.resolve()
            self.assertFalse(source_path.exists())
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].is_file())
            self.assertEqual(opened[0].read_text(encoding="utf-8"), "<html><body>persistent review</body></html>")

    def test_duplicate_auto_launch_is_suppressed_but_always_can_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.html"
            review.write_text("<html><body>review</body></html>", encoding="utf-8")
            opened: list[Path] = []
            environment = {
                "AICAD_REVIEW_LAUNCH": "",
                "AICAD_REVIEW_STAGE_DIR": str(root / "stage"),
                "AICAD_REVIEW_AUTO_DEDUP_SECONDS": "3600",
            }
            with patch.dict(os.environ, environment, clear=False):
                first = launch_review(review, "auto", opener=opened.append)
                duplicate = launch_review(review, "auto", opener=opened.append)
                forced = launch_review(review, "always", opener=opened.append)
            self.assertEqual(first["status"], "launched")
            self.assertEqual(duplicate["status"], "skipped")
            self.assertEqual(duplicate["reason"], "duplicate_auto_launch")
            self.assertEqual(forced["status"], "launched")
            self.assertEqual(len(opened), 2)

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
