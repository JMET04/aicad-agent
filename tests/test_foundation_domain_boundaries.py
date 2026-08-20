from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.domain_rules import evaluate_domain_plan


FOUNDATION_DOMAINS = (
    "civil", "structural", "electrical", "plumbing", "hvac",
    "process_piping", "product_design",
)


def intent_line(domain: str) -> dict:
    return {
        "schema_version": "2.0",
        "drawing": {
            "name": f"{domain}-intent", "domain": domain, "units": "mm",
            "origin": [0, 0], "tolerance": 1e-6,
        },
        "steps": [{
            "id": "L001", "type": "line", "purpose": "intent baseline",
            "reasoning": "origin-controlled review geometry", "start": {"ref": "origin"},
            "construction": {"kind": "vector", "dx": 100, "dy": 0},
            "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 100}],
            "layer": "INTENT", "role": "annotation",
        }],
    }


class FoundationDomainBoundaryTests(unittest.TestCase):
    def test_registered_foundation_domains_return_explainable_block_not_exception(self) -> None:
        for domain in FOUNDATION_DOMAINS:
            with self.subTest(domain=domain):
                report = evaluate_domain_plan(intent_line(domain), "2d")
                self.assertEqual(report["status"], "failed")
                gate = next(item for item in report["checks"] if item["id"] == "DOMAIN.G000")
                self.assertEqual(gate["severity"], "hard")
                self.assertTrue(gate["evidence"]["specialist_generation_blocked"])
                self.assertTrue(gate["root_cause"])
                self.assertFalse(gate["prevention_rule_candidate"]["ruleEnabled"])

    def test_generic_geometry_cannot_masquerade_as_structural_validation(self) -> None:
        report = evaluate_domain_plan(intent_line("structural"), "2d")
        self.assertNotEqual(report["status"], "passed")
        self.assertNotEqual(report["domain"], "general")


if __name__ == "__main__":
    unittest.main()
