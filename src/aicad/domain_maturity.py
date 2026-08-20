from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping


MATURITY_LEVELS = {"foundation": 0, "constrained": 1, "advanced": 2}
REPARSE_POINT_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


DOMAIN_MATURITY_POLICY: dict[str, dict[str, Any]] = {
    "general": {
        "ceiling": "constrained",
        "capabilities": ("domain_semantic_validator",),
        "evidence": (
            "runtime.domain_rules",
            "rules.normative_governance",
            "rules.cad_normative_quality",
        ),
    },
    "architecture": {
        "ceiling": "constrained",
        "capabilities": (
            "domain_semantic_validator",
            "architecture_detail_validator",
        ),
        "evidence": (
            "runtime.domain_rules",
            "rules.architectural_drafting",
            "rules.architectural_detail_contract",
            "scripts.architecture_detail_qa",
        ),
    },
    "packaging": {
        "ceiling": "constrained",
        "capabilities": (
            "domain_semantic_validator",
            "packaging_guarded_delivery",
        ),
        "evidence": (
            "runtime.domain_rules",
            "rules.packaging_dieline",
            "rules.normality_contract",
            "scripts.guarded_delivery",
        ),
    },
    "mechanical": {
        "ceiling": "constrained",
        "capabilities": (
            "domain_semantic_validator",
            "engineering_preflight",
            "production_readiness_evidence_verifier",
        ),
        "evidence": (
            "runtime.domain_rules",
            "rules.production_readiness",
            "rules.native_solidworks_topology",
            "scripts.engineering_preflight",
            "scripts.production_readiness_v3",
        ),
    },
    "electronics": {
        "ceiling": "constrained",
        "capabilities": (
            "domain_semantic_validator",
            "engineering_preflight",
            "production_readiness_evidence_verifier",
        ),
        "evidence": (
            "runtime.domain_rules",
            "rules.production_readiness",
            "scripts.engineering_preflight",
            "scripts.production_readiness_v3",
        ),
    },
    "sheet_metal": {
        "ceiling": "constrained",
        "capabilities": ("domain_semantic_validator",),
        "evidence": (
            "runtime.domain_rules",
            "rules.normative_governance",
        ),
    },
    "civil": {
        "ceiling": "constrained",
        "capabilities": (
            "domain_semantic_validator",
            "civil_review_candidate_validator",
        ),
        "evidence": (
            "runtime.domain_rules",
            "runtime.civil",
            "rules.civil_engineering",
            "schema.civil_review_candidate",
        ),
    },
}

for _foundation_domain in (
    "structural",
    "electrical",
    "plumbing",
    "hvac",
    "process_piping",
    "product_design",
):
    DOMAIN_MATURITY_POLICY[_foundation_domain] = {
        "ceiling": "foundation",
        "capabilities": (),
        "evidence": (),
        "foundationLocked": True,
    }


DOMAIN_MATURITY_CEILINGS = {
    domain: str(policy["ceiling"])
    for domain, policy in DOMAIN_MATURITY_POLICY.items()
}


_EVIDENCE_LOCATIONS: dict[str, tuple[str, ...]] = {
    "runtime.domain_rules": (
        "plugin:runtime/src/aicad/domain_rules.py",
        "repository:src/aicad/domain_rules.py",
    ),
    "runtime.civil": (
        "plugin:runtime/src/aicad/civil.py",
        "repository:src/aicad/civil.py",
    ),
    "rules.normative_governance": (
        "plugin:rules/normative_governance_rules.json",
    ),
    "rules.cad_normative_quality": (
        "plugin:rules/cad_normative_quality_rules.json",
    ),
    "rules.architectural_drafting": (
        "plugin:rules/architectural_drafting_rules.json",
    ),
    "rules.architectural_detail_contract": (
        "plugin:rules/architectural_detail_contract_v2.schema.json",
    ),
    "rules.packaging_dieline": (
        "plugin:rules/packaging_dieline_rules.json",
    ),
    "rules.normality_contract": (
        "plugin:rules/normality_contract.schema.json",
    ),
    "rules.production_readiness": (
        "plugin:rules/production_readiness_rules.json",
    ),
    "rules.native_solidworks_topology": (
        "plugin:rules/native_solidworks_topology_rules.json",
    ),
    "rules.civil_engineering": (
        "plugin:rules/civil_engineering_rules.json",
    ),
    "schema.civil_review_candidate": (
        "plugin:runtime/schema/aicad-civil-review-candidate.schema.json",
        "repository:schema/aicad-civil-review-candidate.schema.json",
    ),
    "scripts.architecture_detail_qa": (
        "plugin:scripts/aicad_architecture_detail_qa.py",
    ),
    "scripts.guarded_delivery": (
        "plugin:scripts/aicad_guarded_delivery.py",
    ),
    "scripts.engineering_preflight": (
        "plugin:scripts/aicad_engineering_preflight.py",
    ),
    "scripts.production_readiness_v3": (
        "plugin:scripts/aicad_production_readiness_qa_v3.py",
    ),
}


