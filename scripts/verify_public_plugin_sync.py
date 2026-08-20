#!/usr/bin/env python3
"""Verify that every public AICAD plugin surface is one exact release tree.

This verifier is deliberately independent from the copy/sync operation.  It
checks the repository source version, the agent-plugin template, a freshly
built and independently verified package, the tracked marketplace package,
and the staged GitHub marketplace package.  A passing result requires exact
path, size, and SHA-256 closure between all three materialized packages.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REPARSE_POINT_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class PublicPluginVerificationError(RuntimeError):
    """Raised when a tree cannot be inspected safely and deterministically."""


@dataclass(frozen=True)
class FileRecord:
    size: int
    sha256: str


@dataclass(frozen=True)
class TreeSnapshot:
    directories: tuple[str, ...]
    files: Mapping[str, FileRecord]
    fingerprint: str

    def summary(self) -> dict[str, Any]:
        return {
            "directoryCount": len(self.directories),
            "fileCount": len(self.files),
            "fingerprint": self.fingerprint,
        }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_relative_to(path: Path, root: Path) -> bool:
    path_key = _path_key(path)
    root_key = _path_key(root)
    try:
        return os.path.commonpath((path_key, root_key)) == root_key
    except ValueError:
        return False


def _is_reparse_or_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PublicPluginVerificationError(f"cannot inspect path metadata: {path}") from exc
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT_FLAG
    )


def _reject_repository_link_components(
    path: Path, repository_root: Path, label: str
) -> Path:
    """Reject links in every existing component below the repository root."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    root = repository_root.resolve(strict=True)
    if not _is_relative_to(absolute, root):
        raise PublicPluginVerificationError(
            f"{label} must stay inside repository root: {absolute}"
        )
    relative = Path(os.path.relpath(absolute, root))
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise PublicPluginVerificationError(
                f"cannot inspect {label} path component: {current}"
            ) from exc
        if current.is_symlink() or bool(
            getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT_FLAG
        ):
            raise PublicPluginVerificationError(
                f"{label} path component may not be a link or reparse point: {current}"
            )
    return absolute


def require_repository_path(path: Path, repository_root: Path, label: str) -> Path:
    """Resolve an existing path and require it to stay in the repository."""

    try:
        resolved = path.resolve(strict=True)
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise PublicPluginVerificationError(f"{label} is missing: {path}") from exc
    _reject_repository_link_components(path, root, label)
    if not _is_relative_to(resolved, root):
        raise PublicPluginVerificationError(
            f"{label} must stay inside repository root: {resolved}"
        )
    return resolved


def require_repository_destination(
    path: Path, repository_root: Path, label: str
) -> Path:
    """Validate a possibly absent destination and its existing parent chain."""

    root = repository_root.resolve(strict=True)
    absolute = _reject_repository_link_components(path, root, label)
    try:
        resolved_parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise PublicPluginVerificationError(
            f"{label} parent is missing: {absolute.parent}"
        ) from exc
    if not _is_relative_to(resolved_parent, root):
        raise PublicPluginVerificationError(
            f"{label} parent resolves outside repository root: {resolved_parent}"
        )
    return absolute


