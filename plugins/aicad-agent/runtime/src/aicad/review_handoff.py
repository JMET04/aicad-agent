from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .correction import preview_correction, write_correction_artifacts
from .engine import PlanError, compile_plan
from .engine3d import compile_plan3d
from .viewmap import generate_view_package, render_review_html, validate_review_html


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HANDOFF_FIELDS = {
    "handoff_schema_version", "source_sha256", "space", "domain", "instructions",
    "exact_transaction", "agent_action", "review_policy",
}
REVIEW_POLICY_FIELDS = {"reviewOnly", "accepted", "ruleEnabled"}
INSTRUCTION_FIELDS = {"text", "selected_refs"}


def _exact_keys(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise PlanError(f"{label} keys mismatch; missing={missing}, extra={extra}")
    return value


def _review_policy(value: Any) -> None:
    value = _exact_keys(value, REVIEW_POLICY_FIELDS, "review handoff review_policy")
    if value.get("reviewOnly") is not True or value.get("accepted") is not False or value.get("ruleEnabled") is not False:
        raise PlanError("review handoff must remain reviewOnly=true, accepted=false, ruleEnabled=false")


def _source_hash(plan_data: dict[str, Any], space: str) -> str:
    return (compile_plan(plan_data) if space == "2d" else compile_plan3d(plan_data)).source_hash


def _instructions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PlanError("review handoff instructions must be an array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        item = _exact_keys(item, INSTRUCTION_FIELDS, f"review handoff instructions[{index}]")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise PlanError(f"review handoff instructions[{index}].text is required")
        selected = item.get("selected_refs", [])
        if not isinstance(selected, list) or any(not isinstance(reference, dict) for reference in selected):
            raise PlanError(f"review handoff instructions[{index}].selected_refs must be an array")
        rows.append(item)
    return rows


def _validated_preview(
    plan_data: dict[str, Any], handoff_data: dict[str, Any], domain: str, require_actionable: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    handoff_data = _exact_keys(handoff_data, HANDOFF_FIELDS, "review handoff")
    if handoff_data.get("handoff_schema_version") != "1.0":
        raise PlanError("review handoff handoff_schema_version must be '1.0'")
    space = handoff_data.get("space")
    if space not in {"2d", "3d"}:
        raise PlanError("review handoff space must be 2d or 3d")
    declared_domain = handoff_data.get("domain", domain)
    if not isinstance(declared_domain, str) or not declared_domain.strip():
        raise PlanError("review handoff domain must be a non-empty string")
    if not isinstance(handoff_data.get("agent_action"), str) or not handoff_data["agent_action"].strip():
        raise PlanError("review handoff agent_action must be a non-empty string")
    if domain != "general" and declared_domain != domain:
        raise PlanError(f"review handoff domain '{declared_domain}' does not match requested domain '{domain}'")
    _review_policy(handoff_data.get("review_policy"))
    instructions = _instructions(handoff_data.get("instructions"))
    supplied_hash = handoff_data.get("source_sha256")
    if not isinstance(supplied_hash, str) or not SHA256_PATTERN.fullmatch(supplied_hash):
        raise PlanError("review handoff source_sha256 must be a lowercase SHA-256")
    current_hash = _source_hash(plan_data, space)
    if supplied_hash != current_hash:
        raise PlanError("review handoff source_sha256 is stale")
    transaction = handoff_data.get("exact_transaction")
    if transaction is None:
        if require_actionable:
            raise PlanError("review handoff contains natural-language instructions only; agent interpretation is required before apply")
        return {
            "ok": True,
            "status": "requires_agent_interpretation",
            "valid": True,
            "actionable": False,
            "space": space,
            "domain": declared_domain,
            "source_sha256": current_hash,
            "instruction_count": len(instructions),
            "operation_count": 0,
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
        }, None
    if not isinstance(transaction, dict):
        raise PlanError("review handoff exact_transaction must be an object or null")
    if transaction.get("source_sha256") != supplied_hash:
        raise PlanError("review handoff exact_transaction source_sha256 does not match the handoff")
    correction = transaction.get("correction")
    if not isinstance(correction, dict) or correction.get("space") != space:
        raise PlanError("review handoff exact_transaction correction.space does not match the handoff")
    _review_policy(transaction.get("review_policy"))
    preview = preview_correction(plan_data, transaction, declared_domain)
    report = {
        "ok": True,
        "status": "ready_for_apply",
        "valid": True,
        "actionable": True,
        "space": space,
        "domain": declared_domain,
        "source_sha256": current_hash,
        "candidate_sha256": preview["after_sha256"],
        "instruction_count": len(instructions),
        "operation_count": preview["validation"]["operation_count"],
        "directly_changed_ids": preview["directly_changed_ids"],
        "affected_ids": preview["affected_ids"],
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
    }
    return report, preview


def validate_review_handoff(
    plan_data: dict[str, Any], handoff_data: dict[str, Any], domain: str = "general",
) -> dict[str, Any]:
    report, _preview = _validated_preview(plan_data, handoff_data, domain, False)
    return report


def apply_review_handoff(
    plan_data: dict[str, Any],
    handoff_data: dict[str, Any],
    output_dir: Path,
    stem: str,
    domain: str = "general",
) -> dict[str, Any]:
    report, preview = _validated_preview(plan_data, handoff_data, domain, True)
    assert preview is not None
    package = generate_view_package(preview["candidate_plan"], report["space"], report["domain"])
    review_html = render_review_html(package)
    review_issues = validate_review_html(review_html, report["space"])
    if review_issues:
        raise PlanError("corrected review HTML failed validation: " + ", ".join(review_issues))
    destination_is_empty = False
    if output_dir.exists():
        if not output_dir.is_dir() or any(output_dir.iterdir()):
            raise PlanError("review handoff output directory must not already contain artifacts")
        destination_is_empty = True
    receipt = {
        "schema": "aicad_review_handoff_receipt_v1",
        "status": "applied_review_candidate",
        "source_sha256": report["source_sha256"],
        "candidate_sha256": report["candidate_sha256"],
        "space": report["space"],
        "domain": report["domain"],
        "operation_count": report["operation_count"],
        "instruction_count": report["instruction_count"],
        "directly_changed_ids": report["directly_changed_ids"],
        "affected_ids": report["affected_ids"],
        "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False},
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}.{stem}.", dir=output_dir.parent) as temporary:
        stage = Path(temporary) / "payload"
        write_correction_artifacts(preview, stage, stem)
        (stage / f"{stem}.corrected.modifier.html").write_text(review_html, encoding="utf-8")
        (stage / f"{stem}.review-handoff.receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        if destination_is_empty:
            empty_backup = Path(temporary) / "empty-destination"
            os.replace(output_dir, empty_backup)
            try:
                os.replace(stage, output_dir)
            except OSError:
                os.replace(empty_backup, output_dir)
                raise
        else:
            os.replace(stage, output_dir)
    artifacts = {
        "plan": str((output_dir / f"{stem}.corrected.plan.json").resolve()),
        "transaction": str((output_dir / f"{stem}.correction.json").resolve()),
        "audit": str((output_dir / f"{stem}.correction.audit.md").resolve()),
        "review_html": str((output_dir / f"{stem}.corrected.modifier.html").resolve()),
        "receipt": str((output_dir / f"{stem}.review-handoff.receipt.json").resolve()),
    }
    return {
        **report,
        "status": "applied_review_candidate",
        "artifacts": artifacts,
        "gates": {
            "source_hash_current": True,
            "transaction_preview_passed": True,
            "dependency_replay_passed": True,
            "corrected_review_valid": True,
            "atomic_directory_promotion": True,
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
        },
    }
