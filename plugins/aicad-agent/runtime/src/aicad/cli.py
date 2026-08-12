from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .engine import PlanError, compile_plan, load_and_compile
from .exporters import export_all
from .provider import generate_plan
from .settings import config_path, get_api_key, load_config, save_config, set_api_key


VERSION = "1.10.1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aicad", description="Origin-anchored, mathematically constrained AI CAD compiler")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate a UTF-8 JSON drawing plan")
    validate.add_argument("plan", type=Path)
    compile_command = subparsers.add_parser("compile", help="validate and generate AICAD/SCR/DXF/audit outputs")
    compile_command.add_argument("plan", type=Path)
    compile_command.add_argument("--out", type=Path, default=Path("build"))
    compile_command.add_argument("--name", help="output basename; defaults to input filename")

    natural = subparsers.add_parser("natural", help="convert a UTF-8 natural-language request into validated CAD artifacts")
    natural.add_argument("request_file", type=Path)
    natural.add_argument("--out", type=Path, required=True)
    natural.add_argument("--name", default="drawing")
    natural.add_argument("--provider", choices=["auto", "offline", "openai"])
    natural.add_argument("--result", type=Path, help="write a small UTF-8 status file for AutoLISP")

    doctor = subparsers.add_parser("doctor", help="report runtime and provider readiness")
    doctor.add_argument("--json", action="store_true")
    setup = subparsers.add_parser("setup", help="save provider settings; read API key from stdin")
    setup.add_argument("--provider", choices=["auto", "offline", "openai"], default="offline")
    setup.add_argument("--model", default="gpt-5.4-mini")
    setup.add_argument("--base-url", default="https://api.openai.com/v1")
    setup.add_argument("--api-key-stdin", action="store_true")
    subparsers.add_parser("setup-gui", help="open the secure provider setup window")
    return parser


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
    checks = {
        "windows": os.name == "nt",
        "python_supported": sys.version_info >= (3, 10),
        "config_directory_writable": False,
        "openai_key_configured": bool(get_api_key()),
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
    return {
        "version": VERSION, "ready_offline": all(checks[key] for key in ("windows", "python_supported", "config_directory_writable")),
        "ready_openai": all(checks.values()), "checks": checks,
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
        if args.command == "setup-gui":
            return _setup_gui()
        if args.command == "doctor":
            payload = _doctor_payload()
            if args.json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print(f"AICAD {VERSION}; offline={'READY' if payload['ready_offline'] else 'NOT READY'}; OpenAI={'READY' if payload['ready_openai'] else 'NOT CONFIGURED'}")
                print(f"Python: {payload['python']}")
                print(f"Config: {payload['config']}")
            return 0 if payload["ready_offline"] else 3
        if args.command == "setup":
            save_config({"provider": args.provider, "model": args.model, "base_url": args.base_url.rstrip("/")})
            if args.api_key_stdin:
                set_api_key(sys.stdin.readline().strip())
            print(json.dumps(str(config_path()), ensure_ascii=True))
            return 0
        if args.command == "natural":
            try:
                request = args.request_file.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as exc:
                raise PlanError(f"Cannot read UTF-8 request: {exc}") from exc
            provider = args.provider or str(load_config()["provider"])
            data, used_provider = generate_plan(request, provider)
            plan = compile_plan(data)
            args.out.mkdir(parents=True, exist_ok=True)
            source = args.out / f"{args.name}.plan.json"
            _atomic_text(source, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            outputs = export_all(plan, args.out, args.name)
            execution = args.out / f"{args.name}.aicad"
            _write_result(args.result, True, str(execution.resolve()), used_provider, len(plan.entities))
            print(json.dumps({"status": "ok", "provider": used_provider, "entities": len(plan.entities), "plan": str(source.resolve()), "execution": str(execution.resolve()), "outputs": [str(path.resolve()) for path in outputs]}, ensure_ascii=True))
            return 0

        plan = load_and_compile(args.plan)
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
