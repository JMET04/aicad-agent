from __future__ import annotations

import copy
import html
import json
import re
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .engine import PlanError
from .manufacturing_release import (
    FACTORY_MANIFEST_SCHEMA,
    _SAFE_NAME,
    _atomic_text,
)
from .manufacturing_validation import validate_manufacturing_release_package


def _portable_url(value: Any, review_base: Path, evidence_root: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        path = Path(value).resolve(strict=True)
        path.relative_to(evidence_root)
        relative = os.path.relpath(path, review_base)
    except (OSError, ValueError):
        return None
    portable = Path(relative).as_posix()
    if portable.startswith("/") or re.match(r"^[A-Za-z]:", portable):
        return None
    return quote(portable, safe="/-._~")


def _public_review_report(report: dict[str, Any], review_base: Path) -> dict[str, Any]:
    root_value = report.get("evidenceRoot")
    if not isinstance(root_value, str):
        raise PlanError("package-specific reviewer requires a controlled evidence root")
    evidence_root = Path(root_value).resolve(strict=True)
    public = copy.deepcopy(report)
    originals = [row for row in report.get("reviewSubjects", []) if isinstance(row, dict)]
    exported = [row for row in public.get("reviewSubjects", []) if isinstance(row, dict)]
    for source_subject, target_subject in zip(originals, exported):
        for source, target in zip(source_subject.get("previews", []), target_subject.get("previews", [])):
            if isinstance(source, dict) and isinstance(target, dict):
                target["reviewSrc"] = _portable_url(source.get("resolvedPath"), review_base, evidence_root)
                target["reviewHref"] = _portable_url(source.get("targetResolvedPath"), review_base, evidence_root)
        for source, target in zip(source_subject.get("links", []), target_subject.get("links", [])):
            if isinstance(source, dict) and isinstance(target, dict):
                target["reviewHref"] = _portable_url(source.get("resolvedPath"), review_base, evidence_root)

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: scrub(item)
                for key, item in value.items()
                if key not in {"resolvedPath", "targetResolvedPath", "evidenceRoot"}
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(public)


def _subject_panel(subject: dict[str, Any], view: str) -> str:
    subject_key = html.escape(str(subject.get("subjectKey", "unknown")), quote=True)
    title = html.escape(
        f"{subject.get('subjectType', 'subject')} · {subject.get('subjectId', 'unknown')} · {subject.get('revision', 'unknown')}"
    )
    previews: list[str] = []
    for preview in subject.get("previews", []):
        if not isinstance(preview, dict) or preview.get("view") != view:
            continue
        src = preview.get("reviewSrc")
        href = preview.get("reviewHref")
        if not (
            preview.get("pass") is True
            and preview.get("sourceBindingPass") is True
            and preview.get("targetPass") is True
            and src
            and href
        ):
            previews.append(
                '<div class="preview-missing annotation-box" data-text-box="true">'
                + html.escape(str(preview.get("role", "preview")))
                + " · BLOCKED：缺少真实且哈希绑定的预览</div>"
            )
            continue
        role = html.escape(str(preview.get("role", "preview")), quote=True)
        preview_sha = html.escape(str(preview.get("sha256", "")), quote=True)
        source_sha = html.escape(str(preview.get("targetSha256", "")), quote=True)
        previews.append(
            f'<a class="actual-preview-card" href="{html.escape(href, quote=True)}" '
            f'data-preview-role="{role}" data-preview-sha256="{preview_sha}" '
            f'data-source-sha256="{source_sha}" data-subject-key="{subject_key}">'
            f'<img class="actual-preview" src="{html.escape(src, quote=True)}" '
            f'alt="{role} actual hash-bound preview" loading="lazy">'
            f'<span class="annotation-box" data-text-box="true"><b>{role}</b>'
            f'<small>preview {preview_sha[:12]}… · source {source_sha[:12]}…</small></span></a>'
        )
    links: list[str] = []
    for link in subject.get("links", []):
        if not isinstance(link, dict) or link.get("pass") is not True:
            continue
        href = link.get("reviewHref")
        if href is None:
            continue
        role = html.escape(str(link.get("role", "artifact")))
        digest = html.escape(str(link.get("sha256", "")), quote=True)
        links.append(
            f'<a class="artifact-link annotation-box" data-text-box="true" '
            f'data-artifact-sha256="{digest}" href="{html.escape(href, quote=True)}">'
            f'<span>{role}</span><b>{digest[:12]}…</b></a>'
        )
    if not previews:
        previews.append(
            '<div class="preview-missing annotation-box" data-text-box="true">'
            "BLOCKED：该视图没有受控真实预览</div>"
        )
    return (
        f'<article class="subject-card" data-subject-key="{subject_key}" data-subject-view="{view}">'
        f'<h3 class="annotation-box" data-text-box="true">{title}</h3>'
        f'<div class="preview-grid">{"".join(previews)}</div>'
        f'<details><summary class="annotation-box" data-text-box="true">哈希绑定的 CAD / PDF / CAM 文件</summary>'
        f'<div class="artifact-list">{"".join(links)}</div></details></article>'
    )


def render_manufacturing_release_review(
    report: dict[str, Any], review_base: str | Path | None = None
) -> str:
    base = Path(review_base).expanduser().resolve() if review_base else Path(str(report.get("evidenceRoot", "."))).resolve()
    public_report = _public_review_report(report, base)
    report = public_report
    handoff = report.get("factoryHandoffReady") is True
    digital = report.get("digitalPackageReady") is True
    partial = (
        not digital
        and (
            report.get("factoryRfqCandidateReady") is True
            or report.get("prototypeFabricationCandidateReady") is True
        )
    )
    state = (
        "FACTORY HANDOFF CANDIDATE" if handoff
        else "DIGITAL MANUFACTURING CANDIDATE" if digital
        else "PARTIAL DIGITAL CANDIDATE" if partial
        else "BLOCKED — REVIEW ONLY"
    )
    state_class = "ready" if (digital or handoff) else "partial" if partial else "blocked"
    subjects = [row for row in report.get("reviewSubjects", []) if isinstance(row, dict)]
    two_d = "".join(_subject_panel(subject, "2d") for subject in subjects)
    three_d = "".join(_subject_panel(subject, "3d") for subject in subjects)
    blockers = [
        *(("digital", row) for row in report.get("failures", []) if isinstance(row, dict)),
        *(("handoff", row) for row in report.get("handoffFailures", []) if isinstance(row, dict)),
    ]
    blocker_rows = "".join(
        "<tr>"
        f'<td><span class="annotation-box" data-text-box="true">{html.escape(stage)}</span></td>'
        f'<td><span class="annotation-box" data-text-box="true">{html.escape(str(row.get("code", "unknown")))}</span></td>'
        f'<td><span class="annotation-box" data-text-box="true">{html.escape(str(row.get("location", "")))}</span></td>'
        f'<td><span class="annotation-box" data-text-box="true">{html.escape(str(row.get("message", "")))}</span></td>'
        f'<td><span class="annotation-box" data-text-box="true">{html.escape(str(row.get("repair", "")))}</span></td>'
        "</tr>"
        for stage, row in blockers
    ) or '<tr><td colspan="5"><span class="annotation-box" data-text-box="true">数字闭包无阻断；外部签审锁仍按状态显示。</span></td></tr>'
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    expected = int(counts.get("actualPreviewsExpected", 0) or 0)
    verified = int(counts.get("actualPreviewsVerified", 0) or 0)
    embedded = html.escape(json.dumps(public_report, ensure_ascii=False), quote=False)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AICAD package-specific manufacturing review</title>
<style>
:root{{--ink:#17242d;--paper:#f3efe6;--panel:#fffdfa;--accent:#176477;--danger:#9f3026;--ok:#277249;--hair:#b9b2a5}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 "Segoe UI","Microsoft YaHei",sans-serif;overflow-wrap:anywhere}}
header{{padding:20px 26px;background:#132a35;color:#fff;display:flex;gap:18px;justify-content:space-between;align-items:center}}
h1{{font-size:20px;margin:0}}.status,.annotation-box{{border:1px solid #778b94;background:#fffdf8;padding:7px 9px;max-width:100%;overflow:hidden;overflow-wrap:anywhere}}
.status{{border-width:2px;background:transparent;font-weight:800}}.status.ready{{color:#bfe8cd}}.status.partial{{color:#ffe0a3}}.status.blocked{{color:#ffd0ca}}
.warning{{margin:16px 22px;border:2px solid #d28a13;background:#fff1cf;padding:11px 13px;font-weight:700}}
.tabs{{display:flex;gap:8px;margin:0 22px 12px}}button{{padding:9px 13px;border:1px solid #70818a;background:white;font-weight:700;cursor:pointer}}button[aria-selected="true"]{{background:var(--accent);color:white}}
.view{{display:none;padding:0 22px 22px}}.view.active{{display:block}}.subject-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:14px}}
.subject-card{{background:var(--panel);border:1px solid var(--hair);padding:12px;box-shadow:0 4px 14px #26343c12;min-width:0}}.subject-card h3{{margin:0 0 10px}}
.preview-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:9px}}.actual-preview-card{{display:grid;grid-template-rows:minmax(170px,1fr) auto;color:#174f63;text-decoration:none;border:2px solid #526c78;background:white;min-width:0}}
.actual-preview{{width:100%;height:240px;object-fit:contain;background:#eef1ef;border-bottom:1px solid #91a0a6}}.actual-preview-card .annotation-box{{display:grid;gap:3px;border:0;border-top:1px solid #91a0a6}}.actual-preview-card small{{font-family:Consolas,monospace}}
.preview-missing{{border-color:var(--danger);color:var(--danger);min-height:80px}}details{{margin-top:10px}}summary{{cursor:pointer;font-weight:700}}.artifact-list{{display:grid;gap:6px;margin-top:7px}}.artifact-link{{display:flex;justify-content:space-between;gap:8px;color:#174f63;text-decoration:none}}
.line-grammar-legend{{margin:0 22px 16px;background:var(--panel);border:1px solid var(--hair);padding:10px;display:flex;gap:12px;flex-wrap:wrap}}.line-swatch{{width:70px;height:12px;display:inline-block}}.line-outline{{border-top:4px solid #142934}}.line-visible{{border-top:2px solid #215269}}.line-hidden{{border-top:1px dashed #647681}}.line-center{{border-top:1px dashed #a54922}}.line-dimension{{border-top:1px solid #176b82}}
.blockers{{margin:0 22px 26px;background:var(--panel);border:1px solid var(--hair);padding:12px;overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #c6c2b8;padding:6px;vertical-align:top}}td .annotation-box{{display:block}}
.locks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:7px;margin:0 22px 14px}}.lock{{border:1px solid var(--hair);background:white;padding:8px}}.lock b{{display:block}}
@media(max-width:600px){{header{{align-items:flex-start;flex-direction:column}}.tabs,.view,.warning,.locks,.blockers,.line-grammar-legend{{margin-left:8px;margin-right:8px}}.view{{padding-left:8px;padding-right:8px}}}}
</style></head>
<body data-artifact-role="manufacturing_release_candidate_reviewer" data-review-only="true" data-accepted="false" data-production-ready="false" data-tool-steel-cut-authorized="false" data-mass-production-authorized="false" data-factory-handoff-ready="{str(handoff).lower()}" data-actual-preview-expected="{expected}" data-actual-preview-verified="{verified}">
<header><div><h1>AICAD 包级制造审查器</h1><div>Package {html.escape(str(report.get('packageId', 'unknown')))} · Revision {html.escape(str(report.get('releaseRevision', 'unknown')))}</div></div><div class="status {state_class}">{state}</div></header>
<div class="warning">真实图纸/模型预览与源文件均按 SHA-256 绑定。审查器本身不等于签章、采购授权、开钢或量产放行；productionReady=false。</div>
<div class="locks"><div class="lock">factoryRfqCandidateReady<b>{str(report.get('factoryRfqCandidateReady') is True).lower()}</b></div><div class="lock">prototypeFabricationCandidateReady<b>{str(report.get('prototypeFabricationCandidateReady') is True).lower()}</b></div><div class="lock">factoryHandoffReady<b>{str(handoff).lower()}</b></div><div class="lock">toolSteelCut / massProduction<b>false / false</b></div></div>
<div class="line-grammar-legend" data-legend-only="true"><span class="annotation-box" data-text-box="true"><i class="line-swatch line-outline"></i>轮廓粗实线</span><span class="annotation-box" data-text-box="true"><i class="line-swatch line-visible"></i>可见中实线</span><span class="annotation-box" data-text-box="true"><i class="line-swatch line-hidden"></i>隐藏虚线</span><span class="annotation-box" data-text-box="true"><i class="line-swatch line-center"></i>中心点划线</span><span class="annotation-box" data-text-box="true"><i class="line-swatch line-dimension"></i>尺寸细实线</span></div>
<div class="tabs" role="tablist" aria-label="actual 2D and 3D package review"><button type="button" data-view-target="view2d" aria-selected="true">真实 2D 图纸 / PCB</button><button type="button" data-view-target="view3d" aria-selected="false">真实 3D 模型 / 装配</button></div>
<section id="view2d" class="view active" data-view-mode="2d"><div class="subject-grid">{two_d}</div></section>
<section id="view3d" class="view" data-view-mode="3d"><div class="subject-grid">{three_d}</div></section>
<section class="blockers"><h2 class="annotation-box" data-text-box="true">阻断项与逐项修复</h2><table><thead><tr><th>门</th><th>代码</th><th>位置</th><th>问题</th><th>修复</th></tr></thead><tbody>{blocker_rows}</tbody></table></section>
<script type="application/json" id="aicad-manufacturing-release-report">{embedded}</script>
<script>document.querySelectorAll('[data-view-target]').forEach(button=>button.addEventListener('click',()=>{{document.querySelectorAll('[data-view-target]').forEach(x=>x.setAttribute('aria-selected',String(x===button)));document.querySelectorAll('.view').forEach(view=>view.classList.toggle('active',view.id===button.dataset.viewTarget));}}));</script>
</body></html>"""


def validate_manufacturing_release_review_html(text: str) -> dict[str, Any]:
    required = {
        "candidate reviewer role": 'data-artifact-role="manufacturing_release_candidate_reviewer"',
        "review-only lock": 'data-review-only="true"',
        "accepted=false lock": 'data-accepted="false"',
        "production-ready=false lock": 'data-production-ready="false"',
        "tool steel false lock": 'data-tool-steel-cut-authorized="false"',
        "mass production false lock": 'data-mass-production-authorized="false"',
        "2D actual entry": 'data-view-mode="2d"',
        "3D actual entry": 'data-view-mode="3d"',
        "actual preview element": 'class="actual-preview"',
        "actual preview card": 'class="actual-preview-card"',
        "source hash binding": 'data-source-sha256="',
        "preview hash binding": 'data-preview-sha256="',
        "artifact hash binding": 'data-artifact-sha256="',
        "legend only marker": 'data-legend-only="true"',
        "outline lineweight": ".line-outline{border-top:4px solid #142934}",
        "hidden linetype": ".line-hidden{border-top:1px dashed #647681}",
        "center linetype": ".line-center{border-top:1px dashed #a54922}",
        "framed text": 'data-text-box="true"',
        "overflow containment": "overflow-wrap:anywhere",
        "external signoff warning": "productionReady=false",
    }
    missing = [label for label, marker in required.items() if marker not in text]
    if missing:
        raise PlanError(
            "manufacturing release review contract is incomplete: " + ", ".join(missing)
        )
    if (
        'data-production-ready="true"' in text
        or 'data-accepted="true"' in text
        or 'data-tool-steel-cut-authorized="true"' in text
        or 'data-mass-production-authorized="true"' in text
    ):
        raise PlanError("manufacturing candidate reviewer may not claim production/tooling acceptance")
    if 'class="cad-sheet"' in text or 'aria-label="2D manufacturing line grammar"' in text:
        raise PlanError("generic line-grammar artwork may not substitute for package previews")
    match = re.search(
        r'<script type="application/json" id="aicad-manufacturing-release-report">(.*?)</script>',
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise PlanError("manufacturing reviewer has no embedded validation report")
    try:
        report = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise PlanError("manufacturing reviewer embedded report is invalid JSON") from exc
    subjects = [row for row in report.get("reviewSubjects", []) if isinstance(row, dict)]
    expected = int(report.get("counts", {}).get("actualPreviewsExpected", 0) or 0)
    verified = int(report.get("counts", {}).get("actualPreviewsVerified", 0) or 0)
    actual = text.count('<img class="actual-preview"')
    actual_cards = text.count('<a class="actual-preview-card"')
    subject_cards = text.count('<article class="subject-card"')
    if actual != verified or actual_cards != verified:
        raise PlanError(
            f"review actual-preview DOM closure mismatch: expected verified={verified}, images={actual}, cards={actual_cards}"
        )
    if subject_cards != len(subjects) * 2:
        raise PlanError(
            f"review subject/tab closure mismatch: subjects={len(subjects)}, cards={subject_cards}"
        )
    for subject in subjects:
        subject_key = str(subject.get("subjectKey", ""))
        for preview in subject.get("previews", []):
            if not isinstance(preview, dict) or not (
                preview.get("pass") is True
                and preview.get("sourceBindingPass") is True
                and preview.get("targetPass") is True
            ):
                continue
            src = preview.get("reviewSrc")
            href = preview.get("reviewHref")
            markers = [
                f'src="{html.escape(str(src), quote=True)}"',
                f'href="{html.escape(str(href), quote=True)}"',
                f'data-preview-sha256="{html.escape(str(preview.get("sha256", "")), quote=True)}"',
                f'data-source-sha256="{html.escape(str(preview.get("targetSha256", "")), quote=True)}"',
            ]
            if src is None or href is None or any(marker not in text for marker in markers):
                raise PlanError("review preview/link is not bound to a verified artifact URI and hash")
            for url in (src, href):
                if (
                    not isinstance(url, str)
                    or not url
                    or "file:" in url.casefold()
                    or "\\" in url
                    or url.startswith("/")
                    or re.match(r"^[A-Za-z]:", url)
                ):
                    raise PlanError("review artifact URL is absolute, machine-bound, or non-portable")
            if f'data-subject-key="{html.escape(subject_key, quote=True)}"' not in text:
                raise PlanError("review preview is not bound to its exact package subject")
        for link in subject.get("links", []):
            if not isinstance(link, dict) or link.get("pass") is not True:
                continue
            href = link.get("reviewHref")
            if not isinstance(href, str) or not href or "file:" in href.casefold() or "\\" in href or href.startswith("/") or re.match(r"^[A-Za-z]:", href):
                raise PlanError("review artifact link is absolute, machine-bound, or non-portable")
    full_candidate = report.get("digitalPackageReady") is True
    if full_candidate and (expected == 0 or expected != verified):
        raise PlanError("full digital manufacturing candidate lacks exact actual-preview closure")
    if "file://" in text.casefold() or re.search(r"[A-Za-z]:[/\\\\]", text):
        raise PlanError("reviewer leaks an absolute filesystem path")
    return {
        "contract": "aicad_manufacturing_release_candidate_reviewer_v2",
        "reviewOnly": True,
        "accepted": False,
        "productionReady": False,
        "has2dEntry": True,
        "has3dEntry": True,
        "lineGrammarLegendOnly": True,
        "annotationsFramed": True,
        "subjectCount": len(subjects),
        "actualPreviewExpected": expected,
        "actualPreviewVerified": verified,
        "actualPreviewRendered": actual,
        "actualPreviewClosurePass": expected == verified == actual,
    }


def write_manufacturing_release_review(report: dict[str, Any], output: str | Path) -> Path:
    target = Path(output).expanduser().resolve()
    page = render_manufacturing_release_review(report, target.parent)
    validate_manufacturing_release_review_html(page)
    _atomic_text(target, page)
    return target


def build_manufacturing_release_package(
    package: Any,
    evidence_root: str | Path | None,
    output_dir: str | Path,
    name: str = "manufacturing-release",
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve()
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise PlanError(
            "manufacturing release build output must be a new or empty directory; stale ready manifests are forbidden"
        )
    directory.mkdir(parents=True, exist_ok=True)
    stem = _SAFE_NAME.sub("-", name.strip()).strip("-_")[:64] or "manufacturing-release"
    report = validate_manufacturing_release_package(package, evidence_root)
    validation_path = directory / f"{stem}.validation.json"
    review_path = directory / f"{stem}.review.html"
    portable_validation = _public_review_report(report, directory)
    _atomic_text(
        validation_path, json.dumps(portable_validation, ensure_ascii=False, indent=2) + "\n"
    )
    write_manufacturing_release_review(report, review_path)
    files = [validation_path, review_path]
    candidate_ready = (
        report.get("factoryRfqCandidateReady") is True
        or report.get("prototypeFabricationCandidateReady") is True
    )
    if candidate_ready:
        candidate_locations = set(report.get("candidateArtifactLocations", []))
        candidate_artifacts = [
            {
                "location": row["location"],
                "kind": row["kind"],
                "path": row["path"],
                "size": row["actualSize"],
                "sha256": row["actualSha256"],
            }
            for row in sorted(report["artifacts"], key=lambda item: item["location"].casefold())
            if row.get("pass") and row.get("location") in candidate_locations
        ]
        candidate_manifest = {
            "schema": "aicad_digital_manufacturing_candidate_manifest_v1",
            "packageId": report["packageId"],
            "releaseRevision": report["releaseRevision"],
            "factoryRfqCandidateReady": report["factoryRfqCandidateReady"],
            "prototypeFabricationCandidateReady": report["prototypeFabricationCandidateReady"],
            "digitalPackageReady": report["digitalPackageReady"],
            "factoryHandoffReady": False,
            "artifactClosureSha256": report["artifactClosureSha256"],
            "domainArtifactClosureSha256": report["domainArtifactClosureSha256"],
            "artifacts": candidate_artifacts,
            "productionReady": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
            "externalProfessionalSignoffRequired": True,
        }
        candidate_path = directory / f"{stem}.digital-manufacturing-candidate.json"
        _atomic_text(candidate_path, json.dumps(candidate_manifest, ensure_ascii=False, indent=2) + "\n")
        files.append(candidate_path)
    if report["factoryHandoffReady"]:
        artifacts = [
            {
                "location": row["location"],
                "kind": row["kind"],
                "path": row["path"],
                "size": row["actualSize"],
                "sha256": row["actualSha256"],
            }
            for row in sorted(
                [*report["artifacts"], *report["confirmationArtifacts"]],
                key=lambda item: item["location"].casefold(),
            )
        ]
        manifest = {
            "schema": FACTORY_MANIFEST_SCHEMA,
            "packageId": report["packageId"],
            "releaseRevision": report["releaseRevision"],
            "factoryHandoffReady": True,
            "artifactClosureSha256": report["handoffArtifactClosureSha256"],
            "digitalArtifactClosureSha256": report["artifactClosureSha256"],
            "artifacts": artifacts,
            "productionReady": False,
            "productionReleaseAuthorized": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
            "externalProfessionalSignoffRequired": True,
            "safetyLocks": report["safetyLocks"],
        }
        manifest_path = directory / f"{stem}.factory-handoff-candidate.json"
        _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        files.append(manifest_path)
    if not report["factoryHandoffReady"]:
        blockers = {
            "schema": "aicad_manufacturing_release_blockers_v1",
            "packageId": report.get("packageId"),
            "factoryRfqCandidateReady": report["factoryRfqCandidateReady"],
            "prototypeFabricationCandidateReady": report["prototypeFabricationCandidateReady"],
            "digitalPackageReady": report["digitalPackageReady"],
            "factoryHandoffReady": False,
            "productionReady": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
            "candidateReviewerMayOpen": True,
            "failures": report["failures"],
            "handoffFailures": report["handoffFailures"],
            "requiredActions": report["requiredActions"],
            "handoffRequiredActions": report["handoffRequiredActions"],
        }
        blocker_path = directory / f"{stem}.blockers.json"
        _atomic_text(blocker_path, json.dumps(blockers, ensure_ascii=False, indent=2) + "\n")
        files.append(blocker_path)
    return {
        "ok": candidate_ready,
        "status": report["status"],
        "factoryRfqCandidateReady": report["factoryRfqCandidateReady"],
        "prototypeFabricationCandidateReady": report["prototypeFabricationCandidateReady"],
        "digitalPackageReady": report["digitalPackageReady"],
        "factoryHandoffReady": report["factoryHandoffReady"],
        "productionReady": False,
        "externalProfessionalSignoffRequired": True,
        "artifactDisposition": report["artifactDisposition"],
        "artifactClosureSha256": report["artifactClosureSha256"],
        "handoffArtifactClosureSha256": report["handoffArtifactClosureSha256"],
        "validation": report,
        "reviewHtml": str(review_path),
        "files": [str(path) for path in files],
    }
