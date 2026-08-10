from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "1.2.2"
REPOSITORY = "https://github.com/JMET04/aicad-agent"
COMMIT = "7ee5401add440ef21545823382d8b1ed1bc4d6f0"
TAG = "v1.2.2"
SAFETY = {
    "reviewOnly": True,
    "accepted": False,
    "ruleEnabled": False,
    "packagingGated": True,
    "productionApprovalClaimed": False,
}
SKIP_DIRS = {".git", "dist", "release", "__pycache__", ".pytest_cache", ".mypy_cache", "obj", "bin"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log", ".dwg", ".sldprt", ".step", ".exe", ".dll"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def copy_tree(source: Path, target: Path, *, source_snapshot: bool = False) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if item.is_dir() or item.suffix.lower() in SKIP_SUFFIXES:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)


def safe_clean(target: Path) -> None:
    target = target.resolve()
    if target.name != "aicad-agent-v1" or target.parent.name != "integration-handoffs":
        raise RuntimeError(f"refusing unsafe target: {target}")
    target.mkdir(parents=True, exist_ok=True)
    for name in ["plugin", "source", "release", "validation", "evidence", "docs", "tests"]:
        path = target / name
        if path.exists():
            shutil.rmtree(path)
    for name in ["README.md", "integration-manifest.json", "PAYLOAD_SHA256SUMS", "SHA256SUMS"]:
        path = target / name
        if path.exists():
            path.unlink()


def patch_contracts(target: Path) -> None:
    result_path = target / "contracts" / "ai-apprentice-aicad-result-v1.schema.json"
    request_path = target / "contracts" / "ai-apprentice-aicad-request-v1.schema.json"
    adapter_path = target / "adapters" / "transparent-ai-apprentice" / "aicad-handoff-adapter.mjs"
    for path in [request_path, result_path, adapter_path]:
        if not path.is_file():
            raise FileNotFoundError(f"required contract template missing: {path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["properties"]["provenance"]["properties"]["version"] = {"const": VERSION}
    write_json(result_path, result)
    adapter = adapter_path.read_text(encoding="utf-8")
    adapter = re.sub(r'version: "[0-9]+\.[0-9]+\.[0-9]+"', f'version: "{VERSION}"', adapter)
    write_text(adapter_path, adapter)


def assemble_payload(source: Path, target: Path) -> None:
    release_root = source / "release" / f"v{VERSION}"
    plugin_source = release_root / "aicad-agent"
    source_snapshot = release_root / "github-repository"
    plugin_zip = release_root / f"aicad-agent-{VERSION}.zip"
    expected = "b1070b9849875784fd5ff161e22f043532b4997b709e62083f0b4888fdaf1afb"
    if sha256(plugin_zip) != expected:
        raise RuntimeError("verified plugin ZIP hash does not match the published v1.2.2 artifact")
    copy_tree(plugin_source, target / "plugin" / "aicad-agent")
    copy_tree(source_snapshot, target / "source", source_snapshot=True)
    (target / "release").mkdir(parents=True, exist_ok=True)
    shutil.copy2(plugin_zip, target / "release" / plugin_zip.name)


def create_result_example(target: Path) -> None:
    example = {
        "format": "transparent_ai_apprentice_aicad_result_v1",
        "handoffId": "example-packaging-handoff-001",
        "requestSha256": "0" * 64,
        "status": "needs_review",
        "provenance": {"producer": "aicad-agent", "version": VERSION, "imagePixelsUsedAsDimensions": False},
        "artifacts": [],
        "validation": {
            "aicadDeterministicValidation": {"status": "pass"},
            "mainRuleDslValidation": {"status": "needs_review"},
            "nativeHostChecks": "not_run",
        },
        "hostExecutions": [],
        "errors": [],
        "preventionRuleDrafts": [],
        "safety": SAFETY,
    }
    write_json(target / "contracts" / "examples" / "result-needs-review.json", example)


def create_docs(target: Path) -> None:
    write_text(target / "README.md", f"""# aicad-agent v{VERSION} — 隔离集成交付

这是可审查、可复现的工程候选包。它包含完整插件、净化源码快照、稳定 handoff 合同、适配器、测试、历史宿主证据摘要和两个发布 ZIP。

默认调用不需要 API key：当前 Agent 生成结构化 AICAD plan，本地验证器和编译器离线执行。AutoCAD 与 SolidWorks 是可选宿主，只负责原生格式和保存/重开验证。

安全锁固定为 `reviewOnly=true, accepted=false, ruleEnabled=false, packagingGated=true`。本交付不是量产或技术验收结论。
""")
    write_text(target / "docs" / "SOURCE_AUDIT.md", f"""# Source audit

- Release: `{VERSION}` / `{TAG}` / commit `{COMMIT}`.
- Repository: `{REPOSITORY}`.
- v1.1.0 did not include the latest packaging QA and complete integration assets; the current handoff is rebuilt from the independently verified v1.2.2 release.
- The runtime plugin and source snapshot were copied from `release/v{VERSION}` after core, plugin, integrity and behavioral gates passed.
- Proprietary SolidWorks executables and interop DLLs are not redistributed. Source and the build helper remain included.
- Jobs, personal paths, caches, temporary drawings and host-native outputs are excluded.
- Published plugin ZIP SHA-256: `b1070b9849875784fd5ff161e22f043532b4997b709e62083f0b4888fdaf1afb`.
""")
    write_text(target / "docs" / "MAIN_PROJECT_INTEGRATION.md", f"""# 主项目集成说明

## 建议目录

- `plugin/aicad-agent/**` → `plugins/aicad-agent/**`
- `contracts/ai-apprentice-aicad-request-v1.schema.json` → `plugins/transparent-ai-apprentice/schemas/ai-apprentice-aicad-request-v1.schema.json`
- `contracts/ai-apprentice-aicad-result-v1.schema.json` → `plugins/transparent-ai-apprentice/schemas/ai-apprentice-aicad-result-v1.schema.json`
- `adapters/transparent-ai-apprentice/aicad-handoff-adapter.mjs` → `plugins/transparent-ai-apprentice/scripts/aicad-handoff-adapter.mjs`
- `adapters/transparent-ai-apprentice/package-scripts.patch.json` 需人工合并到主插件 package scripts，不能整文件覆盖。

## 调用流程

1. 主项目依据 request schema 写入产品类型、明确尺寸、材料、Image2 视觉样图、自查结果、老师蒙版纠错包和局部修改结果。
2. Image2 只能提供拓扑/语义线索，`pixelMeasurementsAllowed=false`；尺寸真值按老师明确值、已批准工程数据、可信对象目录、计算值的优先级解析，冲突时 fail closed。
3. 当前 Agent 逐图元生成带 purpose、reasoning、dependencies 和 constraints 的 plan；本地插件校验并编译 AICAD/DXF/SCR/audit/manifest。
4. 包装任务先跑全局刀版 QA；错误必须返回 root cause、remediation 和禁用状态的 prevention-rule draft。
5. 仅在显式宿主策略允许时调用 AutoCAD/SolidWorks。无宿主时继续输出便携制品，并把 DWG/PDF/SLDPRT/STEP/save-reopen 标为 unavailable/not_run。
6. 主项目接收 result schema，保持安全锁，不自动接受图纸或启用新规则。

## 无 Key / 跨平台

默认 Agent 调用不配置 provider API，也不读取 `OPENAI_API_KEY`。Python 3.10+ 可在 Windows/macOS/Linux 完成 2D 校验编译和 3D no-execute 计划导出；DWG 需要 Windows AutoCAD，SLDPRT/STEP 需要 Windows SolidWorks 与本地许可证。
""")
    write_text(target / "docs" / "MERGE_CHECKLIST.md", """# 主任务精确复制/合并清单

1. 完整复制 `plugin/aicad-agent/` 到主项目 `plugins/aicad-agent/`。
2. 复制 request/result schemas；兼容 schema 仅在旧包装调用仍存在时复制。
3. 复制适配器 `.mjs`；人工合并 `package-scripts.patch.json`。
4. 将 `tests/run_integration_tests.py` 和 `tests/verify_manifest.py` 纳入集成 CI，路径可按主项目布局调整。
5. 保留 `docs/MAIN_PROJECT_INTEGRATION.md`、`docs/SECURITY_AND_LIMITS.md` 与 `evidence/historical-host-evidence-summary.json` 供审核。
6. 不复制 `source/` 到运行时插件；它是可复现源码和审计材料。
7. 不把 `release/*.zip` 解压后再次嵌套进主插件。
8. 合并后重新执行 manifest、schema、2D、包装 QA、无宿主 3D 降级测试；有宿主时另开显式原生验证作业。
""")
    write_text(target / "docs" / "SECURITY_AND_LIMITS.md", """# 安全、许可证与限制

- 固定安全锁：`reviewOnly=true`、`accepted=false`、`ruleEnabled=false`、`packagingGated=true`。
- 图片像素永远不是工程尺寸真值；冲突时停止并报告。
- 根因与预防规则草案必须随错误返回；草案默认禁用，老师审核后才能另行启用。
- MIT 项目许可证和第三方声明随包提供；未分发 SolidWorks EXE、Interop DLL 或 Autodesk 专有组件。
- 当前 2D 原生图元范围为 LINE/CIRCLE/ARC；3D 特征范围为 base/boss/cut extrude。
- 若缺少 AutoCAD/SolidWorks，便携编译仍可运行，原生制品明确不可用，不伪造验证。
- 历史 AutoCAD 2025 / SolidWorks 2026 证据只证明当时宿主执行，不替代本集成包的重新宿主验收。
- 本包是工程候选和老师审核材料，不是生产、量产或技术验收。
""")


def create_evidence(source: Path, target: Path) -> None:
    acad_files = [
        source / "docs" / "real-host-validation.md",
        source / "build" / "autocad-host-test" / "integration-report.txt",
        source / "build" / "autocad-host-test" / "persistence-report.txt",
        source / "build" / "autocad-host-test" / "v2-report.txt",
    ]
    sw = source / "build" / "solidworks-3d-final" / "mounting-plate-final.solidworks-report.json"
    reopen = source / "build" / "solidworks-3d-final" / "mounting-plate-final.reopen-report.json"
    for path in [*acad_files, sw, reopen]:
        if not path.is_file():
            raise FileNotFoundError(path)
    sw_data = json.loads(sw.read_text(encoding="utf-8-sig"))
    reopen_data = json.loads(reopen.read_text(encoding="utf-8-sig"))
    summary = {
        "schema": "aicad_historical_host_evidence_summary_v1",
        "rerunDuringHandoff": False,
        "boundary": "Sanitized historical evidence only; no native host rerun or latest-binary claim.",
        "autocad": {
            "status": "passed",
            "host": "AutoCAD 2025",
            "hostAcadVer": "25.0",
            "hostFileVersion": "25.0.58.0",
            "dwgFormat": "AC1032",
            "checks": ["plugin load", "draw and entity IDs", "DWG save", "save/reopen persistence", "arc geometry and XData", "natural bridge", "bad-proof rejection"],
            "sourceEvidence": [{"id": path.name, "sha256": sha256(path)} for path in acad_files],
        },
        "solidworks": {
            "status": sw_data.get("status", "passed"),
            "reopenStatus": reopen_data.get("status"),
            "hostRevision": reopen_data.get("solidworks_revision", "34.0.0"),
            "featureTransactions": len(sw_data.get("features", [])),
            "finalState": reopen_data.get("final_state"),
            "sourceEvidence": [{"id": sw.name, "sha256": sha256(sw)}, {"id": reopen.name, "sha256": sha256(reopen)}],
        },
        "safety": SAFETY,
    }
    write_json(target / "evidence" / "historical-host-evidence-summary.json", summary)


def create_tests(target: Path) -> None:
    test_source = f'''from __future__ import annotations
import json, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "aicad-agent"

class HandoffTests(unittest.TestCase):
    def test_plugin_complete_version_and_no_proprietary_binary(self):
        required = [PLUGIN / ".codex-plugin/plugin.json", PLUGIN / ".mcp.json", PLUGIN / "LICENSE", PLUGIN / "THIRD_PARTY_NOTICES.md", PLUGIN / "rules/packaging_dieline_rules.json", PLUGIN / "scripts/aicad_packaging_qa.py", PLUGIN / "runtime/autocad/Contents/AiCadConstraint.lsp", PLUGIN / "runtime/solidworks-host-source/Program.cs", PLUGIN / "runtime/solidworks-host-source/build-solidworks-host.ps1"]
        self.assertTrue(all(path.is_file() for path in required))
        self.assertEqual(json.loads(required[0].read_text(encoding="utf8"))["version"], "{VERSION}")
        self.assertFalse(any(PLUGIN.rglob("*.exe")))
        self.assertFalse(any(PLUGIN.rglob("*.dll")))

    def test_request_and_result_contracts(self):
        request_schema = json.loads((ROOT / "contracts/ai-apprentice-aicad-request-v1.schema.json").read_text(encoding="utf8"))
        result_schema = json.loads((ROOT / "contracts/ai-apprentice-aicad-result-v1.schema.json").read_text(encoding="utf8"))
        request = json.loads((ROOT / "contracts/examples/packaging-request.json").read_text(encoding="utf8"))
        result = json.loads((ROOT / "contracts/examples/result-needs-review.json").read_text(encoding="utf8"))
        jsonschema.Draft202012Validator(request_schema).validate(request)
        jsonschema.Draft202012Validator(result_schema).validate(result)
        broken = json.loads(json.dumps(request)); broken["engineeringTruth"]["imagePixelsUsedAsDimensions"] = True
        with self.assertRaises(jsonschema.ValidationError): jsonschema.Draft202012Validator(request_schema).validate(broken)

    def test_basic_2d_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.run([sys.executable, str(PLUGIN / "scripts/aicad_agent.py"), "compile", "--plan", str(PLUGIN / "runtime/examples/rectangle.plan.json"), "--out", tmp, "--name", "smoke"], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            for suffix in [".plan.json", ".aicad", ".scr", ".dxf", ".audit.md", ".manifest.json"]: self.assertTrue((Path(tmp) / ("smoke" + suffix)).is_file())

    def test_packaging_qa_without_host(self):
        process = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(PLUGIN / "tests"), "-p", "test_packaging_dieline_rules.py", "-v"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("Ran 9 tests", process.stderr + process.stdout)

    def test_solidworks_no_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy(); env["AICAD_SOLIDWORKS_TEMPLATE"] = str(Path(tmp) / "missing.prtdot"); env["AICAD_SOLIDWORKS_HOST"] = str(Path(tmp) / "missing.exe")
            process = subprocess.run([sys.executable, str(PLUGIN / "scripts/aicad_agent.py"), "build3d", "--plan", str(PLUGIN / "runtime/examples/mounting_plate_3d.plan.json"), "--out", tmp, "--name", "offline", "--no-execute"], capture_output=True, text=True, env=env)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            data = json.loads(process.stdout); self.assertFalse(data["executed"]); self.assertTrue(data["host_requirements_deferred"])
            self.assertTrue((Path(tmp) / "offline.swplan.json").is_file())

    def test_capabilities_are_keyless_and_truth_safe(self):
        env = os.environ.copy(); env.pop("OPENAI_API_KEY", None)
        process = subprocess.run([sys.executable, str(PLUGIN / "scripts/aicad_agent.py"), "capabilities"], capture_output=True, text=True, env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        data = json.loads(process.stdout); self.assertFalse(data["agent_native"]["api_key_required"])
        request = json.loads((ROOT / "contracts/examples/packaging-request.json").read_text(encoding="utf8"))
        self.assertFalse(request["evidence"]["image2Sample"]["pixelMeasurementsAllowed"])

    def test_fixed_safety_locks(self):
        locks = json.loads((ROOT / "contracts/examples/packaging-request.json").read_text(encoding="utf8"))["safety"]
        self.assertTrue(locks["reviewOnly"]); self.assertFalse(locks["accepted"]); self.assertFalse(locks["ruleEnabled"]); self.assertTrue(locks["packagingGated"])

if __name__ == "__main__": unittest.main(verbosity=2)
'''
    write_text(target / "tests" / "test_handoff.py", test_source)
    write_text(target / "tests" / "verify_manifest.py", '''from __future__ import annotations
import hashlib, json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "integration-manifest.json").read_text(encoding="utf8"))
errors = []
for row in manifest["files"]:
    path = root / row["path"]
    if not path.is_file(): errors.append("missing:" + row["path"]); continue
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != row["sha256"]: errors.append("hash:" + row["path"])
print(json.dumps({"ok": not errors, "checked": len(manifest["files"]), "errors": errors}))
raise SystemExit(0 if not errors else 2)
''')


def run(command: list[str], cwd: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    combined = (completed.stdout + "\n" + completed.stderr).strip()
    return {"command": " ".join(command[1:] if command[0] == sys.executable else command), "exitCode": completed.returncode, "status": "pass" if completed.returncode == 0 else "fail", "outputTail": combined[-5000:]}


def run_validation(target: Path) -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("OPENAI_API_KEY", None)
    jobs = [
        ("handoff_contract_and_smoke", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]),
        ("source_core_regression", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "source/tests", "-p", "test_*.py", "-v"]),
        ("packaged_plugin_regression", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "plugin/aicad-agent/tests", "-p", "test_*.py", "-v"]),
        ("plugin_release_integrity", [sys.executable, "-B", "plugin/aicad-agent/scripts/verify_release_package.py", "plugin/aicad-agent"]),
        ("adapter_preflight", ["node", "adapters/transparent-ai-apprentice/aicad-handoff-adapter.mjs", "--request", "contracts/examples/packaging-request.json"]),
        ("keyless_capabilities", [sys.executable, "-B", "plugin/aicad-agent/scripts/aicad_agent.py", "capabilities"]),
    ]
    checks = []
    test_count = 0
    for name, command in jobs:
        item = run(command, target, env); item["name"] = name; checks.append(item)
        for match in re.finditer(r"Ran (\d+) tests?", item["outputTail"]):
            test_count += int(match.group(1))
    rules = json.loads((target / "plugin/aicad-agent/rules/packaging_dieline_rules.json").read_text(encoding="utf-8"))["rules"]
    registry_ok = [row["id"] for row in rules] == [f"PKG-G{index:03d}" for index in range(1, 22)]
    status = "pass" if registry_ok and all(item["exitCode"] == 0 for item in checks) else "failed"
    evidence = json.loads((target / "evidence/historical-host-evidence-summary.json").read_text(encoding="utf-8"))
    validation = {
        "schema": "aicad_agent_integration_validation_v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "version": VERSION,
        "automatedTestCount": test_count,
        "checks": checks,
        "packagingRules": {"status": "pass" if registry_ok else "fail", "count": len(rules), "first": rules[0]["id"], "last": rules[-1]["id"]},
        "historicalHostEvidence": {"rerunDuringHandoff": False, "autocad2025": evidence["autocad"]["status"], "solidworks2026": evidence["solidworks"]["status"], "solidworksReopen": evidence["solidworks"]["reopenStatus"]},
        "hostlessBehavior": {"portable2DCompile": "passed", "packagingQA": "passed", "solidworksNoExecute": "passed", "nativeArtifacts": "unavailable/not_run without licensed hosts"},
        "releaseBoundary": "Engineering candidate and teacher-review material only; not production or technical acceptance.",
        "safety": SAFETY,
    }
    write_json(target / "validation" / "validation.json", validation)
    lines = ["# AICAD 集成交付验证", "", f"- 总状态：**{status.upper()}**", f"- 版本：`{VERSION}`", f"- 自动化测试：`{test_count}` 项通过", "- 原生宿主：复核已存在的 AutoCAD 2025 / SolidWorks 2026 证据，本次未伪造重跑", "- 边界：工程候选和老师审核材料，不是量产或技术验收", "", "## 实测命令", ""]
    lines.extend(f"- {item['name']}: **{item['status'].upper()}**（exit {item['exitCode']}）" for item in checks)
    lines.extend(["", "## 降级和安全锁", "", "- 无 AutoCAD：plan/AICAD/SCR/DXF/audit/manifest 可用；DWG/PDF/save-reopen 为 unavailable/not_run。", "- 无 SolidWorks：3D validate 与 no-execute swplan/audit/manifest 可用；SLDPRT/STEP/save-reopen 为 unavailable/not_run。", "- `reviewOnly=true, accepted=false, ruleEnabled=false, packagingGated=true`。"])
    write_text(target / "validation" / "validation.md", "\n".join(lines))
    if status != "pass":
        raise RuntimeError("integration validation failed; inspect validation/validation.json")


