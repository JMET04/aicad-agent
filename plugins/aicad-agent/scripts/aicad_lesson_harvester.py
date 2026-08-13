#!/usr/bin/env python3
"""Harvest failed checks into a deterministic, review-only lesson bundle."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for candidate in (PLUGIN_ROOT / "runtime" / "src", PLUGIN_ROOT.parent.parent / "src"):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from aicad.continuous_learning import (  # noqa: E402
    audit_lesson_bundle,
    controlled_learning_output_path,
    file_entry,
    harvest_lesson_bundle,
    resolve_output_path,
    safe_relative_path,
)
from aicad.reporting import ReportInvariantError  # noqa: E402


def _read_json(root: Path, relative: str) -> dict[str, object]:
    entry = file_entry(root, relative)
    return json.loads((root / entry["path"]).read_text(encoding="utf-8-sig"))


def _atomic_json(root: Path, relative: str, payload: object) -> None:
    destination = resolve_output_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = resolve_output_path(root, relative)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize failed tests/gates into deterministic review-only lesson events."
    )
    parser.add_argument("report", help="Safe-relative aicad_test_failure_report_v1 path")
    parser.add_argument("--root", required=True, type=Path, help="Explicit evidence root; relative inputs resolve here, never at process CWD")
    parser.add_argument("--existing", help="Optional safe-relative existing lesson bundle to merge")
    parser.add_argument("--output", required=True, help="Safe-relative output bundle path")
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        report = safe_relative_path(args.report)
        output = controlled_learning_output_path(args.output)
        if output == report:
            raise ReportInvariantError("lesson output must not overwrite its source failure report")
        existing = _read_json(root, safe_relative_path(args.existing)) if args.existing else None
        bundle = harvest_lesson_bundle(root, report, existing=existing)
        audit = audit_lesson_bundle(root, bundle)
        _atomic_json(root, output, bundle)
    except (OSError, UnicodeError, json.JSONDecodeError, ReportInvariantError) as exc:
        print(json.dumps({"ok": False, "status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "status": "pass",
                "output": output,
                "reportCount": audit["reportCount"],
                "failureCount": audit["failureCount"],
                "lessonCount": audit["lessonCount"],
                "authoritativeRulesModified": False,
                "installedPluginModified": False,
                "technicalPackageReady": False,
                "productionReleaseEligible": False,
                "manufacturingAuthorized": False,
                "fabricationAuthorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
