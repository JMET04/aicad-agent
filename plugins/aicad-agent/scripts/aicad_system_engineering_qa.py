#!/usr/bin/env python3
"""Non-compensatory consistency QA for an AICAD system engineering contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_NAME = "aicad.system-engineering-contract.v1"
LEVEL_RANK = {
    "defined": 0,
    "generated": 1,
    "tool_verified": 2,
    "physical_verified": 3,
    "released": 4,
}
TOP_LEVEL_REQUIRED = {
    "schema", "systemId", "revision", "intendedUse", "prohibitedUses",
    "requirements", "subsystems", "artifacts", "interfaces", "flows",
    "verificationGates", "changeImpacts", "evidenceBindings",
    "authorizations", "releaseLocks",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _id_map(rows: Any, label: str, errors: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        errors.append({"code": "SYS-SHAPE-001", "message": f"{label} must be an array"})
        return result
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            errors.append({"code": "SYS-ID-001", "message": f"{label}[{index}] has no stable id"})
            continue
        if row["id"] in result:
            errors.append({"code": "SYS-ID-002", "message": f"duplicate {label} id: {row['id']}"})
            continue
        result[row["id"]] = row
    return result


def _safe_evidence_path(root: Path, value: str) -> Path | None:
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def validate_contract(contract: dict[str, Any], root: Path) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    missing = sorted(TOP_LEVEL_REQUIRED - set(contract))
    if missing:
        errors.append({"code": "SYS-SHAPE-002", "message": f"missing top-level fields: {', '.join(missing)}"})
    if contract.get("schema") != SCHEMA_NAME:
        errors.append({"code": "SYS-SCHEMA-001", "message": f"schema must equal {SCHEMA_NAME}"})

    requirements = _id_map(contract.get("requirements"), "requirements", errors)
    subsystems = _id_map(contract.get("subsystems"), "subsystems", errors)
    artifacts = _id_map(contract.get("artifacts"), "artifacts", errors)
    interfaces = _id_map(contract.get("interfaces"), "interfaces", errors)
    flows = _id_map(contract.get("flows"), "flows", errors)
    gates = _id_map(contract.get("verificationGates"), "verificationGates", errors)
    evidence = _id_map(contract.get("evidenceBindings"), "evidenceBindings", errors)

    domains = {row.get("domain") for row in subsystems.values() if isinstance(row.get("domain"), str)}
    if len(subsystems) < 2 or len(domains) < 2:
        errors.append({"code": "SYS-BOUNDARY-001", "message": "a system contract needs at least two subsystems in two domains"})

    artifact_claims: dict[str, str] = {}
    for subsystem_id, subsystem in subsystems.items():
        claimed = subsystem.get("artifactIds")
        if not isinstance(claimed, list) or not claimed:
            errors.append({"code": "SYS-ART-001", "message": f"subsystem {subsystem_id} has no artifactIds"})
            continue
        for artifact_id in claimed:
            if artifact_id in artifact_claims:
                errors.append({"code": "SYS-ART-002", "message": f"artifact {artifact_id} is claimed by multiple subsystems"})
            artifact_claims[str(artifact_id)] = subsystem_id
    for artifact_id, artifact in artifacts.items():
        owner = artifact.get("subsystemId")
        if owner not in subsystems:
            errors.append({"code": "SYS-ART-003", "message": f"artifact {artifact_id} references unknown subsystem {owner}"})
        if artifact_claims.get(artifact_id) != owner:
            errors.append({"code": "SYS-ART-004", "message": f"artifact {artifact_id} is not bidirectionally owned by {owner}"})
        for evidence_id in artifact.get("evidenceIds", []):
            if evidence_id not in evidence:
                errors.append({"code": "SYS-EVID-001", "message": f"artifact {artifact_id} references unknown evidence {evidence_id}"})
    for artifact_id in sorted(set(artifact_claims) - set(artifacts)):
        errors.append({"code": "SYS-ART-005", "message": f"subsystem claims missing artifact {artifact_id}"})

    for interface_id, interface in interfaces.items():
        provider = interface.get("providerSubsystemId")
        consumer = interface.get("consumerSubsystemId")
        if provider not in subsystems or consumer not in subsystems:
            errors.append({"code": "SYS-ICD-001", "message": f"interface {interface_id} has an unknown endpoint"})
        if provider == consumer:
            errors.append({"code": "SYS-ICD-002", "message": f"interface {interface_id} must cross a subsystem boundary"})
        parameters = interface.get("parameters")
        if not isinstance(parameters, list) or not parameters:
            errors.append({"code": "SYS-ICD-003", "message": f"interface {interface_id} has no authoritative parameters"})
        for gate_id in interface.get("verificationGateIds", []):
            if gate_id not in gates:
                errors.append({"code": "SYS-TRACE-001", "message": f"interface {interface_id} references unknown gate {gate_id}"})

    for requirement_id, requirement in requirements.items():
        for subsystem_id in requirement.get("subsystemIds", []):
            if subsystem_id not in subsystems:
                errors.append({"code": "SYS-TRACE-002", "message": f"requirement {requirement_id} references unknown subsystem {subsystem_id}"})
        gate_ids = requirement.get("gateIds", [])
        if not isinstance(gate_ids, list) or not gate_ids:
            errors.append({"code": "SYS-TRACE-003", "message": f"requirement {requirement_id} has no verification gate"})
        for gate_id in gate_ids:
            if gate_id not in gates:
                errors.append({"code": "SYS-TRACE-004", "message": f"requirement {requirement_id} references unknown gate {gate_id}"})
            elif requirement_id not in gates[gate_id].get("requirementIds", []):
                errors.append({"code": "SYS-TRACE-005", "message": f"requirement {requirement_id} and gate {gate_id} are not bidirectionally traced"})
    for gate_id, gate in gates.items():
        for requirement_id in gate.get("requirementIds", []):
            if requirement_id not in requirements:
                errors.append({"code": "SYS-TRACE-006", "message": f"gate {gate_id} references unknown requirement {requirement_id}"})
            elif gate_id not in requirements[requirement_id].get("gateIds", []):
                errors.append({"code": "SYS-TRACE-007", "message": f"gate {gate_id} and requirement {requirement_id} are not bidirectionally traced"})
        required_level = gate.get("requiredEvidenceLevel")
        if required_level not in LEVEL_RANK:
            errors.append({"code": "SYS-GATE-001", "message": f"gate {gate_id} has invalid requiredEvidenceLevel {required_level}"})
        evidence_ids = gate.get("evidenceIds", [])
        if gate.get("status") == "passed" and not evidence_ids:
            errors.append({"code": "SYS-GATE-002", "message": f"passed gate {gate_id} has no evidence"})
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                errors.append({"code": "SYS-EVID-002", "message": f"gate {gate_id} references unknown evidence {evidence_id}"})
            elif required_level in LEVEL_RANK:
                actual_level = evidence[evidence_id].get("level")
                if actual_level not in LEVEL_RANK or LEVEL_RANK[actual_level] < LEVEL_RANK[required_level]:
                    errors.append({"code": "SYS-GATE-003", "message": f"evidence {evidence_id} is below gate {gate_id} level {required_level}"})

    for flow_id, flow in flows.items():
        nodes = flow.get("orderedSubsystemIds", [])
        if not isinstance(nodes, list) or len(nodes) < 2:
            errors.append({"code": "SYS-FLOW-001", "message": f"flow {flow_id} needs at least two ordered subsystems"})
        for node in nodes:
            if node not in subsystems:
                errors.append({"code": "SYS-FLOW-002", "message": f"flow {flow_id} references unknown subsystem {node}"})
        for interface_id in flow.get("interfaceIds", []):
            if interface_id not in interfaces:
                errors.append({"code": "SYS-FLOW-003", "message": f"flow {flow_id} references unknown interface {interface_id}"})
            else:
                endpoints = {
                    interfaces[interface_id].get("providerSubsystemId"),
                    interfaces[interface_id].get("consumerSubsystemId"),
                }
                if not endpoints.issubset(set(nodes)):
                    errors.append({"code": "SYS-FLOW-004", "message": f"flow {flow_id} omits an endpoint of interface {interface_id}"})

    known_impact_ids = set(requirements) | set(subsystems) | set(artifacts) | set(interfaces) | set(flows)
    impact_sources: set[str] = set()
    impacts = contract.get("changeImpacts")
    if not isinstance(impacts, list):
        errors.append({"code": "SYS-IMPACT-001", "message": "changeImpacts must be an array"})
        impacts = []
    for index, impact in enumerate(impacts):
        if not isinstance(impact, dict):
            errors.append({"code": "SYS-IMPACT-002", "message": f"changeImpacts[{index}] is not an object"})
            continue
        source = impact.get("sourceId")
        impact_sources.add(str(source))
        if source not in known_impact_ids:
            errors.append({"code": "SYS-IMPACT-003", "message": f"unknown change-impact source {source}"})
        for impacted in impact.get("impactedIds", []):
            if impacted not in known_impact_ids:
                errors.append({"code": "SYS-IMPACT-004", "message": f"change source {source} references unknown impacted id {impacted}"})
        for gate_id in impact.get("requiredRechecks", []):
            if gate_id not in gates:
                errors.append({"code": "SYS-IMPACT-005", "message": f"change source {source} references unknown recheck gate {gate_id}"})
    for interface_id in sorted(set(interfaces) - impact_sources):
        errors.append({"code": "SYS-IMPACT-006", "message": f"interface {interface_id} has no explicit change-impact rule"})

    for evidence_id, binding in evidence.items():
        value = binding.get("path")
        if not isinstance(value, str):
            errors.append({"code": "SYS-EVID-003", "message": f"evidence {evidence_id} has no relative path"})
            continue
        path = _safe_evidence_path(root, value)
        if path is None:
            errors.append({"code": "SYS-EVID-004", "message": f"evidence {evidence_id} path escapes the evidence root"})
            continue
        if not path.is_file():
            errors.append({"code": "SYS-EVID-005", "message": f"evidence {evidence_id} file is missing: {value}"})
            continue
        if path.stat().st_size != binding.get("size"):
            errors.append({"code": "SYS-EVID-006", "message": f"evidence {evidence_id} size mismatch"})
        if _sha256(path) != str(binding.get("sha256", "")).upper():
            errors.append({"code": "SYS-EVID-007", "message": f"evidence {evidence_id} sha256 mismatch"})

    open_gates = sorted(gate_id for gate_id, gate in gates.items() if gate.get("status") != "passed")
    authorizations = contract.get("authorizations", {})
    locks = contract.get("releaseLocks", {})
    production_authorized = authorizations.get("productionRelease") is True
    production_eligible = locks.get("productionReleaseEligible") is True
    if open_gates and (production_authorized or production_eligible):
        errors.append({"code": "SYS-RELEASE-001", "message": "open gates require production authorization and eligibility to remain false"})
    if production_authorized != production_eligible:
        errors.append({"code": "SYS-RELEASE-002", "message": "production authorization and release eligibility disagree"})
    if production_eligible and (
        locks.get("reviewOnly") is not False or
        locks.get("technicalReady") is not True or
        locks.get("physicalVerified") is not True
    ):
        errors.append({"code": "SYS-RELEASE-003", "message": "production eligibility requires reviewOnly=false and both technical/physical locks true"})
    if authorizations.get("prototypeBuild") is True and open_gates:
        warnings.append({"code": "SYS-PROTOTYPE-001", "message": "prototype build is authorized while gates remain open; preserve prototype marking and risk controls"})

    ok = not errors
    return {
        "schema": "aicad.system-engineering-qa-report.v1",
        "ok": ok,
        "systemId": contract.get("systemId"),
        "revision": contract.get("revision"),
        "summary": {
            "requirements": len(requirements),
            "subsystems": len(subsystems),
            "domains": len(domains),
            "artifacts": len(artifacts),
            "interfaces": len(interfaces),
            "flows": len(flows),
            "gates": len(gates),
            "openGates": open_gates,
            "evidenceBindings": len(evidence),
        },
        "systemContractReady": ok,
        "technicalReady": bool(locks.get("technicalReady")) if ok else False,
        "physicalVerified": bool(locks.get("physicalVerified")) if ok else False,
        "productionReleaseEligible": bool(production_eligible) if ok else False,
        "errors": errors,
        "warnings": warnings,
        "claimBoundary": "A pass proves contract consistency and bound-file integrity only; it does not replay domain tools, prove engineering adequacy, or grant manufacturing/production release.",
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AICAD system engineering QA",
        "",
        f"- Result: **{'PASS' if report['ok'] else 'FAIL'}**",
        f"- System: `{report.get('systemId')}` revision `{report.get('revision')}`",
        f"- Open gates: {', '.join(report['summary']['openGates']) or 'none'}",
        "",
        "## Errors",
        "",
    ]
    lines.extend(
        f"- `{item['code']}` {item['message']}" for item in report["errors"]
    )
    if not report["errors"]:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(
        f"- `{item['code']}` {item['message']}" for item in report["warnings"]
    )
    if not report["warnings"]:
        lines.append("- None")
    lines.extend(["", report["claimBoundary"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    contract_path = args.contract.resolve()
    root = (args.root or contract_path.parent).resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise SystemExit("contract root must be a JSON object")
    report = validate_contract(contract, root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(_markdown(report), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
