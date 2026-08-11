from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CANDIDATES = [
    PLUGIN_ROOT / "runtime" / "src",
    PLUGIN_ROOT.parents[1] / "src",
]
for candidate in RUNTIME_CANDIDATES:
    if (candidate / "aicad" / "engine.py").is_file():
        sys.path.insert(0, str(candidate))
        break

try:
    from aicad.correction import apply_correction, preview_correction
    from aicad.domain_rules import DOMAIN_RULE_PACKS, HOST_CAPABILITIES, evaluate_domain_plan, write_domain_validation
    from aicad.engine import PlanError, compile_plan
    from aicad.exporters import export_all
    from aicad.provider import ProviderError, generate_plan
    from aicad.reference_rebuild import build_reference_reconstruction, validate_reference_rebuild
    from aicad.review_launch import REVIEW_LAUNCH_MODES, launch_review
    from aicad.semantic import describe_plan, domain_capabilities
    from aicad.solidworks3d import compile_3d_plan, solidworks_doctor, validate_3d_plan
    from aicad.viewmap import build_multiview_review
except ImportError as exc:  # pragma: no cover - exercised by packaged smoke test
    raise SystemExit(f"AICAD runtime is missing or incomplete: {exc}")


AGENT_API_VERSION = "1.8.3"
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _runtime_file(*parts: str) -> Path:
    packaged = PLUGIN_ROOT / "runtime" / Path(*parts)
    if packaged.exists():
        return packaged
    return PLUGIN_ROOT.parents[1] / Path(*parts)


def _job_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "AiCadConstraint" / "agent-jobs"


def _new_job_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _job_root() / f"{stamp}-{uuid.uuid4().hex[:8]}"


