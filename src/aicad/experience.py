"""Authority-first experience recall and exact review-coverage ledgers.

The recall layer deliberately separates two kinds of memory:

* canonical plugin rules and engineering-preflight gates are mandatory;
* harvested failure lessons remain review-only advisory candidates.

It never promotes a lesson, weakens a rule, or grants technical/manufacturing
readiness.  Its purpose is to make the complete applicable inventory visible
before generation and to invalidate affected checks after a design change.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .domain_maturity import assess_domain_registry
from .engine import PlanError


EXPECTED_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
}

_CONTEXT_FIELDS = frozenset(
    {
        "schema",
        "contextId",
        "domain",
        "spaces",
        "deliveryStage",
        "productFamilies",
        "riskTags",
        "changeTags",
        "requestedOutputs",
        "applicableStandards",
        "assumptions",
        "locks",
    }
)
_STANDARD_FIELDS = frozenset({"standard", "edition", "scope", "authority"})
_ASSUMPTION_FIELDS = frozenset({"id", "statement", "impact", "confirmationPolicy"})
_LEDGER_FIELDS = frozenset(
    {"schema", "contextFingerprint", "catalogFingerprint", "entries", "locks"}
)
_LEDGER_ENTRY_FIELDS = frozenset(
    {"coverageKey", "status", "evidenceRefs", "rationale", "validatedChangeTags"}
)
_EVIDENCE_FIELDS = frozenset({"path", "size", "sha256", "kind"})
_EVIDENCE_KINDS = {
    "calculation",
    "inspection",
    "native_host",
    "test",
    "authority",
    "review",
}
_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(?:[_:-][a-z0-9]+)*$")
_ASCII_ID_RE = re.compile(r"^[A-Z][A-Z0-9_.-]{2,63}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "advisory": 3}
_MATURITY_LEVELS = {"advanced", "constrained", "foundation"}
_ALL_INVALIDATION_TAGS = [
    "requirements",
    "standards",
    "jurisdiction",
    "delivery_stage",
    "geometry",
    "material",
    "process",
    "load",
    "interface",
    "evidence",
    "software",
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _exact_mapping(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        raise PlanError(
            f"{label} fields are not exact; missing={sorted(fields - actual)}, "
            f"extra={sorted(str(item) for item in actual - fields)}"
        )
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{label} must be non-empty text")
    return value.strip()


def _canonical_tags(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be an array")
    tags: list[str] = []
    for index, raw in enumerate(value):
        tag = _required_text(raw, f"{label}[{index}]")
        if tag != raw or not _TAG_RE.fullmatch(tag):
            raise PlanError(f"{label}[{index}] must be canonical lowercase tag text")
        tags.append(tag)
    if len(tags) != len(set(tags)):
        raise PlanError(f"{label} contains duplicate tags")
    return sorted(tags)




def _canonical_match_tags(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be an array")
    tags: list[str] = []
    for index, raw in enumerate(value):
        tag = _required_text(raw, f"{label}[{index}]")
        if tag != raw or (tag not in {"2d", "3d"} and not _TAG_RE.fullmatch(tag)):
            raise PlanError(f"{label}[{index}] must be a canonical match tag")
        tags.append(tag)
    if len(tags) != len(set(tags)):
        raise PlanError(f"{label} contains duplicate tags")
    return sorted(tags)

def canonical_context(value: object) -> dict[str, Any]:
    """Validate and canonicalize one complete design-context fingerprint."""

    value = _exact_mapping(value, _CONTEXT_FIELDS, "design context")
    if value.get("schema") != "aicad_design_context_v1":
        raise PlanError("design context schema must be aicad_design_context_v1")
    context_id = _required_text(value.get("contextId"), "contextId")
    if not _ASCII_ID_RE.fullmatch(context_id):
        raise PlanError("contextId must be a stable ASCII engineering identifier")
    domain = _required_text(value.get("domain"), "domain")
    spaces = value.get("spaces")
    if not isinstance(spaces, list) or not spaces or any(item not in {"2d", "3d"} for item in spaces):
        raise PlanError("spaces must be a non-empty unique subset of ['2d', '3d']")
    if len(spaces) != len(set(spaces)):
        raise PlanError("spaces contains duplicates")
    delivery_stage = _required_text(value.get("deliveryStage"), "deliveryStage")
    if delivery_stage not in {"concept", "prototype", "engineering_review", "production"}:
        raise PlanError(f"unsupported deliveryStage: {delivery_stage!r}")

    standards_raw = value.get("applicableStandards")
    if not isinstance(standards_raw, list):
        raise PlanError("applicableStandards must be an array")
    standards: list[dict[str, str]] = []
    for index, raw in enumerate(standards_raw):
        row = _exact_mapping(raw, _STANDARD_FIELDS, f"applicableStandards[{index}]")
        standard = {
            key: _required_text(row.get(key), f"applicableStandards[{index}].{key}")
            for key in ("standard", "edition", "scope", "authority")
        }
        standards.append(standard)
    standard_keys = [
        (row["standard"].casefold(), row["edition"].casefold(), row["scope"].casefold())
        for row in standards
    ]
    if len(standard_keys) != len(set(standard_keys)):
        raise PlanError("applicableStandards contains duplicate standard/edition/scope rows")

    assumptions_raw = value.get("assumptions")
    if not isinstance(assumptions_raw, list):
        raise PlanError("assumptions must be an array")
    assumptions: list[dict[str, str]] = []
    for index, raw in enumerate(assumptions_raw):
        row = _exact_mapping(raw, _ASSUMPTION_FIELDS, f"assumptions[{index}]")
        assumption_id = _required_text(row.get("id"), f"assumptions[{index}].id")
        if not _ASCII_ID_RE.fullmatch(assumption_id):
            raise PlanError(f"assumptions[{index}].id must be stable ASCII text")
        confirmation = _required_text(
            row.get("confirmationPolicy"), f"assumptions[{index}].confirmationPolicy"
        )
        if confirmation not in {"confirm_before_geometry", "confirm_before_release", "disclosed_default"}:
            raise PlanError(f"unsupported assumption confirmationPolicy: {confirmation!r}")
        assumptions.append(
            {
                "id": assumption_id,
                "statement": _required_text(row.get("statement"), f"assumptions[{index}].statement"),
                "impact": _required_text(row.get("impact"), f"assumptions[{index}].impact"),
                "confirmationPolicy": confirmation,
            }
        )
    if len({row["id"] for row in assumptions}) != len(assumptions):
        raise PlanError("assumptions contains duplicate IDs")
    if value.get("locks") != EXPECTED_LOCKS:
        raise PlanError("design context safety locks are not exact")

    return {
        "schema": "aicad_design_context_v1",
        "contextId": context_id,
        "domain": domain,
        "spaces": sorted(spaces),
        "deliveryStage": delivery_stage,
        "productFamilies": _canonical_tags(value.get("productFamilies"), "productFamilies"),
        "riskTags": _canonical_tags(value.get("riskTags"), "riskTags"),
        "changeTags": _canonical_tags(value.get("changeTags"), "changeTags"),
        "requestedOutputs": _canonical_tags(value.get("requestedOutputs"), "requestedOutputs"),
        "applicableStandards": sorted(
            standards,
            key=lambda row: (row["standard"].casefold(), row["edition"].casefold(), row["scope"].casefold()),
        ),
        "assumptions": sorted(assumptions, key=lambda row: row["id"]),
        "locks": dict(EXPECTED_LOCKS),
    }


def _safe_catalog_path(root: Path, relative: object) -> Path:
    text = _required_text(relative, "rule source path")
    if "\\" in text or re.match(r"^[A-Za-z]:", text):
        raise PlanError(f"unsafe rule source path: {text!r}")
    candidate = PurePosixPath(text)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise PlanError(f"unsafe rule source path: {text!r}")
    path = root.joinpath(*candidate.parts)
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not path.is_file() or resolved_root not in resolved.parents:
        raise PlanError(f"rule source escapes catalog root: {text!r}")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PlanError(f"{label} must contain a JSON object")
    return value


def _catalog_rule_index(catalog: Mapping[str, Any], rules_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    sources = catalog.get("ruleSources")
    if not isinstance(sources, list) or not sources:
        raise PlanError("experience catalog ruleSources must be non-empty")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            raise PlanError(f"ruleSources[{index}] must be an object")
        source_id = _required_text(source.get("id"), f"ruleSources[{index}].id")
        if source_id in source_ids:
            raise PlanError(f"duplicate rule source ID: {source_id}")
        source_ids.add(source_id)
        path = _safe_catalog_path(rules_root, source.get("path"))
        payload = _load_json(path, source_id)
        rules = payload.get("rules")
        if not isinstance(rules, list) or not rules:
            raise PlanError(f"rule source {source_id} has no rules array")
        for row in rules:
            if not isinstance(row, dict):
                raise PlanError(f"rule source {source_id} contains a non-object rule")
            rule_id = _required_text(row.get("id"), f"{source_id}.rule.id")
            key = (source_id, rule_id)
            if key in result:
                raise PlanError(f"duplicate rule ID in source {source_id}: {rule_id}")
            result[key] = {
                "sourceId": source_id,
                "sourcePath": source.get("path"),
                "id": rule_id,
                "name": str(row.get("name", "")),
                "requirement": _required_text(row.get("requirement"), f"{source_id}.{rule_id}.requirement"),
                "prevention": str(row.get("prevention", row.get("rootCausePrevented", ""))),
            }
    return result


def _load_domain_registry(
    catalog: Mapping[str, Any], rules_root: Path
) -> tuple[dict[str, Any], Path]:
    registry_path = _safe_catalog_path(rules_root, catalog.get("domainRegistry"))
    registry = _load_json(registry_path, "engineering domain registry")
    if registry.get("schema") != "aicad_engineering_domain_registry_v1":
        raise PlanError("engineering domain registry schema is invalid")
    if registry.get("safetyLocks") != EXPECTED_LOCKS:
        raise PlanError("engineering domain registry safety locks are not exact")
    domains = registry.get("domains")
    if not isinstance(domains, dict) or not domains:
        raise PlanError("engineering domain registry domains must be non-empty")
    for domain, raw in domains.items():
        if not isinstance(domain, str) or not _TAG_RE.fullmatch(domain):
            raise PlanError(f"engineering domain registry contains invalid domain: {domain!r}")
        if not isinstance(raw, dict):
            raise PlanError(f"engineering domain registry entry must be an object: {domain}")
        maturity = raw.get("maturity")
        if maturity not in _MATURITY_LEVELS:
            raise PlanError(f"engineering domain {domain} has invalid maturity: {maturity!r}")
        spaces = raw.get("spaces")
        if (
            not isinstance(spaces, list)
            or not spaces
            or len(spaces) != len(set(spaces))
            or any(space not in {"2d", "3d"} for space in spaces)
        ):
            raise PlanError(f"engineering domain {domain} has invalid spaces")
        _required_text(raw.get("label"), f"engineering domain {domain}.label")
        _required_text(
            raw.get("nativeGenerationBoundary"),
            f"engineering domain {domain}.nativeGenerationBoundary",
        )
        for field in ("dedicatedRuleCatalogs", "validators"):
            values = raw.get(field)
            if not isinstance(values, list) or not values or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise PlanError(f"engineering domain {domain}.{field} must be non-empty")
    release_policy = registry.get("releasePolicy")
    if not isinstance(release_policy, dict):
        raise PlanError("engineering domain registry releasePolicy is missing")
    if any(
        release_policy.get(field) is not False
        for field in ("productionArtifactExposureGranted", "professionalReleaseGranted")
    ):
        raise PlanError("engineering domain registry may not grant production or professional release")
    if release_policy.get("externalSpecialistEvidenceRequired") is not True:
        raise PlanError("engineering domain registry must require external specialist evidence")
    maturity = assess_domain_registry(registry, plugin_root=rules_root.parent)
    effective = maturity["effectiveRegistry"]
    effective["maturityAssessment"] = {"ok": maturity["ok"], "issues": maturity["issues"]}
    return effective, registry_path


def _domain_pack_inventory(
    rules_root: Path, registry: Mapping[str, Any], domain: str
) -> list[dict[str, Any]]:
    normative = _load_json(
        rules_root / "normative_governance_rules.json", "normative governance rules"
    )
    if normative.get("safetyLocks") != EXPECTED_LOCKS:
        raise PlanError("normative governance safety locks are not exact")
    packs = normative.get("domainPacks")
    domains = registry.get("domains")
    if not isinstance(packs, dict) or not isinstance(domains, dict):
        raise PlanError("normative domain packs or registry domains are missing")
    if set(packs) != set(domains):
        raise PlanError(
            "engineering domain registry and normative packs are not an exact set; "
            f"missingPacks={sorted(set(domains) - set(packs))}, "
            f"unregisteredPacks={sorted(set(packs) - set(domains))}"
        )
    if domain not in domains:
        raise PlanError(f"unregistered engineering domain: {domain!r}")
    names = packs.get(domain)
    if not isinstance(names, list) or not names:
        raise PlanError(f"normative domain pack is empty: {domain}")
    canonical_names = _canonical_tags(names, f"domainPacks.{domain}")
    return [
        {
            "coverageKey": f"domain-pack:{domain}:{name}",
            "label": f"{domain}.{name}",
            "source": "normative_governance_rules.json",
            "required": True,
            "allowNotApplicable": False,
            "invalidatedBy": list(_ALL_INVALIDATION_TAGS),
            "stage": "WF-02",
        }
        for name in canonical_names
    ]


def _dedicated_domain_rule_inventory(
    domain: str, rules: Mapping[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    source_id = {"packaging": "packaging", "civil": "civil"}.get(domain)
    prefix = {"packaging": "PKG-G", "civil": "CIV-G"}.get(domain)
    if source_id is None or prefix is None:
        return []
    matched = sorted(
        (
            rule
            for (source, rule_id), rule in rules.items()
            if source == source_id and rule_id.startswith(prefix)
        ),
        key=lambda row: row["id"],
    )
    expected_count = 25 if domain == "packaging" else 20
    expected_ids = [f"{prefix}{index:03d}" for index in range(1, expected_count + 1)]
    actual_ids = [row["id"] for row in matched]
    if actual_ids != expected_ids:
        raise PlanError(
            f"{domain} dedicated rule inventory is not exact; "
            f"expected={expected_ids}, actual={actual_ids}"
        )
    return [
        {
            "coverageKey": f"rule:{source_id}:{row['id']}",
            "label": f"{row['id']} {row['name']}".strip(),
            "source": row["sourcePath"],
            "required": True,
            "allowNotApplicable": False,
            "invalidatedBy": list(_ALL_INVALIDATION_TAGS),
            "stage": "WF-02",
        }
        for row in matched
    ]


def _catalog_evidence(
    catalog_file: Path,
    catalog: Mapping[str, Any],
    rules_root: Path,
    registry_path: Path,
) -> tuple[str, list[dict[str, Any]]]:
    paths: list[tuple[str, Path]] = [
        ("catalog", catalog_file),
        ("domainRegistry", registry_path),
    ]
    for index, source in enumerate(catalog.get("ruleSources", [])):
        if not isinstance(source, Mapping):
            raise PlanError(f"ruleSources[{index}] must be an object")
        paths.append(
            (
                f"ruleSource:{_required_text(source.get('id'), f'ruleSources[{index}].id')}",
                _safe_catalog_path(rules_root, source.get("path")),
            )
        )
    evidence = [
        {
            "id": evidence_id,
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for evidence_id, path in paths
    ]
    evidence.sort(key=lambda row: row["id"])
    return _fingerprint(evidence), evidence



def _context_tags(context: Mapping[str, Any]) -> set[str]:
    tags = {
        str(context["domain"]),
        f"domain:{context['domain']}",
        f"stage:{context['deliveryStage']}",
    }
    for space in context["spaces"]:
        tags.update({space, f"space:{space}"})
    for field, prefix in (
        ("productFamilies", "family"),
        ("riskTags", "risk"),
        ("changeTags", "change"),
        ("requestedOutputs", "output"),
    ):
        for value in context[field]:
            tags.update({value, f"{prefix}:{value}"})
    return tags


def _card_matches(card: Mapping[str, Any], context: Mapping[str, Any], tags: set[str]) -> tuple[bool, int]:
    domains = card.get("domains")
    stages = card.get("deliveryStages")
    match = card.get("match")
    if not isinstance(domains, list) or not domains or not isinstance(stages, list) or not stages:
        raise PlanError(f"experience card {card.get('id')} has invalid domains or deliveryStages")
    if "*" not in domains and context["domain"] not in domains:
        return False, 0
    if "*" not in stages and context["deliveryStage"] not in stages:
        return False, 0
    if not isinstance(match, Mapping) or set(match) != {"all", "any", "none"}:
        raise PlanError(f"experience card {card.get('id')} has invalid match contract")
    all_tags = set(_canonical_match_tags(match.get("all"), f"{card.get('id')}.match.all"))
    any_tags = set(_canonical_match_tags(match.get("any"), f"{card.get('id')}.match.any"))
    none_tags = set(_canonical_match_tags(match.get("none"), f"{card.get('id')}.match.none"))
    if not all_tags.issubset(tags) or (any_tags and not any_tags.intersection(tags)) or none_tags.intersection(tags):
        return False, 0
    return True, len(all_tags) * 10 + len(any_tags.intersection(tags))


def _canonical_preflight_inventory(rules_root: Path, domain: str) -> list[dict[str, Any]]:
    if domain not in {"mechanical", "electronics"}:
        return []
    rules = _load_json(rules_root / "production_readiness_rules.json", "production readiness rules")
    policy = rules.get("generationPreflightPolicy")
    if not isinstance(policy, dict):
        raise PlanError("production readiness rules lack generationPreflightPolicy")
    profile_name = policy.get("canonicalProfileByDomain", {}).get(domain)
    profile = rules.get(profile_name)
    if not isinstance(profile, dict):
        raise PlanError(f"canonical production profile is missing for {domain}")
    result: list[dict[str, Any]] = []
    for section in policy.get("includedSections", []):
        gates = profile.get(section)
        if not isinstance(gates, dict) or not gates:
            raise PlanError(f"canonical preflight section is missing: {domain}.{section}")
        for gate_name, gate in gates.items():
            result.append(
                {
                    "coverageKey": f"preflight:{domain}.{section}.{gate_name}",
                    "label": f"{domain}.{section}.{gate_name}",
                    "source": "production_readiness_rules.json",
                    "required": True,
                    "allowNotApplicable": section != "intent",
                    "invalidatedBy": ["requirements", "standards", "geometry", "material", "process", "load", "interface", "evidence"],
                    "stage": section,
                    "gate": gate,
                }
            )
    rules_by_id = {row.get("id"): row for row in rules.get("rules", []) if isinstance(row, dict)}
    for rule_id in policy.get("sharedRuleIds", []):
        if rule_id not in rules_by_id:
            raise PlanError(f"canonical shared preflight rule is missing: {rule_id}")
        result.append(
            {
                "coverageKey": f"preflight:shared.rules.{rule_id}",
                "label": f"shared.rules.{rule_id}",
                "source": "production_readiness_rules.json",
                "required": True,
                "allowNotApplicable": False,
                "invalidatedBy": ["requirements", "standards", "geometry", "material", "process", "load", "interface", "evidence"],
                "stage": "shared",
                "gate": rules_by_id[rule_id],
            }
        )
    return sorted(result, key=lambda row: row["coverageKey"])


def _candidate_lesson_matches(
    bundle_paths: Sequence[str | Path], context: Mapping[str, Any], tags: set[str], limit: int
) -> list[dict[str, Any]]:
    tokens = {item.replace(":", "_") for item in tags}
    rows: list[tuple[int, dict[str, Any]]] = []
    for bundle_path in bundle_paths:
        path = Path(bundle_path).expanduser().resolve()
        try:
            if not path.is_file() or path.stat().st_size > 10_000_000:
                raise PlanError(f"candidate lesson bundle is missing or too large: {path}")
            payload = _load_json(path, "candidate lesson bundle")
        except OSError as exc:
            raise PlanError(f"candidate lesson bundle cannot be inspected: {path}") from exc
        if payload.get("schema") != "aicad_lesson_bundle_v1" or payload.get("safetyLocks") != EXPECTED_LOCKS:
            raise PlanError(f"candidate lesson bundle has invalid schema or safety locks: {path}")
        lessons = payload.get("lessons")
        if not isinstance(lessons, list):
            raise PlanError(f"candidate lesson bundle has no lessons array: {path}")
        for lesson in lessons:
            if not isinstance(lesson, Mapping) or lesson.get("domain") != context["domain"]:
                continue
            text = " ".join(
                str(lesson.get(field, "")).casefold()
                for field in ("failureAlias", "failingCheck", "symptom", "rootCause", "correction")
            ).replace("-", "_").replace(".", "_")
            score = sum(1 for token in tokens if token and token in text)
            if score == 0:
                continue
            candidate_rule = lesson.get("candidateRule") if isinstance(lesson.get("candidateRule"), Mapping) else {}
            rows.append(
                (
                    score,
                    {
                        "lessonId": str(lesson.get("lessonId", "")),
                        "failureAlias": str(lesson.get("failureAlias", "")),
                        "domain": str(lesson.get("domain", "")),
                        "rootCause": str(lesson.get("rootCause", "")),
                        "correction": str(lesson.get("correction", "")),
                        "candidateRuleId": str(candidate_rule.get("id", "")),
                        "authority": "review_only_candidate",
                        "maySatisfyCoverage": False,
                        "automaticPromotion": False,
                        "safetyLocks": dict(EXPECTED_LOCKS),
                    },
                )
            )
    rows.sort(key=lambda item: (-item[0], item[1]["lessonId"]))
    return [row for _, row in rows[:limit]]


def _coverage_rows(
    context: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    rules: Mapping[tuple[str, str], dict[str, Any]],
    rules_root: Path,
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    domain = str(context["domain"])
    result = _domain_pack_inventory(rules_root, registry, domain)
    result.extend(_dedicated_domain_rule_inventory(domain, rules))
    result.extend(_canonical_preflight_inventory(rules_root, domain))
    seen = {row["coverageKey"] for row in result}
    if len(seen) != len(result):
        raise PlanError(f"duplicate canonical coverage key for domain {domain}")
    for card in cards:
        invalidated_by = list(card.get("invalidatedBy", []))
        for ref in card.get("ruleRefs", []):
            source_id = str(ref.get("sourceId", ""))
            rule_id = str(ref.get("ruleId", ""))
            rule = rules[(source_id, rule_id)]
            key = f"rule:{source_id}:{rule_id}"
            if key not in seen:
                result.append(
                    {
                        "coverageKey": key,
                        "label": f"{rule_id} {rule['name']}".strip(),
                        "source": rule["sourcePath"],
                        "required": True,
                        "allowNotApplicable": False,
                        "invalidatedBy": invalidated_by,
                        "stage": str(card.get("workflowStage", "review")),
                    }
                )
                seen.add(key)
        for index, check in enumerate(card.get("checklist", []), 1):
            key = f"experience:{card['id']}:{index:02d}"
            if key in seen:
                raise PlanError(f"duplicate generated coverage key: {key}")
            result.append(
                {
                    "coverageKey": key,
                    "label": _required_text(check, f"{card['id']}.checklist[{index - 1}]"),
                    "source": f"experience-card:{card['id']}",
                    "required": bool(card.get("required", False)),
                    "allowNotApplicable": not bool(card.get("required", False)),
                    "invalidatedBy": invalidated_by,
                    "stage": str(card.get("workflowStage", "review")),
                }
            )
            seen.add(key)
    return sorted(result, key=lambda row: row["coverageKey"])


def recall_experience(
    context_value: object,
    catalog_path: str | Path,
    rules_root: str | Path,
    *,
    max_cards: int = 12,
    candidate_lesson_bundles: Sequence[str | Path] = (),
) -> dict[str, Any]:
    """Return compact authoritative recall, advisory lessons and an exact ledger template."""

    if not isinstance(max_cards, int) or isinstance(max_cards, bool) or not 1 <= max_cards <= 50:
        raise PlanError("max_cards must be an integer from 1 to 50")
    context = canonical_context(context_value)
    catalog_file = Path(catalog_path).resolve(strict=True)
    catalog = _load_json(catalog_file, "experience recall catalog")
    if catalog.get("schema") != "aicad_experience_recall_catalog_v1":
        raise PlanError("experience catalog schema must be aicad_experience_recall_catalog_v1")
    if catalog.get("safetyLocks") != EXPECTED_LOCKS:
        raise PlanError("experience catalog safety locks are not exact")
    rules_directory = Path(rules_root).resolve(strict=True)
    registry, registry_path = _load_domain_registry(catalog, rules_directory)
    domains = registry["domains"]
    domain = str(context["domain"])
    if domain not in domains:
        raise PlanError(f"unregistered engineering domain: {domain!r}")
    domain_profile_raw = domains[domain]
    unsupported_spaces = sorted(set(context["spaces"]) - set(domain_profile_raw["spaces"]))
    if unsupported_spaces:
        raise PlanError(
            f"engineering domain {domain} does not support spaces: {unsupported_spaces}"
        )
    rule_index = _catalog_rule_index(catalog, rules_directory)
    cards_raw = catalog.get("cards")
    if not isinstance(cards_raw, list) or not cards_raw:
        raise PlanError("experience catalog cards must be non-empty")
    tags = _context_tags(context)
    matched: list[tuple[int, dict[str, Any]]] = []
    ids: set[str] = set()
    for card in cards_raw:
        if not isinstance(card, dict):
            raise PlanError("experience catalog contains a non-object card")
        card_domains = card.get("domains")
        if (
            not isinstance(card_domains, list)
            or not card_domains
            or any(item != "*" and item not in domains for item in card_domains)
        ):
            raise PlanError(
                f"experience card {card.get('id')} references an unregistered domain"
            )
        card_id = _required_text(card.get("id"), "experience card id")
        if card_id in ids or not _ASCII_ID_RE.fullmatch(card_id):
            raise PlanError(f"duplicate or invalid experience card ID: {card_id!r}")
        ids.add(card_id)
        severity = str(card.get("severity", ""))
        if severity not in _SEVERITY_ORDER:
            raise PlanError(f"experience card {card_id} has invalid severity")
        for ref in card.get("ruleRefs", []):
            if not isinstance(ref, Mapping):
                raise PlanError(f"experience card {card_id} has a non-object ruleRef")
            key = (str(ref.get("sourceId", "")), str(ref.get("ruleId", "")))
            if key not in rule_index:
                raise PlanError(f"experience card {card_id} references missing rule {key}")
        matches, score = _card_matches(card, context, tags)
        if matches:
            matched.append((score, card))
    matched.sort(
        key=lambda item: (
            _SEVERITY_ORDER[str(item[1]["severity"])],
            -item[0],
            str(item[1]["id"]),
        )
    )
    required_cards = [card for _, card in matched if card.get("required") is True]
    optional_cards = [card for _, card in matched if card.get("required") is not True]
    selected = required_cards + optional_cards[: max(0, max_cards - len(required_cards))]
    selected_ids = {card["id"] for card in selected}
    selected.sort(
        key=lambda card: (_SEVERITY_ORDER[str(card["severity"])], str(card["id"]))
    )

    rendered_cards: list[dict[str, Any]] = []
    for card in selected:
        rendered_cards.append(
            {
                "id": card["id"],
                "title": _required_text(card.get("title"), f"{card['id']}.title"),
                "severity": card["severity"],
                "required": bool(card.get("required", False)),
                "workflowStage": _required_text(card.get("workflowStage"), f"{card['id']}.workflowStage"),
                "whyRecalled": _required_text(card.get("whyRecalled"), f"{card['id']}.whyRecalled"),
                "ruleRefs": [
                    rule_index[(str(ref["sourceId"]), str(ref["ruleId"]))]
                    for ref in card.get("ruleRefs", [])
                ],
                "checklist": list(card.get("checklist", [])),
                "invalidatedBy": list(card.get("invalidatedBy", [])),
                "reusableArtifacts": list(card.get("reusableArtifacts", [])),
                "estimatedReviewMinutesAvoided": int(card.get("estimatedReviewMinutesAvoided", 0)),
            }
        )

    coverage_rows = _coverage_rows(
        context, selected, rule_index, rules_directory, registry
    )
    context_fingerprint = _fingerprint(context)
    catalog_fingerprint, catalog_evidence = _catalog_evidence(
        catalog_file, catalog, rules_directory, registry_path
    )
    domain_profile = {
        "id": domain,
        "label": domain_profile_raw["label"],
        "declaredMaturity": domain_profile_raw["declaredMaturity"],
        "maturity": domain_profile_raw["maturity"],
        "maturityDecision": dict(domain_profile_raw["maturityDecision"]),
        "spaces": sorted(domain_profile_raw["spaces"]),
        "dedicatedRuleCatalogs": list(domain_profile_raw["dedicatedRuleCatalogs"]),
        "validators": list(domain_profile_raw["validators"]),
        "nativeGenerationBoundary": domain_profile_raw["nativeGenerationBoundary"],
        "productionReleaseBlocked": True,
        "professionalReleaseBlocked": True,
        "specialistGenerationBlocked": domain_profile_raw["maturity"] == "foundation",
        "specialistEvidenceRequired": True,
    }
    changed = set(context["changeTags"])
    coverage_template = {
        "schema": "aicad_review_coverage_ledger_v1",
        "contextFingerprint": context_fingerprint,
        "catalogFingerprint": catalog_fingerprint,
        "entries": [
            {
                "coverageKey": row["coverageKey"],
                "status": "pending",
                "evidenceRefs": [],
                "rationale": "",
                "validatedChangeTags": [],
            }
            for row in coverage_rows
        ],
        "locks": dict(EXPECTED_LOCKS),
    }
    workflow = catalog.get("workflow")
    if not isinstance(workflow, list) or not workflow:
        raise PlanError("experience catalog workflow must be non-empty")
    candidate_lessons = _candidate_lesson_matches(
        candidate_lesson_bundles, context, tags, min(max_cards, 12)
    )
    compact_material = {
        "cards": [card["id"] for card in rendered_cards],
        "rules": sorted(
            {rule["id"] for card in rendered_cards for rule in card["ruleRefs"]}
        ),
        "coverageKeys": [row["coverageKey"] for row in coverage_rows],
    }
    return {
        "ok": True,
        "schema": "aicad_experience_recall_v1",
        "context": context,
        "contextFingerprint": context_fingerprint,
        "catalogFingerprint": catalog_fingerprint,
        "matchedTags": sorted(tags),
        "workflow": workflow,
        "cards": rendered_cards,
        "catalogEvidence": catalog_evidence,
        "domainProfile": domain_profile,
        "candidateLessons": candidate_lessons,
        "coverageInventory": coverage_rows,
        "coverageTemplate": coverage_template,
        "unresolvedInputs": {
            "standardsLedgerEmpty": not bool(context["applicableStandards"]),
            "standardsSourceBindingRequired": True,
            "confirmBeforeGeometryAssumptions": [
                row["id"]
                for row in context["assumptions"]
                if row["confirmationPolicy"] == "confirm_before_geometry"
            ],
            "domainMaturity": domain_profile["maturity"],
            "nativeGenerationBoundary": domain_profile["nativeGenerationBoundary"],
            "specialistEvidenceRequired": True,
            "specialistGenerationBlocked": domain_profile["maturity"] == "foundation",
            "productionStageBlocked": context["deliveryStage"] == "production",
            "blockingReasons": (
                (["applicable_standards_not_source_bound"] if not context["applicableStandards"] else [])
                + [
                    f"assumption_requires_geometry_confirmation:{row['id']}"
                    for row in context["assumptions"]
                    if row["confirmationPolicy"] == "confirm_before_geometry"
                ]
                + (
                    ["foundation_domain_has_no_specialist_generation_closure"]
                    if domain_profile["maturity"] == "foundation"
                    and context["deliveryStage"] in {"engineering_review", "production"}
                    else []
                )
            ),
        },
        "costControl": {
            "authority": "catalog_heuristic_not_financial_truth",
            "catalogCardsConsidered": len(cards_raw),
            "matchedCards": len(matched),
            "returnedCards": len(rendered_cards),
            "suppressedOptionalCards": len([card for _, card in matched if card["id"] not in selected_ids]),
            "estimatedReviewMinutesAvoided": sum(card["estimatedReviewMinutesAvoided"] for card in rendered_cards),
            "estimatedCompactPromptTokens": max(1, len(_canonical_json(compact_material)) // 4),
            "deduplicationKeyCount": len(coverage_rows),
        },
        "changeInvalidation": {
            "changedTags": sorted(changed),
            "affectedCoverageKeys": [
                row["coverageKey"]
                for row in coverage_rows
                if changed.intersection(row.get("invalidatedBy", []))
                or "*" in row.get("invalidatedBy", [])
            ],
        },
        "readinessBoundary": {
            "recallIsEngineeringApproval": False,
            "candidateLessonsMaySatisfyRules": False,
            "technicalPackageReady": False,
            "manufacturingAuthorized": False,
            "fabricationAuthorized": False,
        },
        "locks": dict(EXPECTED_LOCKS),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_evidence_file(
    evidence_root: str | Path | None, value: object, label: str
) -> tuple[Path, str]:
    if evidence_root is None:
        raise PlanError(f"{label} requires a controlled evidence root")
    root = Path(evidence_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise PlanError(f"{label} evidence root must be a directory")
    text = _required_text(value, f"{label}.path")
    if "\\" in text or re.match(r"^[A-Za-z]:", text):
        raise PlanError(f"{label}.path must be safe canonical relative POSIX text")
    relative = PurePosixPath(text)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != text
    ):
        raise PlanError(f"{label}.path must be safe canonical relative POSIX text")
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", lambda: False)
        if cursor.is_symlink() or is_junction():
            raise PlanError(f"{label}.path may not traverse a link or junction")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PlanError(f"{label}.path does not identify a real evidence file") from exc
    if not candidate.is_file() or (resolved != root and root not in resolved.parents):
        raise PlanError(f"{label}.path escapes the evidence root or is not a file")
    return resolved, relative.as_posix()


def _canonical_evidence_refs(
    value: object, label: str, evidence_root: str | Path | None
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be an array")
    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(value):
        row = _exact_mapping(raw, _EVIDENCE_FIELDS, f"{label}[{index}]")
        path, relative = _safe_evidence_file(
            evidence_root, row.get("path"), f"{label}[{index}]"
        )
        size = row.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise PlanError(f"{label}[{index}].size must be a non-negative integer")
        actual_size = path.stat().st_size
        if size != actual_size:
            raise PlanError(
                f"{label}[{index}].size does not match evidence file; "
                f"declared={size}, actual={actual_size}"
            )
        sha256 = row.get("sha256")
        if not isinstance(sha256, str) or not _HEX64_RE.fullmatch(sha256):
            raise PlanError(f"{label}[{index}].sha256 must be lowercase SHA-256")
        actual_sha256 = _sha256_file(path)
        if sha256 != actual_sha256:
            raise PlanError(f"{label}[{index}].sha256 does not match evidence file")
        kind = row.get("kind")
        if kind not in _EVIDENCE_KINDS:
            raise PlanError(
                f"{label}[{index}].kind must be one of {sorted(_EVIDENCE_KINDS)}"
            )
        path_key = relative.casefold()
        if path_key in seen_paths:
            raise PlanError(f"{label} contains duplicate evidence paths")
        seen_paths.add(path_key)
        rows.append(
            {
                "path": relative,
                "size": size,
                "sha256": sha256,
                "kind": kind,
            }
        )
    return sorted(rows, key=lambda row: (row["path"].casefold(), row["kind"], row["sha256"]))


def validate_coverage_ledger(
    recall: object,
    ledger_value: object,
    *,
    evidence_root: str | Path | None = None,
) -> dict[str, Any]:
    """Require an exact, current, evidence-bearing result for every recalled check."""

    if not isinstance(recall, Mapping) or recall.get("schema") != "aicad_experience_recall_v1":
        raise PlanError("recall must be an aicad_experience_recall_v1 object")
    ledger = _exact_mapping(ledger_value, _LEDGER_FIELDS, "coverage ledger")
    if ledger.get("schema") != "aicad_review_coverage_ledger_v1":
        raise PlanError("coverage ledger schema must be aicad_review_coverage_ledger_v1")
    for field in ("contextFingerprint", "catalogFingerprint"):
        value = ledger.get(field)
        if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
            raise PlanError(f"coverage ledger {field} must be lowercase SHA-256")
        if value != recall.get(field):
            raise PlanError(f"coverage ledger {field} is stale")
    if ledger.get("locks") != EXPECTED_LOCKS:
        raise PlanError("coverage ledger safety locks are not exact")
    inventory = recall.get("coverageInventory")
    if not isinstance(inventory, list) or not inventory:
        raise PlanError("recall coverage inventory is missing")
    expected = {row["coverageKey"]: row for row in inventory}
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise PlanError("coverage ledger entries must be an array")
    actual: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(entries):
        row = _exact_mapping(raw, _LEDGER_ENTRY_FIELDS, f"entries[{index}]")
        key = _required_text(row.get("coverageKey"), f"entries[{index}].coverageKey")
        if key in actual:
            raise PlanError(f"coverage ledger contains duplicate key: {key}")
        status = _required_text(row.get("status"), f"entries[{index}].status")
        if status not in {"pending", "pass", "failed", "not_applicable"}:
            raise PlanError(f"coverage ledger has unsupported status: {status!r}")
        actual[key] = {
            "coverageKey": key,
            "status": status,
            "evidenceRefs": _canonical_evidence_refs(
                row.get("evidenceRefs"),
                f"entries[{index}].evidenceRefs",
                evidence_root,
            ),
            "rationale": str(row.get("rationale", "")).strip(),
            "validatedChangeTags": _canonical_tags(
                row.get("validatedChangeTags"), f"entries[{index}].validatedChangeTags"
            ),
        }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise PlanError(f"coverage ledger inventory is not exact; missing={missing}, extra={extra}")

    changed = set(recall.get("context", {}).get("changeTags", []))
    failures: list[dict[str, Any]] = []
    passed = 0
    not_applicable = 0
    for key in sorted(expected):
        spec = expected[key]
        row = actual[key]
        reasons: list[str] = []
        affected_tags = sorted(
            changed.intersection(spec.get("invalidatedBy", []))
            if "*" not in spec.get("invalidatedBy", [])
            else changed
        )
        if row["status"] == "pass":
            if not row["evidenceRefs"]:
                reasons.append("pass_requires_evidence")
            if not set(affected_tags).issubset(row["validatedChangeTags"]):
                reasons.append("affected_change_not_revalidated")
            if not reasons:
                passed += 1
        elif row["status"] == "not_applicable":
            if not spec.get("allowNotApplicable"):
                reasons.append("not_applicable_forbidden")
            if not row["rationale"] or not row["evidenceRefs"]:
                reasons.append("not_applicable_requires_authority_and_rationale")
            if not reasons:
                not_applicable += 1
        else:
            reasons.append(f"status_{row['status']}")
        if reasons:
            failures.append({"coverageKey": key, "reasons": reasons})
    ok = not failures
    return {
        "ok": ok,
        "schema": "aicad_review_coverage_validation_v1",
        "status": "pass" if ok else "blocked",
        "conclusion": "coverage_ready_for_next_stage_only" if ok else "coverage_incomplete_or_stale",
        "counts": {
            "expected": len(expected),
            "passed": passed,
            "notApplicable": not_applicable,
            "failedOrPending": len(failures),
        },
        "failures": failures,
        "contextFingerprint": recall["contextFingerprint"],
        "catalogFingerprint": recall["catalogFingerprint"],
        "readinessBoundary": {
            "technicalPackageReady": False,
            "productionReleaseEligible": False,
            "manufacturingAuthorized": False,
            "fabricationAuthorized": False,
        },
        "locks": dict(EXPECTED_LOCKS),
    }


def populate_coverage_for_test(
    recall: Mapping[str, Any], *, evidence_root: str | Path
) -> dict[str, Any]:
    """Build real hash-bound fixture evidence; never use this helper for production proof."""

    root = Path(evidence_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    evidence_directory = root / "coverage"
    evidence_directory.mkdir(parents=True, exist_ok=True)
    ledger = json.loads(json.dumps(recall["coverageTemplate"], ensure_ascii=False))
    changed = set(recall.get("context", {}).get("changeTags", []))
    specs = {row["coverageKey"]: row for row in recall["coverageInventory"]}
    for row in ledger["entries"]:
        key_hash = hashlib.sha256(row["coverageKey"].encode("utf-8")).hexdigest()
        relative = f"coverage/{key_hash}.txt"
        path = root.joinpath(*PurePosixPath(relative).parts)
        payload = (row["coverageKey"] + "\\n").encode("utf-8")
        path.write_bytes(payload)
        row["status"] = "pass"
        row["evidenceRefs"] = [
            {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "kind": "test",
            }
        ]
        invalidated = specs[row["coverageKey"]].get("invalidatedBy", [])
        row["validatedChangeTags"] = sorted(
            changed if "*" in invalidated else changed.intersection(invalidated)
        )
    return ledger