_CAPABILITY_PROBES: dict[str, tuple[str, tuple[str, ...]]] = {
    "domain_semantic_validator": (
        "runtime.domain_rules",
        ("evaluate_domain_plan",),
    ),
    "civil_review_candidate_validator": (
        "runtime.civil",
        ("validate_civil_review_candidate",),
    ),
    "architecture_detail_validator": (
        "scripts.architecture_detail_qa",
        ("evaluate",),
    ),
    "packaging_guarded_delivery": (
        "scripts.guarded_delivery",
        ("run_pipeline",),
    ),
    "engineering_preflight": (
        "scripts.engineering_preflight",
        ("build_template", "evaluate"),
    ),
    "production_readiness_evidence_verifier": (
        "scripts.production_readiness_v3",
        ("evaluate",),
    ),
}


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_below(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(path), _path_key(root))) == _path_key(root)
    except ValueError:
        return False


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT_FLAG
    )


def discover_plugin_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    else:
        source = Path(__file__).resolve()
        for parent in source.parents:
            candidates.extend((parent, parent / "agent-plugin" / "aicad-agent"))
    seen: set[str] = set()
    for candidate in candidates:
        absolute = Path(os.path.abspath(os.fspath(candidate)))
        marker = _path_key(absolute)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            if _is_link_or_reparse(absolute):
                continue
            resolved = absolute.resolve(strict=True)
        except OSError:
            continue
        if (resolved / "rules").is_dir() and (resolved / "scripts").is_dir():
            return resolved
    raise FileNotFoundError("cannot locate a controlled AICAD plugin asset root")


def _repository_root(plugin_root: Path) -> Path | None:
    if plugin_root.parent.name == "agent-plugin":
        return plugin_root.parents[1]
    return None


def _candidate_path(plugin_root: Path, location: str) -> tuple[Path, Path, str] | None:
    scope, separator, relative = location.partition(":")
    if not separator:
        return None
    if scope == "plugin":
        base = plugin_root
    elif scope == "repository":
        base = _repository_root(plugin_root)
        if base is None:
            return None
    else:
        return None
    return base, base / Path(relative), f"{scope}:{Path(relative).as_posix()}"


