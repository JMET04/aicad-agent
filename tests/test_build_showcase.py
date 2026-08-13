from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import hashlib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_showcase.py"
SPEC = importlib.util.spec_from_file_location("aicad_build_showcase", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SHOWCASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHOWCASE)


class BuildShowcaseTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "verified-release"
        source.mkdir()
        files = {
            "example.review.html": '<!doctype html><meta charset="utf-8"><title>审核修改器</title>',
            "example.preview.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="white"/></svg>',
            "example.validation.json": '{"status":"pass","reviewOnly":true,"accepted":false,"ruleEnabled":false,"packagingGated":true}\n',
            "example.validation.md": "# 审核通过\n",
        }
        for name, content in files.items():
            (source / name).write_text(content, encoding="utf-8")
        entries = [
            {"path": name, "size": (source / name).stat().st_size, "sha256": SHOWCASE.sha256(source / name)}
            for name in sorted(files)
        ]
        (source / "example.manifest.json").write_text(
            json.dumps({"schema": "fixture", "status": "pass", "files": entries}) + "\n",
            encoding="utf-8",
        )
        return source.resolve()

    def test_bundle_is_deterministic_portable_closed_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            record_a = SHOWCASE.copy_public_artifacts("demo", source, first)
            record_b = SHOWCASE.copy_public_artifacts("demo", source, second)
            archive_a = first / "demo" / "demo-sanitized-review-candidate.zip"
            archive_b = second / "demo" / "demo-sanitized-review-candidate.zip"
            self.assertEqual(SHOWCASE.sha256(archive_a), SHOWCASE.sha256(archive_b))
            self.assertTrue(record_a["sourceManifestClosure"]["exactBidirectionalClosure"])
            self.assertEqual(record_a["publicScan"], record_b["publicScan"])
            self.assertEqual(
                [row["role"] for row in record_a["artifacts"]],
                ["preview", "interactive_review", "validation_machine", "validation_human", "source_manifest", "sanitized_review_candidate"],
            )
            with zipfile.ZipFile(archive_a) as bundle:
                names = bundle.namelist()
                self.assertEqual(names, sorted(names, key=lambda value: (value.casefold(), value)))
                self.assertTrue(all(info.date_time == SHOWCASE.FIXED_ZIP_TIME for info in bundle.infolist()))

            canonical = source / "review.html"
            nested = source / "nested"
            nested.mkdir()
            canonical.write_text("<title>canonical</title>", encoding="utf-8")
            (nested / "larger.review.html").write_text("<title>wrong</title>" * 100, encoding="utf-8")
            selected = SHOWCASE._root_role(source, SHOWCASE.source_files(source), "review.html") or SHOWCASE._select(
                SHOWCASE.source_files(source), ("*.review.html",), prefer_largest=True
            )
            self.assertEqual(selected, canonical)

            readme = root / "README.md"
            readme.write_text("# Public showcase\n", encoding="utf-8")
            copied_readme = SHOWCASE.copy_public_readme(readme, first)
            self.assertEqual(copied_readme.read_text(encoding="utf-8"), "# Public showcase\n")

    def test_artifact_manifest_plus_sha256sums_can_prove_full_source_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            manifest_path = source / "example.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = manifest.pop("files")
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            qa = source / "qa"
            qa.mkdir()
            (qa / "hash-closure.json").write_text('{"status":"pass"}\n', encoding="utf-8")
            (qa / "public-material-scan.json").write_text('{"status":"pass"}\n', encoding="utf-8")
            files = SHOWCASE.source_files(source)
            sums = source / "SHA256SUMS.txt"
            sums.write_text(
                "".join(
                    f"{SHOWCASE.sha256(path)}  {path.relative_to(source).as_posix()}\n"
                    for path in files
                ),
                encoding="utf-8",
            )
            record = SHOWCASE.copy_public_artifacts("demo", source, root / "public")
            self.assertEqual(record["sourceManifestClosure"]["closureAuthority"], "SHA256SUMS")
            self.assertTrue(record["sourceManifestClosure"]["sha256Sums"]["exactBidirectionalClosure"])

    def test_empty_open_or_stale_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            manifest = source / "example.manifest.json"
            manifest.write_text('{"files":[]}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "manifest files list is empty"):
                SHOWCASE.copy_public_artifacts("demo", source, root / "public")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            (source / "unlisted.txt").write_text("stale", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "manifest closure failed"):
                SHOWCASE.copy_public_artifacts("demo", source, root / "public")

    def test_public_scan_rejects_paths_secrets_forbidden_files_and_brand(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            audit = source / "audit.md"
            private_path = "C" + ":\\Users\\Example\\drawing.dwg"
            audit.write_text(f"source={private_path}\napi_key=unquoted-secret-value\n明徒\ufffd\n", encoding="utf-8")
            findings = SHOWCASE.scan_public_text(source, SHOWCASE.source_files(source))
            issues = {row["issue"] for row in findings}
            self.assertIn("private_or_secret_pattern", issues)
            self.assertIn("forbidden_brand", issues)
            self.assertIn("unicode_replacement_character", issues)
            log = source / "host.log"
            log.write_bytes("native host log".encode("utf-16"))
            log_findings = SHOWCASE.scan_public_text(source, SHOWCASE.source_files(source))
            self.assertIn({"file": "host.log", "issue": "not_strict_utf8"}, log_findings)
            absolute = source / "absolute.log"
            absolute.write_text("Current Directory: " + "R" + ":\\native-host\n", encoding="utf-8")
            absolute_findings = SHOWCASE.scan_public_text(source, SHOWCASE.source_files(source))
            self.assertIn({"file": "absolute.log", "issue": "private_or_secret_pattern"}, absolute_findings)
            (source / ".env").write_text("TOKEN=secret", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "forbidden file type"):
                SHOWCASE.source_files(source)

    def test_missing_role_duplicate_slug_and_output_inside_source_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            (source / "example.preview.svg").unlink()
            manifest = json.loads((source / "example.manifest.json").read_text(encoding="utf-8"))
            manifest["files"] = [row for row in manifest["files"] if row["path"] != "example.preview.svg"]
            (source / "example.manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "required public roles are missing"):
                SHOWCASE.copy_public_artifacts("demo", source, root / "public")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            with self.assertRaisesRegex(RuntimeError, "output cannot be inside"):
                SHOWCASE.copy_public_artifacts("demo", source, source / "public")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            validation = source / "example.validation.json"
            payload = json.loads(validation.read_text(encoding="utf-8"))
            payload["accepted"] = True
            validation.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            manifest_path = source / "example.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for row in manifest["files"]:
                if row["path"] == validation.name:
                    row["size"] = validation.stat().st_size
                    row["sha256"] = SHOWCASE.sha256(validation)
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "safety locks"):
                SHOWCASE.copy_public_artifacts("demo", source, root / "public")


if __name__ == "__main__":
    unittest.main()
