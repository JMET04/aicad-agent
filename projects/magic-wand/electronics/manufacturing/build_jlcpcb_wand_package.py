#!/usr/bin/env python3
"""Build and verify the JLCPCB prototype package for the magic-wand PCB."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ELECTRONICS = HERE.parent
BOARD_DIR = ELECTRONICS / "wand"
BOARD = BOARD_DIR / "wand.kicad_pcb"
SCHEMATIC = BOARD_DIR / "wand.kicad_sch"
PACKAGE = HERE / "jlcpcb-wand-rev-a0"
GERBER = PACKAGE / "gerber"
DRILL = PACKAGE / "drill"
ASSEMBLY = PACKAGE / "assembly"
REPORTS = PACKAGE / "reports"
KICAD_CLI = Path(os.environ.get("MAGIC_WAND_KICAD_CLI", r"D:\Temp\KiCad10\bin\kicad-cli.exe"))

LAYERS = (
    "F.Cu", "In1.Cu", "In2.Cu", "B.Cu",
    "F.Paste", "B.Paste", "F.SilkS", "B.SilkS",
    "F.Mask", "B.Mask", "Edge.Cuts",
)
EXPECTED_GERBER_SUFFIXES = {
    ".gtl", ".g1", ".g2", ".gbl", ".gtp", ".gbp",
    ".gto", ".gbo", ".gts", ".gbs", ".gm1", ".gbrjob",
}


def run(*args: str) -> None:
    subprocess.run([str(KICAD_CLI), *args], cwd=ELECTRONICS, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def clean_package() -> None:
    resolved_parent = HERE.resolve()
    resolved_package = PACKAGE.resolve()
    if resolved_package.parent != resolved_parent or resolved_package.name != "jlcpcb-wand-rev-a0":
        raise RuntimeError(f"unsafe package target: {resolved_package}")
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    for directory in (GERBER, DRILL, ASSEMBLY, REPORTS):
        directory.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    if not KICAD_CLI.is_file():
        raise RuntimeError(f"KiCad CLI not found: {KICAD_CLI}")
    clean_package()
    version = subprocess.run(
        [str(KICAD_CLI), "version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if version != "10.0.5":
        raise RuntimeError(f"unreviewed KiCad version: {version}")

    run("sch", "erc", "--severity-all", "--exit-code-violations",
        "--output", str(REPORTS / "wand-native-erc.rpt"), str(SCHEMATIC))
    run("pcb", "drc", "--refill-zones", "--severity-all", "--exit-code-violations",
        "--units", "mm", "--output", str(REPORTS / "wand-native-drc.rpt"), str(BOARD))
    run("pcb", "export", "gerbers", "--layers", ",".join(LAYERS),
        "--check-zones", "--subtract-soldermask", "--output", str(GERBER), str(BOARD))
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal", "--excellon-separate-th", "--generate-map",
        "--map-format", "gerberx2", "--generate-report", "--report-path",
        str(REPORTS / "wand-drill-report.txt"), "--output", str(DRILL), str(BOARD))

    shutil.copy2(BOARD_DIR / "wand-bom.csv", ASSEMBLY / "wand-bom.csv")
    shutil.copy2(BOARD_DIR / "wand-cpl.csv", ASSEMBLY / "wand-cpl.csv")

    gerbers = sorted(path for path in GERBER.iterdir() if path.is_file())
    suffixes = {path.suffix.casefold() for path in gerbers}
    if suffixes != EXPECTED_GERBER_SUFFIXES or len(gerbers) != 12:
        raise RuntimeError(f"unexpected Gerber set: {[path.name for path in gerbers]}")
    upload_drills = [DRILL / "wand-PTH.drl", DRILL / "wand-NPTH.drl"]
    if any(not path.is_file() or path.stat().st_size == 0 for path in gerbers + upload_drills):
        raise RuntimeError("empty or missing manufacturing file")

    order_parameters = {
        "schema": "aicad.jlcpcb-order-parameters.v1",
        "status": "READY_FOR_BARE_PCB_UPLOAD",
        "board": "magic-wand-controller",
        "revision": "A0",
        "quantity": 5,
        "dimensionsMm": [15.0, 80.0],
        "layers": 4,
        "finishedThicknessMm": 1.6,
        "outerCopperWeightOz": 1,
        "solderMask": "Black",
        "silkscreen": "White",
        "surfaceFinish": "ENIG",
        "viaCovering": "Tented",
        "impedanceControl": False,
        "removeOrderNumber": True,
        "panelization": "Single PCB",
        "goldFingers": False,
        "castellatedHoles": False,
        "edgePlating": False,
        "assembly": {
            "requested": False,
            "reason": "Bare-PCB order first; BOM/CPL are included for a later PCBA sourcing pass.",
        },
    }
    write_json(PACKAGE / "jlcpcb-order-parameters.json", order_parameters)
    (PACKAGE / "README.md").write_text(
        "# JLCPCB magic-wand PCB REV A0\n\n"
        "Upload `JLCPCB_WAND_REV_A0_GERBER_DRILL.zip` as a bare-PCB order. "
        "Apply the exact values in `jlcpcb-order-parameters.json`.\n\n"
        "Electronic gates: native KiCad ERC 0/0/None and DRC 0/0/0/None. "
        "BOM/CPL are supplied for review but PCBA is intentionally not selected in this order.\n",
        encoding="utf-8", newline="\n",
    )
    (PACKAGE / "tool-version.txt").write_text(f"KiCad CLI {version}\n", encoding="utf-8", newline="\n")

    upload_zip = PACKAGE / "JLCPCB_WAND_REV_A0_GERBER_DRILL.zip"
    with zipfile.ZipFile(upload_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in gerbers + upload_drills:
            archive.write(path, arcname=path.name)

    manifest_files = sorted(
        path for path in PACKAGE.rglob("*")
        if path.is_file() and path.name != "manufacturing-manifest.json"
    )
    manifest = {
        "schema": "aicad.jlcpcb-manufacturing-package.v1",
        "status": "VERIFIED_UPLOAD_CANDIDATE",
        "revision": "A0",
        "sourceBoard": {
            "path": "electronics/wand/wand.kicad_pcb",
            "size": BOARD.stat().st_size,
            "sha256": sha256(BOARD),
        },
        "electronicGates": {
            "ercErrors": 0, "ercWarnings": 0, "drcViolations": 0,
            "unconnected": 0, "footprintErrors": 0, "exclusions": 0, "suppressions": 0,
        },
        "files": [
            {
                "path": path.relative_to(PACKAGE).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in manifest_files
        ],
    }
    write_json(PACKAGE / "manufacturing-manifest.json", manifest)
    print(json.dumps({
        "status": manifest["status"],
        "uploadZip": str(upload_zip),
        "uploadZipSha256": sha256(upload_zip),
        "gerbers": len(gerbers),
        "drills": len(upload_drills),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
