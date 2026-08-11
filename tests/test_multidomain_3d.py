from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.engine import PlanError
from aicad.engine3d import compile_plan3d
from aicad.exporters3d import export_plan3d
from aicad.semantic import describe_plan


DOMAIN_ROLES = {
    "mechanical": ("body", "boss", "mounting_hole"),
    "electronics": ("enclosure", "connector", "mounting_hole"),
    "sheet_metal": ("blank", "flange", "hole"),
    "architecture": ("slab", "column", "opening"),
    "packaging": ("panel", "tab", "lock"),
}


class MultiDomain3DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "schema" / "aicad-3d-plan.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)

    def source(self, domain: str) -> dict:
        value = copy.deepcopy(self.base)
        value["part"].update({
            "id": f"PART_{domain.upper()}", "domain": domain, "locks": ["F001.profile.center"],
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
        })
        roles = DOMAIN_ROLES[domain]
        for index, feature in enumerate(value["features"]):
            feature["roles"] = [roles[min(index, len(roles) - 1)]]
            feature["editable"] = index != 0
        return value

    def test_five_domains_share_one_ordered_feature_kernel(self) -> None:
        validator = Draft202012Validator(self.schema)
        expected_hashes = set()
        for domain in DOMAIN_ROLES:
            with self.subTest(domain=domain):
                source = self.source(domain)
                validator.validate(source)
                plan = compile_plan3d(source)
                self.assertEqual(plan.domain, domain)
                self.assertFalse(plan.features[0].editable)
                self.assertEqual(plan.features[0].roles, (DOMAIN_ROLES[domain][0],))
                payload = describe_plan(source, "3d")
                self.assertEqual(payload["document"]["domain"], domain)
                self.assertEqual(payload["objects"][0]["roles"], [DOMAIN_ROLES[domain][0]])
                self.assertTrue(payload["validation"]["valid"])
                expected_hashes.add(payload["document"]["source_sha256"])
        self.assertEqual(len(expected_hashes), len(DOMAIN_ROLES), "domain/role metadata is part of the auditable source identity")

    def test_declared_domain_conflict_is_rejected(self) -> None:
        with self.assertRaisesRegex(PlanError, "conflicts with requested domain"):
            describe_plan(self.source("electronics"), "3d", "mechanical")

    def test_3d_execution_audit_and_manifest_retain_roles_and_domain(self) -> None:
        plan = compile_plan3d(self.source("electronics"))
        with tempfile.TemporaryDirectory() as directory:
            paths = export_plan3d(plan, Path(directory), "enclosure", None)
            execution = json.loads(paths["execution"].read_text(encoding="utf-8"))
            audit = paths["audit"].read_text(encoding="utf-8")
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(execution["features"][0]["roles"], ["enclosure"])
            self.assertFalse(execution["features"][0]["editable"])
            self.assertIn("- Domain: `electronics`", audit)
            self.assertIn("| Roles | Editable |", audit)
            self.assertEqual(manifest["domain"], "electronics")
            self.assertEqual(manifest["editable_features"], len(plan.features) - 1)
            self.assertEqual(manifest["roles"]["enclosure"], 1)


if __name__ == "__main__":
    unittest.main()
