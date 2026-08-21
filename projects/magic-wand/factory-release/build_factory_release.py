#!/usr/bin/env python3
"""Freeze and build the magic-wand package-specific factory release.

The script intentionally separates the one-time source-lock operation from an
ordinary rebuild.  Ordinary builds trust no current bytes: the upstream
manifests, package document, interface and every package artifact are checked
against frozen size/SHA-256 declarations before the repository manufacturing
core is invoked.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
REPO_ROOT = HERE.parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from aicad.manufacturing_validation import validate_manufacturing_release_package
from aicad.manufacturing_workflow import (
    build_manufacturing_release_package,
    validate_manufacturing_release_review_html,
)


from source_adapter import (
    adapt_mechanical_manifest,
    manifests_equivalent,
    receiver_interface_semantics,
    validate_receiver_coordinate_contract,
    wand_interface_semantics,
)

PACKAGE_ID = "MW-FACTORY-RELEASE-001"
PACKAGE_SCHEMA = "aicad_manufacturing_release_package_v1"
LOCK_SCHEMA = "aicad_magic_wand_factory_source_lock_v1"
MECHANICAL_DELIVERY_SCHEMA = "aicad_magic_wand_mechanical_factory_delivery_manifest_v1"
MECHANICAL_SCHEMA = "aicad_magic_wand_mechanical_source_manifest_v1"
ELECTRONICS_SCHEMA = "aicad_magic_wand_electronics_source_manifest_v1"
MECHANICAL_MANIFEST_REL = (
    "mechanical/factory-rfq/reports/factory-delivery-manifest.json"
)
MECHANICAL_COMPAT_MANIFEST_REL = "mechanical/factory-rfq/reports/mechanical-source-manifest.json"
ELECTRONICS_MANIFEST_REL = "electronics/factory-release-source-manifest.json"
WAND_INTERFACE_REL = "electronics/wand/wand-electromechanical-interface.json"
PACKAGE_REL = "factory-release/manufacturing-release-package.json"
LOCK_REL = "factory-release/source-lock.json"
BUILT_REL = "factory-release/built"
RELEASE_NAME = "magic-wand-factory-release"
NEUTRAL_ID = "unassigned_rfq_recipient"

EXPECTED_PART_IDS = {
    "MW-M-001A",
    "MW-M-001B",
    "MW-M-002",
    "MW-M-003",
    "MW-M-004",
    "MW-M-005",
    "MW-P-001",
    "MW-M-101",
    "MW-M-102",
}
EXPECTED_ASSEMBLY_IDS = {"MW-A-001", "MW-A-101"}
EXPECTED_FABRICATION_LAYERS = {
    "F.Cu",
    "In1.Cu",
    "In2.Cu",
    "B.Cu",
    "F.Paste",
    "B.Paste",
    "F.Mask",
    "B.Mask",
    "F.SilkS",
    "B.SilkS",
    "Edge.Cuts",
}
ZERO_GATE_KEYS = (
    "ercErrors",
    "drcViolations",
    "unconnected",
    "exclusions",
    "suppressions",
)
TEXT_SCAN_SUFFIXES = {
    ".json",
    ".html",
    ".htm",
    ".md",
    ".txt",
    ".rpt",
    ".csv",
    ".svg",
    ".dru",
    ".kicad_pro",
    ".kicad_sch",
    ".kicad_pcb",
    ".gbrjob",
}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_PATH = re.compile(r"(?i)(?:^|[\s\"'])(?:[A-Z]:[\\/]|file://)")
_USER_PATH = re.compile(
    r"(?i)(?:^|[\s\"'])(?:(?:users|home)[\\/]|/(?:users|home)/)[^\\/\s\"']+(?:[\\/]|$)"
)
_BANNED_COMPONENT = re.compile(
    r"(?i)^(?:probe(?:[-_].*)?|wip(?:[-_].*)?|temp(?:[-_].*)?|tmp(?:[-_].*)?|__pycache__)$"
)
_BANNED_PATH_TOKEN = re.compile(
    r"(?i)(?:^|[-_.])(?:probe|wip|temp|tmp)(?:[-_.]|$)"
)


class ReleaseBuildError(RuntimeError):
    """A fail-closed source or package contract violation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_text(text, encoding="utf-8", newline="\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError(f"{label} is not readable UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseBuildError(f"{label} root must be a JSON object")
    return value


def _component_is_banned(component: str) -> bool:
    return bool(
        _BANNED_COMPONENT.fullmatch(component)
        or _BANNED_PATH_TOKEN.search(component)
        or component.casefold().endswith(".kicad_prl")
    )


def _safe_relative(path_text: Any, location: str) -> PurePosixPath:
    if not isinstance(path_text, str) or not path_text or "\\" in path_text:
        raise ReleaseBuildError(f"{location}: path must be a POSIX relative path")
    pure = PurePosixPath(path_text)
    if (
        pure.is_absolute()
        or "." in pure.parts
        or ".." in pure.parts
        or not pure.parts
        or ":" in pure.parts[0]
    ):
        raise ReleaseBuildError(f"{location}: unsafe/traversing path {path_text!r}")
    for component in pure.parts:
        if _component_is_banned(component):
            raise ReleaseBuildError(
                f"{location}: probe/WIP/temp/session artifact is forbidden: {path_text}"
            )
    return pure


def _resolved_project_file(path_text: Any, location: str) -> Path:
    pure = _safe_relative(path_text, location)
    candidate = PROJECT_ROOT.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(PROJECT_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReleaseBuildError(
            f"{location}: referenced file is missing or outside the project root: {path_text}"
        ) from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise ReleaseBuildError(f"{location}: evidence must be a real regular file")
    return resolved


def evidence_ref(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(PROJECT_ROOT.resolve(strict=True)).as_posix()
    except ValueError as exc:
        raise ReleaseBuildError(f"evidence is outside projects/magic-wand: {path}") from exc
    _safe_relative(relative, "evidence.path")
    return {"path": relative, "size": resolved.stat().st_size, "sha256": _sha256(resolved)}


def verify_artifact_reference(
    reference: Any,
    *,
    location: str,
    scan_text: bool = True,
) -> Path:
    if not isinstance(reference, dict):
        raise ReleaseBuildError(f"{location}: evidence reference must be an object")
    required = {"path", "size", "sha256"}
    if not required.issubset(reference):
        raise ReleaseBuildError(f"{location}: evidence reference lacks path/size/sha256")
    declared_size = reference.get("size")
    declared_sha = reference.get("sha256")
    if (
        isinstance(declared_size, bool)
        or not isinstance(declared_size, int)
        or declared_size < 1
        or not isinstance(declared_sha, str)
        or _SHA.fullmatch(declared_sha) is None
    ):
        raise ReleaseBuildError(f"{location}: invalid size/SHA-256 declaration")
    path = _resolved_project_file(reference.get("path"), location + ".path")
    actual_size = path.stat().st_size
    actual_sha = _sha256(path)
    if actual_size != declared_size or actual_sha != declared_sha:
        raise ReleaseBuildError(
            f"{location}: artifact mutation/stale lock; "
            f"declared {declared_size}/{declared_sha}, actual {actual_size}/{actual_sha}"
        )
    if scan_text and path.suffix.casefold() in TEXT_SCAN_SUFFIXES:
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        if _DRIVE_PATH.search(source) or _USER_PATH.search(source):
            raise ReleaseBuildError(
                f"{location}: controlled public text leaks an absolute drive/user path"
            )
    return path


def _walk_evidence_refs(
    value: Any, location: str = "$"
) -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if {"path", "size", "sha256"}.issubset(value):
            yield location, value
            return
        for key, child in value.items():
            yield from _walk_evidence_refs(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_evidence_refs(child, f"{location}[{index}]")


def _assert_no_banned_path_strings(value: Any, location: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_no_banned_path_strings(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_banned_path_strings(child, f"{location}[{index}]")
    elif isinstance(value, str) and ("/" in value or "\\" in value):
        normalized = value.replace("\\", "/")
        if (
            "\\" in value or normalized.startswith("/")
            or _DRIVE_PATH.search(value) or _USER_PATH.search(value)
            or any(component in {".", ".."} for component in normalized.split("/"))
        ):
            raise ReleaseBuildError(
                f"{location}: formal manifest/interface/frozen-routes path is absolute or nonportable")
        components = [component.split("?", 1)[0].split("#", 1)[0] for component in normalized.split("/")]
        if any(_component_is_banned(component) for component in components if component):
            raise ReleaseBuildError(
                f"{location}: formal manifest/interface/frozen-routes path contains probe/WIP/temp data"
            )


def _unique_evidence_ref_by_name(value: Any, basename: str, label: str) -> dict[str, Any]:
    matches: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for _, reference in _walk_evidence_refs(value, label):
        path_text = reference.get("path")
        if isinstance(path_text, str) and PurePosixPath(path_text).name.casefold() == basename.casefold():
            key = (path_text, reference.get("size"), reference.get("sha256"))
            matches[key] = reference
    if len(matches) != 1:
        raise ReleaseBuildError(f"{label}: exactly one exact {basename} evidence reference is required")
    return copy.deepcopy(next(iter(matches.values())))


def _optional_exact_source_board(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("sha256"), str) or _SHA.fullmatch(value["sha256"]) is None:
        raise ReleaseBuildError(f"{label}: sourceBoard must consume one exact lowercase board SHA-256")
    has_path = "path" in value
    has_size = "size" in value
    if has_path != has_size:
        raise ReleaseBuildError(f"{label}: sourceBoard path and size must be declared together")
    if has_path:
        verify_artifact_reference(value, location=label)
    return copy.deepcopy(value)


def _normalize_manifest_refs(value: Any, manifest_path: Path) -> Any:
    """Return a deep copy whose evidence paths are project-root relative."""
    value = copy.deepcopy(value)
    for location, reference in _walk_evidence_refs(value):
        raw_path = reference.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        direct = PROJECT_ROOT.joinpath(*PurePosixPath(raw_path.replace("\\", "/")).parts)
        if direct.is_file():
            normalized = direct.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        else:
            local = manifest_path.parent.joinpath(
                *PurePosixPath(raw_path.replace("\\", "/")).parts
            )
            try:
                normalized = local.resolve(strict=True).relative_to(
                    PROJECT_ROOT.resolve(strict=True)
                ).as_posix()
            except (OSError, ValueError) as exc:
                raise ReleaseBuildError(
                    f"{location}: source-manifest artifact is unavailable: {raw_path}"
                ) from exc
        reference["path"] = normalized
        verify_artifact_reference(reference, location=location)
    return value


def _find_manifest(
    relative: str,
    schema: str,
    wait_seconds: int,
) -> Path:
    deadline = time.monotonic() + max(0, wait_seconds)
    preferred = PROJECT_ROOT.joinpath(*PurePosixPath(relative).parts)
    while True:
        candidates: list[Path] = []
        if preferred.is_file():
            try:
                preferred_document = _load_json(preferred, "preferred upstream manifest")
            except ReleaseBuildError:
                preferred_document = {}
            if preferred_document.get("schema") == schema and preferred_document.get("status") == "frozen":
                candidates.append(preferred)
        for path in PROJECT_ROOT.rglob("*source-manifest.json"):
            if path == preferred or any(_component_is_banned(part) for part in path.parts):
                continue
            try:
                candidate = _load_json(path, "source manifest candidate")
            except ReleaseBuildError:
                continue
            if candidate.get("schema") == schema and candidate.get("status") == "frozen":
                candidates.append(path)
        unique = sorted({path.resolve() for path in candidates})
        if len(unique) == 1:
            return unique[0]
        if len(unique) > 1:
            raise ReleaseBuildError(
                f"multiple {schema} manifests found; keep one formal frozen source manifest"
            )
        if time.monotonic() >= deadline:
            raise ReleaseBuildError(
                f"missing frozen upstream manifest {relative} ({schema})"
            )
        time.sleep(min(5.0, max(0.1, deadline - time.monotonic())))


def _require_frozen_manifest(
    path: Path,
    schema: str | set[str],
    label: str,
) -> dict[str, Any]:
    raw = _load_json(path, label)
    _assert_no_banned_path_strings(raw, label)
    schemas = {schema} if isinstance(schema, str) else set(schema)
    if raw.get("schema") not in schemas:
        raise ReleaseBuildError(
            f"{label} schema must be one of {sorted(schemas)}, got {raw.get('schema')!r}"
        )
    if raw.get("status") != "frozen":
        raise ReleaseBuildError(
            f"{label} is not frozen; current status={raw.get('status')!r}"
        )
    normalized = _normalize_manifest_refs(raw, path)
    verify_artifact_reference(evidence_ref(path), location=f"{label}.manifest")
    return normalized


def _release_revision(manifest: dict[str, Any], label: str) -> str:
    revision = manifest.get("releaseRevision", manifest.get("revision"))
    if not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", revision):
        raise ReleaseBuildError(f"{label} must declare a portable releaseRevision")
    return revision


def _coordinates(manifest: dict[str, Any], label: str) -> list[dict[str, Any]]:
    value = manifest.get("coordinateSystems", manifest.get("coordinateSystem"))
    rows = value if isinstance(value, list) else [value]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ReleaseBuildError(f"{label} must declare coordinateSystem(s)")
    return copy.deepcopy(rows)


def _domain_value(manifest: dict[str, Any], key: str) -> Any:
    nested = manifest.get(key.rstrip("s"))
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    domain = manifest.get("mechanical") if key in {"parts", "assemblies"} else manifest.get("electronics")
    if isinstance(domain, dict) and key in domain:
        return domain[key]
    return manifest.get(key)


def _subject_ids(rows: Any, key: str, label: str) -> set[str]:
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ReleaseBuildError(f"{label} must be a non-empty subject array")
    identifiers = [row.get(key) for row in rows]
    if any(not isinstance(value, str) or not value for value in identifiers):
        raise ReleaseBuildError(f"{label} contains a missing {key}")
    if len(identifiers) != len(set(identifiers)):
        raise ReleaseBuildError(f"{label} contains duplicate {key} values")
    return set(identifiers)


def _neutral_recipient(parts: list[dict[str, Any]], assemblies: list[dict[str, Any]], coordinate_ids: list[str], revision: str) -> dict[str, Any]:
    processes = sorted(
        {str(part.get("process")) for part in parts if isinstance(part.get("process"), str)}
        | {"mechanical_assembly"}
    )
    formats: set[str] = set()
    for subject in [*parts, *assemblies]:
        artifacts = subject.get("artifacts") if isinstance(subject, dict) else None
        if not isinstance(artifacts, dict):
            continue
        for role, reference in artifacts.items():
            if role not in {
                "nativeCad", "nativeAssembly", "step", "manufacturingDrawing",
                "assemblyDrawing", "explodedDrawing", "sectionDrawing",
            } or not isinstance(reference, dict):
                continue
            suffix = PurePosixPath(str(reference.get("path", ""))).suffix.casefold()
            if suffix:
                formats.add(suffix)
    document = {
        "schema": "aicad_rfq_recipient_profile_v1",
        "recipientId": NEUTRAL_ID,
        "status": "rfq_recipient_unassigned",
        "revision": revision,
        "units": ["mm"],
        "coordinateSystemIds": coordinate_ids,
        "processRequirements": processes,
        "nativeFormats": sorted(formats),
        "authorship": "project_rfq_requirements",
        "supplierAuthorityClaimed": False,
    }
    path = HERE / "evidence" / "unassigned-rfq-recipient.json"
    _atomic_json(path, document)
    return {"supplierId": NEUTRAL_ID, "recipientProfile": evidence_ref(path)}


def _gate_rows(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return {
            str(key): row
            for key, row in value.items()
            if isinstance(row, dict)
        }
    if isinstance(value, list):
        result: dict[str, dict[str, Any]] = {}
        for row in value:
            if not isinstance(row, dict):
                continue
            key = row.get("pcbId", row.get("board"))
            if isinstance(key, str):
                result[key] = row
        return result
    return {}


def _matching_gate(assertions: dict[str, dict[str, Any]], pcb_id: str) -> dict[str, Any] | None:
    lowered = pcb_id.casefold()
    for key, row in assertions.items():
        key_lower = key.casefold()
        if key == pcb_id or ("wand" in lowered and "wand" in key_lower) or (
            "receiver" in lowered and "receiver" in key_lower
        ):
            return row
    return None


def _validate_native_gate_reports(row: dict[str, Any], label: str) -> None:
    erc_ref = row.get("ercReport", row.get("ercNativeReport"))
    drc_ref = row.get("drcReport", row.get("drcNativeReport"))
    if not isinstance(erc_ref, dict) or not isinstance(drc_ref, dict):
        raise ReleaseBuildError(
            f"{label}: gate assertion must bind native ercReport and drcReport"
        )
    erc_path = verify_artifact_reference(erc_ref, location=label + ".ercReport")
    drc_path = verify_artifact_reference(drc_ref, location=label + ".drcReport")
    erc = erc_path.read_text(encoding="utf-8-sig", errors="replace")
    drc = drc_path.read_text(encoding="utf-8-sig", errors="replace")
    erc_summary = re.search(
        r"ERC messages:\s*(\d+)\s+Errors\s+(\d+)\s+Warnings\s+(\d+)", erc, re.I
    )
    drc_summary = re.search(r"Found\s+(\d+)\s+DRC violations", drc, re.I)
    unconnected_summary = re.search(r"Found\s+(\d+)\s+unconnected(?:\s+pads?|\s+items?)?", drc, re.I)
    if erc_summary is None or int(erc_summary.group(2)) != 0:
        raise ReleaseBuildError(f"{label}: native ERC report does not prove zero errors")
    if drc_summary is None or int(drc_summary.group(1)) != 0:
        raise ReleaseBuildError(f"{label}: native DRC report does not prove zero violations")
    if unconnected_summary is None or int(unconnected_summary.group(1)) != 0:
        raise ReleaseBuildError(f"{label}: native DRC report does not prove zero unconnected items")
    if re.search(r"\[unconnected_items\]", drc, re.I):
        raise ReleaseBuildError(f"{label}: native DRC report contains unconnected items")


def _find_interface_reference(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseBuildError(f"{label}: receiverInterface object is required")
    artifact = value.get("artifact")
    if isinstance(artifact, dict) and {"path", "size", "sha256"}.issubset(artifact):
        return artifact
    refs = [reference for _, reference in _walk_evidence_refs(value, label)]
    if len(refs) != 1:
        raise ReleaseBuildError(f"{label}: exactly one interface artifact reference is required")
    return refs[0]


def _validate_receiver_interface_closure(
    mechanical: dict[str, Any],
    electronics: dict[str, Any],
    pcbs: list[dict[str, Any]],
) -> dict[str, Any]:
    mechanical_interface = mechanical.get("receiverInterface")
    electronics_interface = electronics.get("receiverInterface")
    if not isinstance(mechanical_interface, dict) or not isinstance(electronics_interface, dict):
        raise ReleaseBuildError("both frozen manifests require receiverInterface objects")
    if mechanical_interface.get("status") != "frozen":
        raise ReleaseBuildError("mechanical receiverInterface.status must be exactly frozen")
    if electronics_interface.get("status") != "frozen":
        raise ReleaseBuildError("electronics receiverInterface.status must be exactly frozen")
    mechanical_interface = {
        **mechanical_interface, "status": "frozen_electronics_native_drc"}
    try:
        mechanical_semantics = validate_receiver_coordinate_contract(mechanical_interface)
    except ValueError as exc:
        raise ReleaseBuildError(f"mechanical receiver coordinate contract failed: {exc}") from exc
    mechanical_ref = _find_interface_reference(
        mechanical_interface, "mechanical.receiverInterface"
    )
    electronics_ref = _find_interface_reference(
        electronics_interface, "electronics.receiverInterface"
    )
    mechanical_path = verify_artifact_reference(
        mechanical_ref, location="mechanical.receiverInterface.artifact"
    )
    verify_artifact_reference(
        electronics_ref, location="electronics.receiverInterface.artifact"
    )
    consumed = mechanical_interface.get("consumedSha256")
    interface_hashes = {
        mechanical_ref.get("sha256"),
        electronics_ref.get("sha256"),
        consumed,
        mechanical_interface.get("actualSha256"),
    }
    if len(interface_hashes) != 1 or None in interface_hashes:
        raise ReleaseBuildError(
            "receiver interface SHA mismatch: electronics artifact and mechanical consumed/actual SHA must match"
        )
    if mechanical_interface.get("hashMatch") is not True:
        raise ReleaseBuildError("mechanical receiverInterface.hashMatch must be true")
    interface_document = _load_json(mechanical_path, "receiver mechanical interface artifact")
    if (
        interface_document.get("schema") != "aicad_receiver_mechanical_interface_v1"
        or interface_document.get("status") != "frozen"
    ):
        raise ReleaseBuildError("receiver interface artifact schema/status is not the frozen v1 contract")
    _assert_no_banned_path_strings(interface_document, "receiverInterface.artifact")
    try:
        artifact_semantics = receiver_interface_semantics(interface_document)
    except ValueError as exc:
        raise ReleaseBuildError(f"receiver interface artifact contract failed: {exc}") from exc
    for key in ("coordinateContract", "holes", "connectors", "rfKeepout"):
        if artifact_semantics.get(key) != mechanical_semantics.get(key):
            raise ReleaseBuildError(
                f"mechanical receiverInterface.{key} is not an exact mirror of the frozen interface artifact"
            )

    receiver_rows = [row for row in pcbs if "receiver" in str(row.get("pcbId", "")).casefold()]
    if len(receiver_rows) != 1:
        raise ReleaseBuildError("electronics package must identify exactly one receiver PCB")
    receiver_artifacts = receiver_rows[0].get("artifacts")
    board_ref = receiver_artifacts.get("board") if isinstance(receiver_artifacts, dict) else None
    if not isinstance(board_ref, dict):
        raise ReleaseBuildError("receiver PCB native board artifact is missing")
    verify_artifact_reference(board_ref, location="electronics.receiverPcb.artifacts.board")
    mechanical_board = _optional_exact_source_board(
        mechanical_interface.get("sourceBoard"), "mechanical.receiverInterface.sourceBoard"
    )
    electronics_board = _optional_exact_source_board(
        electronics_interface.get("sourceBoard"), "electronics.receiverInterface.sourceBoard"
    )
    artifact_board = _optional_exact_source_board(
        artifact_semantics.get("sourceBoard"), "receiverInterface.artifact.sourceBoard"
    )

    routes_ref = _unique_evidence_ref_by_name(
        electronics, "receiver-frozen-routes.json", "electronics manifest"
    )
    routes_path = verify_artifact_reference(
        routes_ref, location="electronics.receiverFrozenRoutes"
    )
    routes = _load_json(routes_path, "receiver frozen routes")
    _assert_no_banned_path_strings(routes, "receiverFrozenRoutes")
    expected_route_coordinates = {
        "origin": "board_top_left", "x": "right", "y": "down", "units": "mm"
    }
    if routes.get("schema") != "aicad.frozen-pcb-routes.v1" or routes.get("status") != "DRC_FROZEN":
        raise ReleaseBuildError("receiver frozen routes schema/status is not final DRC_FROZEN")
    if routes.get("board") != "receiver" or routes.get("coordinateSystem") != expected_route_coordinates:
        raise ReleaseBuildError("receiver frozen routes must use internal top-left/right/down millimetres")
    dimensions = routes.get("boardDimensionsMm")
    if not isinstance(dimensions, list) or len(dimensions) != 3 or any(
        isinstance(actual, bool) or not isinstance(actual, (int, float))
        or abs(float(actual) - expected) > 1e-6
        for actual, expected in zip(dimensions, (50.0, 42.0, 1.6))
    ):
        raise ReleaseBuildError("receiver frozen routes boardDimensionsMm must be [50,42,1.6]")
    routes_board = _optional_exact_source_board(
        routes.get("sourceBoard"), "receiverFrozenRoutes.sourceBoard"
    )
    board_hashes = {
        board_ref.get("sha256"), mechanical_board.get("sha256"),
        electronics_board.get("sha256"), artifact_board.get("sha256"),
        routes_board.get("sha256"),
    }
    if len(board_hashes) != 1 or None in board_hashes:
        raise ReleaseBuildError(
            "receiver board SHA mismatch across PCB, frozen routes, interface artifact and both frozen manifests"
        )
    return {
        "artifact": copy.deepcopy(electronics_ref),
        "consumedSha256": consumed,
        "sourceBoard": copy.deepcopy(board_ref),
        "frozenRoutes": routes_ref,
        "coordinateContract": copy.deepcopy(mechanical_semantics["coordinateContract"]),
        "holeCount": len(mechanical_semantics["holes"]),
        "connectorCount": len(mechanical_semantics["connectors"]),
        "rfKeepoutVertexCount": len(mechanical_semantics["rfKeepout"]["sourceKicadPolygon"]),
    }

def _same_evidence_identity(left: Any, right: Any, *, include_kind: bool = False) -> bool:
    keys = ("path", "size", "sha256", "kind") if include_kind else ("path", "size", "sha256")
    return isinstance(left, dict) and isinstance(right, dict) and all(
        left.get(key) == right.get(key) for key in keys
    )


def _require_canonical_reference(
    value: Any,
    *,
    path: str,
    location: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or not {"path", "size", "sha256", "kind"}.issubset(value):
        raise ReleaseBuildError(f"{location}: exact path/size/sha256/kind reference is required")
    if value.get("path") != path:
        raise ReleaseBuildError(
            f"{location}: canonical artifact path must be {path!r}, got {value.get('path')!r}"
        )
    verify_artifact_reference(value, location=location)
    return copy.deepcopy(value)


def _validate_wand_authority_evidence(
    interface_path: Path,
    semantics: dict[str, Any],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for row in semantics["refs"]:
        ref = str(row["ref"])
        authority_ref = row["authorityEvidence"]
        authority_path = verify_artifact_reference(
            authority_ref, location=f"wandInterface.refs.{ref}.authorityEvidence"
        )
        authority = _load_json(authority_path, f"wand {ref} authority")
        _assert_no_banned_path_strings(authority, f"wand {ref} authority")
        if authority.get("status") not in {"controlled", "FROZEN"}:
            raise ReleaseBuildError(f"wand {ref} authority status is not controlled/FROZEN")
        if authority.get("releaseBlocked") is True:
            raise ReleaseBuildError(f"wand {ref} authority remains release-blocked")
        if authority.get("manufacturer") != row.get("manufacturer"):
            raise ReleaseBuildError(f"wand {ref} authority manufacturer mismatch")
        if authority.get("mpn") != row.get("mpn"):
            raise ReleaseBuildError(f"wand {ref} authority MPN mismatch")
        hashes[ref] = str(authority_ref["sha256"])

    u1 = next(row for row in semantics["refs"] if row["ref"] == "U1")
    for key in ("fullGroundEvidence", "mechanicalKeepoutSolid", "caseClearanceEvidence"):
        verify_artifact_reference(
            u1[key], location=f"wandInterface.refs.U1.{key}"
        )
    verify_artifact_reference(
        semantics["mechanicalRequirements"]["ninaMechanicalKeepout"]["artifact"],
        location="wandInterface.mechanicalRequirements.ninaMechanicalKeepout.artifact",
    )
    return hashes


def _validate_wand_interface_closure(
    mechanical: dict[str, Any],
    electronics: dict[str, Any],
    pcbs: list[dict[str, Any]],
    assertions: dict[str, dict[str, Any]],
    release_revision: str,
) -> dict[str, Any]:
    mechanical_interface = mechanical.get("wandInterface")
    electronics_interface = electronics.get("wandInterface")
    if not isinstance(mechanical_interface, dict) or not isinstance(electronics_interface, dict):
        raise ReleaseBuildError("both frozen manifests require wandInterface objects")

    mechanical_artifact = _require_canonical_reference(
        mechanical_interface.get("artifact"),
        path=WAND_INTERFACE_REL,
        location="mechanical.wandInterface.artifact",
    )
    electronics_artifact = _require_canonical_reference(
        electronics_interface.get("artifact"),
        path=WAND_INTERFACE_REL,
        location="electronics.wandInterface.artifact",
    )
    if not _same_evidence_identity(mechanical_artifact, electronics_artifact, include_kind=True):
        raise ReleaseBuildError("wand interface artifact differs across mechanical/electronics manifests")
    interface_hashes = {
        mechanical_artifact.get("sha256"),
        electronics_artifact.get("sha256"),
        mechanical_interface.get("consumedSha256"),
        mechanical_interface.get("actualSha256"),
    }
    if len(interface_hashes) != 1 or None in interface_hashes:
        raise ReleaseBuildError(
            "wand interface SHA mismatch across artifact/electronics/mechanical consumed/actual declarations"
        )
    if mechanical_interface.get("hashMatch") is not True:
        raise ReleaseBuildError("mechanical wandInterface.hashMatch must be true")

    interface_path = verify_artifact_reference(
        electronics_artifact, location="wandInterface.artifact"
    )
    interface_document = _load_json(interface_path, "wand interface artifact")
    _assert_no_banned_path_strings(interface_document, "wandInterface.artifact")
    try:
        semantics = wand_interface_semantics(interface_document)
    except ValueError as exc:
        raise ReleaseBuildError(f"wand interface artifact contract failed: {exc}") from exc
    if semantics["revision"] != release_revision:
        raise ReleaseBuildError(
            "wand interface revision does not match the frozen package releaseRevision"
        )

    mirrored_keys = (
        "status", "revision", "authorityReleaseBlockedRefs", "sourceBoard",
        "sourceRoutes", "nativeDrc", "coordinateContract", "boardDimensionsMm",
        "refs", "absentRefs", "consistencyEvidence", "mechanicalRequirements",
    )
    for key in mirrored_keys:
        if mechanical_interface.get(key) != semantics.get(key):
            raise ReleaseBuildError(
                f"mechanical wandInterface.{key} is not an exact mirror of the FROZEN artifact"
            )
    for key in ("sourceBoard", "sourceRoutes", "nativeDrc"):
        if electronics_interface.get(key) != semantics.get(key):
            raise ReleaseBuildError(
                f"electronics wandInterface.{key} is not an exact mirror of the FROZEN artifact"
            )

    for location, reference in _walk_evidence_refs(interface_document, "wandInterface.artifact"):
        verify_artifact_reference(reference, location=location)
    authority_hashes = _validate_wand_authority_evidence(interface_path, semantics)

    wand_rows = [row for row in pcbs if "wand" in str(row.get("pcbId", "")).casefold()]
    if len(wand_rows) != 1:
        raise ReleaseBuildError("electronics package must identify exactly one wand PCB")
    wand_artifacts = wand_rows[0].get("artifacts")
    package_board = wand_artifacts.get("board") if isinstance(wand_artifacts, dict) else None
    board_ref = _require_canonical_reference(
        package_board,
        path="electronics/wand/wand.kicad_pcb",
        location="electronics.wandPcb.artifacts.board",
    )
    interface_board = _require_canonical_reference(
        semantics["sourceBoard"],
        path="electronics/wand/wand.kicad_pcb",
        location="wandInterface.sourceBoard",
    )
    mechanical_board = _require_canonical_reference(
        mechanical_interface.get("sourceBoard"),
        path="electronics/wand/wand.kicad_pcb",
        location="mechanical.wandInterface.sourceBoard",
    )
    electronics_board = _require_canonical_reference(
        electronics_interface.get("sourceBoard"),
        path="electronics/wand/wand.kicad_pcb",
        location="electronics.wandInterface.sourceBoard",
    )
    embedded_route_board = _require_canonical_reference(
        semantics["sourceRoutes"].get("sourceBoard"),
        path="electronics/wand/wand.kicad_pcb",
        location="wandInterface.sourceRoutes.sourceBoard",
    )

    routes_ref = _require_canonical_reference(
        semantics["sourceRoutes"],
        path="electronics/wand/wand-frozen-routes.json",
        location="wandInterface.sourceRoutes",
    )
    if not _same_evidence_identity(mechanical_interface.get("sourceRoutes"), routes_ref, include_kind=True):
        raise ReleaseBuildError("mechanical wandInterface.sourceRoutes differs from the interface artifact")
    if not _same_evidence_identity(electronics_interface.get("sourceRoutes"), routes_ref, include_kind=True):
        raise ReleaseBuildError("electronics wandInterface.sourceRoutes differs from the interface artifact")
    routes_path = verify_artifact_reference(routes_ref, location="wandInterface.sourceRoutes")
    routes = _load_json(routes_path, "wand frozen routes")
    _assert_no_banned_path_strings(routes, "wandFrozenRoutes")
    if (
        routes.get("schema") != "aicad.frozen-pcb-routes.v1"
        or routes.get("status") != "DRC_FROZEN"
        or routes.get("board") != "wand"
        or routes.get("coordinateSystem")
        != {"origin": "board_top_left", "x": "right", "y": "down", "units": "mm"}
    ):
        raise ReleaseBuildError(
            "wand frozen routes must be final DRC_FROZEN in top-left/right/down millimetres"
        )
    dimensions = routes.get("boardDimensionsMm")
    if not isinstance(dimensions, list) or len(dimensions) != 3 or any(
        isinstance(actual, bool)
        or not isinstance(actual, (int, float))
        or abs(float(actual) - expected) > 1e-6
        for actual, expected in zip(dimensions, (15.0, 80.0, 1.6))
    ):
        raise ReleaseBuildError("wand frozen routes boardDimensionsMm must be [15,80,1.6]")
    routes_board = _require_canonical_reference(
        routes.get("sourceBoard"),
        path="electronics/wand/wand.kicad_pcb",
        location="wandFrozenRoutes.sourceBoard",
    )
    board_hashes = {
        board_ref.get("sha256"),
        interface_board.get("sha256"),
        mechanical_board.get("sha256"),
        electronics_board.get("sha256"),
        embedded_route_board.get("sha256"),
        routes_board.get("sha256"),
    }
    if len(board_hashes) != 1 or None in board_hashes:
        raise ReleaseBuildError(
            "wand canonical board SHA mismatch across package/interface/routes/electronics/mechanical declarations"
        )

    native_drc = _require_canonical_reference(
        semantics["nativeDrc"],
        path="electronics/wand/wand-native-drc.rpt",
        location="wandInterface.nativeDrc",
    )
    if not _same_evidence_identity(mechanical_interface.get("nativeDrc"), native_drc, include_kind=True):
        raise ReleaseBuildError("mechanical wandInterface.nativeDrc differs from the interface artifact")
    if not _same_evidence_identity(electronics_interface.get("nativeDrc"), native_drc, include_kind=True):
        raise ReleaseBuildError("electronics wandInterface.nativeDrc differs from the interface artifact")
    wand_gate = _matching_gate(assertions, str(wand_rows[0]["pcbId"]))
    if wand_gate is None:
        raise ReleaseBuildError("wand native DRC cannot be matched to one gate assertion")
    gate_drc = wand_gate.get("drcReport", wand_gate.get("drcNativeReport"))
    if not _same_evidence_identity(native_drc, gate_drc):
        raise ReleaseBuildError("wand interface nativeDrc is not the canonical gate DRC report")

    rows = {row["ref"]: row for row in semantics["refs"]}
    requirements = semantics["mechanicalRequirements"]
    semantic_closure = {
        "switch": {
            "ref": "SW1",
            "sourceCenterMm": rows["SW1"]["sourceCenterMm"],
            "caseCenterMm": rows["SW1"]["caseCenterMm"],
            "travelMm": rows["SW1"]["travelMm"],
            "physicalPadCount": len(rows["SW1"]["fourPhysicalPadGeometry"]),
            "buttonStack": copy.deepcopy(requirements["buttonStack"]),
        },
        "usb": {
            "ref": "J1",
            "sourceCenterMm": rows["J1"]["sourceCenterMm"],
            "caseCenterMm": rows["J1"]["caseCenterMm"],
            "matingDirection": rows["J1"]["matingDirection"],
            "contactCount": len(rows["J1"]["sixteenContactPads"]),
            "shellDipStakeCount": len(rows["J1"]["fourShellDipStakes"]),
            "locatingHoleCount": len(rows["J1"]["locatingHoles"]),
            "panelOpening": copy.deepcopy(requirements["j1PanelOpening"]),
        },
        "mountHoles": [
            {
                "ref": ref,
                "sourceCenterMm": rows[ref]["sourceCenterMm"],
                "caseCenterMm": rows[ref]["caseCenterMm"],
                "finishedDiameterMm": rows[ref]["finishedDiameterMm"],
                "type": rows[ref]["type"],
                "plating": rows[ref]["plating"],
            }
            for ref in ("H1", "H2")
        ],
        "absentRefs": copy.deepcopy(semantics["absentRefs"]),
        "nina": {
            "ref": "U1",
            "antennaFeedCorner": rows["U1"]["antennaFeedCorner"],
            "antennaDirection": rows["U1"]["antennaDirection"],
            "fullGroundEvidence": copy.deepcopy(rows["U1"]["fullGroundEvidence"]),
            "requirements": copy.deepcopy(requirements["ninaMechanicalKeepout"]),
        },
        "boardChannel": copy.deepcopy(requirements["boardChannel"]),
        "pcbRetentionProcess": copy.deepcopy(requirements["pcbRetentionProcess"]),
    }
    return {
        "schema": semantics["schema"],
        "status": semantics["status"],
        "revision": semantics["revision"],
        "authorityReleaseBlockedRefs": semantics["authorityReleaseBlockedRefs"],
        "artifact": electronics_artifact,
        "consumedSha256": mechanical_interface["consumedSha256"],
        "sourceBoard": board_ref,
        "sourceRoutes": routes_ref,
        "nativeDrc": native_drc,
        "boardHashClosureDeclarations": 6,
        "coordinateContract": copy.deepcopy(semantics["coordinateContract"]),
        "authorityEvidenceSha256ByRef": authority_hashes,
        "semanticClosure": semantic_closure,
    }


def _validate_upstream(
    mechanical: dict[str, Any],
    electronics: dict[str, Any],
) -> dict[str, Any]:
    mechanical_revision = _release_revision(mechanical, "mechanical manifest")
    electronics_revision = _release_revision(electronics, "electronics manifest")
    if mechanical_revision != electronics_revision:
        raise ReleaseBuildError(
            "mechanical/electronics releaseRevision mismatch: "
            f"{mechanical_revision!r} != {electronics_revision!r}"
        )
    try:
        adapted_mechanical = adapt_mechanical_manifest(mechanical)
    except ValueError as exc:
        raise ReleaseBuildError(f"mechanical source adaptation failed: {exc}") from exc
    parts = adapted_mechanical["parts"]
    assemblies = adapted_mechanical["assemblies"]
    pcbs = _domain_value(electronics, "pcbs")
    if _subject_ids(parts, "partId", "mechanical.parts") != EXPECTED_PART_IDS:
        raise ReleaseBuildError("mechanical source manifest must close the exact nine part IDs")
    if _subject_ids(assemblies, "assemblyId", "mechanical.assemblies") != EXPECTED_ASSEMBLY_IDS:
        raise ReleaseBuildError("mechanical source manifest must close the exact two assembly IDs")
    pcb_ids = _subject_ids(pcbs, "pcbId", "electronics.pcbs")
    if len(pcb_ids) != 2 or not any("wand" in value.casefold() for value in pcb_ids) or not any(
        "receiver" in value.casefold() for value in pcb_ids
    ):
        raise ReleaseBuildError("electronics source manifest must close wand and receiver PCBs")
    for subject in [*parts, *assemblies]:
        supplier_id = subject.get("supplierId")
        if supplier_id not in {None, NEUTRAL_ID}:
            raise ReleaseBuildError(
                "mechanical source cannot invent supplier authority; use unassigned_rfq_recipient"
            )
        subject["supplierId"] = NEUTRAL_ID
    suppliers = electronics.get("suppliers")
    if not isinstance(suppliers, list) or not suppliers:
        raise ReleaseBuildError("electronics manifest needs authority-backed suppliers")
    for index, supplier in enumerate(suppliers):
        if not isinstance(supplier, dict) or supplier.get("supplierId") == NEUTRAL_ID:
            raise ReleaseBuildError(f"electronics.suppliers[{index}] cannot be neutral")
        if "packageConfirmationEvidence" in supplier or "confirmationAuthorityEvidence" in supplier:
            raise ReleaseBuildError(
                "source package may not fabricate or pre-bind per-package supplier confirmation"
            )
    assertions = _gate_rows(electronics.get("gateAssertions"))
    if len(assertions) < 2:
        raise ReleaseBuildError("electronics manifest requires two board gateAssertions")
    normalized_assertions: dict[str, dict[str, Any]] = {}
    for pcb in pcbs:
        pcb_id = str(pcb["pcbId"])
        row = _matching_gate(assertions, pcb_id)
        if row is None:
            raise ReleaseBuildError(f"missing gate assertion for {pcb_id}")
        for key in ZERO_GATE_KEYS:
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value != 0:
                raise ReleaseBuildError(f"{pcb_id}.{key} must equal integer zero")
        _validate_native_gate_reports(row, f"gateAssertions.{pcb_id}")
        layers = pcb.get("fabricationLayers")
        if not isinstance(layers, list) or set(layers) != EXPECTED_FABRICATION_LAYERS:
            raise ReleaseBuildError(f"{pcb_id}: exact four-layer plus CAM layer closure is missing")
        gerbers = pcb.get("gerbers")
        gerber_layers = {
            row.get("layer") for row in gerbers if isinstance(row, dict)
        } if isinstance(gerbers, list) else set()
        if gerber_layers != EXPECTED_FABRICATION_LAYERS:
            raise ReleaseBuildError(f"{pcb_id}: Gerber layer closure is not exact")
        normalized_assertions[pcb_id] = {
            key: row[key] for key in ZERO_GATE_KEYS
        } | {
            "ercReport": row["ercReport"] if "ercReport" in row else row["ercNativeReport"],
            "drcReport": row["drcReport"] if "drcReport" in row else row["drcNativeReport"],
        }
    interface_closure = _validate_receiver_interface_closure(mechanical, electronics, pcbs)
    wand_interface_closure = _validate_wand_interface_closure(
        mechanical, electronics, pcbs, normalized_assertions, mechanical_revision
    )
    return {
        "revision": mechanical_revision,
        "parts": parts,
        "assemblies": assemblies,
        "pcbs": pcbs,
        "suppliers": suppliers,
        "mechanicalCoordinates": adapted_mechanical["coordinateSystems"],
        "electronicsCoordinates": _coordinates(electronics, "electronics manifest"),
        "gateAssertions": normalized_assertions,
        "receiverInterface": interface_closure,
        "wandInterface": wand_interface_closure,
    }


def _coordinate_closure(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ReleaseBuildError("coordinate system lacks id")
        if identifier in by_id and by_id[identifier] != row:
            raise ReleaseBuildError(f"coordinate system {identifier} conflicts across domains")
        by_id[identifier] = row
    return [by_id[key] for key in sorted(by_id)]


def _upstream_evidence(manifest: dict[str, Any], label: str) -> list[dict[str, Any]]:
    rows = manifest.get("upstreamEvidence", [])
    if rows is None:
        return []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ReleaseBuildError(f"{label}.upstreamEvidence must be an array of references")
    for index, row in enumerate(rows):
        verify_artifact_reference(row, location=f"{label}.upstreamEvidence[{index}]")
    return copy.deepcopy(rows)


def freeze_source_lock(wait_seconds: int = 0) -> dict[str, Any]:
    mechanical_path = _find_manifest(
        MECHANICAL_MANIFEST_REL, MECHANICAL_DELIVERY_SCHEMA, wait_seconds
    )
    mechanical_compat_path = _find_manifest(
        MECHANICAL_COMPAT_MANIFEST_REL, MECHANICAL_SCHEMA, wait_seconds
    )
    electronics_path = _find_manifest(
        ELECTRONICS_MANIFEST_REL, ELECTRONICS_SCHEMA, wait_seconds
    )
    mechanical = _require_frozen_manifest(
        mechanical_path, MECHANICAL_DELIVERY_SCHEMA, "mechanical delivery manifest"
    )
    mechanical_compat = _require_frozen_manifest(
        mechanical_compat_path, MECHANICAL_SCHEMA, "mechanical compatibility source manifest"
    )
    electronics = _require_frozen_manifest(
        electronics_path, ELECTRONICS_SCHEMA, "electronics source manifest"
    )
    if not manifests_equivalent(mechanical, mechanical_compat):
        raise ReleaseBuildError("mechanical delivery/source manifests differ beyond schema")
    closure = _validate_upstream(mechanical, electronics)
    coordinates = _coordinate_closure(
        [*closure["mechanicalCoordinates"], *closure["electronicsCoordinates"]]
    )
    coordinate_ids = [str(row["id"]) for row in closure["mechanicalCoordinates"]]
    neutral = _neutral_recipient(
        closure["parts"], closure["assemblies"], coordinate_ids, closure["revision"]
    )
    package = {
        "schema": PACKAGE_SCHEMA,
        "packageId": PACKAGE_ID,
        "releaseBasis": {
            "revision": closure["revision"],
            "units": "mm",
            "coordinateSystems": coordinates,
            "suppliers": [neutral, *copy.deepcopy(closure["suppliers"])],
        },
        "mechanical": {
            "parts": copy.deepcopy(closure["parts"]),
            "assemblies": copy.deepcopy(closure["assemblies"]),
        },
        "electronics": {"pcbs": copy.deepcopy(closure["pcbs"])},
    }
    package_path = PROJECT_ROOT.joinpath(*PurePosixPath(PACKAGE_REL).parts)
    _atomic_json(package_path, package)
    package_ref = evidence_ref(package_path)
    upstream = {
        "mechanicalDelivery": evidence_ref(mechanical_path),
        "mechanicalSource": evidence_ref(mechanical_compat_path),
        "electronics": evidence_ref(electronics_path),
    }
    extra_evidence = [
        *_upstream_evidence(mechanical, "mechanical"),
        *_upstream_evidence(electronics, "electronics"),
    ]
    lock = {
        "schema": LOCK_SCHEMA,
        "status": "frozen",
        "packageId": PACKAGE_ID,
        "releaseRevision": closure["revision"],
        "package": package_ref,
        "upstreamManifests": upstream,
        "upstreamEvidence": extra_evidence,
        "subjectClosure": {
            "mechanicalPartIds": sorted(EXPECTED_PART_IDS),
            "mechanicalAssemblyIds": sorted(EXPECTED_ASSEMBLY_IDS),
            "pcbIds": sorted(str(row["pcbId"]) for row in closure["pcbs"]),
            "expectedActualPreviews": 32,
        },
        "gateAssertions": closure["gateAssertions"],
        "receiverInterface": closure["receiverInterface"],
        "wandInterface": closure["wandInterface"],
        "safetyLocks": {
            "factoryHandoffReady": False,
            "productionReady": False,
            "productionReleaseAuthorized": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
        },
    }
    lock["sourceClosureSha256"] = _canonical_sha256(
        {
            "package": package_ref,
            "upstreamManifests": upstream,
            "upstreamEvidence": extra_evidence,
            "gateAssertions": closure["gateAssertions"],
            "receiverInterface": closure["receiverInterface"],
            "wandInterface": closure["wandInterface"],
        }
    )
    lock_path = PROJECT_ROOT.joinpath(*PurePosixPath(LOCK_REL).parts)
    _atomic_json(lock_path, lock)
    return lock


def _load_locked_package() -> tuple[dict[str, Any], dict[str, Any]]:
    lock_path = PROJECT_ROOT.joinpath(*PurePosixPath(LOCK_REL).parts)
    if not lock_path.is_file():
        raise ReleaseBuildError(
            "source-lock.json is missing; freeze final upstream manifests before building"
        )
    lock = _load_json(lock_path, "source lock")
    if lock.get("schema") != LOCK_SCHEMA or lock.get("status") != "frozen":
        raise ReleaseBuildError("source-lock.json is absent, stale, or not frozen")
    package_path = verify_artifact_reference(lock.get("package"), location="sourceLock.package")
    upstream = lock.get("upstreamManifests")
    expected_upstream = {"mechanicalDelivery", "mechanicalSource", "electronics"}
    if not isinstance(upstream, dict) or set(upstream) != expected_upstream:
        raise ReleaseBuildError(
            "source lock must bind mechanical delivery/source and electronics manifests")
    manifest_paths = {
        key: verify_artifact_reference(reference, location=f"sourceLock.upstreamManifests.{key}")
        for key, reference in upstream.items()
    }
    for index, reference in enumerate(lock.get("upstreamEvidence", [])):
        verify_artifact_reference(reference, location=f"sourceLock.upstreamEvidence[{index}]")
    mechanical = _require_frozen_manifest(
        manifest_paths["mechanicalDelivery"], MECHANICAL_DELIVERY_SCHEMA,
        "locked mechanical delivery manifest"
    )
    mechanical_compat = _require_frozen_manifest(
        manifest_paths["mechanicalSource"], MECHANICAL_SCHEMA,
        "locked mechanical compatibility source manifest"
    )
    electronics = _require_frozen_manifest(
        manifest_paths["electronics"], ELECTRONICS_SCHEMA, "locked electronics source manifest"
    )
    if not manifests_equivalent(mechanical, mechanical_compat):
        raise ReleaseBuildError("locked mechanical delivery/source manifests diverged")
    closure = _validate_upstream(mechanical, electronics)
    if lock.get("gateAssertions") != closure["gateAssertions"]:
        raise ReleaseBuildError("locked gate assertions differ from upstream frozen manifests")
    if lock.get("receiverInterface") != closure["receiverInterface"]:
        raise ReleaseBuildError("locked receiver-interface closure differs from upstream manifests")
    if lock.get("wandInterface") != closure["wandInterface"]:
        raise ReleaseBuildError("locked wand-interface closure differs from upstream manifests")
    expected_closure = _canonical_sha256(
        {
            "package": lock.get("package"),
            "upstreamManifests": upstream,
            "upstreamEvidence": lock.get("upstreamEvidence", []),
            "gateAssertions": lock.get("gateAssertions"),
            "receiverInterface": lock.get("receiverInterface"),
            "wandInterface": lock.get("wandInterface"),
        }
    )
    if lock.get("sourceClosureSha256") != expected_closure:
        raise ReleaseBuildError("source lock canonical closure SHA-256 is invalid")
    package = _load_json(package_path, "manufacturing package")
    for location, reference in _walk_evidence_refs(package):
        verify_artifact_reference(reference, location=location)
    return lock, package


def _repair_actions(report: dict[str, Any]) -> dict[str, Any]:
    digital = [
        {
            "stage": "digital",
            "code": row["code"],
            "location": row["location"],
            "action": row["repair"],
        }
        for row in report.get("failures", [])
    ]
    handoff = [
        {
            "stage": "supplier_handoff",
            "code": row["code"],
            "location": row["location"],
            "action": row["repair"],
        }
        for row in report.get("handoffFailures", [])
    ]
    return {
        "schema": "aicad_magic_wand_factory_repair_actions_v1",
        "packageId": report.get("packageId"),
        "digitalPackageReady": report.get("digitalPackageReady") is True,
        "factoryHandoffReady": False,
        "actions": [*digital, *handoff],
        "safetyLocks": {
            "productionReady": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
        },
    }


def _file_row(path: Path, final_relative: str) -> dict[str, Any]:
    return {
        "path": final_relative,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _delivery_manifest(
    staging: Path,
    lock: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    files = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file() or path.name == f"{RELEASE_NAME}.delivery-manifest.json":
            continue
        relative = path.relative_to(staging).as_posix()
        files.append(_file_row(path, f"{BUILT_REL}/{relative}"))
    files.extend(
        [
            {"role": "sourceLock", **evidence_ref(PROJECT_ROOT.joinpath(*PurePosixPath(LOCK_REL).parts))},
            {"role": "manufacturingPackage", **lock["package"]},
            {"role": "mechanicalDeliveryManifest", **lock["upstreamManifests"]["mechanicalDelivery"]},
            {"role": "mechanicalSourceManifest", **lock["upstreamManifests"]["mechanicalSource"]},
            {"role": "electronicsSourceManifest", **lock["upstreamManifests"]["electronics"]},
        ]
    )
    return {
        "schema": "aicad_magic_wand_factory_delivery_manifest_v1",
        "packageId": PACKAGE_ID,
        "releaseRevision": report["releaseRevision"],
        "sourceClosureSha256": lock["sourceClosureSha256"],
        "artifactClosureSha256": report["artifactClosureSha256"],
        "domainArtifactClosureSha256": report["domainArtifactClosureSha256"],
        "receiverInterface": lock["receiverInterface"],
        "wandInterface": lock["wandInterface"],
        "readiness": {
            "factoryRfqCandidateReady": report["factoryRfqCandidateReady"],
            "prototypeFabricationCandidateReady": report["prototypeFabricationCandidateReady"],
            "digitalPackageReady": report["digitalPackageReady"],
            "factoryHandoffReady": False,
            "productionReady": False,
            "productionReleaseAuthorized": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
        },
        "subjectClosure": lock["subjectClosure"],
        "files": files,
    }


def _assert_final_report(report: dict[str, Any]) -> None:
    expected_true = (
        "factoryRfqCandidateReady",
        "prototypeFabricationCandidateReady",
        "digitalPackageReady",
    )
    missing = [key for key in expected_true if report.get(key) is not True]
    if missing:
        failures = ", ".join(
            f"{row.get('code')}@{row.get('location')}" for row in report.get("failures", [])[:12]
        )
        raise ReleaseBuildError(
            f"full digital candidate gate failed ({', '.join(missing)}): {failures}"
        )
    if report.get("factoryHandoffReady") is True:
        raise ReleaseBuildError("factory handoff must remain false without real package confirmation")
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    expected_counts = {
        "mechanicalSubjects": 11,
        "pcbs": 2,
        "actualPreviewsExpected": 32,
        "actualPreviewsVerified": 32,
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            raise ReleaseBuildError(
                f"final subject/preview closure mismatch: {key}={counts.get(key)!r}, expected {expected}"
            )
    for key in (
        "productionReady",
        "productionReleaseAuthorized",
        "toolSteelCutAuthorized",
        "massProductionAuthorized",
    ):
        if report.get(key) is not False:
            raise ReleaseBuildError(f"immutable safety lock {key}=false was violated")


def _publish(staging: Path, destination: Path) -> None:
    backup = HERE / ".built.previous"
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        staging.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def build_release(*, check_only: bool = False) -> dict[str, Any]:
    lock, package = _load_locked_package()
    report = validate_manufacturing_release_package(package, PROJECT_ROOT)
    _assert_final_report(report)
    if check_only:
        return {
            "ok": True,
            "status": report["status"],
            "artifactClosureSha256": report["artifactClosureSha256"],
            "counts": report["counts"],
        }
    staging = Path(tempfile.mkdtemp(prefix=".factory-release-build-", dir=HERE))
    destination = PROJECT_ROOT.joinpath(*PurePosixPath(BUILT_REL).parts)
    try:
        result = build_manufacturing_release_package(
            package, PROJECT_ROOT, staging, RELEASE_NAME
        )
        report = result["validation"]
        _assert_final_report(report)
        review_path = Path(result["reviewHtml"])
        review_contract = validate_manufacturing_release_review_html(
            review_path.read_text(encoding="utf-8")
        )
        if not review_contract.get("actualPreviewClosurePass"):
            raise ReleaseBuildError("reviewer actual preview DOM closure failed")
        _atomic_json(
            staging / f"{RELEASE_NAME}.repair-actions.json",
            _repair_actions(report),
        )
        _atomic_json(
            staging / f"{RELEASE_NAME}.delivery-manifest.json",
            _delivery_manifest(staging, lock, report),
        )
        _publish(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    final_review = destination / f"{RELEASE_NAME}.review.html"
    return {
        "ok": True,
        "status": report["status"],
        "factoryRfqCandidateReady": True,
        "prototypeFabricationCandidateReady": True,
        "digitalPackageReady": True,
        "factoryHandoffReady": False,
        "productionReady": False,
        "toolSteelCutAuthorized": False,
        "massProductionAuthorized": False,
        "artifactClosureSha256": report["artifactClosureSha256"],
        "sourceClosureSha256": lock["sourceClosureSha256"],
        "reviewHtml": str(final_review.resolve()),
        "reviewContract": review_contract,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze-source-lock",
        action="store_true",
        help="create the package/source lock from two final frozen upstream manifests",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help="bounded wait for upstream final manifests during freeze",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify the frozen closure and core report without replacing built/",
    )
    args = parser.parse_args(argv)
    try:
        frozen = None
        if args.freeze_source_lock:
            frozen = freeze_source_lock(args.wait_seconds)
        result = build_release(check_only=args.check_only)
        if frozen is not None:
            result["sourceLockFrozen"] = True
            result["sourceClosureSha256"] = frozen["sourceClosureSha256"]
    except ReleaseBuildError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
