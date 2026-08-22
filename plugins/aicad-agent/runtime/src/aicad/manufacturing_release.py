from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .engine import PlanError
from .manufacturing_preview import probe_png, probe_svg


PACKAGE_SCHEMA = "aicad_manufacturing_release_package_v1"
VALIDATION_SCHEMA = "aicad_manufacturing_release_validation_v1"
FACTORY_MANIFEST_SCHEMA = "aicad_factory_handoff_manifest_v1"
SUPPLIER_SCHEMA = "aicad_supplier_capability_v1"
SUPPLIER_CONFIRMATION_SCHEMA = "aicad_supplier_package_confirmation_v1"
NATIVE_LOG_SCHEMA = "aicad_native_tool_execution_log_v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_PCB_LAYER = re.compile(r"\(\s*\d+\s+\"([^\"]+)\"\s+(?:signal|power|mixed|jumper|user)")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
_REPARSE_POINT = 0x400

_PART_ROLES = {
    "nativeCad": "native_part",
    "step": "step",
    "manufacturingDrawing": "cad_drawing",
    "drawingPreview": "preview",
    "modelPreview": "preview",
    "nativeReopenLog": "machine_log",
}
_ASSEMBLY_ROLES = {
    "nativeAssembly": "native_assembly",
    "step": "step",
    "assemblyDrawing": "cad_drawing",
    "explodedDrawing": "cad_drawing",
    "sectionDrawing": "cad_drawing",
    "assemblyPreview2d": "preview",
    "assemblyPreview3d": "preview",
    "assemblyWorkInstruction": "pdf",
    "inspectionPlan": "pdf",
    "moldingInput": "json",
    "bom": "json",
    "positions": "json",
    "interferenceLog": "machine_log",
    "nativeReopenLog": "machine_log",
}
_PCB_ROLES = {
    "project": "kicad_project",
    "schematic": "kicad_schematic",
    "board": "kicad_board",
    "ercLog": "machine_log",
    "drcLog": "machine_log",
    "schematicPdf": "pdf",
    "assemblyDrawing": "pdf_or_cad_drawing",
    "fabricationDrawing": "pdf_or_cad_drawing",
    "schematicPreview": "preview",
    "boardPreview": "preview",
    "assemblyPreview": "preview",
    "fabricationPreview": "preview",
    "modelPreview3d": "preview",
    "assemblyNotes": "pdf",
    "fabricationNotes": "pdf",
    "model3d": "step",
    "bom": "csv",
    "cpl": "csv",
    "connectivityNetlist": "ipc356",
    "camLog": "machine_log",
    "jobFile": "gbrjob",
    "pthDrill": "drill",
    "npthDrill": "drill",
    "nativeReopenLog": "machine_log",
}

