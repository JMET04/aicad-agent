from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "agent-plugin" / "aicad-agent"
sys.path.insert(0, str(ROOT / "src"))

from aicad.domain_maturity import assess_domain_maturity, assess_domain_registry
from aicad.domain_rules import evaluate_domain_plan
from aicad.engine import PlanError
from aicad.semantic import describe_plan, validate_semantic_document


def _registry() -> dict:
    return json.loads(
        (PLUGIN_ROOT / "rules" / "engineering_domain_registry.json").read_text(
            encoding="utf-8"
        )
    )


def _intent_plan(domain: str) -> dict:
    return {
        "schema_version": "2.0",
        "drawing": {
            "name": f"{domain}-maturity-intent",
            "domain": domain,
            "units": "mm",
            "origin": [0, 0],
            "tolerance": 1e-6,
        },
        "steps": [
            {
                "id": "L001",
                "type": "line",
                "purpose": "intent baseline",
                "reasoning": "origin-controlled review geometry",
                "start": {"ref": "origin"},
                "construction": {"kind": "vector", "dx": 100, "dy": 0},
                "constraints": [
                    {"kind": "horizontal"},
                    {"kind": "length", "value": 100},
                ],
                "layer": "INTENT",
                "role": "annotation",
            }
        ],
    }


def _minimal_general_plugin(
    directory: str, *, include_cad_rules: bool = True, executable: bool = True
) -> Path:
    root = Path(directory)
    rules = root / "rules"
    runtime = root / "runtime" / "src" / "aicad"
    rules.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (root / "scripts").mkdir()
    shutil.copyfile(
        PLUGIN_ROOT / "rules" / "normative_governance_rules.json",
        rules / "normative_governance_rules.json",
    )
    if include_cad_rules:
        shutil.copyfile(
            PLUGIN_ROOT / "rules" / "cad_normative_quality_rules.json",
            rules / "cad_normative_quality_rules.json",
        )
    source = (
        "def evaluate_domain_plan(data, space, domain='general'):\n"
        "    return {'status': 'review_only'}\n"
        if executable
        else "def unrelated_helper():\n    return None\n"
    )
    (runtime / "domain_rules.py").write_text(source, encoding="utf-8")
    return root


