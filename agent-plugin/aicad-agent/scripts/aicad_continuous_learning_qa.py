#!/usr/bin/env python3
"""Audit lesson closure and optional manual-promotion evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for candidate in (PLUGIN_ROOT / "runtime" / "src", PLUGIN_ROOT.parent.parent / "src"):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from aicad.continuous_learning import (  # noqa: E402
    EXPECTED_CANDIDATE_LOCKS,
    audit_lesson_bundle,
    audit_promotion_ledger,
    canonical_failure_alias,
    controlled_learning_output_path,
    file_entry,
    resolve_output_path,
    safe_relative_path,
)
from aicad.reporting import ReportInvariantError, prevention_rule_id  # noqa: E402


def _read_json(root: Path, relative: str) -> dict[str, object]:
    entry = file_entry(root, relative)
    return json.loads((root / entry["path"]).read_text(encoding="utf-8-sig"))


CATALOG_DOMAINS = {
    "general", "software", "release", "cad", "architecture", "packaging",
    "mechanical", "electronics",
}
CATALOG_FIELDS = {
    "schema", "scope", "canonicalEventPolicy", "controls", "preventionRules",
    "failureAliases", "candidateSafetyLocks", "promotionPolicy",
}
EXPECTED_CONTROL_IDS = {f"CL-G{index:03d}" for index in range(1, 10)}
EXPECTED_SCOPE = "test_and_gate_failures_across_all_aicad_domains"
EXPECTED_EVENT_POLICY = "no_implicit_timestamp_no_absolute_machine_path_hash_bound_safe_relative_evidence"
CONTROL_FIELDS = {"id", "name", "requirement", "requiredRegression"}
RULE_FIELDS = {
    "id", "domain", "name", "symptom", "rootCause", "prevention",
    "requiredRegression",
}
ALIAS_FIELDS = {"alias", "domain", "ruleId", "failingCheck"}
ALIAS_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_]+)+$")


def _nonempty_text(row: dict[str, object], field: str, label: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ReportInvariantError(f"{label}.{field} must be non-empty text")
    return value.strip()


def audit_rule_catalog(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("schema") != "aicad_continuous_learning_rules_v1":
        raise ReportInvariantError("continuous-learning rule schema mismatch")
    if set(payload) != CATALOG_FIELDS:
        raise ReportInvariantError("continuous-learning catalog must have the exact top-level fields")
    if payload.get("scope") != EXPECTED_SCOPE or payload.get("canonicalEventPolicy") != EXPECTED_EVENT_POLICY:
        raise ReportInvariantError("continuous-learning scope/event policy mismatch")
    if payload.get("candidateSafetyLocks") != EXPECTED_CANDIDATE_LOCKS:
        raise ReportInvariantError("candidateSafetyLocks are not exact")
    controls = payload.get("controls")
    rules = payload.get("preventionRules")
    aliases = payload.get("failureAliases")
    if not isinstance(controls, list) or not controls or not isinstance(rules, list) or not rules:
        raise ReportInvariantError("continuous-learning controls and preventionRules must be non-empty")
    if not isinstance(aliases, list) or not aliases:
        raise ReportInvariantError("failureAliases must be non-empty")
    control_ids: list[str] = []
    for index, row in enumerate(controls):
        if not isinstance(row, dict) or set(row) != CONTROL_FIELDS:
            raise ReportInvariantError(f"controls[{index}] must have the exact control fields")
        for field in CONTROL_FIELDS:
            _nonempty_text(row, field, f"controls[{index}]")
        rule_id = str(row["id"])
        prevention_rule_id(rule_id + ": catalog")
        control_ids.append(rule_id)
    rule_ids: list[str] = []
    rule_by_id: dict[str, dict[str, object]] = {}
    for index, row in enumerate(rules):
        if not isinstance(row, dict) or set(row) != RULE_FIELDS:
            raise ReportInvariantError(f"preventionRules[{index}] must have the exact rule fields")
        for field in RULE_FIELDS:
            _nonempty_text(row, field, f"preventionRules[{index}]")
        if row["domain"] not in CATALOG_DOMAINS:
            raise ReportInvariantError(f"unsupported prevention-rule domain: {row['domain']!r}")
        rule_id = str(row["id"])
        prevention_rule_id(rule_id + ": catalog")
        rule_ids.append(rule_id)
        rule_by_id[rule_id] = row
    if set(control_ids) != EXPECTED_CONTROL_IDS:
        raise ReportInvariantError("continuous-learning control inventory is not exact")
    if len(set(control_ids)) != len(control_ids) or len(set(rule_ids)) != len(rule_ids):
        raise ReportInvariantError("control and prevention rule IDs must be unique")
    if set(control_ids) & set(rule_ids):
        raise ReportInvariantError("control and prevention rule IDs must be disjoint")
    alias_names: list[str] = []
    aliased_rule_ids: set[str] = set()
    for index, row in enumerate(aliases):
        if not isinstance(row, dict) or set(row) != ALIAS_FIELDS:
            raise ReportInvariantError(f"failureAliases[{index}] must have the exact alias fields")
        alias = _nonempty_text(row, "alias", f"failureAliases[{index}]")
        domain = _nonempty_text(row, "domain", f"failureAliases[{index}]")
        _nonempty_text(row, "failingCheck", f"failureAliases[{index}]")
        if domain not in CATALOG_DOMAINS or not ALIAS_RE.fullmatch(alias) or not alias.startswith(domain + "."):
            raise ReportInvariantError(f"failure alias is not stable/domain-qualified: {alias}")
        if row.get("ruleId") not in rule_by_id:
            raise ReportInvariantError(f"failure alias references unknown prevention rule: {alias}")
        aliased_rule_ids.add(str(row["ruleId"]))
        alias_names.append(alias)
    duplicates = [key for key, count in Counter(alias_names).items() if count != 1]
    if duplicates:
        raise ReportInvariantError(f"duplicate failure aliases: {sorted(duplicates)}")
    orphan_rules = sorted(set(rule_ids) - aliased_rule_ids)
    if orphan_rules:
        raise ReportInvariantError(f"prevention rules without a failure alias: {orphan_rules}")
    policy = payload.get("promotionPolicy")
    expected_policy = {
        "automaticPromotion": False,
        "authoritativeRuleMutationByTool": False,
        "installedPluginMutationByTool": False,
        "testDeletionAllowed": False,
        "ruleWeakeningAllowed": False,
        "requiresTwoDistinctRecordedReviewerIds": True,
        "requiresExternalAuthenticatedReview": True,
        "requiresBundleRuleVersionBinding": True,
        "requiresStrictlyNewerVersion": True,
        "requiresRedBeforeFixGreenAfterFix": True,
        "requiresUnrelatedSuitesPass": True,
    }
    if policy != expected_policy:
        raise ReportInvariantError("promotionPolicy is not the exact fail-closed policy")
    return {
        "schema": "aicad_continuous_learning_rule_audit_v1",
        "status": "pass",
        "controlCount": len(controls),
        "preventionRuleCount": len(rules),
        "failureAliasCount": len(aliases),
        "failureAliasesUniqueAndRuleBound": True,
        "allPreventionRulesAliased": True,
        "promotionPolicyFailClosed": True,
        "externalAuthenticatedReviewRequired": True,
    }


def _audit_bundle_aliases(bundle: dict[str, object], rules: dict[str, object]) -> dict[str, object]:
    alias_map = {row["alias"]: row["ruleId"] for row in rules["failureAliases"]}
    known: list[str] = []
    novel: list[str] = []
    mismatched: list[str] = []
    for lesson in bundle["lessons"]:
        alias = canonical_failure_alias(lesson["failureAlias"], lesson["domain"])
        expected = alias_map.get(alias)
        if expected is None:
            novel.append(alias)
        else:
            known.append(alias)
            if expected != lesson["candidateRule"]["id"]:
                mismatched.append(alias)
    if mismatched:
        raise ReportInvariantError(f"known failure aliases bind different rule IDs: {sorted(mismatched)}")
    return {
        "knownAliases": sorted(known),
        "novelReviewOnlyAliases": sorted(novel),
        "knownAliasBindingsMatch": True,
        "actualFailedChecksAndLessonAliasesExact": True,
    }


def _atomic_json(root: Path, relative: str, payload: object) -> None:
    destination = resolve_output_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = resolve_output_path(root, relative)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a controlled-learning bundle; never promote or mutate rules.")
    parser.add_argument("bundle", help="Safe-relative aicad_lesson_bundle_v1 path")
    parser.add_argument("--root", required=True, type=Path, help="Explicit root for every safe-relative input and output")
    parser.add_argument("--rules", default="rules/continuous_learning_rules.json")
    parser.add_argument("--approval-ledger", help="Optional safe-relative recorded approval ledger")
    parser.add_argument("--plugin-manifest", default=".codex-plugin/plugin.json")
    parser.add_argument("--output", required=True, help="Safe-relative QA output path")
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        bundle_relative = safe_relative_path(args.bundle)
        rules_relative = safe_relative_path(args.rules)
        output = controlled_learning_output_path(args.output)
        approval_relative = safe_relative_path(args.approval_ledger) if args.approval_ledger else None
        manifest_relative = safe_relative_path(args.plugin_manifest)
        protected_inputs = {bundle_relative, rules_relative, manifest_relative}
        if approval_relative:
            protected_inputs.add(approval_relative)
        if output in protected_inputs:
            raise ReportInvariantError("learning audit output must not overwrite any audited input")
        bundle = _read_json(root, bundle_relative)
        rules = _read_json(root, rules_relative)
        bundle_audit = audit_lesson_bundle(root, bundle)
        rules_audit = audit_rule_catalog(rules)
        alias_audit = _audit_bundle_aliases(bundle, rules)
        promotion = None
        if approval_relative:
            manifest = _read_json(root, manifest_relative)
            version = manifest.get("version")
            if not isinstance(version, str):
                raise ReportInvariantError("plugin manifest has no string version")
            ledger = _read_json(root, approval_relative)
            promotion = audit_promotion_ledger(root, ledger, current_version=version)
        result = {
            "schema": "aicad_continuous_learning_qa_v1",
            "status": "pass",
            "bundle": bundle_audit,
            "rules": rules_audit,
            "aliases": alias_audit,
            "recordedPromotionPreconditions": promotion,
            "authoritativeRulesModified": False,
            "testsDeleted": False,
            "installedPluginModified": False,
            "promotionPerformed": False,
            "externalAuthenticatedReviewVerified": False,
            "promotionEligibleForManualApplication": False,
            "technicalPackageReady": False,
            "productionReleaseEligible": False,
            "manufacturingAuthorized": False,
            "fabricationAuthorized": False,
        }
        _atomic_json(root, output, result)
    except (OSError, UnicodeError, json.JSONDecodeError, ReportInvariantError) as exc:
        print(json.dumps({"ok": False, "status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({
        "ok": True,
        "status": "pass",
        "output": output,
        "externalAuthenticatedReviewVerified": False,
        "promotionEligibleForManualApplication": False,
        "promotionPerformed": False,
        "technicalPackageReady": False,
        "productionReleaseEligible": False,
        "manufacturingAuthorized": False,
        "fabricationAuthorized": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