def _safe_name(value: str | None) -> str:
    name = SAFE_NAME.sub("-", (value or "drawing").strip()).strip("-_")
    return name[:64] or "drawing"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_plan(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise PlanError("plan is empty")
        candidate = Path(text)
        source_path: Path | None = None
        if len(text) < 1024 and candidate.is_file():
            source_path = candidate.resolve()
            text = source_path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanError(f"plan must be a JSON object or a path to a UTF-8 JSON file: {exc}") from exc
        if isinstance(parsed, dict):
            reference = parsed.get("reference")
            if source_path is not None and isinstance(reference, dict):
                locator = reference.get("locator")
                if isinstance(locator, str) and locator and "://" not in locator:
                    locator_path = Path(locator)
                    if not locator_path.is_absolute():
                        reference["locator"] = str((source_path.parent / locator_path).resolve())
            return parsed
    raise PlanError("plan must be a JSON object, JSON string, or plan file path")

def capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "api_version": AGENT_API_VERSION,
        "purpose": "Convert 2D/3D CAD intent into deterministic, origin-anchored, audited geometry and SolidWorks parts.",
        "entities": ["line", "circle", "arc"],
        "units": ["mm", "inch"],
        "constraints": [
            "horizontal", "vertical", "length", "parallel", "perpendicular", "collinear",
            "start_coincident", "end_coincident", "start_offset", "radius", "diameter",
            "center_coincident", "center_offset", "start_angle", "end_angle",
        ],
        "artifacts": ["plan.json", "aicad", "scr", "dxf", "audit.md", "manifest.json"],
        "agent_native": {
            "default": True,
            "api_key_required": False,
            "workflow": ["get_plan_schema", "author_plan_in_current_agent", "validate_plan", "compile_plan"],
            "compiler_provider": "caller-plan",
        },
        "generation": {
            "offline": ["rectangle", "circle", "arc", "rectangular plate with one centered hole"],
            "arbitrary_2d": "Submit a schema_version 2.0 plan with aicad_compile_plan.",
            "optional_provider": "openai",
        },
        "invariants": [
            "drawing origin is [0,0]",
            "first entity anchor is origin",
            "every entity has purpose, reasoning, and mathematical constraints",
            "AutoCAD execution channel is ASCII and accepts only LINE/CIRCLE/ARC records",
        ],
        "architectural_drafting_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_architecture_qa.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "architectural_drafting_rules.json").resolve()),
            "complete_axis_groups": True,
            "annotation_completeness_matrix": True,
            "review_only": True,
        },
        "production_readiness_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_production_readiness_qa.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "production_readiness_rules.json").resolve()),
            "contract_schema": str((PLUGIN_ROOT / "rules" / "production_readiness_contract.schema.json").resolve()),
            "policy": "non_compensatory_fail_closed",
            "strict_production_failure_disposition": "blocker_report_only",
            "automatic_acceptance": False,
        },
        "report_quality_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_report_qa.py").resolve()),
            "unique_prevention_rule_ids": True,
            "conflicting_duplicates_fail": True,
            "repeat_run_idempotence_required": True,
            "review_only": True,
        },
        "packaging_dieline_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_packaging_qa.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "packaging_dieline_rules.json").resolve()),
            "workflow": [
                "detect defect",
                "explain root cause",
                "repair locally",
                "encode prevention rule",
                "run regression test",
            ],
            "review_only": True,
        },
        "universal_cad": {
            "core_is_domain_agnostic": True,
            "spaces": ["2d", "3d"],
            "domain_profiles": domain_capabilities()["built_in_profiles"],
            "workflow": [
                "convert plan to ordered semantic object graph",
                "generate synchronized 2D/3D review views",
                "select semantic objects in any view",
                "preview a bounded typed correction",
                "recompile and replay affected dependencies",
                "record root cause and disabled prevention-rule candidate",
            ],
            "correction_operations": [
                "set_parameter", "add_constraint", "remove_constraint", "add_relation",
                "replace_dependency", "insert_object", "remove_object",
                "set_subobject_parameter", "move_subobject", "add_subobject_relation",
            ],
            "exact_subobject_correction": {
                "geometry_types": ["line", "circle", "point", "face"],
                "reference_format": "feature_id|semantic_subobject",
                "preserve_policies": ["keep_center", "keep_opposite", "keep_size", "keep_support"],
                "pattern_scope_requires_explicit_fanout": True,
                "detached_pattern_instance_supported": False,
                "full_dependency_replay": True,
                "positive_residual_wall_gate": True,
                "semantic_reference_authority": True,
                "native_persistent_topology_authority": False,
                "live_solidworks_native_topology_authority_available": True,
                "live_authority_gate": "SLDPRT save/reopen exact key-set equality and zero unresolved required references",
                "selection_measurements": {
                    "line": ["length_mm", "start", "end"],
                    "point": ["coordinates"],
                    "circle": ["center", "radius_mm", "diameter_mm"],
                    "face": ["center", "area_mm2"],
                    "authority": "compiled model coordinates; never screen pixels",
                },
                "coordinate_system": {
                    "id": "MODEL_XYZ", "handedness": "right", "unit": "mm",
                    "visibility_toggle": "synchronized SVG axes, origins, and rotating 3D triad",
                },
            },
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
            "schemas": ["semantic-document", "correction", "view-package", "domain-validation"],
            "domain_rule_packs": sorted(DOMAIN_RULE_PACKS),
            "host_capability_matrix": HOST_CAPABILITIES,
        },
        "reference_reconstruction": {
            "available": True,
            "reference_kinds": ["webpage_svg", "webpage_capture", "svg", "raster", "pdf"],
            "geometry_authority": "explicit dimensions, calibrated baselines, or native vector units; never raw pixels",
            "gates": [
                "source content hash", "direct webpage SVG object catalog", "similarity calibration",
                "one-reference-object-to-one-CAD-object mapping", "dimension values",
                "annotation text and calibrated placement", "lineweight hierarchy", "mojibake", "overlap",
            ],
            "outputs": ["reference.json", "annotated.dxf", "preview.svg", "preview.html", "validation.json", "validation.md", "manifest.json"],
            "native_autocad_dimension_and_dwg": "host postprocess required",
            "schema_path": str(_runtime_file("schema", "aicad-reference-rebuild.schema.json").resolve()),
            "review_only": True,
        },
        "schema_path": str(_runtime_file("schema", "aicad-plan.schema.json").resolve()),
        "solidworks_3d": {
            "features": ["base_extrude", "boss_extrude", "cut_extrude"],
            "profiles": ["center_rectangle", "circle", "circle_pattern"],
            "artifacts": ["SLDPRT", "STEP", "3d.audit.md", "solidworks-report.json", "3d.manifest.json"],
            "invariants": [
                "part origin is [0,0,0]",
                "each feature declares purpose, reasoning, dependencies, support, and mathematical constraints",
                "each sketch must be fully constrained before its feature is accepted",
                "feature error, body faults, body count, volume, bounding box, and persistent references are read back",
                "a failing feature transaction does not save a partial part",
                "boss-supported cuts retain positive residual wall after correction replay",
                "ordered sketch primitives receive required native persistent references",
                "native topology catalog is embedded, saved, reopened, and resolved record by record",
            ],
            "native_topology_rules": str((PLUGIN_ROOT / "rules" / "native_solidworks_topology_rules.json").resolve()),
            "native_topology_authority": "available only in successful executed build result",
            "schema_path": str(_runtime_file("schema", "aicad-3d-plan.schema.json").resolve()),
        },
    }


