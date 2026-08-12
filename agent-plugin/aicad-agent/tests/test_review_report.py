from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_review_report.py"
SPEC = importlib.util.spec_from_file_location("aicad_review_report", SCRIPT)
assert SPEC and SPEC.loader
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def report() -> dict[str, object]:
    return {
        "status": "failed",
        "releaseAllowed": False,
        "artifactDisposition": "blocker_report_only",
        "checks": {
            "axis_grid": {"pass": True, "evidence": {"count": 8}},
            "door_topology": {"pass": False, "evidence": {"doorId": "D01", "reason": "missing opening"}},
        },
        "rootCauseLessons": [
            {
                "ruleId": "ARCH-D027",
                "symptom": "审核文件无法直接打开。",
                "rootCause": "仅交付 Markdown 和 JSON。",
                "correction": "输出单文件 HTML 与白底 PNG。",
                "preventionRule": "阻断报告必须包含 html/png。",
            }
        ],
    }


class ReviewReportTests(unittest.TestCase):
    def test_html_is_utf8_self_contained_and_contains_chinese(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.html"
            RENDERER.write_html(report(), path, "施工审核")
            text = path.read_text(encoding="utf-8")
            self.assertIn('<meta charset="utf-8">', text)
            self.assertIn("施工审核", text)
            self.assertIn("审核文件无法直接打开", text)
            self.assertNotIn("http://", text)
            self.assertNotIn("https://", text)
            for forbidden in ("瀹℃", "鈫", chr(0xFFFD)):
                self.assertNotIn(forbidden, text)

    def test_png_is_opaque_white_background_and_contains_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.png"
            RENDERER.write_png(report(), path, "施工审核")
            with Image.open(path) as image:
                self.assertEqual(image.mode, "RGB")
                self.assertGreaterEqual(image.width, 1600)
                self.assertGreaterEqual(image.height, 900)
                self.assertEqual(image.getpixel((image.width - 1, image.height - 1)), (255, 255, 255))

    def test_bundle_records_compatibility_launch_instead_of_returning_only_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "中文目录" / "review.html"
            png_path = root / "中文目录" / "review.png"
            stage = root / "ascii-stage"
            opened: list[Path] = []
            old_force = os.environ.get("AICAD_REVIEW_FORCE_STAGE")
            old_stage = os.environ.get("AICAD_REVIEW_STAGE_DIR")
            try:
                os.environ["AICAD_REVIEW_FORCE_STAGE"] = "1"
                os.environ["AICAD_REVIEW_STAGE_DIR"] = str(stage)
                result = RENDERER.write_review_bundle(report(), html_path, png_path, "施工审核", "always", opener=opened.append)
            finally:
                if old_force is None:
                    os.environ.pop("AICAD_REVIEW_FORCE_STAGE", None)
                else:
                    os.environ["AICAD_REVIEW_FORCE_STAGE"] = old_force
                if old_stage is None:
                    os.environ.pop("AICAD_REVIEW_STAGE_DIR", None)
                else:
                    os.environ["AICAD_REVIEW_STAGE_DIR"] = old_stage
            launch = result["reviewLaunch"]
            self.assertEqual(launch["status"], "launched")
            self.assertTrue(launch["staged_for_compatibility"])
            self.assertEqual(len(opened), 1)
            self.assertEqual(opened[0], Path(launch["review_html"]))
            self.assertTrue(opened[0].is_file())
            self.assertEqual(opened[0].read_bytes(), html_path.read_bytes())
            launch_json = Path(result["launchJson"])
            self.assertEqual(launch_json.name, "review-launch.json")
            self.assertTrue(launch_json.is_file())
            self.assertEqual(json.loads(launch_json.read_text(encoding="utf-8")), launch)


if __name__ == "__main__":
    unittest.main()
