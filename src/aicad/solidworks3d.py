from __future__ import annotations

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
    template = find_solidworks_template()
    if template is None:
        raise SolidWorksHostError("SolidWorks 2026 part template was not found")
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
        return result
    host = find_solidworks_host()
    if host is None:
        raise SolidWorksHostError("AiCad.SolidWorksHost.exe is not installed; run build-solidworks-host.ps1")
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
    result["actual_final_state"] = report.get("final_state")
    result["feature_transactions"] = [
        {
            "id": item.get("id"),
            "passed": item.get("passed"),
            "sketch_constraint_status": item.get("sketch_constraint_status"),
            "feature_error_code": item.get("feature_error_code"),
            "persistent_reference_resolved": item.get("persistent_reference_resolved"),
            "checks": item.get("checks"),
        }
        for item in report.get("features", [])
    ]
    return result