def validate_plan_value(value: Any) -> dict[str, Any]:
    data = _load_plan(value)
    plan = compile_plan(data)
    return {
        "ok": True,
        "valid": True,
        "name": plan.name,
        "schema_version": plan.schema_version,
        "units": plan.units,
        "origin": list(plan.origin),
        "tolerance": plan.tolerance,
        "source_sha256": plan.source_hash,
        "entity_count": len(plan.entities),
        "entities": [{"index": index, "id": entity.id, "type": entity.type} for index, entity in enumerate(plan.entities, 1)],
    }


def _compile_data(data: dict[str, Any], output_dir: str | None, name: str | None) -> dict[str, Any]:
    plan = compile_plan(data)
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    stem = _safe_name(name or plan.name)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{stem}.plan.json"
    _write_json(source, data)
    artifacts = export_all(plan, directory, stem)
    return {
        "ok": True,
        "name": plan.name,
        "schema_version": plan.schema_version,
        "provider": "caller-plan",
        "source_sha256": plan.source_hash,
        "entity_count": len(plan.entities),
        "entities": [{"index": index, "id": entity.id, "type": entity.type} for index, entity in enumerate(plan.entities, 1)],
        "output_dir": str(directory),
        "plan": str(source),
        "execution": str(directory / f"{stem}.aicad"),
        "script": str(directory / f"{stem}.scr"),
        "dxf": str(directory / f"{stem}.dxf"),
        "audit": str(directory / f"{stem}.audit.md"),
        "manifest": str(directory / f"{stem}.manifest.json"),
        "artifacts": [str(path.resolve()) for path in artifacts],
    }


def _attach_review(
    data: dict[str, Any], result: dict[str, Any], space: str, domain: str,
    name: str | None, review_launch: str,
) -> dict[str, Any]:
    directory = Path(str(result["output_dir"]))
    stem = _safe_name(f"{name or result.get('name') or 'drawing'}-review")
    review = build_multiview_review(data, space, domain, directory, stem)
    review_path = Path(review["artifacts"]["review_html"])
    result["review"] = review
    result["review_launch"] = launch_review(review_path, review_launch)
    return result


def compile_plan_value(
    value: Any, output_dir: str | None = None, name: str | None = None,
    review_launch: str = "never",
) -> dict[str, Any]:
    data = _load_plan(value)
    result = _compile_data(data, output_dir, name)
    domain = str(data.get("drawing", {}).get("domain", "general"))
    return _attach_review(data, result, "2d", domain, name, review_launch)


def generate(
    request: str, output_dir: str | None = None, name: str | None = None,
    provider: str = "offline", review_launch: str = "never",
) -> dict[str, Any]:
    if not isinstance(request, str) or not request.strip():
        raise PlanError("request must be a non-empty string")
    data, used_provider = generate_plan(request.strip(), provider)
    result = _compile_data(data, output_dir, name)
    result["provider"] = used_provider
    result["request_interpreted"] = True
    domain = str(data.get("drawing", {}).get("domain", "general"))
    return _attach_review(data, result, "2d", domain, name, review_launch)


