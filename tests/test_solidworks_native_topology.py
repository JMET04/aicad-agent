from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SolidWorksNativeTopologyTests(unittest.TestCase):
    def test_host_embeds_and_reopens_exact_native_topology_catalog(self) -> None:
        source = (ROOT / "solidworks-host" / "AiCad.SolidWorksHost" / "Program.cs").read_text(encoding="utf-8")
        for token in (
            "AICAD_SOLIDWORKS_REPORT_2",
            "AICAD_SOLIDWORKS_REOPEN_REPORT_2",
            "NativeTopologyReference",
            "CaptureSketchTopology",
            "CaptureFeatureTopology",
            "GetPersistReference3",
            "GetObjectByPersistReference3",
            "PersistNativeTopologyCatalog",
            "ReadAndResolveNativeTopologyCatalog",
            '"AICAD_REF_" + ordinal.ToString("D4"',
            "name.Length != 14",
            "unresolved_required_native_topology_reference_count",
            "PASS:native_topology_required_refs",
        ):
            self.assertIn(token, source)
        self.assertIn("Do not FinalReleaseComObject here", source)

    def test_python_adapter_requires_save_reopen_key_set_equality(self) -> None:
        source = (ROOT / "src" / "aicad" / "solidworks3d.py").read_text(encoding="utf-8")
        for token in (
            "set(saved_keys) != set(reopened_keys)",
            "unresolved_required_native_topology_reference_count",
            'result["native_topology_authority"] = True',
            "solidworks_persist_reference_save_reopen_verified",
            "Required native topology reference set changed after reopen",
        ):
            self.assertIn(token, source)

    def test_host_explicitly_dimensions_negative_offset_rectangles_before_autodefine(self) -> None:
        source = (ROOT / "solidworks-host" / "AiCad.SolidWorksHost" / "Program.cs").read_text(encoding="utf-8")
        for token in (
            "AddExplicitRectangleConstraints",
            "explicit_rectangle_size_dimension_count",
            "explicit_rectangle_position_dimension_count",
            "explicit_rectangle_position_relation_count",
            "rectangle lower-left X dimension",
            "rectangle lower-left Y dimension",
            "Rectangle profile segments are not native SketchLine objects.",
        ):
            self.assertIn(token, source)
        self.assertLess(source.index("AddExplicitRectangleConstraints("), source.index("sketchManager.FullyDefineSketch("))


if __name__ == "__main__":
    unittest.main()
