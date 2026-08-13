"""Controlled failure-to-lesson harvesting for aicad-agent.

This module builds on :mod:`aicad.reporting` and intentionally stops at a
review-only candidate bundle.  It never edits authoritative rules, tests, an
installed plugin, or version metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .reporting import ReportInvariantError, prevention_rule_id


EXPECTED_CANDIDATE_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
}
LEARNING_DOMAINS = {
    "general",
    "software",
    "release",
    "cad",
    "architecture",
    "packaging",
    "mechanical",
    "electronics",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_ALIAS_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_]+)+$")
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)

_FILE_ENTRY_FIELDS = frozenset({"path", "size", "sha256"})
_CLOSURE_FIELDS = frozenset({"policy", "entries"})
_CANDIDATE_RULE_FIELDS = frozenset(
    {"id", "requirement", "prevention", "regressionTest", "safetyLocks"}
)
_FAILED_CHECK_FIELDS = frozenset(
    {
        "failureId", "failureAlias", "domain", "failingCheck", "symptom",
        "rootCause", "correction", "candidateRule", "reproducer",
        "evidenceClosure", "sourceInputClosure", "affectedArtifactClosure",
    }
)
_FAILURE_REPORT_FIELDS = frozenset(
    {"schema", "reportId", "status", "failedChecks", "safetyLocks"}
)
_MAPPING_FIELDS = frozenset({"failureId", "lessonId"})
_SOURCE_REPORT_FIELDS = frozenset(
    {"reportId", "reportArtifact", "declaredFailureIds", "mappings", "exactBidirectionalClosure"}
)
_LESSON_FIELDS = frozenset(
    {
        "lessonId", "sourceFailureId", "failureAlias", "domain", "failingCheck",
        "symptom", "rootCause", "correction", "candidateRule", "reproducer",
        "evidenceClosure", "sourceInputClosure", "affectedArtifactClosure",
    }
)
_COVERAGE_FIELDS = frozenset(
    {
        "declaredFailureKeys", "mappedFailureKeys", "unreferencedLessonIds",
        "missingLessonIds", "exactBidirectionalClosure",
    }
)
_LESSON_BUNDLE_FIELDS = frozenset(
    {"schema", "sourceReports", "lessons", "failureLessonClosure", "safetyLocks"}
)
_APPROVAL_FIELDS = frozenset(
    {
        "role", "reviewerId", "decision", "candidateBundleSha256",
        "targetRuleId", "targetVersion", "approvalEvidence",
    }
)
_REGRESSION_EVIDENCE_FIELDS = frozenset(
    {"report", "redBeforeFix", "greenAfterFix", "unrelatedSuitesPass"}
)
_CHANGE_POLICY_FIELDS = frozenset(
    {
        "weakensExistingRules", "deletesTests", "removesAuthoritativeRules",
        "modifiesInstalledPlugin", "automaticPromotion",
    }
)
_APPROVAL_LEDGER_FIELDS = frozenset(
    {
        "schema", "candidateBundle", "sourceVersion", "targetVersion", "targetRuleId",
        "approvalRecords", "regressionEvidence", "changePolicy", "safetyLocks",
    }
)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportInvariantError(f"{label} must be non-empty text")
    return value.strip()


def _exact_object(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    """Require the complete JSON-object key contract without ignoring unknown data."""

    if not isinstance(value, Mapping):
        raise ReportInvariantError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(repr(key) for key in actual - fields)
        raise ReportInvariantError(
            f"{label} fields are not exact; missing={missing}, extra={extra}"
        )
    return value


def canonical_failure_alias(value: object, domain: object) -> str:
    """Return a stable lowercase alias that is qualified by its exact domain."""

    domain_text = _required_text(domain, "domain")
    if domain_text != domain or domain_text not in LEARNING_DOMAINS:
        raise ReportInvariantError(f"unsupported or non-canonical learning domain: {domain!r}")
    alias = _required_text(value, "failureAlias")
    if alias != value or not _FAILURE_ALIAS_RE.fullmatch(alias):
        raise ReportInvariantError(f"failureAlias is not stable lowercase dotted text: {value!r}")
    if not alias.startswith(domain_text + "."):
        raise ReportInvariantError(
            f"failureAlias must start with its domain {domain_text!r}: {alias!r}"
        )
    return alias


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def safe_relative_path(value: object) -> str:
    """Return a portable canonical path or fail closed."""

    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise ReportInvariantError(f"unsafe relative path: {value!r}")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ReportInvariantError(f"unsafe relative path: {value!r}")
    normalized = candidate.as_posix()
    if normalized != value:
        raise ReportInvariantError(f"path is not canonical POSIX relative form: {value!r}")
    return normalized


def controlled_learning_output_path(value: object) -> str:
    """Allow writes only to explicit JSON candidates below ``learning/``."""

    relative = safe_relative_path(value)
    parts = PurePosixPath(relative).parts
    if len(parts) < 2 or parts[0] != "learning" or not relative.endswith(".json"):
        raise ReportInvariantError(
            "controlled-learning output must be a JSON file below learning/"
        )
    return relative


def resolve_output_path(root: Path, relative: str) -> Path:
    """Resolve a future output below root without following a link/junction."""

    relative = safe_relative_path(relative)
    root = root.resolve(strict=True)
    cursor = root
    parts = PurePosixPath(relative).parts
    for part in parts[:-1]:
        cursor = cursor / part
        if cursor.exists() and (
            cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction())
        ):
            raise ReportInvariantError(f"output path crosses a link: {relative}")
    destination = root / relative
    if destination.exists() and (
        destination.is_symlink()
        or (hasattr(destination, "is_junction") and destination.is_junction())
        or not destination.is_file()
    ):
        raise ReportInvariantError(f"unsafe output destination: {relative}")
    return destination


def _path_has_link(root: Path, relative: str) -> bool:
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            return True
    return False


def canonical_file_entry(root: Path, entry: object, label: str = "artifact") -> dict[str, Any]:
    """Verify one safe-relative file by byte size and lowercase SHA-256."""

    entry = _exact_object(entry, _FILE_ENTRY_FIELDS, label)
    relative = safe_relative_path(entry.get("path"))
    root = root.resolve(strict=True)
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ReportInvariantError(f"{label} is missing: {relative}") from exc
    if not path.is_file() or _path_has_link(root, relative) or root not in resolved.parents:
        raise ReportInvariantError(f"{label} escapes root or crosses a link: {relative}")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size != path.stat().st_size:
        raise ReportInvariantError(f"{label} size mismatch: {relative}")
    sha256 = entry.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise ReportInvariantError(f"{label} sha256 must be lowercase hex: {relative}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha256:
        raise ReportInvariantError(f"{label} sha256 mismatch: {relative}")
    return {"path": relative, "size": size, "sha256": sha256}


def file_entry(root: Path, relative: str) -> dict[str, Any]:
    """Create a verified entry for an existing regular file under root."""

    relative = safe_relative_path(relative)
    root = root.resolve(strict=True)
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ReportInvariantError(f"artifact is missing: {relative}") from exc
    if not path.is_file() or _path_has_link(root, relative) or root not in resolved.parents:
        raise ReportInvariantError(f"artifact escapes root or crosses a link: {relative}")
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _canonical_closure(root: Path, value: object, *, policy: str, label: str) -> dict[str, Any]:
    value = _exact_object(value, _CLOSURE_FIELDS, label)
    if value.get("policy") != policy:
        raise ReportInvariantError(f"{label} policy must be {policy!r}")
    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ReportInvariantError(f"{label} entries must be a non-empty list")
    canonical = [canonical_file_entry(root, row, f"{label}[{index}]") for index, row in enumerate(entries)]
    identities = [row["path"].casefold() for row in canonical]
    if len(identities) != len(set(identities)):
        raise ReportInvariantError(f"{label} contains duplicate case-insensitive paths")
    return {"policy": policy, "entries": sorted(canonical, key=lambda row: row["path"].casefold())}


def _canonical_candidate_rule(value: object) -> dict[str, Any]:
    value = _exact_object(value, _CANDIDATE_RULE_FIELDS, "candidateRule")
    rule_id = _required_text(value.get("id"), "candidateRule.id")
    prevention_rule_id(rule_id + ": candidate")
    if value.get("safetyLocks") != EXPECTED_CANDIDATE_LOCKS:
        raise ReportInvariantError("candidateRule safety locks are not exact")
    return {
        "id": rule_id,
        "requirement": _required_text(value.get("requirement"), "candidateRule.requirement"),
        "prevention": _required_text(value.get("prevention"), "candidateRule.prevention"),
        "regressionTest": _required_text(value.get("regressionTest"), "candidateRule.regressionTest"),
        "safetyLocks": dict(EXPECTED_CANDIDATE_LOCKS),
    }


def _canonical_failure(root: Path, value: object) -> dict[str, Any]:
    value = _exact_object(value, _FAILED_CHECK_FIELDS, "failedChecks entry")
    failure_id = _required_text(value.get("failureId"), "failureId")
    if not re.fullmatch(r"FAIL-[A-Z0-9][A-Z0-9._-]*", failure_id):
        raise ReportInvariantError(f"invalid failureId: {failure_id!r}")
    domain = _required_text(value.get("domain"), "domain")
    if domain != value.get("domain") or domain not in LEARNING_DOMAINS:
        raise ReportInvariantError(f"unsupported or non-canonical learning domain: {value.get('domain')!r}")
    failure_alias = canonical_failure_alias(value.get("failureAlias"), domain)
    return {
        "failureId": failure_id,
        "failureAlias": failure_alias,
        "domain": domain,
        "failingCheck": _required_text(value.get("failingCheck"), "failingCheck"),
        "symptom": _required_text(value.get("symptom"), "symptom"),
        "rootCause": _required_text(value.get("rootCause"), "rootCause"),
        "correction": _required_text(value.get("correction"), "correction"),
        "candidateRule": _canonical_candidate_rule(value.get("candidateRule")),
        "reproducer": canonical_file_entry(root, value.get("reproducer"), f"{failure_id}.reproducer"),
        "evidenceClosure": _canonical_closure(
            root, value.get("evidenceClosure"), policy="exact_declared_evidence", label=f"{failure_id}.evidenceClosure"
        ),
        "sourceInputClosure": _canonical_closure(
            root, value.get("sourceInputClosure"), policy="exact_declared_inputs", label=f"{failure_id}.sourceInputClosure"
        ),
        "affectedArtifactClosure": _canonical_closure(
            root, value.get("affectedArtifactClosure"), policy="exact_declared_artifacts", label=f"{failure_id}.affectedArtifactClosure"
        ),
    }


def canonical_failure_report(root: Path, payload: object) -> dict[str, Any]:
    """Validate one fail-only report and all declared file closures."""

    payload = _exact_object(payload, _FAILURE_REPORT_FIELDS, "failure report")
    if payload.get("schema") != "aicad_test_failure_report_v1":
        raise ReportInvariantError("failure report schema must be aicad_test_failure_report_v1")
    if payload.get("status") != "failed":
        raise ReportInvariantError("only a failed test/gate report can be harvested")
    if payload.get("safetyLocks") != EXPECTED_CANDIDATE_LOCKS:
        raise ReportInvariantError("failure report safety locks are not exact")
    report_id = _required_text(payload.get("reportId"), "reportId")
    if not re.fullmatch(r"REPORT-[A-Z0-9][A-Z0-9._-]*", report_id):
        raise ReportInvariantError(f"invalid reportId: {report_id!r}")
    rows = payload.get("failedChecks")
    if not isinstance(rows, list) or not rows:
        raise ReportInvariantError("failedChecks must be a non-empty list")
    failures = [_canonical_failure(root, row) for row in rows]
    ids = [row["failureId"] for row in failures]
    if len(ids) != len(set(ids)):
        raise ReportInvariantError("failedChecks contains duplicate failureId values")
    return {
        "schema": "aicad_test_failure_report_v1",
        "reportId": report_id,
        "status": "failed",
        "failedChecks": sorted(failures, key=lambda row: row["failureId"]),
        "safetyLocks": dict(EXPECTED_CANDIDATE_LOCKS),
    }


def stable_lesson_id(failure: Mapping[str, Any]) -> str:
    """Derive a stable event ID from failure identity rather than run time."""

    identity = {
        "failureId": failure["failureId"],
        "failureAlias": failure["failureAlias"],
        "domain": failure["domain"],
        "failingCheck": failure["failingCheck"],
        "candidateRuleId": failure["candidateRule"]["id"],
        "reproducer": failure["reproducer"],
    }
    return "LESSON-" + _json_sha256(identity)[:24].upper()


def _lesson_from_failure(failure: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lessonId": stable_lesson_id(failure),
        "sourceFailureId": failure["failureId"],
        "failureAlias": failure["failureAlias"],
        "domain": failure["domain"],
        "failingCheck": failure["failingCheck"],
        "symptom": failure["symptom"],
        "rootCause": failure["rootCause"],
        "correction": failure["correction"],
        "candidateRule": failure["candidateRule"],
        "reproducer": failure["reproducer"],
        "evidenceClosure": failure["evidenceClosure"],
        "sourceInputClosure": failure["sourceInputClosure"],
        "affectedArtifactClosure": failure["affectedArtifactClosure"],
    }


def merge_lesson_events(*groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate byte-equivalent events and reject a conflicting same ID."""

    seen: dict[str, dict[str, Any]] = {}
    for group in groups:
        for raw in group:
            if not isinstance(raw, Mapping):
                raise ReportInvariantError("lesson event must be an object")
            lesson = dict(raw)
            lesson_id = _required_text(lesson.get("lessonId"), "lessonId")
            previous = seen.get(lesson_id)
            if previous is None:
                seen[lesson_id] = lesson
            elif _canonical_json(previous) != _canonical_json(lesson):
                raise ReportInvariantError(f"conflicting lesson event for {lesson_id}")
    return [seen[key] for key in sorted(seen)]


