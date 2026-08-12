#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable


REVIEW_LAUNCH_MODES = ("auto", "stage", "always", "never")


def _evidence_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _load_review_launcher():
    plugin_root = Path(__file__).resolve().parents[1]
    candidates = [plugin_root / "runtime" / "src", plugin_root.parents[1] / "src"]
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    from aicad.review_launch import launch_review

    return launch_review


def _review_launch_json_path(html_path: Path) -> Path:
    suffix = ".review.html"
    if html_path.name == "review.html":
        return html_path.with_name("review-launch.json")
    if html_path.name.endswith(suffix):
        return html_path.with_name(html_path.name[:-len(suffix)] + ".review-launch.json")
    return html_path.with_suffix(".review-launch.json")


def write_html(report: dict[str, Any], path: Path, title: str = "AICAD 审核报告") -> None:
    status = str(report.get("status", "unknown")).lower()
    passed = status == "pass"
    checks = report.get("checks", {}) if isinstance(report.get("checks"), dict) else {}
    if not checks and isinstance(report.get("gateResults"), dict):
        checks = {
            name: {"pass": item.get("status") == "pass", "evidence": item.get("evidence")}
            for name, item in report["gateResults"].items()
            if isinstance(item, dict)
        }
    rows: list[str] = []
    for name, item in checks.items():
        item = item if isinstance(item, dict) else {"pass": False, "evidence": item}
        result = bool(item.get("pass"))
        badge = "通过" if result else "失败"
        css = "pass" if result else "fail"
        evidence = html.escape(_evidence_text(item.get("evidence")))
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(name))}</code></td>"
            f"<td><span class='badge {css}'>{badge}</span></td>"
            f"<td><details><summary>查看证据</summary><pre>{evidence}</pre></details></td>"
            "</tr>"
        )
    lessons: list[str] = []
    for lesson in report.get("rootCauseLessons", []):
        if not isinstance(lesson, dict):
            continue
        lessons.append(
            "<article class='lesson'>"
            f"<h3>{html.escape(str(lesson.get('ruleId', '规则')))}</h3>"
            f"<p><b>现象：</b>{html.escape(str(lesson.get('symptom', '')))}</p>"
            f"<p><b>根因：</b>{html.escape(str(lesson.get('rootCause', '')))}</p>"
            f"<p><b>修正：</b>{html.escape(str(lesson.get('correction', '')))}</p>"
            f"<p><b>预防规则：</b>{html.escape(str(lesson.get('preventionRule', '')))}</p>"
            "</article>"
        )
    disposition = html.escape(str(report.get("artifactDisposition", "unknown")))
    release_allowed = "是" if report.get("releaseAllowed") else "否"
    banner_class = "ok" if passed else "blocked"
    banner_text = "审核通过" if passed else "已阻断：不允许输出 CAD"
    raw = html.escape(_evidence_text(report))
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#f4f6f8;--paper:#fff;--ink:#18212b;--muted:#5c6975;--line:#d7dde3;--pass:#176b45;--fail:#a32020;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif;line-height:1.65}}
main{{max-width:1260px;margin:32px auto;padding:0 24px 48px}} .card{{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:24px;margin:16px 0;box-shadow:0 4px 20px #1926330d}}
h1{{font-size:28px;margin:0 0 8px}} h2{{font-size:20px;margin:0 0 14px}} h3{{margin:0 0 8px}} .meta{{color:var(--muted)}}
.banner{{border-radius:10px;padding:18px 20px;font-size:20px;font-weight:700}} .banner.blocked{{background:#fff0f0;color:var(--fail);border:2px solid #e2a1a1}} .banner.ok{{background:#effbf5;color:var(--pass);border:2px solid #9bd5b8}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}} .fact{{border:1px solid var(--line);border-radius:8px;padding:12px}} .fact small{{display:block;color:var(--muted)}}
table{{width:100%;border-collapse:collapse}} th,td{{border-bottom:1px solid var(--line);padding:12px;text-align:left;vertical-align:top}} th{{background:#f7f8fa}} .badge{{display:inline-block;border-radius:999px;padding:2px 10px;font-weight:700}} .badge.pass{{background:#e7f6ee;color:var(--pass)}} .badge.fail{{background:#fdeaea;color:var(--fail)}}
details summary{{cursor:pointer;color:#245f94}} pre{{white-space:pre-wrap;word-break:break-word;background:#111820;color:#e9eef2;border-radius:8px;padding:14px;max-height:420px;overflow:auto}} .lesson{{border-left:4px solid #d18b23;padding:10px 16px;margin:14px 0;background:#fff9ee}}
.print{{border:0;border-radius:8px;background:#244d73;color:white;padding:10px 16px;cursor:pointer}} @media print{{body{{background:white}}main{{max-width:none;margin:0;padding:0}}.card{{box-shadow:none;break-inside:avoid}}.print{{display:none}}details{{display:block}}}}
</style>
</head>
<body><main>
<section class="card"><h1>{html.escape(title)}</h1><p class="meta">单文件 UTF-8 审核入口；无需服务器或外部字体资源。</p><div class="banner {banner_class}">{banner_text}</div></section>
<section class="card facts">
<div class="fact"><small>状态</small><b>{html.escape(status.upper())}</b></div>
<div class="fact"><small>工件处置</small><b>{disposition}</b></div>
<div class="fact"><small>允许生产候选</small><b>{release_allowed}</b></div>
<div class="fact"><small>失败项数</small><b>{sum(1 for item in checks.values() if not bool(item.get('pass')))}</b></div>
</section>
<section class="card"><h2>逐项检查</h2><table><thead><tr><th>检查</th><th>结果</th><th>证据</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section class="card"><h2>错误根因与永久规则</h2>{''.join(lessons) or '<p>本报告未提供根因条目。</p>'}</section>
<section class="card"><h2>原始机器数据</h2><details><summary>展开完整 JSON</summary><pre>{raw}</pre></details></section>
<section class="card"><button class="print" onclick="window.print()">打印 / 另存为 PDF</button></section>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, replace_whitespace=False, drop_whitespace=True) or [""]


def write_png(report: dict[str, Any], path: Path, title: str = "AICAD 审核摘要") -> None:
    from PIL import Image, ImageDraw

    checks = report.get("checks", {}) if isinstance(report.get("checks"), dict) else {}
    if not checks and isinstance(report.get("gateResults"), dict):
        checks = {
            name: {"pass": item.get("status") == "pass", "evidence": item.get("evidence")}
            for name, item in report["gateResults"].items()
            if isinstance(item, dict)
        }
    failed = [name for name, item in checks.items() if not bool((item or {}).get("pass"))]
    lessons = [item for item in report.get("rootCauseLessons", []) if isinstance(item, dict)]
    lines = [
        f"总状态：{str(report.get('status', 'unknown')).upper()}",
        f"工件处置：{report.get('artifactDisposition', 'unknown')}",
        f"允许生产候选：{'是' if report.get('releaseAllowed') else '否'}",
        "失败项：" + ("、".join(failed) if failed else "无"),
    ]
    for lesson in lessons:
        lines.extend([
            f"{lesson.get('ruleId', '规则')} 根因：{lesson.get('rootCause', '')}",
            f"预防：{lesson.get('preventionRule', '')}",
        ])
    wrapped = [piece for line in lines for piece in _wrap(str(line), 52)]
    width = 1800
    height = max(960, 230 + len(wrapped) * 54 + 90)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(46), _font(30), _font(23)
    draw.rectangle((0, 0, width, 24), fill=(163, 32, 32) if report.get("status") != "pass" else (23, 107, 69))
    draw.text((72, 62), title, fill=(24, 33, 43), font=title_font)
    banner = "已阻断：未通过前不生成或打开 CAD" if report.get("status") != "pass" else "审核通过"
    draw.rounded_rectangle((72, 145, width - 72, 225), radius=14, fill=(255, 239, 239) if report.get("status") != "pass" else (233, 248, 240), outline=(189, 83, 83) if report.get("status") != "pass" else (73, 145, 105), width=3)
    draw.text((100, 163), banner, fill=(138, 25, 25) if report.get("status") != "pass" else (23, 107, 69), font=body_font)
    y = 270
    for line in wrapped:
        draw.text((88, y), line, fill=(32, 42, 52), font=body_font)
        y += 54
    draw.text((88, height - 58), "完整证据请打开同名 .review.html；本 PNG 为白底、不透明摘要。", fill=(88, 100, 112), font=small_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def write_review_bundle(
    report: dict[str, Any],
    html_path: Path,
    png_path: Path | None = None,
    title: str = "AICAD 审核报告",
    review_launch: str = "never",
    *,
    opener: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    write_html(report, html_path, title)
    if png_path is not None:
        write_png(report, png_path, title)
    launch = _load_review_launcher()(html_path, review_launch, opener=opener)
    launch_json_path = _review_launch_json_path(html_path)
    launch_json_path.parent.mkdir(parents=True, exist_ok=True)
    launch_json_path.write_text(json.dumps(launch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "html": str(html_path.resolve()),
        "png": str(png_path.resolve()) if png_path else None,
        "launchJson": str(launch_json_path.resolve()),
        "reviewLaunch": launch,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a machine-readable AICAD validation report as a local UTF-8 HTML review and optional opaque PNG summary.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--png", type=Path)
    parser.add_argument("--title", default="AICAD 审核报告")
    parser.add_argument("--review-launch", choices=REVIEW_LAUNCH_MODES, default="never")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    result = write_review_bundle(report, args.html, args.png, args.title, args.review_launch)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
