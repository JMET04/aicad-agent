from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
import types
from collections import Counter
from pathlib import Path, PurePosixPath


EXPECTED_VERSION = "1.13.0"

EXPECTED_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
    "comparativeSuperiorityClaimAllowed": False,
}
FORBIDDEN_NAMES = {"__pycache__", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".rej", ".orig"}
FORBIDDEN_BINARY_NAMES = {
    "AiCad.SolidWorksHost.exe",
    "SolidWorks.Interop.sldworks.dll",
    "SolidWorks.Interop.swconst.dll",
}
FORBIDDEN_TEXT = (
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"D:\\CAD绘制插件", re.IGNORECASE),
    re.compile("\u5218\u4f73\u660e"),
    re.compile("g" + r"hp_[A-Za-z0-9]+"),
    re.compile("github_" + r"pat_[A-Za-z0-9_]+"),
    re.compile(r"BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY"),
)
SOURCE_INPUT_POLICY = "agent_plugin_builder_v1"
SOURCE_TREE_ROOTS = (
    "agent-plugin/aicad-agent",
    "src/aicad",
    "plugin/AiCadConstraint.bundle",
)
SOURCE_TOP_LEVEL_FILE_ROOTS = ("schema", "examples")
SOURCE_FIXED_FILES = (
    "scripts/build-agent-plugin.ps1",
    "scripts/verify_release_package.py",
    "solidworks-host/AiCad.SolidWorksHost/Program.cs",
    "solidworks-host/AiCad.SolidWorksHost/AiCad.SolidWorksHost.csproj",
    "scripts/build-solidworks-host.ps1",
)