def get_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-plan.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def get_3d_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-3d-plan.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def get_aux_schema(name: str) -> dict[str, Any]:
    filenames = {
        "semantic": "aicad-semantic-document.schema.json",
        "correction": "aicad-correction.schema.json",
        "view": "aicad-view-package.schema.json",
        "domain": "aicad-domain-validation.schema.json",
        "reference": "aicad-reference-rebuild.schema.json",
    }
    if name not in filenames:
        raise PlanError(f"unknown auxiliary schema '{name}'")
    path = _runtime_file("schema", filenames[name])
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def describe_plan_value(value: Any, space: str, domain: str = "general") -> dict[str, Any]:
    return {"ok": True, **describe_plan(_load_plan(value), space, domain)}


def validate_domain_value(
    value: Any, space: str, domain: str = "general", output_dir: str | None = None, name: str | None = None,
) -> dict[str, Any]:
    data = _load_plan(value)
    report = evaluate_domain_plan(data, space, domain)
    result: dict[str, Any] = {"ok": report["status"] != "failed", **report}
    if output_dir is not None:
        directory = Path(output_dir).expanduser().resolve()
        result["artifacts"] = write_domain_validation(data, space, directory, _safe_name(name or "domain-validation"), domain)
    return result

def preview_correction_value(plan_value: Any, correction_value: Any, domain: str = "general") -> dict[str, Any]:
    return preview_correction(_load_plan(plan_value), _load_plan(correction_value), domain)


