from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeSolidWorksTopologyRuleTests(unittest.TestCase):
    def test_native_topology_rule_pack_is_complete_and_review_locked(self) -> None:
        rules = json.loads((ROOT / "rules" / "native_solidworks_topology_rules.json").read_text(encoding="utf-8"))
        self.assertEqual(rules["schema"], "aicad_native_solidworks_topology_rules_v1")
        self.assertTrue(rules["reviewOnly"])
        self.assertFalse(rules["accepted"])
        self.assertFalse(rules["ruleEnabled"])
        self.assertTrue(rules["packagingGated"])
        ids = {item["id"] for item in rules["rules"]}
        self.assertEqual(ids, {f"SW-N{index:03d}" for index in range(1, 11)})
        text = json.dumps(rules, ensure_ascii=False)
        for token in (
            "GetPersistReference3",
            "GetObjectByPersistReference3",
            "AICAD_REF_NNNN",
            "key-set equality",
            "COM wrapper lifetime",
            "AICAD_REF_COUNT",
        ):
            self.assertIn(token, text)

    def test_documentation_preserves_honest_authority_boundary(self) -> None:
        guide = (ROOT / "docs" / "NATIVE_SOLIDWORKS_TOPOLOGY.md").read_text(encoding="utf-8")
        self.assertIn("native_topology_authority=true", guide)
        self.assertIn("offline plan", guide.lower())
        self.assertIn("does not invent", guide)
        self.assertIn("SW-N008", guide)
        self.assertIn("SW-N009", guide)


if __name__ == "__main__":
    unittest.main()
