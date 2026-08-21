from __future__ import annotations

import ast
import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.17.1"
PREVIOUS_VERSION = "1.17.0"


def _python_assignment(relative: str, name: str) -> str | None:
    module = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for row in module.body:
        if (
            isinstance(row, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in row.targets)
            and isinstance(row.value, ast.Constant)
            and isinstance(row.value.value, str)
        ):
            return row.value.value
    return None


def _powershell_default(relative: str, name: str) -> str | None:
    text = (ROOT / relative).read_text(encoding="utf-8-sig")
    match = re.search(
        rf"\[string\]\s*\${re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]",
        text,
    )
    return match.group(1) if match else None


class ReleaseVersionSourceTests(unittest.TestCase):
    def test_machine_version_sources_are_an_exact_singleton(self) -> None:
        plugin = json.loads(
            (ROOT / "agent-plugin/aicad-agent/.codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        sources = {
            "pluginManifest": plugin["version"],
            "pyproject": project["project"]["version"],
            "runtimeCli": _python_assignment("src/aicad/cli.py", "VERSION"),
            "agentApi": _python_assignment(
                "agent-plugin/aicad-agent/scripts/aicad_agent.py",
                "AGENT_API_VERSION",
            ),
            "releaseVerifier": _python_assignment(
                "scripts/verify_release_package.py", "EXPECTED_VERSION"
            ),
            "githubVerifier": _python_assignment(
                "scripts/verify_github_source.py", "EXPECTED_VERSION"
            ),
            "buildAgent": _powershell_default(
                "scripts/build-agent-plugin.ps1", "Version"
            ),
            "buildGithub": _powershell_default(
                "scripts/build-github-source.ps1", "Version"
            ),
            "buildRelease": _powershell_default(
                "scripts/build-release.ps1", "Version"
            ),
            "installer": _powershell_default(
                "scripts/install-agent-plugin.ps1", "ExpectedVersion"
            ),
        }
        self.assertEqual(set(sources.values()), {EXPECTED_VERSION}, sources)

    def test_ci_and_public_documentation_are_pinned_to_current_release(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("-Version 1.17.1", workflow)
        self.assertIn("aicad-agent-1.17.1.zip", workflow)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        plugin_readme = (ROOT / "agent-plugin/aicad-agent/README.md").read_text(
            encoding="utf-8"
        )
        self.assertTrue(readme.startswith("# aicad-agent 1.17.1\n"))
        self.assertTrue(plugin_readme.startswith("# aicad-agent 1.17.1\n"))
        root_notes = (ROOT / "docs/RELEASE_NOTES_v1.17.1.md").read_bytes()
        plugin_notes = (
            ROOT / "agent-plugin/aicad-agent/docs/RELEASE_NOTES_v1.17.1.md"
        ).read_bytes()
        self.assertEqual(root_notes, plugin_notes)
        self.assertIn(b"# aicad-agent 1.17.1", root_notes)
        self.assertIn(b"Release date: 2026-08-21", root_notes)
        overview = (ROOT / "docs/PRODUCT_OVERVIEW.zh-CN.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("RELEASE_NOTES_v1.17.1.md", overview)

        install_surfaces = (
            "README.md",
            "docs/INSTALL.zh-CN.md",
            "agent-plugin/aicad-agent/docs/INSTALL.zh-CN.md",
        )
        for relative in install_surfaces:
            with self.subTest(install_surface=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                marketplace_versions = set(
                    re.findall(
                        r"codex plugin marketplace add JMET04/aicad-agent --ref v(\d+\.\d+\.\d+)",
                        text,
                    )
                )
                archive_versions = set(
                    re.findall(r"aicad-agent-(\d+\.\d+\.\d+)\.zip", text)
                )
                self.assertEqual({EXPECTED_VERSION}, marketplace_versions)
                self.assertEqual({EXPECTED_VERSION}, archive_versions)

    def test_public_surfaces_state_cross_domain_maturity_boundaries(self) -> None:
        for relative in (
            "README.md",
            "docs/PRODUCT_OVERVIEW.zh-CN.md",
            "agent-plugin/aicad-agent/README.md",
        ):
            with self.subTest(relative=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                for term in ("机械", "电子", "包装", "土木", "建筑", "钢结构", "2D", "3D"):
                    self.assertIn(term, text)
                self.assertIn("生产级自动设计", text)

        manifest = json.loads(
            (ROOT / "agent-plugin/aicad-agent/.codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        capabilities = set(manifest["interface"]["capabilities"])
        self.assertIn(
            "Unified mechanical, electronics, packaging, architecture, civil and steel/structural entry point",
            capabilities,
        )
        self.assertIn(
            "Maturity-gated civil and steel/structural diagnostic review candidates",
            capabilities,
        )

    def test_active_version_sources_contain_no_previous_release_token(self) -> None:
        active = (
            ".github/workflows/ci.yml",
            "agent-plugin/aicad-agent/.codex-plugin/plugin.json",
            "agent-plugin/aicad-agent/README.md",
            "agent-plugin/aicad-agent/docs/INSTALL.zh-CN.md",
            "agent-plugin/aicad-agent/scripts/aicad_agent.py",
            "README.md", "pyproject.toml", "src/aicad/cli.py",
            "scripts/build-release.ps1", "scripts/build-agent-plugin.ps1",
            "scripts/build-github-source.ps1", "scripts/install-agent-plugin.ps1",
            "scripts/verify_release_package.py", "scripts/verify_github_source.py",
            "docs/INSTALL.zh-CN.md", "docs/PRODUCT_OVERVIEW.zh-CN.md",
        )
        for relative in active:
            with self.subTest(relative=relative):
                self.assertNotIn(
                    PREVIOUS_VERSION,
                    (ROOT / relative).read_text(encoding="utf-8-sig"),
                )

    def test_historical_release_records_are_preserved(self) -> None:
        self.assertTrue((ROOT / "docs/RELEASE_NOTES_v1.17.0.md").is_file())
        self.assertTrue(
            (ROOT / "agent-plugin/aicad-agent/docs/RELEASE_NOTES_v1.17.0.md").is_file()
        )
        for relative in ("CHANGELOG.md", "agent-plugin/aicad-agent/CHANGELOG.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("## 1.17.0 - 2026-08-21", text)
            self.assertIn("## 1.16.0 - 2026-08-20", text)


if __name__ == "__main__":
    unittest.main()