_FORMAT_SUFFIXES = {
    "native_part": {".sldprt", ".prt", ".ipt", ".fcstd", ".catpart"},
    "native_assembly": {".sldasm", ".asm", ".iam", ".fcstd", ".catproduct"},
    "step": {".step", ".stp"},
    "cad_drawing": {".slddrw", ".dwg", ".dxf"},
    "pdf_or_cad_drawing": {".pdf", ".slddrw", ".dwg", ".dxf"},
    "json": {".json"},
    "machine_log": {".json"},
    "kicad_project": {".kicad_pro"},
    "kicad_schematic": {".kicad_sch"},
    "kicad_board": {".kicad_pcb"},
    "pdf": {".pdf"},
    "csv": {".csv"},
    "gerber": {".gbr", ".ger", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gm1"},
    "drill": {".drl", ".xln"},
    "gbrjob": {".gbrjob"},
    "ipc356": {".d356", ".ipc", ".ipc356", ".net"},
    "preview": {".svg", ".png"},
    "authority_document": {".pdf", ".html", ".htm", ".json"},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
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


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & _REPARSE_POINT)
    except (AttributeError, OSError):
        return path.is_symlink()


@dataclass
class _Context:
    root: Path | None
    failures: list[dict[str, str]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    evidence_paths: dict[str, str] = field(default_factory=dict)
    handoff_failures: list[dict[str, str]] = field(default_factory=list)
    review_subjects: list[dict[str, Any]] = field(default_factory=list)
    used_supplier_ids: set[str] = field(default_factory=set)

    def fail(self, code: str, location: str, message: str, repair: str) -> None:
        self.failures.append(
            {
                "code": code,
                "location": location,
                "message": message,
                "repair": repair,
            }
        )

    def check(self, check_id: str, passed: bool, evidence: Any) -> None:
        self.checks.append(
            {"id": check_id, "status": "pass" if passed else "fail", "evidence": evidence}
        )

    def block_handoff(self, code: str, location: str, message: str, repair: str) -> None:
        self.handoff_failures.append(
            {"code": code, "location": location, "message": message, "repair": repair}
        )


def _exact_keys(
    ctx: _Context,
    value: Any,
    required: set[str],
    location: str,
    *,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        ctx.fail(
            "object_required",
            location,
            "Expected a JSON object.",
            "Replace the value with the documented object and all mandatory fields.",
        )
        return {}
    optional = optional or set()
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required - optional)
    if missing:
        ctx.fail(
            "required_field_missing",
            location,
            "Missing fields: " + ", ".join(missing),
            "Add every named field; manufacturing inventories are exact and non-compensatory.",
        )
    if extra:
        ctx.fail(
            "unexpected_field",
            location,
            "Unexpected fields: " + ", ".join(extra),
            "Move unsupported data into a controlled evidence file or remove the unknown fields.",
        )
    return value


def _identifier(ctx: _Context, value: Any, location: str, *, revision: bool = False) -> str:
    pattern = _REVISION if revision else _IDENTIFIER
    if not isinstance(value, str) or not pattern.fullmatch(value):
        ctx.fail(
            "identifier_invalid",
            location,
            "Identifier/revision is missing or non-portable.",
            "Use the documented ASCII identifier form and freeze the exact revision.",
        )
        return ""
    return value


def _list(ctx: _Context, value: Any, location: str, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        ctx.fail(
            "nonempty_list_required",
            location,
            "A non-empty exact inventory is required.",
            "Enumerate every subject/artifact explicitly; placeholders and implicit inventory are forbidden.",
        )
        return []
    return value


def _path_is_controlled(ctx: _Context, path_text: Any, location: str) -> Path | None:
    if ctx.root is None:
        return None
    if not isinstance(path_text, str) or not path_text or "\\" in path_text:
        ctx.fail(
            "unsafe_or_nonportable_path",
            location,
            "Evidence path must be a non-empty POSIX-style relative path.",
            "Use a forward-slash path below the controlled evidence root.",
        )
        return None
    pure = PurePosixPath(path_text)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts or ":" in pure.parts[0]:
        ctx.fail(
            "unsafe_or_nonportable_path",
            location,
            "Absolute, traversal, drive and dot paths are forbidden.",
            "Copy the evidence below the controlled root and declare its relative path.",
        )
        return None
    candidate = ctx.root.joinpath(*pure.parts)
    current = ctx.root
    for component in pure.parts:
        current = current / component
        if current.exists() and _is_reparse(current):
            ctx.fail(
                "link_or_junction_forbidden",
                location,
                "Evidence path crosses a symlink or reparse point.",
                "Store a real file directly below the controlled evidence root.",
            )
            return None
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(ctx.root)
    except (OSError, ValueError):
        ctx.fail(
            "path_escapes_evidence_root",
            location,
            "Resolved evidence path escapes the controlled root.",
            "Use a real file directly below the controlled evidence root.",
        )
        return None
    return candidate


def _format_ok(path: Path, kind: str) -> tuple[bool, str]:
    suffix = path.suffix.casefold()
    if suffix not in _FORMAT_SUFFIXES[kind]:
        return False, f"extension {suffix or '<none>'} is not valid for {kind}"
    try:
        data = path.read_bytes()
    except OSError as exc:
        return False, f"cannot read artifact: {exc}"
    if not data:
        return False, "artifact is empty"
    upper = data[:131072].upper()
    lower_text = data[:262144].decode("utf-8", errors="ignore").casefold()
    if kind in {"native_part", "native_assembly"}:
        if suffix in {".sldprt", ".sldasm"}:
            correct_role = (
                (kind == "native_part" and suffix == ".sldprt")
                or (kind == "native_assembly" and suffix == ".sldasm")
            )
            probe = data[:65536]
            ok = (
                correct_role
                and len(data) >= 4096
                and data[4:8] == b"\x00\x00\x00\x04"
                and b"\x00" in probe
                and len(set(probe)) >= 48
            )
            return ok, "SolidWorks native file fails role, size, version-word or non-trivial binary probes"
        probe = data[:65536]
        return (len(data) >= 1024 and b"\x00" in probe and len(set(probe)) >= 32, "Native CAD artifact is too small, text-like or zero-entropy")
    if kind == "step":
        ok = b"ISO-10303-21" in upper and b"END-ISO-10303-21" in upper
        return ok, "STEP exchange header/footer is missing"
    if kind in {"cad_drawing", "pdf_or_cad_drawing"}:
        if suffix == ".pdf":
            return data.startswith(b"%PDF-"), "PDF signature is missing"
        if suffix == ".dxf":
            ok = "section" in lower_text and "eof" in lower_text
            return ok, "DXF SECTION/EOF structure is missing"
        if suffix == ".dwg":
            return data.startswith(b"AC10"), "DWG signature is missing"
        return (len(data) >= 128, "native drawing artifact is implausibly small")
    if kind == "pdf":
        return data.startswith(b"%PDF-"), "PDF signature is missing"
    if kind == "kicad_project":
        try:
            return isinstance(json.loads(data.decode("utf-8-sig")), dict), "KiCad project is not a JSON object"
        except (UnicodeError, json.JSONDecodeError):
            return False, "KiCad project is not valid UTF-8 JSON"
    if kind == "kicad_schematic":
        return "(kicad_sch" in lower_text, "KiCad schematic root is missing"
    if kind == "kicad_board":
        return "(kicad_pcb" in lower_text and "(layers" in lower_text, "KiCad board/layer structure is missing"
    if kind == "csv":
        try:
            rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        except (UnicodeError, csv.Error):
            return False, "CSV is not parseable UTF-8"
        ok = len(rows) >= 2 and len(rows[0]) >= 2 and any(cell.strip() for cell in rows[1])
        return ok, "CSV must contain a header and at least one populated data row"
    if kind == "gerber":
        ok = b"%FS" in upper and b"M02*" in upper
        return ok, "Gerber format statement or end marker is missing"
    if kind == "drill":
        ok = b"M48" in upper and b"M30" in upper
        return ok, "Excellon header or end marker is missing"
    if kind == "ipc356":
        ok = b"IPC-D-356" in upper or (b"317" in upper and b"999" in upper)
        return ok, "IPC-D-356 connectivity netlist markers are missing"
    if kind == "gbrjob":
        try:
            document = json.loads(data.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            return False, "Gerber job file is not valid UTF-8 JSON"
        return isinstance(document, dict) and bool(document), "Gerber job file is empty or not an object"
    if kind == "preview":
        if suffix == ".png":
            ok, reason, _ = probe_png(data)
            return ok, reason
        ok, reason, _ = probe_svg(data)
        return ok, reason
    if kind == "authority_document":
        if suffix == ".pdf":
            ok = data.startswith(b"%PDF-") and len(data) >= 256
        elif suffix in {".html", ".htm"}:
            ok = "<html" in lower_text and "</html>" in lower_text and len(data) >= 256
        else:
            try:
                document = json.loads(data.decode("utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError):
                document = None
            ok = isinstance(document, dict) and bool(document)
        blocked = re.search(
            r"(?i)\b(?:todo|tbd|placeholder|dummy|example supplier|unknown supplier)\b",
            lower_text,
        )
        return ok and blocked is None, "Supplier authority document is invalid, too small, or placeholder content"
    if kind in {"json", "machine_log"}:
        try:
            return isinstance(json.loads(data.decode("utf-8-sig")), dict), "JSON evidence is not an object"
        except (UnicodeError, json.JSONDecodeError):
            return False, "JSON evidence is not valid UTF-8"
    return True, ""


def _evidence(
    ctx: _Context,
    value: Any,
    location: str,
    kind: str,
) -> dict[str, Any]:
    ref = _exact_keys(ctx, value, {"path", "size", "sha256"}, location)
    path_text = ref.get("path")
    declared_size = ref.get("size")
    declared_sha = ref.get("sha256")
    row: dict[str, Any] = {
        "location": location,
        "kind": kind,
        "path": path_text if isinstance(path_text, str) else "",
        "declaredSize": declared_size,
        "declaredSha256": declared_sha,
        "exists": False,
        "sizePass": False,
        "sha256Pass": False,
        "formatPass": False,
        "pass": False,
    }
    if not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size < 1:
        ctx.fail(
            "evidence_size_invalid",
            location + ".size",
            "Declared evidence size must be a positive integer.",
            "Record the byte size of the final controlled artifact.",
        )
    if not isinstance(declared_sha, str) or not _SHA256.fullmatch(declared_sha):
        ctx.fail(
            "evidence_sha256_invalid",
            location + ".sha256",
            "Declared SHA-256 must be 64 lowercase hexadecimal characters.",
            "Hash the final controlled artifact bytes and update the declaration.",
        )
    candidate = _path_is_controlled(ctx, path_text, location + ".path")
    if isinstance(path_text, str) and path_text in ctx.evidence_paths:
        ctx.fail(
            "duplicate_evidence_path",
            location + ".path",
            f"The same file is already used by {ctx.evidence_paths[path_text]}.",
            "Provide a distinct artifact for each mandatory manufacturing role.",
        )
    elif isinstance(path_text, str):
        ctx.evidence_paths[path_text] = location
    if candidate is None or not candidate.is_file():
        ctx.fail(
            "evidence_file_missing",
            location,
            "Controlled evidence file is unavailable.",
            "Generate/export the real artifact with its native tool, place it below the evidence root, then bind size and SHA-256.",
        )
        ctx.artifacts.append(row)
        return row
    row["exists"] = True
    actual_size = candidate.stat().st_size
    actual_sha = _sha256(candidate)
    row.update(
        {
            "resolvedPath": str(candidate.resolve()),
            "actualSize": actual_size,
            "actualSha256": actual_sha,
            "sizePass": actual_size == declared_size,
            "sha256Pass": actual_sha == declared_sha,
        }
    )
    if not row["sizePass"]:
        ctx.fail(
            "evidence_size_mismatch",
            location,
            f"Declared size {declared_size!r} does not match {actual_size} bytes.",
            "Freeze the final artifact and regenerate its exact evidence reference.",
        )
    if not row["sha256Pass"]:
        ctx.fail(
            "evidence_sha256_mismatch",
            location,
            "Declared SHA-256 does not match the current file.",
            "Reject stale/tampered evidence; rerun the native export and update the hash only after review.",
        )
    format_pass, format_reason = _format_ok(candidate, kind)
    row["formatPass"] = format_pass
    if not format_pass:
        ctx.fail(
            "artifact_format_invalid",
            location,
            format_reason,
            "Regenerate the real artifact in the required native/exchange/manufacturing format; renamed placeholders are rejected.",
        )
    row["pass"] = bool(row["sizePass"] and row["sha256Pass"] and format_pass)
    ctx.artifacts.append(row)
    return row


def _preview_evidence(
    ctx: _Context,
    value: Any,
    location: str,
) -> dict[str, Any]:
    ref = _exact_keys(
        ctx,
        value,
        {"path", "size", "sha256", "previewOfRole", "subjectId", "sourceSha256"},
        location,
    )
    row = _evidence(
        ctx,
        {key: ref.get(key) for key in ("path", "size", "sha256")},
        location,
        "preview",
    )
    row.update(
        {
            "previewOfRole": ref.get("previewOfRole"),
            "subjectId": ref.get("subjectId"),
            "sourceSha256": ref.get("sourceSha256"),
            "bindingDeclarationPass": True,
        }
    )
    if (
        not isinstance(ref.get("previewOfRole"), str)
        or not _IDENTIFIER.fullmatch(str(ref.get("previewOfRole")))
        or not isinstance(ref.get("subjectId"), str)
        or not _IDENTIFIER.fullmatch(str(ref.get("subjectId")))
        or not isinstance(ref.get("sourceSha256"), str)
        or not _SHA256.fullmatch(str(ref.get("sourceSha256")))
    ):
        row["bindingDeclarationPass"] = False
        row["pass"] = False
        ctx.fail(
            "preview_binding_declaration_invalid", location,
            "Preview must declare a portable source role/subject and exact lowercase source SHA-256.",
            "Bind the rendered preview to the exact hash-verified drawing/STEP/board source.",
        )
    resolved = row.get("resolvedPath")
    suffix = Path(resolved).suffix.casefold() if isinstance(resolved, str) else ""
    embedded_source_sha: str | None = None
    if row.get("formatPass") and isinstance(resolved, str):
        try:
            source = Path(resolved).read_bytes()
        except OSError:
            source = b""
        if suffix == ".svg":
            _, _, embedded_source_sha = probe_svg(source)
        elif suffix == ".png":
            _, _, metadata = probe_png(source)
            values = metadata.get("aicad-source-sha256", [])
            if len(values) == 1:
                embedded_source_sha = values[0]
    if suffix == ".svg" and row.get("formatPass") and embedded_source_sha != ref.get("sourceSha256"):
        row["bindingDeclarationPass"] = False
        row["pass"] = False
        ctx.fail(
            "svg_preview_source_metadata_missing", location,
            "SVG root does not carry the exact declared hash-bound source SHA-256 attribute.",
            "Put data-aicad-source-sha256 on the actual SVG root; comments and child nodes are not accepted.",
        )
    if suffix == ".png" and row.get("formatPass") and embedded_source_sha != ref.get("sourceSha256"):
        row["bindingDeclarationPass"] = False
        row["pass"] = False
        ctx.fail(
            "png_preview_source_metadata_missing", location,
            "PNG lacks one exact structured aicad-source-sha256 tEXt/iTXt value.",
            "Regenerate the PNG with one valid CRC-protected text chunk bound to the exact source hash.",
        )
    return row


def _json_from_row(ctx: _Context, row: dict[str, Any], location: str) -> dict[str, Any]:
    if not row.get("pass") or not isinstance(row.get("resolvedPath"), str):
        return {}
    try:
        value = json.loads(Path(row["resolvedPath"]).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        ctx.fail(
            "evidence_json_unreadable",
            location,
            "Evidence JSON could not be parsed after hash verification.",
            "Export valid UTF-8 JSON from the authoritative tool and rebind its bytes.",
        )
        return {}
    if not isinstance(value, dict):
        ctx.fail(
            "evidence_json_object_required",
            location,
            "Evidence JSON root must be an object.",
            "Regenerate the evidence using the documented machine-readable contract.",
        )
        return {}
    return value
