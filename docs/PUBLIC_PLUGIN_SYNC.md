# Public plugin synchronization

The tracked marketplace plugin and every staged GitHub marketplace plugin must
be exact materializations of one independently verified fresh build. A valid
release has one version and one file-tree fingerprint across these surfaces:

- `agent-plugin/aicad-agent` source template;
- `release/<build>/aicad-agent` fresh build;
- `plugins/aicad-agent` tracked public marketplace package;
- `release/<build>/github-repository/plugins/aicad-agent` staged GitHub package;
- `AGENT_API_VERSION`, runtime CLI `VERSION`, manifests, build defaults, and
  the project version.

## Read-only verification

For a normal versioned release:

```powershell
python -B scripts/verify_public_plugin_sync.py
```

For CI or another staging directory:

```powershell
python -B scripts/verify_public_plugin_sync.py `
  --fresh-build release/ci/aicad-agent `
  --staged-github release/ci/github-repository/plugins/aicad-agent
```

The verifier first runs the independent release-package verifier. It then
requires every materialized package to contain the same relative directories
and regular files with the same sizes and SHA-256 hashes. Links, junctions,
reparse points, extra files, stale files, missing files, and any version drift
fail the check.

## Safe synchronization

The synchronization command is read-only unless `--apply` is present:

```powershell
python -B scripts/sync_public_plugin.py
```

Review the JSON plan, build the full staged GitHub repository, and then apply:

```powershell
python -B scripts/sync_public_plugin.py --apply
```

The apply path is constrained to repository-local locations. It never uses or
updates `%USERPROFILE%\plugins`, `%USERPROFILE%\.agents`, or a personal
marketplace. Every existing path component is checked and links, junctions,
or other reparse-point redirections are rejected before preparation begins.
Before changing the tracked public tree it fails if that tree has
pre-existing Git changes which do not already equal the fresh build.

For each changed destination the synchronizer:

1. copies the fresh build to a unique sibling staging directory;
2. proves exact path/size/SHA-256 closure and rechecks that the source did not
   change during the copy;
3. renames the old destination to a sibling backup and the staged tree into
   place;
4. runs the independent five-surface verification;
5. removes backups only after the verification passes.

Any failed swap or post-swap verification restores every prior destination.
Each directory exchange is an atomic same-parent rename; the Git commit that
contains source plus tracked public snapshot is the atomic public visibility
boundary across the repository.

The command does not commit, tag, publish, install, or push.

## Required release order

1. Freeze source changes for the release candidate.
2. Run `scripts/build-agent-plugin.ps1` into `release/v<version>`.
3. Run `scripts/build-github-source.ps1` from that exact built package.
4. Run `scripts/sync_public_plugin.py --apply`.
5. Run the full unit tests and `scripts/verify_public_plugin_sync.py` again.
6. Review the Git diff and commit source plus `plugins/aicad-agent` together.
7. Publishing or pushing is a separate, explicitly authorized operation.

Never merge-copy into an existing public plugin directory. Exact-tree
replacement is required so removed source files cannot survive as stale public
payload.
