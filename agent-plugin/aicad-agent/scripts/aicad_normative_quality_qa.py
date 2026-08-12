#!/usr/bin/env python3
"""Independent derived QA for the cross-domain AICAD normative contract."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "rules" / "cad_normative_quality_contract.schema.json"
TOLERANCE_MM = 1e-6
RULES_APPLIED = [f"CAD-Q{index:03d}" for index in range(1, 8)]
CHECK_NAMES = (
    "contract_schema_valid",
    "input_hash_ids_unique",
    "structural_support_bidirectional_pair_set",
    "forward_annotation_reservation_dual_viewport",
    "semantic_distance_pick_arbitration",
    "document_set_exact_scope",
    "release_declaration_requires_external_verifier",
    "native_utf8_text_transport",
    "safety_locks_preserved",
)
SEMANTIC_PRIORITY = {
    "COLUMN": 900,
    "WALL": 900,
    "OPENING": 850,
    "EQUIPMENT": 700,
    "FURNITURE": 600,
    "GENERAL": 450,
    "DIMENSION": 250,
    "TEXT": 200,
    "GRID": 100,
}
EXPECTED_VIEWPORTS = {
    "desktop_1920x1200": (1920, 1200),
    "compact_1280x800": (1280, 800),
}


def _check(passed: bool, evidence: Any) -> dict[str, Any]:
    return {"pass": bool(passed), "evidence": evidence}


def _schema_errors(contract: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(contract), key=lambda row: list(row.absolute_path))
    ]


def _blank_report(errors: list[str]) -> dict[str, Any]:
    checks = {
        name: _check(
            False,
            errors if name == "contract_schema_valid" else "not evaluated because schema validation failed",
        )
        for name in CHECK_NAMES
    }
    return {
        "schema": "aicad_cad_normative_quality_validation_v1",
        "status": "failed",
        "rulesApplied": RULES_APPLIED,
        "externalReleaseVerifierRequired": True,
        "checks": checks,
    }


def _valid_rect(row: dict[str, Any]) -> bool:
    values = (row["leftPx"], row["topPx"], row["rightPx"], row["bottomPx"])
    return all(math.isfinite(float(value)) for value in values) and (
        float(row["rightPx"]) > float(row["leftPx"])
        and float(row["bottomPx"]) > float(row["topPx"])
    )


def _inside(inner: dict[str, Any], outer: dict[str, Any]) -> bool:
    return (
        float(inner["leftPx"]) >= float(outer["leftPx"])
        and float(inner["topPx"]) >= float(outer["topPx"])
        and float(inner["rightPx"]) <= float(outer["rightPx"])
        and float(inner["bottomPx"]) <= float(outer["bottomPx"])
    )


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        min(float(left["rightPx"]), float(right["rightPx"]))
        > max(float(left["leftPx"]), float(right["leftPx"]))
        and min(float(left["bottomPx"]), float(right["bottomPx"]))
        > max(float(left["topPx"]), float(right["topPx"]))
    )


def _point_key(row: dict[str, Any]) -> tuple[int, int]:
    return (
        round(float(row["xMm"]) / TOLERANCE_MM),
        round(float(row["yMm"]) / TOLERANCE_MM),
    )


def _duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count != 1)


def _validate_supports(contract: dict[str, Any]) -> dict[str, Any]:
    mode = contract["structuralSupportMode"]
    bindings = contract["structuralSupportBindings"]
    if mode == "not_applicable":
        domain_requires_support = str(contract["domain"]).casefold() in {
            "architecture", "structural", "steel", "steel_structure"
        }
        failures = []
        if domain_requires_support:
            failures.append("this domain cannot waive structural support transfer")
        if bindings:
            failures.append("not-applicable mode cannot carry support bindings")
        return _check(
            not failures,
            {
                "mode": mode,
                "waiverReason": contract.get("structuralSupportWaiverReason"),
                "bindingCount": len(bindings),
                "failures": failures,
            },
        )

    failures: list[str] = []
    evidence: list[dict[str, Any]] = []
    requested = Counter(map(str, contract["documentSet"]["requestedIds"]))
    binding_docs = Counter(str(binding["documentId"]) for binding in bindings)
    if binding_docs != requested or any(count != 1 for count in binding_docs.values()):
        failures.append("support-binding document IDs are not an exact bijection with requested document IDs")

    for binding in bindings:
        document_id = str(binding["documentId"])
        source = binding["source"]
        target = binding["target"]
        source_ids = [str(row["id"]) for row in source]
        target_ids = [str(row["id"]) for row in target]
        duplicate_source_ids = _duplicate_values(source_ids)
        duplicate_target_ids = _duplicate_values(target_ids)
        if duplicate_source_ids:
            failures.append(f"{document_id}: duplicate source support IDs {duplicate_source_ids}")
        if duplicate_target_ids:
            failures.append(f"{document_id}: duplicate target support IDs {duplicate_target_ids}")
        source_pairs = Counter(_point_key(row) for row in source)
        target_pairs = Counter(_point_key(row) for row in target)
        if any(count != 1 for count in source_pairs.values()):
            failures.append(f"{document_id}: duplicate source XY pair")
        if any(count != 1 for count in target_pairs.values()):
            failures.append(f"{document_id}: duplicate target XY pair")
        missing = source_pairs - target_pairs
        extra = target_pairs - source_pairs
        if missing:
            failures.append(f"{document_id}: target is missing source support XY pairs")
        if extra:
            failures.append(f"{document_id}: target adds unsupported XY pairs; Cartesian expansion is forbidden")
        source_id_set = set(source_ids)
        source_by_id = {str(row["id"]): row for row in source}
        unresolved = sorted(
            str(row["sourceEntityId"])
            for row in target
            if str(row["sourceEntityId"]) not in source_id_set
        )
        if unresolved:
            failures.append(f"{document_id}: target provenance does not resolve to source support IDs {unresolved}")
        mismatched_provenance = sorted(
            str(row["id"])
            for row in target
            if str(row["sourceEntityId"]) in source_by_id
            and _point_key(row) != _point_key(source_by_id[str(row["sourceEntityId"])])
        )
        if mismatched_provenance:
            failures.append(
                f"{document_id}: target provenance resolves to a source at a different XY pair {mismatched_provenance}"
            )
        evidence.append(
            {
                "documentId": document_id,
                "sourcePairCount": sum(source_pairs.values()),
                "targetPairCount": sum(target_pairs.values()),
                "missingPairCount": sum(missing.values()),
                "extraPairCount": sum(extra.values()),
                "unresolvedProvenanceCount": len(unresolved),
                "mismatchedProvenanceCount": len(mismatched_provenance),
            }
        )
    return _check(not failures, {"mode": mode, "bindings": evidence, "failures": failures})


def _validate_annotations(contract: dict[str, Any]) -> dict[str, Any]:
    layout = contract["annotationLayout"]
    viewports = layout["viewports"]
    failures: list[str] = []
    evidence: list[dict[str, Any]] = []
    observed = Counter(str(viewport["id"]) for viewport in viewports)
    if observed != Counter(EXPECTED_VIEWPORTS.keys()):
        failures.append("annotation evidence must contain each required viewport exactly once")

    for viewport in viewports:
        viewport_id = str(viewport["id"])
        expected_size = EXPECTED_VIEWPORTS.get(viewport_id)
        size = (int(viewport["widthPx"]), int(viewport["heightPx"]))
        if size != expected_size:
            failures.append(f"{viewport_id}: viewport size {size} differs from {expected_size}")
        if viewport["collisionCount"] != 0:
            failures.append(f"{viewport_id}: reported annotation collision count is not zero")
        if viewport["clippedCount"] != 0:
            failures.append(f"{viewport_id}: reported clipped annotation count is not zero")
        if float(viewport["horizontalOverflowPx"]) != 0.0:
            failures.append(f"{viewport_id}: reported horizontal overflow is not zero")

        frame = {"leftPx": 0, "topPx": 0, "rightPx": size[0], "bottomPx": size[1]}
        reservations = viewport["reservations"]
        required_reservation_stages = {"content", "axis_bubbles", "chain_dimensions", "overall_dimensions", "notes"}
        required_box_stages = {"axis_bubbles", "chain_dimensions", "overall_dimensions", "notes"}
        reservation_stages = {str(row["stage"]) for row in reservations}
        if reservation_stages != required_reservation_stages:
            failures.append(f"{viewport_id}: reservations do not cover every forward placement stage")
        reservation_ids = [str(row["id"]) for row in reservations]
        if _duplicate_values(reservation_ids):
            failures.append(f"{viewport_id}: duplicate reservation ID")
        reservation_map = {str(row["id"]): row for row in reservations}
        for reservation in reservations:
            if not _valid_rect(reservation):
                failures.append(f"{viewport_id}/{reservation['id']}: invalid reservation rectangle")
            elif not _inside(reservation, frame):
                failures.append(f"{viewport_id}/{reservation['id']}: reservation is clipped")
        for index, left in enumerate(reservations):
            for right in reservations[index + 1 :]:
                if left["ownerId"] != right["ownerId"] and _overlaps(left, right):
                    failures.append(
                        f"{viewport_id}: foreign reservations {left['id']} and {right['id']} overlap"
                    )

        boxes = viewport["boxes"]
        box_stages = {str(row["stage"]) for row in boxes}
        if box_stages != required_box_stages:
            failures.append(f"{viewport_id}: annotation boxes do not cover every placement stage")
        box_ids = [str(row["id"]) for row in boxes]
        if _duplicate_values(box_ids):
            failures.append(f"{viewport_id}: duplicate annotation box ID")
        for box in boxes:
            box_id = str(box["id"])
            if not _valid_rect(box):
                failures.append(f"{viewport_id}/{box_id}: invalid annotation rectangle")
                continue
            if float(box["textHeightPx"]) < 8.0:
                failures.append(f"{viewport_id}/{box_id}: text is below 8 CSS pixels")
            if not _inside(box, frame):
                failures.append(f"{viewport_id}/{box_id}: annotation is clipped")
            reservation = reservation_map.get(str(box["reservationId"]))
            if reservation is None:
                failures.append(f"{viewport_id}/{box_id}: owned reservation does not exist")
            else:
                if reservation["ownerId"] != box["ownerId"] or reservation["stage"] != box["stage"]:
                    failures.append(f"{viewport_id}/{box_id}: owner or placement stage differs from reservation")
                if not _inside(box, reservation):
                    failures.append(f"{viewport_id}/{box_id}: annotation escaped its owned reservation")
            for foreign in reservations:
                if foreign["ownerId"] != box["ownerId"] and _overlaps(box, foreign):
                    failures.append(
                        f"{viewport_id}/{box_id}: annotation intrudes into foreign/future reservation {foreign['id']}"
                    )
        for index, left in enumerate(boxes):
            for right in boxes[index + 1 :]:
                if _overlaps(left, right):
                    failures.append(f"{viewport_id}: annotation boxes {left['id']} and {right['id']} collide")
        evidence.append(
            {
                "id": viewport_id,
                "size": list(size),
                "reservationCount": len(reservations),
                "annotationCount": len(boxes),
                "minimumTextHeightPx": min(float(row["textHeightPx"]) for row in boxes),
            }
        )
    return _check(not failures, {"viewports": evidence, "failures": failures})


def _validate_picker(contract: dict[str, Any]) -> dict[str, Any]:
    picker = contract["selectionArbitration"]
    failures: list[str] = []
    evidence: list[dict[str, Any]] = []
    maximum = float(picker["maximumCandidateDistancePx"])
    bucket = float(picker["distanceBucketPx"])
    for case in picker["qaCases"]:
        case_id = str(case["id"])
        candidate_ids = [str(row["id"]) for row in case["candidates"]]
        if _duplicate_values(candidate_ids):
            failures.append(f"{case_id}: duplicate candidate ID")
        for candidate in case["candidates"]:
            expected_priority = SEMANTIC_PRIORITY[str(candidate["semanticType"])]
            if int(candidate["semanticPriority"]) != expected_priority:
                failures.append(
                    f"{case_id}/{candidate['id']}: semantic priority is self-reported incorrectly"
                )
        active_document = str(case["activeDocumentId"])
        eligible = [
            row
            for row in case["candidates"]
            if str(row["documentId"]) == active_document and float(row["distancePx"]) <= maximum
        ]
        eligible.sort(
            key=lambda row: (
                math.floor(float(row["distancePx"]) / bucket),
                -SEMANTIC_PRIORITY[str(row["semanticType"])],
                float(row["distancePx"]),
                str(row["id"]),
            )
        )
        observed = [str(row["id"]) for row in eligible]
        if observed != list(case["expectedCycle"]):
            failures.append(f"{case_id}: expected cycle {case['expectedCycle']} differs from derived {observed}")
        evidence.append({"id": case_id, "activeDocumentId": active_document, "derivedCycle": observed})
    return _check(not failures, {"priorityTable": SEMANTIC_PRIORITY, "cases": evidence, "failures": failures})


def evaluate(contract: dict[str, Any]) -> dict[str, Any]:
    schema_errors = _schema_errors(contract)
    if schema_errors:
        return _blank_report(schema_errors)

    checks: dict[str, dict[str, Any]] = {
        "contract_schema_valid": _check(True, "Draft 2020-12 schema validation passed")
    }
    hash_ids = [str(row["id"]) for row in contract["inputHashes"]]
    duplicate_hash_ids = _duplicate_values(hash_ids)
    checks["input_hash_ids_unique"] = _check(
        not duplicate_hash_ids,
        {"count": len(hash_ids), "duplicateIds": duplicate_hash_ids},
    )
    checks["structural_support_bidirectional_pair_set"] = _validate_supports(contract)
    checks["forward_annotation_reservation_dual_viewport"] = _validate_annotations(contract)
    checks["semantic_distance_pick_arbitration"] = _validate_picker(contract)

    document_set = contract["documentSet"]
    requested = Counter(map(str, document_set["requestedIds"]))
    rendered = Counter(map(str, document_set["renderedIds"]))
    source = Counter(map(str, document_set["sourceIds"]))
    exact_documents = requested == rendered == source and all(count == 1 for count in requested.values())
    checks["document_set_exact_scope"] = _check(
        exact_documents,
        {"requested": dict(requested), "rendered": dict(rendered), "source": dict(source)},
    )

    closure = contract["releaseClosure"]
    checks["release_declaration_requires_external_verifier"] = _check(
        True,
        {
            "declaration": closure,
            "independentlyProvenByThisQA": False,
            "externalVerifierRequired": True,
            "externalVerifier": "scripts/verify_release_package.py --source-root <repository>",
        },
    )
    text = contract["textTransport"]
    checks["native_utf8_text_transport"] = _check(
        text == {
            "executionIdsAscii": True,
            "humanTextEncoding": "UTF-8",
            "nativeTextBijection": True,
            "replacementCharacterCount": 0,
        },
        text,
    )
    locks = contract["safetyLocks"]
    checks["safety_locks_preserved"] = _check(
        locks == {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
        },
        locks,
    )
    status = "pass" if all(row["pass"] for row in checks.values()) else "failed"
    return {
        "schema": "aicad_cad_normative_quality_validation_v1",
        "status": status,
        "rulesApplied": RULES_APPLIED,
        "priorityTableVersion": "aicad_semantic_pick_priority_v1",
        "externalReleaseVerifierRequired": True,
        "checks": checks,
        "reviewOnly": locks["reviewOnly"],
        "accepted": locks["accepted"],
        "ruleEnabled": locks["ruleEnabled"],
        "packagingGated": locks["packagingGated"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate executable cross-domain AICAD normative evidence")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = evaluate(contract)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
