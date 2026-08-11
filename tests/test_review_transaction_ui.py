from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class ReviewTransactionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))

    def test_static_review_emits_formal_exact_reference_transaction(self) -> None:
        page = render_review_html(generate_view_package(self.plan, "3d", "mechanical"))
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertIn("function formalCorrection()", page)
        self.assertIn("op:'move_subobject'", page)
        self.assertIn("op:'set_subobject_parameter'", page)
        self.assertIn("op:'add_subobject_relation'", page)
        self.assertIn("expected_affected_instance_count", page)
        self.assertIn("expected_shared_parameter_groups", page)
        self.assertIn("source_sha256:pkg.source_sha256", page)
        self.assertIn("reviewOnly:true,accepted:false,ruleEnabled:false", page)
        self.assertIn("保持对边", page)

    def test_ui_keeps_precision_stroke_separate_from_hit_target(self) -> None:
        page = render_review_html(generate_view_package(self.plan, "3d", "electronics"))
        self.assertIn("stroke-width:.8", page)
        self.assertIn("stroke-width:12", page)
        self.assertIn("transactionRefs=new Map()", page)
        self.assertIn("aicad-agent-change-request.json", page)


if __name__ == "__main__":
    unittest.main()
