from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "showcase" / "standardized-regeneration-v1.15.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StandardizedRegenerationShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((SHOWCASE / "manifest.json").read_text(encoding="utf-8"))
        cls.packages = {row["discipline"]: row for row in cls.manifest["packages"]}

    def test_manifest_is_fail_closed(self) -> None:
        self.assertEqual("v1.15.0", self.manifest["release"])
        self.assertFalse(self.manifest["productionReleaseEligible"])
        self.assertFalse(self.manifest["fabricationAuthorized"])
        self.assertFalse(self.manifest["manufacturingAuthorized"])

        mechanical = self.packages["mechanical"]
        self.assertTrue(mechanical["evidenceContractReady"])
        self.assertFalse(mechanical["technicalPackageReady"])

        electronics = self.packages["electronics"]
        self.assertEqual(0, electronics["nativeErcViolations"])
        self.assertEqual(0, electronics["nativeDrcGeometryViolations"])
        self.assertEqual(37, electronics["nativeDrcUnconnectedItems"])
        self.assertTrue(electronics["camOutputsWithheld"])
        self.assertFalse(electronics["evidenceContractReady"])
        self.assertFalse(electronics["technicalPackageReady"])

        runtimes = self.manifest["thirdPartyRuntimePolicy"]
        self.assertFalse(runtimes["freeroutingJarIncluded"])
        self.assertFalse(runtimes["javaRuntimeIncluded"])
        self.assertFalse(runtimes["kicadRuntimeIncluded"])

    def test_archives_match_exact_size_hash_count_and_deterministic_metadata(self) -> None:
        checksum_lines: list[str] = []
        for discipline, row in self.packages.items():
            with self.subTest(discipline=discipline):
                archive = SHOWCASE / row["path"]
                self.assertEqual(row["bytes"], archive.stat().st_size)
                self.assertEqual(row["sha256"], sha256(archive))
                checksum_lines.append(f"{row['sha256']}  {row['path']}")
                with zipfile.ZipFile(archive) as bundle:
                    infos = bundle.infolist()
                    self.assertEqual(row["files"], len(infos))
                    self.assertTrue(all(info.date_time == (2026, 8, 14, 0, 0, 0) for info in infos))
                    for info in infos:
                        path = PurePosixPath(info.filename)
                        self.assertFalse(path.is_absolute())
                        self.assertNotIn("..", path.parts)
                        self.assertNotIn("__pycache__", path.parts)
                        self.assertNotIn(".kicad_profile", path.parts)
                        self.assertNotIn(path.suffix.lower(), {".pyc", ".pyo", ".jar", ".exe", ".dll"})
        actual_sums = (SHOWCASE / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual(checksum_lines, actual_sums)

    def test_mechanical_and_electronics_evidence_surfaces_are_present(self) -> None:
        with zipfile.ZipFile(SHOWCASE / self.packages["mechanical"]["path"]) as bundle:
            names = set(bundle.namelist())
            self.assertIn("mechanical-production-validation-v3.json", names)
            self.assertIn("qa/solidworks-roundtrip-aggregate.json", names)
            self.assertIn("qa/autocad-roundtrip-aggregate.json", names)
            self.assertIn("documents/mechanical-bom.json", names)

        with zipfile.ZipFile(SHOWCASE / self.packages["electronics"]["path"]) as bundle:
            names = set(bundle.namelist())
            self.assertIn("evidence/stage-c-native-erc.json", names)
            self.assertIn("evidence/stage-c-native-drc.json", names)
            self.assertIn("evidence/stage-c-routing-geometry.json", names)
            self.assertIn("routing/freerouting-completion-first-config.json", names)
            forbidden_suffixes = (".gbr", ".drl", ".gbrjob")
            self.assertFalse(any(name.lower().endswith(forbidden_suffixes) for name in names))


if __name__ == "__main__":
    unittest.main()