EXPECTED_LEARNING_SCHEMA = "aicad_continuous_learning_rules_v1"
EXPECTED_LEARNING_SCOPE = "test_and_gate_failures_across_all_aicad_domains"
EXPECTED_LEARNING_EVENT_POLICY = "no_implicit_timestamp_no_absolute_machine_path_hash_bound_safe_relative_evidence"
EXPECTED_LEARNING_FIELDS = {
    "schema", "scope", "canonicalEventPolicy", "controls", "preventionRules",
    "failureAliases", "candidateSafetyLocks", "promotionPolicy",
}
EXPECTED_LEARNING_CONTROL_IDS = {f"CL-G{index:03d}" for index in range(1, 10)}
EXPECTED_LEARNING_LOCKS = {
    "reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True,
}
EXPECTED_LEARNING_POLICY = {
    "automaticPromotion": False,
    "authoritativeRuleMutationByTool": False,
    "installedPluginMutationByTool": False,
    "testDeletionAllowed": False,
    "ruleWeakeningAllowed": False,
    "requiresTwoDistinctRecordedReviewerIds": True,
    "requiresExternalAuthenticatedReview": True,
    "requiresBundleRuleVersionBinding": True,
    "requiresStrictlyNewerVersion": True,
    "requiresRedBeforeFixGreenAfterFix": True,
    "requiresUnrelatedSuitesPass": True,
}
LEARNING_DOMAINS = {
    "general", "software", "release", "cad", "architecture", "packaging",
    "mechanical", "electronics",
}
LEARNING_CONTROL_FIELDS = {"id", "name", "requirement", "requiredRegression"}
LEARNING_RULE_FIELDS = {"id", "domain", "name", "symptom", "rootCause", "prevention", "requiredRegression"}
LEARNING_ALIAS_FIELDS = {"alias", "domain", "ruleId", "failingCheck"}
LEARNING_ALIAS_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_]+)+$")
LEARNING_RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-G[0-9]{3}$")
LEARNING_TECHNICAL_AUTHORIZATION_FIELDS = frozenset({
    "technicalPackageReady", "productionReleaseEligible",
    "manufacturingAuthorized", "fabricationAuthorized",
})
LEARNING_CANDIDATE_FALSE_FIELDS = frozenset({
    "promotionEligibleForManualApplication", "independentApprovalAuthenticityVerified",
    "externalAuthenticatedReviewVerified", "promotionPerformed",
    "authoritativeRulesModified", "installedPluginModified",
    *LEARNING_TECHNICAL_AUTHORIZATION_FIELDS,
})
LEARNING_AST_REQUIRED_FALSE_FIELDS = {
    "core": LEARNING_CANDIDATE_FALSE_FIELDS,
    "qa": frozenset({
        "promotionEligibleForManualApplication", "externalAuthenticatedReviewVerified",
        "promotionPerformed", "authoritativeRulesModified", "installedPluginModified",
        *LEARNING_TECHNICAL_AUTHORIZATION_FIELDS,
    }),
    "harvester": frozenset({
        "authoritativeRulesModified", "installedPluginModified",
        *LEARNING_TECHNICAL_AUTHORIZATION_FIELDS,
    }),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


LEARNING_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
LEARNING_SCHEMA_SPECS = {
    "learning_event.schema.json": {
        "id": "https://github.com/JMET04/aicad-agent/rules/learning_event.schema.json",
        "topLevel": {"$schema", "$id", "title", "oneOf", "$defs"},
        "defs": {
            "safetyLocks", "fileEntry", "closure", "candidateRule", "failedCheck",
            "failureReport", "mapping", "sourceReport", "lesson", "coverage", "lessonBundle",
        },
    },
    "learning_approval_ledger.schema.json": {
        "id": "https://github.com/JMET04/aicad-agent/rules/learning_approval_ledger.schema.json",
        "topLevel": {
            "$schema", "$id", "title", "type", "additionalProperties", "required",
            "properties", "$defs",
        },
        "defs": {"semver", "fileEntry", "safetyLocks", "approval"},
    },
}
LEARNING_SCHEMA_TYPES = {"null", "boolean", "object", "array", "number", "string", "integer"}


def _learning_schema_is_valid(payload: object, spec: dict[str, object]) -> bool:
    if not isinstance(payload, dict):
        return False
    if (
        payload.get("$schema") != LEARNING_SCHEMA_DRAFT
        or payload.get("$id") != spec["id"]
        or set(payload) != spec["topLevel"]
    ):
        return False
    definitions = payload.get("$defs")
    if not isinstance(definitions, dict) or set(definitions) != spec["defs"]:
        return False
    if not all(isinstance(name, str) and isinstance(value, dict) for name, value in definitions.items()):
        return False
    if "oneOf" in payload and payload["oneOf"] != [
        {"$ref": "#/$defs/failureReport"}, {"$ref": "#/$defs/lessonBundle"}
    ]:
        return False

    def visit(node: object) -> bool:
        if not isinstance(node, dict):
            return False
        reference = node.get("$ref")
        if reference is not None:
            if (
                not isinstance(reference, str)
                or not reference.startswith("#/$defs/")
                or reference.removeprefix("#/$defs/") not in definitions
            ):
                return False
        schema_type = node.get("type")
        if schema_type is not None:
            if isinstance(schema_type, str):
                if schema_type not in LEARNING_SCHEMA_TYPES:
                    return False
            elif (
                not isinstance(schema_type, list)
                or not schema_type
                or any(not isinstance(value, str) or value not in LEARNING_SCHEMA_TYPES for value in schema_type)
                or len(schema_type) != len(set(schema_type))
            ):
                return False
        properties = node.get("properties")
        if properties is not None:
            if not isinstance(properties, dict) or any(
                not isinstance(name, str) or not visit(value) for name, value in properties.items()
            ):
                return False
        required = node.get("required")
        if required is not None:
            if (
                not isinstance(required, list)
                or not required
                or any(not isinstance(value, str) or not value for value in required)
                or len(required) != len(set(required))
                or not isinstance(properties, dict)
                or not set(required).issubset(properties)
            ):
                return False
        for keyword in ("oneOf", "anyOf", "allOf"):
            branches = node.get(keyword)
            if branches is not None and (
                not isinstance(branches, list) or not branches or any(not visit(branch) for branch in branches)
            ):
                return False
        items = node.get("items")
        if items is not None and not visit(items):
            return False
        additional = node.get("additionalProperties")
        if additional is not None and not isinstance(additional, bool) and not visit(additional):
            return False
        enum = node.get("enum")
        if enum is not None and (not isinstance(enum, list) or not enum):
            return False
        nested_defs = node.get("$defs")
        if nested_defs is not None and (
            not isinstance(nested_defs, dict) or any(not visit(value) for value in nested_defs.values())
        ):
            return False
        return True

    return visit(payload)


def validate_learning_schema_documents(plugin_root: Path, errors: list[str]) -> None:
    for name, spec in LEARNING_SCHEMA_SPECS.items():
        path = plugin_root / "rules" / name
        try:
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                raise UnicodeError("BOM is not permitted")
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append(f"continuous-learning-schema-document:{name}")
            continue
        if not _learning_schema_is_valid(payload, spec):
            errors.append(f"continuous-learning-schema-document:{name}")


def validate_continuous_learning_catalog(payload: object, errors: list[str]) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != EXPECTED_LEARNING_SCHEMA:
        errors.append("continuous-learning-schema")
        return
    if set(payload) != EXPECTED_LEARNING_FIELDS:
        errors.append("continuous-learning-top-level-fields")
    if payload.get("scope") != EXPECTED_LEARNING_SCOPE:
        errors.append("continuous-learning-scope")
    if payload.get("canonicalEventPolicy") != EXPECTED_LEARNING_EVENT_POLICY:
        errors.append("continuous-learning-event-policy")
    if payload.get("candidateSafetyLocks") != EXPECTED_LEARNING_LOCKS:
        errors.append("continuous-learning-locks")
    if payload.get("promotionPolicy") != EXPECTED_LEARNING_POLICY:
        errors.append("continuous-learning-promotion-policy")

    controls = payload.get("controls")
    rules = payload.get("preventionRules")
    aliases = payload.get("failureAliases")
    control_rows = controls if isinstance(controls, list) else []
    rule_rows = rules if isinstance(rules, list) else []
    alias_rows = aliases if isinstance(aliases, list) else []

    control_shape_ok = bool(control_rows) and all(
        isinstance(row, dict) and set(row) == LEARNING_CONTROL_FIELDS for row in control_rows
    )
    rule_shape_ok = bool(rule_rows) and all(
        isinstance(row, dict) and set(row) == LEARNING_RULE_FIELDS for row in rule_rows
    )
    alias_shape_ok = bool(alias_rows) and all(
        isinstance(row, dict) and set(row) == LEARNING_ALIAS_FIELDS for row in alias_rows
    )
    if not control_shape_ok:
        errors.append("continuous-learning-control-inventory")
    if not rule_shape_ok:
        errors.append("continuous-learning-prevention-rule-inventory")
    if not alias_shape_ok:
        errors.append("continuous-learning-alias-inventory")

    def nonempty_fields(rows: list[object], fields: set[str]) -> bool:
        return all(
            isinstance(row, dict)
            and all(isinstance(row.get(field), str) and bool(row[field].strip()) for field in fields)
            for row in rows
        )

    if not nonempty_fields(control_rows, LEARNING_CONTROL_FIELDS):
        errors.append("continuous-learning-control-fields")
    if not nonempty_fields(rule_rows, LEARNING_RULE_FIELDS):
        errors.append("continuous-learning-prevention-rule-fields")
    if any(
        isinstance(row, dict)
        and (not isinstance(row.get("requiredRegression"), str) or not row["requiredRegression"].strip())
        for row in control_rows + rule_rows
    ):
        errors.append("continuous-learning-required-regression")

    control_values = [row.get("id") for row in control_rows if isinstance(row, dict)]
    control_ids = [value for value in control_values if isinstance(value, str)]
    rule_values = [row.get("id") for row in rule_rows if isinstance(row, dict)]
    rule_ids = [value for value in rule_values if isinstance(value, str)]
    if (
        len(control_ids) != len(control_values)
        or set(control_ids) != EXPECTED_LEARNING_CONTROL_IDS
        or len(control_ids) != len(set(control_ids))
        or any(not LEARNING_RULE_ID_RE.fullmatch(value) for value in control_ids)
    ):
        errors.append("continuous-learning-control-inventory")
    if (
        len(rule_ids) != len(rule_values)
        or not rule_ids
        or len(rule_ids) != len(set(rule_ids))
        or any(not LEARNING_RULE_ID_RE.fullmatch(value) for value in rule_ids)
        or bool(set(control_ids) & set(rule_ids))
        or any(not isinstance(row, dict) or row.get("domain") not in LEARNING_DOMAINS for row in rule_rows)
    ):
        errors.append("continuous-learning-prevention-rule-inventory")

    alias_values = [row.get("alias") for row in alias_rows if isinstance(row, dict)]
    alias_names = [value for value in alias_values if isinstance(value, str)]
    alias_id_values = [row.get("ruleId") for row in alias_rows if isinstance(row, dict)]
    alias_ids = [value for value in alias_id_values if isinstance(value, str)]
    if (
        len(alias_names) != len(alias_values)
        or not alias_names
        or len(alias_names) != len(set(alias_names))
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("alias"), str)
            or not LEARNING_ALIAS_RE.fullmatch(row["alias"])
            or row.get("domain") not in LEARNING_DOMAINS
            or not row["alias"].startswith(str(row["domain"]) + ".")
            or not isinstance(row.get("failingCheck"), str)
            or not row["failingCheck"].strip()
            for row in alias_rows
        )
    ):
        errors.append("continuous-learning-alias-inventory")
    if (
        len(alias_ids) != len(alias_id_values)
        or any(rule_id not in set(rule_ids) for rule_id in alias_ids)
    ):
        errors.append("continuous-learning-alias-rule-binding")
    if set(rule_ids) - set(alias_ids):
        errors.append("continuous-learning-prevention-rule-coverage")