def validate_role_paths(
    repository_root: Path,
    fresh_build: Path,
    tracked_public: Path,
    staged_github: Path,
    *,
    require_existing: bool = True,
) -> tuple[Path, Path, Path, Path]:
    """Constrain all package roles to their one permitted repository location."""

    repository = repository_root.resolve(strict=True)
    expected_tracked = repository / "plugins" / "aicad-agent"
    if _path_key(tracked_public) != _path_key(expected_tracked):
        raise PublicPluginVerificationError(
            f"tracked public destination must be {expected_tracked}"
        )

    release_root = repository / "release"
    fresh_absolute = Path(os.path.abspath(os.fspath(fresh_build)))
    staged_absolute = Path(os.path.abspath(os.fspath(staged_github)))
    if not _is_relative_to(fresh_absolute, release_root):
        raise PublicPluginVerificationError("fresh build must stay inside repository release/")
    if not _is_relative_to(staged_absolute, release_root):
        raise PublicPluginVerificationError("staged GitHub plugin must stay inside repository release/")
    staged_parts = tuple(part.casefold() for part in staged_absolute.parts)
    if len(staged_parts) < 3 or staged_parts[-3:] != (
        "github-repository",
        "plugins",
        "aicad-agent",
    ):
        raise PublicPluginVerificationError(
            "staged GitHub plugin must end in github-repository/plugins/aicad-agent"
        )

    if require_existing:
        fresh_absolute = require_repository_path(
            fresh_absolute, repository, "fresh build"
        )
        tracked_public = require_repository_path(
            expected_tracked, repository, "tracked public plugin"
        )
        staged_absolute = require_repository_path(
            staged_absolute, repository, "staged GitHub plugin"
        )
    else:
        fresh_absolute = require_repository_destination(
            fresh_absolute, repository, "fresh build"
        )
        tracked_public = require_repository_destination(
            expected_tracked, repository, "tracked public plugin"
        )
        staged_absolute = require_repository_destination(
            staged_absolute, repository, "staged GitHub plugin"
        )
    return repository, fresh_absolute, tracked_public, staged_absolute


def _hash_regular_file(path: Path) -> FileRecord:
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PublicPluginVerificationError(f"cannot stat file: {path}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise PublicPluginVerificationError(f"non-regular file in plugin tree: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PublicPluginVerificationError(f"cannot hash file: {path}") from exc
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PublicPluginVerificationError(f"file changed while hashing: {path}")
    return FileRecord(size=before.st_size, sha256=digest.hexdigest())


def snapshot_tree(root: Path) -> TreeSnapshot:
    """Return an exact regular-file tree snapshot without following links."""

    unresolved_root = Path(os.path.abspath(os.fspath(root)))
    if _is_reparse_or_link(unresolved_root):
        raise PublicPluginVerificationError(
            f"plugin tree root is a link or reparse point: {unresolved_root}"
        )
    root = unresolved_root.resolve(strict=True)
    if not root.is_dir():
        raise PublicPluginVerificationError(f"plugin tree is not a directory: {root}")

    directories: list[str] = []
    files: dict[str, FileRecord] = {}

    def visit(directory: Path, prefix: tuple[str, ...]) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda row: row.name.casefold())
        except OSError as exc:
            raise PublicPluginVerificationError(
                f"cannot enumerate plugin directory: {directory}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative_parts = prefix + (entry.name,)
            relative = Path(*relative_parts).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise PublicPluginVerificationError(
                    f"cannot inspect plugin entry: {path}"
                ) from exc
            if entry.is_symlink() or bool(
                getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT_FLAG
            ):
                raise PublicPluginVerificationError(
                    f"link or reparse point in plugin tree: {relative}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(relative)
                visit(path, relative_parts)
            elif stat.S_ISREG(metadata.st_mode):
                files[relative] = _hash_regular_file(path)
            else:
                raise PublicPluginVerificationError(
                    f"unsupported filesystem entry in plugin tree: {relative}"
                )

    visit(root, ())
    canonical = {
        "directories": sorted(directories),
        "files": [
            {"path": path, "size": record.size, "sha256": record.sha256}
            for path, record in sorted(files.items())
        ],
    }
    fingerprint = hashlib.sha256(_canonical_json(canonical)).hexdigest()
    return TreeSnapshot(
        directories=tuple(sorted(directories)), files=files, fingerprint=fingerprint
    )


def compare_snapshots(
    expected: TreeSnapshot, actual: TreeSnapshot, actual_label: str
) -> list[str]:
    errors: list[str] = []
    expected_files = set(expected.files)
    actual_files = set(actual.files)
    for path in sorted(expected_files - actual_files):
        errors.append(f"{actual_label}:missing-file:{path}")
    for path in sorted(actual_files - expected_files):
        errors.append(f"{actual_label}:extra-file:{path}")
    for path in sorted(expected_files & actual_files):
        wanted = expected.files[path]
        observed = actual.files[path]
        if wanted.size != observed.size:
            errors.append(
                f"{actual_label}:size-mismatch:{path}:{observed.size}!={wanted.size}"
            )
        elif wanted.sha256 != observed.sha256:
            errors.append(f"{actual_label}:sha256-mismatch:{path}")

    expected_dirs = set(expected.directories)
    actual_dirs = set(actual.directories)
    for path in sorted(expected_dirs - actual_dirs):
        errors.append(f"{actual_label}:missing-directory:{path}")
    for path in sorted(actual_dirs - expected_dirs):
        errors.append(f"{actual_label}:extra-directory:{path}")
    return errors


def _read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label}:unreadable:{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}:not-object")
        return {}
    return value


def _read_python_assignment(
    path: Path, name: str, label: str, errors: list[str]
) -> str | None:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        errors.append(f"{label}:unreadable:{type(exc).__name__}")
        return None
    for row in module.body:
        if isinstance(row, ast.Assign):
            targets = [item.id for item in row.targets if isinstance(item, ast.Name)]
            if name in targets and isinstance(row.value, ast.Constant) and isinstance(row.value.value, str):
                return row.value.value
        if (
            isinstance(row, ast.AnnAssign)
            and isinstance(row.target, ast.Name)
            and row.target.id == name
            and isinstance(row.value, ast.Constant)
            and isinstance(row.value.value, str)
        ):
            return row.value.value
    errors.append(f"{label}:assignment-not-found:{name}")
    return None


def _read_project_version(path: Path, errors: list[str]) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"project.pyproject:unreadable:{type(exc).__name__}")
        return None
    project_match = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
    if project_match:
        version_match = re.search(
            r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']\s*$',
            project_match.group(1),
        )
        if version_match:
            return version_match.group(1)
    errors.append("project.pyproject:version-not-found")
    return None


