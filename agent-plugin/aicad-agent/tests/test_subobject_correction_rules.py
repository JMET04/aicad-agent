from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SubobjectCorrectionRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = json.loads((ROOT / "rules" / "subobject_correction_rules.json").read_text(encoding="utf-8"))

    def test_exact_correction_rule_pack_is_complete_and_review_locked(self) -> None:
        self.assertEqual(self.rules["schema_version"], "1.0")
        self.assertEqual(
            self.rules["review_policy"],
            {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
        )
        rows = {row["id"]: row for row in self.rules["rules"]}
        self.assertEqual(set(rows), {f"SUB-G{index:03d}" for index in range(1, 18)})
        text = json.dumps(self.rules, ensure_ascii=False)
        for term in (
            "source SHA-256", "canonical_cross_view_reference_metadata", "keep_opposite",
            "shared_parameter_group", "full_dependency_replay", "positive_residual_wall",
            "no_fake_geometry_change", "native CAD persistent topology", "real_browser",
            "single_visible_modification_flow", "normalized_free_section_plane",
            "hidden_key_geometry_hover", "compiled_core_parameter_catalog",
            "compiled_typed_selection_measurement", "synchronized_coordinate_system_visibility",
        ):
            self.assertIn(term, text)

    def test_skill_reference_documents_fail_closed_protocol(self) -> None:
        text = (ROOT / "skills" / "aicad-model-3d" / "references" / "subobject-correction.md").read_text(encoding="utf-8")
        self.assertIn("Never detach silently", text)
        self.assertIn("residual-wall", text)
        self.assertIn("Native persistent BREP", text)


if __name__ == "__main__":
    unittest.main()
