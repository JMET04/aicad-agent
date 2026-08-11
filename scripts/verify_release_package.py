from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a built aicad-agent release without modifying it")
    parser.add_argument("plugin_dir", type=Path)
    args = parser.parse_args()
    root = args.plugin_dir.resolve()
    errors: list[str] = []

    plugin_path = root / ".codex-plugin" / "plugin.json"
    manifest_path = root / "integration-manifest.json"
    sums_path = root / "SHA256SUMS"
    for required in (
        plugin_path,
        manifest_path,
        sums_path,
        root / "LICENSE",
        root / "runtime" / "src" / "aicad" / "engine.py",
        root / "runtime" / "src" / "aicad" / "reference_rebuild.py",
        root / "runtime" / "src" / "aicad" / "subobject_correction.py",
        root / "runtime" / "schema" / "aicad-correction.schema.json",
        root / "rules" / "subobject_correction_rules.json",
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
    ):
        if not required.is_file():
            errors.append(f"missing:{required.relative_to(root)}")
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False))
        return 2

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
        if any(part in FORBIDDEN_NAMES for part in path.parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"cache:{path.relative_to(root).as_posix()}")
        if path.name in FORBIDDEN_BINARY_NAMES:
            errors.append(f"proprietary-binary:{path.relative_to(root).as_posix()}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "\ufffd" in text or any(0xE000 <= ord(character) <= 0xF8FF for character in text):
            errors.append(f"mojibake-codepoint:{path.relative_to(root).as_posix()}")
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(text):
                errors.append(f"forbidden-text:{path.relative_to(root).as_posix()}:{pattern.pattern}")

    for item in manifest.get("files", []):
        path = root / item["path"]
        if not path.is_file():
            errors.append(f"manifest-missing:{item['path']}")
            continue
        if path.stat().st_size != item["size"]:
            errors.append(f"manifest-size:{item['path']}")
        if sha256(path) != item["sha256"]:
            errors.append(f"manifest-hash:{item['path']}")

    for line in sums_path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            errors.append(f"sums:{relative}")

    result = {
        "ok": not errors,
        "version": plugin.get("version"),
        "files_checked": len(files),
        "manifest_files_checked": len(manifest.get("files", [])),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