def _read_powershell_default(
    path: Path, parameter: str, label: str, errors: list[str]
) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{label}:unreadable:{type(exc).__name__}")
        return None
    match = re.search(
        rf"\[string\]\s*\${re.escape(parameter)}\s*=\s*['\"]([^'\"]+)['\"]",
        text,
    )
    if not match:
        errors.append(f"{label}:default-not-found:{parameter}")
        return None
    return match.group(1)


def _package_version_sources(
    package_root: Path, label: str, errors: list[str]
) -> dict[str, str | None]:
    plugin = _read_json(
        package_root / ".codex-plugin" / "plugin.json", f"{label}.plugin", errors
    )
    manifest = _read_json(
        package_root / "integration-manifest.json", f"{label}.manifest", errors
    )
    components = manifest.get("componentVersions")
    if not isinstance(components, dict):
        errors.append(f"{label}.manifest:componentVersions-not-object")
        components = {}
    return {
        f"{label}.pluginManifest": plugin.get("version") if isinstance(plugin.get("version"), str) else None,
        f"{label}.integrationManifest": manifest.get("version") if isinstance(manifest.get("version"), str) else None,
        f"{label}.component.agentPlugin": components.get("agentPlugin") if isinstance(components.get("agentPlugin"), str) else None,
        f"{label}.component.pythonConstraintCompiler": components.get("pythonConstraintCompiler") if isinstance(components.get("pythonConstraintCompiler"), str) else None,
        f"{label}.agentApi": _read_python_assignment(
            package_root / "scripts" / "aicad_agent.py",
            "AGENT_API_VERSION",
            f"{label}.agentApi",
            errors,
        ),
        f"{label}.runtimeCli": _read_python_assignment(
            package_root / "runtime" / "src" / "aicad" / "cli.py",
            "VERSION",
            f"{label}.runtimeCli",
            errors,
        ),
    }