def _string_constant(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _subscript_key(node: ast.AST) -> str | None:
    return _string_constant(node.slice) if isinstance(node, ast.Subscript) else None


def _validate_learning_source_ast(label: str, path: Path, errors: list[str]) -> ast.Module | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        errors.append(f"continuous-learning-{label}-ast:{type(exc).__name__}")
        return None
    required = LEARNING_AST_REQUIRED_FALSE_FIELDS[label]
    seen: set[str] = set()

    def record(field: str | None, value: ast.AST | None, location: str) -> None:
        if field not in LEARNING_CANDIDATE_FALSE_FIELDS:
            return
        seen.add(field)
        if not (isinstance(value, ast.Constant) and value.value is False):
            errors.append(f"continuous-learning-{label}-authorization:{field}:{location}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                record(_string_constant(key), value, f"line-{node.lineno}")
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                record(keyword.arg, keyword.value, f"line-{node.lineno}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                record(_subscript_key(target), value, f"line-{node.lineno}")
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                field = _subscript_key(target)
                if field in LEARNING_CANDIDATE_FALSE_FIELDS:
                    errors.append(f"continuous-learning-{label}-authorization:{field}:delete-line-{node.lineno}")
    for field in sorted(required - seen):
        errors.append(f"continuous-learning-{label}-authorization-missing:{field}")
    return tree


def _harvester_output_is_controlled(tree: ast.Module) -> bool:
    main = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    if main is None:
        return False
    controlled_names: set[str] = set()
    atomic_calls: list[ast.Call] = []
    for node in ast.walk(main):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if (
                isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "controlled_learning_output_path"
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                controlled_names.update(target.id for target in targets if isinstance(target, ast.Name))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_atomic_json":
            atomic_calls.append(node)
    return bool(atomic_calls) and all(
        len(call.args) >= 2 and isinstance(call.args[1], ast.Name)
        and call.args[1].id in controlled_names
        for call in atomic_calls
    )


def _load_learning_runtime(plugin_root: Path) -> tuple[object, list[str]]:
    package_root = plugin_root / "runtime" / "src" / "aicad"
    package_name = f"_aicad_learning_boundary_{abs(hash(str(package_root.resolve())))}"
    loaded_names: list[str] = []
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_root)]
    package.__package__ = package_name
    sys.modules[package_name] = package
    loaded_names.append(package_name)
    try:
        for leaf in ("reporting", "continuous_learning"):
            name = f"{package_name}.{leaf}"
            spec = importlib.util.spec_from_file_location(name, package_root / f"{leaf}.py")
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {leaf}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            loaded_names.append(name)
            spec.loader.exec_module(module)
        return sys.modules[f"{package_name}.continuous_learning"], loaded_names
    except Exception:
        for name in reversed(loaded_names):
            sys.modules.pop(name, None)
        raise


def _runtime_rejects(module: object, call, label: str, errors: list[str]) -> None:
    try:
        call()
    except module.ReportInvariantError:
        return
    except Exception as exc:
        errors.append(f"continuous-learning-runtime-{label}-wrong-error:{type(exc).__name__}")
        return
    errors.append(f"continuous-learning-runtime-{label}-not-rejected")


def _validate_learning_runtime_behavior(plugin_root: Path, errors: list[str]) -> None:
    try:
        module, loaded_names = _load_learning_runtime(plugin_root)
    except Exception as exc:
        errors.append(f"continuous-learning-runtime-import:{type(exc).__name__}")
        return
    try:
        for surface, function_name, fields_name, schema in (
            ("report", "canonical_failure_report", "_FAILURE_REPORT_FIELDS", "aicad_test_failure_report_v1"),
            ("bundle", "audit_lesson_bundle", "_LESSON_BUNDLE_FIELDS", "aicad_lesson_bundle_v1"),
            ("ledger", "audit_promotion_ledger", "_APPROVAL_LEDGER_FIELDS", "aicad_learning_approval_ledger_v1"),
        ):
            function = getattr(module, function_name)
            payload = {key: None for key in getattr(module, fields_name)}
            payload["schema"] = schema
            extra = dict(payload)
            extra["unexpectedAuthorization"] = True
            wrong_schema = dict(payload)
            wrong_schema["schema"] = "aicad_untrusted_v0"
            invoke = (
                (lambda value: function(plugin_root, value, current_version="1.13.0"))
                if surface == "ledger" else (lambda value: function(plugin_root, value))
            )
            _runtime_rejects(module, lambda value=extra, call=invoke: call(value), f"{surface}-extra-key", errors)
            _runtime_rejects(module, lambda value=wrong_schema, call=invoke: call(value), f"{surface}-schema", errors)
        if module.controlled_learning_output_path("learning/candidate.json") != "learning/candidate.json":
            errors.append("continuous-learning-runtime-controlled-output-valid")
        for unsafe in (
            "candidate.json", "rules/continuous_learning_rules.json",
            "scripts/aicad_lesson_harvester.py", "runtime/src/aicad/continuous_learning.py",
            ".codex-plugin/plugin.json", "learning/../rules/continuous_learning_rules.json",
        ):
            _runtime_rejects(
                module, lambda value=unsafe: module.controlled_learning_output_path(value),
                "authoritative-output:" + unsafe, errors,
            )
    finally:
        for name in reversed(loaded_names):
            sys.modules.pop(name, None)


def validate_continuous_learning_runtime_boundary(plugin_root: Path, errors: list[str]) -> None:
    paths = {
        "core": plugin_root / "runtime" / "src" / "aicad" / "continuous_learning.py",
        "qa": plugin_root / "scripts" / "aicad_continuous_learning_qa.py",
        "harvester": plugin_root / "scripts" / "aicad_lesson_harvester.py",
    }
    trees: dict[str, ast.Module] = {}
    for label, path in paths.items():
        tree = _validate_learning_source_ast(label, path, errors)
        if tree is not None:
            trees[label] = tree
    harvester = trees.get("harvester")
    if harvester is None or not _harvester_output_is_controlled(harvester):
        errors.append("continuous-learning-harvester-output-boundary")
    _validate_learning_runtime_behavior(plugin_root, errors)


def source_files(source_root: Path, include_solidworks_interop: bool) -> set[str]:
    result: set[str] = set()

    def add_tree(relative: str) -> None:
        root = source_root / relative
        if not root.is_dir():
            return
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(source_root).as_posix()
            if any(part in FORBIDDEN_NAMES for part in PurePosixPath(rel).parts):
                continue
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:
                continue
            result.add(rel)

    for relative in SOURCE_TREE_ROOTS:
        add_tree(relative)
    for relative in SOURCE_TOP_LEVEL_FILE_ROOTS:
        directory = source_root / relative
        if directory.is_dir():
            result.update(
                path.relative_to(source_root).as_posix()
                for path in directory.iterdir()
                if path.is_file() and not path.is_symlink()
            )
    for relative in SOURCE_FIXED_FILES:
        if (source_root / relative).is_file():
            result.add(relative)
    if include_solidworks_interop:
        add_tree("build/solidworks-host")
    return result


def verify_entries(
    *,
    entries: object,
    expected_paths: set[str],
    root: Path,
    label: str,
    errors: list[str],
) -> int:
    if not isinstance(entries, list):
        errors.append(f"{label}-not-list")
        return 0
    normalized: list[str] = []
    rows: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{label}-entry-not-object")
            continue
        relative = safe_relative(entry.get("path"))
        if relative is None:
            errors.append(f"unsafe-{label}-path:{entry.get('path')}")
            continue
        normalized.append(relative)
        rows[relative] = entry
    for relative, count in Counter(normalized).items():
        if count != 1:
            errors.append(f"duplicate-{label}-path:{relative}")
    actual_set = set(normalized)
    for relative in sorted(expected_paths - actual_set):
        errors.append(f"{label}-unlisted:{relative}")
    for relative in sorted(actual_set - expected_paths):
        errors.append(f"{label}-extra:{relative}")
    resolved_root = root.resolve()
    for relative in sorted(actual_set & expected_paths):
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            errors.append(f"{label}-missing:{relative}")
            continue
        if path.is_symlink() or resolved_root not in resolved.parents:
            errors.append(f"{label}-escape:{relative}")
            continue
        entry = rows[relative]
        if path.stat().st_size != entry.get("size"):
            errors.append(f"{label}-size:{relative}")
        if sha256(path) != entry.get("sha256"):
            errors.append(f"{label}-sha256:{relative}")
    return len(actual_set)



def verify_v3_evidence_contract(root: Path, errors: list[str]) -> None:
    rules_path = root / "rules" / "production_readiness_rules.json"
    schema_path = root / "rules" / "production_readiness_contract_v3.schema.json"
    qa_path = root / "scripts" / "aicad_production_readiness_qa_v3.py"
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        qa_text = qa_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"v3-contract-unreadable:{type(exc).__name__}")
        return

    binding = rules.get("evidenceBinding", {})
    expected_binding = {
        "canonicalContract": "rules/production_readiness_contract_v3.schema.json",
        "canonicalQaTool": "scripts/aicad_production_readiness_qa_v3.py",
        "canonicalQaConclusion": "evidenceContractReady_only",
        "artifactIdentityBinding": "artifact_id_plus_kind_plus_part_id_plus_revision_plus_normalized_relative_path_plus_size_plus_sha256",
        "expectedArtifactClosure": "exact_artifact_id_kind_part_id_revision_and_path_inventory",
        "candidateDeclaredClosureConsistency": "parsed_machine_bom_subject_rows_and_parsed_kicad_board_copper_and_drill_inventory_to_exact_candidate_artifact_id_sha256_sets",
        "sourceArtifactBinding": "rule_owned_selector_to_exact_artifact_id_sha256_map",
        "independentEvidenceAuthenticityVerified": False,
        "nativeExecutionReplayedByCanonicalQa": False,
        "technicalPackageReadyGrantedByCanonicalQa": False,
    }
    for key, expected in expected_binding.items():
        if binding.get(key) != expected:
            errors.append(f"v3-binding:{key}")
    if rules.get("safetyLocks") != {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "comparativeSuperiorityClaimAllowed": False,
    }:
        errors.append("v3-rule-safety-locks")

    exposure = rules.get("artifactExposureContract", {})
    if exposure.get("v3EvidenceContractReportExposure") != "report_only_no_candidate_artifacts":
        errors.append("v3-report-exposure")
    if exposure.get("technicalCandidateExposure") != "never_granted_by_v3_evidence_contract_qa":
        errors.append("v3-technical-exposure")

    required_kinds = rules.get("requiredArtifactKindsV3", {})
    for kind in ("native_cad", "neutral_step", "manufacturing_drawing", "mechanical_bom", "product_structure_manifest", "material_database"):
        if kind not in required_kinds.get("mechanical", []):
            errors.append(f"v3-mechanical-artifact-kind:{kind}")
    for kind in ("kicad_project", "kicad_schematic", "kicad_board", "native_board_inventory", "gerber_layer", "drill", "job_file", "cam_output_manifest", "fabrication_drawing"):
        if kind not in required_kinds.get("electronics", []):
            errors.append(f"v3-electronics-artifact-kind:{kind}")

    schema_required = set(schema.get("required", []))
    for field in ("artifactSubjects", "expectedArtifactClosure", "candidateArtifacts"):
        if field not in schema_required:
            errors.append(f"v3-schema-required:{field}")
    schema_defs = schema.get("$defs", {})
    schema_kinds = schema_defs.get("artifactKind", {}).get("enum", [])
    for kind in ("native_cad", "manufacturing_drawing", "product_structure_manifest", "native_board_inventory", "gerber_layer", "drill", "cam_output_manifest", "fabrication_drawing"):
        if kind not in schema_kinds:
            errors.append(f"v3-schema-artifact-kind:{kind}")
    candidate_required = set(schema_defs.get("candidateArtifact", {}).get("required", []))
    for field in ("artifactId", "kind", "path", "revision", "sha256"):
        if field not in candidate_required:
            errors.append(f"v3-schema-candidate-required:{field}")
    lock_required = set(schema_defs.get("safetyLocks", {}).get("required", []))
    if "comparativeSuperiorityClaimAllowed" not in lock_required:
        errors.append("v3-schema-comparative-claim-lock")

    closure_profiles = rules.get("artifactClosureProfilesV3", {})
    mechanical_closure = closure_profiles.get("mechanical", {})
    electronics_closure = closure_profiles.get("electronics", {})
    if mechanical_closure.get("requireAssemblyWhenManufacturedPartCountGreaterThan") != 1:
        errors.append("v3-mechanical-multipart-assembly")
    for subject_type in ("manufactured_part", "mechanical_assembly"):
        required = set(mechanical_closure.get("perSubjectRequiredKinds", {}).get(subject_type, []))
        if not {"native_cad", "neutral_step", "manufacturing_drawing"}.issubset(required):
            errors.append(f"v3-mechanical-subject-closure:{subject_type}")
    machine_bom = mechanical_closure.get("machineReadableBom", {})
    if machine_bom != {
        "kind": "mechanical_bom",
        "schema": "aicad_machine_mechanical_bom_v1",
        "scope": "package_exact_subject_rows_parsed_by_canonical_qa",
    }:
        errors.append("v3-mechanical-machine-readable-bom")
    mechanical_manifest = mechanical_closure.get("candidateClosureManifest", {})
    if mechanical_manifest != {
        "kind": "product_structure_manifest",
        "schema": "aicad_product_structure_manifest_v1",
        "sourceKind": "mechanical_bom",
        "scope": "candidate_declared_package_exact_subject_set_consistency",
    }:
        errors.append("v3-mechanical-candidate-closure-consistency")
    if not {"gerber_layer", "drill"}.issubset(set(electronics_closure.get("granularRepeatableKinds", []))):
        errors.append("v3-electronics-granular-cam")
    if not {"gerber_layer", "drill"}.issubset(set(
        electronics_closure.get("perSubjectRequiredKindAtLeastOne", {}).get("pcb_design", [])
    )):
        errors.append("v3-electronics-per-pcb-cam")
    per_pcb_outputs = {
        "kicad_project", "kicad_schematic", "kicad_board", "native_board_inventory",
        "job_file", "cam_output_manifest", "bom", "pick_and_place", "assembly_drawing",
        "fabrication_drawing", "schematic_pdf", "board_3d",
    }
    if not per_pcb_outputs.issubset(set(
        electronics_closure.get("perSubjectRequiredKinds", {}).get("pcb_design", [])
    )):
        errors.append("v3-electronics-per-pcb-output-closure")
    if not per_pcb_outputs.issubset(set(electronics_closure.get("subjectScopedKinds", []))):
        errors.append("v3-electronics-subject-scoped-output-closure")
    if per_pcb_outputs & set(electronics_closure.get("packageRequiredKinds", [])):
        errors.append("v3-electronics-output-improperly-package-scoped")
    native_board_inventory = electronics_closure.get("candidateBoardInventory", {})
    if native_board_inventory != {
        "kind": "native_board_inventory",
        "schema": "aicad_native_board_fabrication_inventory_v1",
        "sourceKind": "kicad_board",
        "scope": "candidate_inventory_must_match_canonical_qa_kicad_board_copper_and_drill_parse",
    }:
        errors.append("v3-electronics-board-parse-consistency")
    electronics_manifest = electronics_closure.get("candidateClosureManifest", {})
    if electronics_manifest != {
        "kind": "cam_output_manifest",
        "schema": "aicad_cam_output_manifest_v1",
        "sourceKind": "job_file",
        "scope": "candidate_declared_per_pcb_exact_cam_set_consistency",
    }:
        errors.append("v3-electronics-candidate-closure-consistency")

    for profile_name in ("mechanicalManufacturingProfileV3", "electronicsFabricationProfileV3"):
        profile = rules.get(profile_name)
        if not isinstance(profile, dict):
            errors.append(f"v3-profile-missing:{profile_name}")
            continue
        for group, gates in profile.items():
            if not isinstance(gates, dict):
                errors.append(f"v3-gate-group:{profile_name}:{group}")
                continue
            for name, gate in gates.items():
                if not isinstance(gate, dict) or gate.get("bindArtifactSet") is not True:
                    errors.append(f"v3-gate-unbound:{profile_name}:{group}.{name}")

    required_qa_literals = (
        '"evidenceContractReady": evidence_contract_ready',
        '"evidenceContractFailedGates": evidence_contract_failed',
        '"recordedApprovalEvidenceFailedGates": recorded_approval_failed',
        '"independentEvidenceAuthenticityVerified": False',
        '"nativeExecutionReplayedByThisQA": False',
        '"technicalPackageReady": False',
        '"productionReleaseEligible": False',
        '"manufacturingAuthorized": False',
        '"fabricationAuthorized": False',
        '"exposedArtifacts": []',
        '"comparativeSuperiorityClaimAllowed": False',
        "def _verify_candidate_declared_closure_consistency(",
        "def _parse_kicad_board_inventory(",
        "product_structure_subject_set_mismatch",
        "mechanical_bom_subject_rows_mismatch",
        "product_structure_machine_bom_rows_mismatch",
        "cam_manifest_gerber_set_mismatch",
        "cam_manifest_board_copper_layer_set_mismatch",
        "cam_manifest_drill_set_mismatch",
        "cam_manifest_non_plated_output_missing",
        "product_structure_bom_subject_rows_mismatch",
        "native_board_inventory_board_map_mismatch",
        "native_board_inventory_native_parse_mismatch",
        "cam_manifest_board_drill_requirements_mismatch",
    )
    for literal in required_qa_literals:
        if literal not in qa_text:
            errors.append(f"v3-qa-boundary:{literal}")
    for forbidden in (
        "duplicate_kinds",
        "sourceArtifactKind",
        "artifact_hashes.get(source_artifact_kind)",
    ):
        if forbidden in qa_text:
            errors.append(f"v3-qa-legacy-single-kind-binding:{forbidden}")


def load_metadata_object(path: Path, label: str, errors: list[str]) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label}-unreadable:{type(exc).__name__}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label}-not-object")
        return {}
    return payload


