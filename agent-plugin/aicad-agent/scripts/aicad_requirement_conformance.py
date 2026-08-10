from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from aicad_normality_prover import _resolve_parameters  # noqa: E402


EXPECTED_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
}
RULE_IDS = ["PKG-G024", "PKG-G025"]
ROOT_CAUSES = {
    "contract_integrity": (
        "需求没有被整理成唯一、可追踪且有明确权威顺序的契约，后续几何可能从错误前提开始。",
        "先冻结带来源、优先级、冲突处理和安全锁的需求契约；ID、来源引用或权威顺序不完整时禁止进入绘图。",
    ),
    "contract_binding": (
        "设计证据没有绑定当前需求契约，可能拿旧版本或另一任务的证据证明当前图纸。",
        "追踪文件必须同时匹配 contractId 和规范化 SHA-256；需求变化后必须重建全部证据。",
    ),
    "hard_requirements": (
        "至少一条用户硬要求没有被实际值独立证明，或者仅用自报的 satisfied 状态代替数值/枚举比对。",
        "每条硬要求必须恰有一条证据，验证器重新计算 expected 与 observed 的关系；任一失败都不得被其他得分抵消。",
    ),
    "actual_binding": (
        "至少一条硬要求的 observed 只是追踪文件自报值，没有解析到当前结构模板、实际参数实例或契约中的受控字段，或者解析值与自报值不一致。",
        "每条硬要求必须声明可解析的 actualBinding；验证器从当前受控对象重取 boundActual，并强制 boundActual == observed == expected。模板、实例或字段变化后必须重跑第一关。",
    ),
    "assumptions": (
        "影响产品类型、结构或关键尺寸的高影响假设仍未获确认，生成器擅自替用户作了设计决定。",
        "高影响假设必须明确确认为 confirmed；仅 disclosed、被拒绝或缺失均阻断绘图。",
    ),
    "conflicts": (
        "不同输入来源对尺寸或结构的说法冲突，但没有按权威顺序形成可审计的解决结论。",
        "每个冲突必须标为 resolved，写明采用来源和对应需求 ID；未解决冲突不得进入几何阶段。",
    ),
    "dimension_authority": (
        "尺寸来自无尺寸权威的来源，或把参考图片像素当成了工程尺寸真值。",
        "每个关键尺寸都要追到 dimensionalAuthority=true 的非图片来源；图片只能提供拓扑和视觉语义。",
    ),
    "design_identity": (
        "实际产品、结构族、标准或上下闭合方式与需求契约/正常性模板不一致，属于几何正确但产品选错。",
        "在逐线检查前先锁定 typed design identity，并与结构族模板的 profile、standard、top、bottom 逐项相等。",
    ),
    "major_features": (
        "实际设计含有用户未要求的主要功能，或遗漏契约要求的主要功能。",
        "主要功能必须满足 required ⊆ actual ⊆ allowed，且 actual 与 forbidden 不相交；新增结构必须先回写契约。",
    ),
    "outputs": (
        "计划输出与用户要求不一致，可能缺少审计源文件或额外输出未经同意。",
        "契约要求的每种输出都必须在 outputsPlanned 中声明；构建阶段再逐个校验存在性和哈希。",
    ),
    "locks": (
        "审阅安全锁被打开或契约与设计追踪的锁状态不一致。",
        "所有阶段强制 reviewOnly=true、accepted=false、ruleEnabled=false、packagingGated=true。",
    ),
}


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _failure(gate: str, details: Any) -> dict[str, Any]:
    root_cause, prevention = ROOT_CAUSES[gate]
    return {
        "gate": gate,
        "rootCause": root_cause,
        "preventionRule": prevention,
        "persistentRuleIds": RULE_IDS,
        "details": details,
    }


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _expected_match(expected: dict[str, Any], observed: Any) -> tuple[bool, str]:
    kind = expected.get("kind")
    if kind == "exact":
        wanted = expected.get("value")
        if _finite_number(wanted) and _finite_number(observed):
            tolerance = float(expected.get("tolerance", 0.0))
            passed = abs(float(wanted) - float(observed)) <= tolerance
        else:
            passed = observed == wanted
        return passed, f"expected exact {wanted!r}, observed {observed!r}"
    if kind == "one_of":
        values = expected.get("values", [])
        return observed in values, f"expected one of {values!r}, observed {observed!r}"
    if kind == "present":
        passed = observed is not None and observed != "" and observed is not False
        return passed, f"expected present value, observed {observed!r}"
    if kind == "absent":
        passed = observed is None or observed == "" or observed is False or observed == []
        return passed, f"expected absent value, observed {observed!r}"
    if kind == "set_contains":
        wanted = set(expected.get("values", []))
        actual = set(observed) if isinstance(observed, list) else set()
        return wanted <= actual, f"expected set containing {sorted(wanted)!r}, observed {sorted(actual)!r}"
    if kind == "range":
        passed = (
            _finite_number(observed)
            and float(expected.get("minimum")) <= float(observed) <= float(expected.get("maximum"))
        )
        return passed, (
            f"expected range [{expected.get('minimum')!r}, {expected.get('maximum')!r}], "
            f"observed {observed!r}"
        )
    return False, f"unsupported expected kind {kind!r}"


