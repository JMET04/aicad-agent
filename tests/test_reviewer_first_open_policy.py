from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.engine import PlanError
from aicad.review_launch import open_review_request


MODIFIER = '<html data-artifact-role="interactive_drawing_modifier"><body>review</body></html>'


class ReviewerFirstOpenPolicyTests(unittest.TestCase):
    def environment(self, root: Path) -> dict[str, str]:
        return {
            "AICAD_REVIEW_LAUNCH": "",
            "AICAD_REVIEW_STAGE_DIR": str(root / "stage"),
            "AICAD_NO_GUI": "",
            "CI": "",
        }

    def test_generic_view_opens_only_modifier_even_when_cad_path_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            cad = root / "drawing.dwg"
            review.write_text(MODIFIER, encoding="utf-8")
            cad.write_bytes(b"native-cad-placeholder")
            review_opened: list[Path] = []
            native_opened: list[Path] = []
            with patch.dict(os.environ, self.environment(root), clear=False):
                result = open_review_request(
                    review,
                    cad_path=cad,
                    review_opener=review_opened.append,
                    native_opener=native_opened.append,
                )
            self.assertEqual(len(review_opened), 1)
            self.assertEqual(native_opened, [])
            self.assertEqual(result["open_order"], ["interactive_drawing_modifier"])
            self.assertEqual(result["native_cad"]["status"], "blocked")
            self.assertEqual(
                result["native_cad"]["reason"], "explicit_native_cad_request_required"
            )

    def test_explicit_native_request_preserves_reviewer_then_cad_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            cad = root / "drawing.SLDPRT"
            review.write_text(MODIFIER, encoding="utf-8")
            cad.write_bytes(b"native-cad-placeholder")
            opened: list[tuple[str, Path]] = []
            with patch.dict(os.environ, self.environment(root), clear=False):
                result = open_review_request(
                    review,
                    cad_path=cad,
                    open_native_cad=True,
                    review_opener=lambda path: opened.append(("reviewer", path)),
                    native_opener=lambda path: opened.append(("native_cad", path)),
                )
            self.assertEqual([kind for kind, _ in opened], ["reviewer", "native_cad"])
            self.assertEqual(result["open_order"], ["interactive_drawing_modifier", "native_cad"])
            self.assertEqual(result["native_cad"]["status"], "launched")

    def test_raw_pdf_is_never_accepted_as_native_cad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            raw_pdf = root / "drawing.pdf"
            review.write_text(MODIFIER, encoding="utf-8")
            raw_pdf.write_bytes(b"%PDF-placeholder")
            with patch.dict(os.environ, self.environment(root), clear=False):
                with self.assertRaisesRegex(PlanError, "rejects non-CAD artifacts"):
                    open_review_request(review, cad_path=raw_pdf, open_native_cad=True)

    def test_unmarked_html_cannot_masquerade_as_modifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "plain.html"
            review.write_text("<html><body>plain PDF wrapper</body></html>", encoding="utf-8")
            with patch.dict(os.environ, self.environment(root), clear=False):
                with self.assertRaisesRegex(PlanError, "interactive_drawing_modifier"):
                    open_review_request(review)

    def test_native_open_is_blocked_if_reviewer_did_not_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "drawing.review.html"
            cad = root / "drawing.dxf"
            review.write_text(MODIFIER, encoding="utf-8")
            cad.write_text("0\nEOF\n", encoding="ascii")
            native_opened: list[Path] = []
            environment = self.environment(root) | {"CI": "true"}
            with patch.dict(os.environ, environment, clear=False):
                result = open_review_request(
                    review,
                    cad_path=cad,
                    open_native_cad=True,
                    review_mode="auto",
                    native_opener=native_opened.append,
                )
            self.assertEqual(native_opened, [])
            self.assertEqual(result["native_cad"]["status"], "blocked")
            self.assertEqual(result["native_cad"]["reason"], "reviewer_must_launch_before_native_cad")


if __name__ == "__main__":
    unittest.main()
