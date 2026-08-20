from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class ReviewUiOperationalConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = json.loads(
            (ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8")
        )
        cls.drawing = json.loads(
            (ROOT / "examples" / "architecture-dimensions.plan.json").read_text(encoding="utf-8")
        )
        cls.text_drawing = json.loads(
            (ROOT / "examples" / "protocol3-text-layer.plan.json").read_text(encoding="utf-8")
        )
        cls.text_page = render_review_html(
            generate_view_package(cls.text_drawing, "2d", "general")
        )
        cls.model_page = render_review_html(generate_view_package(cls.model, "3d", "mechanical"))
        cls.drawing_page = render_review_html(generate_view_package(cls.drawing, "2d", "architecture"))

    def test_stage_rail_and_truthful_safety_states_are_explicit(self) -> None:
        page = self.model_page
        self.assertIn('class="stage-rail"', page)
        for stage in ("source", "select", "edit", "verify", "handoff"):
            self.assertIn(f'data-stage="{stage}"', page)
        self.assertIn("FRESHNESS / 新鲜度", page)
        self.assertIn("SNAPSHOT BOUND", page)
        self.assertIn("SEVERITY / 风险级", page)
        self.assertIn("WARNING", page)
        self.assertIn("RELEASE / 发布门禁", page)
        self.assertIn("BLOCKED", page)
        self.assertIn("未与外部最新文件自动比对，不声称实时新鲜", page)
        self.assertIn("function updateOperationalStatus()", page)

    def test_command_zone_is_persistent_and_locked_until_a_change_exists(self) -> None:
        page = self.model_page
        command_index = page.index('class="command-zone"')
        submit_index = page.index('id="submitRequest"')
        self.assertLess(command_index, submit_index)
        self.assertIn('id="submitRequest" class="primary" disabled', page)
        self.assertIn('id="exportRequest" disabled', page)
        self.assertIn("document.getElementById('submitRequest').disabled=!rows.length", page)
        self.assertIn("position:sticky;bottom:0", page)

    def test_line_grammar_is_semantically_distinct_and_explained(self) -> None:
        page = self.drawing_page
        for label in ("轮廓线 · 粗实线", "可见线 · 中实线", "隐藏线 · 短虚线", "中心线 · 点划线", "尺寸线 · 细实线"):
            self.assertIn(label, page)
        self.assertIn(".view-entity.layer-outline{stroke:#101e28;stroke-width:2.2}", page)
        self.assertIn(".view-entity.layer-hidden{stroke:#556773;stroke-width:.8;stroke-dasharray:7 3}", page)
        self.assertIn(".view-entity.layer-center{stroke:#9a3b08;stroke-width:.7;stroke-dasharray:12 3 2 3}", page)
        self.assertIn(".view-entity.layer-dimension{stroke:#1e5676;stroke-width:.72}", page)

    def test_every_native_annotation_is_rendered_inside_a_visible_frame(self) -> None:
        page = self.text_page
        native_text_count = page.count('class="native-text')
        frame_count = page.count('class="annotation-frame')
        self.assertGreater(native_text_count, 0)
        self.assertGreaterEqual(frame_count, native_text_count)
        self.assertRegex(
            page,
            re.compile(
                r'<g class="annotation-box"[^>]*><rect class="annotation-frame"[^>]*/><text class="native-text',
                re.DOTALL,
            ),
        )
        self.assertIn("标注框 · 文字在框内", page)
        self.assertIn('class="annotation-frame dimension-frame"', self.drawing_page)
        self.assertIn('class="dimension-value', self.drawing_page)

    def test_keyboard_focus_reduced_motion_and_responsive_gates_are_present(self) -> None:
        page = self.model_page
        self.assertIn('tabindex="0" role="button" aria-label="选择 ', page)
        self.assertIn("document.querySelectorAll('.view-hit').forEach(hit=>", page)
        self.assertIn("hit.addEventListener('keydown'", page)
        self.assertIn("button:focus-visible", page)
        self.assertIn(".coordinate-toggle input:focus-visible+.switch-track", page)
        self.assertIn("@media(max-width:1240px)", page)
        self.assertIn("@media(max-width:880px)", page)
        self.assertIn("@media(max-width:560px)", page)
        self.assertIn("@media(prefers-reduced-motion:reduce)", page)
        self.assertIn('aria-label="截面请求"', page)
        self.assertIn('aria-label="移动坐标轴"', page)
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertEqual(validate_review_html(self.drawing_page, "2d"), [])


if __name__ == "__main__":
    unittest.main()
