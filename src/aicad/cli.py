from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .civil import validate_civil_review_candidate
from .domain_maturity import assess_domain_registry
from .domain_rules import evaluate_domain_plan
from .engine import PlanError, compile_plan
from .experience import EXPECTED_LOCKS, recall_experience, validate_coverage_ledger
from .exporters import export_all
from .provider import generate_plan_with_usage
from .settings import config_path, get_api_key, load_config, save_config, set_api_key


VERSION = "1.17.0"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aicad", description="Origin-anchored, mathematically constrained AI CAD compiler")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate a UTF-8 JSON drawing plan")
    validate.add_argument("plan", type=Path)
    validate.add_argument("--evidence-root", type=Path)
    compile_command = subparsers.add_parser("compile", help="validate and generate AICAD/SCR/DXF/audit outputs")
    compile_command.add_argument("plan", type=Path)
    compile_command.add_argument("--evidence-root", type=Path)
    compile_command.add_argument("--out", type=Path, default=Path("build"))
    compile_command.add_argument("--name", help="output basename; defaults to input filename")

    natural = subparsers.add_parser("natural", help="convert a UTF-8 natural-language request into validated CAD artifacts")
    natural.add_argument("request_file", type=Path)
    natural.add_argument("--out", type=Path, required=True)
    natural.add_argument("--name", default="drawing")
    natural.add_argument("--provider", choices=["auto", "offline", "openai", "deepseek"])
    natural.add_argument("--result", type=Path, help="write a small UTF-8 status file for AutoLISP")

    doctor = subparsers.add_parser("doctor", help="report runtime and provider readiness")
    doctor.add_argument("--json", action="store_true")
    setup = subparsers.add_parser("setup", help="save provider settings; read API key from stdin")
    setup.add_argument("--provider", choices=["auto", "offline", "openai", "deepseek"], default="offline")
    setup.add_argument("--model")
    setup.add_argument("--base-url")
    setup.add_argument("--api-key-stdin", action="store_true")
    subparsers.add_parser("setup-gui", help="open the secure provider setup window")

    subparsers.add_parser("experience-context-schema", help="print the strict experience-recall context schema")
    subparsers.add_parser("review-coverage-schema", help="print the evidence-bearing review coverage schema")
    registry = subparsers.add_parser("domain-registry", help="print the controlled engineering domain registry")
    registry.add_argument("--rules-root", type=Path)
    subparsers.add_parser("civil-review-schema", help="print the source-bound civil review-candidate schema")
    civil_review = subparsers.add_parser("civil-review-validate", help="validate a civil review candidate against real evidence")
    civil_review.add_argument("candidate", type=Path)
    civil_review.add_argument("--evidence-root", type=Path)
    recall = subparsers.add_parser("experience-recall", help="recall authority-first rules before geometry")
    recall.add_argument("context", type=Path)
    recall.add_argument("--rules-root", type=Path)
    recall.add_argument("--max-cards", type=int, default=12)
    recall.add_argument("--candidate-lesson-bundle", action="append", type=Path, default=[])
    coverage = subparsers.add_parser("coverage-validate", help="validate exact coverage against real evidence files")
    coverage.add_argument("recall", type=Path)
    coverage.add_argument("ledger", type=Path)
    coverage.add_argument("--evidence-root", type=Path, required=True)
    return parser


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"Cannot read {label} JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PlanError(f"{label} must contain a JSON object")
    return value


def _asset_directory(
    directory_name: str,
    required_files: tuple[str, ...],
    *,
    explicit: Path | None = None,
) -> Path:
    if explicit is not None:
        candidates = [explicit]
    else:
        candidates: list[Path] = []
        for parent in Path(__file__).resolve().parents:
            candidates.extend(
                [
                    parent / directory_name,
                    parent / "agent-plugin" / "aicad-agent" / directory_name,
                ]
            )
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve(strict=True)
        except OSError:
            continue
        marker = os.path.normcase(str(resolved))
        if marker in seen:
            continue
        seen.add(marker)
        if resolved.is_dir() and all((resolved / name).is_file() for name in required_files):
            return resolved
    if explicit is not None:
        raise PlanError(f"Invalid controlled {directory_name} root: {explicit}")
    raise PlanError(f"Cannot locate packaged AICAD {directory_name} assets")


