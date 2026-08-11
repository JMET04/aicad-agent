from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SolidWorksNativeEvidenceTests(unittest.TestCase):
    def test_executed_result_persists_native_evidence_in_manifest_and_audit(self) -> None:
        source = (ROOT / "src" / "aicad" / "solidworks3d.py").read_text(encoding="utf-8")
        for token in (
            'manifest["native_host_validation"]',
            '"native_topology_authority": True',
            '"saved_reference_count": len(saved_native)',
            '"reopened_reference_count": len(reopened_native)',
            '"reference_keys": sorted(reopened_keys)',
            '"reviewOnly": True',
            '"accepted": False',
            '"ruleEnabled": False',
            '"packagingGated": True',
            "Native SolidWorks topology save/reopen verification",
            'result["file_sha256"]',
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