def apply_correction_value(
    plan_value: Any, correction_value: Any, output_dir: str | None = None,
    name: str | None = None, domain: str = "general",
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    return apply_correction(_load_plan(plan_value), _load_plan(correction_value), directory, _safe_name(name or "correction"), domain)


def build_multiview_value(
    value: Any, space: str, domain: str = "general", output_dir: str | None = None,
    name: str | None = None, review_launch: str = "never",
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    result = build_multiview_review(_load_plan(value), space, domain, directory, _safe_name(name or "multiview"))
    result["review_launch"] = launch_review(Path(result["artifacts"]["review_html"]), review_launch)
    return result


def validate_reference_rebuild_value(plan_value: Any, reference_value: Any) -> dict[str, Any]:
    return validate_reference_rebuild(_load_plan(plan_value), _load_plan(reference_value))


def build_reference_reconstruction_value(
    plan_value: Any, reference_value: Any, output_dir: str | None = None, name: str | None = None,
) -> dict[str, Any]:
    data = _load_plan(plan_value)
    reference = _load_plan(reference_value)
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    return build_reference_reconstruction(data, reference, directory, _safe_name(name or "reference-rebuild"))


def validate_3d_plan_value(value: Any) -> dict[str, Any]:
    return validate_3d_plan(_load_plan(value))


def build_solidworks_part(
    value: Any,
    output_dir: str | None = None,
    name: str | None = None,
    execute: bool = True,
    timeout_seconds: int = 300,
    review_launch: str = "never",
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    data = _load_plan(value)
    result = compile_3d_plan(data, directory, name, execute, timeout_seconds)
    domain = str(data.get("part", {}).get("domain", "general"))
    return _attach_review(data, result, "3d", domain, name, review_launch)


TOOLS: list[dict[str, Any]] = [
    {
        "name": "aicad_capabilities",
        "description": "Discover supported CAD entities, constraints, artifacts, providers, and hard invariants before planning.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_plan_schema",
        "description": "Return the complete schema_version 2.0 JSON Schema for arbitrary caller-authored CAD plans.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_generate",
        "description": "Generate and compile common 2D geometry from natural language. Defaults to deterministic offline interpretation.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["request"],
            "properties": {
                "request": {"type": "string", "minLength": 1},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
                "provider": {"type": "string", "enum": ["offline", "auto", "openai"], "default": "offline"},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
            },
        },
    },
    {
        "name": "aicad_validate_plan",
        "description": "Validate an origin-anchored plan without writing CAD artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan"],
            "properties": {"plan": {"description": "Plan object, JSON string, or UTF-8 plan file path"}},
        },
    },
    {
        "name": "aicad_compile_plan",
        "description": "Validate a caller-authored plan and produce AICAD, SCR, DXF, audit, and manifest artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan"],
            "properties": {
                "plan": {"description": "Plan object, JSON string, or UTF-8 plan file path"},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
            },
        },
    },
    {
        "name": "aicad_get_semantic_schema",
        "description": "Return the domain-agnostic ordered 2D/3D semantic object graph schema.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_correction_schema",
        "description": "Return the bounded typed correction transaction schema shared by 2D and 3D.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_view_package_schema",
        "description": "Return the synchronized multi-view and semantic selection-map schema.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_describe_plan",
        "description": "Compile a 2D or 3D plan into an ordered, domain-agnostic semantic object and relation graph.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "space"],
            "properties": {
                "plan": {"description": "Plan object, JSON string, or UTF-8 plan file path"},
                "space": {"type": "string", "enum": ["2d", "3d"]},
                "domain": {"type": "string", "default": "general"},
            },
        },
    },
    {
        "name": "aicad_preview_correction",
        "description": "Apply a typed correction in memory, enforce locks and change budgets, recompile, and report downstream impact without writing artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "correction"],
            "properties": {
                "plan": {"description": "2D/3D plan object, JSON string, or file path"},
                "correction": {"description": "Correction object, JSON string, or file path"},
                "domain": {"type": "string", "default": "general"},
            },
        },
    },
    {
        "name": "aicad_apply_correction",
        "description": "Commit a validated correction to a new plan and write transaction, root-cause, prevention-rule, and change audit artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "correction"],
            "properties": {
                "plan": {"description": "2D/3D plan object, JSON string, or file path"},
                "correction": {"description": "Correction object, JSON string, or file path"},
                "domain": {"type": "string", "default": "general"},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
            },
        },
    },
    {
        "name": "aicad_build_multiview_review",
        "description": "Generate synchronized 2D plan, orthographic, isometric semantic selector, and section review views with 3D back-references.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "space"],
            "properties": {
                "plan": {"description": "2D/3D plan object, JSON string, or file path"},
                "space": {"type": "string", "enum": ["2d", "3d"]},
                "domain": {"type": "string", "default": "general"},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
            },
        },
    },
    {
        "name": "aicad_get_reference_rebuild_schema",
        "description": "Return the calibrated webpage/image-to-CAD reconstruction contract schema; raw pixels are never dimension truth.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_validate_reference_rebuild",
        "description": "Validate source hash, webpage SVG DOM objects, calibrated 1:1 geometry, annotations, drafting hierarchy, overlap, and text encoding without writing artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "reference"],
            "properties": {
                "plan": {"description": "AICAD 2D plan object, JSON string, or UTF-8 file path"},
                "reference": {"description": "Reference reconstruction contract object, JSON string, or UTF-8 file path"},
            },
        },
    },
    {
        "name": "aicad_build_reference_reconstruction",
        "description": "Build editable 1:1 DXF geometry, annotation graphics, UTF-8 SVG/HTML preview, validation, and manifest from a calibrated webpage/image reference contract.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "reference"],
            "properties": {
                "plan": {"description": "AICAD 2D plan object, JSON string, or UTF-8 file path"},
                "reference": {"description": "Reference reconstruction contract object, JSON string, or UTF-8 file path"},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
            },
        },
    },
    {
        "name": "aicad_get_domain_validation_schema",
        "description": "Return the cross-domain role, layer, geometry, root-cause, prevention-rule, and capability-boundary report schema.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_validate_domain_plan",
        "description": "Validate a compiled 2D/3D plan against mechanical, electronics, sheet-metal, architecture, packaging, or custom domain semantics.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "space"],
            "properties": {
                "plan": {"description": "2D/3D plan object, JSON string, or UTF-8 file path"},
                "space": {"type": "string", "enum": ["2d", "3d"]},
                "domain": {"type": "string", "default": "general"},
                "output_dir": {"type": "string"}, "name": {"type": "string"}
            },
        },
    },    {
        "name": "aicad_solidworks_doctor",
        "description": "Check whether SolidWorks, its part template, and the typed AICAD host are ready for real 3D execution.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_3d_plan_schema",
        "description": "Return the complete schema_version 1.0 JSON Schema for feature-by-feature SolidWorks plans.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_validate_3d_plan",
        "description": "Validate a feature graph and all declared mathematical constraints without opening SolidWorks or writing artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan"],
            "properties": {"plan": {"description": "3D plan object, JSON string, or UTF-8 plan file path"}},
        },
    },
    {
        "name": "aicad_build_solidworks_part",
        "description": "Build a SolidWorks part one validated feature transaction at a time and export SLDPRT, STEP, audit, and readback report.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan"],
            "properties": {
                "plan": {"description": "3D plan object, JSON string, or UTF-8 plan file path"},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
                "execute": {"type": "boolean", "default": True},
                "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 1800, "default": 300},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
            },
        },
    },
]


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "aicad_capabilities":
        return capabilities()
    if name == "aicad_get_plan_schema":
        return get_schema()
    if name == "aicad_generate":
        return generate(arguments.get("request", ""), arguments.get("output_dir"), arguments.get("name"), arguments.get("provider", "offline"), arguments.get("review_launch", "auto"))
    if name == "aicad_validate_plan":
        return validate_plan_value(arguments.get("plan"))
    if name == "aicad_compile_plan":
        return compile_plan_value(arguments.get("plan"), arguments.get("output_dir"), arguments.get("name"), arguments.get("review_launch", "auto"))
    if name == "aicad_get_semantic_schema":
        return get_aux_schema("semantic")
    if name == "aicad_get_correction_schema":
        return get_aux_schema("correction")
    if name == "aicad_get_domain_validation_schema":
        return get_aux_schema("domain")
    if name == "aicad_validate_domain_plan":
        return validate_domain_value(arguments.get("plan"), arguments.get("space", "2d"), arguments.get("domain", "general"), arguments.get("output_dir"), arguments.get("name"))
    if name == "aicad_get_view_package_schema":
        return get_aux_schema("view")
    if name == "aicad_describe_plan":
        return describe_plan_value(arguments.get("plan"), arguments.get("space", "2d"), arguments.get("domain", "general"))
    if name == "aicad_preview_correction":
        return preview_correction_value(arguments.get("plan"), arguments.get("correction"), arguments.get("domain", "general"))
    if name == "aicad_apply_correction":
        return apply_correction_value(
            arguments.get("plan"), arguments.get("correction"), arguments.get("output_dir"),
            arguments.get("name"), arguments.get("domain", "general"),
        )
    if name == "aicad_build_multiview_review":
        return build_multiview_value(
            arguments.get("plan"), arguments.get("space", "2d"), arguments.get("domain", "general"),
            arguments.get("output_dir"), arguments.get("name"), arguments.get("review_launch", "auto"),
        )
    if name == "aicad_get_reference_rebuild_schema":
        return get_aux_schema("reference")
    if name == "aicad_validate_reference_rebuild":
        return validate_reference_rebuild_value(arguments.get("plan"), arguments.get("reference"))
    if name == "aicad_build_reference_reconstruction":
        return build_reference_reconstruction_value(
            arguments.get("plan"), arguments.get("reference"), arguments.get("output_dir"), arguments.get("name"),
        )
    if name == "aicad_solidworks_doctor":
        return solidworks_doctor()
    if name == "aicad_get_3d_plan_schema":
        return get_3d_schema()
    if name == "aicad_validate_3d_plan":
        return validate_3d_plan_value(arguments.get("plan"))
    if name == "aicad_build_solidworks_part":
        return build_solidworks_part(
            arguments.get("plan"), arguments.get("output_dir"), arguments.get("name"),
            arguments.get("execute", True), arguments.get("timeout_seconds", 300), arguments.get("review_launch", "auto"),
        )
    raise PlanError(f"Unknown tool '{name}'")


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ProviderError):
        code = "PROVIDER_ERROR"
    elif isinstance(exc, PlanError):
        code = "PLAN_INVALID"
    elif isinstance(exc, (OSError, UnicodeError)):
        code = "IO_ERROR"
    else:
        code = "INTERNAL_ERROR"
    return {"ok": False, "error": {"code": code, "message": str(exc)}}


