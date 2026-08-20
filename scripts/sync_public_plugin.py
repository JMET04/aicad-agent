#!/usr/bin/env python3
"""Transactionally synchronize verified AICAD plugin release trees.

The command is dry-run by default.  ``--apply`` is required before it changes
the tracked marketplace package or the staged GitHub marketplace package.  It
never reads or writes a personal plugin directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from verify_public_plugin_sync import (
    PublicPluginVerificationError,
    TreeSnapshot,
    _defaults,
    _is_reparse_or_link,
    _path_key,
    _read_project_version,
    compare_snapshots,
    require_repository_path,
    snapshot_tree,
    validate_role_paths,
    verify_fresh_build,
    verify_public_plugin_sync,
)


class PublicPluginSyncError(RuntimeError):
    """Raised when a sync cannot complete without weakening atomicity."""


@dataclass
class PreparedDestination:
    destination: Path
    staging: Path
    backup: Path
    existed: bool
    before_fingerprint: str | None
    old_moved: bool = False
    new_installed: bool = False


def _safe_sibling(path: Path, parent: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    resolved_parent = parent.resolve(strict=True)
    if _path_key(absolute.parent) != _path_key(resolved_parent):
        raise PublicPluginSyncError(f"{label} must be a direct sibling in {resolved_parent}")
    if not absolute.name.startswith(".aicad-agent."):
        raise PublicPluginSyncError(f"{label} has an unexpected name: {absolute.name}")
    return absolute


def _remove_transaction_tree(path: Path, parent: Path, label: str) -> None:
    candidate = _safe_sibling(path, parent, label)
    if not candidate.exists():
        return
    if _is_reparse_or_link(candidate):
        raise PublicPluginSyncError(f"refusing to remove linked {label}: {candidate}")
    shutil.rmtree(candidate)


def _ensure_non_overlapping(source: Path, destinations: Sequence[Path]) -> None:
    source_key = _path_key(source)
    destination_keys = [_path_key(path) for path in destinations]
    if len(destination_keys) != len(set(destination_keys)):
        raise PublicPluginSyncError("sync destinations must be unique")
    for path, key in zip(destinations, destination_keys):
        if key == source_key:
            raise PublicPluginSyncError("fresh build cannot also be a sync destination")
        try:
            common = os.path.commonpath((source_key, key))
        except ValueError:
            continue
        if common in {source_key, key}:
            raise PublicPluginSyncError(
                f"fresh build and destination may not contain one another: {path}"
            )
    for index, left in enumerate(destination_keys):
        for right in destination_keys[index + 1 :]:
            try:
                common = os.path.commonpath((left, right))
            except ValueError:
                continue
            if common in {left, right}:
                raise PublicPluginSyncError("sync destinations may not overlap")


def _snapshot_if_present(path: Path) -> TreeSnapshot | None:
    if not path.exists():
        return None
    return snapshot_tree(path)


def _trees_equal(expected: TreeSnapshot, actual: TreeSnapshot | None) -> bool:
    return actual is not None and not compare_snapshots(expected, actual, "destination")


def transactional_sync(
    source: Path,
    destinations: Sequence[Path],
    *,
    post_commit_verifier: Callable[[], dict[str, Any]] | None = None,
    replace: Callable[[str | bytes | os.PathLike[str] | os.PathLike[bytes], str | bytes | os.PathLike[str] | os.PathLike[bytes]], None] = os.replace,
) -> dict[str, Any]:
    """Prepare exact sibling trees, swap them, verify, and roll back on failure."""

    source = source.resolve(strict=True)
    source_snapshot = snapshot_tree(source)
    absolute_destinations = [Path(os.path.abspath(os.fspath(path))) for path in destinations]
    _ensure_non_overlapping(source, absolute_destinations)

    changed: list[Path] = []
    unchanged: list[Path] = []
    before_snapshots: dict[Path, TreeSnapshot | None] = {}
    for destination in absolute_destinations:
        parent = destination.parent.resolve(strict=True)
        if destination.exists() and _is_reparse_or_link(destination):
            raise PublicPluginSyncError(f"destination may not be a link: {destination}")
        current = _snapshot_if_present(destination)
        before_snapshots[destination] = current
        if _trees_equal(source_snapshot, current):
            unchanged.append(destination)
        else:
            changed.append(destination)

    if not changed:
        verification = post_commit_verifier() if post_commit_verifier else None
        if verification is not None and verification.get("ok") is not True:
            raise PublicPluginSyncError(
                "post-sync verification failed for an already synchronized tree: "
                + json.dumps(verification.get("errors", []), ensure_ascii=False)
            )
        return {
            "ok": True,
            "changedDestinations": [],
            "unchangedDestinations": [str(path) for path in unchanged],
            "sourceFingerprint": source_snapshot.fingerprint,
            "postCommitVerification": verification,
        }

    nonce = uuid.uuid4().hex
    prepared: list[PreparedDestination] = []
    commit_verified = False
    try:
        for destination in changed:
            parent = destination.parent.resolve(strict=True)
            staging = _safe_sibling(
                parent / f".aicad-agent.{nonce}.{len(prepared)}.staging",
                parent,
                "staging tree",
            )
            backup = _safe_sibling(
                parent / f".aicad-agent.{nonce}.{len(prepared)}.backup",
                parent,
                "backup tree",
            )
            if staging.exists() or backup.exists():
                raise PublicPluginSyncError("transaction staging or backup already exists")
            row = PreparedDestination(
                destination=destination,
                staging=staging,
                backup=backup,
                existed=destination.exists(),
                before_fingerprint=(
                    before_snapshots[destination].fingerprint if before_snapshots[destination] else None
                ),
            )
            prepared.append(row)
            shutil.copytree(source, staging, symlinks=False, copy_function=shutil.copy2)
            staged_snapshot = snapshot_tree(staging)
            differences = compare_snapshots(source_snapshot, staged_snapshot, "staging")
            if differences:
                raise PublicPluginSyncError(
                    "staged tree does not match fresh build: " + "; ".join(differences)
                )

        # Detect a concurrently changing build after every staging copy is complete.
        current_source = snapshot_tree(source)
        if current_source.fingerprint != source_snapshot.fingerprint:
            raise PublicPluginSyncError("fresh build changed while preparing sync")

        for row in prepared:
            current_destination = _snapshot_if_present(row.destination)
            current_fingerprint = (
                current_destination.fingerprint if current_destination else None
            )
            if current_fingerprint != row.before_fingerprint:
                raise PublicPluginSyncError(
                    f"destination changed while preparing sync: {row.destination}"
                )

        for row in prepared:
            if row.existed:
                replace(row.destination, row.backup)
                row.old_moved = True
                moved_fingerprint = snapshot_tree(row.backup).fingerprint
                if moved_fingerprint != row.before_fingerprint:
                    raise PublicPluginSyncError(
                        "destination changed at swap boundary; preserved in backup: "
                        f"{row.destination}"
                    )
            replace(row.staging, row.destination)
            row.new_installed = True

        verification = post_commit_verifier() if post_commit_verifier else None
        if verification is not None and verification.get("ok") is not True:
            raise PublicPluginSyncError(
                "post-sync verification failed: "
                + json.dumps(verification.get("errors", []), ensure_ascii=False)
            )
        commit_verified = True

        for row in prepared:
            if row.backup.exists():
                _remove_transaction_tree(row.backup, row.destination.parent, "backup tree")
        return {
            "ok": True,
            "changedDestinations": [str(path) for path in changed],
            "unchangedDestinations": [str(path) for path in unchanged],
            "sourceFingerprint": source_snapshot.fingerprint,
            "postCommitVerification": verification,
        }
    except Exception as exc:
        if commit_verified:
            raise PublicPluginSyncError(
                "sync is installed and verified, but transaction backup cleanup "
                f"did not finish: {type(exc).__name__}: {exc}"
            ) from exc
        rollback_errors: list[str] = []
        for row in reversed(prepared):
            try:
                if row.new_installed and row.destination.exists():
                    replace(row.destination, row.staging)
                    row.new_installed = False
                if row.old_moved and row.backup.exists():
                    replace(row.backup, row.destination)
                    row.old_moved = False
            except Exception as rollback_exc:  # preserve backups if rollback cannot finish
                rollback_errors.append(
                    f"{row.destination}:{type(rollback_exc).__name__}:{rollback_exc}"
                )
        if not rollback_errors:
            for row in prepared:
                try:
                    if row.staging.exists():
                        _remove_transaction_tree(
                            row.staging, row.destination.parent, "staging tree"
                        )
                    if row.backup.exists():
                        _remove_transaction_tree(
                            row.backup, row.destination.parent, "backup tree"
                        )
                except Exception as cleanup_exc:
                    rollback_errors.append(
                        f"cleanup:{row.destination}:{type(cleanup_exc).__name__}:{cleanup_exc}"
                    )
        detail = f"{type(exc).__name__}: {exc}"
        if rollback_errors:
            detail += "; rollback incomplete: " + "; ".join(rollback_errors)
        raise PublicPluginSyncError(detail) from exc
    finally:
        # Preparation failures happen before a row is installed; clean only exact
        # transaction siblings.  Never delete a backup after an incomplete rollback.
        for row in prepared:
            if not row.old_moved and not row.new_installed and row.staging.exists():
                try:
                    _remove_transaction_tree(
                        row.staging, row.destination.parent, "staging tree"
                    )
                except PublicPluginSyncError:
                    pass


def _git_dirty_paths(repository_root: Path, tracked_public: Path) -> list[str]:
    try:
        relative = tracked_public.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise PublicPluginSyncError("tracked public plugin is outside repository") from exc
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            relative,
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise PublicPluginSyncError(
            "cannot inspect tracked public plugin status: " + completed.stderr.strip()
        )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _resolve_repository_argument(path: Path | None, repository_root: Path, default: Path) -> Path:
    selected = path or default
    if not selected.is_absolute():
        selected = repository_root / selected
    return Path(os.path.abspath(os.fspath(selected)))


def _dry_run_report(
    source: Path, tracked: Path, staged: Path, fresh_report: dict[str, Any]
) -> dict[str, Any]:
    source_snapshot = snapshot_tree(source)
    destination_rows: dict[str, Any] = {}
    for label, destination in (("trackedPublic", tracked), ("stagedGithub", staged)):
        current = _snapshot_if_present(destination)
        differences = (
            compare_snapshots(source_snapshot, current, label)
            if current is not None
            else [f"{label}:missing-tree"]
        )
        destination_rows[label] = {
            "path": str(destination),
            "exists": current is not None,
            "wouldChange": bool(differences),
            "currentFingerprint": current.fingerprint if current else None,
            "differenceCount": len(differences),
            "differences": differences,
        }
    return {
        "ok": fresh_report.get("ok") is True,
        "schema": "aicad_public_plugin_sync_plan_v1",
        "mode": "dry-run",
        "freshBuildVerification": fresh_report,
        "sourceFingerprint": source_snapshot.fingerprint,
        "destinations": destination_rows,
        "applyRequired": any(row["wouldChange"] for row in destination_rows.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or transactionally synchronize a verified fresh AICAD plugin "
            "to tracked public and staged GitHub trees."
        )
    )
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--expected-version")
    parser.add_argument("--fresh-build", type=Path)
    parser.add_argument("--tracked-public", type=Path)
    parser.add_argument("--staged-github", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform repository-local swaps; without this flag the command is read-only",
    )
    args = parser.parse_args()

    repository = args.repository_root.resolve(strict=True)
    version_errors: list[str] = []
    expected = args.expected_version or _read_project_version(
        repository / "pyproject.toml", version_errors
    )
    if not expected:
        result: dict[str, Any] = {
            "ok": False,
            "errors": version_errors or ["expected version is unknown"],
        }
    else:
        default_fresh, default_tracked, default_staged = _defaults(repository, expected)
        fresh = _resolve_repository_argument(args.fresh_build, repository, default_fresh)
        tracked = _resolve_repository_argument(args.tracked_public, repository, default_tracked)
        staged = _resolve_repository_argument(args.staged_github, repository, default_staged)
        try:
            validate_role_paths(
                repository, fresh, tracked, staged, require_existing=False
            )
            fresh = require_repository_path(fresh, repository, "fresh build")
            fresh_report = verify_fresh_build(
                repository,
                fresh,
                expected_version=expected,
                run_release_verifier=True,
            )
            if fresh_report.get("ok") is not True:
                raise PublicPluginSyncError(
                    "fresh build is not independently verified: "
                    + json.dumps(fresh_report.get("errors", []), ensure_ascii=False)
                )
            if not args.apply:
                result = _dry_run_report(fresh, tracked, staged, fresh_report)
            else:
                source_snapshot = snapshot_tree(fresh)
                tracked_snapshot = _snapshot_if_present(tracked)
                dirty = _git_dirty_paths(repository, tracked)
                if dirty and not _trees_equal(source_snapshot, tracked_snapshot):
                    raise PublicPluginSyncError(
                        "tracked public plugin has pre-existing changes and differs from "
                        "the fresh build: " + json.dumps(dirty, ensure_ascii=False)
                    )

                final_verification: dict[str, Any] = {}

                def verify_after_swap() -> dict[str, Any]:
                    nonlocal final_verification
                    final_verification = verify_public_plugin_sync(
                        repository,
                        fresh,
                        tracked,
                        staged,
                        expected_version=expected,
                        run_release_verifier=True,
                    )
                    return final_verification

                transaction = transactional_sync(
                    fresh,
                    [tracked, staged],
                    post_commit_verifier=verify_after_swap,
                )
                result = {
                    "ok": True,
                    "schema": "aicad_public_plugin_sync_result_v1",
                    "mode": "apply",
                    "freshBuildVerification": fresh_report,
                    "transaction": transaction,
                    "finalVerification": final_verification,
                    "personalPluginDirectoriesTouched": False,
                    "publishedOrPushed": False,
                }
        except (PublicPluginVerificationError, PublicPluginSyncError, OSError) as exc:
            result = {
                "ok": False,
                "schema": "aicad_public_plugin_sync_result_v1",
                "mode": "apply" if args.apply else "dry-run",
                "errors": [f"{type(exc).__name__}: {exc}"],
                "personalPluginDirectoriesTouched": False,
                "publishedOrPushed": False,
            }

    payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(payload)
    return 0 if result.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
