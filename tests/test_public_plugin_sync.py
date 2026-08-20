from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sync_public_plugin as sync_module  # noqa: E402
from sync_public_plugin import (  # noqa: E402
    PublicPluginSyncError,
    _dry_run_report,
    transactional_sync,
)
from verify_public_plugin_sync import (  # noqa: E402
    REPARSE_POINT_FLAG,
    PublicPluginVerificationError,
    snapshot_tree,
    validate_role_paths,
    verify_fresh_build,
    verify_public_plugin_sync,
)


VERSION = "1.2.3"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def package_tree(path: Path, *, version: str = VERSION, payload: str = "current") -> None:
    write(
        path / ".codex-plugin" / "plugin.json",
        json.dumps({"name": "aicad-agent", "version": version}) + "\n",
    )
    write(
        path / "integration-manifest.json",
        json.dumps(
            {
                "schema": "aicad_agent_release_manifest_v1",
                "version": version,
                "componentVersions": {
                    "agentPlugin": version,
                    "pythonConstraintCompiler": version,
                },
            }
        )
        + "\n",
    )
    write(path / "scripts" / "aicad_agent.py", f'AGENT_API_VERSION = "{version}"\n')
    write(path / "runtime" / "src" / "aicad" / "cli.py", f'VERSION = "{version}"\n')
    write(path / "payload" / "data.txt", payload + "\n")


class RepositoryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.fresh = root / "release" / f"v{VERSION}" / "aicad-agent"
        self.tracked = root / "plugins" / "aicad-agent"
        self.staged = (
            root
            / "release"
            / f"v{VERSION}"
            / "github-repository"
            / "plugins"
            / "aicad-agent"
        )
        write(root / "pyproject.toml", f'[project]\nname = "aicad"\nversion = "{VERSION}"\n')
        write(
            root / "scripts" / "build-agent-plugin.ps1",
            f"param([string]$Version = '{VERSION}')\n",
        )
        write(
            root / "scripts" / "build-github-source.ps1",
            f"param([string]$Version = '{VERSION}')\n",
        )
        write(
            root / "scripts" / "install-agent-plugin.ps1",
            f"param([string]$ExpectedVersion = '{VERSION}')\n",
        )
        write(root / "src" / "aicad" / "cli.py", f'VERSION = "{VERSION}"\n')
        write(
            root / "agent-plugin" / "aicad-agent" / ".codex-plugin" / "plugin.json",
            json.dumps({"name": "aicad-agent", "version": VERSION}) + "\n",
        )
        write(
            root / "agent-plugin" / "aicad-agent" / "scripts" / "aicad_agent.py",
            f'AGENT_API_VERSION = "{VERSION}"\n',
        )
        package_tree(self.fresh)
        shutil.copytree(self.fresh, self.tracked)
        shutil.copytree(self.fresh, self.staged)


class PublicPluginSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = RepositoryFixture(Path(self.temporary.name))

    def verify(self) -> dict:
        return verify_public_plugin_sync(
            self.fixture.root,
            self.fixture.fresh,
            self.fixture.tracked,
            self.fixture.staged,
            expected_version=VERSION,
            run_release_verifier=False,
        )

    def test_exact_version_and_file_closure_passes(self) -> None:
        report = self.verify()
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(report["exactClosure"])
        self.assertEqual(len(set(report["treeFingerprints"].values())), 1)
        self.assertEqual(set(report["versionSources"].values()), {VERSION})

    def test_version_drift_is_reported_even_when_it_is_inside_runtime_api(self) -> None:
        write(
            self.fixture.tracked / "scripts" / "aicad_agent.py",
            'AGENT_API_VERSION = "9.9.9"\n',
        )
        report = self.verify()
        self.assertFalse(report["ok"])
        self.assertIn(
            f"version-mismatch:trackedPublic.agentApi:9.9.9!={VERSION}",
            report["errors"],
        )

    def test_extra_stale_public_file_breaks_exact_closure(self) -> None:
        write(self.fixture.tracked / "stale.txt", "stale\n")
        report = self.verify()
        self.assertFalse(report["ok"])
        self.assertIn("trackedPublic:extra-file:stale.txt", report["errors"])
        self.assertFalse(report["exactClosure"])

    def test_transactional_sync_removes_stale_files_and_updates_both_destinations(self) -> None:
        write(self.fixture.tracked / "stale.txt", "stale\n")
        write(self.fixture.staged / "payload" / "data.txt", "old staged\n")
        result = transactional_sync(
            self.fixture.fresh, [self.fixture.tracked, self.fixture.staged]
        )
        self.assertTrue(result["ok"])
        self.assertFalse((self.fixture.tracked / "stale.txt").exists())
        expected = snapshot_tree(self.fixture.fresh).fingerprint
        self.assertEqual(snapshot_tree(self.fixture.tracked).fingerprint, expected)
        self.assertEqual(snapshot_tree(self.fixture.staged).fingerprint, expected)

    def test_failed_post_commit_verification_rolls_back_every_destination(self) -> None:
        write(self.fixture.tracked / "payload" / "data.txt", "tracked before\n")
        write(self.fixture.staged / "payload" / "data.txt", "staged before\n")
        tracked_before = snapshot_tree(self.fixture.tracked).fingerprint
        staged_before = snapshot_tree(self.fixture.staged).fingerprint

        with self.assertRaises(PublicPluginSyncError):
            transactional_sync(
                self.fixture.fresh,
                [self.fixture.tracked, self.fixture.staged],
                post_commit_verifier=lambda: {
                    "ok": False,
                    "errors": ["injected-post-commit-failure"],
                },
            )

        self.assertEqual(snapshot_tree(self.fixture.tracked).fingerprint, tracked_before)
        self.assertEqual(snapshot_tree(self.fixture.staged).fingerprint, staged_before)
        residue = [
            path.name
            for parent in {self.fixture.tracked.parent, self.fixture.staged.parent}
            for path in parent.glob(".aicad-agent.*")
        ]
        self.assertEqual(residue, [])

    def test_dry_run_reports_changes_without_mutating_destinations(self) -> None:
        write(self.fixture.tracked / "payload" / "data.txt", "old\n")
        before = snapshot_tree(self.fixture.tracked).fingerprint
        fresh = verify_fresh_build(
            self.fixture.root,
            self.fixture.fresh,
            expected_version=VERSION,
            run_release_verifier=False,
        )
        report = _dry_run_report(
            self.fixture.fresh, self.fixture.tracked, self.fixture.staged, fresh
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["applyRequired"])
        self.assertTrue(report["destinations"]["trackedPublic"]["wouldChange"])
        self.assertEqual(snapshot_tree(self.fixture.tracked).fingerprint, before)

    def test_concurrent_destination_change_aborts_before_any_swap(self) -> None:
        write(self.fixture.tracked / "payload" / "data.txt", "old tracked\n")
        write(self.fixture.staged / "payload" / "data.txt", "old staged\n")
        real_copytree = shutil.copytree
        copy_count = 0

        def copy_and_change_destination(*args, **kwargs):
            nonlocal copy_count
            result = real_copytree(*args, **kwargs)
            copy_count += 1
            if copy_count == 1:
                write(self.fixture.tracked / "concurrent.txt", "do not overwrite\n")
            return result

        with mock.patch.object(
            sync_module.shutil, "copytree", side_effect=copy_and_change_destination
        ):
            with self.assertRaisesRegex(
                PublicPluginSyncError, "destination changed while preparing sync"
            ):
                transactional_sync(
                    self.fixture.fresh, [self.fixture.tracked, self.fixture.staged]
                )

        self.assertTrue((self.fixture.tracked / "concurrent.txt").is_file())
        self.assertEqual(
            (self.fixture.staged / "payload" / "data.txt").read_text(encoding="utf-8"),
            "old staged\n",
        )

    def test_concurrent_source_change_aborts_before_any_swap(self) -> None:
        write(self.fixture.tracked / "payload" / "data.txt", "old tracked\n")
        write(self.fixture.staged / "payload" / "data.txt", "old staged\n")
        tracked_before = snapshot_tree(self.fixture.tracked).fingerprint
        staged_before = snapshot_tree(self.fixture.staged).fingerprint
        real_copytree = shutil.copytree
        copy_count = 0

        def copy_and_change_source(*args, **kwargs):
            nonlocal copy_count
            result = real_copytree(*args, **kwargs)
            if Path(args[0]).resolve() == self.fixture.fresh.resolve():
                copy_count += 1
                if copy_count == 2:
                    write(
                        self.fixture.fresh / "payload" / "data.txt",
                        "source changed during preparation\n",
                    )
            return result

        with mock.patch.object(
            sync_module.shutil, "copytree", side_effect=copy_and_change_source
        ):
            with self.assertRaisesRegex(
                PublicPluginSyncError, "fresh build changed while preparing sync"
            ):
                transactional_sync(
                    self.fixture.fresh, [self.fixture.tracked, self.fixture.staged]
                )

        self.assertEqual(snapshot_tree(self.fixture.tracked).fingerprint, tracked_before)
        self.assertEqual(snapshot_tree(self.fixture.staged).fingerprint, staged_before)

    def test_backup_cleanup_error_never_rolls_back_a_verified_install(self) -> None:
        write(self.fixture.tracked / "payload" / "data.txt", "old tracked\n")
        write(self.fixture.staged / "payload" / "data.txt", "old staged\n")
        real_remove = sync_module._remove_transaction_tree

        def fail_backup_cleanup(path: Path, parent: Path, label: str) -> None:
            if label == "backup tree":
                raise PublicPluginSyncError("injected backup cleanup failure")
            real_remove(path, parent, label)

        with mock.patch.object(
            sync_module, "_remove_transaction_tree", side_effect=fail_backup_cleanup
        ):
            with self.assertRaisesRegex(
                PublicPluginSyncError, "sync is installed and verified"
            ):
                transactional_sync(
                    self.fixture.fresh, [self.fixture.tracked, self.fixture.staged]
                )

        expected = snapshot_tree(self.fixture.fresh).fingerprint
        self.assertEqual(snapshot_tree(self.fixture.tracked).fingerprint, expected)
        self.assertEqual(snapshot_tree(self.fixture.staged).fingerprint, expected)

    def test_tracked_destination_role_cannot_be_redirected(self) -> None:
        outside_role = self.fixture.root / "plugins" / "different-plugin"
        with self.assertRaises(PublicPluginVerificationError):
            validate_role_paths(
                self.fixture.root,
                self.fixture.fresh,
                outside_role,
                self.fixture.staged,
                require_existing=False,
            )

    def test_reparse_destination_ancestor_is_rejected_without_link_privilege(
        self,
    ) -> None:
        github_root = (
            self.fixture.root
            / "release"
            / f"v{VERSION}"
            / "github-repository"
        )
        real_lstat = Path.lstat

        def lstat_with_injected_reparse(path: Path):
            metadata = real_lstat(path)
            if path == github_root:
                injected = mock.Mock()
                injected.st_mode = metadata.st_mode
                injected.st_file_attributes = (
                    getattr(metadata, "st_file_attributes", 0) | REPARSE_POINT_FLAG
                )
                return injected
            return metadata

        with mock.patch.object(Path, "lstat", new=lstat_with_injected_reparse):
            with self.assertRaisesRegex(
                PublicPluginVerificationError,
                "path component may not be a link or reparse point",
            ):
                validate_role_paths(
                    self.fixture.root,
                    self.fixture.fresh,
                    self.fixture.tracked,
                    self.fixture.staged,
                    require_existing=False,
                )

    def test_linked_destination_ancestor_is_rejected_when_supported(self) -> None:
        github_root = (
            self.fixture.root
            / "release"
            / f"v{VERSION}"
            / "github-repository"
        )
        shutil.rmtree(github_root)
        linked_target = self.fixture.root / "linked-github-target"
        (linked_target / "plugins").mkdir(parents=True)
        try:
            github_root.symlink_to(linked_target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem does not permit unprivileged directory symlinks")
        with self.assertRaisesRegex(
            PublicPluginVerificationError, "path component may not be a link"
        ):
            validate_role_paths(
                self.fixture.root,
                self.fixture.fresh,
                self.fixture.tracked,
                self.fixture.staged,
                require_existing=False,
            )

    def test_link_inside_plugin_tree_is_rejected_when_supported(self) -> None:
        target = self.fixture.root / "outside.txt"
        write(target, "outside\n")
        link = self.fixture.tracked / "payload" / "linked.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem does not permit unprivileged symlink creation")
        with self.assertRaises(PublicPluginVerificationError):
            snapshot_tree(self.fixture.tracked)


if __name__ == "__main__":
    unittest.main()
