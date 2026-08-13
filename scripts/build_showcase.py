#!/usr/bin/env python3
"""Build deterministic, sanitized GitHub showcase candidates from closed review releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Iterable


TEXT_SUFFIXES = {
    ".aicad", ".csv", ".dru", ".dxf", ".gbr", ".html", ".json", ".kicad_pcb",
    ".kicad_pro", ".kicad_sch", ".log", ".lsp", ".md", ".pro", ".sch", ".scr", ".svg",
    ".txt", ".xml", ".yaml", ".yml",
}
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".git", ".staging", "node_modules"}
FORBIDDEN_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials.json"}
FORBIDDEN_SUFFIXES = {".bak", ".db", ".dll", ".env", ".exe", ".key", ".p12", ".pem", ".pfx", ".pyc", ".pyo", ".sqlite", ".tmp"}
PRIVATE_PATTERNS = (
    re.compile(r"(?i)(?:^|[\s=:\"'])[A-Z]:[\\/]"),
    re.compile(r"(?i)(?:^|[\s=:\"'])(?:\x2f(?:home|Users)\x2f|\\\\[^\\\s]+\\)"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*[\"']?[^\s\"']{8,}"),
    re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
FORBIDDEN_BRAND = re.compile(r"明徒|Mingtu", re.IGNORECASE)
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def source_files(root: Path) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in SKIP_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"symlink is forbidden in public showcase source: {relative.as_posix()}")
        if not path.is_file():
            continue
        if path.name.casefold() in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"forbidden file type in public showcase source: {relative.as_posix()}")
        files.append(path)
    return sorted(files, key=lambda item: (item.relative_to(root).as_posix().casefold(), item.relative_to(root).as_posix()))


def scan_public_text(root: Path, files: Iterable[Path]) -> list[dict[str, str]]:
    root = root.resolve()
    findings: list[dict[str, str]] = []
    for path in files:
        if path.suffix.casefold() not in TEXT_SUFFIXES and path.name not in {"LICENSE", "SHA256SUMS"}:
            continue
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append({"file": relative, "issue": "not_strict_utf8"})
            continue
        if "\ufffd" in text:
            findings.append({"file": relative, "issue": "unicode_replacement_character"})
        if FORBIDDEN_BRAND.search(text):
            findings.append({"file": relative, "issue": "forbidden_brand"})
        for pattern in PRIVATE_PATTERNS:
            if pattern.search(text):
                findings.append({"file": relative, "issue": "private_or_secret_pattern"})
                break
    return findings


def _sanitize_value(value: object) -> object:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in PRIVATE_PATTERNS):
            return "<private-or-secret-value-redacted>"
        return value
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    return value


def _sanitize_human_report(text: str) -> str:
    return "\n".join(
        "[private path or secret value omitted]" if any(pattern.search(line) for pattern in PRIVATE_PATTERNS) else line
        for line in text.splitlines()
    ) + "\n"


def _manifest_entries(manifest: dict[str, object]) -> dict[str, tuple[int, str]]:
    declared: dict[str, tuple[int, str]] = {}
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        rows = manifest.get("artifacts", [])
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("manifest file entry is not an object")
        relative = _safe_relative(item.get("path"))
        size = item.get("size", item.get("bytes"))
        digest = item.get("sha256")
        if relative is None or relative in declared:
            raise RuntimeError(f"manifest contains unsafe or duplicate path: {item.get('path')}")
        if not isinstance(size, int) or size < 0 or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError(f"manifest contains invalid entry: {relative}")
        declared[relative] = (size, digest)
    if not declared:
        raise RuntimeError("manifest files list is empty")
    return declared


def _validate_sums_closure(root: Path, files: list[Path], sums_path: Path) -> dict[str, object]:
    root = root.resolve()
    sums_path = sums_path.resolve()
    declared: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            raise RuntimeError(f"invalid SHA256SUMS line: {line}")
        digest, raw_relative = line.split("  ", 1)
        relative = _safe_relative(raw_relative)
        if relative is None or relative in declared or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError(f"unsafe or duplicate SHA256SUMS entry: {raw_relative}")
        declared[relative] = digest
    actual = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in files
        if path != sums_path
    }
    missing = sorted(set(actual) - set(declared))
    extra = sorted(set(declared) - set(actual))
    mismatched = sorted(path for path in set(actual) & set(declared) if actual[path] != declared[path])
    if missing or extra or mismatched:
        raise RuntimeError(
            f"SHA256SUMS closure failed: unlisted={missing} stale_extra={extra} mismatched={mismatched}"
        )
    return {"entryCount": len(actual), "sha256": sha256(sums_path), "exactBidirectionalClosure": True}


def validate_manifest_closure(root: Path, files: list[Path], manifest_path: Path) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = _manifest_entries(manifest)
    actual = {
        path.relative_to(root).as_posix(): (path.stat().st_size, sha256(path))
        for path in files
        if path != manifest_path
    }
    missing = sorted(set(actual) - set(declared))
    extra = sorted(set(declared) - set(actual))
    mismatched = sorted(path for path in set(actual) & set(declared) if actual[path] != declared[path])
    closure_authority = "manifest"
    sums_evidence = None
    if missing or extra or mismatched:
        sums_path = root / "SHA256SUMS.txt"
        if extra or mismatched or not sums_path.is_file():
            raise RuntimeError(
                f"manifest closure failed: unlisted={missing} stale_extra={extra} mismatched={mismatched}"
            )
        sums_evidence = _validate_sums_closure(root, files, sums_path)
        closure_authority = "SHA256SUMS"
    return {
        "schema": manifest.get("schema"),
        "status": manifest.get("status"),
        "fileCount": len(actual) if closure_authority == "manifest" else sums_evidence["entryCount"],
        "manifestSha256": sha256(manifest_path),
        "exactBidirectionalClosure": True,
        "closureAuthority": closure_authority,
        "manifestDeclaredArtifactCount": len(declared),
        "sha256Sums": sums_evidence,
    }


def _select(files: list[Path], patterns: tuple[str, ...], *, prefer_largest: bool = False) -> Path | None:
    for pattern in patterns:
        matches = [path for path in files if path.match(pattern)]
        if matches:
            key = (lambda item: (-item.stat().st_size, item.name.casefold(), item.name)) if prefer_largest else (
                lambda item: (item.name.casefold(), item.name)
            )
            return sorted(matches, key=key)[0]
    return None


def write_deterministic_zip(root: Path, files: list[Path], target: Path) -> None:
    root = root.resolve()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def _root_role(source: Path, files: list[Path], name: str) -> Path | None:
    candidate = source.resolve() / name
    return candidate if candidate in files else None


def copy_public_artifacts(slug: str, source: Path, output: Path) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    if output == source or source in output.parents:
        raise RuntimeError(f"{slug}: output cannot be inside the showcase source")
    files = source_files(source)
    if not files:
        raise RuntimeError(f"{slug}: source directory contains no files: {source}")
    preview = _root_role(source, files, "preview.png") or _select(
        files,
        ("*1920x1200_MF.png", "*review-dashboard.png", "*browser_qa.png", "*board_top_white.png", "*preview.png", "*preview.svg", "*.png", "*.svg"),
    )
    review = _root_role(source, files, "review.html") or _root_role(source, files, "index.html") or _select(
        files, ("*.review.html", "*review*.html", "index.html"), prefer_largest=True
    )
    validation_json = _root_role(source, files, "validation.json") or _select(files, ("*.validation.json",), prefer_largest=True)
    validation_md = _root_role(source, files, "validation.md") or _select(files, ("*.validation.md", "*review.md"), prefer_largest=True)
    manifest = _root_role(source, files, "manifest.json") or _select(files, ("*.manifest.json",), prefer_largest=True)
    required = {
        "preview": preview,
        "interactive_review": review,
        "validation_machine": validation_json,
        "validation_human": validation_md,
        "source_manifest": manifest,
    }
    missing_roles = [role for role, path in required.items() if path is None]
    if missing_roles:
        raise RuntimeError(f"{slug}: required public roles are missing: {missing_roles}")
    assert manifest is not None
    closure = validate_manifest_closure(source, files, manifest)
    assert validation_json is not None
    validation_payload = json.loads(validation_json.read_text(encoding="utf-8"))
    expected_locks = {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True}
    lock_candidates = (
        validation_payload.get("safetyLocks"),
        validation_payload.get("locks"),
        validation_payload.get("status"),
        validation_payload,
    )
    input_locks = next(
        (candidate for candidate in lock_candidates if isinstance(candidate, dict) and all(key in candidate for key in expected_locks)),
        None,
    )
    observed_locks = {key: input_locks.get(key) for key in expected_locks} if input_locks else None
    if observed_locks != expected_locks:
        raise RuntimeError(f"{slug}: source validation safety locks are absent or incorrect: {observed_locks}")
    findings = scan_public_text(source, files)
    findings_by_path: dict[str, set[str]] = {}
    for finding in findings:
        findings_by_path.setdefault(finding["file"], set()).add(finding["issue"])
    finding_paths = {row["file"] for row in findings}
    unsafe_required = [
        role for role, path in required.items()
        if path is not None
        and path.relative_to(source).as_posix() in finding_paths
        and (
            role not in {"validation_machine", "validation_human"}
            or findings_by_path[path.relative_to(source).as_posix()] != {"private_or_secret_pattern"}
        )
    ]
    if unsafe_required:
        raise RuntimeError(f"{slug}: required public roles failed public-material scan: {unsafe_required}")
    public_files = [path for path in files if path.relative_to(source).as_posix() not in finding_paths]

    target = output / slug
    target.mkdir(parents=True, exist_ok=False)
    copied: list[dict[str, object]] = []
    names = {
        "preview": f"preview{preview.suffix.casefold()}",
        "interactive_review": "review.html",
        "validation_machine": "validation.json",
        "validation_human": "validation.md",
        "source_manifest": "source-manifest.json",
    }
    for role, path in required.items():
        assert path is not None
        destination = target / names[role]
        relative_source = path.relative_to(source).as_posix()
        if relative_source in finding_paths and role == "validation_machine":
            json_dump(destination, _sanitize_value(json.loads(path.read_text(encoding="utf-8"))))
        elif relative_source in finding_paths and role == "validation_human":
            destination.write_text(_sanitize_human_report(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(path, destination)
        post_copy_findings = scan_public_text(target, [destination])
        if post_copy_findings:
            raise RuntimeError(f"{slug}: copied public role still contains unsafe text: {post_copy_findings}")
        copied.append(
            {
                "role": role,
                "path": destination.relative_to(output).as_posix(),
                "sourceName": path.name,
                "size": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        )

    archive = target / f"{slug}-sanitized-review-candidate.zip"
    write_deterministic_zip(source, public_files, archive)
    copied.append(
        {
            "role": "sanitized_review_candidate",
            "path": archive.relative_to(output).as_posix(),
            "sourceName": source.name,
            "size": archive.stat().st_size,
            "sha256": sha256(archive),
            "memberCount": len(public_files),
        }
    )
    return {
        "slug": slug,
        "sourceDirectoryName": source.name,
        "publicScan": {
            "strictUtf8": True,
            "privateOrSecretMatches": sum(row["issue"] == "private_or_secret_pattern" for row in findings),
            "forbiddenBrandMatches": sum(row["issue"] == "forbidden_brand" for row in findings),
            "replacementCharacterMatches": sum(row["issue"] == "unicode_replacement_character" for row in findings),
            "symlinks": 0,
            "forbiddenFileTypes": 0,
            "excludedSourceFiles": sorted(finding_paths, key=lambda value: (value.casefold(), value)),
            "publicArchiveFileCount": len(public_files),
        },
        "sourceManifestClosure": closure,
        "inputSafetyLocks": observed_locks,
        "artifacts": copied,
    }


def parse_demo(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--demo must use SLUG=SOURCE_DIRECTORY")
    slug, raw_path = value.split("=", 1)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise argparse.ArgumentTypeError(f"invalid showcase slug: {slug}")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"showcase source is not a directory: {path}")
    return slug, path


def copy_public_readme(source: Path, output: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise RuntimeError(f"showcase README must be a regular file: {source}")
    target = output / "README.md"
    shutil.copy2(source, target)
    findings = scan_public_text(output, [target])
    if findings:
        raise RuntimeError(f"showcase README failed public-material scan: {findings}")
    return target


def _publish(staging: Path, final: Path) -> None:
    backup = final.with_name(f".{final.name}.previous-{uuid.uuid4().hex}")
    had_final = final.exists()
    if had_final:
        os.replace(final, backup)
    try:
        os.replace(staging, final)
    except BaseException:
        if final.exists():
            shutil.rmtree(final)
        if had_final and backup.exists():
            os.replace(backup, final)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--readme", type=Path, help="UTF-8 public showcase README copied into the closed output")
    parser.add_argument("--demo", action="append", required=True, type=parse_demo, metavar="SLUG=DIR")
    args = parser.parse_args()
    slugs = [slug for slug, _source in args.demo]
    if len(slugs) != len(set(slugs)):
        raise RuntimeError("duplicate showcase slug")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    try:
        if args.readme is not None:
            copy_public_readme(args.readme, staging)
        records = [copy_public_artifacts(slug, source, staging) for slug, source in args.demo]
        manifest = {
            "schema": "aicad_github_showcase_v2",
            "releaseStatus": "engineering-review-candidate",
            "verificationBoundary": "source manifests are exact-closure checked; native engineering acceptance remains external",
            "safetyLocks": {
                "reviewOnly": True,
                "accepted": False,
                "ruleEnabled": False,
                "packagingGated": True,
                "productionOrFabricationAcceptanceClaimed": False,
            },
            "deterministicArchiveTimestamp": "2020-01-01T00:00:00Z",
            "demos": records,
        }
        manifest_path = staging / "showcase-manifest.json"
        json_dump(manifest_path, manifest)
        output_entries = [
            {
                "path": path.relative_to(staging).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in source_files(staging)
            if path != manifest_path
        ]
        manifest["outputClosure"] = {
            "policy": "all_output_files_except_manifest_self",
            "files": output_entries,
        }
        json_dump(manifest_path, manifest)
        _publish(staging, output)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    final_manifest = output / "showcase-manifest.json"
    print(
        json.dumps(
            {"status": "pass", "output": str(output), "demos": len(records), "manifestSha256": sha256(final_manifest)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
