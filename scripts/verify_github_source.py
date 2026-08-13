from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
import types
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath


EXPECTED_VERSION = "1.14.0"
SOURCE_INPUT_POLICY = "github_source_builder_v1"
REQUIRED_README_SECTIONS = (
    "# aicad-agent 1.14.0",
    "## 安装步骤",
    "## 第一次使用：完全不需要写代码",
    "## 常用任务提示词",
    "## 主要功能详解",
    "## MCP 工具",
    "## 本地 CLI 使用",
    "## 依赖与降级行为",
    "## 开发与验证",
    "## 文档索引",
    "点击直线",
    "点击点",
    "点击圆",
    "坐标系开关",
    "建筑平面专业制图",
    "默认不需要 API Key",
)
FORBIDDEN_TOP_LEVEL = ("build", "jobs", "out", "release", ".git")
FORBIDDEN_NAMES = ("__pycache__", ".pytest_cache", ".env", "id_rsa", "id_ed25519")
SOURCE_SKIP_NAMES = {"__pycache__", ".pytest_cache", "bin", "obj"}
SOURCE_SKIP_SUFFIXES = {".pyc", ".pyo", ".rej", ".orig"}
SOURCE_ROOT_FILES = ("README.md", "pyproject.toml", ".gitignore", ".gitattributes")
SOURCE_TREE_ROOTS = (
    ".github", ".agents", "src", "schema", "examples", "prompts", "docs",
    "plugin", "agent-plugin", "scripts", "tests", "tools", "showcase",
)
SOURCE_FIXED_FILES = (
    "solidworks-host/AiCad.SolidWorksHost/Program.cs",
    "solidworks-host/AiCad.SolidWorksHost/AiCad.SolidWorksHost.csproj",
)
TEXT_SUFFIXES = {
    ".aicad", ".cjs", ".cs", ".csproj", ".css", ".html", ".js", ".json",
    ".lsp", ".md", ".mjs", ".ps1", ".py", ".scr", ".svg", ".toml",
    ".txt", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {".gitattributes", ".gitignore", "LICENSE", "SHA256SUMS"}
SHOWCASE_SLUGS = ("architecture", "steel", "mechanical", "pcb")
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
EXPECTED_LEARNING_LOCKS = {
    "reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True,
}

EXPECTED_LEARNING_SCHEMA = "aicad_continuous_learning_rules_v1"
EXPECTED_LEARNING_SCOPE = "test_and_gate_failures_across_all_aicad_domains"
EXPECTED_LEARNING_EVENT_POLICY = "no_implicit_timestamp_no_absolute_machine_path_hash_bound_safe_relative_evidence"
EXPECTED_LEARNING_FIELDS = {
    "schema", "scope", "canonicalEventPolicy", "controls", "preventionRules",
    "failureAliases", "candidateSafetyLocks", "promotionPolicy",
}
EXPECTED_LEARNING_CONTROL_IDS = {f"CL-G{index:03d}" for index in range(1, 10)}
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
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid-json:{path.name}:{exc}")
        return {}


def safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


def tree_files(source_root: Path, relative: str) -> set[str]:
    result: set[str] = set()
    tree = source_root / relative
    if not tree.is_dir():
        return result
    for path in tree.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(source_root).as_posix()
        if any(part in SOURCE_SKIP_NAMES for part in PurePosixPath(rel).parts):
            continue
        if path.suffix.lower() in SOURCE_SKIP_SUFFIXES:
            continue
        result.add(rel)
    return result


def expected_source_inputs(source_root: Path, manifest: dict, errors: list[str]) -> set[str]:
    result = {relative for relative in SOURCE_ROOT_FILES if (source_root / relative).is_file()}
    for relative in SOURCE_TREE_ROOTS:
        result.update(tree_files(source_root, relative))
    result.update(relative for relative in SOURCE_FIXED_FILES if (source_root / relative).is_file())
    build_inputs = manifest.get("sourceBuildInputs")
    if not isinstance(build_inputs, dict):
        errors.append("source-build-inputs")
        return result
    plugin_dir = safe_relative(build_inputs.get("pluginDirectory"))
    archive = safe_relative(build_inputs.get("pluginArchive"))
    if plugin_dir is None or not plugin_dir.startswith("release/"):
        errors.append(f"unsafe-source-plugin-directory:{build_inputs.get('pluginDirectory')}")
    else:
        result.update(tree_files(source_root, plugin_dir))
    if archive is None or not archive.startswith("release/"):
        errors.append(f"unsafe-source-plugin-archive:{build_inputs.get('pluginArchive')}")
    elif (source_root / archive).is_file():
        result.add(archive)
    return result


def verify_entries(
    *, entries: object, expected_paths: set[str], root: Path, label: str, errors: list[str]
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


def verify_showcase(root: Path, errors: list[str]) -> int:
    showcase = root / "showcase"
    required = {"README.md", "showcase-manifest.json"}
    for slug in SHOWCASE_SLUGS:
        required.update({
            f"{slug}/preview.png",
            f"{slug}/review.html",
            f"{slug}/validation.json",
            f"{slug}/validation.md",
            f"{slug}/source-manifest.json",
            f"{slug}/{slug}-sanitized-review-candidate.zip",
        })
    for relative in sorted(required):
        if not (showcase / relative).is_file():
            errors.append(f"showcase-missing:{relative}")

    manifest = load_json(showcase / "showcase-manifest.json", errors)
    if manifest.get("schema") != "aicad_github_showcase_v2":
        errors.append("showcase-schema")
    if manifest.get("releaseStatus") != "engineering-review-candidate":
        errors.append("showcase-release-status")
    expected_locks = {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "productionOrFabricationAcceptanceClaimed": False,
    }
    if manifest.get("safetyLocks") != expected_locks:
        errors.append("showcase-safety-locks")
    demos = manifest.get("demos")
    demo_slugs = [row.get("slug") for row in demos] if isinstance(demos, list) and all(isinstance(row, dict) for row in demos) else []
    if demo_slugs != list(SHOWCASE_SLUGS):
        errors.append(f"showcase-demo-bijection:{demo_slugs}")
    expected_input_locks = {key: expected_locks[key] for key in ("reviewOnly", "accepted", "ruleEnabled", "packagingGated")}
    for row in demos if isinstance(demos, list) else []:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug")
        if row.get("inputSafetyLocks") != expected_input_locks:
            errors.append(f"showcase-input-locks:{row.get('slug')}")
        if slug not in SHOWCASE_SLUGS:
            continue
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, list) or not all(isinstance(item, dict) for item in artifacts):
            errors.append(f"showcase-demo-artifacts:{slug}")
            continue
        expected_role_paths = {
            "preview": f"{slug}/preview.png",
            "interactive_review": f"{slug}/review.html",
            "validation_machine": f"{slug}/validation.json",
            "validation_human": f"{slug}/validation.md",
            "source_manifest": f"{slug}/source-manifest.json",
            "sanitized_review_candidate": f"{slug}/{slug}-sanitized-review-candidate.zip",
        }
        role_paths = [(item.get("role"), item.get("path")) for item in artifacts]
        if Counter(role for role, _ in role_paths) != Counter(expected_role_paths.keys()):
            errors.append(f"showcase-demo-role-bijection:{slug}")
        for role, expected_path in expected_role_paths.items():
            matches = [path for candidate_role, path in role_paths if candidate_role == role]
            if matches != [expected_path]:
                errors.append(f"showcase-demo-artifact-link:{slug}:{role}")
        closure = row.get("sourceManifestClosure")
        if not isinstance(closure, dict) or closure.get("exactBidirectionalClosure") is not True:
            errors.append(f"showcase-source-closure:{slug}")

    actual_paths = {
        path.relative_to(showcase).as_posix()
        for path in showcase.rglob("*")
        if path.is_file()
    } if showcase.is_dir() else set()
    closure = manifest.get("outputClosure")
    if not isinstance(closure, dict) or closure.get("policy") != "all_output_files_except_manifest_self":
        errors.append("showcase-output-closure-policy")
        entries = []
    else:
        entries = closure.get("files")
    closure_count = verify_entries(
        entries=entries,
        expected_paths=actual_paths - {"showcase-manifest.json"},
        root=showcase,
        label="showcase-closure",
        errors=errors,
    )
    readme_path = showcase / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        for relative in sorted(required - {"README.md", "showcase-manifest.json"}):
            if relative not in readme:
                errors.append(f"showcase-readme-link:{relative}")
    return closure_count


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
                (lambda value: function(plugin_root, value, current_version="1.14.0"))
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


def verify_continuous_learning_boundary(root: Path, errors: list[str]) -> None:
    plugin = root / "plugins" / "aicad-agent"
    rules = load_json(plugin / "rules" / "continuous_learning_rules.json", errors)
    validate_continuous_learning_catalog(rules, errors)
    validate_learning_schema_documents(plugin, errors)
    validate_continuous_learning_runtime_boundary(plugin, errors)


def verify(root: Path, source_root: Path | None = None) -> dict:
    errors: list[str] = []
    root = root.resolve()
    required = (
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "source-manifest.json",
        "dist/aicad-agent-1.14.0.zip",
        "dist/SHA256SUMS",
        "docs/images/modifier-measurements-v3.png",
        "plugins/aicad-agent/.codex-plugin/plugin.json",
        "plugins/aicad-agent/integration-manifest.json",
        "plugins/aicad-agent/SHA256SUMS",
        "plugins/aicad-agent/rules/architectural_drafting_rules.json",
        "plugins/aicad-agent/scripts/aicad_architecture_qa.py",
        "plugins/aicad-agent/tests/test_architectural_drafting_rules.py",
        "plugins/aicad-agent/rules/cad_normative_quality_rules.json",
        "plugins/aicad-agent/rules/cad_normative_quality_contract.schema.json",
        "plugins/aicad-agent/scripts/aicad_normative_quality_qa.py",
        "plugins/aicad-agent/tests/test_cad_normative_quality.py",
        "plugins/aicad-agent/runtime/src/aicad/continuous_learning.py",
        "plugins/aicad-agent/rules/continuous_learning_rules.json",
        "plugins/aicad-agent/rules/learning_event.schema.json",
        "plugins/aicad-agent/rules/learning_approval_ledger.schema.json",
        "plugins/aicad-agent/scripts/aicad_lesson_harvester.py",
        "plugins/aicad-agent/scripts/aicad_continuous_learning_qa.py",
        "plugins/aicad-agent/tests/test_continuous_learning.py",
        "docs/ARCHITECTURAL_DRAFTING.md",
        "scripts/build_showcase.py",
        "tests/test_build_showcase.py",
        "showcase/README.md",
        "showcase/showcase-manifest.json",
        "scripts/verify_github_source.py",
    )
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"missing:{relative}")

    for name in FORBIDDEN_TOP_LEVEL:
        if (root / name).exists():
            errors.append(f"forbidden-top-level:{name}")

    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"symlink:{relative}")
        if path.name in FORBIDDEN_NAMES:
            errors.append(f"forbidden-name:{relative}")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".rej", ".orig", ".dwg", ".sldprt", ".step", ".log"}:
            errors.append(f"forbidden-artifact:{relative}")

    readme_path = root / "README.md"
    readme = ""
    if readme_path.is_file():
        try:
            readme = readme_path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            errors.append(f"readme-utf8:{exc}")
        for fragment in REQUIRED_README_SECTIONS:
            if fragment not in readme:
                errors.append(f"readme-missing:{fragment}")
        for stale in ("v1.3.4", "v1.4.0", "aicad-agent 1.3.4", "aicad-agent 1.4.0"):
            if stale in readme:
                errors.append(f"readme-stale-version:{stale}")
        if "docs/images/modifier-measurements-v3.png" not in readme:
            errors.append("readme-missing-measurement-screenshot")

    workflow = root / ".github" / "workflows" / "ci.yml"
    if workflow.is_file():
        workflow_text = workflow.read_text(encoding="utf-8")
        if "Version 1.14.0" not in workflow_text:
            errors.append("ci-not-pinned-to-1.14.0")
        if "verify_github_source.py" not in workflow_text:
            errors.append("ci-missing-github-source-verifier")
        if "1.3.4" in workflow_text or "1.4.0" in workflow_text:
            errors.append("ci-stale-version")
    else:
        errors.append("missing:.github/workflows/ci.yml")

    plugin_manifest = load_json(root / "plugins" / "aicad-agent" / ".codex-plugin" / "plugin.json", errors)
    if plugin_manifest.get("version") != EXPECTED_VERSION:
        errors.append("plugin-version-mismatch")
    verify_continuous_learning_boundary(root, errors)

    source_manifest = load_json(root / "source-manifest.json", errors)
    if source_manifest.get("version") != EXPECTED_VERSION:
        errors.append("source-version-mismatch")
    if source_manifest.get("releaseStatus") != "engineering-candidate":
        errors.append("source-release-status")
    expected_locks = {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "comparativeSuperiorityClaimAllowed": False,
    }
    if source_manifest.get("safetyLocks", {}) != expected_locks:
        errors.append("source-safety-locks")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    manifest_count = verify_entries(
        entries=source_manifest.get("files"),
        expected_paths=actual_paths - {"source-manifest.json"},
        root=root,
        label="manifest",
        errors=errors,
    )

    source_count = 0
    if source_manifest.get("sourceInputPolicy") != SOURCE_INPUT_POLICY:
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
        expected_inputs = expected_source_inputs(resolved_source, source_manifest, errors)
        source_count = verify_entries(
            entries=source_manifest.get("sourceInputs"),
            expected_paths=expected_inputs,
            root=resolved_source,
            label="source-input",
            errors=errors,
        )
    showcase_count = verify_showcase(root, errors)

    archive = root / "dist" / "aicad-agent-1.14.0.zip"
    sums = root / "dist" / "SHA256SUMS"
    if archive.is_file() and sums.is_file():
        parts = sums.read_text(encoding="ascii").strip().split()
        if len(parts) != 2 or parts[1] != archive.name or parts[0].lower() != sha256(archive):
            errors.append("dist-checksum-mismatch")
        try:
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
            if not names or any(not name.startswith("aicad-agent/") for name in names):
                errors.append("zip-top-level")
        except zipfile.BadZipFile:
            errors.append("dist-invalid-zip")

    personal_path = re.compile(r"(?:[A-Za-z]:[\\/](?:Users|CAD绘制插件)[\\/]|/Users/|/home/)", re.IGNORECASE)
    mojibake = ("锛", "銆", "鈥", "缁樺埗", "鎻掍欢")
    for path in root.rglob("*"):
        if not path.is_file() or not (path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"text-not-utf8:{relative}")
            continue
        if "\r" in text and not relative.startswith("showcase/"):
            errors.append(f"non-lf-text:{relative}")
        if relative != "scripts/verify_github_source.py" and personal_path.search(text):
            errors.append(f"personal-path:{relative}")
        if relative != "scripts/verify_github_source.py" and any(marker in text for marker in mojibake):
            errors.append(f"suspected-mojibake:{relative}")

    return {
        "ok": not errors,
        "status": "pass" if not errors else "failed",
        "version": EXPECTED_VERSION,
        "root": str(root),
        "files_checked": len(actual_paths),
        "manifest_files_checked": manifest_count,
        "source_inputs_checked": source_count,
        "showcase_files_checked": showcase_count,
        "readme_required_items": len(REQUIRED_README_SECTIONS),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the publishable aicad-agent GitHub source tree")
    parser.add_argument("root", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    result = verify(args.root, args.source_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
