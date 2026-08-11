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
SCHEMA_PATH = ROOT / "rules" / "production_readiness_contract_v2.schema.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve(path_value: str, base_dir: Path) -> Path:
    candidate = Path(path_value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()


def _pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _artifact_set_sha(rows: list[dict[str, Any]]) -> str:
    portable = [
        {"kind": row["kind"], "sha256": row["actualSha256"], "sizeBytes": row["sizeBytes"]}
        for row in sorted(rows, key=lambda item: (item["kind"], item["path"]))
    ]
    encoded = json.dumps(portable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_artifacts(contract: dict[str, Any], base_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    rows: list[dict[str, Any]] = []
    for item in contract["candidateArtifacts"]:
        path = _resolve(item["path"], base_dir)
        exists = path.is_file()
        actual = _sha256(path) if exists else None
        size = path.stat().st_size if exists else None
        rows.append({
            "kind": item["kind"], "path": str(path), "exists": exists, "sizeBytes": size,
            "declaredSha256": item["sha256"].lower(), "actualSha256": actual,
            "pass": exists and actual == item["sha256"].lower(),
        })
    return rows, _artifact_set_sha(rows) if rows and all(row["pass"] for row in rows) else None


def _verify_evidence(reference: dict[str, Any], group: str, base_dir: Path, artifact_set_sha: str | None) -> tuple[bool, dict[str, Any]]:
    path = _resolve(reference["path"], base_dir)
    exists = path.is_file()
    actual_hash = _sha256(path) if exists else None
    result: dict[str, Any] = {
        "kind": reference["kind"], "path": str(path), "exists": exists,
        "declaredSha256": reference["sha256"].lower(), "actualSha256": actual_hash,
        "hashPass": exists and actual_hash == reference["sha256"].lower(),
    }
    if not result["hashPass"]:
        result["reason"] = "evidence_file_missing_or_hash_mismatch"
        return False, result

    kind = reference["kind"]
    expected_kind = "authority_document" if group == "authority" else "professional_release" if group == "professionalRelease" else "machine_report"
    result["expectedKind"] = expected_kind
    result["kindPass"] = kind == expected_kind
    if not result["kindPass"]:
        result["reason"] = "evidence_kind_does_not_match_gate_group"
        return False, result

    if kind == "machine_report":
        pointer = reference.get("jsonPointer")
        if not pointer or "expectedValue" not in reference:
            result["reason"] = "machine_report_requires_json_pointer_and_expected_value"
            return False, result
        try:
            document = _load(path)
            actual_value = _pointer(document, pointer)
        except Exception as exc:
            result["reason"] = "machine_report_read_or_pointer_failure"
            result["error"] = str(exc)
            return False, result
        result.update({"jsonPointer": pointer, "expectedValue": reference["expectedValue"], "actualValue": actual_value, "valuePass": actual_value == reference["expectedValue"]})
        if not result["valuePass"]:
            result["reason"] = "machine_report_value_mismatch"
            return False, result
        if group == "host":
            artifact_pointer = reference.get("artifactSetPointer")
            if not artifact_pointer or not artifact_set_sha:
                result["reason"] = "host_report_requires_verified_artifact_set_binding"
                return False, result
            try:
                reported_set = _pointer(document, artifact_pointer)
            except Exception as exc:
                result["reason"] = "host_artifact_set_pointer_failure"
                result["error"] = str(exc)
                return False, result
            result.update({"artifactSetPointer": artifact_pointer, "reportedArtifactSetSha256": reported_set, "actualArtifactSetSha256": artifact_set_sha, "artifactSetPass": str(reported_set).lower() == artifact_set_sha})
            if not result["artifactSetPass"]:
                result["reason"] = "host_report_artifact_set_mismatch"
                return False, result
        return True, result

    if kind == "authority_document":
        required = ("issuer", "scope", "issuedAt")
        missing = [key for key in required if not str(reference.get(key, "")).strip()]
        result.update({"issuer": reference.get("issuer"), "scope": reference.get("scope"), "issuedAt": reference.get("issuedAt"), "missingMetadata": missing})
        if missing:
            result["reason"] = "authority_metadata_incomplete"
            return False, result
        return True, result

    required = ("signer", "credential", "scope", "subjectArtifactSetSha256")
    missing = [key for key in required if not str(reference.get(key, "")).strip()]
    result.update({"signer": reference.get("signer"), "credential": reference.get("credential"), "scope": reference.get("scope"), "missingMetadata": missing})
    if missing or not artifact_set_sha:
        result["reason"] = "professional_release_metadata_or_artifact_set_missing"
        return False, result
    result["subjectArtifactSetSha256"] = reference["subjectArtifactSetSha256"].lower()
    result["actualArtifactSetSha256"] = artifact_set_sha
    result["artifactSetPass"] = result["subjectArtifactSetSha256"] == artifact_set_sha
    if not result["artifactSetPass"]:
        result["reason"] = "professional_release_artifact_set_mismatch"
        return False, result
    return True, result


def evaluate(contract: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    base_dir = (base_dir or Path.cwd()).resolve()
    schema = _load(SCHEMA_PATH)
    rules = _load(RULES_PATH)
    jsonschema.Draft202012Validator(schema).validate(contract)
    profile_name = f"{contract['discipline']}ProductionProfile"
    profile = rules.get(profile_name)
    if not isinstance(profile, dict):
        raise ValueError(f"no production profile is defined for discipline: {contract['discipline']}")

    artifact_rows, artifact_set_sha = _verify_artifacts(contract, base_dir)
    gate_results: dict[str, dict[str, Any]] = {
        "artifacts.hashAndExistence": {
            "status": "pass" if artifact_set_sha else "fail",
            "evidence": artifact_rows,
        }
    }
    for group, names in profile.items():
        for name in names:
            record = contract.get("evidence", {}).get(group, {}).get(name)
            if not isinstance(record, dict):
                gate_results[f"{group}.{name}"] = {"status": "fail", "evidence": {"reason": "missing_required_gate"}}
                continue
            passed, evidence = _verify_evidence(record["evidenceRef"], group, base_dir, artifact_set_sha)
            gate_results[f"{group}.{name}"] = {"status": "pass" if passed else "fail", "evidence": evidence}

    failed = [name for name, row in gate_results.items() if row["status"] != "pass"]
    passed = not failed
    lessons = [] if passed else [{
        "ruleId": "PROD-G009",
        "symptom": f"{len(failed)} 个生产门禁没有可验证的文件证据或工件绑定。",
        "rootCause": "旧契约接受 passed=true 和任意字符串，无法证明机器报告、宿主重开或专业放行确实属于当前工件集合。",
        "correction": "为每个门禁提供真实路径和 SHA-256；机器报告使用 JSON Pointer 读值，宿主与专业放行绑定 artifact-set SHA-256。",
        "preventionRule": "PROD-G009：生产结论不得接受自报布尔值，必须从哈希固定的外部证据读取并绑定同一工件集合。",
        "failedGates": failed,
    }]
    return {
        "schema": "aicad_production_readiness_validation_v2",
        "status": "pass" if passed else "blocked_for_production",
        "project": contract["project"],
        "requestedStage": "production",
        "discipline": contract["discipline"],
        "strictProductionOnly": True,
        "deliveryDisposition": "production_release_candidate" if passed else "blocker_report_only",
        "productionArtifactAllowed": passed,
        "automaticAcceptanceAllowed": False,
        "artifactSetSha256": artifact_set_sha,
        "gateResults": gate_results,
        "failedGates": failed,
        "candidateArtifacts": contract["candidateArtifacts"],
        "exposedArtifacts": contract["candidateArtifacts"] if passed else [],
        "rootCauseLessons": lessons,
        "rules": {"path": str(RULES_PATH), "sha256": _sha256(RULES_PATH)},
        "contractSchema": {"path": str(SCHEMA_PATH), "sha256": _sha256(SCHEMA_PATH)},
        "safetyLocks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


def render_markdown(result: dict[str, Any]) -> str:
    rows = [
        "# AICAD 生产就绪证据门禁", "", f"- 判定：**{result['status']}**",
        f"- 交付处置：`{result['deliveryDisposition']}`", f"- 允许暴露生产工件：`{str(result['productionArtifactAllowed']).lower()}`",
        f"- 工件集 SHA-256：`{result.get('artifactSetSha256') or 'unavailable'}`", "", "## 证据绑定结果", "", "| 门禁 | 结果 |", "|---|---|",
    ]
    rows.extend(f"| `{name}` | `{record['status']}` |" for name, record in result["gateResults"].items())
    if result["failedGates"]:
        rows.extend(["", "## 阻断项", "", *[f"- `{name}`" for name in result["failedGates"]]])
    rows.extend(["", "插件不会自签或自动验收；安全锁保持 reviewOnly=true、accepted=false、ruleEnabled=false、packagingGated=true。"])
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate evidence-bound, strict production-only AICAD readiness.")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--png", type=Path)
    args = parser.parse_args()
    contract_path = args.contract.resolve()
    contract = _load(contract_path)
    result = evaluate(contract, contract_path.parent)
    output = args.output or contract_path.with_suffix(".production-validation-v2.json")
    markdown = args.markdown or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(result), encoding="utf-8-sig")
    if args.html or args.png:
        from aicad_review_report import write_html, write_png
        if args.html:
            write_html(result, args.html, "AICAD 生产就绪证据审核")
        if args.png:
            write_png(result, args.png, "AICAD 生产就绪证据审核")
    print(json.dumps({"ok": result["status"] == "pass", "status": result["status"], "deliveryDisposition": result["deliveryDisposition"], "output": str(output.resolve()), "markdown": str(markdown.resolve()), "html": str(args.html.resolve()) if args.html else None, "png": str(args.png.resolve()) if args.png else None}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