def _mcp_result(payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
    }
    if is_error:
        result["isError"] = True
    return result


def _handle_mcp(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    try:
        if method == "initialize":
            requested = message.get("params", {}).get("protocolVersion")
            response["result"] = {
                "protocolVersion": requested or "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}},
                "serverInfo": {"name": "aicad-agent", "version": AGENT_API_VERSION},
            }
        elif method == "ping":
            response["result"] = {}
        elif method == "tools/list":
            response["result"] = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise PlanError("tool arguments must be an object")
            try:
                response["result"] = _mcp_result(_dispatch_tool(str(params.get("name", "")), arguments))
            except Exception as exc:
                response["result"] = _mcp_result(_error_payload(exc), True)
        elif method == "resources/list":
            response["result"] = {"resources": [
                {"uri": "aicad://plan-schema", "name": "AICAD Plan Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://3d-plan-schema", "name": "AICAD 3D Plan Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://semantic-schema", "name": "AICAD Semantic Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://correction-schema", "name": "AICAD Correction Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://view-package-schema", "name": "AICAD View Package Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://domain-validation-schema", "name": "AICAD Domain Validation Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://reference-rebuild-schema", "name": "AICAD Reference Rebuild Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://capabilities", "name": "AICAD Capabilities", "mimeType": "application/json"},
            ]}
        elif method == "resources/read":
            uri = (message.get("params") or {}).get("uri")
            if uri == "aicad://plan-schema":
                payload = get_schema()["schema"]
            elif uri == "aicad://3d-plan-schema":
                payload = get_3d_schema()["schema"]
            elif uri == "aicad://semantic-schema":
                payload = get_aux_schema("semantic")["schema"]
            elif uri == "aicad://correction-schema":
                payload = get_aux_schema("correction")["schema"]
            elif uri == "aicad://domain-validation-schema":
                payload = get_aux_schema("domain")["schema"]
            elif uri == "aicad://view-package-schema":
                payload = get_aux_schema("view")["schema"]
            elif uri == "aicad://reference-rebuild-schema":
                payload = get_aux_schema("reference")["schema"]
            elif uri == "aicad://capabilities":
                payload = capabilities()
            else:
                raise PlanError(f"Unknown resource '{uri}'")
            response["result"] = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False)}]}
        else:
            response["error"] = {"code": -32601, "message": f"Method not found: {method}"}
    except Exception as exc:
        response["error"] = {"code": -32603, "message": str(exc)}
    return response


