from __future__ import annotations

import json
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]


class ReleaseIntegrityRuleTests(unittest.TestCase):
    def test_release_failures_are_encoded_as_persistent_rules(self) -> None:
        payload = json.loads(
            (PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["schema"], "aicad_release_integrity_rules_v1")
        rules = {item["id"]: item for item in payload["rules"]}
        self.assertEqual(set(rules), {"REL-G001", "REL-G002", "REL-G003", "REL-G004", "REL-G005", "REL-G006"})
        for rule in rules.values():
            self.assertTrue(rule["symptom"])
            self.assertTrue(rule["root_cause"])
            self.assertTrue(rule["prevention"])


if __name__ == "__main__":
    unittest.main()