def _regular_file_record(
    logical_id: str, base: Path, candidate: Path, public_path: str
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    absolute = Path(os.path.abspath(os.fspath(candidate)))
    if not _is_below(absolute, base):
        return None, None, f"evidence_path_escape:{logical_id}"
    current = base
    relative = Path(os.path.relpath(absolute, base))
    try:
        for part in relative.parts:
            current = current / part
            if not current.exists() and not current.is_symlink():
                return None, None, None
            if _is_link_or_reparse(current):
                return None, None, f"evidence_link_forbidden:{logical_id}"
        resolved = absolute.resolve(strict=True)
        if not _is_below(resolved, base):
            return None, None, f"evidence_path_escape:{logical_id}"
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            return None, None, f"evidence_not_regular:{logical_id}"
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = resolved.stat(follow_symlinks=False)
    except OSError as exc:
        return None, None, f"evidence_unreadable:{logical_id}:{type(exc).__name__}"
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None, None, f"evidence_changed_while_hashing:{logical_id}"
    return (
        {
            "logicalId": logical_id,
            "path": public_path,
            "size": before.st_size,
            "sha256": digest.hexdigest(),
        },
        resolved,
        None,
    )


def _evidence_record(
    logical_id: str, plugin_root: Path
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    for location in _EVIDENCE_LOCATIONS.get(logical_id, ()):
        selected = _candidate_path(plugin_root, location)
        if selected is None:
            continue
        record, resolved, error = _regular_file_record(logical_id, *selected)
        if error is not None:
            return None, None, error
        if record is not None:
            return record, resolved, None
    return None, None, f"evidence_missing:{logical_id}"


def _is_placeholder_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return True
    if len(body) != 1:
        return False
    statement = body[0]
    return (
        isinstance(statement, (ast.Pass, ast.Raise))
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        )
        or (isinstance(statement, ast.Return) and statement.value is None)
    )


def _function_names(path: Path) -> tuple[set[str], set[str], str | None]:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return set(), set(), f"implementation_not_parseable:{type(exc).__name__}"
    functions = [
        row for row in module.body
        if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    placeholders = {row.name for row in functions if _is_placeholder_function(row)}
    return {row.name for row in functions} - placeholders, placeholders, None


def assess_domain_maturity(
    domain: str,
    declared_maturity: object | None = None,
    *,
    plugin_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    policy = DOMAIN_MATURITY_POLICY.get(domain)
    if policy is None:
        return {
            "ok": False,
            "domain": domain,
            "declaredMaturity": declared_maturity,
            "codeCeiling": "foundation",
            "earnedMaturity": "foundation",
            "effectiveMaturity": "foundation",
            "specialistGenerationBlocked": True,
            "productionReleaseBlocked": True,
            "issues": [f"unregistered_domain:{domain}"],
            "evidenceClosure": {"ok": False, "records": [], "fingerprint": None},
            "capabilities": {},
        }

    ceiling = str(policy["ceiling"])
    declared = ceiling if declared_maturity is None else declared_maturity
    issues: list[str] = []
    if declared not in MATURITY_LEVELS:
        issues.append(f"invalid_declared_maturity:{declared!r}")
        declared_rank = MATURITY_LEVELS["foundation"]
    else:
        declared_rank = MATURITY_LEVELS[str(declared)]
    if declared_rank > MATURITY_LEVELS[ceiling]:
        issues.append(f"declared_maturity_exceeds_code_ceiling:{declared}>{ceiling}")

    required_evidence = tuple(str(item) for item in policy.get("evidence", ()))
    records: list[dict[str, Any]] = []
    resolved_paths: dict[str, Path] = {}
    try:
        root = discover_plugin_root(plugin_root)
    except (FileNotFoundError, OSError) as exc:
        root = None
        if required_evidence:
            issues.append(f"plugin_root_unavailable:{type(exc).__name__}")
    if root is not None:
        for logical_id in required_evidence:
            record, resolved, error = _evidence_record(logical_id, root)
            if error is not None:
                issues.append(error)
            elif record is not None and resolved is not None:
                records.append(record)
                resolved_paths[logical_id] = resolved
    records.sort(key=lambda row: str(row["logicalId"]))
    fingerprint = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence_ok = len(records) == len(required_evidence)

    capability_results: dict[str, dict[str, Any]] = {}
    for capability in tuple(str(item) for item in policy.get("capabilities", ())):
        logical_id, required_functions = _CAPABILITY_PROBES[capability]
        implementation = resolved_paths.get(logical_id)
        if implementation is None:
            capability_results[capability] = {
                "ok": False,
                "implementationEvidence": logical_id,
                "requiredFunctions": list(required_functions),
                "missingFunctions": list(required_functions),
                "placeholderFunctions": [],
            }
            issues.append(f"capability_evidence_missing:{capability}:{logical_id}")
            continue
        available, placeholders, parse_error = _function_names(implementation)
        required = set(required_functions)
        placeholder = sorted(required.intersection(placeholders))
        missing = sorted(required - available - placeholders)
        capability_results[capability] = {
            "ok": parse_error is None and not missing and not placeholder,
            "implementationEvidence": logical_id,
            "requiredFunctions": list(required_functions),
            "missingFunctions": missing,
            "placeholderFunctions": placeholder,
        }
        if parse_error is not None:
            issues.append(f"capability_not_executable:{capability}:{parse_error}")
        elif placeholder:
            issues.append(
                "capability_functions_placeholder:"
                f"{capability}:{','.join(placeholder)}"
            )
        elif missing:
            issues.append(
                f"capability_functions_missing:{capability}:{','.join(missing)}"
            )
    capabilities_ok = all(row["ok"] for row in capability_results.values())

    foundation_locked = bool(policy.get("foundationLocked", False))
    earned = (
        ceiling
        if not foundation_locked and evidence_ok and capabilities_ok
        else "foundation"
    )
    effective_rank = min(declared_rank, MATURITY_LEVELS[earned])
    effective = next(
        name for name, rank in MATURITY_LEVELS.items() if rank == effective_rank
    )
    return {
        "ok": not issues,
        "domain": domain,
        "declaredMaturity": declared,
        "codeCeiling": ceiling,
        "earnedMaturity": earned,
        "effectiveMaturity": effective,
        "foundationLocked": foundation_locked,
        "specialistGenerationBlocked": effective == "foundation",
        "productionReleaseBlocked": True,
        "decisionSource": "code_ceiling_plus_executable_capabilities_plus_sha256_evidence_closure",
        "issues": issues,
        "evidenceClosure": {
            "ok": evidence_ok,
            "records": records,
            "fingerprint": fingerprint,
        },
        "capabilities": capability_results,
    }


def assess_domain_registry(
    registry: Mapping[str, Any],
    *,
    plugin_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    effective_registry = copy.deepcopy(dict(registry))
    raw_domains = registry.get("domains")
    domains = raw_domains if isinstance(raw_domains, Mapping) else {}
    effective_domains = effective_registry.get("domains")
    if not isinstance(effective_domains, dict):
        effective_domains = {}
        effective_registry["domains"] = effective_domains
    issues: list[str] = []
    missing = sorted(set(DOMAIN_MATURITY_POLICY) - set(domains))
    extra = sorted(set(domains) - set(DOMAIN_MATURITY_POLICY))
    issues.extend(f"registry_domain_missing:{domain}" for domain in missing)
    issues.extend(f"registry_domain_unregistered:{domain}" for domain in extra)
    decisions: dict[str, dict[str, Any]] = {}
    for domain in sorted(DOMAIN_MATURITY_POLICY):
        raw = domains.get(domain)
        declared = raw.get("maturity") if isinstance(raw, Mapping) else None
        decision = assess_domain_maturity(
            domain, declared, plugin_root=plugin_root
        )
        decisions[domain] = decision
        issues.extend(f"{domain}:{issue}" for issue in decision["issues"])
        if not isinstance(effective_domains.get(domain), dict):
            effective_domains[domain] = {}
        row = effective_domains[domain]
        row["declaredMaturity"] = declared
        row["maturity"] = decision["effectiveMaturity"]
        row["maturityDecision"] = {
            "codeCeiling": decision["codeCeiling"],
            "earnedMaturity": decision["earnedMaturity"],
            "effectiveMaturity": decision["effectiveMaturity"],
            "specialistGenerationBlocked": decision[
                "specialistGenerationBlocked"
            ],
            "evidenceClosureFingerprint": decision["evidenceClosure"][
                "fingerprint"
            ],
            "issues": list(decision["issues"]),
        }
    for domain in extra:
        raw = effective_domains.get(domain)
        if isinstance(raw, dict):
            raw["declaredMaturity"] = raw.get("maturity")
            raw["maturity"] = "foundation"
            raw["maturityDecision"] = {
                "codeCeiling": "foundation",
                "earnedMaturity": "foundation",
                "effectiveMaturity": "foundation",
                "specialistGenerationBlocked": True,
                "evidenceClosureFingerprint": None,
                "issues": [f"unregistered_domain:{domain}"],
            }
    effective_registry["maturityAuthority"] = (
        "code_ceiling_plus_executable_capabilities_plus_sha256_evidence_closure"
    )
    return {
        "ok": not issues,
        "effectiveRegistry": effective_registry,
        "domains": decisions,
        "issues": issues,
    }
