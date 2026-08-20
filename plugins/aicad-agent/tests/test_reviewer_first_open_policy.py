from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PLUGIN_ROOT / "runtime" / "src" if (PLUGIN_ROOT / "runtime" / "src").is_dir() else PLUGIN_ROOT.parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from aicad.engine import PlanError
from aicad.review_launch import open_review_request


MODIFIER = """<!doctype html>
<html data-artifact-role="interactive_drawing_modifier">
<body>
  <svg class="cad-view" aria-label="source-bound selectable CAD">
    <g class="view-hit"
       data-view-entity-id="view-entity-1"
       data-source-id="source-object-1"
       data-source-subobject="Edge1"></g>
  </svg>
  <section class="measurement-card">12.0 mm</section>
  <script id="aicad-semantic-entity-catalog" type="application/json">{}</script>
  <script>
    const formalCorrection = {reviewOnly: true, accepted: false};
  </script>
</body>
</html>
"""


class ReviewerFirstOpenPolicyTests(unittest.TestCase):
    def environment(self, root: Path) -> dict[str, str]:
        return {
            "AICAD_REVIEW_LAUNCH": "",
            "AICAD_REVIEW_STAGE_DIR": str(root / "stage"),
            "AICAD_NO_GUI": "",
            "CI": "",
        }

    def test_generic_request_blocks_native_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            cad = root / "drawing.dwg"
            review.write_text(MODIFIER, encoding="utf-8")
            cad.write_bytes(b"native-cad-placeholder")
            reviewers: list[Path] = []
            native: list[Path] = []
            with patch.dict(os.environ, self.environment(root), clear=False):
                result = open_review_request(
                    review,
                    cad_path=cad,
                    review_opener=reviewers.append,
                    native_opener=native.append,
                )
            self.assertEqual(len(reviewers), 1)
            self.assertEqual(native, [])
            self.assertEqual(result["native_cad"]["reason"], "explicit_native_cad_request_required")

    def test_explicit_native_request_opens_reviewer_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            cad = root / "drawing.kicad_pcb"
            review.write_text(MODIFIER, encoding="utf-8")
            cad.write_text("(kicad_pcb)", encoding="utf-8")
            opened: list[str] = []
            with patch.dict(os.environ, self.environment(root), clear=False):
                result = open_review_request(
                    review,
                    cad_path=cad,
                    open_native_cad=True,
                    review_opener=lambda _: opened.append("reviewer"),
                    native_opener=lambda _: opened.append("native_cad"),
                )
            self.assertEqual(opened, ["reviewer", "native_cad"])
            self.assertEqual(result["open_order"], ["interactive_drawing_modifier", "native_cad"])

    def test_pdf_cannot_be_native_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            pdf = root / "drawing.pdf"
            review.write_text(MODIFIER, encoding="utf-8")
            pdf.write_bytes(b"%PDF-placeholder")
            with patch.dict(os.environ, self.environment(root), clear=False):
                with self.assertRaisesRegex(PlanError, "rejects non-CAD artifacts"):
                    open_review_request(review, cad_path=pdf, open_native_cad=True)


if __name__ == "__main__":
    unittest.main()
