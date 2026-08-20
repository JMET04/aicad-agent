from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from jsonschema import Draft202012Validator


SCRIPT_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_ROOT.parent
RULES_PATH = PLUGIN_ROOT / "rules" / "production_readiness_rules.json"
SCHEMA_PATH = PLUGIN_ROOT / "rules" / "engineering_normative_preflight.schema.json"
NORMATIVE_RULES_PATH = PLUGIN_ROOT / "rules" / "normative_governance_rules.json"

EXPECTED_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
    "technicalPackageReady": False,
    "productionReleaseEligible": False,
    "manufacturingAuthorized": False,
    "fabricationAuthorized": False,
}
DOMAIN_RULE_ID = {"mechanical": "PROD-G011", "electronics": "PROD-G012"}
AUTHORITATIVE_SOURCE_KINDS = {
    "selected_standard",
    "approved_engineering_input",
    "user_explicit_numeric",
    "user_explicit_semantic",
}
NA_AUTHORITY_KINDS = {"selected_standard", "approved_engineering_input"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_TEXT = re.compile(r"(?:placeholder|replace with|todo|tbd|unresolved)", re.IGNORECASE)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value

def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _gate_fingerprint(path: str, gate: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json({"gatePath": path, "canonicalGate": gate}).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _controlled_evidence_root(value: str | Path | None) -> tuple[Path | None, str | None]:
    if value is None:
        return None, "controlled_evidence_root_required"
    raw = Path(value).expanduser()
    try:
        is_junction = getattr(raw, "is_junction", lambda: False)
        if raw.is_symlink() or is_junction():
            return None, "evidence_root_link_or_junction_forbidden"
        root = raw.resolve(strict=True)
    except OSError:
        return None, "evidence_root_missing"
    if not root.is_dir():
        return None, "evidence_root_not_directory"
    return root, None


def _source_evidence_errors(root: Path, row: dict[str, Any]) -> list[str]:
    value = row["path"]
    if not _portable_source_path(value):
        return ["unsafe_or_nonportable_path"]
    relative = PurePosixPath(value)
    if relative.as_posix() != value:
        return ["noncanonical_path"]
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", lambda: False)
        if cursor.is_symlink() or is_junction():
            return ["link_or_junction_forbidden"]
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return ["source_file_missing"]
    if not candidate.is_file() or (resolved != root and root not in resolved.parents):
        return ["source_not_regular_file_or_outside_root"]
    reasons: list[str] = []
    actual_size = resolved.stat().st_size
    if row["size"] != actual_size:
        reasons.append(f"size_mismatch:{row['size']}:{actual_size}")
    actual_sha256 = _sha256_file(resolved)
    if row["sha256"] != actual_sha256:
        reasons.append("sha256_mismatch")
    if str(row["authorityRevision"]).strip().casefold().startswith("unresolved"):
        reasons.append("authority_revision_unresolved")
    if str(row["mediaType"]).strip().casefold().startswith("unresolved"):
        reasons.append("media_type_unresolved")
    return reasons


def _canonical_context(domain: str) -> tuple[dict[str, Any], dict[str, Any], list[str], dict[str, dict[str, Any]]]:
    rules = _load_json(RULES_PATH)
    policy = rules.get("generationPreflightPolicy", {})
    profile_name = policy.get("canonicalProfileByDomain", {}).get(domain)
    if not profile_name or profile_name not in rules:
        raise ValueError(f"unsupported engineering preflight domain: {domain!r}")
    sections = policy.get("includedSections", [])
    if not isinstance(sections, list) or not sections:
        raise ValueError("generationPreflightPolicy.includedSections is missing")
    profile = rules[profile_name]
    inventory: dict[str, dict[str, Any]] = {}
    for section in sections:
        gates = profile.get(section)
        if not isinstance(gates, dict) or not gates:
            raise ValueError(f"canonical profile section is missing: {profile_name}.{section}")
        for gate_name, gate in gates.items():
            inventory[f"{domain}.{section}.{gate_name}"] = gate
    rules_by_id = {row["id"]: row for row in rules.get("rules", [])}
    for rule_id in policy.get("sharedRuleIds", []):
        if rule_id not in rules_by_id:
            raise ValueError(f"canonical shared generation rule is missing: {rule_id}")
        inventory[f"shared.rules.{rule_id}"] = rules_by_id[rule_id]
    return rules, profile, sections, inventory


def _requirement_text(path: str, gate: dict[str, Any]) -> str:
    if isinstance(gate.get("requirement"), str):
        return gate["requirement"]
    pointer = gate.get("jsonPointer", "canonical evidence field")
    expected = json.dumps(gate.get("expectedValue"), ensure_ascii=False, sort_keys=True)
    return (
        f"Resolve canonical gate {path} before controlled generation. The generated design and its later "
        f"evidence plan must bind {pointer} to the rule-owned expected value {expected}."
    )


def build_template(domain: str) -> dict[str, Any]:
    rules, profile, _, inventory = _canonical_context(domain)
    normative = _load_json(NORMATIVE_RULES_PATH)
    standards = profile.get("intent", {}).get("currentStandardsLedger", {}).get("expectedValue", [])
    if not isinstance(standards, list) or not standards:
        raise ValueError(f"{domain} canonical standards ledger is missing")
    first_standard = standards[0]["standard"]
    return {
        "schema": "aicad_engineering_normative_preflight_v1",
        "contractId": f"{domain.upper()}_NORMATIVE_PREFLIGHT_DRAFT",
        "revision": 1,
        "domain": domain,
        "deliveryStage": "review",
        "canonicalRulesSchema": rules["schema"],
        "canonicalRulesVersion": rules["version"],
        "authorityOrder": normative["authorityPrecedence"],
        "sources": [
            {
                "id": "STD_AUTHORITY",
                "kind": "selected_standard",
                "description": "Replace with the controlled standards source and edition/scope evidence.",
                "path": "UNRESOLVED/selected-standard.bin",
                "size": 0,
                "sha256": "0" * 64,
                "mediaType": "application/octet-stream",
                "authorityRevision": "UNRESOLVED",
            },
            {
                "id": "ENG_INPUT",
                "kind": "approved_engineering_input",
                "description": "Replace with the approved design basis, calculations, interfaces and process capability.",
                "path": "UNRESOLVED/approved-engineering-input.json",
                "size": 0,
                "sha256": "0" * 64,
                "mediaType": "application/json",
                "authorityRevision": "UNRESOLVED",
            },
        ],
        "applicableStandards": [
            {
                "standard": row["standard"],
                "status": row["status"],
                "applicability": row["applicability"],
                "sourceId": "STD_AUTHORITY",
                "scopeDecision": "Confirm applicability and edition against the controlled project design basis.",
            }
            for row in standards
        ],
        "ruleApplications": [
            {
                "gatePath": path,
                "disposition": "unresolved",
                "requirement": _requirement_text(path, gate),
                "canonicalGateSha256": _gate_fingerprint(path, gate),
                "sourceIds": ["STD_AUTHORITY", "ENG_INPUT"],
                "standardIds": [first_standard],
                "verificationMethod": "Replace with the calculation, rule check, native-host check or inspection method.",
                "verifierId": "unresolved",
            }
            for path, gate in inventory.items()
        ],
        "conflicts": [],
        "locks": dict(EXPECTED_LOCKS),
    }


def _failure(code: str, details: Any, domain: str | None) -> dict[str, Any]:
    persistent = ["NORM-G001", "NORM-G002", "NORM-G003", "NORM-G004"]
    if domain in DOMAIN_RULE_ID:
        persistent.append(DOMAIN_RULE_ID[domain])
    return {
        "code": code,
        "details": details,
        "persistentRuleIds": persistent,
        "rootCause": "A canonical mechanical/electronics rule was not converted into a source-bound generation constraint.",
        "preventionRule": "Derive the exact preflight inventory from production_readiness_rules.json and fail before geometry on every unresolved, unbound, missing or extra gate.",
    }


def _portable_source_path(value: str) -> bool:
    if not value or "\\" in value or PureWindowsPath(value).drive:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _failed_report(domain: str | None, failures: list[dict[str, Any]], checks: dict[str, bool], counts: dict[str, int]) -> dict[str, Any]:
    return {
        "schema": "aicad_engineering_normative_preflight_report_v1",
        "status": "failed",
        "domain": domain,
        "conclusion": "normative_preflight_blocked",
        "checks": checks,
        "counts": counts,
        "failures": failures,
        "generationGate": {
            "stage": 0,
            "nextStageAllowed": False,
            "nonCompensatory": True,
            "artifactExposureAllowed": False,
        },
        "readinessBoundary": {
            "evidenceContractReady": False,
            "technicalPackageReady": False,
            "productionReleaseEligible": False,
            "manufacturingAuthorized": False,
            "fabricationAuthorized": False,
        },
        "locks": dict(EXPECTED_LOCKS),
    }


def evaluate(contract: dict[str, Any], evidence_root: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return _failed_report(None, [_failure("contract_not_object", {}, None)], {"schemaValid": False}, {})
    domain = contract.get("domain") if contract.get("domain") in DOMAIN_RULE_ID else None
    schema = _load_json(SCHEMA_PATH)
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(contract), key=lambda item: list(item.path))
    if schema_errors:
        details = [
            {"path": "/" + "/".join(str(part) for part in error.path), "message": error.message}
            for error in schema_errors
        ]
        return _failed_report(domain, [_failure("schema_invalid", details, domain)], {"schemaValid": False}, {})

    assert domain is not None
    rules, profile, sections, inventory = _canonical_context(domain)
    normative = _load_json(NORMATIVE_RULES_PATH)
    checks: dict[str, bool] = {"schemaValid": True}
    failures: list[dict[str, Any]] = []

    canonical_ok = (
        contract["canonicalRulesSchema"] == rules["schema"]
        and contract["canonicalRulesVersion"] == rules["version"]
    )
    checks["canonicalRulesIdentityMatches"] = canonical_ok
    if not canonical_ok:
        failures.append(_failure("canonical_rules_identity_mismatch", {
            "expectedSchema": rules["schema"], "expectedVersion": rules["version"],
            "actualSchema": contract["canonicalRulesSchema"], "actualVersion": contract["canonicalRulesVersion"],
        }, domain))

    authority_ok = contract["authorityOrder"] == normative["authorityPrecedence"]
    checks["authorityOrderIsCanonical"] = authority_ok
    if not authority_ok:
        failures.append(_failure("authority_order_mismatch", {"expected": normative["authorityPrecedence"]}, domain))

    source_ids = [row["id"] for row in contract["sources"]]
    source_counts = Counter(source_ids)
    duplicate_sources = sorted(key for key, count in source_counts.items() if count != 1)
    sources_by_id = {row["id"]: row for row in contract["sources"]}
    source_kinds = {row["kind"] for row in contract["sources"]}
    root, root_error = _controlled_evidence_root(evidence_root)
    seen_paths: set[str] = set()
    duplicate_paths: list[str] = []
    source_evidence_errors: dict[str, list[str]] = {}
    for row in contract["sources"]:
        path = row["path"]
        normalized = str(PurePosixPath(path)).casefold()
        if normalized in seen_paths:
            duplicate_paths.append(path)
        seen_paths.add(normalized)
        reasons = [root_error] if root_error is not None else _source_evidence_errors(root, row)
        if reasons:
            source_evidence_errors[row["id"]] = reasons
    required_source_kinds = {"selected_standard", "approved_engineering_input"}
    sources_ok = (
        not duplicate_sources
        and not duplicate_paths
        and not source_evidence_errors
        and required_source_kinds.issubset(source_kinds)
    )
    checks["sourcesAreUniquePortableAndAuthoritative"] = sources_ok
    checks["sourceFilesExistAndMatchDeclaredHashes"] = root_error is None and not source_evidence_errors
    if not sources_ok:
        failures.append(_failure("source_inventory_invalid", {
            "duplicateIds": duplicate_sources,
            "duplicatePaths": duplicate_paths,
            "evidenceRootError": root_error,
            "sourceEvidenceErrors": source_evidence_errors,
            "missingRequiredKinds": sorted(required_source_kinds - source_kinds),
        }, domain))

    required_standards = profile["intent"]["currentStandardsLedger"]["expectedValue"]
    expected_standard_rows = {
        (row["standard"], row["status"], row["applicability"])
        for row in required_standards
    }
    actual_standard_rows = {
        (row["standard"], row["status"], row["applicability"])
        for row in contract["applicableStandards"]
    }
    duplicate_standard_names = sorted(
        key for key, count in Counter(row["standard"] for row in contract["applicableStandards"]).items() if count != 1
    )
    bad_standard_sources = [
        row["standard"] for row in contract["applicableStandards"]
        if row["sourceId"] not in sources_by_id or sources_by_id[row["sourceId"]]["kind"] != "selected_standard"
    ]
    standards_ok = (
        expected_standard_rows.issubset(actual_standard_rows)
        and not duplicate_standard_names and not bad_standard_sources
    )
    checks["canonicalStandardsAreEditionScopeBound"] = standards_ok
    if not standards_ok:
        failures.append(_failure("standards_ledger_incomplete", {
            "missing": sorted(expected_standard_rows - actual_standard_rows),
            "duplicateStandards": duplicate_standard_names,
            "invalidStandardSource": bad_standard_sources,
        }, domain))

    applications = contract["ruleApplications"]
    application_counts = Counter(row["gatePath"] for row in applications)
    duplicate_gates = sorted(key for key, count in application_counts.items() if count != 1)
    actual_gates = set(application_counts)
    expected_gates = set(inventory)
    inventory_ok = actual_gates == expected_gates and not duplicate_gates
    checks["canonicalGenerationGateInventoryIsExact"] = inventory_ok
    if not inventory_ok:
        failures.append(_failure("gate_inventory_mismatch", {
            "missing": sorted(expected_gates - actual_gates),
            "extra": sorted(actual_gates - expected_gates),
            "duplicates": duplicate_gates,
        }, domain))

    unresolved: list[str] = []
    invalid_na: list[str] = []
    invalid_bindings: list[str] = []
    unknown_standard_refs: list[str] = []
    canonical_requirement_mismatch: list[str] = []
    canonical_fingerprint_mismatch: list[str] = []
    invalid_verifiers: list[str] = []
    placeholder_fields: list[str] = []
    standard_names = {row["standard"] for row in contract["applicableStandards"]}
    for row in applications:
        path = row["gatePath"]
        disposition = row["disposition"]
        if disposition == "unresolved":
            unresolved.append(path)
        if disposition == "not_applicable" and (".intent." in path or path.startswith("shared.rules.")):
            invalid_na.append(path)
        referenced_sources = [sources_by_id.get(source_id) for source_id in row["sourceIds"]]
        known_sources = [item for item in referenced_sources if item is not None]
        known_kinds = {item["kind"] for item in known_sources}
        required_kinds = {"selected_standard", "approved_engineering_input"}
        if len(known_sources) != len(referenced_sources) or not required_kinds.issubset(known_kinds):
            invalid_bindings.append(path)
        for standard_id in row["standardIds"]:
            if standard_id not in standard_names:
                unknown_standard_refs.append(f"{path}:{standard_id}")
        canonical_gate = inventory.get(path)
        if canonical_gate is not None:
            if row["requirement"] != _requirement_text(path, canonical_gate):
                canonical_requirement_mismatch.append(path)
            if row["canonicalGateSha256"] != _gate_fingerprint(path, canonical_gate):
                canonical_fingerprint_mismatch.append(path)
        verifier_id = row["verifierId"]
        if (
            (disposition == "constrained" and verifier_id == "unresolved")
            or (disposition == "not_applicable" and verifier_id != "authority_review")
        ):
            invalid_verifiers.append(path)
        if disposition == "constrained":
            for field in ("generationConstraint", "verificationMethod"):
                if PLACEHOLDER_TEXT.search(str(row.get(field, ""))):
                    placeholder_fields.append(f"{path}:{field}")
    applications_ok = not any((
        unresolved,
        invalid_na,
        invalid_bindings,
        unknown_standard_refs,
        canonical_requirement_mismatch,
        canonical_fingerprint_mismatch,
        invalid_verifiers,
        placeholder_fields,
    ))
    checks["everyGateIsSourceBoundAndGenerationConstrained"] = applications_ok
    checks["canonicalGateContentAndFingerprintMatch"] = (
        not canonical_requirement_mismatch and not canonical_fingerprint_mismatch
    )
    if not applications_ok:
        failures.append(_failure("gate_application_invalid", {
            "unresolved": unresolved,
            "intentMarkedNotApplicable": invalid_na,
            "missingAuthoritativeSourceBinding": invalid_bindings,
            "unknownStandardReferences": unknown_standard_refs,
            "canonicalRequirementMismatch": canonical_requirement_mismatch,
            "canonicalGateFingerprintMismatch": canonical_fingerprint_mismatch,
            "invalidVerifier": invalid_verifiers,
            "placeholderFields": placeholder_fields,
        }, domain))

    conflict_errors = []
    for row in contract["conflicts"]:
        unknown = sorted(set(row["sourceIds"]) - set(sources_by_id))
        if row["status"] != "resolved" or not row.get("resolution") or unknown:
            conflict_errors.append({"id": row["id"], "unknownSourceIds": unknown, "status": row["status"]})
    conflicts_ok = not conflict_errors
    checks["allConflictsAreResolved"] = conflicts_ok
    if not conflicts_ok:
        failures.append(_failure("unresolved_source_conflict", conflict_errors, domain))

    locks_ok = contract["locks"] == EXPECTED_LOCKS
    checks["safetyLocksRemainClosed"] = locks_ok
    if not locks_ok:
        failures.append(_failure("safety_lock_mismatch", {"actual": contract["locks"]}, domain))

    counts = {
        "canonicalSections": len(sections),
        "canonicalGates": len(expected_gates),
        "contractGates": len(applications),
        "requiredStandards": len(expected_standard_rows),
        "contractStandards": len(contract["applicableStandards"]),
        "sources": len(contract["sources"]),
        "unresolvedGates": len(unresolved),
        "notApplicableGates": sum(row["disposition"] == "not_applicable" for row in applications),
    }
    if failures:
        return _failed_report(domain, failures, checks, counts)
    return {
        "schema": "aicad_engineering_normative_preflight_report_v1",
        "status": "pass",
        "domain": domain,
        "conclusion": rules["generationPreflightPolicy"]["preflightConclusion"],
        "canonicalRules": {"schema": rules["schema"], "version": rules["version"], "path": "rules/production_readiness_rules.json"},
        "checks": checks,
        "counts": counts,
        "failures": [],
        "generationGate": {
            "stage": 0,
            "nextStageAllowed": True,
            "nonCompensatory": True,
            "artifactExposureAllowed": False,
        },
        "readinessBoundary": {
            "evidenceContractReady": False,
            "technicalPackageReady": False,
            "productionReleaseEligible": False,
            "manufacturingAuthorized": False,
            "fabricationAuthorized": False,
        },
        "locks": dict(EXPECTED_LOCKS),
    }


def write_markdown(report: dict[str, Any], target: Path) -> None:
    lines = [
        "# AICAD engineering normative preflight",
        "",
        f"- Status: **{report.get('status', 'failed').upper()}**",
        f"- Domain: `{report.get('domain')}`",
        f"- Conclusion: `{report.get('conclusion')}`",
        f"- Generation allowed: `{report.get('generationGate', {}).get('nextStageAllowed', False)}`",
        f"- Artifact exposure allowed: `{report.get('generationGate', {}).get('artifactExposureAllowed', False)}`",
        "",
        "## Checks",
        "",
    ]
    for key, passed in report.get("checks", {}).items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} - {key}")
    lines.extend(["", "## Failures", ""])
    if not report.get("failures"):
        lines.append("No normative preflight failures.")
    for failure in report.get("failures", []):
        lines.extend([
            f"### {failure['code']}", "",
            f"- Root cause: {failure['rootCause']}",
            f"- Prevention: {failure['preventionRule']}",
            f"- Details: `{json.dumps(failure['details'], ensure_ascii=False, sort_keys=True)}`", "",
        ])
    lines.extend([
        "## Boundary", "",
        "A pass only freezes source-bound mechanical/electronics generation constraints. It is not design proof, native-host replay, technical-package readiness, manufacturing authorization or fabrication authorization.",
    ])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or validate the canonical mechanical/electronics normative generation preflight")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--template", choices=sorted(DOMAIN_RULE_ID))
    group.add_argument("--contract", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args()
    if args.template:
        payload = build_template(args.template)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "draft", "domain": args.template, "output": str(args.output.resolve())}, ensure_ascii=False))
        return
    try:
        contract = _load_json(args.contract)
        report = evaluate(contract, args.evidence_root or args.contract.parent)
    except Exception as exc:
        report = _failed_report(None, [_failure("contract_read_error", {"error": str(exc)}, None)], {"contractReadable": False}, {})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        write_markdown(report, args.markdown)
    print(json.dumps({"status": report["status"], "domain": report.get("domain"), "output": str(args.output.resolve())}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