def _unique_ids(rows: Any) -> tuple[bool, list[str], list[str]]:
    if not isinstance(rows, list):
        return False, [], ["<not-an-array>"]
    ids = [str(row.get("id", "")) for row in rows if isinstance(row, dict)]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1 or not key)
    return len(ids) == len(rows) and not duplicates, ids, duplicates


def _json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("jsonPointer must begin with /")
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"jsonPointer {pointer!r} does not resolve at {part!r}")
    return current


def _resolve_actual_binding(
    binding: dict[str, Any],
    contract: dict[str, Any],
    normality_template: dict[str, Any] | None,
    normality_instance: dict[str, Any] | None,
) -> Any:
    sources = {
        "contract": contract,
        "normality_template": normality_template,
        "normality_instance": normality_instance,
    }
    source_name = binding.get("source")
    source = sources.get(source_name)
    if source is None:
        raise ValueError(f"actual binding source {source_name!r} is unavailable")
    transform = binding.get("transform")
    if transform == "normality_parameters":
        if normality_template is None or normality_instance is None:
            raise ValueError("normality_parameters requires template and instance")
        resolved = _resolve_parameters(normality_template, normality_instance.get("values", {})).values
        parameter_ids = binding.get("parameterIds", [])
        unknown = [parameter_id for parameter_id in parameter_ids if parameter_id not in resolved]
        if unknown:
            raise ValueError(f"unknown normality parameters {unknown}")
        values = [resolved[parameter_id] for parameter_id in parameter_ids]
        return values[0] if len(values) == 1 else values
    value = _json_pointer(source, binding.get("jsonPointer"))
    if transform == "identity":
        return value
    if transform == "contains":
        return binding.get("containsValue") in value
    if transform == "all_review_locks_closed":
        return isinstance(value, dict) and all(value.get(key) == expected for key, expected in EXPECTED_LOCKS.items())
    raise ValueError(f"unsupported actual binding transform {transform!r}")


