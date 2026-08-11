from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.viewmap import generate_view_package


class CrossViewReferenceIntegrityTests(unittest.TestCase):
    def test_same_reference_has_identical_canonical_edit_metadata_in_every_view(self) -> None:
        plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
        package = generate_view_package(plan, "3d", "mechanical")
        groups: dict[str, list[dict]] = {}
        for row in package["selection_map"].values():
            if "edit_scope" in row:
                groups.setdefault(row["reference_key"], []).append(row)
        compared = 0
        for key, rows in groups.items():
            if len(rows) < 2:
                continue
            expected = {
                field: rows[0][field]
                for field in (
                    "edit_paths", "edit_scope", "shared_parameter_groups",
                    "affected_instance_count", "requires_preserve_policy", "detach_supported",
                )
            }
            for row in rows[1:]:
                self.assertEqual(
                    {field: row[field] for field in expected}, expected,
                    f"cross-view exact reference metadata drifted for {key}",
                )
            compared += 1
        self.assertGreater(compared, 0)
        self.assertEqual(
            package["selection_map"]["TOP_F001_P_1"]["edit_paths"],
            package["selection_map"]["SEL3D_F001_PROFILE_EDGE_1"]["edit_paths"],
        )


if __name__ == "__main__":
    unittest.main()
