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
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
RUNTIME_CANDIDATES = [
    # In a source checkout the repository runtime is authoritative; packaged
    # releases have no sibling src tree and therefore fall back to runtime/src.
    PLUGIN_ROOT.parents[1] / "src",
    PLUGIN_ROOT / "runtime" / "src",
]
for candidate in RUNTIME_CANDIDATES:
    if (candidate / "aicad" / "engine.py").is_file():
        sys.path.insert(0, str(candidate))
        break

try:
    from aicad.correction import apply_correction, preview_correction
    from aicad.civil import validate_civil_review_candidate
    from aicad.domain_maturity import assess_domain_registry
    from aicad.domain_rules import DOMAIN_RULE_PACKS, HOST_CAPABILITIES, evaluate_domain_plan, write_domain_validation
    from aicad.engine import PlanError, compile_plan
    from aicad.experience import recall_experience, validate_coverage_ledger
    from aicad.exporters import export_all
    from aicad.provider import ProviderError, generate_plan, generate_plan_with_usage
    from aicad.reference_rebuild import build_reference_reconstruction, validate_reference_rebuild
    from aicad.review_handoff import apply_review_handoff, validate_review_handoff
    from aicad.review_launch import REVIEW_LAUNCH_MODES, launch_review, open_review_request
    from aicad.semantic import describe_plan, domain_capabilities
    from aicad.solidworks3d import compile_3d_plan, solidworks_doctor, validate_3d_plan
    from aicad.viewmap import build_multiview_review
except ImportError as exc:  # pragma: no cover - exercised by packaged smoke test
    raise SystemExit(f"AICAD runtime is missing or incomplete: {exc}")


AGENT_API_VERSION = "1.17.0"
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
def _source_parent(value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) >= 1024:
        return None
    try:
        candidate = Path(text)
        return candidate.resolve(strict=True).parent if candidate.is_file() else None
    except OSError:
        return None




def _normative_governance_capabilities() -> dict[str, Any]:
    rules_path = PLUGIN_ROOT / "rules" / "normative_governance_rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    domain_packs = rules.get("domainPacks", {})
    return {
        "available": True,
        "priority": rules["priority"],
        "scope": rules["scope"],
        "rules": str(rules_path.resolve()),
        "validator": str((PLUGIN_ROOT / "scripts" / "aicad_requirement_conformance.py").resolve()),
        "contract_schema": str((PLUGIN_ROOT / "rules" / "drawing_requirement_contract.schema.json").resolve()),
        "rule_ids": [item["id"] for item in rules["rules"]],
        "governed_domains": sorted(domain_packs),
        "domain_pack_requirements": domain_packs,
        "authority_precedence": rules["authorityPrecedence"],
        "contract_requirements": rules["contractRequirements"],
        "implementation_proof": [
            "schema_contract_field",
            "generation_constraint",
            "independent_qa",
            "negative_regression_test",
        ],
        "failure_disposition": "blocker_report_only",
        "safety_locks": rules["safetyLocks"],
        "review_only": True,
    }


def capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "api_version": AGENT_API_VERSION,
        "purpose": "Convert 2D/3D CAD intent into deterministic, origin-anchored, audited geometry and SolidWorks parts.",
        "entities": ["line", "circle", "arc", "text", "dimension"],
        "experience_recall_and_coverage": {
            "available": True,
            "workflow_position": "after domain resolution and before geometry",
            "domain_registry": str((PLUGIN_ROOT / "rules" / "engineering_domain_registry.json").resolve()),
            "catalog": str((PLUGIN_ROOT / "rules" / "experience_recall_catalog.json").resolve()),
            "context_schema": str(_runtime_file("schema", "aicad-experience-context.schema.json").resolve()),
            "coverage_schema": str(_runtime_file("schema", "aicad-review-coverage-ledger.schema.json").resolve()),
            "registered_domains": sorted(
                json.loads(
                    (PLUGIN_ROOT / "rules" / "engineering_domain_registry.json").read_text(encoding="utf-8")
                )["domains"]
            ),
            "exact_coverage_inventory_required": True,
            "rule_source_hash_closure_required": True,
            "evidence_file_hash_revalidation_required": True,
            "candidate_lessons_may_satisfy_coverage": False,
            "professional_release_granted": False,
        },
        "units": ["mm", "inch"],
        "constraints": [
            "horizontal", "vertical", "length", "parallel", "perpendicular", "collinear",
            "start_coincident", "end_coincident", "start_offset", "radius", "diameter",
            "center_coincident", "center_offset", "start_angle", "end_angle",
            "position_coincident", "position_offset", "text_height", "rotation",
            "dimension_measurement", "dimension_orientation", "base_offset",
        ],
        "artifacts": ["plan.json", "aicad", "scr", "dxf", "audit.md", "manifest.json"],
        "review_opening": {
            "policy": "reviewer_first",
            "default_target": "interactive_drawing_modifier",
            "generic_open_blocks_raw_artifacts": True,
            "native_cad_requires_explicit_user_request": True,
            "native_cad_order": ["interactive_drawing_modifier", "native_cad"],
        },
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
            "AutoCAD execution channel is ASCII and accepts LINE/CIRCLE/ARC/TEXT/DIMENSION records",
            "schema 2.0 compiles to AICAD protocol 3, or protocol 4 when native dimensions are present",
            "semantic architecture layers preserve normative linetype and lineweight through DXF, SCR, and AutoCAD",
        ],
        "architectural_drafting_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_architecture_qa.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "architectural_drafting_rules.json").resolve()),
            "complete_axis_groups": True,
            "axis_identifiers_are_plan_entities": True,
            "semantic_layer_style_transport": ["aicad-v3", "aicad-v4", "scr", "dxf", "autocad"],
            "annotation_completeness_matrix": True,
            "review_only": True,
        },
        "architectural_detail_contract": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_architecture_detail_qa.py").resolve()),
            "schema": str((PLUGIN_ROOT / "rules" / "architectural_detail_contract_v2.schema.json").resolve()),
            "symbol_profiles": str((PLUGIN_ROOT / "rules" / "architectural_symbol_profiles.json").resolve()),
            "review_renderer": str((PLUGIN_ROOT / "scripts" / "aicad_review_report.py").resolve()),
            "gates": ["complete axis identity groups", "complete production drawing set", "programme-authoritative room categories", "room equipment matrix", "typed selectable detailed object linework", "semantic interior layers", "four-purpose dimension chains", "door host-opening-sweep topology", "exhaustive typed occupancy clearance", "production authority"],
            "room_category_provenance_required": True,
            "name_based_clearance_exclusions_allowed": False,
            "precompile_required": True,
            "strict_production_only": True,
            "allow_intermediate_cad": False,
            "failure_disposition": "blocker_report_only",
            "blocker_formats": ["json", "html", "png", "launch_json"],
            "review_only": True,
        },
        "production_readiness_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_production_readiness_qa_v3.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "production_readiness_rules.json").resolve()),
            "contract_schema": str((PLUGIN_ROOT / "rules" / "production_readiness_contract_v3.schema.json").resolve()),
            "disciplines": ["mechanical", "electronics"],
            "policy": "evidence_bound_non_compensatory_fail_closed",
            "self_reported_boolean_allowed": False,
            "machine_evidence": "sha256_plus_json_pointer",
            "native_host_evidence_binding": "artifact_set_sha256",
            "recorded_approval_evidence_binding": "artifact_set_sha256_evidence_only",
            "artifact_set_binding": "artifact_id_plus_kind_plus_part_id_plus_revision_plus_normalized_relative_path_plus_size_plus_sha256",
            "expected_artifact_closure": "exact_artifact_id_kind_part_id_revision_and_path_inventory",
            "candidate_declared_closure_consistency": "parsed_machine_bom_subject_rows_and_parsed_kicad_board_copper_and_drill_inventory_to_exact_candidate_artifact_id_sha256_sets",
            "repeated_artifact_kinds_allowed": True,
            "per_subject_source_closure": True,
            "source_artifact_binding": "rule_owned_selector_to_exact_artifact_id_sha256_map",
            "conclusion": "evidence_contract_ready_only",
            "independent_evidence_authenticity_verified": False,
            "native_execution_replayed_by_this_qa": False,
            "technical_package_ready_granted_by_this_qa": False,
            "candidate_artifacts_exposed_by_this_qa": False,
            "technical_readiness_is_release_authorization": False,
            "release_authorization_requires_independent_trust_chain": True,
            "strict_production_failure_disposition": "blocker_report_only",
            "automatic_acceptance": False,
            "architecture_compatibility": {
                "script": str((PLUGIN_ROOT / "scripts" / "aicad_production_readiness_qa_v2.py").resolve()),
                "contract_schema": str((PLUGIN_ROOT / "rules" / "production_readiness_contract_v2.schema.json").resolve()),
            },
        },
        "engineering_normative_preflight": {
            "available": True,
            "domains": ["mechanical", "electronics"],
            "canonical_rules": str((PLUGIN_ROOT / "rules" / "production_readiness_rules.json").resolve()),
            "contract_schema": str((PLUGIN_ROOT / "rules" / "engineering_normative_preflight.schema.json").resolve()),
            "validator": str((PLUGIN_ROOT / "scripts" / "aicad_engineering_preflight.py").resolve()),
            "canonical_sections": ["intent", "design", "manufacturingDefinition"],
            "mechanical_gate_count": 54,
            "electronics_gate_count": 63,
            "exact_gate_inventory_required": True,
            "embedded_contract_required_for_domain_compile": True,
            "conclusion": "normative_preflight_ready_for_controlled_generation_only",
            "artifact_exposure_allowed_by_preflight": False,
            "technical_readiness_granted": False,
            "manufacturing_authorized": False,
            "fabrication_authorized": False,
        },
        "report_quality_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_report_qa.py").resolve()),
            "unique_prevention_rule_ids": True,
            "conflicting_duplicates_fail": True,
            "repeat_run_idempotence_required": True,
            "review_only": True,
        },
        "controlled_continuous_learning": {
            "available": True,
            "harvester": str((PLUGIN_ROOT / "scripts" / "aicad_lesson_harvester.py").resolve()),
            "qa": str((PLUGIN_ROOT / "scripts" / "aicad_continuous_learning_qa.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "continuous_learning_rules.json").resolve()),
            "event_schema": str((PLUGIN_ROOT / "rules" / "learning_event.schema.json").resolve()),
            "approval_schema": str((PLUGIN_ROOT / "rules" / "learning_approval_ledger.schema.json").resolve()),
            "workflow": [
                "hash-bind every failed test or gate",
                "normalize one lesson per declared failure",
                "prove exact failure-to-lesson closure",
                "deduplicate deterministically and reject conflicts",
                "require a negative regression plus red-before-fix and green-after-fix",
                "verify two distinct recorded reviewer IDs bound to bundle, target rule and newer version",
                "require external authenticated review before any manual promotion decision",
            ],
            "canonical_event_contains_current_time": False,
            "canonical_event_contains_absolute_machine_paths": False,
            "candidate_safety_locks": {
                "reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True
            },
            "candidate_output_scope": "learning/**/*.json_only",
            "automatic_promotion": False,
            "authoritative_rule_mutation": False,
            "installed_plugin_mutation": False,
            "readiness_or_authorization_unlock": False,
            "external_authenticated_review_required": True,
            "external_authenticated_review_verified": False,
            "promotion_eligible_for_manual_application": False,
            "technical_package_ready": False,
            "production_release_eligible": False,
            "manufacturing_authorized": False,
            "fabrication_authorized": False,
        },
        "packaging_dieline_qa": {
            "available": True,
            "script": str((PLUGIN_ROOT / "scripts" / "aicad_packaging_qa.py").resolve()),
            "rules": str((PLUGIN_ROOT / "rules" / "packaging_dieline_rules.json").resolve()),
            "guarded_delivery": {
                "tool": "aicad_guarded_packaging_delivery",
                "script": str((PLUGIN_ROOT / "scripts" / "aicad_guarded_delivery.py").resolve()),
                "ordered_non_compensatory_stages": [
                    "overall_user_requirement_conformance",
                    "detail_mathematical_reliability",
                    "deterministic_artifact_build_and_hash_audit",
                ],
                "candidate_exposed_on_failure": False,
            },
            "workflow": [
                "detect defect",
                "explain root cause",
                "repair locally",
                "encode prevention rule",
                "run regression test",
            ],
            "review_only": True,
        },
        "normative_governance": _normative_governance_capabilities(),
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
            "schemas": ["semantic-document", "correction", "review-handoff", "view-package", "domain-validation"],
            "review_handoff": {
                "schema_version": "1.0",
                "browser_bridges": ["clipboard", "aicad:review-handoff", "parent.postMessage", "chrome.webview.postMessage"],
                "tools": ["aicad_validate_review_handoff", "aicad_apply_review_handoff"],
                "source_hash_gate": True,
                "notes_only_apply": False,
                "corrected_reviewer_regenerated": True,
            },
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
            "native_autocad_dimension_and_dwg": "schema-2 plans emit native DIMENSION through protocol 4; reference-annotation postprocess remains a separate compatibility path",
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


def _require_civil_review_candidate(
    data: dict[str, Any],
    domain: str,
    evidence_root: str | Path | None,
) -> dict[str, Any] | None:
    if domain != "civil":
        return None
    contract = data.get("civil_review_candidate")
    if not isinstance(contract, dict):
        raise PlanError(
            "civil plans require an embedded civil_review_candidate before validation or compilation"
        )
    if evidence_root is None:
        raise PlanError("civil review candidate requires a controlled evidence_root")
    report = validate_civil_review_candidate(contract, evidence_root)
    if (
        report.get("status") != "review_candidate"
        or report.get("authorizedOutput") != "review_candidate"
    ):
        failures = [
            str(item.get("code"))
            for item in report.get("failures", [])
            if isinstance(item, dict)
        ]
        detail = ", ".join(failures[:12]) if failures else "civil_review_candidate_not_ready"
        raise PlanError(
            "civil constrained precompile gate failed; blocker_report_only: " + detail
        )
    return report


def _require_domain_validation(
    data: dict[str, Any],
    space: str,
    domain: str,
    specialist_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = evaluate_domain_plan(data, space, domain, specialist_validation)
    if report.get("status") == "failed":
        failures = [
            str(item.get("id"))
            for item in report.get("checks", [])
            if isinstance(item, dict) and item.get("status") == "fail"
        ]
        detail = ", ".join(failures) if failures else "domain_validation_not_ready"
        raise PlanError(
            f"{domain} {space} domain gate failed before artifact generation: {detail}"
        )
    return report


def validate_plan_value(
    value: Any, evidence_root: str | None = None
) -> dict[str, Any]:
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    data = _load_plan(value)
    plan = compile_plan(data)
    domain = str(data.get("drawing", {}).get("domain", "general"))
    civil_validation = _require_civil_review_candidate(data, domain, root)
    domain_validation = _require_domain_validation(data, "2d", domain, civil_validation)
    architecture_detail = _require_architecture_detail_contract(data, plan)
    engineering_preflight = _require_engineering_normative_preflight(
        data, str(data.get("drawing", {}).get("domain", "general")), root
    )
    return {
        "ok": True,
        "valid": True,
        "architecture_detail_validation": architecture_detail,
        "civil_review_validation": civil_validation,
        "engineering_normative_preflight": engineering_preflight,
        "name": plan.name,
        "domain_validation": domain_validation,
        "schema_version": plan.schema_version,
        "units": plan.units,
        "origin": list(plan.origin),
        "tolerance": plan.tolerance,
        "source_sha256": plan.source_hash,
        "entity_count": len(plan.entities),
        "entities": [{"index": index, "id": entity.id, "type": entity.type} for index, entity in enumerate(plan.entities, 1)],
    }


def _compile_data(
    data: dict[str, Any], output_dir: str | None, name: str | None, evidence_root: str | Path | None = None
) -> dict[str, Any]:
    plan = compile_plan(data)
    domain = str(data.get("drawing", {}).get("domain", "general"))
    civil_validation = _require_civil_review_candidate(data, domain, evidence_root)
    domain_validation = _require_domain_validation(data, "2d", domain, civil_validation)
    architecture_detail = _require_architecture_detail_contract(data, plan)
    engineering_preflight = _require_engineering_normative_preflight(
        data, str(data.get("drawing", {}).get("domain", "general")), evidence_root
    )
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
        "architecture_detail_validation": architecture_detail,
        "civil_review_validation": civil_validation,
        "domain_validation": domain_validation,
        "engineering_normative_preflight": engineering_preflight,
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
    review_launch: str = "never", evidence_root: str | None = None,
) -> dict[str, Any]:
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    data = _load_plan(value)
    result = _compile_data(data, output_dir, name, root)
    domain = str(data.get("drawing", {}).get("domain", "general"))
    return _attach_review(data, result, "2d", domain, name, review_launch)


def generate(
    request: str, output_dir: str | None = None, name: str | None = None,
    provider: str = "offline", review_launch: str = "never",
) -> dict[str, Any]:
    if not isinstance(request, str) or not request.strip():
        raise PlanError("request must be a non-empty string")
    generation = generate_plan_with_usage(request.strip(), provider)
    data = generation["plan"]
    used_provider = str(generation["provider"])
    result = _compile_data(data, output_dir, name)
    result["provider"] = used_provider
    result["model"] = generation["model"]
    result["request_interpreted"] = True
    provider_run = Path(str(result["output_dir"])) / f"{_safe_name(name or result['name'])}.provider-run.json"
    _write_json(provider_run, generation["runLedger"])
    result["provider_run"] = str(provider_run.resolve())
    result["usage"] = generation["runLedger"]["usage"]
    result["cost"] = generation["runLedger"]["cost"]
    result["artifacts"].append(str(provider_run.resolve()))
    domain = str(data.get("drawing", {}).get("domain", "general"))
    return _attach_review(data, result, "2d", domain, name, review_launch)


def get_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-plan.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def get_3d_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-3d-plan.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def get_architecture_detail_schema() -> dict[str, Any]:
    path = PLUGIN_ROOT / "rules" / "architectural_detail_contract_v2.schema.json"
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def validate_architecture_detail_contract_value(value: Any, plan_value: Any) -> dict[str, Any]:
    from aicad_architecture_detail_qa import evaluate, normalize_resolved_entities
    plan = compile_plan(_load_plan(plan_value))
    report = evaluate(_load_plan(value), normalize_resolved_entities(plan))
    return {"ok": bool(report.get("releaseAllowed")), **report}


def _require_architecture_detail_contract(data: dict[str, Any], plan: Any) -> dict[str, Any] | None:
    if str(data.get("drawing", {}).get("domain", "general")) != "architecture":
        return None
    contract = data.get("architecture_detail_contract")
    if not isinstance(contract, dict):
        raise PlanError("architecture plans require an embedded architecture_detail_contract before validation or compilation")
    from aicad_architecture_detail_qa import evaluate, normalize_resolved_entities
    report = evaluate(contract, normalize_resolved_entities(plan))
    if report["status"] != "pass" or not report.get("releaseAllowed"):
        failed = [name for name, item in report["checks"].items() if not item["pass"]]
        detail = ", ".join(failed) if failed else "production_release_not_authorized"
        raise PlanError("architectural production-only precompile gate failed; blocker_report_only: " + detail)
    return report


def get_engineering_preflight_schema() -> dict[str, Any]:
    path = PLUGIN_ROOT / "rules" / "engineering_normative_preflight.schema.json"
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}

def get_experience_context_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-experience-context.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def get_review_coverage_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-review-coverage-ledger.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def get_civil_review_candidate_schema() -> dict[str, Any]:
    path = _runtime_file("schema", "aicad-civil-review-candidate.schema.json")
    return {"ok": True, "schema": json.loads(path.read_text(encoding="utf-8")), "path": str(path.resolve())}


def validate_civil_review_candidate_value(
    value: Any, evidence_root: str | None = None
) -> dict[str, Any]:
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    report = validate_civil_review_candidate(_load_plan(value), root)
    return {"ok": report.get("status") == "review_candidate", **report}


def get_engineering_domain_registry() -> dict[str, Any]:
    path = PLUGIN_ROOT / "rules" / "engineering_domain_registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    maturity = assess_domain_registry(registry, plugin_root=PLUGIN_ROOT)
    if not maturity["ok"]:
        raise PlanError(
            "engineering domain maturity verification failed: "
            + "; ".join(maturity["issues"][:12])
        )
    return {
        "ok": True,
        "registry": maturity["effectiveRegistry"],
        "maturityAssessment": {
            "ok": True,
            "issues": [],
            "domains": maturity["domains"],
        },
        "path": str(path.resolve()),
    }


def recall_experience_value(
    context_value: Any,
    max_cards: int = 12,
    candidate_lesson_bundles: list[str] | None = None,
) -> dict[str, Any]:
    return recall_experience(
        _load_plan(context_value),
        PLUGIN_ROOT / "rules" / "experience_recall_catalog.json",
        PLUGIN_ROOT / "rules",
        max_cards=max_cards,
        candidate_lesson_bundles=candidate_lesson_bundles or (),
    )


def validate_review_coverage_value(
    recall_value: Any, ledger_value: Any, evidence_root: str
) -> dict[str, Any]:
    if not isinstance(evidence_root, str) or not evidence_root.strip():
        raise PlanError("review coverage validation requires a controlled evidence_root")
    return validate_coverage_ledger(
        _load_plan(recall_value),
        _load_plan(ledger_value),
        evidence_root=Path(evidence_root).expanduser(),
    )


def guarded_packaging_delivery_value(
    contract: str,
    trace: str,
    plan: str,
    geometry: str,
    template: str,
    instance: str,
    output_dir: str | None = None,
    report_dir: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Run the non-skippable packaging review/build boundary through MCP or CLI."""
    inputs = {
        "contract": contract,
        "trace": trace,
        "plan": plan,
        "geometry": geometry,
        "template": template,
        "instance": instance,
    }
    paths: dict[str, Path] = {}
    for key, value in inputs.items():
        if not isinstance(value, str) or not value.strip():
            raise PlanError(f"guarded packaging delivery requires {key} file path")
        candidate = Path(value).expanduser().resolve()
        if not candidate.is_file():
            raise PlanError(f"guarded packaging delivery {key} file does not exist: {candidate}")
        paths[key] = candidate

    safe_name = _safe_name(name or "packaging-candidate")
    if output_dir:
        candidate_dir = Path(output_dir).expanduser().resolve()
        reports = (
            Path(report_dir).expanduser().resolve()
            if report_dir
            else candidate_dir.parent / f"{safe_name}.reports"
        )
    else:
        job = _new_job_dir().resolve()
        candidate_dir = job / "candidate"
        reports = Path(report_dir).expanduser().resolve() if report_dir else job / "reports"

    from aicad_guarded_delivery import (
        _write_delivery_markdown,
        _write_json as write_guarded_json,
        run_pipeline,
    )

    report = run_pipeline(
        paths["contract"],
        paths["trace"],
        paths["plan"],
        paths["geometry"],
        paths["template"],
        paths["instance"],
        candidate_dir,
        reports,
        safe_name,
        compile_plan_fn=compile_plan_value,
    )
    report_json = reports / "guarded_delivery.json"
    report_markdown = reports / "guarded_delivery.md"
    write_guarded_json(report_json, report)
    _write_delivery_markdown(report, report_markdown)
    return {
        "ok": report["status"] == "pass",
        **report,
        "reportJson": str(report_json),
        "reportMarkdown": str(report_markdown),
    }




def get_engineering_preflight_template_value(domain: str) -> dict[str, Any]:
    from aicad_engineering_preflight import build_template
    if domain not in {"mechanical", "electronics"}:
        raise PlanError("engineering normative preflight domain must be mechanical or electronics")
    return {"ok": True, "status": "draft", "domain": domain, "template": build_template(domain)}


def validate_engineering_preflight_value(
    value: Any, evidence_root: str | None = None
) -> dict[str, Any]:
    from aicad_engineering_preflight import evaluate
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    report = evaluate(_load_plan(value), root)
    return {"ok": report["status"] == "pass", **report}


def _require_engineering_normative_preflight(
    data: dict[str, Any], domain: str, evidence_root: str | Path | None
) -> dict[str, Any] | None:
    if domain not in {"mechanical", "electronics"}:
        return None
    contract = data.get("engineering_normative_preflight")
    if not isinstance(contract, dict):
        raise PlanError(f"{domain} plans require an embedded engineering_normative_preflight before validation or compilation")
    from aicad_engineering_preflight import evaluate
    report = evaluate(contract, evidence_root)
    if report["status"] != "pass" or not report.get("generationGate", {}).get("nextStageAllowed"):
        failed = [item["code"] for item in report.get("failures", [])]
        detail = ", ".join(failed) if failed else "normative_preflight_not_ready"
        raise PlanError(f"{domain} normative precompile gate failed; blocker_report_only: {detail}")
    return report


def get_aux_schema(name: str) -> dict[str, Any]:
    filenames = {
        "semantic": "aicad-semantic-document.schema.json",
        "correction": "aicad-correction.schema.json",
        "handoff": "aicad-review-handoff.schema.json",
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
    evidence_root: str | None = None,
) -> dict[str, Any]:
    data = _load_plan(value)
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    civil_validation = _require_civil_review_candidate(data, domain, root)
    report = evaluate_domain_plan(data, space, domain, civil_validation)
    result: dict[str, Any] = {"ok": report["status"] != "failed", **report}
    result["civil_review_validation"] = civil_validation
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


def validate_review_handoff_value(plan_value: Any, handoff_value: Any, domain: str = "general") -> dict[str, Any]:
    return validate_review_handoff(_load_plan(plan_value), _load_plan(handoff_value), domain)


def apply_review_handoff_value(
    plan_value: Any, handoff_value: Any, output_dir: str | None = None,
    name: str | None = None, domain: str = "general",
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    return apply_review_handoff(
        _load_plan(plan_value), _load_plan(handoff_value), directory,
        _safe_name(name or "review-handoff"), domain,
    )


def build_multiview_value(
    value: Any, space: str, domain: str = "general", output_dir: str | None = None,
    name: str | None = None, review_launch: str = "never",
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    result = build_multiview_review(_load_plan(value), space, domain, directory, _safe_name(name or "multiview"))
    result["review_launch"] = launch_review(Path(result["artifacts"]["review_html"]), review_launch)
    return result


def open_review_request_value(
    review_html: str, cad_path: str | None = None, open_native_cad: bool = False,
    review_launch: str = "always",
) -> dict[str, Any]:
    return open_review_request(
        review_html,
        cad_path=cad_path,
        open_native_cad=open_native_cad,
        review_mode=review_launch,
    )


def validate_reference_rebuild_value(plan_value: Any, reference_value: Any) -> dict[str, Any]:
    return validate_reference_rebuild(_load_plan(plan_value), _load_plan(reference_value))


def build_reference_reconstruction_value(
    plan_value: Any, reference_value: Any, output_dir: str | None = None, name: str | None = None,
) -> dict[str, Any]:
    data = _load_plan(plan_value)
    reference = _load_plan(reference_value)
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    return build_reference_reconstruction(data, reference, directory, _safe_name(name or "reference-rebuild"))


def validate_3d_plan_value(
    value: Any, evidence_root: str | None = None
) -> dict[str, Any]:
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    data = _load_plan(value)
    result = validate_3d_plan(data)
    domain = str(data.get("part", {}).get("domain", "general"))
    civil_validation = _require_civil_review_candidate(data, domain, root)
    result["civil_review_validation"] = civil_validation
    result["domain_validation"] = _require_domain_validation(data, "3d", domain, civil_validation)
    result["engineering_normative_preflight"] = _require_engineering_normative_preflight(
        data, domain, root
    )
    return result


def build_solidworks_part(
    value: Any,
    output_dir: str | None = None,
    name: str | None = None,
    execute: bool = True,
    timeout_seconds: int = 300,
    review_launch: str = "never",
    evidence_root: str | None = None,
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _new_job_dir().resolve()
    root = Path(evidence_root).expanduser() if evidence_root else _source_parent(value)
    data = _load_plan(value)
    domain = str(data.get("part", {}).get("domain", "general"))
    civil_validation = _require_civil_review_candidate(data, domain, root)
    domain_validation = _require_domain_validation(data, "3d", domain, civil_validation)
    engineering_preflight = _require_engineering_normative_preflight(data, domain, root)
    result = compile_3d_plan(data, directory, name, execute, timeout_seconds)
    result["engineering_normative_preflight"] = engineering_preflight
    result["civil_review_validation"] = civil_validation
    result["domain_validation"] = domain_validation
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
        "name": "aicad_get_engineering_preflight_schema",
        "description": "Return the canonical mechanical/electronics generation-preflight contract schema derived from the v3 production rule inventory.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_engineering_preflight_template",
        "description": "Create an exact unresolved mechanical or electronics rule-application template; every gate must be source-bound before generation.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["domain"],
            "properties": {"domain": {"type": "string", "enum": ["mechanical", "electronics"]}},
        },
    },
    {
        "name": "aicad_validate_engineering_preflight",
        "description": "Fail closed before geometry when any canonical mechanical/electronics intent, design or manufacturing-definition rule is missing, unresolved, unbound or waived without authority.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["contract"],
            "properties": {
                "contract": {"description": "Engineering normative preflight object, JSON string, or UTF-8 file path"},
                "evidence_root": {"type": "string", "description": "Controlled root for source paths; file inputs default to their parent directory"}
            },
        },
    },
    {
        "name": "aicad_get_architecture_detail_contract_schema",
        "description": "Return the strict precompile architectural contract for complete axes, cited room programmes, equipment, dimension purposes, door host topology and exhaustive typed occupancy clearance.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_validate_architecture_detail_contract",
        "description": "Fail closed before CAD compilation when axes, room-programme provenance, detail completeness, dimension purposes, door topology, typed occupancy clearance or stage authority is unproved.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["contract", "plan"],
            "properties": {
                "contract": {"description": "Architectural detail contract object, JSON string, or UTF-8 file path"},
                "plan": {"description": "AICAD architecture plan object, JSON string, or UTF-8 file path"},
            },
        },
    },
    {
        "name": "aicad_generate",
        "description": "Generate and compile common 2D geometry from natural language. Defaults to deterministic offline interpretation.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["request"],
            "properties": {
                "request": {"type": "string", "minLength": 1},
                "output_dir": {"type": "string"}, "name": {"type": "string"},
                "provider": {"type": "string", "enum": ["offline", "auto", "openai", "deepseek"], "default": "offline"},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "never"},
            },
        },
    },
    {
        "name": "aicad_validate_plan",
        "description": "Validate an origin-anchored plan without writing CAD artifacts.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan"],
            "properties": {
                "plan": {"description": "Plan object, JSON string, or UTF-8 plan file path"},
                "evidence_root": {"type": "string"}
            },
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
                "evidence_root": {"type": "string"},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "never"},
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
        "name": "aicad_get_review_handoff_schema",
        "description": "Return the source-hash-bound interactive reviewer handoff schema.",
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
        "name": "aicad_validate_review_handoff",
        "description": "Validate a reviewer handoff against the current plan source hash and preview its exact transaction. Notes-only handoffs remain non-actionable.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "handoff"],
            "properties": {
                "plan": {"description": "2D/3D plan object, JSON string, or file path"},
                "handoff": {"description": "Reviewer handoff object, JSON string, or file path"},
                "domain": {"type": "string", "default": "general"}
            }
        }
    },
    {
        "name": "aicad_apply_review_handoff",
        "description": "Apply an actionable source-current reviewer handoff, replay dependencies, and write a corrected plan, audit, receipt, and fresh selectable modifier.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["plan", "handoff"],
            "properties": {
                "plan": {"description": "2D/3D plan object, JSON string, or file path"},
                "handoff": {"description": "Reviewer handoff object, JSON string, or file path"},
                "domain": {"type": "string", "default": "general"},
                "output_dir": {"type": "string"}, "name": {"type": "string"}
            }
        }
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
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "never"},
            },
        },
    },
    {
        "name": "aicad_open_review_request",
        "description": "Open only a source-bound selectable-vector drawing modifier for every generic view request. Raster-only wrappers fail closed. Native CAD is blocked unless open_native_cad=true reflects an explicit user request, and then opens only after the modifier.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["review_html"],
            "properties": {
                "review_html": {"type": "string", "description": "Existing local HTML satisfying aicad_selectable_vector_modifier_v1; the role marker alone is insufficient"},
                "cad_path": {"type": "string", "description": "Optional native CAD path; supplying it alone never authorizes launch"},
                "open_native_cad": {"type": "boolean", "default": False, "description": "Set true only for an explicit user request for native CAD editing/output"},
                "review_launch": {"type": "string", "enum": ["auto", "always"], "default": "always"},
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
                "output_dir": {"type": "string"}, "name": {"type": "string"},
                "evidence_root": {"type": "string"}
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
            "properties": {
                "plan": {"description": "3D plan object, JSON string, or UTF-8 plan file path"},
                "evidence_root": {"type": "string"}
            },
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
                "evidence_root": {"type": "string"},
                "review_launch": {"type": "string", "enum": ["auto", "always", "never"], "default": "never"},
            },
        },
    },
    {
        "name": "aicad_get_experience_context_schema",
        "description": "Return the strict authority-first design-context schema used before engineering geometry.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_review_coverage_schema",
        "description": "Return the exact evidence-bearing review coverage ledger schema.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_get_engineering_domain_registry",
        "description": "Return registered engineering domains, honest maturity boundaries, validators and native generation limits.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_recall_experience",
        "description": "Recall authority-first rules and advisory lessons, then build an exact change-aware coverage inventory before geometry.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["context"],
            "properties": {
                "context": {"description": "Design context object, JSON string, or UTF-8 file path"},
                "max_cards": {"type": "integer", "minimum": 1, "maximum": 50, "default": 12},
                "candidate_lesson_bundles": {
                    "type": "array", "items": {"type": "string"}, "default": []
                },
            },
        },
    },
    {
        "name": "aicad_validate_review_coverage",
        "description": "Fail closed unless every recalled coverage key has current real-file evidence under a controlled root.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["recall", "ledger", "evidence_root"],
            "properties": {
                "recall": {"description": "Recall result object, JSON string, or UTF-8 file path"},
                "ledger": {"description": "Coverage ledger object, JSON string, or UTF-8 file path"},
                "evidence_root": {"type": "string", "minLength": 1},
            },
        },
    },
    {
        "name": "aicad_guarded_packaging_delivery",
        "description": "Run packaging whole-requirement, mathematical-normality, deterministic build and SHA-256 gates in order; no candidate directory is exposed when an upstream gate fails.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["contract", "trace", "plan", "geometry", "template", "instance"],
            "properties": {
                "contract": {"type": "string", "minLength": 1},
                "trace": {"type": "string", "minLength": 1},
                "plan": {"type": "string", "minLength": 1},
                "geometry": {"type": "string", "minLength": 1},
                "template": {"type": "string", "minLength": 1},
                "instance": {"type": "string", "minLength": 1},
                "output_dir": {"type": "string"},
                "report_dir": {"type": "string"},
                "name": {"type": "string"},
            },
        },
    },
    {
        "name": "aicad_get_civil_review_candidate_schema",
        "description": "Return the strict source-bound civil coordination review-candidate schema.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "aicad_validate_civil_review_candidate",
        "description": "Validate jurisdiction, CRS/datum, field controls, alignment/profile/drainage and utility/geotechnical evidence; authorizes review_candidate only.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["candidate"],
            "properties": {
                "candidate": {"description": "Civil candidate object, JSON string, or UTF-8 file path"},
                "evidence_root": {"type": "string", "description": "Controlled source root; file inputs default to their parent directory"},
            },
        },
    },
]


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "aicad_capabilities":
        return capabilities()
    if name == "aicad_get_experience_context_schema":
        return get_experience_context_schema()
    if name == "aicad_get_review_coverage_schema":
        return get_review_coverage_schema()
    if name == "aicad_get_engineering_domain_registry":
        return get_engineering_domain_registry()
    if name == "aicad_get_civil_review_candidate_schema":
        return get_civil_review_candidate_schema()
    if name == "aicad_validate_civil_review_candidate":
        return validate_civil_review_candidate_value(arguments.get("candidate"), arguments.get("evidence_root"))
    if name == "aicad_recall_experience":
        return recall_experience_value(
            arguments.get("context"),
            arguments.get("max_cards", 12),
            arguments.get("candidate_lesson_bundles", []),
        )
    if name == "aicad_validate_review_coverage":
        return validate_review_coverage_value(
            arguments.get("recall"),
            arguments.get("ledger"),
            str(arguments.get("evidence_root", "")),
        )
    if name == "aicad_guarded_packaging_delivery":
        return guarded_packaging_delivery_value(
            str(arguments.get("contract", "")),
            str(arguments.get("trace", "")),
            str(arguments.get("plan", "")),
            str(arguments.get("geometry", "")),
            str(arguments.get("template", "")),
            str(arguments.get("instance", "")),
            arguments.get("output_dir"),
            arguments.get("report_dir"),
            arguments.get("name"),
        )
    if name == "aicad_get_plan_schema":
        return get_schema()
    if name == "aicad_get_engineering_preflight_schema":
        return get_engineering_preflight_schema()
    if name == "aicad_get_engineering_preflight_template":
        return get_engineering_preflight_template_value(str(arguments.get("domain", "")))
    if name == "aicad_validate_engineering_preflight":
        return validate_engineering_preflight_value(arguments.get("contract"), arguments.get("evidence_root"))
    if name == "aicad_get_architecture_detail_contract_schema":
        return get_architecture_detail_schema()
    if name == "aicad_validate_architecture_detail_contract":
        return validate_architecture_detail_contract_value(arguments.get("contract"), arguments.get("plan"))
    if name == "aicad_generate":
        return generate(arguments.get("request", ""), arguments.get("output_dir"), arguments.get("name"), arguments.get("provider", "offline"), arguments.get("review_launch", "never"))
    if name == "aicad_validate_plan":
        return validate_plan_value(arguments.get("plan"), arguments.get("evidence_root"))
    if name == "aicad_compile_plan":
        return compile_plan_value(
            arguments.get("plan"), arguments.get("output_dir"), arguments.get("name"),
            arguments.get("review_launch", "never"), arguments.get("evidence_root"),
        )
    if name == "aicad_get_semantic_schema":
        return get_aux_schema("semantic")
    if name == "aicad_get_correction_schema":
        return get_aux_schema("correction")
    if name == "aicad_get_review_handoff_schema":
        return get_aux_schema("handoff")
    if name == "aicad_get_domain_validation_schema":
        return get_aux_schema("domain")
    if name == "aicad_validate_domain_plan":
        return validate_domain_value(
            arguments.get("plan"), arguments.get("space", "2d"), arguments.get("domain", "general"),
            arguments.get("output_dir"), arguments.get("name"), arguments.get("evidence_root"),
        )
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
    if name == "aicad_validate_review_handoff":
        return validate_review_handoff_value(
            arguments.get("plan"), arguments.get("handoff"), arguments.get("domain", "general"),
        )
    if name == "aicad_apply_review_handoff":
        return apply_review_handoff_value(
            arguments.get("plan"), arguments.get("handoff"), arguments.get("output_dir"),
            arguments.get("name"), arguments.get("domain", "general"),
        )
    if name == "aicad_build_multiview_review":
        return build_multiview_value(
            arguments.get("plan"), arguments.get("space", "2d"), arguments.get("domain", "general"),
            arguments.get("output_dir"), arguments.get("name"), arguments.get("review_launch", "never"),
        )
    if name == "aicad_open_review_request":
        return open_review_request_value(
            str(arguments.get("review_html", "")),
            arguments.get("cad_path"),
            bool(arguments.get("open_native_cad", False)),
            str(arguments.get("review_launch", "always")),
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
        return validate_3d_plan_value(arguments.get("plan"), arguments.get("evidence_root"))
    if name == "aicad_build_solidworks_part":
        return build_solidworks_part(
            arguments.get("plan"), arguments.get("output_dir"), arguments.get("name"),
            arguments.get("execute", True), arguments.get("timeout_seconds", 300), arguments.get("review_launch", "never"),
            arguments.get("evidence_root"),
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
                {"uri": "aicad://review-handoff-schema", "name": "AICAD Review Handoff Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://view-package-schema", "name": "AICAD View Package Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://domain-validation-schema", "name": "AICAD Domain Validation Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://reference-rebuild-schema", "name": "AICAD Reference Rebuild Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://experience-context-schema", "name": "AICAD Experience Context Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://review-coverage-schema", "name": "AICAD Review Coverage Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://civil-review-candidate-schema", "name": "AICAD Civil Review Candidate Schema", "mimeType": "application/schema+json"},
                {"uri": "aicad://engineering-domain-registry", "name": "AICAD Engineering Domain Registry", "mimeType": "application/json"},
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
            elif uri == "aicad://review-handoff-schema":
                payload = get_aux_schema("handoff")["schema"]
            elif uri == "aicad://domain-validation-schema":
                payload = get_aux_schema("domain")["schema"]
            elif uri == "aicad://view-package-schema":
                payload = get_aux_schema("view")["schema"]
            elif uri == "aicad://reference-rebuild-schema":
                payload = get_aux_schema("reference")["schema"]
            elif uri == "aicad://experience-context-schema":
                payload = get_experience_context_schema()["schema"]
            elif uri == "aicad://review-coverage-schema":
                payload = get_review_coverage_schema()["schema"]
            elif uri == "aicad://civil-review-candidate-schema":
                payload = get_civil_review_candidate_schema()["schema"]
            elif uri == "aicad://engineering-domain-registry":
                payload = get_engineering_domain_registry()["registry"]
            elif uri == "aicad://capabilities":
                payload = capabilities()
            else:
                raise PlanError(f"Unknown resource '{uri}'")
            schema_resources = {
                "aicad://plan-schema",
                "aicad://3d-plan-schema",
                "aicad://semantic-schema",
                "aicad://correction-schema",
                "aicad://review-handoff-schema",
                "aicad://view-package-schema",
                "aicad://domain-validation-schema",
                "aicad://reference-rebuild-schema",
                "aicad://experience-context-schema",
                "aicad://review-coverage-schema",
                "aicad://civil-review-candidate-schema",
            }
            mime_type = "application/schema+json" if uri in schema_resources else "application/json"
            response["result"] = {"contents": [{"uri": uri, "mimeType": mime_type, "text": json.dumps(payload, ensure_ascii=False)}]}
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
    commands.add_parser("architecture-detail-schema")
    architecture_detail_parser = commands.add_parser("architecture-detail-validate")
    architecture_detail_parser.add_argument("--contract", required=True)
    architecture_detail_parser.add_argument("--plan", required=True)
    commands.add_parser("schema3d")
    commands.add_parser("semantic-schema")
    commands.add_parser("correction-schema")
    commands.add_parser("review-handoff-schema")
    commands.add_parser("view-schema")
    commands.add_parser("domain-schema")
    commands.add_parser("experience-context-schema")
    commands.add_parser("review-coverage-schema")
    commands.add_parser("domain-registry")
    commands.add_parser("civil-review-schema")
    civil_review_parser = commands.add_parser("civil-review-validate")
    civil_review_parser.add_argument("--candidate", required=True)
    civil_review_parser.add_argument("--evidence-root")
    experience_parser = commands.add_parser("experience-recall")
    experience_parser.add_argument("--context", required=True)
    experience_parser.add_argument("--max-cards", type=int, default=12)
    experience_parser.add_argument("--candidate-lesson-bundle", action="append", default=[])
    coverage_parser = commands.add_parser("coverage-validate")
    coverage_parser.add_argument("--recall", required=True)
    coverage_parser.add_argument("--ledger", required=True)
    coverage_parser.add_argument("--evidence-root", required=True)
    guarded_packaging_parser = commands.add_parser("guarded-packaging-delivery")
    guarded_packaging_parser.add_argument("--contract", required=True)
    guarded_packaging_parser.add_argument("--trace", required=True)
    guarded_packaging_parser.add_argument("--plan", required=True)
    guarded_packaging_parser.add_argument("--geometry", required=True)
    guarded_packaging_parser.add_argument("--template", required=True)
    guarded_packaging_parser.add_argument("--instance", required=True)
    guarded_packaging_parser.add_argument("--out")
    guarded_packaging_parser.add_argument("--report-dir")
    guarded_packaging_parser.add_argument("--name")
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
    generate_parser.add_argument("--provider", choices=["offline", "auto", "openai", "deepseek"], default="offline")
    generate_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="never")
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--plan", required=True)
    compile_parser = commands.add_parser("compile")
    validate_parser.add_argument("--evidence-root")
    compile_parser.add_argument("--plan", required=True)
    compile_parser.add_argument("--out")
    compile_parser.add_argument("--name")
    compile_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="never")
    validate3d_parser = commands.add_parser("validate3d")
    compile_parser.add_argument("--evidence-root")
    validate3d_parser.add_argument("--plan", required=True)
    build3d_parser = commands.add_parser("build3d")
    validate3d_parser.add_argument("--evidence-root")
    build3d_parser.add_argument("--plan", required=True)
    build3d_parser.add_argument("--out")
    build3d_parser.add_argument("--name")
    build3d_parser.add_argument("--no-execute", action="store_true")
    build3d_parser.add_argument("--timeout", type=int, default=300)
    build3d_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="never")
    describe_parser = commands.add_parser("describe")
    build3d_parser.add_argument("--evidence-root")
    describe_parser.add_argument("--plan", required=True)
    describe_parser.add_argument("--space", choices=["2d", "3d"], required=True)
    describe_parser.add_argument("--domain", default="general")
    domain_parser = commands.add_parser("domain-validate")
    domain_parser.add_argument("--plan", required=True)
    domain_parser.add_argument("--space", choices=["2d", "3d"], required=True)
    domain_parser.add_argument("--domain", default="general")
    domain_parser.add_argument("--out")
    domain_parser.add_argument("--name")
    domain_parser.add_argument("--evidence-root")
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
    validate_handoff_parser = commands.add_parser("validate-review-handoff")
    validate_handoff_parser.add_argument("--plan", required=True)
    validate_handoff_parser.add_argument("--handoff", required=True)
    validate_handoff_parser.add_argument("--domain", default="general")
    apply_handoff_parser = commands.add_parser("apply-review-handoff")
    apply_handoff_parser.add_argument("--plan", required=True)
    apply_handoff_parser.add_argument("--handoff", required=True)
    apply_handoff_parser.add_argument("--domain", default="general")
    apply_handoff_parser.add_argument("--out")
    apply_handoff_parser.add_argument("--name")
    multiview_parser = commands.add_parser("multiview")
    multiview_parser.add_argument("--plan", required=True)
    multiview_parser.add_argument("--space", choices=["2d", "3d"], required=True)
    multiview_parser.add_argument("--domain", default="general")
    multiview_parser.add_argument("--out")
    multiview_parser.add_argument("--name")
    multiview_parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="never")
    open_review_parser = commands.add_parser("open-review")
    open_review_parser.add_argument("--review-html", required=True)
    open_review_parser.add_argument("--cad-path")
    open_review_parser.add_argument("--open-native-cad", action="store_true")
    open_review_parser.add_argument("--review-launch", choices=["auto", "always"], default="always")
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
        "architecture-detail-schema": get_architecture_detail_schema,
        "architecture-detail-validate": lambda: validate_architecture_detail_contract_value(args.contract, args.plan),
        "schema3d": get_3d_schema,
        "semantic-schema": lambda: get_aux_schema("semantic"),
        "correction-schema": lambda: get_aux_schema("correction"),
        "review-handoff-schema": lambda: get_aux_schema("handoff"),
        "view-schema": lambda: get_aux_schema("view"),
        "domain-schema": lambda: get_aux_schema("domain"),
        "experience-context-schema": get_experience_context_schema,
        "review-coverage-schema": get_review_coverage_schema,
        "domain-registry": get_engineering_domain_registry,
        "civil-review-schema": get_civil_review_candidate_schema,
        "civil-review-validate": lambda: validate_civil_review_candidate_value(args.candidate, args.evidence_root),
        "experience-recall": lambda: recall_experience_value(args.context, args.max_cards, args.candidate_lesson_bundle),
        "coverage-validate": lambda: validate_review_coverage_value(
            args.recall, args.ledger, args.evidence_root,
        ),
        "guarded-packaging-delivery": lambda: guarded_packaging_delivery_value(
            args.contract, args.trace, args.plan, args.geometry, args.template, args.instance,
            args.out, args.report_dir, args.name,
        ),
        "reference-schema": lambda: get_aux_schema("reference"),
        "reference-validate": lambda: validate_reference_rebuild_value(args.plan, args.reference),
        "reference-build": lambda: build_reference_reconstruction_value(args.plan, args.reference, args.out, args.name),
        "solidworks-doctor": solidworks_doctor,
        "generate": generate_action,
        "validate": lambda: validate_plan_value(args.plan, args.evidence_root),
        "compile": lambda: compile_plan_value(args.plan, args.out, args.name, args.review_launch, args.evidence_root),
        "validate3d": lambda: validate_3d_plan_value(args.plan, args.evidence_root),
        "build3d": lambda: build_solidworks_part(args.plan, args.out, args.name, not args.no_execute, args.timeout, args.review_launch, args.evidence_root),
        "describe": lambda: describe_plan_value(args.plan, args.space, args.domain),
        "domain-validate": lambda: validate_domain_value(args.plan, args.space, args.domain, args.out, args.name, args.evidence_root),
        "preview-correction": lambda: preview_correction_value(args.plan, args.correction, args.domain),
        "apply-correction": lambda: apply_correction_value(args.plan, args.correction, args.out, args.name, args.domain),
        "validate-review-handoff": lambda: validate_review_handoff_value(args.plan, args.handoff, args.domain),
        "apply-review-handoff": lambda: apply_review_handoff_value(args.plan, args.handoff, args.out, args.name, args.domain),
        "multiview": lambda: build_multiview_value(args.plan, args.space, args.domain, args.out, args.name, args.review_launch),
        "open-review": lambda: open_review_request_value(
            args.review_html, args.cad_path, args.open_native_cad, args.review_launch,
        ),
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