def collect_version_sources(
    repository_root: Path,
    fresh_build: Path,
    tracked_public: Path | None,
    staged_github: Path | None,
    errors: list[str],
) -> dict[str, str | None]:
    template = repository_root / "agent-plugin" / "aicad-agent"
    template_plugin = _read_json(
        template / ".codex-plugin" / "plugin.json", "agentPlugin.plugin", errors
    )
    sources: dict[str, str | None] = {
        "project.pyproject": _read_project_version(
            repository_root / "pyproject.toml", errors
        ),
        "project.runtimeCli": _read_python_assignment(
            repository_root / "src" / "aicad" / "cli.py",
            "VERSION",
            "project.runtimeCli",
            errors,
        ),
        "project.buildAgentDefault": _read_powershell_default(
            repository_root / "scripts" / "build-agent-plugin.ps1",
            "Version",
            "project.buildAgentDefault",
            errors,
        ),
        "project.buildGithubDefault": _read_powershell_default(
            repository_root / "scripts" / "build-github-source.ps1",
            "Version",
            "project.buildGithubDefault",
            errors,
        ),
        "project.installExpected": _read_powershell_default(
            repository_root / "scripts" / "install-agent-plugin.ps1",
            "ExpectedVersion",
            "project.installExpected",
            errors,
        ),
        "agentPlugin.pluginManifest": template_plugin.get("version")
        if isinstance(template_plugin.get("version"), str)
        else None,
        "agentPlugin.agentApi": _read_python_assignment(
            template / "scripts" / "aicad_agent.py",
            "AGENT_API_VERSION",
            "agentPlugin.agentApi",
            errors,
        ),
    }
    sources.update(_package_version_sources(fresh_build, "freshBuild", errors))
    if tracked_public is not None:
        sources.update(_package_version_sources(tracked_public, "trackedPublic", errors))
    if staged_github is not None:
        sources.update(_package_version_sources(staged_github, "stagedGithub", errors))
    return sources


