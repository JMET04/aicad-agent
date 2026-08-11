from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.engine import PlanError
from aicad.engine3d import compile_plan3d


class ResidualWallInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))

    def test_boss_supported_cut_requires_positive_radial_wall(self) -> None:
        value = copy.deepcopy(self.plan)
        bore = value["features"][3]
        bore["profile"]["radius"] = 15
        next(row for row in bore["constraints"] if row["kind"] == "radius")["value"] = 15
        with self.assertRaisesRegex(PlanError, "positive residual wall"):
            compile_plan3d(value)

    def test_original_annular_wall_remains_valid(self) -> None:
        compiled = compile_plan3d(self.plan)
        boss = compiled.features[2]
        bore = compiled.features[3]
        self.assertEqual(boss.profile.radius - bore.profile.radius, 10.0)


if __name__ == "__main__":
    unittest.main()
