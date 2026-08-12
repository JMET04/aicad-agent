from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath


EXPECTED_VERSION = "1.12.0"
SOURCE_INPUT_POLICY = "github_source_builder_v1"
REQUIRED_README_SECTIONS = (
    "# aicad-agent 1.12.0",
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
    "建筑平面专业制图",
    "默认不需要 API Key",
)
FORBIDDEN_TOP_LEVEL = ("build", "jobs", "out", "release", ".git")
FORBIDDEN_NAMES = ("__pycache__", ".pytest_cache", ".env", "id_rsa", "id_ed25519")
SOURCE_SKIP_NAMES = {"__pycache__", ".pytest_cache", "bin", "obj"}
SOURCE_SKIP_SUFFIXES = {".pyc", ".pyo"}
SOURCE_ROOT_FILES = ("README.md", "pyproject.toml", ".gitignore", ".gitattributes")
SOURCE_TREE_ROOTS = (
    ".github", ".agents", "src", "schema", "examples", "prompts", "docs",
    "plugin", "agent-plugin", "scripts", "tests", "tools", "showcase",
)
SOURCE_FIXED_FILES = (
    "solidworks-host/AiCad.SolidWorksHost/Program.cs",
    "solidworks-host/AiCad.SolidWorksHost/AiCad.SolidWorksHost.csproj",
)
TEXT_SUFFIXES = {
    ".aicad", ".cjs", ".cs", ".csproj", ".css", ".html", ".js", ".json",
    ".lsp", ".md", ".mjs", ".ps1", ".py", ".scr", ".svg", ".toml",
    ".txt", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {".gitattributes", ".gitignore", "LICENSE", "SHA256SUMS"}
SHOWCASE_SLUGS = ("architecture", "steel", "mechanical", "pcb")


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


def safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


def tree_files(source_root: Path, relative: str) -> set[str]:
    result: set[str] = set()
    tree = source_root / relative
    if not tree.is_dir():
        return result
    for path in tree.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(source_root).as_posix()
        if any(part in SOURCE_SKIP_NAMES for part in PurePosixPath(rel).parts):
            continue
        if path.suffix.lower() in SOURCE_SKIP_SUFFIXES:
            continue
        result.add(rel)
    return result


def expected_source_inputs(source_root: Path, manifest: dict, errors: list[str]) -> set[str]:
    result = {relative for relative in SOURCE_ROOT_FILES if (source_root / relative).is_file()}
    for relative in SOURCE_TREE_ROOTS:
        result.update(tree_files(source_root, relative))
    result.update(relative for relative in SOURCE_FIXED_FILES if (source_root / relative).is_file())
    build_inputs = manifest.get("sourceBuildInputs")
    if not isinstance(build_inputs, dict):
        errors.append("source-build-inputs")
        return result
    plugin_dir = safe_relative(build_inputs.get("pluginDirectory"))
    archive = safe_relative(build_inputs.get("pluginArchive"))
    if plugin_dir is None or not plugin_dir.startswith("release/"):
        errors.append(f"unsafe-source-plugin-directory:{build_inputs.get('pluginDirectory')}")
    else:
        result.update(tree_files(source_root, plugin_dir))
    if archive is None or not archive.startswith("release/"):
        errors.append(f"unsafe-source-plugin-archive:{build_inputs.get('pluginArchive')}")
    elif (source_root / archive).is_file():
        result.add(archive)
    return result


def verify_entries(
    *, entries: object, expected_paths: set[str], root: Path, label: str, errors: list[str]
) -> int:
    if not isinstance(entries, list):
        errors.append(f"{label}-not-list")
        return 0
    normalized: list[str] = []
    rows: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{label}-entry-not-object")
            continue
        relative = safe_relative(entry.get("path"))
        if relative is None:
            errors.append(f"unsafe-{label}-path:{entry.get('path')}")
            continue
        normalized.append(relative)
        rows[relative] = entry
    for relative, count in Counter(normalized).items():
        if count != 1:
            errors.append(f"duplicate-{label}-path:{relative}")
    actual_set = set(normalized)
    for relative in sorted(expected_paths - actual_set):
        errors.append(f"{label}-unlisted:{relative}")
    for relative in sorted(actual_set - expected_paths):
        errors.append(f"{label}-extra:{relative}")
    resolved_root = root.resolve()
    for relative in sorted(actual_set & expected_paths):
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            errors.append(f"{label}-missing:{relative}")
            continue
        if path.is_symlink() or resolved_root not in resolved.parents:
            errors.append(f"{label}-escape:{relative}")
            continue
        entry = rows[relative]
        if path.stat().st_size != entry.get("size"):
            errors.append(f"{label}-size:{relative}")
        if sha256(path) != entry.get("sha256"):
            errors.append(f"{label}-sha256:{relative}")
    return len(actual_set)


def verify_showcase(root: Path, errors: list[str]) -> int:
    showcase = root / "showcase"
    required = {"README.md", "showcase-manifest.json"}
    for slug in SHOWCASE_SLUGS:
        required.update({
            f"{slug}/preview.png",
            f"{slug}/review.html",
            f"{slug}/validation.json",
            f"{slug}/validation.md",
            f"{slug}/source-manifest.json",
            f"{slug}/{slug}-sanitized-review-candidate.zip",
        })
    for relative in sorted(required):
        if not (showcase / relative).is_file():
            errors.append(f"showcase-missing:{relative}")

    manifest = load_json(showcase / "showcase-manifest.json", errors)
    if manifest.get("schema") != "aicad_github_showcase_v2":
        errors.append("showcase-schema")
    if manifest.get("releaseStatus") != "engineering-review-candidate":
        errors.append("showcase-release-status")
    expected_locks = {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "productionOrFabricationAcceptanceClaimed": False,
    }
    if manifest.get("safetyLocks") != expected_locks:
        errors.append("showcase-safety-locks")
    demos = manifest.get("demos")
    demo_slugs = [row.get("slug") for row in demos] if isinstance(demos, list) and all(isinstance(row, dict) for row in demos) else []
    if Counter(demo_slugs) != Counter(SHOWCASE_SLUGS):
        errors.append(f"showcase-demo-bijection:{demo_slugs}")
    expected_input_locks = {key: expected_locks[key] for key in ("reviewOnly", "accepted", "ruleEnabled", "packagingGated")}
    for row in demos if isinstance(demos, list) else []:
        if isinstance(row, dict) and row.get("inputSafetyLocks") != expected_input_locks:
            errors.append(f"showcase-input-locks:{row.get('slug')}")

    actual_paths = {
        path.relative_to(showcase).as_posix()
        for path in showcase.rglob("*")
        if path.is_file()
    } if showcase.is_dir() else set()
    closure = manifest.get("outputClosure")
    if not isinstance(closure, dict) or closure.get("policy") != "all_output_files_except_manifest_self":
        errors.append("showcase-output-closure-policy")
        entries = []
    else:
        entries = closure.get("files")
    closure_count = verify_entries(
        entries=entries,
        expected_paths=actual_paths - {"showcase-manifest.json"},
        root=showcase,
        label="showcase-closure",
        errors=errors,
    )
    readme_path = showcase / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        for relative in sorted(required - {"README.md", "showcase-manifest.json"}):
            if relative.endswith(("source-manifest.json", "validation.json")):
                continue
            if relative not in readme:
                errors.append(f"showcase-readme-link:{relative}")
    return closure_count


def verify(root: Path, source_root: Path | None = None) -> dict:
    errors: list[str] = []
    root = root.resolve()
    required = (
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "source-manifest.json",
        "dist/aicad-agent-1.12.0.zip",
        "dist/SHA256SUMS",
        "docs/images/modifier-measurements-v3.png",
        "plugins/aicad-agent/.codex-plugin/plugin.json",
        "plugins/aicad-agent/integration-manifest.json",
        "plugins/aicad-agent/SHA256SUMS",
        "plugins/aicad-agent/rules/architectural_drafting_rules.json",
        "plugins/aicad-agent/scripts/aicad_architecture_qa.py",
        "plugins/aicad-agent/tests/test_architectural_drafting_rules.py",
        "plugins/aicad-agent/rules/cad_normative_quality_rules.json",
        "plugins/aicad-agent/rules/cad_normative_quality_contract.schema.json",
        "plugins/aicad-agent/scripts/aicad_normative_quality_qa.py",
        "plugins/aicad-agent/tests/test_cad_normative_quality.py",
        "docs/ARCHITECTURAL_DRAFTING.md",
        "scripts/build_showcase.py",
        "tests/test_build_showcase.py",
        "showcase/README.md",
        "showcase/showcase-manifest.json",
        "scripts/verify_github_source.py",
    )
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"missing:{relative}")

    for name in FORBIDDEN_TOP_LEVEL:
        if (root / name).exists():
            errors.append(f"forbidden-top-level:{name}")

    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"symlink:{relative}")
        if path.name in FORBIDDEN_NAMES:
            errors.append(f"forbidden-name:{relative}")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".dwg", ".sldprt", ".step", ".log"}:
            errors.append(f"forbidden-artifact:{relative}")

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
        if "Version 1.12.0" not in workflow_text:
            errors.append("ci-not-pinned-to-1.12.0")
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
    expected_locks = {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "comparativeSuperiorityClaimAllowed": False,
    }
    if source_manifest.get("safetyLocks", {}) != expected_locks:
        errors.append("source-safety-locks")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    manifest_count = verify_entries(
        entries=source_manifest.get("files"),
        expected_paths=actual_paths - {"source-manifest.json"},
        root=root,
        label="manifest",
        errors=errors,
    )

    source_count = 0
    if source_manifest.get("sourceInputPolicy") != SOURCE_INPUT_POLICY:
        errors.append("source-input-policy")
    if source_root is None:
        errors.append("source-root-required")
    else:
        resolved_source = source_root.resolve()
        expected_inputs = expected_source_inputs(resolved_source, source_manifest, errors)
        source_count = verify_entries(
            entries=source_manifest.get("sourceInputs"),
            expected_paths=expected_inputs,
            root=resolved_source,
            label="source-input",
            errors=errors,
        )
    showcase_count = verify_showcase(root, errors)

    archive = root / "dist" / "aicad-agent-1.12.0.zip"
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

    personal_path = re.compile(r"(?:[A-Za-z]:[\\/](?:Users|CAD绘制插件)[\\/]|/Users/|/home/)", re.IGNORECASE)
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
        if "\r" in text and not relative.startswith("showcase/"):
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
        "manifest_files_checked": manifest_count,
        "source_inputs_checked": source_count,
        "showcase_files_checked": showcase_count,
        "readme_required_items": len(REQUIRED_README_SECTIONS),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the publishable aicad-agent GitHub source tree")
    parser.add_argument("root", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    result = verify(args.root, args.source_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