def serve_mcp() -> int:
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            response = _handle_mcp(message)
            if response is not None:
                encoded = (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                sys.stdout.buffer.write(encoded)
                sys.stdout.buffer.flush()
        except Exception as exc:
            error = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.buffer.write((json.dumps(error, ensure_ascii=False) + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aicad-agent", description="Agent-facing API for deterministic 2D CAD and SolidWorks 3D generation")
    parser.add_argument("--version", action="version", version=AGENT_API_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    commands.add_parser("schema")
    commands.add_parser("schema3d")
    commands.add_parser("semantic-schema")
    commands.add_parser("correction-schema")
    commands.add_parser("view-schema")
    commands.add_parser("domain-schema")
    commands.add_parser("reference-schema")
    reference_validate_parser = commands.add_parser("reference-validate")
    reference_validate_parser.add_argument("--plan", required=True)
    reference_validate_parser.add_argument("--reference", required=True)
    reference_build_parser = commands.add_parser("reference-build")
    reference_build_parser.add_argument("--plan", required=True)
    reference_build_parser.add_argument("--reference", required=True)
    reference_build_parser.add_argument("--out")
    reference_build_parser.add_argument("--name")
    commands.add_parser("solidworks-doctor")
    commands.add_parser("mcp")
    generate_parser = commands.add_parser("generate")
    request_group = generate_parser.add_mutually_exclusive_group(required=True)
    request_group.add_argument("--request")
    request_group.add_argument("--request-file", type=Path, help="UTF-8 text file, recommended for non-ASCII requests")
    generate_parser.add_argument("--out")
    generate_parser.add_argument("--name")
    generate_parser.add_argument("--provider", choices=["offline", "auto", "openai"], default="offline")
    generate_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="auto")
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--plan", required=True)
    compile_parser = commands.add_parser("compile")
    compile_parser.add_argument("--plan", required=True)
    compile_parser.add_argument("--out")
    compile_parser.add_argument("--name")
    compile_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="auto")
    validate3d_parser = commands.add_parser("validate3d")
    validate3d_parser.add_argument("--plan", required=True)
    build3d_parser = commands.add_parser("build3d")
    build3d_parser.add_argument("--plan", required=True)
    build3d_parser.add_argument("--out")
    build3d_parser.add_argument("--name")
    build3d_parser.add_argument("--no-execute", action="store_true")
    build3d_parser.add_argument("--timeout", type=int, default=300)
    build3d_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="auto")
    describe_parser = commands.add_parser("describe")
    describe_parser.add_argument("--plan", required=True)
    describe_parser.add_argument("--space", choices=["2d", "3d"], required=True)
    describe_parser.add_argument("--domain", default="general")
    domain_parser = commands.add_parser("domain-validate")
    domain_parser.add_argument("--plan", required=True)
    domain_parser.add_argument("--space", choices=["2d", "3d"], required=True)
    domain_parser.add_argument("--domain", default="general")
    domain_parser.add_argument("--out")
    domain_parser.add_argument("--name")
    preview_parser = commands.add_parser("preview-correction")
    preview_parser.add_argument("--plan", required=True)
    preview_parser.add_argument("--correction", required=True)
    preview_parser.add_argument("--domain", default="general")
    apply_parser = commands.add_parser("apply-correction")
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--correction", required=True)
    apply_parser.add_argument("--domain", default="general")
    apply_parser.add_argument("--out")
    apply_parser.add_argument("--name")
    multiview_parser = commands.add_parser("multiview")
    multiview_parser.add_argument("--plan", required=True)
    multiview_parser.add_argument("--space", choices=["2d", "3d"], required=True)
    multiview_parser.add_argument("--domain", default="general")
    multiview_parser.add_argument("--out")
    multiview_parser.add_argument("--name")
    multiview_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "mcp":
        return serve_mcp()
    def generate_action() -> dict[str, Any]:
        request = args.request
        if args.request_file is not None:
            request = args.request_file.read_text(encoding="utf-8")
        return generate(request, args.out, args.name, args.provider, args.review_launch)

    actions: dict[str, Callable[[], dict[str, Any]]] = {
        "capabilities": capabilities,
        "schema": get_schema,
        "schema3d": get_3d_schema,
        "semantic-schema": lambda: get_aux_schema("semantic"),
        "correction-schema": lambda: get_aux_schema("correction"),
        "view-schema": lambda: get_aux_schema("view"),
        "domain-schema": lambda: get_aux_schema("domain"),
        "reference-schema": lambda: get_aux_schema("reference"),
        "reference-validate": lambda: validate_reference_rebuild_value(args.plan, args.reference),
        "reference-build": lambda: build_reference_reconstruction_value(args.plan, args.reference, args.out, args.name),
        "solidworks-doctor": solidworks_doctor,
        "generate": generate_action,
        "validate": lambda: validate_plan_value(args.plan),
        "compile": lambda: compile_plan_value(args.plan, args.out, args.name, args.review_launch),
        "validate3d": lambda: validate_3d_plan_value(args.plan),
        "build3d": lambda: build_solidworks_part(args.plan, args.out, args.name, not args.no_execute, args.timeout, args.review_launch),
        "describe": lambda: describe_plan_value(args.plan, args.space, args.domain),
        "domain-validate": lambda: validate_domain_value(args.plan, args.space, args.domain, args.out, args.name),
        "preview-correction": lambda: preview_correction_value(args.plan, args.correction, args.domain),
        "apply-correction": lambda: apply_correction_value(args.plan, args.correction, args.out, args.name, args.domain),
        "multiview": lambda: build_multiview_value(args.plan, args.space, args.domain, args.out, args.name, args.review_launch),
    }
    try:
        payload = actions[args.command]()
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(_error_payload(exc), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
