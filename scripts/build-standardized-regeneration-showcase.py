#!/usr/bin/env python3
"""Build deterministic public archives for the standardized regeneration evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


FIXED_ZIP_TIME = (2026, 8, 14, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_tree(source: Path, archive: Path) -> int:
    files = sorted(
        path for path in source.rglob("*")
        if path.is_file() and ".kicad_profile" not in path.parts and "__pycache__" not in path.parts
        and path.suffix.lower() not in {".pyc", ".pyo"}
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mechanical", type=Path, required=True)
    parser.add_argument("--electronics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mechanical-preview", type=Path, required=True)
    args = parser.parse_args()

    mechanical = args.mechanical.resolve(strict=True)
    electronics = args.electronics.resolve(strict=True)
    output = args.output.resolve()
    repository = Path(__file__).resolve().parents[1]
    showcase_root = (repository / "showcase").resolve()
    if output.parent != showcase_root or output.name != "standardized-regeneration-v1.15.0":
        raise RuntimeError(f"Output must be the canonical v1.15.0 showcase directory: {output}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    mechanical_zip = output / "mechanical-standardized-review.zip"
    electronics_zip = output / "electronics-blocked-review.zip"
    mechanical_count = package_tree(mechanical, mechanical_zip)
    electronics_count = package_tree(electronics, electronics_zip)
    shutil.copy2(args.mechanical_preview.resolve(strict=True), output / "mechanical-preview.png")
    shutil.copy2(electronics / "renders" / "board-top.png", output / "electronics-preview.png")

    manifest = {
        "schemaVersion": 1,
        "release": "v1.15.0",
        "status": "STANDARDIZED_REGENERATION_REVIEW_EVIDENCE",
        "packages": [
            {
                "discipline": "mechanical",
                "path": mechanical_zip.name,
                "files": mechanical_count,
                "bytes": mechanical_zip.stat().st_size,
                "sha256": sha256(mechanical_zip),
                "evidenceContractReady": True,
                "technicalPackageReady": False,
            },
            {
                "discipline": "electronics",
                "path": electronics_zip.name,
                "files": electronics_count,
                "bytes": electronics_zip.stat().st_size,
                "sha256": sha256(electronics_zip),
                "nativeErcViolations": 0,
                "nativeDrcGeometryViolations": 0,
                "nativeDrcUnconnectedItems": 37,
                "camOutputsWithheld": True,
                "evidenceContractReady": False,
                "technicalPackageReady": False,
            },
        ],
        "thirdPartyRuntimePolicy": {
            "freeroutingJarIncluded": False,
            "javaRuntimeIncluded": False,
            "kicadRuntimeIncluded": False,
            "reason": "The evidence binds versions, commands, and hashes without redistributing third-party runtimes.",
        },
        "productionReleaseEligible": False,
        "fabricationAuthorized": False,
        "manufacturingAuthorized": False,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    checksum_rows = [f"{row['sha256']}  {row['path']}" for row in manifest["packages"]]
    (output / "SHA256SUMS").write_text("\n".join(checksum_rows) + "\n", encoding="utf-8")
    (output / "README.md").write_text(
        "# Standardized regeneration evidence — v1.15.0\n\n"
        "These archives supersede the earlier showcase drawings for engineering review. They do not authorize production.\n\n"
        "- Mechanical: regenerated unique geometry, native SolidWorks/AutoCAD save-reopen evidence, drawings, BOM, analysis, 54-rule preflight, and v3 evidence contract.\n"
        "- Electronics: 63-rule preflight, accepted Stage A schematic, Stage B placement parity, constrained KiCad Stage C, native ERC/DRC, routing geometry, PDFs, BOM/CPL, STEP, and renders.\n"
        "- Electronics remains blocked by 37 native unconnected items plus unresolved field-return, buck hot-loop, impedance, EMC, thermal, and qualification gates. Gerber, drill, and job files are intentionally withheld.\n"
        "- Every readiness and authorization lock remains false except the mechanical evidence-contract completeness flag.\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": manifest["status"],
        "mechanicalFiles": mechanical_count,
        "electronicsFiles": electronics_count,
        "output": str(output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
