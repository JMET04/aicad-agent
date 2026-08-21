from __future__ import annotations

"""Authoritative SolidWorks conversion and reopen verification.

The script owns the COM instance it creates, records honest failures, and never
substitutes a renamed neutral file for native SLDPRT/SLDASM output.
"""

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import pythoncom
import win32com.client
from build123d import export_brep, export_step, import_step
from win32com.client import VARIANT
from win32com.client.gencache import EnsureDispatch
from win32com.client import constants

import factory_release_geometry as geometry


SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT = 1
SW_SAVE_SILENT = 1
SW_SAVE_REFERENCED = 4
REVISION = geometry.P["revision"]
SW_PREF_ENABLE_3D_INTERCONNECT = 691
SW_PREF_DEFAULT_ASSEMBLY_TEMPLATE = 9

ASSEMBLIES: dict[str, dict[str, Any]] = {
    "MW-A-001": {
        "basename": "MW-A-001_magic_wand_assembly",
        "parts": geometry.WAND_PART_NUMBERS,
        "placements": {
            part_id: tuple(geometry.ASSEMBLY_PLACEMENTS[part_id].position)
            for part_id in geometry.WAND_PART_NUMBERS
        },
    },
    "MW-A-101": {
        "basename": "MW-A-101_receiver_enclosure_assembly",
        "parts": geometry.RECEIVER_PART_NUMBERS,
        "placements": {
            "MW-M-101": (0.0, 0.0, 0.0),
            "MW-M-102": (
                0.0,
                0.0,
                float(
                    geometry.P["interfaces"]["receiver_enclosure"]["case"][
                        "lid_assembly_z"
                    ]
                ),
            ),
        },
    },
}

