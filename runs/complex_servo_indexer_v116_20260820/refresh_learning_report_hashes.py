from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORTS = [
    ROOT / "learning" / "review-handoff-cli-invocation" / "reports" / "failures.json",
]


def refreshed(entry: dict[str, object]) -> dict[str, object]:
    relative = str(entry["path"])
    path = ROOT / relative
    raw = path.read_bytes()
    return {"path": relative, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def build() -> None:
    for report_path in REPORTS:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for failure in report["failedChecks"]:
            failure["reproducer"] = refreshed(failure["reproducer"])
            for closure_name in ("evidenceClosure", "sourceInputClosure", "affectedArtifactClosure"):
                closure = failure[closure_name]
                closure["entries"] = [refreshed(row) for row in closure["entries"]]
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    build()