def evaluate(
    contract: dict[str, Any],
    trace: dict[str, Any],
    normality_template: dict[str, Any] | None = None,
    normality_instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}

    contract_schema_ok = contract.get("schema") == "aicad_drawing_requirement_contract_v1"
    trace_schema_ok = trace.get("schema") == "aicad_drawing_requirement_trace_v1"
    source_ids_ok, source_ids, duplicate_sources = _unique_ids(contract.get("sources"))
    requirement_ids_ok, requirement_ids, duplicate_requirements = _unique_ids(contract.get("requirements"))
    assumption_ids_ok, _, duplicate_assumptions = _unique_ids(contract.get("assumptions"))
    conflict_ids_ok, _, duplicate_conflicts = _unique_ids(contract.get("conflicts"))
    source_set = set(source_ids)
    authority = contract.get("authorityOrder", [])
    authority_ok = isinstance(authority, list) and len(authority) == len(set(authority)) and set(authority) == source_set
    source_references: list[dict[str, Any]] = []
    for collection in ("requirements", "assumptions", "conflicts"):
        for row in contract.get(collection, []):
            unknown = sorted(set(row.get("sourceIds", [])) - source_set)
            if unknown:
                source_references.append({"collection": collection, "id": row.get("id"), "unknown": unknown})
    required_features = set(contract.get("requiredMajorFeatures", []))
    allowed_features = set(contract.get("allowedMajorFeatures", []))
    forbidden_features = set(contract.get("forbiddenMajorFeatures", []))
    feature_contract_ok = required_features <= allowed_features and not (allowed_features & forbidden_features)
    contract_integrity = all(
        (
            contract_schema_ok,
            trace_schema_ok,
            source_ids_ok,
            requirement_ids_ok,
            assumption_ids_ok,
            conflict_ids_ok,
            authority_ok,
            not source_references,
            feature_contract_ok,
            bool(contract.get("requirements")),
        )
    )
    checks["contractCompleteAndAuthorityOrdered"] = contract_integrity
    if not contract_integrity:
        failures.append(
            _failure(
                "contract_integrity",
                {
                    "contractSchemaOk": contract_schema_ok,
                    "traceSchemaOk": trace_schema_ok,
                    "duplicateSourceIds": duplicate_sources,
                    "duplicateRequirementIds": duplicate_requirements,
                    "duplicateAssumptionIds": duplicate_assumptions,
                    "duplicateConflictIds": duplicate_conflicts,
                    "authorityCoversEverySourceExactlyOnce": authority_ok,
                    "unknownSourceReferences": source_references,
                    "requiredFeaturesSubsetAllowedAndNotForbidden": feature_contract_ok,
                },
            )
        )

    actual_contract_sha = canonical_sha256(contract)
    binding_ok = (
        trace.get("contractId") == contract.get("contractId")
        and trace.get("contractSha256") == actual_contract_sha
    )
    checks["traceBindsExactContractRevision"] = binding_ok
    if not binding_ok:
        failures.append(
            _failure(
                "contract_binding",
                {
                    "expectedContractId": contract.get("contractId"),
                    "actualContractId": trace.get("contractId"),
                    "expectedContractSha256": actual_contract_sha,
                    "actualContractSha256": trace.get("contractSha256"),
                },
            )
        )

    evidence_rows = trace.get("requirementEvidence", [])
    evidence_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_rows if isinstance(evidence_rows, list) else []:
        evidence_by_id.setdefault(str(row.get("requirementId")), []).append(row)
    unknown_evidence = sorted(set(evidence_by_id) - set(requirement_ids))
    hard_results: list[dict[str, Any]] = []
    for requirement in contract.get("requirements", []):
        if requirement.get("priority") != "hard":
            continue
        rows = evidence_by_id.get(str(requirement.get("id")), [])
        if len(rows) != 1:
            hard_results.append(
                {
                    "requirementId": requirement.get("id"),
                    "pass": False,
                    "reason": f"expected exactly one evidence row, found {len(rows)}",
                }
            )
            continue
        row = rows[0]
        value_pass, comparison = _expected_match(requirement.get("expected", {}), row.get("observed"))
        binding_error = None
        bound_actual = None
        try:
            bound_actual = _resolve_actual_binding(
                row.get("actualBinding", {}),
                contract,
                normality_template,
                normality_instance,
            )
            binding_matches_observed, binding_comparison = _expected_match(
                {"kind": "exact", "value": bound_actual, "tolerance": requirement.get("expected", {}).get("tolerance", 0)},
                row.get("observed"),
            )
        except Exception as exc:
            binding_matches_observed = False
            binding_comparison = f"actual binding failed: {exc}"
            binding_error = str(exc)
        evidence = row.get("evidence")
        evidence_present = isinstance(evidence, list) and bool(evidence)
        confirmation_ok = (
            not requirement.get("mustConfirm")
            or any(item.get("method") == "human_confirmation" for item in evidence if isinstance(item, dict))
        )
        passed = (
            row.get("status") == "satisfied"
            and value_pass
            and binding_matches_observed
            and evidence_present
            and confirmation_ok
        )
        hard_results.append(
            {
                "requirementId": requirement.get("id"),
                "category": requirement.get("category"),
                "pass": passed,
                "status": row.get("status"),
                "independentComparisonPass": value_pass,
                "comparison": comparison,
                "actualBinding": row.get("actualBinding"),
                "boundActual": bound_actual,
                "bindingMatchesObserved": binding_matches_observed,
                "bindingComparison": binding_comparison,
                "bindingError": binding_error,
                "evidencePresent": evidence_present,
                "confirmationRequired": bool(requirement.get("mustConfirm")),
                "humanConfirmationPresent": confirmation_ok,
            }
        )
    actual_bindings_ok = (
        bool(hard_results)
        and all(row.get("bindingMatchesObserved") is True for row in hard_results)
        and not unknown_evidence
    )
    checks["everyHardRequirementActualBoundToControlledSource"] = actual_bindings_ok
    if not actual_bindings_ok:
        failures.append(
            _failure(
                "actual_binding",
                {
                    "failedBindings": [
                        row for row in hard_results if row.get("bindingMatchesObserved") is not True
                    ],
                    "unknownEvidenceRequirementIds": unknown_evidence,
                },
            )
        )

    hard_requirements_ok = (
        bool(hard_results)
        and all(row["pass"] for row in hard_results)
        and not unknown_evidence
    )
    checks["everyHardRequirementIndependentlyProven"] = hard_requirements_ok
    if not hard_requirements_ok:
        failures.append(
            _failure(
                "hard_requirements",
                {
                    "failedRequirements": [row for row in hard_results if not row["pass"]],
                    "unknownEvidenceRequirementIds": unknown_evidence,
                },
            )
        )

    unresolved_assumptions = [
        row for row in contract.get("assumptions", [])
        if row.get("impact") == "high" and row.get("status") != "confirmed"
    ]
    assumptions_ok = not unresolved_assumptions
    checks["highImpactAssumptionsConfirmed"] = assumptions_ok
    if not assumptions_ok:
        failures.append(_failure("assumptions", {"unconfirmedHighImpactAssumptions": unresolved_assumptions}))

    unresolved_conflicts = [
        row for row in contract.get("conflicts", [])
        if row.get("status") != "resolved" or not row.get("resolution") or not row.get("resolvedRequirementId")
    ]
    conflict_targets_unknown = [
        row.get("id") for row in contract.get("conflicts", [])
        if row.get("resolvedRequirementId") and row.get("resolvedRequirementId") not in set(requirement_ids)
    ]
    conflicts_ok = not unresolved_conflicts and not conflict_targets_unknown
    checks["allSourceConflictsResolved"] = conflicts_ok
    if not conflicts_ok:
        failures.append(
            _failure(
                "conflicts",
                {
                    "unresolved": unresolved_conflicts,
                    "unknownResolvedRequirementTargets": conflict_targets_unknown,
                },
            )
        )

    sources_by_id = {str(row.get("id")): row for row in contract.get("sources", [])}
    invalid_image_authority = [
        source_id for source_id, row in sources_by_id.items()
        if row.get("kind") == "reference_image" and row.get("dimensionalAuthority") is not False
    ]
    invalid_dimension_sources: list[dict[str, Any]] = []
    for row in trace.get("dimensionSources", []):
        source = sources_by_id.get(str(row.get("sourceId")))
        if (
            source is None
            or source.get("dimensionalAuthority") is not True
            or source.get("kind") == "reference_image"
            or row.get("derivedFromImagePixels") is not False
        ):
            invalid_dimension_sources.append(row)
    dimension_authority_ok = not invalid_image_authority and not invalid_dimension_sources
    checks["dimensionsUseAuthoritativeNonPixelSources"] = dimension_authority_ok
    if not dimension_authority_ok:
        failures.append(
            _failure(
                "dimension_authority",
                {
                    "referenceImagesIncorrectlyGrantedAuthority": invalid_image_authority,
                    "invalidDimensionSources": invalid_dimension_sources,
                },
            )
        )

    identity = trace.get("designIdentity", {})
    identity_errors: list[str] = []
    if identity.get("productType") != contract.get("productType"):
        identity_errors.append("productType")
    if identity.get("units") != contract.get("units"):
        identity_errors.append("units")
    if normality_template is not None:
        closure = normality_template.get("closureSystem", {})
        expected_identity = {
            "structureFamily": normality_template.get("profileId"),
            "standard": closure.get("standard"),
            "topClosure": closure.get("top"),
            "bottomClosure": closure.get("bottom"),
        }
        for key, value in expected_identity.items():
            if identity.get(key) != value:
                identity_errors.append(key)
        if normality_template.get("productType") != contract.get("productType"):
            identity_errors.append("templateProductType")
    identity_ok = not identity_errors
    checks["typedDesignIdentityMatchesContractAndTemplate"] = identity_ok
    if not identity_ok:
        failures.append(
            _failure(
                "design_identity",
                {
                    "mismatchedFields": sorted(set(identity_errors)),
                    "actual": identity,
                    "templateProfile": normality_template.get("profileId") if normality_template else None,
                    "templateClosureSystem": normality_template.get("closureSystem") if normality_template else None,
                },
            )
        )

    actual_features = set(trace.get("declaredMajorFeatures", []))
    template_features = (
        set(normality_template.get("majorFeatures", []))
        if normality_template is not None
        else actual_features
    )
    missing_required = sorted(required_features - actual_features)
    unrequested = sorted(actual_features - allowed_features)
    explicitly_forbidden = sorted(actual_features & forbidden_features)
    template_feature_contract_missing = (
        normality_template is not None and bool(required_features) and not normality_template.get("majorFeatures")
    )
    trace_template_feature_drift = sorted(actual_features ^ template_features)
    major_features_ok = (
        not missing_required
        and not unrequested
        and not explicitly_forbidden
        and not template_feature_contract_missing
        and not trace_template_feature_drift
    )
    checks["majorFeaturesAreRequiredOrExplicitlyAllowed"] = major_features_ok
    if not major_features_ok:
        failures.append(
            _failure(
                "major_features",
                {
                    "missingRequired": missing_required,
                    "unrequestedOrUndeclared": unrequested,
                    "forbiddenPresent": explicitly_forbidden,
                    "templateMajorFeaturesMissing": template_feature_contract_missing,
                    "traceTemplateFeatureDrift": trace_template_feature_drift,
                },
            )
        )

    required_outputs = set(contract.get("requiredOutputs", []))
    planned_outputs = set(trace.get("outputsPlanned", []))
    missing_outputs = sorted(required_outputs - planned_outputs)
    outputs_ok = not missing_outputs
    checks["requiredOutputsPlanned"] = outputs_ok
    if not outputs_ok:
        failures.append(_failure("outputs", {"missingRequiredOutputs": missing_outputs}))

    locks_ok = all(contract.get("locks", {}).get(key) == value for key, value in EXPECTED_LOCKS.items())
    locks_ok = locks_ok and all(trace.get("locks", {}).get(key) == value for key, value in EXPECTED_LOCKS.items())
    checks["reviewSafetyLocksClosed"] = locks_ok
    if not locks_ok:
        failures.append(
            _failure("locks", {"contractLocks": contract.get("locks"), "traceLocks": trace.get("locks")})
        )

    return {
        "schema": "aicad_requirement_conformance_report_v1",
        "status": "pass" if not failures else "failed",
        "contract": {
            "id": contract.get("contractId"),
            "revision": contract.get("revision"),
            "canonicalSha256": actual_contract_sha,
            "requestSummary": contract.get("requestSummary"),
        },
        "designIdentity": identity,
        "ruleIds": RULE_IDS,
        "checks": checks,
        "counts": {
            "sources": len(contract.get("sources", [])),
            "hardRequirements": len(hard_results),
            "hardRequirementsPassed": sum(1 for row in hard_results if row["pass"]),
            "actualBindings": len(hard_results),
            "actualBindingsPassed": sum(
                1 for row in hard_results if row.get("bindingMatchesObserved") is True
            ),
            "assumptions": len(contract.get("assumptions", [])),
            "conflicts": len(contract.get("conflicts", [])),
            "requiredMajorFeatures": len(required_features),
            "actualMajorFeatures": len(actual_features),
            "requiredOutputs": len(required_outputs),
        },
        "hardRequirementResults": hard_results,
        "failures": failures,
        "orderedGate": {
            "stage": 1,
            "name": "overall_user_requirement_conformance",
            "nextStageAllowed": not failures,
            "nonCompensatory": True,
            "meaning": "A failed overall requirement cannot be offset by perfect line geometry.",
        },
        "locks": EXPECTED_LOCKS,
    }


