from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" if (ROOT / "runtime" / "src").is_dir() else ROOT.parents[1]


def load_agent():
    script = ROOT / "scripts" / "aicad_agent.py"
    spec = importlib.util.spec_from_file_location("aicad_agent_packaged_handoff_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("agent plugin script is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewHandoffPackagedRulesTests(unittest.TestCase):
    def test_plugin_surface_and_runtime_close_the_reviewer_loop(self) -> None:
        agent = load_agent()
        names = {item["name"] for item in agent.TOOLS}
        self.assertIn("aicad_validate_review_handoff", names)
        self.assertIn("aicad_apply_review_handoff", names)
        self.assertIn("aicad_get_review_handoff_schema", names)
        self.assertTrue((SOURCE / "src" / "aicad" / "review_handoff.py").is_file())
        self.assertTrue((SOURCE / "schema" / "aicad-review-handoff.schema.json").is_file())
        handoff = agent.capabilities()["universal_cad"]["review_handoff"]
        self.assertTrue(handoff["source_hash_gate"])
        self.assertTrue(handoff["corrected_reviewer_regenerated"])
        self.assertFalse(handoff["notes_only_apply"])
        if SOURCE.name != "runtime":
            build = (SOURCE / "scripts" / "build-agent-plugin.ps1").read_text(encoding="utf-8")
            for name in (
                "aicad_get_review_handoff_schema",
                "aicad_validate_review_handoff",
                "aicad_apply_review_handoff",
            ):
                self.assertIn(name, build)


if __name__ == "__main__":
    unittest.main()
