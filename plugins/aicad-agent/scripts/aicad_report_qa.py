#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = PLUGIN_ROOT / "runtime" / "src"
REPOSITORY_SRC = PLUGIN_ROOT.parent.parent / "src"
for candidate in (RUNTIME_SRC, REPOSITORY_SRC):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from aicad.reporting import audit_root_cause_lessons


EXPECTED_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_report(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    lesson_audit = audit_root_cause_lessons(payload.get("rootCauseLessons", []))
    checks = {
        "root_cause_lessons_present": lesson_audit["checks"]["lessonsPresent"],
        "root_cause_records_complete": lesson_audit["checks"]["recordsComplete"],
        "prevention_rule_ids_unique": lesson_audit["checks"]["ruleIdsUnique"],
        "duplicate_rule_ids_nonconflicting": lesson_audit["checks"]["duplicateIdsNonconflicting"],
        "declared_status_is_valid": payload.get("status") in {"pass", "fail", "failed"},
        "safety_locks_exact": payload.get("safetyLocks") == EXPECTED_LOCKS,
    }
    return {
        "schema": "aicad_report_quality_validation_v1",
        "status": "pass" if all(checks.values()) else "failed",
        "source": {"path": str(path.resolve()), "sha256": _sha256(path)},
        "checks": checks,
        "rootCauseInventory": lesson_audit,
        "reviewPolicy": EXPECTED_LOCKS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit validation-report completeness, unique prevention-rule IDs and safety locks.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_report(args.report)
    output = args.output or args.report.with_suffix(".report-qa.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["status"] == "pass", "status": result["status"], "output": str(output.resolve())}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
