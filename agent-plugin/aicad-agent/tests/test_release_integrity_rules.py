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
        self.assertEqual(
            set(rules),
            {
                "REL-G001", "REL-G002", "REL-G003", "REL-G004",
                "REL-G005", "REL-G006", "REL-G007", "REL-G008", "REL-G009", "REL-G010",
                "REL-G011", "REL-G012", "REL-G013", "REL-G014", "REL-G015", "REL-G016",
            },
        )
        for rule in rules.values():
            self.assertTrue(rule["symptom"])
            self.assertTrue(rule["root_cause"])
            self.assertTrue(rule["prevention"])

    def test_marketplace_runtime_rule_requires_isolated_behavior(self) -> None:
        payload = json.loads(
            (PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8")
        )
        rule = next(item for item in payload["rules"] if item["id"] == "REL-G011")
        self.assertIn("runtime/src/aicad/engine.py", rule["prevention"])
        self.assertIn("real remote-tag installation", rule["prevention"])
        self.assertIn("without repository src on sys.path", rule["prevention"])

    def test_git_checkout_rule_pins_line_endings_before_hash_verification(self) -> None:
        payload = json.loads(
            (PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8")
        )
        rule = next(item for item in payload["rules"] if item["id"] == "REL-G012")
        self.assertIn("Canonicalize every assembled text file", rule["prevention"])
        self.assertIn(".gitattributes", rule["prevention"])
        self.assertIn("fixed to LF", rule["prevention"])
        self.assertIn("real remote-tag installation", rule["prevention"])

    def test_clean_environment_rule_declares_jsonschema(self) -> None:
        payload = json.loads(
            (PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8")
        )
        rule = next(item for item in payload["rules"] if item["id"] == "REL-G013")
        requirements = (PLUGIN / "requirements-packaging.txt").read_text(encoding="utf-8")
        notices = (PLUGIN / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("jsonschema>=4.23,<5", requirements)
        self.assertIn("jsonschema", notices)
        self.assertIn("clean environment", rule["prevention"])


    def test_reference_preview_rule_requires_encoding_and_browser_gates(self) -> None:
        payload = json.loads(
            (PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8")
        )
        rule = next(item for item in payload["rules"] if item["id"] == "REL-G014")
        self.assertIn("replacement/private-use", rule["prevention"])
        self.assertIn("viewBox aspect ratio", rule["prevention"])
        self.assertIn("real-browser", rule["prevention"])
        self.assertIn("overlap", rule["prevention"])

    def test_host_command_rule_uses_get_command_source(self) -> None:
        payload = json.loads(
            (PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8")
        )
        rule = next(item for item in payload["rules"] if item["id"] == "REL-G015")
        self.assertIn("Get-Command", rule["root_cause"])
        self.assertIn("Source returned by Get-Command", rule["prevention"])
        self.assertIn("default command-name path", rule["prevention"])
    def test_release_installer_must_preserve_verified_hashes(self) -> None:
        data = json.loads((PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8"))
        rule = next(item for item in data["rules"] if item["id"] == "REL-G016")
        self.assertEqual(rule["name"], "installed_package_integrity_is_immutable")
        self.assertIn("byte-for-byte", rule["prevention"])
        self.assertIn("SHA256SUMS", rule["root_cause"])

if __name__ == "__main__":
    unittest.main()
