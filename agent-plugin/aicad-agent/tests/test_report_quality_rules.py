from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_report_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_report_qa", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


def record(rule_id: str = "ARCH-G001", correction: str = "correct") -> dict[str, str]:
    return {
        "symptom": "defect",
        "rootCause": "cause",
        "correction": correction,
        "preventionRule": f"{rule_id}：gate",
    }


def write_report(path: Path, lessons: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "pass",
                "rootCauseLessons": lessons,
                "safetyLocks": {
                    "reviewOnly": True,
                    "accepted": False,
                    "ruleEnabled": False,
                    "packagingGated": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class ReportQualityQATests(unittest.TestCase):
    def test_complete_unique_report_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation.json"
            write_report(path, [record(), record("ARCH-G002")])
            result = QA.audit_report(path)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_duplicate_rule_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation.json"
            write_report(path, [record(), record()])
            result = QA.audit_report(path)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["prevention_rule_ids_unique"])

    def test_wrong_safety_locks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation.json"
            write_report(path, [record()])
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["safetyLocks"]["accepted"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = QA.audit_report(path)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["safety_locks_exact"])


if __name__ == "__main__":
    unittest.main()
