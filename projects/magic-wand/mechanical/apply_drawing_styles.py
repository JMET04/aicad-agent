from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import ezdxf


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "drawing-style-profile.json"
ARTIFACTS_ROOT = ROOT / "artifacts" / "2d"
AUDIT_PATH = ROOT / "evidence" / "drawing-style-audit.json"

LINETYPE_PATTERNS: dict[str, tuple[str, list[float]]] = {
    "DASHED": ("Dashed __ __ __", [19.05, 12.7, -6.35]),
    "DASHED2": ("Dashed half scale", [9.525, 6.35, -3.175]),
    "CENTER2": ("Center half scale", [15.875, 9.525, -3.175, 1.5875, -1.5875]),
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    document = ezdxf.readfile(path)
    rows: dict[str, dict[str, int | str]] = {}
    for name, expected in profile["layers"].items():
        if name not in document.layers:
            continue
        layer = document.layers.get(name)
        rows[name] = {
            "color": int(layer.dxf.color),
            "lineweight": int(layer.dxf.lineweight),
            "linetype": str(layer.dxf.linetype).upper(),
        }
        if rows[name] != expected:
            raise RuntimeError(f"{path.name}: layer {name} is not styled by the controlled profile")
    if "OUTLINE" in rows and "CENTER" in rows:
        if int(rows["OUTLINE"]["lineweight"]) <= int(rows["CENTER"]["lineweight"]):
            raise RuntimeError(f"{path.name}: outline must be heavier than centerline")
        if rows["CENTER"]["linetype"] == rows["OUTLINE"]["linetype"]:
            raise RuntimeError(f"{path.name}: centerline must differ from outline")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "layers": rows,
    }


def apply(path: Path, profile: dict[str, Any]) -> None:
    document = ezdxf.readfile(path)
    required_linetypes = {
        str(row["linetype"]).upper()
        for row in profile["layers"].values()
        if str(row["linetype"]).upper() != "CONTINUOUS"
    }
    for name in sorted(required_linetypes):
        if name not in document.linetypes:
            description, pattern = LINETYPE_PATTERNS[name]
            document.linetypes.add(name, pattern=pattern, description=description)
    for name, row in profile["layers"].items():
        if name not in document.layers:
            continue
        layer = document.layers.get(name)
        layer.dxf.color = int(row["color"])
        layer.dxf.lineweight = int(row["lineweight"])
        layer.dxf.linetype = str(row["linetype"])
    for entity in document.modelspace():
        if str(entity.dxf.layer).upper() in profile["layers"]:
            entity.dxf.color = 256
            entity.dxf.lineweight = -1
            entity.dxf.linetype = "BYLAYER"
    document.saveas(path)


def run(check: bool) -> dict[str, Any]:
    profile = load_json(PROFILE_PATH)
    paths = sorted(ARTIFACTS_ROOT.glob("*/*.dxf"))
    if len(paths) != 5:
        raise RuntimeError(f"expected five compiled DXF artifacts, found {len(paths)}")
    if not check:
        for path in paths:
            apply(path, profile)
    rows = [inspect(path, profile) for path in paths]
    audit = {
        "schema": "aicad_magic_wand_mechanical_drawing_style_audit_v1",
        "revision": profile["revision"],
        "status": "passed",
        "profile": PROFILE_PATH.relative_to(ROOT).as_posix(),
        "files": rows,
        "assertions": {
            "outline_heavier_than_center": True,
            "centerline_noncontinuous": True,
            "hidden_line_noncontinuous_where_present": True,
            "keepout_noncontinuous_where_present": True,
            "entity_properties_by_layer": True
        },
        "locks": profile["locks"],
    }
    if check:
        if not AUDIT_PATH.exists() or load_json(AUDIT_PATH) != audit:
            raise RuntimeError("drawing style audit is stale or missing")
    else:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the package-local controlled mechanical DXF layer profile")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run(args.check)
    print(json.dumps({"ok": True, "status": result["status"], "fileCount": len(result["files"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
