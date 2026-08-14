from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import re
import sys
import time
from typing import Callable

from .engine import PlanError


REVIEW_LAUNCH_MODES = ("auto", "stage", "always", "never")
REVIEW_REQUEST_MODES = ("auto", "always")
NATIVE_CAD_SUFFIXES = frozenset({
    ".aicad", ".dwg", ".dxf", ".kicad_pcb", ".kicad_pro", ".kicad_sch",
    ".sldasm", ".sldprt", ".step", ".stp",
})
_MODIFIER_ROLE = re.compile(r"data-artifact-role\s*=\s*['\"]interactive_drawing_modifier['\"]", re.IGNORECASE)
_CAD_VIEW = re.compile(r"<svg\b[^>]*class\s*=\s*['\"][^'\"]*\bcad-view\b[^'\"]*['\"]", re.IGNORECASE)
_VIEW_HIT = re.compile(r"class\s*=\s*['\"][^'\"]*\bview-hit\b[^'\"]*['\"]", re.IGNORECASE)
_SOURCE_ID = re.compile(r"data-source-id\s*=", re.IGNORECASE)
_SOURCE_SUBOBJECT = re.compile(r"data-source-subobject\s*=", re.IGNORECASE)
_VIEW_ENTITY_ID = re.compile(r"data-view-entity-id\s*=", re.IGNORECASE)
_SEMANTIC_CATALOG = re.compile(r"aicad-semantic-entity-catalog|selection_map", re.IGNORECASE)
_MEASUREMENT_SURFACE = re.compile(r"measurement-card|metric-card", re.IGNORECASE)
_CORRECTION_SURFACE = re.compile(r"formalCorrection|data-correction-contract\s*=", re.IGNORECASE)
_REVIEW_ONLY = re.compile(r"reviewOnly\s*[:=]\s*true", re.IGNORECASE)
_NOT_ACCEPTED = re.compile(r"accepted\s*[:=]\s*false", re.IGNORECASE)
_RASTER_IMAGE = re.compile(r"<img\b", re.IGNORECASE)
_VECTOR_SOURCE_BOUND = re.compile(r"data-vector-source-bound\s*=\s*['\"]true['\"]", re.IGNORECASE)
_RASTER_ONLY_FALSE = re.compile(r"data-raster-only\s*=\s*['\"]false['\"]", re.IGNORECASE)

_TRUE = {"1", "true", "yes", "on"}
_DEFAULT_AUTO_DEDUP_SECONDS = 300.0


def _environment_mode(requested: str) -> str:
    override = os.environ.get("AICAD_REVIEW_LAUNCH", "").strip().lower()
    if override:
        if override not in REVIEW_LAUNCH_MODES:
            raise PlanError("AICAD_REVIEW_LAUNCH must be auto, stage, always, or never")
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


def _review_stage_root() -> Path:
    configured = os.environ.get("AICAD_REVIEW_STAGE_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        system_drive = Path(os.environ.get("SystemDrive", "C:"))
        public = Path(os.environ.get("PUBLIC") or (system_drive / "Users" / "Public"))
        root = public / "AICADReview"
    return root.resolve()


def _stage_review_for_compatibility(path: Path) -> Path:
    root = _review_stage_root()
    source_bytes = path.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()[:16]
    destination = root / digest / "review.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != destination.resolve() and (
        not destination.is_file() or destination.read_bytes() != source_bytes
    ):
        shutil.copy2(path, destination)
    return destination.resolve()


