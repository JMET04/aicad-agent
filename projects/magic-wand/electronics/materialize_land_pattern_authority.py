#!/usr/bin/env python3
"""Materialize the reviewed 92-reference authority ledger from static source extracts.

This is an explicit release step.  Importing the board generator never creates,
updates, or blesses evidence; it only reads the immutable output of this tool.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import build_factory_package as build

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CATALOG_PATH = ROOT / "evidence" / "authority" / "source-catalog" / "source-catalog-complete.json"
OUTPUT = build.AUTHORITY_FINAL_INVENTORY
SCHEMA = "aicad_land_pattern_authority_inventory_v1"


def _artifact_ref(path: Path, kind: str) -> dict:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
        "kind": kind,
    }


def _candidate_rows(document: dict) -> list[dict]:
    rows: list[dict] = []
    if any(key in document for key in ("manufacturer", "mpn", "coveredMpns")):
        rows.append(document)
    for key in ("families", "rows", "entries", "authorities", "sources"):
        value = document.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _kind(value: object) -> str:
    if value in build.AUTHORITY_SOURCE_KINDS:
        return str(value)
    text = str(value or "").casefold()
    if "kicad" in text:
        return "controlledKiCadLibrary"
    if "design" in text:
        return "designAuthority"
    return "manufacturerDrawingExtract"


def load_catalog() -> list[tuple[dict, Path, dict]]:
    path = CATALOG_PATH
    if not path.is_file():
        raise RuntimeError(f"complete static authority source catalog is missing: {path}")
    payload = path.read_bytes()
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid source catalog JSON {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("status") != "CONTROLLED":
        raise RuntimeError(f"source catalog is not CONTROLLED: {path}")
    if document.get("schema") != "aicad_land_pattern_source_catalog_v1":
        raise RuntimeError(f"unexpected source catalog schema: {path}")
    if document.get("coverageStatus") != "COMPLETE" or document.get("blockers") != []:
        raise RuntimeError(f"source catalog still contains release blockers: {path}")
    summary = document.get("summary")
    expected_summary = {"refCount": 92, "refCoverage": 92, "blockerCount": 0}
    if not isinstance(summary, dict) or any(summary.get(key) != value for key, value in expected_summary.items()):
        raise RuntimeError(f"source catalog coverage summary is not 92/92/0: {path}")
    rows = _candidate_rows(document)
    if not rows or summary.get("familyCount") != len(rows):
        raise RuntimeError(f"source catalog family count does not match its rows: {path}")
    document_kind = _kind(document.get("kind") or document.get("sourceKind"))
    result: list[tuple[dict, Path, dict]] = []
    for row in rows:
        row_kind = _kind(row.get("kind") or row.get("sourceKind") or document_kind)
        result.append((row, path, _artifact_ref(path, row_kind)))
    return result


def _covers(row: dict, part) -> bool:
    mpns = row.get("coveredMpns")
    exact_mpn = (isinstance(mpns, list) and part.mpn in mpns) or row.get("mpn") == part.mpn
    return exact_mpn and row.get("manufacturer") == part.manufacturer


def _extractions(row: dict, artifacts: list[dict], metadata: dict) -> list[dict]:
    value = row.get("extractionEvidence")
    if not isinstance(value, list):
        value = row.get("extractions")
    if not isinstance(value, list) and isinstance(row.get("extractionTemplate"), dict):
        value = [row["extractionTemplate"]]
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    available_hashes = {str(artifact.get("sha256", "")).upper() for artifact in artifacts}
    for source in value:
        if not isinstance(source, dict):
            continue
        fields = source.get("extractedFields")
        if isinstance(fields, dict):
            fields = sorted(fields)
        if not isinstance(fields, list):
            continue
        declared_sha = source.get("sourceArtifactSha256")
        if not isinstance(declared_sha, str) or declared_sha.upper() not in available_hashes:
            raise RuntimeError("extractionEvidence sourceArtifactSha256 does not match a declared sourceArtifact")
        result.append({
            "documentNumber": str(source.get("documentNumber") or metadata["documentNumber"]),
            "page": source.get("page", "controlled-source-snapshot"),
            "section": str(source.get("section") or "land pattern and body datum"),
            "sourceArtifactSha256": declared_sha,
            "extractedFields": [str(field) for field in fields],
        })
    return result


def authority_for(board, part, catalog: list[tuple[dict, Path, dict]]) -> dict:
    matches = [(row, path, artifact) for row, path, artifact in catalog if _covers(row, part)]
    if not matches:
        raise RuntimeError(f"no external source catalog family covers {board.name}/{part.ref}/{part.mpn}")
    primary = matches[0][0]
    metadata = {
        "documentNumber": primary.get("documentNumber"),
        "revision": primary.get("revision"),
        "officialUrl": primary.get("officialUrl") or primary.get("designAuthorityUri"),
        "sourceCoordinateFrame": primary.get("sourceCoordinateFrame"),
    }
    for field_name in ("documentNumber", "revision", "officialUrl"):
        if not isinstance(metadata[field_name], str) or not metadata[field_name]:
            raise RuntimeError(f"catalog family lacks {field_name} for {board.name}/{part.ref}")
    if not isinstance(metadata["sourceCoordinateFrame"], dict):
        first_ref = primary.get("sourceArtifacts", [None])[0]
        if isinstance(first_ref, dict) and isinstance(first_ref.get("path"), str):
            source_path = PROJECT_ROOT / Path(first_ref["path"])
            try:
                source_document = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                source_document = {}
            metadata["sourceCoordinateFrame"] = source_document.get("coordinateFrame") or source_document.get("sourceCoordinateFrame")
    if not isinstance(metadata["sourceCoordinateFrame"], dict) or not metadata["sourceCoordinateFrame"]:
        raise RuntimeError(f"catalog source lacks coordinate frame for {board.name}/{part.ref}")
    sources: list[dict] = []
    extractions: list[dict] = []
    seen_sources: set[tuple[str, str]] = set()
    for row, _path, artifact in matches:
        declared_sources = row.get("sourceArtifacts")
        if not isinstance(declared_sources, list) or not declared_sources:
            raise RuntimeError(f"catalog family lacks explicit sourceArtifacts for {board.name}/{part.ref}")
        row_sources = declared_sources
        for row_source in row_sources:
            if not isinstance(row_source, dict):
                raise RuntimeError(f"invalid sourceArtifact for {board.name}/{part.ref}")
            source_failures, _actual_sha = build._validate_source_artifact_ref(row_source, "")
            if source_failures:
                raise RuntimeError(f"invalid sourceArtifact for {board.name}/{part.ref}: {source_failures}")
            source_key = (str(row_source.get("path")), str(row_source.get("sha256")))
            if source_key not in seen_sources:
                sources.append(dict(row_source))
                seen_sources.add(source_key)
        extractions.extend(_extractions(row, row_sources, metadata))
    covered_fields = {
        field
        for extraction in extractions
        for field in extraction.get("extractedFields", [])
    }
    missing_fields = {"physicalPads", "bodyDatum"} - covered_fields
    if missing_fields:
        raise RuntimeError(
            f"external extraction coverage incomplete for {board.name}/{part.ref}: {sorted(missing_fields)}"
        )
    evidence_kinds = {source["kind"] for source in sources}
    if "controlledKiCadLibrary" in evidence_kinds and evidence_kinds & {"manufacturerDrawing", "manufacturerDrawingExtract"}:
        source_kind = "manufacturerDrawing+controlledKiCadLibrary"
    elif evidence_kinds & {"manufacturerDrawing", "manufacturerDrawingExtract"}:
        source_kind = "manufacturerDrawing"
    elif evidence_kinds == {"designAuthority"}:
        source_kind = "designAuthority"
    else:
        source_kind = "controlledKiCadLibrary"
    pads = build.physical_pad_rows(part.physical_pads)
    body = build.body_datum_payload(part)
    pad_fingerprint = build.physical_pad_fingerprint(part.physical_pads)
    body_fingerprint = build.body_datum_fingerprint(part)
    expected_refs = [
        expected
        for row, _path, _artifact in matches
        for expected in (row.get("expectedRefs") or [])
        if isinstance(expected, dict) and expected.get("board") == board.name and expected.get("ref") == part.ref
    ]
    if len(expected_refs) != 1:
        raise RuntimeError(f"catalog must contain one independent expectedRef fingerprint for {board.name}/{part.ref}")
    expected = expected_refs[0]
    if expected.get("physicalPadFingerprint", "").upper() != pad_fingerprint.upper():
        raise RuntimeError(f"catalog physical-pad fingerprint mismatch for {board.name}/{part.ref}")
    if expected.get("bodyDatumFingerprint", "").upper() != body_fingerprint.upper():
        raise RuntimeError(f"catalog body/datum fingerprint mismatch for {board.name}/{part.ref}")
    return {
        "authorityId": f"magic-wand:{board.name}:{part.ref}:{part.mpn}",
        "status": "CONTROLLED",
        "manufacturer": part.manufacturer,
        "mpn": part.mpn,
        "sourceKind": source_kind,
        "documentNumber": metadata["documentNumber"],
        "revision": metadata["revision"],
        "officialUrl": metadata["officialUrl"],
        "sourceCoordinateFrame": metadata["sourceCoordinateFrame"],
        "sourceLibraryFootprint": part.footprint,
        "emittedFootprint": f"MW_FACTORY:{board.name}_{part.ref}",
        "sourceArtifacts": sources,
        "extractionEvidence": extractions,
        "physicalPads": pads,
        "physicalPadFingerprint": pad_fingerprint,
        "bodyDatum": body,
        "bodyDatumFingerprint": body_fingerprint,
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite existing final authority ledger: {OUTPUT}")
    catalog = load_catalog()
    rows = []
    for board in build.BOARDS:
        for part in board.parts:
            authority = authority_for(board, part, catalog)
            rows.append({
                "board": board.name,
                "ref": part.ref,
                "historical": False,
                "supersedes": "land-pattern-authority-inventory-baseline.json",
                **authority,
            })
    keys = {(row["board"], row["ref"]) for row in rows}
    if len(rows) != 92 or len(keys) != 92:
        raise RuntimeError(f"final authority ledger must close exactly 92 unique refs, got {len(rows)}/{len(keys)}")
    document = {
        "schema": SCHEMA,
        "status": "CONTROLLED",
        "revision": "FACTORY-AUTHORITY-2026-08-21",
        "summary": {"totalRefs": 92, "controlledRefs": 92, "releaseBlockedRefs": 0},
        "policy": {
            "packageNameWhitelistAccepted": False,
            "externalSourceArtifactRequired": True,
            "selfSignedGeometryAccepted": False,
            "supplierConfirmationRequiredForProduction": True,
            "productionAuthorized": False,
        },
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    payload = OUTPUT.read_bytes()
    print(f"{OUTPUT.relative_to(ROOT)} refs=92 controlled=92 blocked=0 size={len(payload)} sha256={hashlib.sha256(payload).hexdigest().upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
