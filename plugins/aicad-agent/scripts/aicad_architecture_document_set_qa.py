#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "rules" / "architectural_document_set.schema.json"
TOLERANCE_MM = 1e-6
RULES_APPLIED = ["ARCH-D048", "ARCH-D049", "ARCH-D050", "ARCH-D051"]
CHECK_NAMES = (
    "contract_schema_valid",
    "requested_storey_document_bijection",
    "plan_view_source_hash_freshness",
    "independent_axis_authority_binding",
    "modifier_document_set_complete",
    "modifier_open_target_freshness",
    "safety_locks_preserved",
)
DIGEST_FIELDS = (
    "schema",
    "projectId",
    "deliveryStage",
    "requestedStoreys",
    "documents",
    "axisAuthorityBindings",
    "safetyLocks",
)
MODE_TO_STATUS = {
    "external_authority_catalog": "project_authority",
    "approved_input_catalog": "approved_input",
    "concept_assumption_catalog": "concept_assumption",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path_value: str, base_dir: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def document_set_digest(contract: dict[str, Any]) -> str:
    projection = {field: contract.get(field) for field in DIGEST_FIELDS}
    return _canonical_sha256(projection)


def _check(passed: bool, evidence: Any) -> dict[str, Any]:
    return {"pass": bool(passed), "evidence": evidence}


def _schema_errors(contract: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for error in sorted(validator.iter_errors(contract), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def _counter_is_bijection(counter: Counter[str], requested: Counter[str]) -> bool:
    return counter == requested and all(count == 1 for count in counter.values())


def _axis_map(rows: list[dict[str, Any]]) -> tuple[dict[str, float], list[str]]:
    result: dict[str, float] = {}
    errors: list[str] = []
    for row in rows:
        axis_id = str(row.get("id", ""))
        coordinate = row.get("coordinateMm")
        if not axis_id:
            errors.append("empty axis identifier")
            continue
        if axis_id in result:
            errors.append(f"duplicate axis identifier {axis_id}")
            continue
        if not isinstance(coordinate, (int, float)) or not math.isfinite(float(coordinate)):
            errors.append(f"axis {axis_id} has non-finite coordinate")
            continue
        result[axis_id] = float(coordinate)
    return result, errors


def _axis_sets_match(
    candidate_rows: list[dict[str, Any]],
    authority_rows: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    candidate, errors = _axis_map(candidate_rows)
    authority, authority_errors = _axis_map(authority_rows)
    errors.extend(authority_errors)
    if set(candidate) != set(authority):
        errors.append(
            "axis identifier set differs: "
            f"candidate={sorted(candidate)} authority={sorted(authority)}"
        )
    for axis_id in sorted(set(candidate) & set(authority)):
        delta = abs(candidate[axis_id] - authority[axis_id])
        if delta > TOLERANCE_MM:
            errors.append(
                f"axis {axis_id} coordinate differs by {delta:.9f} mm "
                f"(candidate={candidate[axis_id]:.9f}, authority={authority[axis_id]:.9f})"
            )
    for row in candidate_rows:
        supports = row.get("supportEntityIds", [])
        if not supports:
            errors.append(f"axis {row.get('id', '<unknown>')} has no structural support binding")
    return not errors, errors


def _is_equal_spaced(rows: list[dict[str, Any]]) -> bool | None:
    coordinates = sorted({float(row["coordinateMm"]) for row in rows})
    if len(coordinates) < 3:
        return None
    intervals = [coordinates[index + 1] - coordinates[index] for index in range(len(coordinates) - 1)]
    return max(intervals) - min(intervals) <= TOLERANCE_MM


def _plan_grid_signature(plan: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[str], str]:
    """Derive axes from actual GRID steps, with legacy plan.axes only for explicit test fixtures."""
    result: dict[str, list[dict[str, Any]]] = {"vertical": [], "horizontal": []}
    failures: list[str] = []
    steps = list(plan.get("steps", []))
    grids = [step for step in steps if step.get("type") == "line" and step.get("layer") == "GRID"]
    if not grids:
        legacy = plan.get("axes")
        if not isinstance(legacy, dict):
            return result, ["plan contains neither GRID steps nor an explicit axes catalogue"], "missing"
        for direction in ("vertical", "horizontal"):
            for row in legacy.get(direction, []):
                result[direction].append(
                    {
                        "coordinateMm": float(row["coordinateMm"]),
                        "supportEntityIds": [str(value) for value in row.get("supportEntityIds", [])],
                    }
                )
            result[direction].sort(key=lambda row: float(row["coordinateMm"]))
        return result, failures, "explicit_plan_axes"

    step_index = {str(step.get("id")): index for index, step in enumerate(steps) if step.get("id")}
    for step in grids:
        construction = step.get("construction", {})
        start = step.get("start", {})
        point = start.get("point") if isinstance(start, dict) else None
        if not isinstance(point, list) or len(point) < 2:
            failures.append(f"{step.get('id', '<unknown>')}: GRID start is not an explicit point")
            continue
        dx = float(construction.get("dx", 0.0))
        dy = float(construction.get("dy", 0.0))
        if abs(dx) <= TOLERANCE_MM and abs(dy) > TOLERANCE_MM:
            direction = "vertical"
            coordinate = float(point[0])
        elif abs(dy) <= TOLERANCE_MM and abs(dx) > TOLERANCE_MM:
            direction = "horizontal"
            coordinate = float(point[1])
        else:
            failures.append(f"{step.get('id', '<unknown>')}: GRID is not orthogonal")
            continue
        supports = [str(value) for value in step.get("support_entity_ids", [])]
        if not supports:
            failures.append(f"{step.get('id', '<unknown>')}: GRID has no support_entity_ids")
        grid_index = step_index.get(str(step.get("id")), -1)
        unresolved = [value for value in supports if value not in step_index or step_index[value] >= grid_index]
        if unresolved:
            failures.append(f"{step.get('id', '<unknown>')}: support IDs are missing or not earlier {unresolved}")
        result[direction].append({"coordinateMm": coordinate, "supportEntityIds": supports})
    for rows in result.values():
        rows.sort(key=lambda row: float(row["coordinateMm"]))
    return result, failures, "derived_grid_steps"


def _plan_axes_match_binding(
    plan_axes: dict[str, list[dict[str, Any]]],
    candidate_axes: dict[str, list[dict[str, Any]]],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for direction in ("vertical", "horizontal"):
        actual = plan_axes[direction]
        claimed = sorted(candidate_axes[direction], key=lambda row: float(row["coordinateMm"]))
        if len(actual) != len(claimed):
            failures.append(f"{direction}: plan GRID count differs from candidate binding")
            continue
        actual_intervals = [actual[i + 1]["coordinateMm"] - actual[i]["coordinateMm"] for i in range(len(actual) - 1)]
        claimed_intervals = [claimed[i + 1]["coordinateMm"] - claimed[i]["coordinateMm"] for i in range(len(claimed) - 1)]
        if any(abs(float(left) - float(right)) > TOLERANCE_MM for left, right in zip(actual_intervals, claimed_intervals)):
            failures.append(f"{direction}: plan GRID intervals differ from candidate binding")
        for actual_row, claimed_row in zip(actual, claimed):
            if set(actual_row["supportEntityIds"]) != set(claimed_row["supportEntityIds"]):
                failures.append(f"{direction}/{claimed_row['id']}: plan support IDs differ from candidate binding")
    return not failures, failures


class _ModifierParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.storey_ids: list[str] = []
        self.mode: str | None = None
        self.artifact_role: str | None = None
        self.selection_scope: str | None = None
        self.default_storey: str | None = None
        self.active_storey: str | None = None
        self.document_set_sha256: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value for name, value in attrs}
        storey_id = values.get("data-storey-id")
        if storey_id:
            self.storey_ids.append(storey_id)
        self.mode = values.get("data-aicad-modifier-mode") or self.mode
        self.artifact_role = values.get("data-artifact-role") or self.artifact_role
        self.selection_scope = values.get("data-selection-scope-mode") or self.selection_scope
        self.default_storey = values.get("data-default-storey-id") or self.default_storey
        self.active_storey = values.get("data-active-storey-id") or self.active_storey
        if tag.lower() == "meta" and values.get("name") == "aicad-document-set-sha256":
            self.document_set_sha256 = values.get("content")


def _blank_report(schema_errors: list[str]) -> dict[str, Any]:
    checks = {
        name: _check(False, schema_errors if name == "contract_schema_valid" else "not evaluated because schema validation failed")
        for name in CHECK_NAMES
    }
    return {
        "schema": "aicad_architectural_document_set_validation_v1",
        "status": "failed",
        "rulesApplied": RULES_APPLIED,
        "documentSetSha256": None,
        "checks": checks,
    }


def evaluate(contract: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    base_dir = (base_dir or Path.cwd()).resolve()
    schema_errors = _schema_errors(contract)
    if schema_errors:
        return _blank_report(schema_errors)

    checks: dict[str, dict[str, Any]] = {
        "contract_schema_valid": _check(True, "Draft 2020-12 schema validation passed")
    }
    requested_ids = [str(row["id"]) for row in contract["requestedStoreys"]]
    requested = Counter(requested_ids)
    document_ids = [str(row["storeyId"]) for row in contract["documents"]]
    binding_ids = [str(row["storeyId"]) for row in contract["axisAuthorityBindings"]]
    document_counter = Counter(document_ids)
    binding_counter = Counter(binding_ids)
    unique_document_ids = len({row["documentId"] for row in contract["documents"]}) == len(contract["documents"])
    unique_sheet_ids = len({row["sheetId"] for row in contract["documents"]}) == len(contract["documents"])
    bijection_pass = (
        all(count == 1 for count in requested.values())
        and _counter_is_bijection(document_counter, requested)
        and _counter_is_bijection(binding_counter, requested)
        and unique_document_ids
        and unique_sheet_ids
    )
    checks["requested_storey_document_bijection"] = _check(
        bijection_pass,
        {
            "requested": dict(requested),
            "documents": dict(document_counter),
            "axisAuthorityBindings": dict(binding_counter),
            "uniqueDocumentIds": unique_document_ids,
            "uniqueSheetIds": unique_sheet_ids,
        },
    )

    document_failures: list[str] = []
    document_evidence: list[dict[str, Any]] = []
    plan_paths: list[Path] = []
    view_paths: list[Path] = []
    plan_axes_by_storey: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for document in contract["documents"]:
        storey_id = str(document["storeyId"])
        plan_path = _resolve(document["planPath"], base_dir)
        view_path = _resolve(document["viewPackagePath"], base_dir)
        plan_paths.append(plan_path)
        view_paths.append(view_path)
        row_evidence: dict[str, Any] = {
            "storeyId": storey_id,
            "planPath": str(document["planPath"]),
            "viewPackagePath": str(document["viewPackagePath"]),
        }
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_sha = _canonical_sha256(plan)
            row_evidence["planCanonicalSha256"] = plan_sha
            if plan_sha != document["planCanonicalSha256"]:
                document_failures.append(f"{storey_id}: plan canonical SHA-256 mismatch")
            plan_document_id = str(plan.get("drawing", {}).get("id", ""))
            if plan_document_id != str(document["documentId"]):
                document_failures.append(f"{storey_id}: plan drawing.id differs from documentId")
            plan_axes, grid_failures, grid_source = _plan_grid_signature(plan)
            plan_axes_by_storey[storey_id] = plan_axes
            row_evidence["planAxisSource"] = grid_source
            document_failures.extend(f"{storey_id}: {value}" for value in grid_failures)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            document_failures.append(f"{storey_id}: plan unreadable: {error}")
            document_evidence.append(row_evidence)
            continue
        try:
            view_sha = _file_sha256(view_path)
            row_evidence["viewPackageSha256"] = view_sha
            if view_sha != document["viewPackageSha256"]:
                document_failures.append(f"{storey_id}: view-package byte SHA-256 mismatch")
            view = json.loads(view_path.read_text(encoding="utf-8"))
            source_sha = view.get("source_sha256")
            row_evidence["viewSourceSha256"] = source_sha
            if source_sha != plan_sha:
                document_failures.append(f"{storey_id}: view-package source SHA-256 is stale")
            if view.get("space") != "2d" or view.get("domain") != "architecture":
                document_failures.append(f"{storey_id}: view package is not architecture/2d")
            semantic_document_id = str(view.get("semantic_document", {}).get("document", {}).get("id", ""))
            if semantic_document_id and semantic_document_id != str(document["documentId"]):
                document_failures.append(f"{storey_id}: view semantic document ID differs from documentId")
            if not isinstance(view.get("views"), list) or not view["views"]:
                document_failures.append(f"{storey_id}: view package contains no views")
        except (OSError, json.JSONDecodeError, ValueError) as error:
            document_failures.append(f"{storey_id}: view package unreadable: {error}")
        document_evidence.append(row_evidence)
    normalized_plan_paths = [os.path.normcase(str(path)) for path in plan_paths]
    normalized_view_paths = [os.path.normcase(str(path)) for path in view_paths]
    if len(set(normalized_plan_paths)) != len(normalized_plan_paths):
        document_failures.append("document planPath values are not unique")
    if len(set(normalized_view_paths)) != len(normalized_view_paths):
        document_failures.append("document viewPackagePath values are not unique")
    checks["plan_view_source_hash_freshness"] = _check(
        not document_failures,
        {"documents": document_evidence, "failures": document_failures},
    )

    authority_failures: list[str] = []
    authority_evidence: list[dict[str, Any]] = []
    forbidden_authority_paths = plan_paths + view_paths
    modifier_path = _resolve(contract["modifier"]["htmlPath"], base_dir)
    forbidden_authority_paths.append(modifier_path)
    authority_cache: dict[Path, dict[str, Any]] = {}
    for binding in contract["axisAuthorityBindings"]:
        storey_id = str(binding["storeyId"])
        source_path = _resolve(binding["sourcePath"], base_dir)
        row_evidence: dict[str, Any] = {
            "storeyId": storey_id,
            "sourcePath": str(binding["sourcePath"]),
            "equalSpacingObserved": {},
        }
        expected_status = MODE_TO_STATUS.get(binding["mode"])
        if binding["authorityStatus"] != expected_status:
            authority_failures.append(
                f"{storey_id}: mode {binding['mode']} requires authorityStatus {expected_status}"
            )
        if contract["deliveryStage"] == "production" and binding["authorityStatus"] == "concept_assumption":
            authority_failures.append(f"{storey_id}: concept assumption cannot authorize production")
        if any(_same_path(source_path, candidate_path) for candidate_path in forbidden_authority_paths):
            authority_failures.append(f"{storey_id}: authority source is inside the candidate artefact set")
        try:
            source_sha = _file_sha256(source_path)
            row_evidence["sourceSha256"] = source_sha
            if source_sha != binding["sourceSha256"]:
                authority_failures.append(f"{storey_id}: authority source SHA-256 mismatch")
            if source_path not in authority_cache:
                authority_cache[source_path] = json.loads(source_path.read_text(encoding="utf-8"))
            catalog = authority_cache[source_path]
            if catalog.get("schema") != "aicad_axis_authority_catalog_v1":
                authority_failures.append(f"{storey_id}: unsupported authority catalogue schema")
            if catalog.get("revision") != binding["sourceRevision"]:
                authority_failures.append(f"{storey_id}: authority catalogue revision mismatch")
            if catalog.get("authorityStatus") != binding["authorityStatus"]:
                authority_failures.append(f"{storey_id}: authority catalogue status mismatch")
            storey_rows = [
                row for row in catalog.get("storeys", [])
                if str(row.get("storeyId")) == storey_id
            ]
            if len(storey_rows) != 1:
                authority_failures.append(
                    f"{storey_id}: authority catalogue must contain exactly one matching storey row"
                )
            else:
                authority_storey = storey_rows[0]
                for direction in ("vertical", "horizontal"):
                    candidate_rows = binding["candidateAxes"][direction]
                    authority_rows = authority_storey.get(direction, [])
                    matched, errors = _axis_sets_match(candidate_rows, authority_rows)
                    row_evidence["equalSpacingObserved"][direction] = _is_equal_spaced(authority_rows)
                    if not matched:
                        authority_failures.extend(
                            f"{storey_id}/{direction}: {error}" for error in errors
                        )
                plan_axes = plan_axes_by_storey.get(storey_id)
                if plan_axes is None:
                    authority_failures.append(f"{storey_id}: actual plan axis evidence is unavailable")
                else:
                    plan_matched, plan_errors = _plan_axes_match_binding(plan_axes, binding["candidateAxes"])
                    if not plan_matched:
                        authority_failures.extend(f"{storey_id}: {error}" for error in plan_errors)
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as error:
            authority_failures.append(f"{storey_id}: authority source unreadable or invalid: {error}")
        authority_evidence.append(row_evidence)
    checks["independent_axis_authority_binding"] = _check(
        not authority_failures,
        {
            "bindings": authority_evidence,
            "failures": authority_failures,
            "equalSpacingPolicy": "allowed only when the independent authority catalogue yields it",
        },
    )

    digest = document_set_digest(contract)
    modifier = contract["modifier"]
    selector_counter = Counter(str(value) for value in modifier["storeySelectorIds"])
    modifier_failures: list[str] = []
    parser = _ModifierParser()
    try:
        html = modifier_path.read_text(encoding="utf-8")
        parser.feed(html)
    except (OSError, UnicodeError) as error:
        html = ""
        modifier_failures.append(f"modifier unreadable as UTF-8: {error}")
    rendered_counter = Counter(parser.storey_ids)
    if not _counter_is_bijection(selector_counter, requested):
        modifier_failures.append("declared modifier selector is not a bijection with requestedStoreys")
    if not _counter_is_bijection(rendered_counter, requested):
        modifier_failures.append("rendered modifier selector is not a bijection with requestedStoreys")
    if parser.mode != "document_set_switcher":
        modifier_failures.append("rendered modifier mode is not document_set_switcher")
    if parser.artifact_role != "interactive_drawing_modifier":
        modifier_failures.append("rendered modifier artifact role is incorrect")
    if parser.selection_scope != "document_scoped":
        modifier_failures.append("rendered modifier selection scope is not document_scoped")
    if parser.default_storey != modifier["defaultStoreyId"]:
        modifier_failures.append("rendered default storey differs from contract")
    if parser.active_storey != modifier["activeStoreyId"]:
        modifier_failures.append("rendered active storey differs from contract")
    if modifier["defaultStoreyId"] not in requested:
        modifier_failures.append("default storey is outside requestedStoreys")
    if modifier["activeStoreyId"] not in requested:
        modifier_failures.append("active storey is outside requestedStoreys")
    if parser.document_set_sha256 != digest:
        modifier_failures.append("rendered document-set digest is stale")
    if modifier["embeddedDocumentSetSha256"] != digest:
        modifier_failures.append("declared embedded document-set digest is stale")
    checks["modifier_document_set_complete"] = _check(
        not modifier_failures,
        {
            "requested": dict(requested),
            "declaredSelectors": dict(selector_counter),
            "renderedSelectors": dict(rendered_counter),
            "defaultStoreyId": modifier["defaultStoreyId"],
            "activeStoreyId": modifier["activeStoreyId"],
            "failures": modifier_failures,
        },
    )

    freshness_failures: list[str] = []
    open_target = _resolve(modifier["openTargetPath"], base_dir)
    actual_html_sha: str | None = None
    actual_open_sha: str | None = None
    try:
        actual_html_sha = _file_sha256(modifier_path)
        if actual_html_sha != modifier["htmlSha256"]:
            freshness_failures.append("modifier byte SHA-256 mismatch")
    except OSError as error:
        freshness_failures.append(f"modifier hash unavailable: {error}")
    try:
        actual_open_sha = _file_sha256(open_target)
        if actual_open_sha != modifier["openTargetSha256"]:
            freshness_failures.append("open-target byte SHA-256 mismatch")
    except OSError as error:
        freshness_failures.append(f"open-target hash unavailable: {error}")
    if not _same_path(modifier_path, open_target):
        freshness_failures.append("declared open target is not the validated modifier path")
    if actual_html_sha is not None and actual_open_sha is not None and actual_html_sha != actual_open_sha:
        freshness_failures.append("opened bytes differ from validated modifier bytes")
    checks["modifier_open_target_freshness"] = _check(
        not freshness_failures,
        {
            "modifierPath": str(modifier["htmlPath"]),
            "modifierSha256": actual_html_sha,
            "openTargetPath": str(modifier["openTargetPath"]),
            "openTargetSha256": actual_open_sha,
            "failures": freshness_failures,
        },
    )

    locks = contract["safetyLocks"]
    locks_pass = (
        locks == {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
        }
    )
    checks["safety_locks_preserved"] = _check(locks_pass, locks)
    status = "pass" if all(row["pass"] for row in checks.values()) else "failed"
    return {
        "schema": "aicad_architectural_document_set_validation_v1",
        "status": status,
        "rulesApplied": RULES_APPLIED,
        "documentSetSha256": digest,
        "checks": checks,
        "reviewOnly": locks["reviewOnly"],
        "accepted": locks["accepted"],
        "ruleEnabled": locks["ruleEnabled"],
        "packagingGated": locks["packagingGated"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate architecture multi-storey document-set, axis-authority and modifier freshness contracts."
    )
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    contract_path = args.contract.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    result = evaluate(contract, contract_path.parent)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
