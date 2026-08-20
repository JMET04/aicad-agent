from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.cli import main  # noqa: E402


def _load_fixture():
    path = ROOT / "tests" / "test_civil_review_candidate.py"
    spec = importlib.util.spec_from_file_location("aicad_civil_cli_fixture", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXTURE = _load_fixture()


def _invoke(arguments: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def _civil_plan(root: Path) -> tuple[dict, Path]:
    plan = json.loads((ROOT / "examples" / "arc.plan.json").read_text(encoding="utf-8"))
    plan["drawing"]["domain"] = "civil"
    plan["civil_review_candidate"] = FIXTURE.valid_candidate(root)
    path = root / "civil.plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return plan, path


class CivilCliIntegrationTests(unittest.TestCase):
    def test_schema_and_candidate_commands_use_packaged_schema_and_parent_evidence(self) -> None:
        code, output, error = _invoke(["civil-review-schema"])
        self.assertEqual(code, 0, error)
        payload = json.loads(output)
        self.assertTrue(payload["ok"])
        Draft202012Validator.check_schema(payload["schema"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = FIXTURE.valid_candidate(root)
            path = root / "civil-candidate.json"
            path.write_text(json.dumps(candidate), encoding="utf-8")
            code, output, error = _invoke(["civil-review-validate", str(path)])
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertTrue(report["ok"])
        self.assertEqual(report["authorizedOutput"], "review_candidate")

    def test_source_bound_civil_plan_validates_and_compiles_as_review_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, path = _civil_plan(root)
            code, output, error = _invoke(["validate", str(path)])
            self.assertEqual(code, 0, error)
            self.assertIn("VALID:", output)

            destination = root / "compiled"
            code, output, error = _invoke(
                ["compile", str(path), "--out", str(destination), "--name", "civil"]
            )
            self.assertEqual(code, 0, error)
            self.assertIn("COMPILED:", output)
            self.assertTrue((destination / "civil.aicad").is_file())

    def test_tampered_civil_evidence_blocks_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, path = _civil_plan(root)
            source = root.joinpath(*plan["civil_review_candidate"]["sources"][0]["path"].split("/"))
            source.write_bytes(source.read_bytes() + b"tampered")
            destination = root / "must-not-exist"
            code, output, error = _invoke(
                ["compile", str(path), "--out", str(destination), "--name", "blocked"]
            )
            self.assertEqual(code, 2, output)
            self.assertIn("civil review-candidate gate failed", error)
            self.assertFalse(destination.exists())

    def test_portable_cli_refuses_non_civil_specialist_domains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = json.loads((ROOT / "examples" / "arc.plan.json").read_text(encoding="utf-8"))
            plan["drawing"]["domain"] = "mechanical"
            path = root / "mechanical.plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            destination = root / "must-not-exist"
            code, output, error = _invoke(
                ["compile", str(path), "--out", str(destination)]
            )
        self.assertEqual(code, 2, output)
        self.assertIn("refuses specialist domain", error)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