def _coverage(source_reports: list[dict[str, Any]], lessons: list[dict[str, Any]]) -> dict[str, Any]:
    declared = sorted(
        f"{report['reportId']}/{failure_id}"
        for report in source_reports
        for failure_id in report["declaredFailureIds"]
    )
    mapped = sorted(
        f"{report['reportId']}/{mapping['failureId']}"
        for report in source_reports
        for mapping in report["mappings"]
    )
    referenced = {mapping["lessonId"] for report in source_reports for mapping in report["mappings"]}
    lesson_ids = {lesson["lessonId"] for lesson in lessons}
    return {
        "declaredFailureKeys": declared,
        "mappedFailureKeys": mapped,
        "unreferencedLessonIds": sorted(lesson_ids - referenced),
        "missingLessonIds": sorted(referenced - lesson_ids),
        "exactBidirectionalClosure": declared == mapped and lesson_ids == referenced,
    }


def harvest_lesson_bundle(
    root: Path,
    report_relative: str,
    *,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Harvest a hash-bound report into a deterministic review-only bundle."""

    root = root.resolve(strict=True)
    report_artifact = file_entry(root, report_relative)
    report_payload = json.loads((root / report_artifact["path"]).read_text(encoding="utf-8-sig"))
    report = canonical_failure_report(root, report_payload)
    lessons = [_lesson_from_failure(row) for row in report["failedChecks"]]
    report_record = {
        "reportId": report["reportId"],
        "reportArtifact": report_artifact,
        "declaredFailureIds": [row["failureId"] for row in report["failedChecks"]],
        "mappings": [
            {"failureId": row["failureId"], "lessonId": stable_lesson_id(row)}
            for row in report["failedChecks"]
        ],
        "exactBidirectionalClosure": True,
    }
    source_reports: list[dict[str, Any]] = []
    existing_lessons: list[dict[str, Any]] = []
    if existing is not None:
        audit_lesson_bundle(root, existing)
        source_reports.extend(dict(row) for row in existing["sourceReports"])
        existing_lessons.extend(dict(row) for row in existing["lessons"])
    reports_by_id = {row["reportId"]: row for row in source_reports}
    previous = reports_by_id.get(report_record["reportId"])
    if previous is not None and _canonical_json(previous) != _canonical_json(report_record):
        raise ReportInvariantError(f"conflicting source report for {report_record['reportId']}")
    reports_by_id[report_record["reportId"]] = report_record
    merged_lessons = merge_lesson_events(existing_lessons, lessons)
    merged_reports = [reports_by_id[key] for key in sorted(reports_by_id)]
    coverage = _coverage(merged_reports, merged_lessons)
    if not coverage["exactBidirectionalClosure"]:
        raise ReportInvariantError("harvested failure-to-lesson closure is not exact")
    return {
        "schema": "aicad_lesson_bundle_v1",
        "sourceReports": merged_reports,
        "lessons": merged_lessons,
        "failureLessonClosure": coverage,
        "safetyLocks": dict(EXPECTED_CANDIDATE_LOCKS),
    }


def _canonical_lesson(root: Path, value: object, label: str) -> dict[str, Any]:
    value = _exact_object(value, _LESSON_FIELDS, label)
    lesson_id = _required_text(value.get("lessonId"), f"{label}.lessonId")
    if lesson_id != value.get("lessonId") or not re.fullmatch(r"LESSON-[0-9A-F]{24}", lesson_id):
        raise ReportInvariantError(f"invalid lessonId: {value.get('lessonId')!r}")
    failure_id = _required_text(value.get("sourceFailureId"), f"{label}.sourceFailureId")
    if failure_id != value.get("sourceFailureId") or not re.fullmatch(r"FAIL-[A-Z0-9][A-Z0-9._-]*", failure_id):
        raise ReportInvariantError(f"invalid sourceFailureId: {value.get('sourceFailureId')!r}")
    domain = _required_text(value.get("domain"), f"{label}.domain")
    failure_alias = canonical_failure_alias(value.get("failureAlias"), domain)
    return {
        "lessonId": lesson_id,
        "sourceFailureId": failure_id,
        "failureAlias": failure_alias,
        "domain": domain,
        "failingCheck": _required_text(value.get("failingCheck"), f"{label}.failingCheck"),
        "symptom": _required_text(value.get("symptom"), f"{label}.symptom"),
        "rootCause": _required_text(value.get("rootCause"), f"{label}.rootCause"),
        "correction": _required_text(value.get("correction"), f"{label}.correction"),
        "candidateRule": _canonical_candidate_rule(value.get("candidateRule")),
        "reproducer": canonical_file_entry(root, value.get("reproducer"), f"{label}.reproducer"),
        "evidenceClosure": _canonical_closure(
            root, value.get("evidenceClosure"), policy="exact_declared_evidence",
            label=f"{label}.evidenceClosure",
        ),
        "sourceInputClosure": _canonical_closure(
            root, value.get("sourceInputClosure"), policy="exact_declared_inputs",
            label=f"{label}.sourceInputClosure",
        ),
        "affectedArtifactClosure": _canonical_closure(
            root, value.get("affectedArtifactClosure"), policy="exact_declared_artifacts",
            label=f"{label}.affectedArtifactClosure",
        ),
    }


def _canonical_source_report_row(root: Path, value: object, label: str) -> dict[str, Any]:
    value = _exact_object(value, _SOURCE_REPORT_FIELDS, label)
    report_id = _required_text(value.get("reportId"), f"{label}.reportId")
    if report_id != value.get("reportId") or not re.fullmatch(r"REPORT-[A-Z0-9][A-Z0-9._-]*", report_id):
        raise ReportInvariantError(f"invalid source reportId: {value.get('reportId')!r}")
    declared = value.get("declaredFailureIds")
    if not isinstance(declared, list) or not declared:
        raise ReportInvariantError(f"{label}.declaredFailureIds must be a non-empty list")
    for failure_id in declared:
        if not isinstance(failure_id, str) or not re.fullmatch(r"FAIL-[A-Z0-9][A-Z0-9._-]*", failure_id):
            raise ReportInvariantError(f"invalid declared failureId: {failure_id!r}")
    mappings = value.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ReportInvariantError(f"{label}.mappings must be a non-empty list")
    canonical_mappings: list[dict[str, str]] = []
    for index, mapping in enumerate(mappings):
        mapping = _exact_object(mapping, _MAPPING_FIELDS, f"{label}.mappings[{index}]")
        failure_id = mapping.get("failureId")
        lesson_id = mapping.get("lessonId")
        if not isinstance(failure_id, str) or not re.fullmatch(r"FAIL-[A-Z0-9][A-Z0-9._-]*", failure_id):
            raise ReportInvariantError(f"invalid mapping failureId: {failure_id!r}")
        if not isinstance(lesson_id, str) or not re.fullmatch(r"LESSON-[0-9A-F]{24}", lesson_id):
            raise ReportInvariantError(f"invalid mapping lessonId: {lesson_id!r}")
        canonical_mappings.append({"failureId": failure_id, "lessonId": lesson_id})
    if value.get("exactBidirectionalClosure") is not True:
        raise ReportInvariantError(f"{label}.exactBidirectionalClosure must be true")
    return {
        "reportId": report_id,
        "reportArtifact": canonical_file_entry(root, value.get("reportArtifact"), f"{label}.reportArtifact"),
        "declaredFailureIds": list(declared),
        "mappings": canonical_mappings,
        "exactBidirectionalClosure": True,
    }


def _canonical_coverage(value: object) -> dict[str, Any]:
    value = _exact_object(value, _COVERAGE_FIELDS, "failureLessonClosure")
    canonical: dict[str, Any] = {}
    for field in (
        "declaredFailureKeys", "mappedFailureKeys", "unreferencedLessonIds", "missingLessonIds"
    ):
        rows = value.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
            raise ReportInvariantError(f"failureLessonClosure.{field} must be a string list")
        canonical[field] = list(rows)
    if canonical["unreferencedLessonIds"] or canonical["missingLessonIds"]:
        raise ReportInvariantError("failureLessonClosure missing/extra lesson lists must be empty")
    if value.get("exactBidirectionalClosure") is not True:
        raise ReportInvariantError("failureLessonClosure.exactBidirectionalClosure must be true")
    canonical["exactBidirectionalClosure"] = True
    return canonical


def audit_lesson_bundle(root: Path, payload: object) -> dict[str, Any]:
    """Recompute every source report, event, hash, path, and closure relation."""

    payload = _exact_object(payload, _LESSON_BUNDLE_FIELDS, "lesson bundle")
    if payload.get("schema") != "aicad_lesson_bundle_v1":
        raise ReportInvariantError("lesson bundle schema must be aicad_lesson_bundle_v1")
    if payload.get("safetyLocks") != EXPECTED_CANDIDATE_LOCKS:
        raise ReportInvariantError("lesson bundle safety locks are not exact")
    reports = payload.get("sourceReports")
    lessons = payload.get("lessons")
    if not isinstance(reports, list) or not reports or not isinstance(lessons, list) or not lessons:
        raise ReportInvariantError("lesson bundle requires non-empty sourceReports and lessons")
    lesson_by_id: dict[str, dict[str, Any]] = {}
    canonical_lessons: list[dict[str, Any]] = []
    for index, lesson in enumerate(lessons):
        canonical_lesson = _canonical_lesson(root, lesson, f"lessons[{index}]")
        lesson_id = canonical_lesson["lessonId"]
        if lesson_id in lesson_by_id:
            raise ReportInvariantError(f"duplicate lessonId: {lesson_id}")
        lesson_by_id[lesson_id] = canonical_lesson
        canonical_lessons.append(canonical_lesson)
    seen_report_ids: set[str] = set()
    canonical_reports: list[dict[str, Any]] = []
    expected_lessons: list[dict[str, Any]] = []
    for index, report_row in enumerate(reports):
        provided_row = _canonical_source_report_row(root, report_row, f"sourceReports[{index}]")
        report_id = provided_row["reportId"]
        if report_id in seen_report_ids:
            raise ReportInvariantError(f"duplicate source report: {report_id}")
        seen_report_ids.add(report_id)
        artifact = provided_row["reportArtifact"]
        source_payload = json.loads((root.resolve(strict=True) / artifact["path"]).read_text(encoding="utf-8-sig"))
        source_report = canonical_failure_report(root, source_payload)
        if source_report["reportId"] != report_id:
            raise ReportInvariantError(f"source report ID mismatch: {report_id}")
        expected_lessons.extend(_lesson_from_failure(row) for row in source_report["failedChecks"])
        declared = [row["failureId"] for row in source_report["failedChecks"]]
        mappings = [
            {"failureId": row["failureId"], "lessonId": stable_lesson_id(row)}
            for row in source_report["failedChecks"]
        ]
        canonical_row = {
            "reportId": report_id,
            "reportArtifact": artifact,
            "declaredFailureIds": declared,
            "mappings": mappings,
            "exactBidirectionalClosure": True,
        }
        if _canonical_json(canonical_row) != _canonical_json(provided_row):
            raise ReportInvariantError(f"source report closure mismatch: {report_id}")
        canonical_reports.append(canonical_row)
    expected_merged = merge_lesson_events(expected_lessons)
    actual_merged = merge_lesson_events(canonical_lessons)
    if _canonical_json(expected_merged) != _canonical_json(actual_merged):
        raise ReportInvariantError("report failures and lesson events are not an exact bidirectional closure")
    coverage = _coverage(canonical_reports, actual_merged)
    provided_coverage = _canonical_coverage(payload.get("failureLessonClosure"))
    if not coverage["exactBidirectionalClosure"] or _canonical_json(coverage) != _canonical_json(provided_coverage):
        raise ReportInvariantError("failureLessonClosure is incomplete or stale")
    return {
        "schema": "aicad_lesson_bundle_audit_v1",
        "status": "pass",
        "checks": {
            "sourceReportHashesVerified": True,
            "allPersistedPathsSafeRelative": True,
            "sourceInputClosuresVerified": True,
            "failureLessonExactBidirectionalClosure": True,
            "lessonIdsDeterministicAndUnique": True,
            "candidateSafetyLocksExact": True,
            "runtimeSchemaFieldsExact": True,
            "failureAliasesStableAndDomainQualified": True,
        },
        "reportCount": len(canonical_reports),
        "failureCount": sum(len(row["declaredFailureIds"]) for row in canonical_reports),
        "lessonCount": len(actual_merged),
        "failureLessonClosure": coverage,
        "candidateOnly": True,
        "externalAuthenticatedReviewVerified": False,
        "promotionEligibleForManualApplication": False,
        "technicalPackageReady": False,
        "productionReleaseEligible": False,
        "manufacturingAuthorized": False,
        "fabricationAuthorized": False,
    }


def _semver_key(value: object) -> tuple[int, int, int, int, str]:
    text = _required_text(value, "version")
    match = _SEMVER_RE.fullmatch(text)
    if not match:
        raise ReportInvariantError(f"invalid semantic version: {text!r}")
    prerelease = match.group("pre")
    return (
        int(match.group("major")), int(match.group("minor")), int(match.group("patch")),
        1 if prerelease is None else 0, prerelease or "",
    )


def audit_promotion_ledger(root: Path, payload: object, *, current_version: str) -> dict[str, Any]:
    """Verify recorded manual-promotion prerequisites without promoting anything."""

    payload = _exact_object(payload, _APPROVAL_LEDGER_FIELDS, "approval ledger")
    if payload.get("schema") != "aicad_learning_approval_ledger_v1":
        raise ReportInvariantError("approval ledger schema must be aicad_learning_approval_ledger_v1")
    if payload.get("safetyLocks") != EXPECTED_CANDIDATE_LOCKS:
        raise ReportInvariantError("approval ledger safety locks are not exact")
    bundle_entry = canonical_file_entry(root, payload.get("candidateBundle"), "candidateBundle")
    bundle_payload = json.loads((root.resolve(strict=True) / bundle_entry["path"]).read_text(encoding="utf-8-sig"))
    bundle_audit = audit_lesson_bundle(root, bundle_payload)
    if payload.get("sourceVersion") != current_version:
        raise ReportInvariantError("approval ledger sourceVersion does not match the plugin")
    current_key = _semver_key(current_version)
    target_version = _required_text(payload.get("targetVersion"), "targetVersion")
    if _semver_key(target_version) <= current_key:
        raise ReportInvariantError("manual promotion requires a strictly newer semantic version")
    target_rule_id = _required_text(payload.get("targetRuleId"), "targetRuleId")
    prevention_rule_id(target_rule_id + ": target")
    bundle_rule_ids = {lesson["candidateRule"]["id"] for lesson in bundle_payload["lessons"]}
    if target_rule_id not in bundle_rule_ids:
        raise ReportInvariantError("targetRuleId is not present in the candidate bundle")
    approvals = payload.get("approvalRecords")
    if not isinstance(approvals, list) or len(approvals) != 2:
        raise ReportInvariantError("exactly two distinct recorded reviewer approvals are required")
    expected_roles = {"candidate_rule_reviewer", "regression_reviewer"}
    roles: set[str] = set()
    reviewers: set[str] = set()
    for index, approval in enumerate(approvals):
        approval = _exact_object(approval, _APPROVAL_FIELDS, f"approvalRecords[{index}]")
        role = _required_text(approval.get("role"), f"approvalRecords[{index}].role")
        reviewer = _required_text(approval.get("reviewerId"), f"approvalRecords[{index}].reviewerId")
        if role not in expected_roles or role in roles or reviewer in reviewers:
            raise ReportInvariantError("approval roles and recorded reviewer IDs must be distinct and unique")
        if (
            approval.get("decision") != "approved"
            or approval.get("candidateBundleSha256") != bundle_entry["sha256"]
            or approval.get("targetRuleId") != target_rule_id
            or approval.get("targetVersion") != target_version
        ):
            raise ReportInvariantError("approval is not bound to the same bundle, target rule, and target version")
        canonical_file_entry(root, approval.get("approvalEvidence"), f"approvalRecords[{index}].approvalEvidence")
        roles.add(role)
        reviewers.add(reviewer)
    if roles != expected_roles:
        raise ReportInvariantError("both candidate-rule and regression approvals are required")
    regression = _exact_object(
        payload.get("regressionEvidence"), _REGRESSION_EVIDENCE_FIELDS, "regressionEvidence"
    )
    canonical_file_entry(root, regression.get("report"), "regressionEvidence.report")
    for field in ("redBeforeFix", "greenAfterFix", "unrelatedSuitesPass"):
        if regression.get(field) is not True:
            raise ReportInvariantError(f"regressionEvidence.{field} must be true")
    expected_change_policy = {
        "weakensExistingRules": False,
        "deletesTests": False,
        "removesAuthoritativeRules": False,
        "modifiesInstalledPlugin": False,
        "automaticPromotion": False,
    }
    change_policy = _exact_object(
        payload.get("changePolicy"), _CHANGE_POLICY_FIELDS, "changePolicy"
    )
    if dict(change_policy) != expected_change_policy:
        raise ReportInvariantError("manual promotion change policy is not fail-closed")
    return {
        "schema": "aicad_learning_promotion_preflight_v1",
        "status": "pass",
        "checks": {
            "candidateBundleHashVerified": True,
            "candidateBundleAuditPassed": bundle_audit["status"] == "pass",
            "twoDistinctRecordedReviewerIdsBound": True,
            "redBeforeFixGreenAfterFixAndUnrelatedSuitesPassed": True,
            "strictlyNewerVersionRequired": True,
            "noRuleWeakeningOrTestDeletionDeclared": True,
        },
        "currentVersion": current_version,
        "sourceVersion": current_version,
        "targetVersion": target_version,
        "targetRuleId": target_rule_id,
        "recordedApprovalEvidenceStructurallyValid": True,
        "independentApprovalAuthenticityVerified": False,
        "externalAuthenticatedReviewVerified": False,
        "recordedPromotionPreconditionsComplete": True,
        "manualPromotionRequiresExternalAuthenticatedReview": True,
        "promotionEligibleForManualApplication": False,
        "promotionPerformed": False,
        "authoritativeRulesModified": False,
        "installedPluginModified": False,
        "technicalPackageReady": False,
        "productionReleaseEligible": False,
        "manufacturingAuthorized": False,
        "fabricationAuthorized": False,
    }
