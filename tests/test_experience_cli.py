from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "agent-plugin" / "aicad-agent" / "rules"

sys.path.insert(0, str(ROOT / "src"))

from aicad.cli import main
from aicad.experience import EXPECTED_LOCKS, populate_coverage_for_test


def civil_context() -> dict:
    return {
        "schema": "aicad_design_context_v1",
        "contextId": "CTX_CIVIL_CLI",
        "domain": "civil",
        "spaces": ["3d", "2d"],
        "deliveryStage": "engineering_review",
        "productFamilies": [],
        "riskTags": ["interface"],
        "changeTags": ["geometry"],
        "requestedOutputs": ["review_html"],
        "applicableStandards": [
            {
                "standard": "PROJECT-SPEC",
                "edition": "CONTROLLED",
                "scope": "civil",
                "authority": "approved_engineering_input",
            }
        ],
        "assumptions": [],
        "locks": dict(EXPECTED_LOCKS),
    }


def invoke(arguments: list[str]) -> tuple[int, dict, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(arguments)
    text = stdout.getvalue().strip()
    return code, json.loads(text) if text else {}, stderr.getvalue()


class ExperienceCliTests(unittest.TestCase):
    def test_schema_and_domain_registry_commands_resolve_controlled_assets(self) -> None:
        context_code, context_payload, context_error = invoke(
            ["experience-context-schema"]
        )
        self.assertEqual(context_code, 0, context_error)
        self.assertTrue(context_payload["ok"])
        Draft202012Validator.check_schema(context_payload["schema"])
        self.assertEqual(
            context_payload["schema"]["properties"]["domain"]["enum"],
            [
                "general",
                "architecture",
                "packaging",
                "mechanical",
                "electronics",
                "sheet_metal",
                "civil",
                "structural",
                "electrical",
                "plumbing",
                "hvac",
                "process_piping",
                "product_design",
            ],
        )

        coverage_code, coverage_payload, coverage_error = invoke(
            ["review-coverage-schema"]
        )
        self.assertEqual(coverage_code, 0, coverage_error)
        Draft202012Validator.check_schema(coverage_payload["schema"])
        evidence_schema = coverage_payload["schema"]["properties"]["entries"]["items"]["properties"]["evidenceRefs"]["items"]
        self.assertEqual(
            set(evidence_schema["required"]), {"path", "size", "sha256", "kind"}
        )

        registry_code, registry_payload, registry_error = invoke(
            ["domain-registry", "--rules-root", str(RULES)]
        )
        self.assertEqual(registry_code, 0, registry_error)
        self.assertTrue(registry_payload["ok"])
        self.assertEqual(len(registry_payload["registry"]["domains"]), 13)
        self.assertEqual(registry_payload["registry"]["safetyLocks"], EXPECTED_LOCKS)

    def test_experience_recall_cli_runs_full_domain_inventory_from_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.json"
            context_path.write_text(
                json.dumps(civil_context(), ensure_ascii=False), encoding="utf-8"
            )
            code, payload, error = invoke(
                ["experience-recall", str(context_path), "--max-cards", "1"]
            )
        self.assertEqual(code, 0, error)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["context"]["spaces"], ["2d", "3d"])
        self.assertEqual(payload["domainProfile"]["id"], "civil")
        civil_rules = {
            row["coverageKey"]
            for row in payload["coverageInventory"]
            if row["coverageKey"].startswith("rule:civil:CIV-G")
        }
        self.assertEqual(civil_rules, {f"rule:civil:CIV-G{index:03d}" for index in range(1, 21)})
        self.assertGreaterEqual(
            len([row for row in payload["cards"] if row["required"]]), 3
        )

    def test_coverage_validate_cli_checks_real_files_and_blocks_pending_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path = root / "context.json"
            context_path.write_text(json.dumps(civil_context()), encoding="utf-8")
            recall_code, recalled, recall_error = invoke(
                [
                    "experience-recall",
                    str(context_path),
                    "--rules-root",
                    str(RULES),
                ]
            )
            self.assertEqual(recall_code, 0, recall_error)

            evidence_root = root / "evidence"
            ledger = populate_coverage_for_test(recalled, evidence_root=evidence_root)
            recall_path = root / "recall.json"
            ledger_path = root / "ledger.json"
            recall_path.write_text(json.dumps(recalled), encoding="utf-8")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            code, validation, error = invoke(
                [
                    "coverage-validate",
                    str(recall_path),
                    str(ledger_path),
                    "--evidence-root",
                    str(evidence_root),
                ]
            )
            self.assertEqual(code, 0, error)
            self.assertTrue(validation["ok"])
            self.assertTrue(
                all(value is False for value in validation["readinessBoundary"].values())
            )

            ledger_path.write_text(
                json.dumps(recalled["coverageTemplate"]), encoding="utf-8"
            )
            blocked_code, blocked, blocked_error = invoke(
                [
                    "coverage-validate",
                    str(recall_path),
                    str(ledger_path),
                    "--evidence-root",
                    str(evidence_root),
                ]
            )
            self.assertEqual(blocked_code, 2, blocked_error)
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["status"], "blocked")
            self.assertTrue(blocked["failures"])

    def test_invalid_explicit_rules_root_fails_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, payload, error = invoke(
                ["domain-registry", "--rules-root", directory]
            )
        self.assertEqual(code, 2)
        self.assertEqual(payload, {})
        self.assertIn("Invalid controlled rules root", error)


if __name__ == "__main__":
    unittest.main()
