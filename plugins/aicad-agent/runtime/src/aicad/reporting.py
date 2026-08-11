"""Quality invariants for generated audit and validation reports."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REQUIRED_LESSON_FIELDS = ("symptom", "rootCause", "correction", "preventionRule")
_RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?:/[A-Z0-9]+)*$")


class ReportInvariantError(ValueError):
    """Raised when report records conflict or cannot be identified."""


def prevention_rule_id(value: str) -> str:
    if not isinstance(value, str):
        raise ReportInvariantError("preventionRule must be a string")
    head = value.split("：", 1)[0].split(":", 1)[0].strip()
    if not _RULE_ID_RE.fullmatch(head):
        raise ReportInvariantError(f"invalid prevention rule id: {head!r}")
    return head


def _canonical_lesson(lesson: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(lesson, Mapping):
        raise ReportInvariantError("root-cause lesson must be an object")
    canonical: dict[str, str] = {}
    for field in REQUIRED_LESSON_FIELDS:
        value = lesson.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ReportInvariantError(f"root-cause lesson field {field!r} must be non-empty text")
        canonical[field] = value.strip()
    prevention_rule_id(canonical["preventionRule"])
    return canonical


def merge_root_cause_lessons(*groups: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Merge lessons by stable rule ID.

    Byte-equivalent repeated records are collapsed so repeated generator runs are
    idempotent. A repeated ID with conflicting content is rejected instead of
    silently selecting one explanation.
    """

    merged: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    for group in groups:
        for lesson in group:
            canonical = _canonical_lesson(lesson)
            rule_id = prevention_rule_id(canonical["preventionRule"])
            previous = seen.get(rule_id)
            if previous is None:
                seen[rule_id] = canonical
                merged.append(canonical)
            elif previous != canonical:
                raise ReportInvariantError(f"conflicting root-cause lesson for {rule_id}")
    return merged


def audit_root_cause_lessons(lessons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rule_ids: list[str] = []
    invalid_records: list[dict[str, Any]] = []
    canonical_by_id: dict[str, dict[str, str]] = {}
    duplicates: list[str] = []
    conflicts: list[str] = []

    for index, lesson in enumerate(lessons):
        try:
            canonical = _canonical_lesson(lesson)
            rule_id = prevention_rule_id(canonical["preventionRule"])
        except ReportInvariantError as exc:
            invalid_records.append({"index": index, "error": str(exc)})
            continue
        rule_ids.append(rule_id)
        previous = canonical_by_id.get(rule_id)
        if previous is None:
            canonical_by_id[rule_id] = canonical
        else:
            duplicates.append(rule_id)
            if previous != canonical:
                conflicts.append(rule_id)

    unique = len(rule_ids) == len(set(rule_ids))
    complete = not invalid_records
    return {
        "status": "pass" if complete and unique and not conflicts and bool(rule_ids) else "failed",
        "checks": {
            "lessonsPresent": bool(rule_ids),
            "recordsComplete": complete,
            "ruleIdsUnique": unique,
            "duplicateIdsNonconflicting": not conflicts,
        },
        "ruleIds": rule_ids,
        "totalCount": len(rule_ids),
        "uniqueCount": len(set(rule_ids)),
        "duplicates": sorted(set(duplicates)),
        "conflicts": sorted(set(conflicts)),
        "invalidRecords": invalid_records,
    }
