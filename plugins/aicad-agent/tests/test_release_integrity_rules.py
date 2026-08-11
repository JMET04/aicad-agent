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
                "REL-G011", "REL-G012", "REL-G013", "REL-G014", "REL-G015", "REL-G016", "REL-G017", "REL-G018", "REL-G019", "REL-G020", "REL-G021",
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
    def test_runtime_fallback_paths_are_environment_derived(self) -> None:
        data = json.loads((PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8"))
        rule = next(item for item in data["rules"] if item["id"] == "REL-G018")
        packaged_runtime = PLUGIN / "runtime" / "src" / "aicad" / "review_launch.py"
        source_runtime = PLUGIN.parents[1] / "src" / "aicad" / "review_launch.py"
        runtime_path = packaged_runtime if packaged_runtime.is_file() else source_runtime
        self.assertTrue(runtime_path.is_file(), runtime_path)
        runtime = runtime_path.read_text(encoding="utf-8")
        self.assertIn("environment variables", rule["prevention"])
        self.assertNotIn("C:\\Users\\", runtime)

    def test_installer_payload_is_manifest_allowlisted(self) -> None:
        data = json.loads((PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8"))
        rule = next(item for item in data["rules"] if item["id"] == "REL-G017")
        self.assertEqual(rule["name"], "installed_payload_is_manifest_allowlisted")
        self.assertIn("integration-manifest.json", rule["root_cause"])
        self.assertIn("Install only files declared", rule["prevention"])
        self.assertIn("caches and temporary files", rule["prevention"])

    def test_modern_dxf_features_require_version_and_native_host_parity(self) -> None:
        data = json.loads((PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8"))
        rule = next(item for item in data["rules"] if item["id"] == "REL-G020")
        self.assertEqual(rule["name"], "declared_dxf_capability_and_native_parser_parity")
        self.assertIn("declared DXF version", rule["root_cause"])
        self.assertIn("declared ACADVER", rule["prevention"])
        self.assertIn("real AutoCAD import", rule["prevention"])
        self.assertIn("semantic persistence", rule["prevention"])

    def test_capability_surfaces_are_noncontradictory(self) -> None:
        data = json.loads((PLUGIN / "rules" / "release_integrity_rules.json").read_text(encoding="utf-8"))
        rule = next(item for item in data["rules"] if item["id"] == "REL-G021")
        self.assertIn("evolved independently", rule["root_cause"])
        self.assertIn("stale-version contradictions", rule["prevention"])
        self.assertIn("real-host import-save-reopen evidence", rule["prevention"])


if __name__ == "__main__":
    unittest.main()
