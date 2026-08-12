from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath


EXPECTED_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
    "comparativeSuperiorityClaimAllowed": False,
}
FORBIDDEN_NAMES = {"__pycache__", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}
FORBIDDEN_BINARY_NAMES = {
    "AiCad.SolidWorksHost.exe",
    "SolidWorks.Interop.sldworks.dll",
    "SolidWorks.Interop.swconst.dll",
}
FORBIDDEN_TEXT = (
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"D:\\CAD绘制插件", re.IGNORECASE),
    re.compile("\u5218\u4f73\u660e"),
    re.compile("g" + r"hp_[A-Za-z0-9]+"),
    re.compile("github_" + r"pat_[A-Za-z0-9_]+"),
    re.compile(r"BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY"),
)
SOURCE_INPUT_POLICY = "agent_plugin_builder_v1"
SOURCE_TREE_ROOTS = (
    "agent-plugin/aicad-agent",
    "src/aicad",
    "plugin/AiCadConstraint.bundle",
)
SOURCE_TOP_LEVEL_FILE_ROOTS = ("schema", "examples")
SOURCE_FIXED_FILES = (
    "scripts/build-agent-plugin.ps1",
    "scripts/verify_release_package.py",
    "solidworks-host/AiCad.SolidWorksHost/Program.cs",
    "solidworks-host/AiCad.SolidWorksHost/AiCad.SolidWorksHost.csproj",
    "scripts/build-solidworks-host.ps1",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


def source_files(source_root: Path, include_solidworks_interop: bool) -> set[str]:
    result: set[str] = set()

    def add_tree(relative: str) -> None:
        root = source_root / relative
        if not root.is_dir():
            return
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(source_root).as_posix()
            if any(part in FORBIDDEN_NAMES for part in PurePosixPath(rel).parts):
                continue
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:
                continue
            result.add(rel)

    for relative in SOURCE_TREE_ROOTS:
        add_tree(relative)
    for relative in SOURCE_TOP_LEVEL_FILE_ROOTS:
        directory = source_root / relative
        if directory.is_dir():
            result.update(
                path.relative_to(source_root).as_posix()
                for path in directory.iterdir()
                if path.is_file() and not path.is_symlink()
            )
    for relative in SOURCE_FIXED_FILES:
        if (source_root / relative).is_file():
            result.add(relative)
    if include_solidworks_interop:
        add_tree("build/solidworks-host")
    return result


def verify_entries(
    *,
    entries: object,
    expected_paths: set[str],
    root: Path,
    label: str,
    errors: list[str],
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


def verify(plugin_dir: Path, source_root: Path | None = None) -> dict:
    root = plugin_dir.resolve()
    errors: list[str] = []
    plugin_path = root / ".codex-plugin" / "plugin.json"
    manifest_path = root / "integration-manifest.json"
    sums_path = root / "SHA256SUMS"
    required = (
        plugin_path,
        manifest_path,
        sums_path,
        root / "LICENSE",
        root / "runtime" / "src" / "aicad" / "engine.py",
        root / "runtime" / "src" / "aicad" / "reference_rebuild.py",
        root / "runtime" / "src" / "aicad" / "subobject_correction.py",
        root / "runtime" / "schema" / "aicad-correction.schema.json",
        root / "rules" / "subobject_correction_rules.json",
        root / "rules" / "architectural_drafting_rules.json",
        root / "scripts" / "aicad_architecture_qa.py",
        root / "tests" / "test_architectural_drafting_rules.py",
        root / "docs" / "ARCHITECTURAL_DRAFTING.md",
        root / "rules" / "cad_normative_quality_rules.json",
        root / "rules" / "cad_normative_quality_contract.schema.json",
        root / "scripts" / "aicad_normative_quality_qa.py",
        root / "tests" / "test_cad_normative_quality.py",
        root / "rules" / "native_solidworks_topology_rules.json",
        root / "docs" / "NATIVE_SOLIDWORKS_TOPOLOGY.md",
        root / "skills" / "aicad-model-3d" / "references" / "native-topology.md",
        root / "runtime" / "solidworks-host-source" / "Program.cs",
        root / "tests" / "test_native_solidworks_topology_rules.py",
        root / "docs" / "EXACT_SUBOBJECT_CORRECTION.md",
        root / "runtime" / "schema" / "aicad-reference-rebuild.schema.json",
        root / "runtime" / "examples" / "web_reference_plate.html",
        root / "scripts" / "aicad_reference_visual_qa.cjs",
        root / "scripts" / "aicad_multiview_visual_qa.cjs",
        root / "tests" / "test_subobject_correction_rules.py",
        root / "tests" / "test_reference_rebuild_release.py",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"missing:{path.relative_to(root)}")
    if not plugin_path.is_file() or not manifest_path.is_file() or not sums_path.is_file():
        return {"ok": False, "errors": errors}

    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if plugin.get("name") != "aicad-agent":
        errors.append("plugin-name")
    if plugin.get("version") != manifest.get("version"):
        errors.append("version-mismatch")
    if len(plugin.get("interface", {}).get("defaultPrompt", [])) > 3:
        errors.append("too-many-default-prompts")
    if manifest.get("apiKeyRequired") is not False:
        errors.append("api-key-policy")
    if manifest.get("safetyLocks") != EXPECTED_LOCKS:
        errors.append("safety-locks")
    if manifest.get("proprietaryDependenciesRedistributed") is not False:
        errors.append("proprietary-redistribution-policy")

    files = [path for path in root.rglob("*") if path.is_file()]
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"symlink:{relative}")
        if any(part in FORBIDDEN_NAMES for part in path.parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"cache:{relative}")
        if path.name in FORBIDDEN_BINARY_NAMES:
            errors.append(f"proprietary-binary:{relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "\ufffd" in text or any(0xE000 <= ord(character) <= 0xF8FF for character in text):
            errors.append(f"mojibake-codepoint:{relative}")
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(text):
                errors.append(f"forbidden-text:{relative}:{pattern.pattern}")

    actual_paths = {path.relative_to(root).as_posix() for path in files}
    payload_paths = actual_paths - {"integration-manifest.json", "SHA256SUMS"}
    manifest_count = verify_entries(
        entries=manifest.get("files"),
        expected_paths=payload_paths,
        root=root,
        label="manifest",
        errors=errors,
    )

    sum_rows: list[dict[str, object]] = []
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            errors.append(f"invalid-sums-line:{line}")
            continue
        expected, relative = line.split("  ", 1)
        sum_rows.append({"path": relative, "sha256": expected, "size": (root / relative).stat().st_size if (root / relative).is_file() else None})
    sums_count = verify_entries(
        entries=sum_rows,
        expected_paths=actual_paths - {"SHA256SUMS"},
        root=root,
        label="sums",
        errors=errors,
    )

    source_count = 0
    if manifest.get("sourceInputPolicy") != SOURCE_INPUT_POLICY:
        errors.append("source-input-policy")
    if source_root is None:
        errors.append("source-root-required")
    else:
        resolved_source = source_root.resolve()
        include_interop = manifest.get("buildOptions", {}).get("includeSolidWorksInterop") is True
        expected_inputs = source_files(resolved_source, include_interop)
        source_count = verify_entries(
            entries=manifest.get("sourceInputs"),
            expected_paths=expected_inputs,
            root=resolved_source,
            label="source-input",
            errors=errors,
        )

    return {
        "ok": not errors,
        "version": plugin.get("version"),
        "files_checked": len(files),
        "manifest_files_checked": manifest_count,
        "sums_files_checked": sums_count,
        "source_inputs_checked": source_count,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a built aicad-agent release without modifying it")
    parser.add_argument("plugin_dir", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    result = verify(args.plugin_dir, args.source_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