def _load_agent():
    path = PLUGIN_ROOT / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_maturity", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class DomainMaturityAuthorityTests(unittest.TestCase):
    def test_current_registry_earns_only_code_owned_boundaries(self) -> None:
        result = assess_domain_registry(_registry(), plugin_root=PLUGIN_ROOT)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(
            result["domains"]["civil"]["effectiveMaturity"], "constrained"
        )
        self.assertEqual(
            result["domains"]["structural"]["effectiveMaturity"], "foundation"
        )
        self.assertTrue(
            result["domains"]["structural"]["specialistGenerationBlocked"]
        )

    def test_registry_text_cannot_self_grant_advanced_or_foundation_domains(self) -> None:
        registry = copy.deepcopy(_registry())
        registry["domains"]["general"]["maturity"] = "advanced"
        registry["domains"]["structural"]["maturity"] = "advanced"
        result = assess_domain_registry(registry, plugin_root=PLUGIN_ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["effectiveRegistry"]["domains"]["general"]["maturity"],
            "constrained",
        )
        self.assertEqual(
            result["effectiveRegistry"]["domains"]["structural"]["maturity"],
            "foundation",
        )
        self.assertTrue(
            any("declared_maturity_exceeds_code_ceiling" in row for row in result["issues"])
        )

    def test_missing_evidence_downgrades_to_foundation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _minimal_general_plugin(directory, include_cad_rules=False)
            decision = assess_domain_maturity(
                "general", "constrained", plugin_root=root
            )
        self.assertEqual(decision["earnedMaturity"], "foundation")
        self.assertEqual(decision["effectiveMaturity"], "foundation")
        self.assertFalse(decision["evidenceClosure"]["ok"])
        self.assertTrue(decision["specialistGenerationBlocked"])
        self.assertIn(
            "evidence_missing:rules.cad_normative_quality", decision["issues"]
        )

    def test_named_file_without_required_function_is_not_executable_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _minimal_general_plugin(directory, executable=False)
            decision = assess_domain_maturity(
                "general", "constrained", plugin_root=root
            )
        self.assertTrue(decision["evidenceClosure"]["ok"])
        self.assertFalse(decision["capabilities"]["domain_semantic_validator"]["ok"])
        self.assertEqual(decision["effectiveMaturity"], "foundation")
        self.assertTrue(
            any("capability_functions_missing" in row for row in decision["issues"])
        )

    def test_placeholder_function_does_not_count_as_executable_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _minimal_general_plugin(directory)
            implementation = root / "runtime" / "src" / "aicad" / "domain_rules.py"
            implementation.write_text(
                "def evaluate_domain_plan(data, space, domain='general'):\n"
                "    pass\n",
                encoding="utf-8",
            )
            decision = assess_domain_maturity("general", "constrained", plugin_root=root)
        capability = decision["capabilities"]["domain_semantic_validator"]
        self.assertFalse(capability["ok"])
        self.assertEqual(capability["placeholderFunctions"], ["evaluate_domain_plan"])
        self.assertEqual(decision["effectiveMaturity"], "foundation")
        self.assertTrue(
            any("capability_functions_placeholder" in row for row in decision["issues"])
        )

    def test_incomplete_closure_drives_runtime_domain_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _minimal_general_plugin(directory, include_cad_rules=False)
            with patch(
                "aicad.domain_maturity.discover_plugin_root", return_value=root
            ):
                report = evaluate_domain_plan(_intent_plan("general"), "2d")
        self.assertEqual(report["status"], "failed")
        gate = next(row for row in report["checks"] if row["id"] == "DOMAIN.G000")
        self.assertEqual(gate["status"], "fail")
        self.assertEqual(
            report["maturity_decision"]["effective_maturity"], "foundation"
        )
        self.assertTrue(
            report["maturity_decision"]["specialist_generation_blocked"]
        )

    def test_foundation_domain_remains_hard_blocked(self) -> None:
        report = evaluate_domain_plan(_intent_plan("structural"), "2d")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["maturity_decision"]["code_ceiling"], "foundation")
        self.assertEqual(report["maturity_decision"]["effective_maturity"], "foundation")
        gate = next(row for row in report["checks"] if row["id"] == "DOMAIN.G000")
        self.assertTrue(gate["evidence"]["production_release_blocked"])

    def test_semantic_maturity_tampering_is_rejected(self) -> None:
        payload = describe_plan(_intent_plan("general"), "2d")
        payload["domain_profile"]["maturity"] = "advanced"
        with self.assertRaisesRegex(PlanError, "code-owned effective decision"):
            validate_semantic_document(payload)

    def test_domain_report_schema_requires_maturity_decision(self) -> None:
        schema = json.loads(
            (ROOT / "schema" / "aicad-domain-validation.schema.json").read_text(
                encoding="utf-8"
            )
        )
        report = evaluate_domain_plan(_intent_plan("general"), "2d")
        Draft202012Validator(schema).validate(report)
        without_decision = copy.deepcopy(report)
        without_decision.pop("maturity_decision")
        self.assertTrue(
            any(
                error.validator == "required"
                for error in Draft202012Validator(schema).iter_errors(without_decision)
            )
        )

    def test_public_agent_registry_returns_effective_maturity_evidence(self) -> None:
        result = _load_agent().get_engineering_domain_registry()
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["registry"]["maturityAuthority"],
            "code_ceiling_plus_executable_capabilities_plus_sha256_evidence_closure",
        )
        structural = result["registry"]["domains"]["structural"]
        self.assertEqual(structural["maturity"], "foundation")
        self.assertTrue(
            structural["maturityDecision"]["specialistGenerationBlocked"]
        )


if __name__ == "__main__":
    unittest.main()
