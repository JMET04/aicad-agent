from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
REPOSITORY = PLUGIN.parents[1]
RUNTIME = PLUGIN / "runtime"
SOURCE_ROOT = RUNTIME if (RUNTIME / "src" / "aicad" / "reference_rebuild.py").is_file() else REPOSITORY
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from aicad.reference_rebuild import build_reference_reconstruction, validate_reference_rebuild


def load_agent_module():
    script = PLUGIN / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_release_reference", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load aicad_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceRebuildReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        examples = SOURCE_ROOT / "examples"
        cls.plan = json.loads((examples / "web_reference_plate.plan.json").read_text(encoding="utf-8"))
        cls.reference = json.loads((examples / "web_reference_plate.reference.json").read_text(encoding="utf-8"))
        cls.reference["reference"]["locator"] = str((examples / "web_reference_plate.html").resolve())
        cls.agent = load_agent_module()

    def test_reference_tools_schema_runtime_and_visual_qa_are_packaged(self) -> None:
        names = {tool["name"] for tool in self.agent.TOOLS}
        self.assertIn("aicad_get_reference_rebuild_schema", names)
        self.assertIn("aicad_validate_reference_rebuild", names)
        self.assertIn("aicad_build_reference_reconstruction", names)
        self.assertTrue((SOURCE_ROOT / "schema" / "aicad-reference-rebuild.schema.json").is_file())
        self.assertTrue((SOURCE_ROOT / "src" / "aicad" / "reference_rebuild.py").is_file())
        visual = PLUGIN / "scripts" / "aicad_reference_visual_qa.cjs"
        self.assertTrue(visual.is_file())
        text = visual.read_text(encoding="utf-8")
        self.assertIn("viewBoxAspectPreserved", text)
        self.assertIn("noAnnotationGeometryOverlap", text)

    def test_packaged_runtime_validates_and_builds_reference_artifacts(self) -> None:
        validation = validate_reference_rebuild(self.plan, self.reference)
        self.assertEqual(validation["status"], "pass")
        self.assertTrue(validation["checks"]["reference_dom_catalog_verified"])
        self.assertTrue(validation["checks"]["annotation_layout_policy_valid"])
        self.assertEqual(validation["text_encoding_issues"], [])
        with tempfile.TemporaryDirectory() as directory:
            result = build_reference_reconstruction(self.plan, self.reference, Path(directory), "release-reference")
            self.assertTrue(result["ok"])
            self.assertEqual(result["dxf_entity_counts"]["mtext"], 5)
            for artifact in result["artifacts"].values():
                self.assertTrue(Path(artifact).is_file(), artifact)
            svg = Path(result["artifacts"]["preview_svg"]).read_text(encoding="utf-8")
            self.assertIn('transform="rotate(-90', svg)
            self.assertIn('preserveAspectRatio="xMidYMid meet"', svg)


if __name__ == "__main__":
    unittest.main()