def verify_release_versions(
    plugin: object, manifest: object, expected_version: str, errors: list[str],
) -> None:
    if not isinstance(plugin, dict) or not isinstance(manifest, dict):
        errors.append("version-metadata-type")
        return
    if plugin.get("version") != expected_version or manifest.get("version") != expected_version:
        errors.append("expected-version-mismatch")
    if plugin.get("version") != manifest.get("version"):
        errors.append("version-mismatch")
    component_versions = manifest.get("componentVersions")
    if (
        not isinstance(component_versions, dict)
        or component_versions.get("agentPlugin") != expected_version
        or component_versions.get("pythonConstraintCompiler") != expected_version
    ):
        errors.append("component-version-mismatch")


def verify(plugin_dir: Path, source_root: Path | None = None, expected_version: str = EXPECTED_VERSION) -> dict:
    root = plugin_dir.resolve()
    errors: list[str] = []
    plugin_path = root / ".codex-plugin" / "plugin.json"
    manifest_path = root / "integration-manifest.json"
    sums_path = root / "SHA256SUMS"
    required = (
        plugin_path,
        manifest_path,
        sums_path,
        root / "LICENSE",
        root / "runtime" / "src" / "aicad" / "engine.py",
        root / "runtime" / "src" / "aicad" / "reference_rebuild.py",
        root / "runtime" / "src" / "aicad" / "subobject_correction.py",
        root / "runtime" / "schema" / "aicad-correction.schema.json",
        root / "rules" / "subobject_correction_rules.json",
        root / "rules" / "architectural_drafting_rules.json",
        root / "scripts" / "aicad_architecture_qa.py",
        root / "tests" / "test_architectural_drafting_rules.py",
        root / "docs" / "ARCHITECTURAL_DRAFTING.md",
        root / "rules" / "cad_normative_quality_rules.json",
        root / "rules" / "cad_normative_quality_contract.schema.json",
        root / "scripts" / "aicad_normative_quality_qa.py",
        root / "tests" / "test_cad_normative_quality.py",
        root / "rules" / "native_solidworks_topology_rules.json",
        root / "docs" / "NATIVE_SOLIDWORKS_TOPOLOGY.md",
        root / "skills" / "aicad-model-3d" / "references" / "native-topology.md",
        root / "runtime" / "solidworks-host-source" / "Program.cs",
        root / "tests" / "test_native_solidworks_topology_rules.py",
        root / "docs" / "EXACT_SUBOBJECT_CORRECTION.md",
        root / "runtime" / "schema" / "aicad-reference-rebuild.schema.json",
        root / "runtime" / "examples" / "web_reference_plate.html",
        root / "scripts" / "aicad_reference_visual_qa.cjs",
        root / "scripts" / "aicad_multiview_visual_qa.cjs",
        root / "tests" / "test_subobject_correction_rules.py",
        root / "tests" / "test_reference_rebuild_release.py",
        root / "rules" / "production_readiness_contract_v3.schema.json",
        root / "scripts" / "aicad_production_readiness_qa_v3.py",
        root / "tests" / "test_production_readiness_v3.py",
        root / "runtime" / "src" / "aicad" / "continuous_learning.py",
        root / "rules" / "continuous_learning_rules.json",
        root / "rules" / "learning_event.schema.json",
        root / "rules" / "learning_approval_ledger.schema.json",
        root / "scripts" / "aicad_lesson_harvester.py",
        root / "scripts" / "aicad_continuous_learning_qa.py",
        root / "tests" / "test_continuous_learning.py",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"missing:{path.relative_to(root)}")
    if not plugin_path.is_file() or not manifest_path.is_file() or not sums_path.is_file():
        return {"ok": False, "errors": errors}

    plugin = load_metadata_object(plugin_path, "plugin-metadata", errors)
    manifest = load_metadata_object(manifest_path, "integration-manifest", errors)
    if plugin.get("name") != "aicad-agent":
        errors.append("plugin-name")
    verify_release_versions(plugin, manifest, expected_version, errors)
    interface = plugin.get("interface")
    if interface is not None and not isinstance(interface, dict):
        errors.append("plugin-interface-type")
        interface = {}
    prompts = (interface or {}).get("defaultPrompt", [])
    if not isinstance(prompts, list):
        errors.append("default-prompts-type")
    elif len(prompts) > 3:
        errors.append("too-many-default-prompts")
    if manifest.get("apiKeyRequired") is not False:
        errors.append("api-key-policy")
    if manifest.get("safetyLocks") != EXPECTED_LOCKS:
        errors.append("safety-locks")
    if manifest.get("proprietaryDependenciesRedistributed") is not False:
        errors.append("proprietary-redistribution-policy")
    try:
        learning_rules = json.loads((root / "rules" / "continuous_learning_rules.json").read_text(encoding="utf-8"))
        learning_qa = (root / "scripts" / "aicad_continuous_learning_qa.py").read_text(encoding="utf-8")
        learning_core = (root / "runtime" / "src" / "aicad" / "continuous_learning.py").read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"continuous-learning-unreadable:{type(exc).__name__}")
    else:
        validate_continuous_learning_catalog(learning_rules, errors)
        validate_learning_schema_documents(root, errors)
        validate_continuous_learning_runtime_boundary(root, errors)

    verify_v3_evidence_contract(root, errors)

    files = [path for path in root.rglob("*") if path.is_file()]
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"symlink:{relative}")
        if any(part in FORBIDDEN_NAMES for part in path.parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"cache:{relative}")
        if path.name in FORBIDDEN_BINARY_NAMES:
            errors.append(f"proprietary-binary:{relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "\ufffd" in text or any(0xE000 <= ord(character) <= 0xF8FF for character in text):
            errors.append(f"mojibake-codepoint:{relative}")
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(text):
                errors.append(f"forbidden-text:{relative}:{pattern.pattern}")

    actual_paths = {path.relative_to(root).as_posix() for path in files}
    payload_paths = actual_paths - {"integration-manifest.json", "SHA256SUMS"}
    manifest_count = verify_entries(
        entries=manifest.get("files"),
        expected_paths=payload_paths,
        root=root,
        label="manifest",
        errors=errors,
    )

    sum_rows: list[dict[str, object]] = []
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            errors.append(f"invalid-sums-line:{line}")
            continue
        expected, relative = line.split("  ", 1)
        sum_rows.append({"path": relative, "sha256": expected, "size": (root / relative).stat().st_size if (root / relative).is_file() else None})
    sums_count = verify_entries(
        entries=sum_rows,
        expected_paths=actual_paths - {"SHA256SUMS"},
        root=root,
        label="sums",
        errors=errors,
    )

    source_count = 0
    if manifest.get("sourceInputPolicy") != SOURCE_INPUT_POLICY:
        errors.append("source-input-policy")
    if source_root is None:
        errors.append("source-root-required")
    else:
        resolved_source = source_root.resolve()
        for path in resolved_source.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".rej", ".orig"}:
                errors.append(
                    f"source-reject-residue:{path.relative_to(resolved_source).as_posix()}"
                )
        build_options = manifest.get("buildOptions")
        if build_options is not None and not isinstance(build_options, dict):
            errors.append("build-options-type")
            build_options = {}
        include_interop = (build_options or {}).get("includeSolidWorksInterop") is True
        expected_inputs = source_files(resolved_source, include_interop)
        source_count = verify_entries(
            entries=manifest.get("sourceInputs"),
            expected_paths=expected_inputs,
            root=resolved_source,
            label="source-input",
            errors=errors,
        )

    return {
        "ok": not errors,
        "version": plugin.get("version"),
        "files_checked": len(files),
        "manifest_files_checked": manifest_count,
        "sums_files_checked": sums_count,
        "source_inputs_checked": source_count,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a built aicad-agent release without modifying it")
    parser.add_argument("plugin_dir", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--expected-version", default=EXPECTED_VERSION)
    args = parser.parse_args()
    result = verify(args.plugin_dir, args.source_root, args.expected_version)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
