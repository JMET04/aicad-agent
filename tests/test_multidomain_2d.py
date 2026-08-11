from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.domain_rules import evaluate_domain_plan
from aicad.engine import PlanError, compile_plan
from aicad.exporters import export_all
from aicad.semantic import describe_plan


DOMAIN_CASES = {
    "mechanical": (("OUTLINE", "datum_edge"), ("CENTER", "axis"), ("HOLE", "mounting_hole")),
    "electronics": (("BOARD_OUTLINE", "board_edge"), ("KEEP_OUT", "keepout_edge"), ("PAD", "pad")),
    "architecture": (("WALL", "wall_face"), ("OPENING", "opening_jamb"), ("COLUMN", "column")),
    "packaging": (("CUT", "cut_edge"), ("CREASE", "fold_edge"), ("SLOT", "slot_end")),
}


def domain_plan(domain: str) -> dict:
    (layer1, role1), (layer2, role2), (layer3, role3) = DOMAIN_CASES[domain]
    return {
        "schema_version": "2.0",
        "drawing": {
            "id": f"DOC_{domain.upper()}",
            "name": f"{domain}_2d_fixture",
            "domain": domain,
            "units": "mm",
            "origin": [0, 0],
            "tolerance": 1e-6,
            "locks": ["L001.start"],
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
        },
        "steps": [
            {
                "id": "L001", "type": "line", "purpose": f"establish {role1}",
                "reasoning": "the first controlled datum begins at the drawing origin",
                "start": {"ref": "origin"}, "construction": {"kind": "vector", "dx": 100, "dy": 0},
                "constraints": [{"kind": "horizontal"}, {"kind": "length", "value": 100}],
                "layer": layer1, "roles": [role1, "datum"], "editable": False,
            },
            {
                "id": "L002", "type": "line", "purpose": f"establish {role2}",
                "reasoning": "the second object is perpendicular and starts at the first endpoint",
                "start": {"ref": "L001.end"},
                "construction": {"kind": "perpendicular", "to": "L001", "length": 50, "turn": "left"},
                "constraints": [
                    {"kind": "start_coincident", "target": "L001.end"},
                    {"kind": "perpendicular", "target": "L001"}, {"kind": "length", "value": 50},
                ],
                "depends_on": ["L001"], "layer": layer2, "role": role2,
            },
            {
                "id": "C001", "type": "circle", "purpose": f"locate {role3}",
                "reasoning": "the radial feature is positioned by an exact offset from the origin datum",
                "center": {"point": [25, 25]}, "radius": 5,
                "constraints": [
                    {"kind": "center_offset", "target": "L001.start", "dx": 25, "dy": 25},
                    {"kind": "diameter", "value": 10},
                ],
                "depends_on": ["L001"], "layer": layer3, "roles": [role3],
            },
        ],
    }


class MultiDomain2DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((ROOT / "schema" / "aicad-plan.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)

    def test_four_domains_share_one_compiler_and_preserve_semantics(self) -> None:
        validator = Draft202012Validator(self.schema)
        for domain, layer_roles in DOMAIN_CASES.items():
            with self.subTest(domain=domain):
                source = domain_plan(domain)
                validator.validate(source)
                plan = compile_plan(source)
                self.assertEqual(plan.domain, domain)
                self.assertEqual([item.layer for item in plan.entities], [item[0] for item in layer_roles])
                self.assertEqual(plan.entities[1].depends_on, ("L001",))
                self.assertFalse(plan.entities[0].editable)
                semantic = describe_plan(source, "2d", domain)
                self.assertEqual(semantic["objects"][1]["depends_on"], ["L001"])
                self.assertEqual(semantic["objects"][2]["source"]["cad_layer"], layer_roles[2][0])
                self.assertTrue(semantic["validation"]["valid"])

    def test_dxf_script_audit_and_manifest_retain_domain_layers_and_roles(self) -> None:
        source = domain_plan("electronics")
        plan = compile_plan(source)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            export_all(plan, output, "pcb")
            dxf = (output / "pcb.dxf").read_text(encoding="ascii")
            script = (output / "pcb.scr").read_text(encoding="ascii")
            audit = (output / "pcb.audit.md").read_text(encoding="utf-8")
            manifest = json.loads((output / "pcb.manifest.json").read_text(encoding="utf-8"))
            for layer in ("BOARD_OUTLINE", "KEEP_OUT", "PAD"):
                self.assertIn(f"8\n{layer}\n", dxf)
                self.assertIn(f"_Make\n{layer}\n", script)
            self.assertIn("| Depends on |", audit)
            self.assertIn("keepout_edge", audit)
            self.assertEqual(manifest["domain"], "electronics")
            self.assertEqual(manifest["layers"], {"BOARD_OUTLINE": 1, "KEEP_OUT": 1, "PAD": 1})
            self.assertEqual(manifest["dependency_edges"], 2)
            self.assertEqual(manifest["editable_entities"], 2)

    def test_forward_declared_dependency_and_non_ascii_layer_are_rejected(self) -> None:
        forward = domain_plan("mechanical")
        forward["steps"][0]["depends_on"] = ["L002"]
        with self.assertRaisesRegex(PlanError, "earlier entities"):
            compile_plan(forward)
        bad_layer = domain_plan("architecture")
        bad_layer["steps"][0]["layer"] = "墙体"
        with self.assertRaisesRegex(PlanError, "ASCII CAD layer"):
            compile_plan(bad_layer)

    def test_architecture_grid_bubble_is_a_strict_circle_role(self) -> None:
        source = domain_plan("architecture")
        bubble = source["steps"][2]
        bubble["layer"] = "GRID_BUBBLE"
        bubble["roles"] = ["grid_bubble"]
        result = evaluate_domain_plan(source, "2d", "architecture")
        self.assertIn(result["status"], {"passed", "passed_with_warnings"})
        self.assertFalse(any(check["id"] in {"DOMAIN.G003", "DOMAIN.2D.001"} and check["status"] == "fail" for check in result["checks"]))
        bubble["layer"] = "GRID"
        rejected = evaluate_domain_plan(source, "2d", "architecture")
        self.assertEqual(rejected["status"], "failed")
        self.assertTrue(any(check["id"] == "DOMAIN.2D.001" and check["status"] == "fail" for check in rejected["checks"]))

    def test_legacy_plan_defaults_remain_stable(self) -> None:
        source = json.loads((ROOT / "examples" / "rectangle.plan.json").read_text(encoding="utf-8"))
        plan = compile_plan(source)
        self.assertEqual(plan.domain, "general")
        self.assertTrue(all(item.layer == "AICAD_GEOMETRY" for item in plan.entities))
        self.assertTrue(all(item.editable for item in plan.entities))


if __name__ == "__main__":
    unittest.main()
