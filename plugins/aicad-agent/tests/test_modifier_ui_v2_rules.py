from __future__ import annotations

import json
import importlib.util
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" if (ROOT / "runtime" / "src").is_dir() else ROOT.parents[1]
sys.path.insert(0, str(SOURCE / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class ModifierUiV2PackagedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((SOURCE / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((SOURCE / "schema" / "aicad-view-package.schema.json").read_text(encoding="utf-8"))

    def test_packaged_runtime_has_free_section_hidden_keys_and_core_parameters(self) -> None:
        package = generate_view_package(self.plan, "3d", "mechanical")
        Draft202012Validator(self.schema).validate(package)
        page = render_review_html(package)
        self.assertEqual(validate_review_html(page, "3d"), [])
        self.assertIn("\u81ea\u7531\u622a\u9762", page)
        self.assertIn("entity-pair.key-geometry .view-entity{opacity:0}", page)
        self.assertIn("parameter-row", page)
        self.assertNotIn("\u7ea0\u9519\u610f\u56fe", page)
        self.assertNotIn("\u6b63\u5f0f\u4e8b\u52a1", page)
        objects = package["selector_3d"]["objects"]
        self.assertEqual(sum(len(x["core_parameters"]) for x in objects), 16)
        keys = {s["reference_key"] for o in objects for s in o["subobjects"]}
        self.assertIn("F002|profile.pattern.pitch_circle", keys)
        self.assertIn("F003|profile.center", keys)

    def test_agent_capabilities_advertise_selectable_points(self) -> None:
        script = ROOT / "scripts" / "aicad_agent.py"
        spec = importlib.util.spec_from_file_location("aicad_agent_modifier_v2_test", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        geometry_types = module.capabilities()["universal_cad"]["exact_subobject_correction"]["geometry_types"]
        self.assertIn("point", geometry_types)
        exact = module.capabilities()["universal_cad"]["exact_subobject_correction"]
        self.assertEqual(exact["selection_measurements"]["line"], ["length_mm", "start", "end"])
        self.assertEqual(exact["coordinate_system"]["id"], "MODEL_XYZ")


if __name__ == "__main__":
    unittest.main()
