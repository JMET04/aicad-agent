#!/usr/bin/env python3
"""Read-only, fail-closed loader for non-self-signed land-pattern sources."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CATALOG_DIR = ROOT / "evidence" / "authority" / "source-catalog"
CATALOG_FILES = (CATALOG_DIR / "source-catalog.json", CATALOG_DIR / "source-catalog-supplement.json")
KICAD10_FOOTPRINT_ROOT = (
    Path.home() / "AppData" / "Local" / "Programs" / "KiCad" / "10.0" / "share" / "kicad" / "footprints"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_KINDS = {"manufacturerDrawing", "manufacturerDrawingExtract", "controlledKiCadLibrary", "designAuthority"}
EXTRACT_SCHEMAS = {
    "aicad_manufacturer_drawing_extract_v1",
    "aicad_controlled_kicad_library_extract_v1",
    "aicad_design_authority_extract_v1",
}


class AuthoritySourceError(RuntimeError):
    """A catalog or source byte failed a fail-closed validation."""


def _fail(message: str) -> None:
    raise AuthoritySourceError(message)


def _bytes_and_sha(path: Path) -> tuple[bytes, str]:
    if path.is_symlink() or not path.is_file():
        _fail(f"source is not a regular file: {path}")
    payload = path.read_bytes()
    return payload, hashlib.sha256(payload).hexdigest()


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be non-empty text")
    return value


def _lower_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{label} must be a lowercase SHA-256")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        _fail(f"{label} must be a non-empty string list")
    if len(value) != len(set(value)):
        _fail(f"{label} contains duplicates")
    return value


def _project_artifact(path_text: object, label: str) -> Path:
    text = _nonempty_text(path_text, label)
    if "\\" in text:
        _fail(f"{label} must use POSIX separators")
    relative = PurePosixPath(text)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "electronics":
        _fail(f"{label} must be canonical beneath electronics/")
    target = PROJECT_ROOT.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        _fail(f"{label} escapes the project root")
    return target


def _verify_reference(reference: object, label: str, *, required_prefix: str | None = None) -> tuple[Path, str]:
    if not isinstance(reference, dict):
        _fail(f"{label} must be an artifact object")
    path_text = _nonempty_text(reference.get("path"), f"{label}.path")
    if required_prefix and not path_text.startswith(required_prefix):
        _fail(f"{label}.path must start with {required_prefix}")
    size = reference.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        _fail(f"{label}.size must be a positive integer")
    expected_sha = _lower_sha(reference.get("sha256"), f"{label}.sha256")
    target = _project_artifact(path_text, f"{label}.path")
    payload, actual_sha = _bytes_and_sha(target)
    if len(payload) != size:
        _fail(f"{label}.size mismatch: expected {size}, got {len(payload)}")
    if actual_sha != expected_sha:
        _fail(f"{label}.sha256 mismatch: expected {expected_sha}, got {actual_sha}")
    return target, actual_sha


def _verify_original_pdf(reference: object, label: str) -> None:
    target, _ = _verify_reference(reference, label, required_prefix="electronics/evidence/datasheets/")
    lowered = target.as_posix().casefold()
    if target.suffix.casefold() != ".pdf" or any(token in lowered for token in ("/_render/", "/probe", ".html", ".zip")):
        _fail(f"{label} is not an admissible original manufacturer PDF")


def _verify_extract(family: dict, artifact: dict, label: str) -> None:
    target, extract_sha = _verify_reference(
        artifact, label, required_prefix="electronics/evidence/authority/source-catalog/"
    )
    kind = artifact.get("kind")
    if kind not in SOURCE_KINDS:
        _fail(f"{label}.kind is not controlled")
    try:
        extract = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthoritySourceError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if extract.get("schema") not in EXTRACT_SCHEMAS or extract.get("status") != "CONTROLLED":
        _fail(f"{label} is not a CONTROLLED extraction snapshot")
    family_mpns = set(_string_list(family.get("coveredMpns"), f"{label}.family.coveredMpns"))
    extract_mpns = set(_string_list(extract.get("coveredMpns"), f"{label}.extract.coveredMpns"))
    if not family_mpns <= extract_mpns:
        _fail(f"{label} extraction does not cover every family MPN")
    if extract.get("documentNumber") != family.get("documentNumber"):
        _fail(f"{label} extraction documentNumber mismatch")
    if extract.get("revision") != family.get("revision") and kind != "controlledKiCadLibrary":
        _fail(f"{label} extraction revision mismatch")
    _nonempty_text(extract.get("humanExtractionDeclaration"), f"{label}.humanExtractionDeclaration")
    geometry = extract.get("geometry")
    if not isinstance(geometry, dict) or not isinstance(geometry.get("physicalPads"), dict) or not isinstance(geometry.get("bodyDatum"), dict):
        _fail(f"{label} extraction lacks geometry.physicalPads/bodyDatum")
    _nonempty_text(geometry.get("heightBasis"), f"{label}.geometry.heightBasis")
    if not isinstance(extract.get("coordinateFrame"), dict) or not extract["coordinateFrame"]:
        _fail(f"{label} extraction lacks coordinateFrame")
    if kind == "manufacturerDrawingExtract":
        originals = extract.get("originalSourceArtifacts")
        if originals is None:
            originals = [extract.get("originalSourceArtifact")]
        if not isinstance(originals, list) or not originals:
            _fail(f"{label} has no original manufacturer source")
        for index, source in enumerate(originals):
            _verify_original_pdf(source, f"{label}.originalSourceArtifacts[{index}]")
    elif kind == "controlledKiCadLibrary":
        library_path = _nonempty_text(extract.get("sourceLibraryPath"), f"{label}.sourceLibraryPath")
        relative = PurePosixPath(library_path)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".kicad_mod":
            _fail(f"{label}.sourceLibraryPath is not canonical")
        source_ref = extract.get("sourceLibraryArtifact")
        if not isinstance(source_ref, dict):
            _fail(f"{label}.sourceLibraryArtifact is missing")
        source_size = source_ref.get("size")
        if not isinstance(source_size, int) or isinstance(source_size, bool) or source_size <= 0:
            _fail(f"{label}.sourceLibraryArtifact.size must be positive")
        source_sha = _lower_sha(source_ref.get("sha256"), f"{label}.sourceLibraryArtifact.sha256")
        source_path = KICAD10_FOOTPRINT_ROOT.joinpath(*relative.parts)
        source_bytes, actual_source_sha = _bytes_and_sha(source_path)
        if len(source_bytes) != source_size or actual_source_sha != source_sha:
            _fail(f"{label} installed KiCad 10 source size/hash mismatch")
    if extract_sha != artifact["sha256"]:
        _fail(f"{label} internal hash verification failed")


def _validate_family(family: object, label: str) -> dict:
    if not isinstance(family, dict):
        _fail(f"{label} must be an object")
    for field in ("familyId", "manufacturer", "documentNumber", "revision"):
        _nonempty_text(family.get(field), f"{label}.{field}")
    _string_list(family.get("coveredMpns"), f"{label}.coveredMpns")
    if "officialUrl" in family:
        parsed = urlparse(_nonempty_text(family.get("officialUrl"), f"{label}.officialUrl"))
        if parsed.scheme != "https" or not parsed.netloc:
            _fail(f"{label}.officialUrl must be an HTTPS URL")
    else:
        _nonempty_text(family.get("designAuthorityUri"), f"{label}.designAuthorityUri")
    artifacts = family.get("sourceArtifacts")
    if not isinstance(artifacts, list) or not artifacts:
        _fail(f"{label}.sourceArtifacts must be non-empty")
    verified_hashes: set[str] = set()
    for index, artifact in enumerate(artifacts):
        _verify_extract(family, artifact, f"{label}.sourceArtifacts[{index}]")
        verified_hashes.add(artifact["sha256"])
    extraction = family.get("extractionTemplate")
    if not isinstance(extraction, dict):
        _fail(f"{label}.extractionTemplate must be an object")
    for field in ("documentNumber", "page", "section", "sourceArtifactSha256", "extractedFields"):
        if field not in extraction:
            _fail(f"{label}.extractionTemplate missing {field}")
    if extraction.get("documentNumber") != family.get("documentNumber"):
        _fail(f"{label}.extractionTemplate documentNumber mismatch")
    _nonempty_text(str(extraction.get("page", "")), f"{label}.extractionTemplate.page")
    _nonempty_text(extraction.get("section"), f"{label}.extractionTemplate.section")
    extraction_sha = _lower_sha(extraction.get("sourceArtifactSha256"), f"{label}.extractionTemplate.sourceArtifactSha256")
    if extraction_sha not in verified_hashes:
        _fail(f"{label}.extractionTemplate is not bound to a verified sourceArtifact")
    fields = set(_string_list(extraction.get("extractedFields"), f"{label}.extractionTemplate.extractedFields"))
    required_fields = {"physicalPads", "bodyDatum", "heightBasis", "sourceCoordinateFrame"}
    if not required_fields <= fields:
        _fail(f"{label}.extractionTemplate misses {sorted(required_fields - fields)}")
    return copy.deepcopy(family)


def load_catalog() -> dict:
    """Load, rehash and merge the base catalog and its controlled supplement."""
    documents: list[dict] = []
    for path in CATALOG_FILES:
        payload, _ = _bytes_and_sha(path)
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthoritySourceError(f"invalid catalog {path}: {exc}") from exc
        if document.get("status") != "CONTROLLED" or document.get("schema") not in {
            "aicad_land_pattern_source_catalog_v1", "aicad_land_pattern_source_catalog_supplement_v1"
        }:
            _fail(f"catalog is not CONTROLLED with an accepted schema: {path}")
        documents.append(document)
    superseded = set(documents[1].get("supersedesBlockerFamilyIds", []))
    families: list[dict] = []
    family_ids: set[str] = set()
    mpn_index: dict[str, str] = {}
    for document_index, document in enumerate(documents):
        rows = document.get("families")
        if not isinstance(rows, list):
            _fail(f"catalog[{document_index}].families must be a list")
        for index, raw in enumerate(rows):
            family = _validate_family(raw, f"catalog[{document_index}].families[{index}]")
            family_id = family["familyId"]
            if family_id in family_ids:
                _fail(f"duplicate controlled familyId: {family_id}")
            family_ids.add(family_id)
            for mpn in family["coveredMpns"]:
                if mpn in mpn_index:
                    _fail(f"MPN {mpn} appears in controlled families {mpn_index[mpn]} and {family_id}")
                mpn_index[mpn] = family_id
            families.append(family)
    blockers: list[dict] = []
    for document_index, document in enumerate(documents):
        rows = document.get("blockers", [])
        if not isinstance(rows, list):
            _fail(f"catalog[{document_index}].blockers must be a list")
        for index, raw in enumerate(rows):
            if not isinstance(raw, dict):
                _fail(f"catalog[{document_index}].blockers[{index}] must be an object")
            family_id = _nonempty_text(raw.get("familyId"), "blocker.familyId")
            if family_id in superseded:
                continue
            _nonempty_text(raw.get("manufacturer"), "blocker.manufacturer")
            _nonempty_text(raw.get("reason"), "blocker.reason")
            for mpn in _string_list(raw.get("coveredMpns"), "blocker.coveredMpns"):
                if mpn in mpn_index:
                    _fail(f"MPN {mpn} is both controlled and blocked")
            blockers.append(copy.deepcopy(raw))
    return {
        "schema": "aicad_land_pattern_source_catalog_merged_v1",
        "status": "CONTROLLED" if not blockers else "BLOCKED_PARTIAL",
        "families": families,
        "blockers": blockers,
    }


def index_by_mpn(catalog: dict | None = None) -> dict[str, dict]:
    catalog = catalog or load_catalog()
    result: dict[str, dict] = {}
    for family in catalog["families"]:
        for mpn in family["coveredMpns"]:
            result[mpn] = {"status": "CONTROLLED", "family": copy.deepcopy(family)}
    for blocker in catalog["blockers"]:
        for mpn in blocker["coveredMpns"]:
            result[mpn] = {"status": "BLOCKED", "blocker": copy.deepcopy(blocker)}
    return result


def resolve_mpn(mpn: str, catalog: dict | None = None) -> dict:
    """Return a detached controlled family record or an explicit blocker."""
    result = index_by_mpn(catalog).get(mpn)
    if result is None:
        return {"status": "BLOCKED", "blocker": {"coveredMpns": [mpn], "reason": "MPN is absent from the source catalog"}}
    return result


def authority_source_fields(mpn: str, catalog: dict | None = None) -> dict:
    """Materialize the immutable source fields consumed by per-ref authority rows."""
    resolved = resolve_mpn(mpn, catalog)
    if resolved["status"] != "CONTROLLED":
        _fail(f"no controlled source family for {mpn}: {resolved['blocker']['reason']}")
    family = resolved["family"]
    kinds = {item["kind"] for item in family["sourceArtifacts"]}
    if kinds == {"designAuthority"}:
        source_kind = "designAuthority"
    elif kinds == {"controlledKiCadLibrary"}:
        source_kind = "controlledKiCadLibrary"
    elif kinds <= {"manufacturerDrawing", "manufacturerDrawingExtract"}:
        source_kind = "manufacturerDrawing"
    else:
        source_kind = "manufacturerDrawing+controlledKiCadLibrary"
    return {
        "sourceFamilyId": family["familyId"],
        "sourceKind": source_kind,
        "documentNumber": family["documentNumber"],
        "revision": family["revision"],
        "sourceArtifacts": copy.deepcopy(family["sourceArtifacts"]),
        "extractionEvidence": [copy.deepcopy(family["extractionTemplate"])],
        "supplierConfirmationRequired": bool(family.get("supplierConfirmationRequired", False)),
    }


def check() -> dict:
    catalog = load_catalog()
    by_mpn = index_by_mpn(catalog)
    sys.path.insert(0, str(ROOT))
    try:
        import build_factory_package as build
    finally:
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)
    refs = [(board.name, part.ref, part.mpn) for board in build.BOARDS for part in board.parts]
    blockers = []
    covered = 0
    supplier_confirmation = 0
    for board, ref, mpn in refs:
        resolved = by_mpn.get(mpn)
        if resolved and resolved["status"] == "CONTROLLED":
            covered += 1
            if resolved["family"].get("supplierConfirmationRequired"):
                supplier_confirmation += 1
        else:
            reason = (resolved or {}).get("blocker", {}).get("reason", "MPN absent from catalog")
            blockers.append({"board": board, "ref": ref, "mpn": mpn, "reason": reason})
    return {
        "schema": catalog["schema"],
        "familyCount": len(catalog["families"]),
        "refCount": len(refs),
        "refCoverage": covered,
        "supplierConfirmationRequiredRefs": supplier_confirmation,
        "blockers": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="rehash every source and report ref coverage")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required; this module is read-only")
    try:
        report = check()
    except AuthoritySourceError as exc:
        print(json.dumps({"status": "BLOCKED", "blockers": [str(exc)]}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if not report["blockers"] and report["refCoverage"] == report["refCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
