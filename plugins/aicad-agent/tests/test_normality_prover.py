from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_normality_prover.py"
SPEC = importlib.util.spec_from_file_location("aicad_normality_prover", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
}


def _line(entity_id: str, start: tuple[float, float], end: tuple[float, float]) -> dict:
    return {
        "id": entity_id,
        "type": "line",
        "purpose": f"{entity_id} bounded feature edge",
        "reasoning": "The endpoint formula and named-face contract determine this edge.",
        "start": {"point": list(start)},
        "construction": {"kind": "to_point", "target": {"point": list(end)}},
        "constraints": [
            {"kind": "start_offset", "target": "origin", "dx": start[0], "dy": start[1]},
            {
                "kind": "length",
                "value": ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5,
            },
        ],
    }


def _payload(
    *,
    waist: bool = False,
    mirrored_closures: bool = False,
    width: float = 10.0,
    height: float = 5.0,
) -> tuple[dict, dict, dict, dict]:
    tip_y = height / 2 if waist else height + height / 2
    points = [(0.0, 0.0), (width, 0.0), (width, height), (width / 2, tip_y), (0.0, height)]
    steps = [_line("ORIGIN_BOOTSTRAP", (0.0, 0.0), (1.0, 0.0))]
    production_ids = [f"E{index}" for index in range(5)]
    for index, entity_id in enumerate(production_ids):
        steps.append(_line(entity_id, points[index], points[(index + 1) % len(points)]))
    plan = {
        "schema_version": "2.0",
        "drawing": {"name": "normality_red_green_fixture", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
        "steps": steps,
    }
    geometry = {
        "schema": "aicad.normality-regression-geometry.v1",
        "design": dict(LOCKS),
        "entities": [
            {
                "id": entity_id,
                "type": "LINE",
                "layer": "CUT",
                "start": list(points[index]),
                "end": list(points[(index + 1) % len(points)]),
                "purpose": f"{entity_id} bounded feature edge",
                "reasoning": "The endpoint formula and named-face contract determine this edge.",
                "dependencies": ["ORIGIN_BOOTSTRAP"],
            }
            for index, entity_id in enumerate(production_ids)
        ],
    }
    y_formula = "H-T" if waist else "H+T"
    vertices = []
    formulas = [("0", "0"), ("W", "0"), ("W", "H"), ("W/2", y_formula), ("0", "H")]
    for index, (x_formula, y_value) in enumerate(formulas):
        vertices.append(
            {
                "id": f"V{index}",
                "purpose": f"polygon vertex {index}",
                "x": x_formula,
                "y": y_value,
                "refs": [f"E{index}.start", f"E{(index - 1) % 5}.end"],
            }
        )
    template = {
        "schema": "aicad_normality_template_v1",
        "profileId": "NORMALITY_RED_GREEN_FIXTURE",
        "profileVersion": "1.0.0",
        "productType": "folding_carton",
        "majorFeatures": ["top_tuck", "automatic_bottom"],
        "structureName": "convex top-tuck and asymmetric auto-bottom regression fixture",
        "closureSystem": {
            "top": "tuck_in",
            "bottom": "tuck_in" if mirrored_closures else "automatic_crash_lock",
            "asymmetric": True,
            "standard": "ECMA A60.20.00.03 regression abstraction",
        },
        "toleranceMm": 1e-6,
        "parameters": [
            {
                "id": "W",
                "role": "independent",
                "unit": "mm",
                "default": 10,
                "min": 1,
                "max": 20,
                "purpose": "fixture width",
            },
            {
                "id": "H",
                "role": "independent",
                "unit": "mm",
                "default": 5,
                "min": 1,
                "max": 10,
                "purpose": "fixture height",
            },
            {
                "id": "T",
                "role": "derived",
                "unit": "mm",
                "formula": "H/2",
                "purpose": "tip rise",
            },
        ],
        "excludedEntityIds": ["ORIGIN_BOOTSTRAP"],
        "productionEntityIds": production_ids,
        "expectedLayerCounts": {"CUT": 5},
        "vertices": vertices,
        "outerContour": production_ids,
        "features": [
            {
                "id": "MAIN_FUNCTION_FACE",
                "kind": "face",
                "purpose": "whole-face gate catches an inward waist even when every coordinate is fully constrained",
                "countsAsFace": True,
                "entityIds": production_ids,
                "polygonVertexIds": [f"V{index}" for index in range(5)],
                "rules": {"simple": True, "convex": True, "minAreaMm2": 1},
            }
        ],
        "measurements": [
            {"id": "WIDTH_MEASURED", "kind": "abs_dx", "a": "V0", "b": "V1"},
        ],
        "domainAssertions": [
            {
                "id": "WIDTH_GREATER_THAN_HEIGHT",
                "purpose": "coupled dimensions preserve the intended structure family",
                "lhs": "W",
                "operator": ">",
                "rhs": "H",
            }
        ],
        "assertions": [
            {
                "id": "WIDTH_EQUALS_PARAMETER",
                "purpose": "measured width follows the declared parameter",
                "lhs": "WIDTH_MEASURED",
                "operator": "==",
                "rhs": "W",
            }
        ],
        "expectedBBox": {"minX": "0", "minY": "0", "maxX": "W", "maxY": "H" if waist else "H+T"},
        "sampling": {"randomSeed": 23, "randomCases": 8, "explicitCases": []},
        "locks": dict(LOCKS),
    }
    instance = {
        "schema": "aicad_normality_instance_v1",
        "profileId": template["profileId"],
        "profileVersion": template["profileVersion"],
        "values": {"W": width, "H": height},
        "locks": dict(LOCKS),
    }
    return plan, geometry, template, instance


def _evaluate(payload: tuple[dict, dict, dict, dict]) -> dict:
    plan, geometry, template, instance = payload
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "fixture.plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        compiled = MODULE.load_and_compile(path)
    return MODULE.evaluate(compiled, geometry, template, instance)


class NormalityProverTests(unittest.TestCase):
    def test_accepts_fully_determined_convex_asymmetric_structure(self):
        report = _evaluate(_payload())
        self.assertEqual(report["status"], "pass", report["failures"])
        self.assertEqual(report["mathematicalProof"]["instanceNullity"], 0)
        self.assertEqual(report["closureSystem"]["top"], "tuck_in")
        self.assertEqual(report["closureSystem"]["bottom"], "automatic_crash_lock")

    def test_rejects_inward_waist_even_when_constraint_rank_is_complete(self):
        report = _evaluate(_payload(waist=True))
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["checks"]["constraintRankComplete"])
        self.assertFalse(report["checks"]["allFeatureContractsPass"])
        failed = {item["gate"] for item in report["failures"]}
        self.assertIn("feature", failed)
        self.assertIn("PKG-G023", {item["persistentRuleId"] for item in report["failures"]})

    def test_rejects_mirrored_top_and_bottom_when_contract_requires_asymmetry(self):
        report = _evaluate(_payload(mirrored_closures=True))
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["closureSystem"]["pass"])
        self.assertFalse(report["checks"]["allFunctionalAssertionsAndBBoxPass"])

    def test_rejects_missing_endpoint_ownership(self):
        plan, geometry, template, instance = _payload()
        broken = copy.deepcopy(template)
        broken["vertices"][0]["refs"].pop()
        report = _evaluate((plan, geometry, broken, instance))
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["everyEndpointExactlyOneNamedVertex"])

    def test_rejects_invalid_coupled_parameter_combination(self):
        report = _evaluate(_payload(width=4, height=5))
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["parameterDomainSweepPass"])
        self.assertFalse(report["parameterDomainSweep"]["actualInstancePass"])

    def test_schema_accepts_released_template_and_fixture_instance(self):
        schema = json.loads((ROOT / "rules" / "normality_contract.schema.json").read_text(encoding="utf-8"))
        released = json.loads((ROOT / "rules" / "top_tuck_crash_lock.normality.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(released)
        _, _, template, instance = _payload()
        jsonschema.Draft202012Validator(schema).validate(template)
        jsonschema.Draft202012Validator(schema).validate(instance)


if __name__ == "__main__":
    unittest.main()