OPEN_WARNING_NAMES = {
    32: "swFileLoadWarning_NeedsRegen",
}
SUPPRESSION_STATE_NAMES = {
    0: "swComponentSuppressed", 1: "swComponentLightweight",
    2: "swComponentFullyResolved", 3: "swComponentResolved",
    4: "swComponentFullyLightweight", 5: "swComponentInternalIdMismatch",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _value(obj: Any, name: str) -> Any:
    value = getattr(obj, name)
    return value() if callable(value) else value


def _delete_exact(path: Path) -> None:
    if path.exists() and path.is_file():
        path.unlink()


def _json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _native_tool(sw: Any) -> dict[str, Any]:
    return {
        "name": "Dassault Systemes SOLIDWORKS Premium",
        "version": str(_value(sw, "RevisionNumber")),
        "nativeExecution": True,
        "api": "SOLIDWORKS COM API / OpenDoc7 / SaveAs3",
        "automation": "owned DispatchEx COM instance",
        "neutralImportMode": "embedded imported solid; 3D Interconnect external links disabled",
    }


def _warning_names(code: int) -> list[str]:
    names: list[str] = []
    remaining = int(code)
    for bit, name in OPEN_WARNING_NAMES.items():
        if remaining & bit:
            names.append(name)
            remaining &= ~bit
    if remaining:
        names.append(f"UNMAPPED_WARNING_BITS_0x{remaining:X}")
    return names


def _open_native(sw: Any, path: Path, document_type: int) -> tuple[Any, dict[str, Any]]:
    spec = sw.GetOpenDocSpec(str(path.resolve()))
    spec.DocumentType = document_type
    spec.Silent = True
    spec.ReadOnly = False
    model = sw.OpenDoc7(spec)
    detail = {
        "errorCode": int(spec.Error),
        "warningCode": int(spec.Warning),
        "warningNames": _warning_names(int(spec.Warning)),
    }
    if model is None or detail["errorCode"] != 0:
        raise RuntimeError(f"SolidWorks OpenDoc7 failed for {path}: {detail}")
    return model, detail


def _close(sw: Any, model: Any | None) -> None:
    if model is None:
        return
    try:
        sw.CloseDoc(str(_value(model, "GetTitle")))
    except Exception:
        pass


def _bbox_mm(values: Any) -> list[float]:
    return [round(float(value) * 1000.0, 6) for value in values]


def _source_metrics(shape: Any) -> dict[str, Any]:
    bbox = shape.bounding_box(optimal=True)
    return {
        "valid": bool(shape.is_valid),
        "solidCount": len(shape.solids()),
        "volumeMm3": round(sum(float(s.volume) for s in shape.solids()), 6),
        "bboxMm": [
            round(float(bbox.min.X), 6),
            round(float(bbox.min.Y), 6),
            round(float(bbox.min.Z), 6),
            round(float(bbox.max.X), 6),
            round(float(bbox.max.Y), 6),
            round(float(bbox.max.Z), 6),
        ],
    }


def _final_step_metrics(path: Path) -> dict[str, Any]:
    return _source_metrics(import_step(path))


def _assembly_template(sw: Any) -> Path:
    """Resolve the host-configured template without publishing a machine path."""
    configured = str(sw.GetUserPreferenceStringValue(SW_PREF_DEFAULT_ASSEMBLY_TEMPLATE)).strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
    program_data = os.environ.get("ProgramData", "").strip()
    if program_data:
        root = Path(program_data) / "SolidWorks"
        candidates = sorted(root.glob("SOLIDWORKS */templates/*.asmdot"))
        preferred = [path for path in candidates if path.name.lower() == "gb_assembly.asmdot"]
        if preferred:
            return preferred[-1]
        if candidates:
            return candidates[-1]
    raise RuntimeError("SolidWorks assembly template discovery returned no usable .asmdot")


def export_part(sw: Any, root: Path, part_id: str, native_tool: dict[str, Any]) -> dict[str, Any]:
    output_dir = root / "outputs" / "3d"
    report_path = root / "reports" / "native" / f"{part_id}_solidworks-execution.json"
    basename = geometry.PART_BASENAMES[part_id]
    source_step = output_dir / f"_{basename}_native-input.step"
    source_brep = root / "reports" / "geometry" / f"{basename}.brep"
    native_path = output_dir / f"{basename}.SLDPRT"
    final_step = output_dir / f"{basename}.step"
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in (source_step, native_path, final_step):
        _delete_exact(path)

    report: dict[str, Any] = {
        "schema": "aicad_solidworks_native_execution_raw_v1",
        "subjectId": part_id,
        "revision": REVISION,
        "operation": "STEP import -> native SLDPRT save -> native reopen -> STEP export",
        "status": "fail",
        "nativeTool": native_tool,
        "paths": {
            "nativeCad": native_path.relative_to(root).as_posix(),
            "step": final_step.relative_to(root).as_posix(),
        },
        "checks": [],
    }
    imported = None
    reopened = None
    try:
        shape = geometry.make_part(part_id)
        source_metrics = _source_metrics(shape)
        if not source_metrics["valid"] or source_metrics["solidCount"] != 1:
            raise RuntimeError(f"source BREP invalid for {part_id}: {source_metrics}")
        export_step(shape, source_step)
        source_brep.parent.mkdir(parents=True, exist_ok=True)
        export_brep(shape, source_brep)
        report["source"] = {
            "kind": "authoritative generated BREP",
            "path": source_brep.relative_to(root).as_posix(),
            "sizeBytes": source_brep.stat().st_size,
            "sha256": sha256_file(source_brep),
            "solidWorksImportStepSizeBytes": source_step.stat().st_size,
            "solidWorksImportStepSha256": sha256_file(source_step),
            "metrics": source_metrics,
        }

        import_data = sw.GetImportFileData(str(source_step.resolve()))
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        imported = sw.LoadFile4(str(source_step.resolve()), "r", import_data, errors)
        if imported is None or int(errors.value) != 0:
            raise RuntimeError(f"SolidWorks LoadFile4 error={int(errors.value)}")
        save_code = int(imported.SaveAs3(str(native_path.resolve()), 0, SW_SAVE_SILENT))
        if save_code != 0 or not native_path.is_file():
            raise RuntimeError(f"SolidWorks SaveAs3 SLDPRT error={save_code}")
        _close(sw, imported)
        imported = None

        reopened, open_result = _open_native(sw, native_path, SW_DOC_PART)
        if open_result["warningCode"] != 0:
            raise RuntimeError(f"native part reopen warning is nonzero: {open_result}")
        bodies = reopened.GetBodies2(0, False)
        body_count = 0 if bodies is None else len(bodies)
        if int(_value(reopened, "GetType")) != SW_DOC_PART or body_count != 1:
            raise RuntimeError(
                f"native reopen mismatch: type={_value(reopened, 'GetType')} bodies={body_count}"
            )
        native_bbox = _bbox_mm(reopened.GetPartBox(True))
        step_save_code = int(reopened.SaveAs3(str(final_step.resolve()), 0, SW_SAVE_SILENT))
        if step_save_code != 0 or not final_step.is_file():
            raise RuntimeError(f"SolidWorks SaveAs3 STEP error={step_save_code}")
        _close(sw, reopened)
        reopened = None

        final_metrics = _final_step_metrics(final_step)
        volume_delta = abs(final_metrics["volumeMm3"] - source_metrics["volumeMm3"])
        volume_limit = max(0.10, source_metrics["volumeMm3"] * 2e-5)
        if (
            not final_metrics["valid"]
            or final_metrics["solidCount"] != 1
            or volume_delta > volume_limit
        ):
            raise RuntimeError(
                f"final STEP BREP closure failed: final={final_metrics}, volumeDelta={volume_delta}"
            )

        report["nativeReopen"] = {
            **open_result,
            "documentType": "part",
            "bodyCount": body_count,
            "bboxMm": native_bbox,
        }
        report["nativeCad"] = {
            "path": native_path.relative_to(root).as_posix(),
            "sizeBytes": native_path.stat().st_size,
            "sha256": sha256_file(native_path),
        }
        report["finalStep"] = {
            "path": final_step.relative_to(root).as_posix(),
            "sizeBytes": final_step.stat().st_size,
            "sha256": sha256_file(final_step),
            "metrics": final_metrics,
            "volumeDeltaMm3": round(volume_delta, 9),
        }
        report["checks"] = [
            {"id": "source-brep", "status": "pass", "detail": "valid single-solid source BREP"},
            {"id": "solidworks-import", "status": "pass", "detail": "LoadFile4 imported the source STEP without error"},
            {"id": "native-save", "status": "pass", "detail": "SaveAs3 created an authentic SLDPRT"},
            {"id": "native-reopen", "status": "pass", "detail": f"OpenDoc7 returned one solid body; bbox mm={native_bbox}"},
            {"id": "step-roundtrip", "status": "pass", "detail": f"reopened native document exported valid single-solid STEP; volume delta {volume_delta:.9f} mm3"},
        ]
        report["status"] = "pass"
        return report
    except Exception as exc:
        report["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        raise
    finally:
        _close(sw, imported)
        _close(sw, reopened)
        _delete_exact(source_step)
        _json(report_path, report)


def _component_closure(root: Path, output_dir: Path, config: dict[str, Any], assembly: Any) -> list[dict[str, Any]]:
    part_by_filename = {
        f"{geometry.PART_BASENAMES[part_id]}.sldprt".lower(): part_id
        for part_id in config["parts"]
    }
    rows: list[dict[str, Any]] = []
    components = assembly.GetComponents(True)
    for component in (() if components is None else components):
        host_path = str(_value(component, "GetPathName"))
        filename = Path(host_path).name.lower()
        part_id = part_by_filename.get(filename)
        if part_id is None:
            raise RuntimeError(f"native assembly contains an unbound component filename: {Path(host_path).name}")
        transform_object = component.Transform2
        transform = [float(value) for value in transform_object.ArrayData]
        if len(transform) != 16:
            raise RuntimeError(f"{part_id} native transform has {len(transform)} values")
        actual_translation = [round(transform[index] * 1000.0, 6) for index in (9, 10, 11)]
        expected_translation = [round(float(value), 6) for value in config["placements"][part_id]]
        delta = [round(actual_translation[index] - expected_translation[index], 9) for index in range(3)]
        suppression_state = int(_value(component, "GetSuppression"))
        referenced_configuration = str(_value(component, "ReferencedConfiguration"))
        part_path = output_dir / f"{geometry.PART_BASENAMES[part_id]}.SLDPRT"
        row = {
            "instanceId": f"{part_id}:1",
            "partId": part_id,
            "nativeCadPath": part_path.relative_to(root).as_posix(),
            "nativeCadSizeBytes": part_path.stat().st_size,
            "nativeCadSha256": sha256_file(part_path),
            "suppressionState": suppression_state,
            "suppressionStateName": SUPPRESSION_STATE_NAMES.get(suppression_state, f"unmapped:{suppression_state}"),
            "referencedConfiguration": referenced_configuration,
            "transformArray": [round(value, 12) for value in transform],
            "expectedTranslationMm": expected_translation,
            "actualTranslationMm": actual_translation,
            "translationDeltaMm": delta,
            "transformMatches": max(abs(value) for value in delta) <= 1e-6,
        }
        if suppression_state not in {2, 3} or not referenced_configuration or not row["transformMatches"]:
            raise RuntimeError(f"native component is not fully resolved/configured/positioned: {row}")
        rows.append(row)
    by_part = {row["partId"]: row for row in rows}
    if set(by_part) != set(config["parts"]) or len(rows) != len(config["parts"]):
        raise RuntimeError(f"native component inventory mismatch: {sorted(by_part)}")
    return [by_part[part_id] for part_id in config["parts"]]


def export_assembly(sw: Any, root: Path, assembly_id: str, native_tool: dict[str, Any]) -> dict[str, Any]:
    config = ASSEMBLIES[assembly_id]
    output_dir = root / "outputs" / "3d"
    report_path = root / "reports" / "native" / f"{assembly_id}_solidworks-execution.json"
    native_path = output_dir / f"{config['basename']}.SLDASM"
    final_step = output_dir / f"{config['basename']}.step"
    assembly_template = _assembly_template(sw)
    for path in (native_path, final_step):
        _delete_exact(path)

    report: dict[str, Any] = {
        "schema": "aicad_solidworks_native_execution_raw_v1",
        "subjectId": assembly_id,
        "revision": REVISION,
        "operation": "native component load -> SLDASM build/save -> native reopen -> STEP export",
        "status": "fail",
        "nativeTool": native_tool,
        "paths": {
            "nativeAssembly": native_path.relative_to(root).as_posix(),
            "step": final_step.relative_to(root).as_posix(),
        },
        "components": [],
        "checks": [],
    }
    opened_parts: list[Any] = []
    assembly = None
    reopened = None
    try:
        for part_id in config["parts"]:
            part_path = output_dir / f"{geometry.PART_BASENAMES[part_id]}.SLDPRT"
            if not part_path.is_file():
                raise FileNotFoundError(part_path)
            model, open_result = _open_native(sw, part_path, SW_DOC_PART)
            if open_result["warningCode"] != 0:
                raise RuntimeError(f"assembly component reopen warning is nonzero: {part_id}: {open_result}")
            opened_parts.append(model)
            report["components"].append(
                {
                    "partId": part_id,
                    "path": part_path.relative_to(root).as_posix(),
                    "sizeBytes": part_path.stat().st_size,
                    "sha256": sha256_file(part_path),
                    "expectedTranslationMm": list(config["placements"][part_id]),
                    "open": open_result,
                }
            )

        assembly = sw.NewDocument(str(assembly_template), 0, 0.0, 0.0)
        if assembly is None or int(_value(assembly, "GetType")) != SW_DOC_ASSEMBLY:
            raise RuntimeError("SolidWorks NewDocument did not return an assembly")
        for part_id in config["parts"]:
            part_path = output_dir / f"{geometry.PART_BASENAMES[part_id]}.SLDPRT"
            local_bbox = geometry.make_part(part_id).bounding_box(optimal=True)
            local_center = (
                (local_bbox.min.X + local_bbox.max.X) / 2.0,
                (local_bbox.min.Y + local_bbox.max.Y) / 2.0,
                (local_bbox.min.Z + local_bbox.max.Z) / 2.0,
            )
            x, y, z = [
                (float(config["placements"][part_id][index]) + float(local_center[index])) / 1000.0
                for index in range(3)
            ]
            component = assembly.AddComponent5(
                str(part_path.resolve()), 0, "", False, "", x, y, z
            )
            if component is None:
                raise RuntimeError(f"SolidWorks AddComponent5 failed for {part_id}")
        assembly.ForceRebuild3(False)
        save_code = int(assembly.SaveAs3(str(native_path.resolve()), 0, SW_SAVE_SILENT | SW_SAVE_REFERENCED))
        if save_code != 0 or not native_path.is_file():
            raise RuntimeError(f"SolidWorks SaveAs3 SLDASM error={save_code}")
        _close(sw, assembly)
        assembly = None
        for model in opened_parts:
            _close(sw, model)
        opened_parts = []

        reopened, open_result = _open_native(sw, native_path, SW_DOC_ASSEMBLY)
        if open_result["warningCode"] != 0:
            raise RuntimeError(f"native assembly reopen warning is nonzero: {open_result}")
        component_count = int(reopened.GetComponentCount(True))
        if int(_value(reopened, "GetType")) != SW_DOC_ASSEMBLY or component_count != len(config["parts"]):
            raise RuntimeError(
                f"assembly native reopen mismatch: type={_value(reopened, 'GetType')} components={component_count}"
            )
        component_closure = _component_closure(root, output_dir, config, reopened)
        native_bbox = _bbox_mm(reopened.GetBox(0))
        step_save_code = int(reopened.SaveAs3(str(final_step.resolve()), 0, SW_SAVE_SILENT))
        if step_save_code != 0 or not final_step.is_file():
            raise RuntimeError(f"SolidWorks SaveAs3 assembly STEP error={step_save_code}")
        _close(sw, reopened)
        reopened = None

        final_metrics = _final_step_metrics(final_step)
        if not final_metrics["valid"] or final_metrics["solidCount"] != len(config["parts"]):
            raise RuntimeError(f"assembly STEP solid closure failed: {final_metrics}")
        report["nativeReopen"] = {
            **open_result,
            "documentType": "assembly",
            "componentCount": component_count,
            "bboxMm": native_bbox,
        }
        report["components"] = component_closure
        report["componentClosure"] = component_closure
        report["nativeAssembly"] = {
            "path": native_path.relative_to(root).as_posix(),
            "sizeBytes": native_path.stat().st_size,
            "sha256": sha256_file(native_path),
        }
        report["finalStep"] = {
            "path": final_step.relative_to(root).as_posix(),
            "sizeBytes": final_step.stat().st_size,
            "sha256": sha256_file(final_step),
            "metrics": final_metrics,
        }
        report["checks"] = [
            {"id": "component-native-load", "status": "pass", "detail": f"OpenDoc7 loaded {component_count} final native component documents"},
            {"id": "assembly-native-save", "status": "pass", "detail": "SaveAs3 created an authentic SLDASM with Silent|SaveReferenced options"},
            {"id": "assembly-native-reopen", "status": "pass", "detail": f"OpenDoc7 returned warningCode=0 and {component_count} resolved components; bbox mm={native_bbox}"},
            {"id": "component-transform-closure", "status": "pass", "detail": f"all {component_count} resolved native components match released translation transforms within 0.000001 mm"},
            {"id": "assembly-step-roundtrip", "status": "pass", "detail": f"reopened SLDASM exported a valid {final_metrics['solidCount']}-solid STEP"},
        ]
        report["status"] = "pass"
        return report
    except Exception as exc:
        report["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        raise
    finally:
        _close(sw, assembly)
        _close(sw, reopened)
        for model in opened_parts:
            _close(sw, model)
        _json(report_path, report)


def _refresh_part_after_assembly_save(sw: Any, root: Path, part_id: str) -> dict[str, Any]:
    """Rebind the part log after SaveReferenced has finalized component files."""
    output_dir = root / "outputs" / "3d"
    basename = geometry.PART_BASENAMES[part_id]
    native_path = output_dir / f"{basename}.SLDPRT"
    final_step = output_dir / f"{basename}.step"
    report_path = root / "reports" / "native" / f"{part_id}_solidworks-execution.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    native_sha_before = sha256_file(native_path)
    reopened = None
    try:
        reopened, open_result = _open_native(sw, native_path, SW_DOC_PART)
        if open_result["warningCode"] != 0:
            raise RuntimeError(f"post-assembly part reopen warning is nonzero: {open_result}")
        bodies = reopened.GetBodies2(0, False)
        body_count = 0 if bodies is None else len(bodies)
        if int(_value(reopened, "GetType")) != SW_DOC_PART or body_count != 1:
            raise RuntimeError(f"post-assembly part body closure failed: {part_id}: {body_count}")
        native_bbox = _bbox_mm(reopened.GetPartBox(True))
        save_code = int(reopened.SaveAs3(str(final_step.resolve()), 0, SW_SAVE_SILENT))
        if save_code != 0 or not final_step.is_file():
            raise RuntimeError(f"post-assembly STEP export failed: {part_id}: {save_code}")
        _close(sw, reopened)
        reopened = None
        native_sha_after = sha256_file(native_path)
        if native_sha_after != native_sha_before:
            raise RuntimeError(f"STEP export mutated native part bytes: {part_id}")
        final_metrics = _final_step_metrics(final_step)
        source_metrics = report["source"]["metrics"]
        volume_delta = abs(final_metrics["volumeMm3"] - source_metrics["volumeMm3"])
        volume_limit = max(0.10, source_metrics["volumeMm3"] * 2e-5)
        if not final_metrics["valid"] or final_metrics["solidCount"] != 1 or volume_delta > volume_limit:
            raise RuntimeError(f"post-assembly STEP BREP closure failed: {part_id}: {final_metrics}")
        report["nativeReopen"] = {
            **open_result,
            "documentType": "part",
            "bodyCount": body_count,
            "bboxMm": native_bbox,
            "phase": "post-assembly SaveReferenced final closure",
        }
        report["nativeCad"] = {
            "path": native_path.relative_to(root).as_posix(),
            "sizeBytes": native_path.stat().st_size,
            "sha256": native_sha_after,
        }
        report["finalStep"] = {
            "path": final_step.relative_to(root).as_posix(),
            "sizeBytes": final_step.stat().st_size,
            "sha256": sha256_file(final_step),
            "metrics": final_metrics,
            "volumeDeltaMm3": round(volume_delta, 9),
        }
        report["checks"] = [row for row in report["checks"] if row["id"] != "post-assembly-native-reopen"]
        report["checks"].append({"id": "post-assembly-native-reopen", "status": "pass", "detail": "OpenDoc7 warningCode=0, one solid body, and STEP export did not mutate final SLDPRT bytes after SaveReferenced"})
        report["status"] = "pass"
        report.pop("failure", None)
        _json(report_path, report)
        return report
    finally:
        _close(sw, reopened)


def run(root: Path) -> dict[str, Any]:
    pythoncom.CoInitialize()
    sw = None
    previous_3d_interconnect: bool | None = None
    results: dict[str, Any] = {"parts": {}, "assemblies": {}}
    try:
        sw = win32com.client.DispatchEx("SldWorks.Application")
        sw.Visible = False
        sw.UserControl = False
        sw.CommandInProgress = True
        previous_3d_interconnect = bool(sw.GetUserPreferenceToggle(SW_PREF_ENABLE_3D_INTERCONNECT))
        sw.SetUserPreferenceToggle(SW_PREF_ENABLE_3D_INTERCONNECT, False)
        native_tool = _native_tool(sw)
        for part_id in geometry.PART_FACTORIES:
            results["parts"][part_id] = export_part(sw, root, part_id, native_tool)
        for assembly_id in ASSEMBLIES:
            results["assemblies"][assembly_id] = export_assembly(
                sw, root, assembly_id, native_tool
            )
        for part_id in geometry.PART_FACTORIES:
            results["parts"][part_id] = _refresh_part_after_assembly_save(sw, root, part_id)
        results["nativeTool"] = native_tool
        results["passed"] = True
        return results
    finally:
        if sw is not None:
            try:
                if previous_3d_interconnect is not None:
                    sw.SetUserPreferenceToggle(SW_PREF_ENABLE_3D_INTERCONNECT, previous_3d_interconnect)
                sw.CommandInProgress = False
                sw.ExitApp()
            except Exception:
                pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    try:
        result = run(package_root)
        print(
            json.dumps(
                {
                    "passed": result["passed"],
                    "partCount": len(result["parts"]),
                    "assemblyCount": len(result["assemblies"]),
                    "nativeTool": result["nativeTool"],
                },
                indent=2,
            )
        )
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        sys.exit(1)

