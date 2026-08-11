from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

from .engine import PlanError


REVIEW_LAUNCH_MODES = ("auto", "always", "never")
_TRUE = {"1", "true", "yes", "on"}


def _environment_mode(requested: str) -> str:
    override = os.environ.get("AICAD_REVIEW_LAUNCH", "").strip().lower()
    if override:
        if override not in REVIEW_LAUNCH_MODES:
            raise PlanError("AICAD_REVIEW_LAUNCH must be auto, always, or never")
        return override
    return requested


def _headless_reason() -> str | None:
    if os.environ.get("AICAD_NO_GUI", "").strip().lower() in _TRUE:
        return "AICAD_NO_GUI"
    if os.environ.get("CI", "").strip().lower() in _TRUE:
        return "CI"
    if os.name != "nt" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return "no_desktop_display"
    return None


def _system_open(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_review(
    review_html: str | Path,
    mode: str = "auto",
    *,
    opener: Callable[[Path], None] | None = None,
) -> dict[str, object]:
    if mode not in REVIEW_LAUNCH_MODES:
        raise PlanError("review launch mode must be auto, always, or never")
    resolved_mode = _environment_mode(mode)
    path = Path(review_html).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".html":
        raise PlanError(f"review launch requires an existing local HTML file: {path}")
    if resolved_mode == "never":
        return {"status": "skipped", "mode": resolved_mode, "reason": "disabled", "review_html": str(path)}
    headless = _headless_reason()
    if resolved_mode == "auto" and headless:
        return {"status": "skipped", "mode": resolved_mode, "reason": headless, "review_html": str(path)}
    try:
        (opener or _system_open)(path)
    except OSError as exc:
        if resolved_mode == "always":
            raise PlanError(f"review UI launch failed: {exc}") from exc
        return {"status": "failed", "mode": resolved_mode, "reason": str(exc), "review_html": str(path)}
    return {"status": "launched", "mode": resolved_mode, "reason": None, "review_html": str(path)}
