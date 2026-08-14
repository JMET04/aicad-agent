#!/usr/bin/env python3
"""Refresh only the exact top-level showcase file closure after adding review evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "showcase"
MANIFEST = SHOWCASE / "showcase-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "aicad_github_showcase_v2":
        raise RuntimeError("Unexpected showcase manifest schema.")
    expected_locks = {
        "reviewOnly": True,
        "accepted": False,
        "ruleEnabled": False,
        "packagingGated": True,
        "productionOrFabricationAcceptanceClaimed": False,
    }
    if manifest.get("safetyLocks") != expected_locks:
        raise RuntimeError("Showcase safety locks changed; refusing to refresh closure.")
    files = sorted(
        (path for path in SHOWCASE.rglob("*") if path.is_file() and path != MANIFEST),
        key=lambda path: (path.relative_to(SHOWCASE).as_posix().casefold(), path.relative_to(SHOWCASE).as_posix()),
    )
    manifest["outputClosure"] = {
        "policy": "all_output_files_except_manifest_self",
        "files": [
            {
                "path": path.relative_to(SHOWCASE).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "pass", "files": len(files), "manifestSha256": sha256(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
