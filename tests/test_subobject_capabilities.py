from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py"


def load_agent():
    spec = importlib.util.spec_from_file_location("aicad_agent_subobject_capabilities", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("agent plugin script is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SubobjectCapabilityTests(unittest.TestCase):
    def test_capability_contract_is_explicit_and_honest(self) -> None:
        value = load_agent().capabilities()["universal_cad"]
        for operation in ("set_subobject_parameter", "move_subobject", "add_subobject_relation"):
            self.assertIn(operation, value["correction_operations"])
        exact = value["exact_subobject_correction"]
        self.assertEqual(exact["geometry_types"], ["line", "circle", "point", "face"])
        self.assertTrue(exact["pattern_scope_requires_explicit_fanout"])
        self.assertFalse(exact["detached_pattern_instance_supported"])
        self.assertTrue(exact["positive_residual_wall_gate"])
        self.assertTrue(exact["semantic_reference_authority"])
        self.assertFalse(exact["native_persistent_topology_authority"])
        self.assertTrue(exact["live_solidworks_native_topology_authority_available"])
        self.assertIn("save/reopen", exact["live_authority_gate"])
        self.assertEqual(exact["selection_measurements"]["line"], ["length_mm", "start", "end"])
        self.assertEqual(exact["selection_measurements"]["point"], ["coordinates"])
        self.assertEqual(exact["selection_measurements"]["circle"], ["center", "radius_mm", "diameter_mm"])
        self.assertEqual(exact["coordinate_system"]["id"], "MODEL_XYZ")
        self.assertEqual(exact["coordinate_system"]["handedness"], "right")


if __name__ == "__main__":
    unittest.main()
