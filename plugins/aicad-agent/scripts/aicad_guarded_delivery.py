from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from aicad_normality_prover import _write_markdown as write_normality_markdown  # noqa: E402
from aicad_normality_prover import evaluate as evaluate_normality  # noqa: E402
from aicad_normality_prover import load_and_compile  # noqa: E402
from aicad_requirement_conformance import EXPECTED_LOCKS  # noqa: E402
from aicad_requirement_conformance import evaluate as evaluate_requirements  # noqa: E402
from aicad_requirement_conformance import write_markdown as write_requirement_markdown  # noqa: E402


OUTPUT_KEYS = {
    "plan.json": "plan",
    "aicad": "execution",
    "scr": "script",
    "dxf": "dxf",
    "audit.md": "audit",
    "manifest.json": "manifest",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_set_sha(rows: list[dict[str, Any]]) -> str:
    portable = [
        {"kind": row["kind"], "sizeBytes": row["sizeBytes"], "sha256": row["sha256"]}
        for row in sorted(rows, key=lambda item: item["kind"])
    ]
    canonical = json.dumps(portable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _blocked_stage(number: int, name: str, upstream: str) -> dict[str, Any]:
    return {
        "stage": number,
        "name": name,
        "status": "blocked_by_previous_stage",
        "upstreamFailure": upstream,
        "nonCompensatory": True,
    }


def _write_delivery_markdown(report: dict[str, Any], target: Path) -> None:
    lines = [
        "# AICAD 受控输出流水线报告",
        "",
        f"- 总状态：**{report['status'].upper()}**",
        f"- 候选工件已构建：{'是' if report.get('candidateArtifactsBuilt') else '否'}",
        "- 顺序：整体需求一致 → 细节可靠性证明 → 确定性构建与哈希核验。",
        "",
        "## 不可跳级阶段",
        "",
    ]
    for row in report.get("stages", []):
        lines.append(f"- 阶段 {row['stage']}：{row['name']} — **{row['status'].upper()}**")
    lines.extend(["", "## 为什么这样阻断", ""])
    if report["status"] == "pass":
        lines.append("三个阶段均通过。候选工件是在整体要求和细节证明完成后才创建的。")
    else:
        lines.append(report.get("failureExplanation", "前级硬门禁失败，后级不得执行。"))
    if report.get("artifacts"):
        lines.extend(["", "## 候选工件与哈希", ""])
        for row in report["artifacts"]:
            lines.append(f"- {row['kind']}：{row['path']} — SHA-256 {row['sha256']}")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "这是一套候选输出硬门禁，不是量产、材料强度、加工设备公差或技术验收。可视化、真实 CAD 宿主重开和人工审阅仍按任务风险另设发布门禁。",
            "",
            "安全锁保持 reviewOnly=true、accepted=false、ruleEnabled=false、packagingGated=true。",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(
    contract_path: Path,
    trace_path: Path,
    plan_path: Path,
    geometry_path: Path,
    template_path: Path,
    instance_path: Path,
    output_dir: Path,
    report_dir: Path,
    name: str,
    compile_plan_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    report_dir = report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise ValueError(f"refusing to overwrite existing output directory: {output_dir}")

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    instance = json.loads(instance_path.read_text(encoding="utf-8"))

    requirement_report = evaluate_requirements(contract, trace, template, instance)
    requirement_json = report_dir / "requirement_conformance.json"
    requirement_md = report_dir / "requirement_conformance.md"
    _write_json(requirement_json, requirement_report)
    write_requirement_markdown(requirement_report, requirement_md)
    stage_one = {
        "stage": 1,
        "name": "overall_user_requirement_conformance",
        "status": requirement_report["status"],
        "reportJson": str(requirement_json),
        "reportMarkdown": str(requirement_md),
        "nonCompensatory": True,
    }
    if requirement_report["status"] != "pass":
        report = {
            "schema": "aicad_guarded_delivery_report_v1",
            "status": "failed",
            "candidateArtifactsBuilt": False,
            "stages": [
                stage_one,
                _blocked_stage(2, "detail_mathematical_reliability", stage_one["name"]),
                _blocked_stage(3, "deterministic_artifact_build_and_hash_audit", stage_one["name"]),
            ],
            "artifacts": [],
            "failureExplanation": (
                "整体要求尚未被证明一致，因此没有读取/编译几何，也没有创建候选 CAD。"
                "细节正确不能补偿产品或结构选错。"
            ),
            "ruleIds": ["PKG-G024", "PKG-G025"],
            "locks": EXPECTED_LOCKS,
        }
        return report

    plan = load_and_compile(plan_path)
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    normality_report = evaluate_normality(plan, geometry, template, instance)
    normality_json = report_dir / "detail_normality.json"
    normality_md = report_dir / "detail_normality.md"
    _write_json(normality_json, normality_report)
    write_normality_markdown(normality_report, normality_md)
    stage_two = {
        "stage": 2,
        "name": "detail_mathematical_reliability",
        "status": normality_report["status"],
        "reportJson": str(normality_json),
        "reportMarkdown": str(normality_md),
        "nonCompensatory": True,
    }
    if normality_report["status"] != "pass":
        return {
            "schema": "aicad_guarded_delivery_report_v1",
            "status": "failed",
            "candidateArtifactsBuilt": False,
            "stages": [
                stage_one,
                stage_two,
                _blocked_stage(3, "deterministic_artifact_build_and_hash_audit", stage_two["name"]),
            ],
            "artifacts": [],
            "failureExplanation": (
                "整体要求已匹配，但至少一个逐线、顶点、约束秩、闭环、功能面、功能公式或参数域细节失败，"
                "因此没有创建候选 CAD。"
            ),
            "ruleIds": ["PKG-G023", "PKG-G024", "PKG-G025"],
            "locks": EXPECTED_LOCKS,
        }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}.staging-", dir=output_dir.parent))
    try:
        if compile_plan_fn is None:
            # Import lazily so the MCP agent can expose this pipeline without a
            # circular import. Standalone CLI use still resolves the same
            # deterministic compiler at the only stage where artifacts may be
            # created.
            from aicad_agent import compile_plan_value as compile_plan_fn
        compile_result = compile_plan_fn(str(plan_path), str(staging), name)
        required_outputs = list(contract.get("requiredOutputs", []))
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        non_ascii_execution: list[str] = []
        for kind in required_outputs:
            result_key = OUTPUT_KEYS.get(kind)
            candidate_value = compile_result.get(result_key) if result_key else None
            candidate = Path(candidate_value) if candidate_value else None
            if candidate is None or not candidate.is_file():
                missing.append(kind)
                continue
            if kind in {"aicad", "scr"}:
                try:
                    candidate.read_text(encoding="ascii")
                except UnicodeDecodeError:
                    non_ascii_execution.append(kind)
            rows.append(
                {
                    "kind": kind,
                    "path": candidate.name,
                    "sizeBytes": candidate.stat().st_size,
                    "sha256": _sha256(candidate),
                }
            )
        manifest = json.loads(Path(compile_result["manifest"]).read_text(encoding="utf-8"))
        manifest_ok = (
            manifest.get("source_sha256") == compile_result.get("source_sha256")
            and manifest.get("entity_count") == compile_result.get("entity_count")
            and manifest.get("origin") == [0.0, 0.0]
        )
        stage_three_pass = not missing and not non_ascii_execution and manifest_ok
        stage_three = {
            "stage": 3,
            "name": "deterministic_artifact_build_and_hash_audit",
            "status": "pass" if stage_three_pass else "failed",
            "missingRequiredOutputs": missing,
            "nonAsciiExecutionChannels": non_ascii_execution,
            "manifestMatchesCompiledPlan": manifest_ok,
            "artifactSetSha256": _artifact_set_sha(rows),
            "nonCompensatory": True,
        }
        if not stage_three_pass:
            return {
                "schema": "aicad_guarded_delivery_report_v1",
                "status": "failed",
                "candidateArtifactsBuilt": False,
                "stages": [stage_one, stage_two, stage_three],
                "artifacts": [],
                "failureExplanation": (
                    "需求与细节证明通过，但候选工件集合不完整、执行通道含非 ASCII，或 manifest 与实际编译不一致；"
                    "临时构建已丢弃。"
                ),
                "ruleIds": ["PKG-G008", "PKG-G024", "PKG-G025"],
                "locks": EXPECTED_LOCKS,
            }
        staging.replace(output_dir)
        for row in rows:
            row["path"] = str((output_dir / row["path"]).resolve())
        return {
            "schema": "aicad_guarded_delivery_report_v1",
            "status": "pass",
            "candidateArtifactsBuilt": True,
            "outputDirectory": str(output_dir),
            "stages": [stage_one, stage_two, stage_three],
            "artifacts": rows,
            "artifactSetSha256": _artifact_set_sha(rows),
            "failureExplanation": "",
            "ruleIds": ["PKG-G008", "PKG-G023", "PKG-G024", "PKG-G025"],
            "postBuildReleaseGates": [
                "opaque original-resolution visual inspection when presentation matters",
                "real CAD host save/reopen when native DWG or persistence is required",
                "human engineering review for unmodeled manufacturing risks",
            ],
            "locks": EXPECTED_LOCKS,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run non-skippable whole-requirement, detail-normality and artifact-output gates in order"
    )
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        report = run_pipeline(
            args.contract,
            args.trace,
            args.plan,
            args.geometry,
            args.template,
            args.instance,
            args.out,
            args.report_dir,
            args.name,
        )
    except Exception as exc:
        report = {
            "schema": "aicad_guarded_delivery_report_v1",
            "status": "failed",
            "candidateArtifactsBuilt": False,
            "stages": [],
            "artifacts": [],
            "failureExplanation": f"流水线输入或构建异常：{exc}",
            "ruleIds": ["PKG-G024", "PKG-G025"],
            "locks": EXPECTED_LOCKS,
        }
    report_json = args.report_dir.resolve() / "guarded_delivery.json"
    report_md = args.report_dir.resolve() / "guarded_delivery.md"
    _write_json(report_json, report)
    _write_delivery_markdown(report, report_md)
    print(
        json.dumps(
            {
                "status": report["status"],
                "candidateArtifactsBuilt": report.get("candidateArtifactsBuilt", False),
                "outJson": str(report_json),
                "outMarkdown": str(report_md),
                "outputDirectory": report.get("outputDirectory"),
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
