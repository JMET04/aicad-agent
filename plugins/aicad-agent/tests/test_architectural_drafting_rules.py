from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import ezdxf
from ezdxf.tools.standards import setup_linetypes


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_architecture_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_architecture_qa", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


def build_fixture(path: Path, bad_route: bool = False, bad_axis: bool = False) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4
    doc.header["$LTSCALE"] = 100.0
    doc.header["$PSLTSCALE"] = 1
    setup_linetypes(doc)
    for name, (weight, linetype) in QA.EXPECTED_LAYERS.items():
        layer = doc.layers.new(name) if name not in doc.layers else doc.layers.get(name)
        layer.dxf.lineweight = weight
        layer.dxf.linetype = "Continuous" if bad_route and name == "ROUTE" else linetype
    style = doc.dimstyles.new("AICAD_ARCH")
    for name, value in {
        "dimtxt": 280.0, "dimasz": 180.0, "dimtsz": 150.0,
        "dimexo": 100.0, "dimexe": 150.0, "dimgap": 90.0,
        "dimtad": 1, "dimdec": 0, "dimzin": 8, "dimlunit": 2,
    }.items():
        setattr(style.dxf, name, value)
    doc.appids.add("AICAD")
    msp = doc.modelspace()
    y = 0.0
    for layer in ("WALL", "COLUMN", "OPENING", "ROOM", "STAIR", "FURNITURE", "CASEWORK", "SANITARY", "APPLIANCE", "ROUTE"):
        msp.add_line((0, y), (1000, y), dxfattribs={"layer": layer})
        y += 250.0
    msp.add_line((500, 1500), (500, 2500), dxfattribs={"layer": "GRID"})
    for index, center in enumerate(((500, 1300), (500, 2700)), 1):
        circle = msp.add_circle(center, 200, dxfattribs={"layer": "GRID_BUBBLE"})
        circle.set_xdata("AICAD", [(1000, f"AXIS_{index}")])
        if not bad_axis or index == 1:
            msp.add_mtext("1", dxfattribs={"layer": "GRID_TEXT", "attachment_point": 5}).set_location(center)
    msp.add_mtext("建筑平面", dxfattribs={"layer": "TEXT"})
    for index, value in enumerate(("D01", "W01", "UP 上", "标高 +0.000", "N ↑")):
        msp.add_mtext(value, dxfattribs={"layer": "TAG_TEXT"}).set_location((1500, index * 300))
    for index, purpose in enumerate(("overall", "grid", "partition", "opening")):
        override = msp.add_linear_dim(base=(0, -500 - index * 300), p1=(0, 0), p2=(1000 - index * 100, 0), dimstyle="AICAD_ARCH", dxfattribs={"layer": "DIMENSION"})
        override.render()
        override.dimension.set_xdata("AICAD", [(1000, f"DIM_PURPOSE:{purpose}")])
    doc.saveas(path)


class ArchitecturalDraftingRulesTests(unittest.TestCase):
    def test_rule_pack_records_causes_and_prevention(self) -> None:
        data = json.loads((ROOT / "rules" / "architectural_drafting_rules.json").read_text(encoding="utf-8"))
        ids = {row["id"] for row in data["rules"]}
        self.assertEqual(ids, {f"ARCH-D{i:03d}" for i in range(1, 36)})
        self.assertEqual(data["axisCoverageContract"]["remoteAppendagePolicy"], "explicit_include_or_exclude")
        self.assertEqual(data["reportQualityContract"]["conflictingDuplicatePolicy"], "fail")
        self.assertTrue(all(row["failureCause"] and row["prevention"] for row in data["rules"]))
        self.assertEqual(data["defaultLayerProfile"]["ROUTE"]["linetype"], "DASHED")
        self.assertEqual(data["defaultLayerProfile"]["GRID"]["linetype"], "CENTER2")
        self.assertEqual(data["defaultLayerProfile"]["GRID_BUBBLE"]["linetype"], "Continuous")
        self.assertIn("axis_identifier", data["annotationCompletenessProfile"]["architectural_concept_plan"]["required"])
        self.assertIn("paperspace_viewport", data["annotationCompletenessProfile"]["architectural_construction_plan"]["requiredAdditional"])
        self.assertIn("typed_furniture_linework", data["annotationCompletenessProfile"]["architectural_construction_plan"]["requiredAdditional"])
        self.assertIn("door_host_binding", data["annotationCompletenessProfile"]["architectural_construction_plan"]["requiredAdditional"])
        self.assertIn("opening_dimension_chain", data["annotationCompletenessProfile"]["architectural_construction_plan"]["requiredAdditional"])
        self.assertEqual(data["architecturalDetailContract"]["failureDisposition"], "blocker_report_only")
        self.assertFalse(data["reviewPolicy"]["accepted"])
        self.assertFalse(data["reviewPolicy"]["ruleEnabled"])

    def test_architectural_dxf_passes_all_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "good.dxf"
            build_fixture(path)
            result = QA.audit_dxf(path)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["nativeDimensionCount"], 4)
        self.assertEqual(set(result["nativeDimensionPurposes"]["counts"]), {"overall", "grid", "partition", "opening"})
        self.assertIn("DASHED", result["effectiveLinetypes"])
        self.assertIn("CENTER2", result["effectiveLinetypes"])

    def test_all_continuous_route_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.dxf"
            build_fixture(path, bad_route=True)
            result = QA.audit_dxf(path)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["layer_profile_exact"])
        self.assertFalse(result["checks"]["effective_solid_dashed_center_distinction"])

    def test_missing_axis_identifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-axis.dxf"
            build_fixture(path, bad_axis=True)
            result = QA.audit_dxf(path)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["axis_groups_complete"])
        self.assertFalse(result["checks"]["axis_identifiers_centered"])


if __name__ == "__main__":
    unittest.main()
