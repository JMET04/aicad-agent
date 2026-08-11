from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


EXPECTED_VERSION = "1.7.0"
REQUIRED_README_SECTIONS = (
    "# aicad-agent 1.7.0",
    "## 安装步骤",
    "## 第一次使用：完全不需要写代码",
    "## 常用任务提示词",
    "## 主要功能详解",
    "## MCP 工具",
    "## 本地 CLI 使用",
    "## 依赖与降级行为",
    "## 开发与验证",
    "## 文档索引",
    "点击直线",
    "点击点",
    "点击圆",
    "坐标系开关",
    "默认不需要 API Key",
)
FORBIDDEN_TOP_LEVEL = ("build", "jobs", "out", "release", ".git")
FORBIDDEN_NAMES = ("__pycache__", ".pytest_cache", ".env", "id_rsa", "id_ed25519")
TEXT_SUFFIXES = {
    ".aicad",
    ".cjs",
    ".cs",
    ".csproj",
    ".css",
    ".html",
    ".js",
    ".json",
    ".lsp",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".scr",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {".gitattributes", ".gitignore", "LICENSE", "SHA256SUMS"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid-json:{path.name}:{exc}")
        return {}


def verify(root: Path) -> dict:
    errors: list[str] = []
    root = root.resolve()
    required = (
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "source-manifest.json",
        "dist/aicad-agent-1.7.0.zip",
        "dist/SHA256SUMS",
        "docs/images/modifier-measurements-v3.png",
        "plugins/aicad-agent/.codex-plugin/plugin.json",
        "plugins/aicad-agent/integration-manifest.json",
        "plugins/aicad-agent/SHA256SUMS",
        "scripts/verify_github_source.py",
    )
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"missing:{relative}")

    for name in FORBIDDEN_TOP_LEVEL:
        if (root / name).exists():
            errors.append(f"forbidden-top-level:{name}")

    for path in root.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            errors.append(f"forbidden-name:{path.relative_to(root).as_posix()}")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".dwg", ".sldprt", ".step", ".log"}:
            errors.append(f"forbidden-artifact:{path.relative_to(root).as_posix()}")

    readme_path = root / "README.md"
    readme = ""
    if readme_path.is_file():
        try:
            readme = readme_path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            errors.append(f"readme-utf8:{exc}")
        for fragment in REQUIRED_README_SECTIONS:
            if fragment not in readme:
                errors.append(f"readme-missing:{fragment}")
        for stale in ("v1.3.4", "v1.4.0", "aicad-agent 1.3.4", "aicad-agent 1.4.0"):
            if stale in readme:
                errors.append(f"readme-stale-version:{stale}")
        if "docs/images/modifier-measurements-v3.png" not in readme:
            errors.append("readme-missing-measurement-screenshot")

    workflow = root / ".github" / "workflows" / "ci.yml"
    if workflow.is_file():
        workflow_text = workflow.read_text(encoding="utf-8")
        if "Version 1.7.0" not in workflow_text:
            errors.append("ci-not-pinned-to-1.7.0")
        if "verify_github_source.py" not in workflow_text:
            errors.append("ci-missing-github-source-verifier")
        if "1.3.4" in workflow_text or "1.4.0" in workflow_text:
            errors.append("ci-stale-version")
    else:
        errors.append("missing:.github/workflows/ci.yml")

    plugin_manifest = load_json(root / "plugins" / "aicad-agent" / ".codex-plugin" / "plugin.json", errors)
    if plugin_manifest.get("version") != EXPECTED_VERSION:
        errors.append("plugin-version-mismatch")

    source_manifest = load_json(root / "source-manifest.json", errors)
    if source_manifest.get("version") != EXPECTED_VERSION:
        errors.append("source-version-mismatch")
    if source_manifest.get("releaseStatus") != "engineering-candidate":
        errors.append("source-release-status")
    locks = source_manifest.get("safetyLocks", {})
    expected_locks = {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "comparativeSuperiorityClaimAllowed": False,
    }
    if locks != expected_locks:
        errors.append("source-safety-locks")

    manifest_entries = source_manifest.get("files", [])
    manifest_paths: set[str] = set()
    for entry in manifest_entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            errors.append(f"unsafe-manifest-path:{relative}")
            continue
        manifest_paths.add(relative)
        path = root / relative
        if not path.is_file():
            errors.append(f"manifest-missing:{relative}")
            continue
        if path.stat().st_size != entry.get("size"):
            errors.append(f"manifest-size:{relative}")
        if sha256(path) != entry.get("sha256"):
            errors.append(f"manifest-sha256:{relative}")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "source-manifest.json"
    }
    for relative in sorted(actual_paths - manifest_paths):
        errors.append(f"manifest-unlisted:{relative}")
    for relative in sorted(manifest_paths - actual_paths):
        errors.append(f"manifest-extra:{relative}")

    archive = root / "dist" / "aicad-agent-1.7.0.zip"
    sums = root / "dist" / "SHA256SUMS"
    if archive.is_file() and sums.is_file():
        parts = sums.read_text(encoding="ascii").strip().split()
        if len(parts) != 2 or parts[1] != archive.name or parts[0].lower() != sha256(archive):
            errors.append("dist-checksum-mismatch")
        try:
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
            if not names or any(not name.startswith("aicad-agent/") for name in names):
                errors.append("zip-top-level")
        except zipfile.BadZipFile:
            errors.append("dist-invalid-zip")

    personal_path = re.compile(r"(?:[A-Za-z]:[\\/]Users[\\/]|/Users/|/home/)", re.IGNORECASE)
    mojibake = ("锛", "銆", "鈥", "缁樺埗", "鎻掍欢")
    for path in root.rglob("*"):
        if not path.is_file() or not (path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"text-not-utf8:{relative}")
            continue
        if "\r" in text:
            errors.append(f"non-lf-text:{relative}")
        if relative != "scripts/verify_github_source.py" and personal_path.search(text):
            errors.append(f"personal-path:{relative}")
        if relative != "scripts/verify_github_source.py" and any(marker in text for marker in mojibake):
            errors.append(f"suspected-mojibake:{relative}")

    return {
        "ok": not errors,
        "status": "pass" if not errors else "failed",
        "version": EXPECTED_VERSION,
        "root": str(root),
        "files_checked": len(actual_paths),
        "manifest_files_checked": len(manifest_entries),
        "readme_required_items": len(REQUIRED_README_SECTIONS),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the publishable aicad-agent GitHub source tree")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = verify(args.root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