def write_markdown(report: dict[str, Any], target: Path) -> None:
    lines = [
        "# AICAD 整体需求一致性报告",
        "",
        f"- 总状态：**{report['status'].upper()}**",
        f"- 需求契约：{report['contract'].get('id')} / revision {report['contract'].get('revision')}",
        f"- 契约规范化 SHA-256：{report['contract'].get('canonicalSha256')}",
        f"- 硬要求：{report['counts']['hardRequirementsPassed']}/{report['counts']['hardRequirements']} 通过。",
        f"- 受控实际值绑定：{report['counts'].get('actualBindingsPassed', 0)}/{report['counts'].get('actualBindings', 0)} 通过。",
        "",
        "## 第一阶段硬门禁",
        "",
    ]
    labels = {
        "contractCompleteAndAuthorityOrdered": "需求完整且输入权威顺序封闭",
        "traceBindsExactContractRevision": "证据绑定当前契约版本",
        "everyHardRequirementActualBoundToControlledSource": "每条硬要求均绑定当前受控模板/实例/契约字段",
        "everyHardRequirementIndependentlyProven": "每条硬要求均由实际值独立证明",
        "highImpactAssumptionsConfirmed": "高影响假设已确认",
        "allSourceConflictsResolved": "输入冲突已按优先级解决",
        "dimensionsUseAuthoritativeNonPixelSources": "尺寸来自权威非像素来源",
        "typedDesignIdentityMatchesContractAndTemplate": "产品/结构族/上下闭合类型一致",
        "majorFeaturesAreRequiredOrExplicitlyAllowed": "主要功能无遗漏、无擅自增加",
        "requiredOutputsPlanned": "输出清单覆盖用户要求",
        "reviewSafetyLocksClosed": "审阅安全锁保持关闭",
    }
    for key, passed in report.get("checks", {}).items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {labels.get(key, key)}")
    lines.extend(["", "## 错误根因与下次预防规则", ""])
    if not report.get("failures"):
        lines.append("本次整体意图门禁全部通过，才允许进入逐线、拓扑、功能面和参数域的细节证明。")
    for failure in report.get("failures", []):
        lines.extend(
            [
                f"### {failure['gate']}",
                "",
                f"- 为什么出现：{failure['rootCause']}",
                f"- 下次如何避免：{failure['preventionRule']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 顺序约束",
            "",
            "本报告仅是第一阶段。只有本阶段 PASS，才可运行第二阶段细节正常性证明；两阶段均 PASS 后才允许构建候选工件。任何后级高分都不能抵消本阶段失败。",
            "",
            "当前仍是审阅候选，不代表量产、强度、设备公差或技术验收。",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prove that the selected CAD design matches the user's whole requirement before geometry checks"
    )
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--normality-template", type=Path)
    parser.add_argument("--normality-instance", type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-md", required=True, type=Path)
    args = parser.parse_args()
    try:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        trace = json.loads(args.trace.read_text(encoding="utf-8"))
        template = (
            json.loads(args.normality_template.read_text(encoding="utf-8"))
            if args.normality_template
            else None
        )
        instance = (
            json.loads(args.normality_instance.read_text(encoding="utf-8"))
            if args.normality_instance
            else None
        )
        report = evaluate(contract, trace, template, instance)
    except Exception as exc:
        report = {
            "schema": "aicad_requirement_conformance_report_v1",
            "status": "failed",
            "checks": {"contractReadable": False},
            "counts": {"hardRequirementsPassed": 0, "hardRequirements": 0},
            "contract": {},
            "failures": [_failure("contract_integrity", {"error": str(exc)})],
            "orderedGate": {
                "stage": 1,
                "name": "overall_user_requirement_conformance",
                "nextStageAllowed": False,
                "nonCompensatory": True,
            },
            "locks": EXPECTED_LOCKS,
        }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, args.out_md)
    print(
        json.dumps(
            {
                "status": report["status"],
                "failedGates": [item["gate"] for item in report.get("failures", [])],
                "outJson": str(args.out_json.resolve()),
                "outMarkdown": str(args.out_md.resolve()),
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