def _load_release_verifier(repository_root: Path):
    path = repository_root / "scripts" / "verify_release_package.py"
    spec = importlib.util.spec_from_file_location("aicad_release_verifier", path)
    if spec is None or spec.loader is None:
        raise PublicPluginVerificationError(f"cannot load release verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verify = getattr(module, "verify", None)
    if not callable(verify):
        raise PublicPluginVerificationError("release verifier has no callable verify()")
    return verify


def _verify_release_package(
    repository_root: Path, package_root: Path, expected_version: str
) -> dict[str, Any]:
    verify = _load_release_verifier(repository_root)
    result = verify(package_root, repository_root, expected_version)
    if not isinstance(result, dict):
        raise PublicPluginVerificationError("release verifier returned a non-object result")
    return result


def _version_errors(
    sources: Mapping[str, str | None], expected_version: str
) -> list[str]:
    errors: list[str] = []
    for label, value in sorted(sources.items()):
        if value is None:
            errors.append(f"version-source-missing:{label}")
        elif value != expected_version:
            errors.append(
                f"version-mismatch:{label}:{value}!={expected_version}"
            )
    return errors


def verify_fresh_build(
    repository_root: Path,
    fresh_build: Path,
    *,
    expected_version: str | None = None,
    run_release_verifier: bool = True,
) -> dict[str, Any]:
    """Validate source/template/fresh-build versions and source-input closure."""

    errors: list[str] = []
    repository = repository_root.resolve(strict=True)
    try:
        fresh = require_repository_path(fresh_build, repository, "fresh build")
        if not _is_relative_to(fresh, repository / "release"):
            raise PublicPluginVerificationError(
                "fresh build must stay inside repository release/"
            )
        snapshot = snapshot_tree(fresh)
    except PublicPluginVerificationError as exc:
        return {"ok": False, "errors": [str(exc)]}

    project_version = _read_project_version(repository / "pyproject.toml", errors)
    expected = expected_version or project_version or ""
    sources = collect_version_sources(repository, fresh, None, None, errors)
    errors.extend(_version_errors(sources, expected))
    release_report: dict[str, Any] | None = None
    if run_release_verifier:
        try:
            release_report = _verify_release_package(repository, fresh, expected)
        except Exception as exc:  # independent verifier failure must stay fail-closed
            errors.append(f"fresh-release-verifier-exception:{type(exc).__name__}:{exc}")
        else:
            if release_report.get("ok") is not True:
                errors.extend(
                    f"fresh-release:{item}" for item in release_report.get("errors", [])
                )
    return {
        "ok": not errors,
        "expectedVersion": expected,
        "versionSources": sources,
        "freshBuild": snapshot.summary(),
        "releaseVerification": release_report,
        "errors": errors,
    }


def verify_public_plugin_sync(
    repository_root: Path,
    fresh_build: Path,
    tracked_public: Path,
    staged_github: Path,
    *,
    expected_version: str | None = None,
    run_release_verifier: bool = True,
) -> dict[str, Any]:
    """Verify exact version and file closure across all public plugin surfaces."""

    errors: list[str] = []
    try:
        repository, fresh, tracked, staged = validate_role_paths(
            repository_root,
            fresh_build,
            tracked_public,
            staged_github,
            require_existing=True,
        )
        snapshots = {
            "freshBuild": snapshot_tree(fresh),
            "trackedPublic": snapshot_tree(tracked),
            "stagedGithub": snapshot_tree(staged),
        }
    except PublicPluginVerificationError as exc:
        return {"ok": False, "errors": [str(exc)]}

    expected = expected_version or _read_project_version(
        repository / "pyproject.toml", errors
    ) or ""
    sources = collect_version_sources(
        repository, fresh, tracked, staged, errors
    )
    errors.extend(_version_errors(sources, expected))
    errors.extend(
        compare_snapshots(snapshots["freshBuild"], snapshots["trackedPublic"], "trackedPublic")
    )
    errors.extend(
        compare_snapshots(snapshots["freshBuild"], snapshots["stagedGithub"], "stagedGithub")
    )

    release_reports: dict[str, Any] = {}
    if run_release_verifier:
        for label, package in (
            ("freshBuild", fresh),
            ("trackedPublic", tracked),
            ("stagedGithub", staged),
        ):
            try:
                report = _verify_release_package(repository, package, expected)
            except Exception as exc:  # fail closed and preserve a machine-readable result
                errors.append(
                    f"{label}-release-verifier-exception:{type(exc).__name__}:{exc}"
                )
                continue
            release_reports[label] = report
            if report.get("ok") is not True:
                errors.extend(
                    f"{label}-release:{item}" for item in report.get("errors", [])
                )

    fingerprints = {label: row.fingerprint for label, row in snapshots.items()}
    return {
        "ok": not errors,
        "schema": "aicad_public_plugin_sync_verification_v1",
        "expectedVersion": expected,
        "versionSources": sources,
        "treeFingerprints": fingerprints,
        "trees": {label: row.summary() for label, row in snapshots.items()},
        "releaseVerification": release_reports,
        "exactClosure": len(set(fingerprints.values())) == 1,
        "errors": errors,
    }


def _defaults(repository_root: Path, expected_version: str) -> tuple[Path, Path, Path]:
    return (
        repository_root / "release" / f"v{expected_version}" / "aicad-agent",
        repository_root / "plugins" / "aicad-agent",
        repository_root
        / "release"
        / f"v{expected_version}"
        / "github-repository"
        / "plugins"
        / "aicad-agent",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify source, fresh build, tracked marketplace plugin, staged GitHub "
            "plugin, runtime API version, and exact file closure without modifying them."
        )
    )
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--expected-version")
    parser.add_argument("--fresh-build", type=Path)
    parser.add_argument("--tracked-public", type=Path)
    parser.add_argument("--staged-github", type=Path)
    args = parser.parse_args()

    repository = args.repository_root.resolve(strict=True)
    bootstrap_errors: list[str] = []
    expected = args.expected_version or _read_project_version(
        repository / "pyproject.toml", bootstrap_errors
    )
    if not expected:
        result = {"ok": False, "errors": bootstrap_errors or ["expected version is unknown"]}
    else:
        default_fresh, default_tracked, default_staged = _defaults(repository, expected)
        result = verify_public_plugin_sync(
            repository,
            args.fresh_build or default_fresh,
            args.tracked_public or default_tracked,
            args.staged_github or default_staged,
            expected_version=expected,
        )
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(payload)
    return 0 if result.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