def _rules_root(value: Path | None = None) -> Path:
    return _asset_directory(
        "rules",
        (
            "experience_recall_catalog.json",
            "engineering_domain_registry.json",
            "normative_governance_rules.json",
        ),
        explicit=value,
    )


def _schema_path(filename: str) -> Path:
    return _asset_directory("schema", (filename,)) / filename


def _portable_cli_domain_gate(
    data: dict[str, object],
    *,
    evidence_root: Path | None = None,
) -> dict[str, object]:
    drawing = data.get("drawing")
    domain = (
        str(drawing.get("domain", "general"))
        if isinstance(drawing, dict)
        else "general"
    )
    if domain not in {"general", "civil"}:
        raise PlanError(
            f"portable CLI refuses specialist domain {domain!r}; use the AICAD agent "
            "workflow so its mandatory preflight/guarded-delivery validator cannot be bypassed"
        )
    specialist: dict[str, object] | None = None
    if domain == "civil":
        contract = data.get("civil_review_candidate")
        if not isinstance(contract, dict):
            raise PlanError("civil plans require an embedded civil_review_candidate")
        if evidence_root is None:
            raise PlanError("civil plans require a controlled evidence root")
        specialist = validate_civil_review_candidate(contract, evidence_root)
        if (
            specialist.get("status") != "review_candidate"
            or specialist.get("authorizedOutput") != "review_candidate"
        ):
            codes = [
                str(row.get("code"))
                for row in specialist.get("failures", [])
                if isinstance(row, dict)
            ]
            raise PlanError(
                "civil review-candidate gate failed: "
                + (", ".join(codes[:12]) or "candidate_not_ready")
            )
    report = evaluate_domain_plan(data, "2d", domain, specialist)
    if report.get("status") == "failed":
        failed = [
            str(row.get("id"))
            for row in report.get("checks", [])
            if isinstance(row, dict) and row.get("status") == "fail"
        ]
        raise PlanError("domain gate failed: " + (", ".join(failed) or "not_ready"))
    return {"domainValidation": report, "civilReviewValidation": specialist}


def _domain_registry_value(rules_root: Path) -> dict[str, object]:
    path = rules_root / "engineering_domain_registry.json"
    registry = _load_json_object(path, "engineering domain registry")
    if registry.get("schema") != "aicad_engineering_domain_registry_v1":
        raise PlanError("engineering domain registry schema is invalid")
    domains = registry.get("domains")
    if not isinstance(domains, dict) or not domains:
        raise PlanError("engineering domain registry has no domains")
    if registry.get("safetyLocks") != EXPECTED_LOCKS:
        raise PlanError("engineering domain registry safety locks are not exact")
    maturity = assess_domain_registry(registry, plugin_root=rules_root.parent)
    if not maturity["ok"]:
        raise PlanError(
            "engineering domain maturity verification failed: "
            + "; ".join(maturity["issues"][:12])
        )
    return {
        "ok": True,
        "registry": maturity["effectiveRegistry"],
        "maturityAssessment": {
            "ok": True, "issues": [], "domains": maturity["domains"]
        },
        "path": str(path.resolve()),
    }


def _atomic_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temporary)
    try:
        temp_path.write_text(text, encoding=encoding, newline="\n")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_result(path: Path | None, ok: bool, message_or_path: str, provider: str = "", count: int = 0) -> None:
    if path is None:
        return
    if ok:
        content = f"OK\n{message_or_path}\n{provider}\n{count}\n"
    else:
        safe = message_or_path.encode("ascii", "backslashreplace").decode("ascii").replace("\n", " ")
        content = f"ERROR\n{safe[:1000]}\n"
    _atomic_text(path, content)