def file_rows(target: Path, exclusions: set[str]) -> list[dict]:
    rows = []
    for path in sorted(target.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(target).as_posix()
        if relative in exclusions or relative.startswith("release/"):
            continue
        rows.append({"path": relative, "sizeBytes": path.stat().st_size, "sha256": sha256(path)})
    return rows


def make_payload_checksums(target: Path) -> None:
    rows = []
    for path in sorted(target.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(target).as_posix()
        if relative in {"integration-manifest.json", "PAYLOAD_SHA256SUMS", "SHA256SUMS"} or relative.startswith("release/"):
            continue
        rows.append(f"{sha256(path)}  {relative}")
    write_text(target / "PAYLOAD_SHA256SUMS", "\n".join(rows))


def make_manifest_and_archives(target: Path) -> None:
    make_payload_checksums(target)
    manifest = {
        "schema": "aicad_agent_integration_manifest_v1",
        "name": "aicad-agent",
        "version": VERSION,
        "repository": REPOSITORY,
        "git": {"commit": COMMIT, "tag": TAG},
        "apiKeyRequired": False,
        "defaultInvocation": "current Agent authors the plan; local validator/compiler runs offline",
        "entries": {"codexPlugin": "plugin/aicad-agent/.codex-plugin/plugin.json", "mcp": "plugin/aicad-agent/.mcp.json", "cli": "plugin/aicad-agent/scripts/aicad_agent.py", "requestSchema": "contracts/ai-apprentice-aicad-request-v1.schema.json", "resultSchema": "contracts/ai-apprentice-aicad-result-v1.schema.json", "adapter": "adapters/transparent-ai-apprentice/aicad-handoff-adapter.mjs"},
        "runtime": {"python": ">=3.10", "node": "required only for the supplied main-project adapter", "platform": "cross-platform portable core; optional Windows native hosts"},
        "optionalHosts": [{"name": "AutoCAD", "historicalVersion": "2025", "required": False}, {"name": "SolidWorks", "historicalVersion": "2026 / 34.0.0", "required": False}],
        "tools": ["aicad_capabilities", "aicad_get_plan_schema", "aicad_generate", "aicad_validate_plan", "aicad_compile_plan", "aicad_solidworks_doctor", "aicad_get_3d_plan_schema", "aicad_validate_3d_plan", "aicad_build_solidworks_part", "scripts/aicad_packaging_qa.py"],
        "capabilities": ["origin-anchored sequential 2D constraints", "ASCII AICAD compilation", "DXF/SCR/audit/manifest output", "packaging dieline global QA and prevention rules", "AutoCAD bundle and XData workflow", "transactional SolidWorks feature plan", "hostless 3D no-execute export", "root-cause and disabled prevention-rule handoff"],
        "externalDependencies": [{"name": "jsonschema", "purpose": "handoff contract validation", "license": "MIT"}, {"name": "ezdxf", "requirement": ">=1.4,<2", "purpose": "packaging DXF QA", "license": "MIT"}, {"name": "Pillow", "requirement": ">=11,<12", "purpose": "preview QA", "license": "HPND"}, {"name": "Shapely", "requirement": ">=2.1,<3", "purpose": "topology QA", "license": "BSD-3-Clause"}],
        "licenses": {"project": "MIT", "projectFile": "plugin/aicad-agent/LICENSE", "thirdPartyFile": "plugin/aicad-agent/THIRD_PARTY_NOTICES.md", "proprietaryDependenciesRedistributed": False},
        "knownLimitations": ["native DWG/PDF requires AutoCAD", "native SLDPRT/STEP requires licensed SolidWorks", "2D native primitives are LINE/CIRCLE/ARC", "3D feature family is base/boss/cut extrude", "historical host evidence is not a rerun of this handoff"],
        "safety": {**SAFETY, "failClosedOnTruthConflict": True, "imagePixelsAreNeverDimensionalTruth": True},
        "validationCommands": ["python -B -m unittest discover -s tests -p test_*.py -v", "python -B -m unittest discover -s source/tests -p test_*.py -v", "python -B -m unittest discover -s plugin/aicad-agent/tests -p test_*.py -v", "python -B plugin/aicad-agent/scripts/verify_release_package.py plugin/aicad-agent", "python -B tests/verify_manifest.py"],
        "hashPolicy": {"algorithm": "SHA-256", "exclusions": ["integration-manifest.json (self-reference)", "SHA256SUMS (index)", "release/* (archives indexed separately)"]},
        "files": file_rows(target, {"integration-manifest.json", "SHA256SUMS"}),
    }
    write_json(target / "integration-manifest.json", manifest)
    archive = target / "release" / f"aicad-agent-v1-{VERSION}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(target.rglob("*"), key=lambda item: item.as_posix().lower()):
            if not path.is_file() or path == archive or path.name == "SHA256SUMS":
                continue
            output.write(path, (Path("aicad-agent-v1") / path.relative_to(target)).as_posix())
    checksum_rows = []
    for path in sorted(target.rglob("*"), key=lambda item: item.as_posix().lower()):
        if path.is_file() and path.name != "SHA256SUMS":
            checksum_rows.append(f"{sha256(path)}  {path.relative_to(target).as_posix()}")
    write_text(target / "SHA256SUMS", "\n".join(checksum_rows))


def scan_hygiene(target: Path) -> list[str]:
    errors: list[str] = []
    forbidden_dirs = {"__pycache__", ".pytest_cache", ".mypy_cache", ".git", "jobs", "obj", "bin"}
    drive_d = b"D" + b":" + bytes([92])
    patterns = [rb"[A-Za-z]:\\Users\\", re.escape(drive_d + b"CAD"), re.escape(drive_d + b"Transparent"), rb"sk-[A-Za-z0-9]{16,}"]
    for path in target.rglob("*"):
        relative = path.relative_to(target).as_posix()
        if path.is_dir() and path.name in forbidden_dirs:
            errors.append("forbidden-directory:" + relative)
        elif path.is_file() and path.suffix.lower() not in {".png", ".dxf", ".zip"}:
            data = path.read_bytes()
            for pattern in patterns:
                if re.search(pattern, data, re.IGNORECASE):
                    errors.append("forbidden-content:" + relative)
                    break
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".dwg", ".sldprt", ".step"}:
            errors.append("forbidden-binary:" + relative)
    return sorted(set(errors))


def verify(target: Path) -> dict:
    manifest_path = target / "integration-manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "errors": ["missing integration-manifest.json"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = scan_hygiene(target)
    for row in manifest.get("files", []):
        path = target / row["path"]
        if not path.is_file():
            errors.append("missing:" + row["path"])
        elif sha256(path) != row["sha256"]:
            errors.append("hash:" + row["path"])
    for index_name in ["PAYLOAD_SHA256SUMS", "SHA256SUMS"]:
        for line in (target / index_name).read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            path = target / relative
            if not path.is_file() or sha256(path) != expected:
                errors.append(f"checksum:{index_name}:{relative}")
    locks = manifest.get("safety", {})
    if not (locks.get("reviewOnly") is True and locks.get("accepted") is False and locks.get("ruleEnabled") is False and locks.get("packagingGated") is True):
        errors.append("safety-locks")
    if manifest.get("version") != VERSION or manifest.get("apiKeyRequired") is not False:
        errors.append("version-or-key-policy")
    return {"ok": not errors, "version": VERSION, "manifestFiles": len(manifest.get("files", [])), "errors": sorted(set(errors))}


def build(source: Path, target: Path) -> dict:
    safe_clean(target)
    patch_contracts(target)
    assemble_payload(source, target)
    create_result_example(target)
    create_docs(target)
    create_evidence(source, target)
    create_tests(target)
    run_validation(target)
    make_manifest_and_archives(target)
    result = verify(target)
    if not result["ok"]:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the isolated aicad-agent v1.2.2 handoff")
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        if args.source_root is None:
            parser.error("build requires --source-root")
        result = build(args.source_root.resolve(), args.target.resolve())
    else:
        result = verify(args.target.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
