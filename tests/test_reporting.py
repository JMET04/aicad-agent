from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.reporting import (
    ReportInvariantError,
    audit_root_cause_lessons,
    merge_root_cause_lessons,
    prevention_rule_id,
)


def lesson(rule_id: str = "ARCH-G001", correction: str = "correct once") -> dict[str, str]:
    return {
        "symptom": "observable defect",
        "rootCause": "identified generator cause",
        "correction": correction,
        "preventionRule": f"{rule_id}：executable prevention gate",
    }


class ReportingInvariantTests(unittest.TestCase):
    def test_rule_id_accepts_grouped_ids(self) -> None:
        self.assertEqual(prevention_rule_id("REVIEW-G001/G002：workflow gate"), "REVIEW-G001/G002")

    def test_identical_repeated_lessons_merge_idempotently(self) -> None:
        first = merge_root_cause_lessons([lesson()], [lesson()])
        second = merge_root_cause_lessons(first, [lesson()])
        self.assertEqual(first, second)
        self.assertEqual(len(second), 1)

    def test_conflicting_duplicate_rule_id_is_rejected(self) -> None:
        with self.assertRaises(ReportInvariantError):
            merge_root_cause_lessons([lesson()], [lesson(correction="different correction")])

    def test_audit_rejects_duplicate_or_incomplete_records(self) -> None:
        duplicate = audit_root_cause_lessons([lesson(), lesson()])
        incomplete = audit_root_cause_lessons([{"preventionRule": "ARCH-G002：gate"}])
        self.assertEqual(duplicate["status"], "failed")
        self.assertFalse(duplicate["checks"]["ruleIdsUnique"])
        self.assertEqual(incomplete["status"], "failed")
        self.assertFalse(incomplete["checks"]["recordsComplete"])


if __name__ == "__main__":
    unittest.main()