def _dedup_seconds() -> float:
    raw = os.environ.get("AICAD_REVIEW_AUTO_DEDUP_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_AUTO_DEDUP_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise PlanError("AICAD_REVIEW_AUTO_DEDUP_SECONDS must be a non-negative number") from exc
    if value < 0:
        raise PlanError("AICAD_REVIEW_AUTO_DEDUP_SECONDS must be a non-negative number")
    return value


def _launch_state_path() -> Path:
    configured = os.environ.get("AICAD_REVIEW_LAUNCH_STATE", "").strip()
    return Path(configured).expanduser().resolve() if configured else _review_stage_root() / "launch-state.json"


def _load_launch_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_launch_state(path: Path, digest: str, review_html: Path, mode: str) -> bool:
    payload = {
        "schema_version": "1.0",
        "digest": digest,
        "review_html": str(review_html),
        "mode": mode,
        "launched_at_epoch": time.time(),
    }
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def validate_interactive_modifier_contract(modifier_text: str) -> dict[str, object]:
    """Reject raster wrappers and prove source-bound selectable CAD geometry."""
    missing: list[str] = []
    checks = (
        ("interactive_drawing_modifier role", _MODIFIER_ROLE),
        ("SVG cad-view", _CAD_VIEW),
        ("separate view-hit target", _VIEW_HIT),
        ("view entity identifier", _VIEW_ENTITY_ID),
        ("source object identifier", _SOURCE_ID),
        ("source subobject identifier", _SOURCE_SUBOBJECT),
        ("semantic entity catalog", _SEMANTIC_CATALOG),
        ("model measurement inspector", _MEASUREMENT_SURFACE),
        ("typed correction surface", _CORRECTION_SURFACE),
        ("reviewOnly=true safety lock", _REVIEW_ONLY),
        ("accepted=false safety lock", _NOT_ACCEPTED),
    )
    for label, pattern in checks:
        if not pattern.search(modifier_text):
            missing.append(label)
    image_count = len(_RASTER_IMAGE.findall(modifier_text))
    hit_count = len(_VIEW_HIT.findall(modifier_text))
    if image_count and not (
        _VECTOR_SOURCE_BOUND.search(modifier_text)
        and _RASTER_ONLY_FALSE.search(modifier_text)
        and hit_count > image_count
    ):
        missing.append("raster underlay must be secondary to declared source-bound vector entities")
    if missing:
        raise PlanError(
            "review request requires a selectable vector CAD modifier; missing: "
            + ", ".join(missing)
        )
    return {
        "contract": "aicad_selectable_vector_modifier_v1",
        "vector_source_bound": True,
        "raster_only": False,
        "svg_view_count": len(_CAD_VIEW.findall(modifier_text)),
        "view_hit_count": hit_count,
        "raster_image_count": image_count,
    }


def launch_review(
    review_html: str | Path,
    mode: str = "auto",
    *,
    opener: Callable[[Path], None] | None = None,
) -> dict[str, object]:
    if mode not in REVIEW_LAUNCH_MODES:
        raise PlanError("review launch mode must be auto, stage, always, or never")
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
    if resolved_mode == "stage":
        staged_path = _stage_review_for_compatibility(path)
        return {
            "status": "staged",
            "mode": resolved_mode,
            "reason": "staged_without_launch",
            "review_html": str(staged_path),
            "source_review_html": str(path),
            "sha256": hashlib.sha256(staged_path.read_bytes()).hexdigest(),
            "staged_for_compatibility": staged_path != path,
            "staged_for_persistence": staged_path != path,
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

    # A browser must never receive an ephemeral build/test path. Persist every
    # launched report, including an ASCII path, before handing it to the GUI.
    launch_path = _stage_review_for_compatibility(path)
    digest = hashlib.sha256(launch_path.read_bytes()).hexdigest()
    state_path = _launch_state_path()
    if resolved_mode == "auto":
        state = _load_launch_state(state_path)
        launched_at = state.get("launched_at_epoch")
        if (
            state.get("digest") == digest
            and isinstance(launched_at, (int, float))
            and time.time() - float(launched_at) <= _dedup_seconds()
            and launch_path.is_file()
        ):
            return {
                "status": "skipped",
                "mode": resolved_mode,
                "reason": "duplicate_auto_launch",
                "review_html": str(launch_path),
                "source_review_html": str(path),
                "staged_for_compatibility": launch_path != path,
                "staged_for_persistence": launch_path != path,
                "launch_state": str(state_path),
            }
    open_review = opener or _system_open
    try:
        open_review(launch_path)
    except OSError as error:
        if resolved_mode == "always":
            raise PlanError(f"review UI launch failed: {error}") from error
        return {
            "status": "failed",
            "mode": resolved_mode,
            "reason": str(error),
            "review_html": str(launch_path),
            "source_review_html": str(path),
            "staged_for_compatibility": launch_path != path,
            "staged_for_persistence": launch_path != path,
            "launch_state": str(state_path),
        }
    state_persisted = _write_launch_state(state_path, digest, launch_path, resolved_mode)
    return {
        "status": "launched",
        "mode": resolved_mode,
        "reason": None,
        "review_html": str(launch_path),
        "source_review_html": str(path),
        "staged_for_compatibility": launch_path != path,
        "staged_for_persistence": launch_path != path,
        "launch_state": str(state_path),
        "launch_state_persisted": state_persisted,
    }


def open_review_request(
    review_html: str | Path,
    *,
    cad_path: str | Path | None = None,
    open_native_cad: bool = False,
    review_mode: str = "always",
    review_opener: Callable[[Path], None] | None = None,
    native_opener: Callable[[Path], None] | None = None,
) -> dict[str, object]:
    """Open a content-bound modifier first and native CAD only on explicit intent.

    Generic open/show/view requests must leave ``open_native_cad`` false. Merely
    supplying a CAD or PDF path never counts as intent to launch a native host.
    """
    if review_mode not in REVIEW_REQUEST_MODES:
        raise PlanError("review request mode must be auto or always")
    modifier = Path(review_html).expanduser().resolve()
    if not modifier.is_file() or modifier.suffix.lower() != ".html":
        raise PlanError(f"review request requires an existing local HTML modifier: {modifier}")
    try:
        modifier_text = modifier.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanError(f"review modifier cannot be read as UTF-8: {modifier}") from exc
    modifier_contract = validate_interactive_modifier_contract(modifier_text)

    native: Path | None = None
    if open_native_cad:
        if cad_path is None:
            raise PlanError("explicit native CAD opening requires cad_path")
        native = Path(cad_path).expanduser().resolve()
        if not native.is_file():
            raise PlanError(f"native CAD opening requires an existing local file: {native}")
        if native.suffix.lower() not in NATIVE_CAD_SUFFIXES:
            allowed = ", ".join(sorted(NATIVE_CAD_SUFFIXES))
            raise PlanError(f"native CAD opening rejects non-CAD artifacts; allowed suffixes: {allowed}")

    review_result = launch_review(modifier, review_mode, opener=review_opener)
    result: dict[str, object] = {
        "policy": "reviewer_first",
        "reviewer_role": "interactive_drawing_modifier",
        "native_cad_policy": "explicit_user_request_only_after_reviewer",
        "modifier_contract": modifier_contract,
        "review": review_result,
        "open_order": ["interactive_drawing_modifier"]
        if review_result.get("status") == "launched" else [],
    }
    if not open_native_cad:
        result["native_cad"] = {
            "status": "blocked" if cad_path is not None else "not_requested",
            "reason": "explicit_native_cad_request_required" if cad_path is not None else None,
            "cad_path": str(Path(cad_path).expanduser().resolve()) if cad_path is not None else None,
        }
        return result
    if review_result.get("status") != "launched":
        result["native_cad"] = {
            "status": "blocked",
            "reason": "reviewer_must_launch_before_native_cad",
            "cad_path": str(native),
        }
        return result

    open_native = native_opener or _system_open
    try:
        open_native(native)  # type: ignore[arg-type]
    except OSError as exc:
        raise PlanError(f"native CAD UI launch failed after reviewer launch: {exc}") from exc
    result["native_cad"] = {"status": "launched", "reason": None, "cad_path": str(native)}
    result["open_order"] = ["interactive_drawing_modifier", "native_cad"]
    return result
