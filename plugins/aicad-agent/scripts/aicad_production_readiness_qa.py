#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "rules" / "production_readiness_rules.json"
SCHEMA_PATH = ROOT / "rules" / "production_readiness_contract.schema.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _gate(contract: dict[str, Any], group: str, name: str) -> tuple[bool, Any]:
    record = contract.get("evidence", {}).get(group, {}).get(name)
    if not isinstance(record, dict):
        return False, {"reason": "missing_required_gate", "group": group, "name": name}
    evidence = record.get("evidence")
    return record.get("passed") is True and evidence not in (None, ""), evidence


def evaluate(contract: dict[str, Any]) -> dict[str, Any]:
    schema = _load(SCHEMA_PATH)
    rules = _load(RULES_PATH)
    jsonschema.Draft202012Validator(schema).validate(contract)

    requested_stage = contract["requestedStage"]
    discipline = contract["discipline"]
    strict = contract["strictProductionOnly"]
    profile_name = f"{discipline}ProductionProfile"
    profile = rules.get(profile_name)
    if requested_stage == "production" and not isinstance(profile, dict):
        raise ValueError(f"no production profile is defined for discipline: {discipline}")

    gate_results: dict[str, dict[str, Any]] = {}
    if requested_stage == "production":
        for group, names in profile.items():
            for name in names:
                passed, evidence = _gate(contract, group, name)
                gate_results[f"{group}.{name}"] = {"status": "pass" if passed else "fail", "evidence": evidence}
    else:
        for group, records in contract["evidence"].items():
            for name, record in records.items():
                passed = isinstance(record, dict) and record.get("passed") is True
                gate_results[f"{group}.{name}"] = {"status": "pass" if passed else "advisory_fail", "evidence": record.get("evidence") if isinstance(record, dict) else None}

    artifact_evidence = []
    for item in contract.get("candidateArtifacts", []):
        candidate = Path(item["path"]).expanduser()
        exists = candidate.is_file()
        actual_hash = _sha256(candidate) if exists else None
        artifact_evidence.append({
            "kind": item["kind"], "path": str(candidate), "exists": exists,
            "declaredSha256": item["sha256"].lower(), "actualSha256": actual_hash,
            "pass": exists and actual_hash == item["sha256"].lower(),
        })
    if requested_stage == "production":
        artifacts_pass = bool(artifact_evidence) and all(item["pass"] for item in artifact_evidence)
        gate_results["artifacts.hashAndExistence"] = {"status": "pass" if artifacts_pass else "fail", "evidence": artifact_evidence}

    failed = [name for name, result in gate_results.items() if result["status"] == "fail"]
    if requested_stage == "production" and failed:
        status = "blocked_for_production"
        disposition = "blocker_report_only" if strict else "review_candidate"
    elif requested_stage == "production":
        status = "pass"
        disposition = "production_release_candidate"
    else:
        status = "pass"
        disposition = "review_candidate"

    lessons = []
    if failed:
        lessons.append({
            "ruleId": "PROD-G001",
            "symptom": f"{len(failed)} required production gates are missing or failed.",
            "rootCause": "The requested production label is stronger than the available authoritative evidence.",
            "correction": "Supply and hash the missing evidence, regenerate affected geometry/sheets, and rerun this non-compensatory gate.",
            "preventionRule": "PROD-G001: strict production requests expose blocker reports only until every required gate passes.",
            "failedGates": failed,
        })

    artifacts = contract.get("candidateArtifacts", [])
    exposed_artifacts = artifacts if disposition in {"review_candidate", "production_release_candidate"} else []
    return {
        "schema": "aicad_production_readiness_validation_v1",
        "status": status,
        "project": contract["project"],
        "requestedStage": requested_stage,
        "discipline": discipline,
        "strictProductionOnly": strict,
        "deliveryDisposition": disposition,
        "productionArtifactAllowed": disposition == "production_release_candidate",
        "automaticAcceptanceAllowed": False,
        "gateResults": gate_results,
        "failedGates": failed,
        "candidateArtifacts": artifacts,
        "exposedArtifacts": exposed_artifacts,
        "rootCauseLessons": lessons,
        "rules": {"path": str(RULES_PATH), "sha256": _sha256(RULES_PATH)},
        "contractSchema": {"path": str(SCHEMA_PATH), "sha256": _sha256(SCHEMA_PATH)},
        "safetyLocks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def render_markdown(result: dict[str, Any]) -> str:
    rows = [
        "# AICAD 生产就绪门禁报告",
        "",
        f"- 判定：**{result['status']}**",
        f"- 交付处置：`{result['deliveryDisposition']}`",
        f"- 生产工件允许暴露：`{str(result['productionArtifactAllowed']).lower()}`",
        "- 自动验收：`false`",
        "",
        "## 非补偿门禁",
        "",
        "| 门禁 | 结果 |",
        "|---|---|",
    ]
    for name, record in result["gateResults"].items():
        rows.append(f"| `{name}` | `{record['status']}` |")
    if result["failedGates"]:
        rows.extend(["", "## 阻断项", "", *[f"- `{name}`" for name in result["failedGates"]]])
    rows.extend([
        "",
        "## 边界",
        "",
        "插件只证明候选文件和证据合同通过机器门禁；它不替代法定审查、注册专业人员签章或制造方放行。",
    ])
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a fail-closed AICAD production-readiness contract.")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    contract = _load(args.contract.resolve())
    result = evaluate(contract)
    output = args.output or args.contract.with_suffix(".production-validation.json")
    markdown = args.markdown or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(result), encoding="utf-8-sig")
    print(json.dumps({"ok": result["status"] == "pass", "status": result["status"], "deliveryDisposition": result["deliveryDisposition"], "output": str(output.resolve()), "markdown": str(markdown.resolve())}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