def _doctor_payload() -> dict[str, object]:
    config = load_config()
    openai_key = bool(get_api_key("openai"))
    deepseek_key = bool(get_api_key("deepseek"))
    checks = {
        "windows": os.name == "nt",
        "python_supported": sys.version_info >= (3, 10),
        "config_directory_writable": False,
        "openai_key_configured": openai_key,
        "deepseek_key_configured": deepseek_key,
    }
    try:
        path = config_path().parent
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        checks["config_directory_writable"] = True
    except OSError:
        pass
    common_ready = all(checks[key] for key in ("windows", "python_supported", "config_directory_writable"))
    return {
        "version": VERSION,
        "ready_offline": common_ready,
        "ready_openai": common_ready and openai_key,
        "ready_deepseek": common_ready and deepseek_key,
        "checks": checks,
        "python": sys.executable, "python_version": platform.python_version(),
        "provider": config["provider"], "model": config["model"], "base_url": config["base_url"],
        "config": str(config_path()), "utc": datetime.now(timezone.utc).isoformat(),
    }


def _setup_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as exc:
        raise PlanError("Tkinter is not available in this Python installation") from exc
    config = load_config()
    root = tk.Tk()
    root.title("AI CAD Constraint - Provider Setup")
    root.resizable(False, False)
    fields: dict[str, tk.Entry] = {}
    labels = [("Model", "model"), ("Base URL", "base_url"), ("OpenAI API key", "api_key")]
    for row, (label, key) in enumerate(labels):
        tk.Label(root, text=label, anchor="w", width=18).grid(row=row, column=0, padx=10, pady=6, sticky="w")
        entry = tk.Entry(root, width=52, show="*" if key == "api_key" else "")
        if key != "api_key":
            entry.insert(0, str(config[key]))
        entry.grid(row=row, column=1, padx=10, pady=6)
        fields[key] = entry
    tk.Label(root, text="API key is stored in Windows Credential Manager, never in a file.", fg="#555555").grid(row=3, column=0, columnspan=2, padx=10, pady=5)

    def save() -> None:
        try:
            model, base_url, api_key = fields["model"].get().strip(), fields["base_url"].get().strip(), fields["api_key"].get().strip()
            if not model or not base_url.startswith(("https://", "http://")):
                raise ValueError("Model and a valid HTTP(S) base URL are required")
            # Keep the local default unless the user later explicitly selects an API provider.
            save_config({"provider": "offline", "model": model, "base_url": base_url.rstrip("/")})
            if api_key:
                set_api_key(api_key)
            messagebox.showinfo("AI CAD Constraint", "Settings saved. You may close this window and run AICAD_AI.")
        except Exception as exc:
            messagebox.showerror("AI CAD Constraint", str(exc))

    tk.Button(root, text="Save", width=16, command=save).grid(row=4, column=0, columnspan=2, pady=12)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "experience-context-schema":
            path = _schema_path("aicad-experience-context.schema.json")
            print(json.dumps({"ok": True, "schema": _load_json_object(path, "experience context schema"), "path": str(path.resolve())}, ensure_ascii=False))
            return 0
        if args.command == "review-coverage-schema":
            path = _schema_path("aicad-review-coverage-ledger.schema.json")
            print(json.dumps({"ok": True, "schema": _load_json_object(path, "review coverage schema"), "path": str(path.resolve())}, ensure_ascii=False))
            return 0
        if args.command == "domain-registry":
            print(json.dumps(_domain_registry_value(_rules_root(args.rules_root)), ensure_ascii=False))
            return 0
        if args.command == "civil-review-schema":
            path = _schema_path("aicad-civil-review-candidate.schema.json")
            print(json.dumps({"ok": True, "schema": _load_json_object(path, "civil review candidate schema"), "path": str(path.resolve())}, ensure_ascii=False))
            return 0
        if args.command == "civil-review-validate":
            candidate_path = args.candidate.expanduser().resolve(strict=True)
            candidate = _load_json_object(candidate_path, "civil review candidate")
            evidence_root = args.evidence_root or candidate_path.parent
            payload = validate_civil_review_candidate(candidate, evidence_root)
            payload = {"ok": payload.get("status") == "review_candidate", **payload}
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if payload["ok"] else 2
        if args.command == "experience-recall":
            rules_root = _rules_root(args.rules_root)
            context = _load_json_object(args.context, "experience recall context")
            payload = recall_experience(
                context,
                rules_root / "experience_recall_catalog.json",
                rules_root,
                max_cards=args.max_cards,
                candidate_lesson_bundles=args.candidate_lesson_bundle,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        if args.command == "coverage-validate":
            recalled = _load_json_object(args.recall, "experience recall result")
            ledger = _load_json_object(args.ledger, "review coverage ledger")
            payload = validate_coverage_ledger(
                recalled,
                ledger,
                evidence_root=args.evidence_root,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if payload["ok"] else 2

        if args.command == "setup-gui":
            return _setup_gui()
        if args.command == "doctor":
            payload = _doctor_payload()
            if args.json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print(f"AICAD {VERSION}; offline={'READY' if payload['ready_offline'] else 'NOT READY'}; OpenAI={'READY' if payload['ready_openai'] else 'NOT CONFIGURED'}; DeepSeek={'READY' if payload['ready_deepseek'] else 'NOT CONFIGURED'}")
                print(f"Python: {payload['python']}")
                print(f"Config: {payload['config']}")
            return 0 if payload["ready_offline"] else 3
        if args.command == "setup":
            default_model = "deepseek-v4-flash" if args.provider == "deepseek" else "gpt-5.4-mini"
            default_base = "https://api.deepseek.com" if args.provider == "deepseek" else "https://api.openai.com/v1"
            model = args.model or default_model
            base_url = (args.base_url or default_base).rstrip("/")
            save_config({"provider": args.provider, "model": model, "base_url": base_url})
            if args.api_key_stdin:
                if args.provider not in {"openai", "deepseek"}:
                    raise PlanError("--api-key-stdin requires provider openai or deepseek")
                set_api_key(sys.stdin.readline().strip(), args.provider)
            print(json.dumps(str(config_path()), ensure_ascii=True))
            return 0
        if args.command == "natural":
            try:
                request = args.request_file.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as exc:
                raise PlanError(f"Cannot read UTF-8 request: {exc}") from exc
            provider = args.provider or str(load_config()["provider"])
            generation = generate_plan_with_usage(request, provider)
            data = generation["plan"]
            used_provider = str(generation["provider"])
            _portable_cli_domain_gate(data)
            plan = compile_plan(data)
            args.out.mkdir(parents=True, exist_ok=True)
            source = args.out / f"{args.name}.plan.json"
            _atomic_text(source, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            outputs = export_all(plan, args.out, args.name)
            provider_run = args.out / f"{args.name}.provider-run.json"
            _atomic_text(provider_run, json.dumps(generation["runLedger"], ensure_ascii=False, indent=2) + "\n")
            execution = args.out / f"{args.name}.aicad"
            _write_result(args.result, True, str(execution.resolve()), used_provider, len(plan.entities))
            print(json.dumps({
                "status": "ok", "provider": used_provider, "model": generation["model"],
                "usage": generation["runLedger"]["usage"], "cost": generation["runLedger"]["cost"],
                "provider_run": str(provider_run.resolve()), "entities": len(plan.entities),
                "plan": str(source.resolve()), "execution": str(execution.resolve()),
                "outputs": [str(path.resolve()) for path in outputs],
            }, ensure_ascii=True))
            return 0

        plan_path = args.plan.expanduser().resolve(strict=True)
        data = _load_json_object(plan_path, "drawing plan")
        root = (
            args.evidence_root.expanduser().resolve(strict=True)
            if args.evidence_root is not None
            else plan_path.parent
        )
        _portable_cli_domain_gate(data, evidence_root=root)
        plan = compile_plan(data)
        if args.command == "validate":
            print(f"VALID: entities={len(plan.entities)}; origin=(0,0); sha256={plan.source_hash}")
            return 0
        stem = args.name or args.plan.name.removesuffix(".plan.json")
        outputs = export_all(plan, args.out, stem)
        print(f"COMPILED: entities={len(plan.entities)}")
        for output in outputs:
            print(json.dumps(str(output.resolve()), ensure_ascii=True))
        return 0
    except PlanError as exc:
        if "args" in locals() and getattr(args, "command", None) == "natural":
            _write_result(getattr(args, "result", None), False, str(exc))
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if "args" in locals() and getattr(args, "command", None) == "natural":
            _write_result(getattr(args, "result", None), False, f"Unexpected runtime error: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
