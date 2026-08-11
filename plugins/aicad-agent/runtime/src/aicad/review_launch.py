from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
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


def _needs_ascii_stage(path: Path) -> bool:
    forced = os.environ.get("AICAD_REVIEW_FORCE_STAGE", "").strip().lower() in _TRUE
    return forced or (os.name == "nt" and any(ord(character) > 127 for character in str(path)))


def _stage_review_for_compatibility(path: Path) -> Path:
    configured = os.environ.get("AICAD_REVIEW_STAGE_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        system_drive = Path(os.environ.get("SystemDrive", "C:"))
        public = Path(os.environ.get("PUBLIC") or (system_drive / "Users" / "Public"))
        root = public / "AICADReview"
    source_bytes = path.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()[:16]
    destination = root / digest / "review.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or destination.read_bytes() != source_bytes:
        shutil.copy2(path, destination)
    return destination.resolve()


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
        return {
            "status": "skipped",
            "mode": resolved_mode,
            "reason": "disabled",
            "review_html": str(path),
            "source_review_html": str(path),
            "staged_for_compatibility": False,
        }
    headless = _headless_reason()
    if resolved_mode == "auto" and headless:
        return {
            "status": "skipped",
            "mode": resolved_mode,
            "reason": headless,
            "review_html": str(path),
            "source_review_html": str(path),
            "staged_for_compatibility": False,
        }

    launch_path = _stage_review_for_compatibility(path) if _needs_ascii_stage(path) else path
    open_review = opener or _system_open
    try:
        open_review(launch_path)
    except OSError as first_error:
        if launch_path == path:
            try:
                launch_path = _stage_review_for_compatibility(path)
                open_review(launch_path)
            except OSError as second_error:
                message = f"direct launch failed: {first_error}; compatibility launch failed: {second_error}"
                if resolved_mode == "always":
                    raise PlanError(f"review UI launch failed: {message}") from second_error
                return {
                    "status": "failed",
                    "mode": resolved_mode,
                    "reason": message,
                    "review_html": str(launch_path),
                    "source_review_html": str(path),
                    "staged_for_compatibility": True,
                }
        else:
            if resolved_mode == "always":
                raise PlanError(f"review UI launch failed: {first_error}") from first_error
            return {
                "status": "failed",
                "mode": resolved_mode,
                "reason": str(first_error),
                "review_html": str(launch_path),
                "source_review_html": str(path),
                "staged_for_compatibility": True,
            }
    return {
        "status": "launched",
        "mode": resolved_mode,
        "reason": None,
        "review_html": str(launch_path),
        "source_review_html": str(path),
        "staged_for_compatibility": launch_path != path,
    }
