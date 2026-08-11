from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .engine import PlanError
from .engine3d import CompiledPlan3D, compile_plan3d
from .exporters3d import export_plan3d


SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


class SolidWorksHostError(PlanError):
    """Raised when the deterministic SolidWorks host rejects or cannot build a plan."""


def _module_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_solidworks_template() -> Path | None:
    configured = os.environ.get("AICAD_SOLIDWORKS_TEMPLATE")
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    candidates = [
        Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates\gb_part.prtdot"),
        Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates\Part.prtdot"),
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def find_solidworks_host() -> Path | None:
    configured = os.environ.get("AICAD_SOLIDWORKS_HOST")
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    root = _module_root()
    candidates = [
        root / "solidworks-host" / "AiCad.SolidWorksHost.exe",
        root / "build" / "solidworks-host" / "AiCad.SolidWorksHost.exe",
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def solidworks_doctor() -> dict[str, Any]:
    template = find_solidworks_template()
    host = find_solidworks_host()
    progid_registered = False
    revision = None
    executable = None
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID"):
                progid_registered = True
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\SolidWorks\SolidWorks 2026\Setup") as key:
                folder = Path(winreg.QueryValueEx(key, "SolidWorks Folder")[0])
                candidate = folder / "SLDWORKS.exe"
                executable = str(candidate.resolve()) if candidate.is_file() else None
                revision = "2026"
        except OSError:
            pass
    return {
        "ok": bool(template and host and progid_registered),
        "solidworks_registered": progid_registered,
        "solidworks_revision": revision,
        "solidworks_executable": executable,
        "template": str(template) if template else None,
        "host": str(host) if host else None,
    }


def _safe_name(value: str | None, fallback: str) -> str:
    name = SAFE_NAME.sub("-", (value or fallback).strip()).strip("-_")
    return name[:64] or "part"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _summary(plan: CompiledPlan3D) -> dict[str, Any]:
    return {
        "name": plan.name,
        "schema_version": "1.0",
        "source_sha256": plan.source_hash,
        "feature_count": len(plan.features),
        "features": [
            {
                "index": index,
                "id": feature.id,
                "type": feature.type,
                "depends_on": list(feature.depends_on),
                "support_feature": feature.support_feature,
                "expected_volume_delta_mm3": feature.expected_volume_delta,
                "expected_volume_after_mm3": feature.expected_volume_after,
            }
            for index, feature in enumerate(plan.features, 1)
        ],
        "expected_final_volume_mm3": plan.features[-1].expected_volume_after,
        "expected_final_bbox_mm": list(plan.features[-1].expected_bbox),
    }


def validate_3d_plan(data: dict[str, Any]) -> dict[str, Any]:
    plan = compile_plan3d(data)
    return {"ok": True, "valid": True, **_summary(plan)}


def compile_3d_plan(
    data: dict[str, Any],
    output_dir: Path,
    name: str | None = None,
    execute: bool = True,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    plan = compile_plan3d(data)
    stem = _safe_name(name, plan.name)
    output_dir = output_dir.expanduser().resolve()
    template = None
    host = None
    if execute:
        template = find_solidworks_template()
        if template is None:
            raise SolidWorksHostError("SolidWorks 2026 part template was not found")
        host = find_solidworks_host()
        if host is None:
            raise SolidWorksHostError("AiCad.SolidWorksHost.exe is not installed; run build-solidworks-host.ps1")
    paths = export_plan3d(plan, output_dir, stem, template)
    _write_json(paths["source"], data)
    result: dict[str, Any] = {
        "ok": True,
        "executed": False,
        **_summary(plan),
        "output_dir": str(output_dir),
        "plan": str(paths["source"].resolve()),
        "solidworks_plan": str(paths["execution"].resolve()),
        "audit": str(paths["audit"].resolve()),
        "manifest": str(paths["manifest"].resolve()),
        "sldprt": str(paths["sldprt"].resolve()),
        "step": str(paths["step"].resolve()),
        "solidworks_report": str(paths["host_report"].resolve()),
        "reopen_report": str(paths["reopen_report"].resolve()),
    }
    if not execute:
        result["host_requirements_deferred"] = True
        return result
    try:
        completed = subprocess.run(
            [str(host), str(paths["execution"]), str(paths["host_report"])],
            cwd=output_dir,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SolidWorksHostError(f"SolidWorks host timed out after {timeout_seconds} seconds") from exc
    stdout = completed.stdout.decode("utf-8", "replace").strip()
    stderr = completed.stderr.decode("utf-8", "replace").strip()
    report = None
    if paths["host_report"].is_file():
        try:
            report = json.loads(paths["host_report"].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            report = None
    if completed.returncode != 0 or not isinstance(report, dict) or report.get("status") != "passed":
        detail = stderr or stdout or (report.get("errors", ["unknown host failure"])[0] if isinstance(report, dict) else "no report")
        raise SolidWorksHostError(f"SolidWorks host rejected the feature transaction: {detail[:1000]}")
    for path in (paths["sldprt"], paths["step"]):
        if not path.is_file() or path.stat().st_size == 0:
            raise SolidWorksHostError(f"SolidWorks reported success but output is missing: {path}")
    paths["reopen_report"].unlink(missing_ok=True)
    try:
        reopened = subprocess.run(
            [str(host), "--inspect", str(paths["sldprt"]), str(paths["reopen_report"])],
            cwd=output_dir,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SolidWorksHostError(f"SolidWorks reopen verification timed out after {timeout_seconds} seconds") from exc
    reopen_report = None
    if paths["reopen_report"].is_file():
        try:
            reopen_report = json.loads(paths["reopen_report"].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            reopen_report = None
    if reopened.returncode != 0 or not isinstance(reopen_report, dict) or reopen_report.get("status") != "passed":
        detail = reopened.stderr.decode("utf-8", "replace").strip() or reopened.stdout.decode("utf-8", "replace").strip() or "no reopen report"
        raise SolidWorksHostError(f"Saved SLDPRT failed reopen verification: {detail[:1000]}")
    saved_native = [
        item
        for feature_report in report.get("features", [])
        for item in feature_report.get("native_topology", [])
        if isinstance(item, dict) and item.get("persistent_reference_resolved")
    ]
    reopened_native = [
        item for item in reopen_report.get("native_topology", [])
        if isinstance(item, dict)
    ]
    saved_keys = [str(item.get("reference_key")) for item in saved_native]
    reopened_keys = [str(item.get("reference_key")) for item in reopened_native]
    if not saved_keys or len(saved_keys) != len(set(saved_keys)):
        raise SolidWorksHostError("SolidWorks save report has no unique native topology catalog")
    if not reopened_keys or len(reopened_keys) != len(set(reopened_keys)):
        raise SolidWorksHostError("Reopened SLDPRT has no unique native topology catalog")
    if set(saved_keys) != set(reopened_keys):
        missing = sorted(set(saved_keys) - set(reopened_keys))
        unexpected = sorted(set(reopened_keys) - set(saved_keys))
        raise SolidWorksHostError(
            f"Reopened native topology catalog changed; missing={missing}, unexpected={unexpected}"
        )
    if int(reopen_report.get("required_native_topology_reference_count", 0)) <= 0:
        raise SolidWorksHostError("Reopened SLDPRT contains no required native topology references")
    if int(reopen_report.get("unresolved_required_native_topology_reference_count", -1)) != 0:
        raise SolidWorksHostError("Reopened SLDPRT contains unresolved required native topology references")
    unresolved = [item.get("reference_key") for item in reopened_native if not item.get("persistent_reference_resolved")]
    if unresolved:
        raise SolidWorksHostError(f"Reopened SLDPRT contains unresolved stored topology references: {unresolved}")
    required_saved = {item["reference_key"] for item in saved_native if item.get("required")}
    required_reopened = {item["reference_key"] for item in reopened_native if item.get("required")}
    if required_saved != required_reopened:
        raise SolidWorksHostError("Required native topology reference set changed after reopen")

    expected = plan.features[-1]
    actual = reopen_report.get("final_state") or {}
    actual_bbox = actual.get("bbox_mm")
    if actual.get("solid_body_count") != expected.expected_body_count or actual.get("body_fault_count") != 0:
        raise SolidWorksHostError("Saved SLDPRT changed body count or contains body faults after reopen")
    if abs(float(actual.get("volume_mm3", -1)) - expected.expected_volume_after) > max(0.5, abs(expected.expected_volume_after) * 1e-6):
        raise SolidWorksHostError("Saved SLDPRT volume changed after reopen")
    if not isinstance(actual_bbox, list) or len(actual_bbox) != 6 or any(abs(float(actual_bbox[index]) - expected.expected_bbox[index]) > max(0.01, plan.tolerance * 10) for index in range(6)):
        raise SolidWorksHostError("Saved SLDPRT bounding box changed after reopen")
    result["executed"] = True
    result["solidworks_revision"] = report.get("solidworks_revision")
    result["host_status"] = report.get("status")
    result["reopen_status"] = reopen_report.get("status")
    result["reopened_aicad_feature_count"] = reopen_report.get("aicad_feature_count")
    result["native_topology_authority"] = True
    result["native_topology_stability"] = "solidworks_persist_reference_save_reopen_verified"
    result["native_topology_reference_count"] = len(saved_native)
    result["required_native_topology_reference_count"] = len(required_saved)
    result["reopened_native_topology_reference_count"] = len(reopened_native)
    result["unresolved_required_native_topology_reference_count"] = 0
    result["native_topology_reference_keys"] = sorted(reopened_keys)
    result["actual_final_state"] = report.get("final_state")
    result["feature_transactions"] = [
        {
            "id": item.get("id"),
            "passed": item.get("passed"),
            "sketch_constraint_status": item.get("sketch_constraint_status"),
            "feature_error_code": item.get("feature_error_code"),
            "persistent_reference_resolved": item.get("persistent_reference_resolved"),
            "native_topology_reference_count": len(item.get("native_topology", [])),
            "required_native_topology_reference_count": sum(
                1 for reference in item.get("native_topology", []) if reference.get("required")
            ),
            "native_topology_reference_keys": [
                reference.get("reference_key") for reference in item.get("native_topology", [])
            ],
            "checks": item.get("checks"),
        }
        for item in report.get("features", [])
    ]
    evidence_files = {
        "sldprt": paths["sldprt"],
        "step": paths["step"],
        "solidworks_report": paths["host_report"],
        "reopen_report": paths["reopen_report"],
    }
    result["file_sha256"] = {name: _sha256(path) for name, path in evidence_files.items()}
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["native_host_validation"] = {
        "status": "passed",
        "solidworks_revision": report.get("solidworks_revision"),
        "host_protocol": report.get("protocol"),
        "reopen_protocol": reopen_report.get("protocol"),
        "native_topology_authority": True,
        "native_topology_stability": result["native_topology_stability"],
        "saved_reference_count": len(saved_native),
        "reopened_reference_count": len(reopened_native),
        "required_reference_count": len(required_saved),
        "unresolved_required_reference_count": 0,
        "reference_keys": sorted(reopened_keys),
        "file_sha256": result["file_sha256"],
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
    }
    _write_json(paths["manifest"], manifest)
    result["manifest_sha256"] = _sha256(paths["manifest"])
    with paths["audit"].open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "\n## Native SolidWorks topology save/reopen verification\n\n"
            f"- SolidWorks revision: `{report.get('solidworks_revision')}`\n"
            "- Native topology authority: `true`\n"
            f"- Stored and reopened references: `{len(reopened_native)}`\n"
            f"- Required sketch references: `{len(required_saved)}`\n"
            "- Unresolved required references: `0`\n"
            "- Exact saved/reopened semantic-key set equality: `PASS`\n"
            "- Body/volume/bounding-box reopen checks: `PASS`\n"
            "- Safety locks: `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`\n"
        )
    result["audit_sha256"] = _sha256(paths["audit"])
    return result
