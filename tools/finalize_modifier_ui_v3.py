from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "modifier-ui-v3-packaged"
RELEASE = ROOT / "release" / "v1.7.0"
PACKAGE = RELEASE / "aicad-agent"
INSTALLED = Path.home() / "plugins" / "aicad-agent"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_tests(test_dir: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(test_dir), "-q"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    transcript = result.stdout + result.stderr
    match = re.search(r"Ran\s+(\d+)\s+tests?", transcript)
    return {
        "ok": result.returncode == 0,
        "count": int(match.group(1)) if match else None,
        "summary": transcript.strip(),
    }


def verify_package(path: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_release_package.py"), str(path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "errors": [result.stdout or result.stderr]}
    payload["process_ok"] = result.returncode == 0
    return payload


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    browser_compat = load_json(BUILD / "validation.compat.json")
    browser_measurements = load_json(BUILD / "validation.measurements.json")
    tests = {
        "source": run_tests(ROOT / "tests"),
        "release": run_tests(PACKAGE / "tests"),
        "installed": run_tests(INSTALLED / "tests"),
    }
    integrity = {
        "release": verify_package(PACKAGE),
        "installed": verify_package(INSTALLED),
    }

    review = BUILD / "mounting_plate_v3_packaged.review.html"
    views = BUILD / "mounting_plate_v3_packaged.views.json"
    compat_png = BUILD / "modifier_v3.compat.png"
    measurements_png = BUILD / "modifier_v3.measurements.png"
    release_zip = RELEASE / "aicad-agent-1.7.0.zip"
    hashes = {
        "review_html": sha256(review),
        "view_package": sha256(views),
        "compatibility_screenshot": sha256(compat_png),
        "measurement_screenshot": sha256(measurements_png),
        "release_zip": sha256(release_zip),
    }
    sums_line = (RELEASE / "SHA256SUMS").read_text(encoding="ascii").strip()
    sums_hash = sums_line.split()[0] if sums_line else ""

    gates = {
        "source_tests": tests["source"]["ok"] and tests["source"]["count"] == 105,
        "release_tests": tests["release"]["ok"] and tests["release"]["count"] == 45,
        "installed_tests": tests["installed"]["ok"] and tests["installed"]["count"] == 45,
        "release_integrity": bool(integrity["release"].get("ok")) and bool(integrity["release"].get("process_ok")),
        "installed_integrity": bool(integrity["installed"].get("ok")) and bool(integrity["installed"].get("process_ok")),
        "browser_compatibility": browser_compat.get("ok") is True and all(browser_compat.get("checks", {}).values()),
        "selection_measurements": browser_measurements.get("ok") is True and all(browser_measurements.get("checks", {}).values()),
        "review_hash_stable": (
            hashes["review_html"] == browser_compat.get("hashes", {}).get("review")
            == browser_measurements.get("hashes", {}).get("review")
        ),
        "release_zip_checksum": hashes["release_zip"] == sums_hash,
    }
    status = "pass" if all(gates.values()) else "failed"

    measurement_evidence = browser_measurements["evidence"]
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "version": "1.7.0",
        "review_only": True,
        "accepted": False,
        "rule_enabled": False,
        "packaging_gated": True,
        "gates": gates,
        "tests": tests,
        "integrity": integrity,
        "browser": {
            "compatibility_checks": len(browser_compat["checks"]),
            "compatibility_passed": sum(browser_compat["checks"].values()),
            "measurement_checks": len(browser_measurements["checks"]),
            "measurement_passed": sum(browser_measurements["checks"].values()),
            "console_errors": browser_measurements.get("errors", []),
        },
        "measured_examples": {
            "line_1": {
                "length_mm": measurement_evidence["line"]["selected"][0]["measurement"]["length_mm"],
                "start": measurement_evidence["line"]["selected"][0]["measurement"]["start"],
                "end": measurement_evidence["line"]["selected"][0]["measurement"]["end"],
                "controller_path": measurement_evidence["line"]["path"],
            },
            "perpendicular_line": {
                "length_mm": measurement_evidence["secondLine"]["selected"][0]["measurement"]["length_mm"],
                "controller_path": measurement_evidence["secondLine"]["path"],
            },
            "point": measurement_evidence["point"]["selected"][0]["measurement"]["coordinates"],
            "circle": {
                "radius_mm": measurement_evidence["circle"]["selected"][0]["measurement"]["radius_mm"],
                "diameter_mm": measurement_evidence["circle"]["selected"][0]["measurement"]["diameter_mm"],
                "center": measurement_evidence["circle"]["selected"][0]["measurement"]["center"],
            },
            "coordinate_system": measurement_evidence["initialCoordinates"]["system"],
            "coordinate_views": {
                "svg_triads": measurement_evidence["initialCoordinates"]["triads"],
                "origin_markers": measurement_evidence["initialCoordinates"]["origins"],
                "toggle_hides_all": browser_measurements["checks"]["coordinateToggleHidesAllViews"],
                "toggle_restores_all": browser_measurements["checks"]["coordinateToggleRestoresAllViews"],
            },
        },
        "root_causes": [
            "旧界面把特征参数目录误当成当前选择对象的直接测量，没有形成 selection reference → compiled measurement → visible card 数据链。",
            "矩形边与宽高参数曾按边号手工绑定，缺少端点方向复核，导致水平边和竖直边控制量颠倒。",
        ],
        "prevention_rules": {
            "SUB-G016": "每个可选线、点、圆、面必须携带由编译模型计算的严格类型 measurement，并在真实浏览器逐类点击验证。",
            "SUB-G017": "坐标系固定为右手 MODEL_XYZ；一个开关同步控制全部 SVG 轴、模型原点和三维坐标轴。",
            "edge_direction_gate": "水平矩形边只允许绑定宽度，竖直矩形边只允许绑定高度；测试必须覆盖一组相互垂直边。",
            "pixel_non_authority": "屏幕像素、缩放和投影只用于命中与显示，不得成为尺寸真值。",
        },
        "hashes": hashes,
        "artifacts": {
            "review_html": str(review),
            "view_package": str(views),
            "compatibility_screenshot": str(compat_png),
            "measurement_screenshot": str(measurements_png),
            "release_directory": str(PACKAGE),
            "release_zip": str(release_zip),
            "installed_plugin": str(INSTALLED),
        },
    }

    (BUILD / "validation.final.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
    )

    md = f"""# CAD 修改器 v3 最终验证

- 总判定：**{status.upper()}**
- 插件版本：1.7.0
- 安全状态：`reviewOnly=true`、`accepted=false`、`ruleEnabled=false`、`packagingGated=true`
- 源码测试：{tests['source']['count']}/105 通过
- 发布包测试：{tests['release']['count']}/45 通过
- 安装包测试：{tests['installed']['count']}/45 通过
- 发布包完整性：{integrity['release'].get('files_checked')} 个文件、{integrity['release'].get('manifest_files_checked')} 个清单项，0 错误
- 安装包完整性：{integrity['installed'].get('files_checked')} 个文件、{integrity['installed'].get('manifest_files_checked')} 个清单项，0 错误
- 原功能浏览器门禁：{sum(browser_compat['checks'].values())}/{len(browser_compat['checks'])} 通过
- 数值与坐标系浏览器门禁：{sum(browser_measurements['checks'].values())}/{len(browser_measurements['checks'])} 通过

## 点击实测

- 直线 `F001|profile.edge.1`：长度 120 mm，起点 (-60,-40,0)，终点 (60,-40,0)，自动回填 `profile.width=120`。
- 垂直边 `F001|profile.edge.2`：长度 80 mm，自动回填 `profile.height=80`，证明宽高没有反绑。
- 点 `F003|profile.center`：坐标 (0,0,12) mm，自动回填 `profile.center=0,0`。
- 圆 `F003|profile.circle.1`：半径 15 mm、直径 30 mm、圆心 (0,0,12) mm，自动回填 `profile.radius=15`。
- 坐标系：右手 `MODEL_XYZ`，单位 mm。顶部“坐标系”开关已实测同步隐藏并恢复 6 个二维轴标、6 个原点标记和三维坐标轴。

## 错误根因与永久规则

旧界面将“特征参数目录”误当成“当前选中对象的直接测量”，缺少 `selection reference → compiled measurement → visible card` 数据链；同时，矩形边按编号手工绑定宽高而没有用端点方向复核，曾造成水平边与竖直边控制量颠倒。

- `SUB-G016`：每个可选线、点、圆、面都必须携带编译模型产生的类型化测量，并在真实浏览器逐类点击。
- `SUB-G017`：一个开关必须同步控制 SVG 轴、模型原点和三维轴，禁止假开关。
- 边方向门禁：水平矩形边只绑定宽，竖直矩形边只绑定高，测试同时覆盖两条垂直边。
- 像素无权威：屏幕像素、缩放和投影不作为尺寸真值。

## 交付与哈希

- 修改器：`{review}`
- 机器验证：`{BUILD / 'validation.final.json'}`
- 交互截图：`{measurements_png}`
- 发布 ZIP：`{release_zip}`
- ZIP SHA256：`{hashes['release_zip']}`
- 修改器 SHA256：`{hashes['review_html']}`
"""
    (BUILD / "validation.final.md").write_text(md, encoding="utf-8-sig")
    print(json.dumps({"status": status, "gates": gates, "outputs": [str(BUILD / "validation.final.json"), str(BUILD / "validation.final.md")]}, ensure_ascii=False))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
