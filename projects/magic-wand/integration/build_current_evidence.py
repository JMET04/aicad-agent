from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


INTEGRATION = Path(__file__).resolve().parent
MAGIC_WAND = INTEGRATION.parent
REPO_ROOT = MAGIC_WAND.parents[1]

TRACE_PATH = INTEGRATION / "current-system-traceability.json"
MANIFEST_PATH = INTEGRATION / "current-delivery-manifest.json"

SYSTEM_REQUIREMENTS_REL = "projects/magic-wand/system-requirements.json"
STATUS_REL = "projects/magic-wand/integration/CURRENT_SYSTEM_STATUS.json"
CONTRACT_REL = "projects/magic-wand/integration/system-design-contract.json"
QA_REL = "projects/magic-wand/integration/system-design-qa-report.json"

REQUIREMENT_MAP: dict[str, dict[str, list[str]]] = {
    "SYS-001": {
        "contractRequirementIds": ["FIT-001", "PHYSICAL-001"],
        "gateIds": ["GATE-MECH-TOOL-001", "GATE-FIRST-ARTICLE-001"],
    },
    "SYS-002": {
        "contractRequirementIds": ["GESTURE-001", "TARGET-001", "RECEIVER-001"],
        "gateIds": ["GATE-FW-HOST-001", "GATE-RECEIVER-FW-HOST-001", "GATE-TARGET-FW-001", "GATE-RECEIVER-001"],
    },
    "SYS-003": {
        "contractRequirementIds": ["TARGET-001", "RECEIVER-001"],
        "gateIds": ["GATE-RECEIVER-FW-HOST-001", "GATE-TARGET-FW-001", "GATE-RECEIVER-001"],
    },
    "SYS-004": {
        "contractRequirementIds": ["GESTURE-001", "TARGET-001"],
        "gateIds": ["GATE-FW-HOST-001", "GATE-TARGET-FW-001"],
    },
    "SYS-005": {
        "contractRequirementIds": ["GESTURE-001", "RECEIVER-001"],
        "gateIds": ["GATE-FW-HOST-001", "GATE-RECEIVER-FW-HOST-001", "GATE-TARGET-FW-001", "GATE-RECEIVER-001"],
    },
    "SYS-006": {
        "contractRequirementIds": ["POWER-001", "PHYSICAL-001"],
        "gateIds": ["GATE-MECH-TOOL-001", "GATE-FIRST-ARTICLE-001"],
    },
    "SYS-007": {
        "contractRequirementIds": ["RF-001", "PHYSICAL-001"],
        "gateIds": ["GATE-MECH-TOOL-001", "GATE-FIRST-ARTICLE-001", "GATE-TARGET-FW-001"],
    },
    "SYS-008": {
        "contractRequirementIds": ["RECEIVER-001", "RECEIVER-PCB-001"],
        "gateIds": ["GATE-RECEIVER-FW-HOST-001", "GATE-RECEIVER-PCB-001", "GATE-RECEIVER-001"],
    },
    "SYS-009": {
        "contractRequirementIds": ["RECEIVER-001", "PRODUCTION-001"],
        "gateIds": ["GATE-RECEIVER-FW-HOST-001", "GATE-RECEIVER-001", "GATE-PRODUCTION-001"],
    },
    "SYS-010": {
        "contractRequirementIds": ["RECEIVER-001", "PRODUCTION-001"],
        "gateIds": ["GATE-RECEIVER-FW-HOST-001", "GATE-RECEIVER-001", "GATE-PRODUCTION-001"],
    },
    "SYS-011": {
        "contractRequirementIds": ["HAPTIC-001", "PHYSICAL-001", "TARGET-001"],
        "gateIds": ["GATE-MECH-TOOL-001", "GATE-FIRST-ARTICLE-001", "GATE-TARGET-FW-001"],
    },
    "SYS-012": {
        "contractRequirementIds": ["FAB-001", "RECEIVER-PCB-001", "PCBA-001", "PRODUCTION-001"],
        "gateIds": ["GATE-JLC-BARE-001", "GATE-RECEIVER-PCB-001", "GATE-PCBA-001", "GATE-PRODUCTION-001"],
    },
}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _portable_path(relative: str, *, require_exists: bool = True) -> Path:
    if "\\" in relative or ":" in relative:
        raise RuntimeError(f"non-portable path: {relative}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"unsafe path: {relative}")
    path = REPO_ROOT.joinpath(*pure.parts)
    if require_exists and not path.is_file():
        raise RuntimeError(f"missing current evidence file: {relative}")
    return path


def _file_record(relative: str, role: str, kind: str, data: bytes | None = None) -> dict[str, Any]:
    path = _portable_path(relative, require_exists=data is None)
    payload = path.read_bytes() if data is None else data
    return {
        "path": relative,
        "size": len(payload),
        "sha256": _sha256(payload),
        "role": role,
        "kind": kind,
    }


def _render(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_trace() -> dict[str, Any]:
    system = _load_object(REPO_ROOT / SYSTEM_REQUIREMENTS_REL)
    contract = _load_object(REPO_ROOT / CONTRACT_REL)
    status = _load_object(REPO_ROOT / STATUS_REL)
    qa = _load_object(REPO_ROOT / QA_REL)

    source_rows = system.get("requirements")
    contract_rows = contract.get("requirements")
    gate_rows = contract.get("verificationGates")
    evidence_rows = contract.get("evidenceBindings")
    if not all(isinstance(rows, list) for rows in (source_rows, contract_rows, gate_rows, evidence_rows)):
        raise RuntimeError("current authority inventory is malformed")

    sources = {row["id"]: row for row in source_rows}
    requirements = {row["id"]: row for row in contract_rows}
    gates = {row["id"]: row for row in gate_rows}
    evidence = {row["id"]: row for row in evidence_rows}
    expected_ids = {f"SYS-{index:03d}" for index in range(1, 13)}
    if set(sources) != expected_ids or set(REQUIREMENT_MAP) != expected_ids:
        raise RuntimeError("SYS-001..012 mapping is not exact")
    if system.get("revision") != "B" or system.get("authoritativeStatus") != "integration/CURRENT_SYSTEM_STATUS.json":
        raise RuntimeError("system requirements are not current Rev B authority")
    if qa.get("ok") is not True or qa.get("revision") != contract.get("revision"):
        raise RuntimeError("current system QA is not a passing report for this contract")

    traced: list[dict[str, Any]] = []
    for requirement_id in sorted(sources):
        source = sources[requirement_id]
        mapping = REQUIREMENT_MAP[requirement_id]
        mapped_requirements = mapping["contractRequirementIds"]
        mapped_gates = mapping["gateIds"]
        missing_requirements = sorted(set(mapped_requirements) - set(requirements))
        missing_gates = sorted(set(mapped_gates) - set(gates))
        if missing_requirements or missing_gates:
            raise RuntimeError(
                f"invalid current trace {requirement_id}: requirements={missing_requirements}, gates={missing_gates}"
            )
        gate_statuses = {gate_id: gates[gate_id]["status"] for gate_id in mapped_gates}
        evidence_ids = sorted(
            {
                evidence_id
                for gate_id in mapped_gates
                for evidence_id in gates[gate_id].get("evidenceIds", [])
            }
        )
        unknown_evidence = sorted(set(evidence_ids) - set(evidence))
        if unknown_evidence:
            raise RuntimeError(f"unknown evidence in {requirement_id}: {unknown_evidence}")
        traced.append(
            {
                "id": requirement_id,
                "category": source["category"],
                "requirement": source["requirement"],
                "acceptance": source["acceptance"],
                "verification": source["verification"],
                "sourceStatus": source["status"],
                "contractRequirementIds": mapped_requirements,
                "gateIds": mapped_gates,
                "gateStatuses": gate_statuses,
                "verificationClosed": all(value == "passed" for value in gate_statuses.values()),
                "evidenceIds": evidence_ids,
                "evidencePaths": [evidence[evidence_id]["path"] for evidence_id in evidence_ids],
            }
        )

    open_ids = [row["id"] for row in traced if not row["verificationClosed"]]
    return {
        "schema": "magic-wand.current-system-traceability.v1",
        "projectId": system["projectId"],
        "systemRequirementsRevision": system["revision"],
        "systemContractRevision": contract["revision"],
        "status": "MAPPED_WITH_OPEN_VERIFICATION_GATES",
        "authorityPaths": {
            "systemRequirements": SYSTEM_REQUIREMENTS_REL,
            "currentStatus": STATUS_REL,
            "systemContract": CONTRACT_REL,
            "systemQa": QA_REL,
        },
        "coverage": {
            "required": len(expected_ids),
            "mapped": len(traced),
            "missing": [],
            "verificationOpen": open_ids,
        },
        "requirements": traced,
        "openReleaseGates": qa["summary"]["openGates"],
        "releaseLocks": status["releaseLocks"],
        "claimBoundary": qa["claimBoundary"],
    }


def build_manifest(trace_bytes: bytes) -> dict[str, Any]:
    system = _load_object(REPO_ROOT / SYSTEM_REQUIREMENTS_REL)
    status = _load_object(REPO_ROOT / STATUS_REL)
    contract = _load_object(REPO_ROOT / CONTRACT_REL)
    qa = _load_object(REPO_ROOT / QA_REL)

    source_specs = (
        ("projects/magic-wand/README.md", "entry", "current_project_entry"),
        ("projects/magic-wand/integration/README.md", "entry", "current_integration_index"),
        (SYSTEM_REQUIREMENTS_REL, "authority", "system_requirements"),
        (STATUS_REL, "authority", "current_system_status"),
        (CONTRACT_REL, "authority", "system_engineering_contract"),
        (QA_REL, "report", "system_engineering_qa"),
        ("projects/magic-wand/integration/system-design-qa-report.md", "report", "human_system_qa"),
        ("projects/magic-wand/integration/SYSTEM_ENGINEERING_HANDOFF.md", "handoff", "current_handoff"),
        ("projects/magic-wand/integration/RECEIVER_EFFECTS_SYSTEM_HANDOFF.md", "handoff", "receiver_effects_handoff"),
        ("projects/magic-wand/integration/current-system-traceability.json", "trace", "source_faithful_trace"),
        ("projects/magic-wand/integration/build_current_evidence.py", "builder", "deterministic_builder"),
    )
    source_files = [
        _file_record(relative, role, kind, trace_bytes if role == "trace" else None)
        for relative, role, kind in source_specs
    ]

    evidence_files: list[dict[str, Any]] = []
    for row in contract["evidenceBindings"]:
        record = _file_record(row["path"], "evidence", "tool_verified_artifact")
        if record["size"] != row["size"] or record["sha256"] != row["sha256"].upper():
            raise RuntimeError(f"contract evidence is stale: {row['id']}")
        record.update(
            {
                "evidenceId": row["id"],
                "level": row["level"],
                "toolVersion": row["toolVersion"],
            }
        )
        evidence_files.append(record)

    paths = [row["path"].casefold() for row in [*source_files, *evidence_files]]
    if len(paths) != len(set(paths)):
        raise RuntimeError("current delivery manifest has duplicate paths")
    return {
        "schema": "magic-wand.current-delivery-manifest.v1",
        "projectId": system["projectId"],
        "systemRequirementsRevision": system["revision"],
        "systemContractRevision": contract["revision"],
        "sourceFiles": source_files,
        "evidenceFiles": evidence_files,
        "counts": {
            "sourceFiles": len(source_files),
            "evidenceFiles": len(evidence_files),
            "totalBoundFiles": len(source_files) + len(evidence_files),
        },
        "readiness": {
            "systemContractReady": qa["systemContractReady"],
            "technicalReady": qa["technicalReady"],
            "physicalVerified": qa["physicalVerified"],
            "productionReleaseEligible": qa["productionReleaseEligible"],
        },
        "ownerAuthorizations": status["ownerAuthorizations"],
        "releaseLocks": status["releaseLocks"],
        "openReleaseGates": qa["summary"]["openGates"],
        "selfHashPolicy": {
            "currentDeliveryManifestExcluded": True,
            "reason": "the manifest cannot contain its own stable digest",
        },
        "claimBoundary": qa["claimBoundary"],
    }


def generate(*, check: bool) -> list[str]:
    trace_bytes = _render(build_trace())
    manifest_bytes = _render(build_manifest(trace_bytes))
    expected = ((TRACE_PATH, trace_bytes), (MANIFEST_PATH, manifest_bytes))
    stale: list[str] = []
    for path, payload in expected:
        if check:
            if not path.is_file() or path.read_bytes() != payload:
                stale.append(path.relative_to(REPO_ROOT).as_posix())
        else:
            path.write_bytes(payload)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = generate(check=args.check)
    print(json.dumps({"ok": not stale, "stale": stale}, ensure_ascii=False))
    return 0 if not stale else 2


if __name__ == "__main__":
    raise SystemExit(main())
