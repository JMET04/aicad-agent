from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine import PlanError
from .manufacturing_validation import validate_manufacturing_release_package
from .manufacturing_workflow import (
    build_manufacturing_release_package,
    validate_manufacturing_release_review_html,
)
from .review_launch import launch_review


def _load_value(value: Any) -> tuple[dict[str, Any], Path | None]:
    if isinstance(value, dict):
        return value, None
    if not isinstance(value, str) or not value.strip():
        raise PlanError("manufacturing release package must be an object, JSON string, or UTF-8 file path")
    text = value.strip()
    source: Path | None = None
    if len(text) < 2048:
        candidate = Path(text).expanduser()
        if candidate.is_file():
            source = candidate.resolve()
            try:
                text = source.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise PlanError(f"cannot read manufacturing release package: {source}") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"manufacturing release package is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PlanError("manufacturing release package JSON root must be an object")
    return document, source


def validate_manufacturing_release_value(
    value: Any, evidence_root: str | Path | None = None
) -> dict[str, Any]:
    document, source = _load_value(value)
    root = Path(evidence_root).expanduser() if evidence_root else (source.parent if source else None)
    report = validate_manufacturing_release_package(document, root)
    return {"ok": bool(report["factoryRfqCandidateReady"] or report["prototypeFabricationCandidateReady"]), **report}


def build_manufacturing_release_value(
    value: Any,
    evidence_root: str | Path | None,
    output_dir: str | Path | None,
    name: str = "manufacturing-release",
    review_launch: str = "never",
) -> dict[str, Any]:
    if output_dir is None or not str(output_dir).strip():
        raise PlanError("manufacturing release build requires an explicit fresh output_dir")
    document, source = _load_value(value)
    root = Path(evidence_root).expanduser() if evidence_root else (source.parent if source else None)
    result = build_manufacturing_release_package(document, root, output_dir, name)
    review_path = Path(result["reviewHtml"])
    review_contract = validate_manufacturing_release_review_html(
        review_path.read_text(encoding="utf-8")
    )
    result["reviewContract"] = review_contract
    result["reviewLaunch"] = launch_review(review_path, review_launch)
    return result


def open_manufacturing_release_review_value(
    review_html: str | Path, review_launch: str = "always"
) -> dict[str, Any]:
    path = Path(review_html).expanduser().resolve()
    if not path.is_file() or path.suffix.casefold() != ".html":
        raise PlanError(f"manufacturing release review requires an existing local HTML file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanError(f"manufacturing release review is not readable UTF-8: {path}") from exc
    contract = validate_manufacturing_release_review_html(text)
    return {
        "ok": True,
        "candidateReviewerMayOpen": True,
        "factoryHandoffReadyClaimedByOpen": False,
        "productionReady": False,
        "reviewContract": contract,
        "reviewLaunch": launch_review(path, review_launch),
    }
