from __future__ import annotations

"""Source-bound visual evidence for the mechanical RFQ package."""

import hashlib
import json
from pathlib import Path
from typing import Any

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from build123d import import_step
from ezdxf.addons.drawing.matplotlib import qsave
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

import factory_release_drawings as drawings
import factory_release_geometry as geometry


PALETTE = (
    "#2F6FA3",
    "#47A36F",
    "#D88934",
    "#7B61A8",
    "#C95B68",
    "#3C8C8C",
    "#7C6C55",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mesh(shape: Any) -> tuple[np.ndarray, np.ndarray]:
    vertices, triangles = shape.tessellate(0.35)
    xyz = np.asarray([[float(p.X), float(p.Y), float(p.Z)] for p in vertices])
    faces = np.asarray(triangles, dtype=int)
    return xyz, faces


def _limits(solids: list[Any]) -> tuple[np.ndarray, np.ndarray]:
    boxes = [solid.bounding_box(optimal=True) for solid in solids]
    lo = np.min([[box.min.X, box.min.Y, box.min.Z] for box in boxes], axis=0)
    hi = np.max([[box.max.X, box.max.Y, box.max.Z] for box in boxes], axis=0)
    center = (lo + hi) / 2.0
    span = max(float(np.max(hi - lo)), 1.0) * 0.58
    return center, np.asarray([span, span, span])


def _render_solids(ax: Any, solids: list[Any], *, alpha: float = 0.92) -> None:
    for index, solid in enumerate(solids):
        xyz, faces = _mesh(solid)
        collection = Poly3DCollection(
            xyz[faces],
            facecolor=PALETTE[index % len(PALETTE)],
            edgecolor="#18212A",
            linewidth=0.12,
            alpha=alpha,
        )
        ax.add_collection3d(collection)


def _format_3d(ax: Any, center: np.ndarray, span: np.ndarray, title: str) -> None:
    ax.set_xlim(center[0] - span[0], center[0] + span[0])
    ax.set_ylim(center[1] - span[1], center[1] + span[1])
    ax.set_zlim(center[2] - span[2], center[2] + span[2])
    ax.set_box_aspect((1, 1, 1))
    ax.set_proj_type("ortho")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10, color="#17202A", pad=4, fontweight="bold")


def _section_for(subject_id: str, shape: Any) -> tuple[Any, str, float]:
    if subject_id in drawings.PART_SECTION_SPECS:
        spec = drawings.PART_SECTION_SPECS[subject_id][0]
    else:
        spec = drawings.ASSEMBLY_SECTION_SPECS[subject_id][0]
    axis = str(spec["axis"])
    coordinate = float(spec["coordinate"])
    return (
        geometry.section_intersection(
            shape, plane_axis=axis, coordinate=coordinate, thickness=0.10
        ),
        axis,
        coordinate,
    )


def render_model_preview(subject_id: str, step_path: Path, output_path: Path) -> dict[str, Any]:
    """Render actual re-imported STEP geometry in orthographic/isometric/section views."""
    shape = import_step(step_path)
    solids = list(shape.solids())
    if not solids:
        raise RuntimeError(f"{step_path} contains no solids")
    center, span = _limits(solids)
    section, axis, coordinate = _section_for(subject_id, shape)
    section_solids = list(section.solids())

    fig = plt.figure(figsize=(12, 8), dpi=200, facecolor="white")
    view_specs = (
        ("FRONT ORTHOGRAPHIC", 0, -90),
        ("TOP ORTHOGRAPHIC", 90, -90),
        ("ISOMETRIC", 24, -48),
    )
    for pane, (title, elevation, azimuth) in enumerate(view_specs, 1):
        ax = fig.add_subplot(2, 2, pane, projection="3d")
        _render_solids(ax, solids)
        _format_3d(ax, center, span, title)
        ax.view_init(elev=elevation, azim=azimuth)

    section_ax = fig.add_subplot(2, 2, 4, projection="3d")
    _render_solids(section_ax, section_solids, alpha=1.0)
    section_center, section_span = _limits(section_solids)
    _format_3d(
        section_ax,
        section_center,
        section_span,
        f"TRUE BREP SECTION {axis}={coordinate:g} mm",
    )
    if axis == "X":
        section_ax.view_init(elev=0, azim=0)
    elif axis == "Y":
        section_ax.view_init(elev=0, azim=-90)
    else:
        section_ax.view_init(elev=90, azim=-90)

    source_sha = sha256_file(step_path)
    fig.suptitle(
        f"{subject_id} · FINAL STEP REIMPORT · SHA256 {source_sha[:16]}…",
        fontsize=13,
        fontweight="bold",
        color="#0F3554",
        y=0.985,
    )
    fig.text(
        0.5,
        0.012,
        "REVIEW ONLY · ORTHOGRAPHIC + ISOMETRIC + FINITE-BREP SECTION · mm",
        ha="center",
        fontsize=8,
        color="#394B59",
    )
    fig.tight_layout(rect=(0.015, 0.035, 0.985, 0.955))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="white")
    plt.close(fig)
    return {
        "subjectId": subject_id,
        "kind": "modelPreview",
        "path": output_path.as_posix(),
        "previewOf": step_path.as_posix(),
        "sourceSha256": source_sha,
        "previewSha256": sha256_file(output_path),
        "views": ["frontOrthographic", "topOrthographic", "isometric", "trueBrepSection"],
        "section": {"axis": axis, "coordinateMm": coordinate},
        "solidCount": len(solids),
    }


def render_dxf_preview(subject_id: str, dxf_path: Path, output_path: Path) -> dict[str, Any]:
    """Render the exact DXF through ezdxf's real drawing backend."""
    document = ezdxf.readfile(dxf_path)
    # Keep the manufacturing DXF untouched, but render its semantic layers with
    # high-contrast print colours. ACI yellow/light-grey is technically valid
    # yet becomes illegible when an A3 sheet is fitted into the reviewer pane.
    preview_layer_rgb = {
        "BORDER": (24, 31, 39),
        "OUTLINE": (10, 18, 28),
        "VISIBLE": (0, 0, 0),
        "HIDDEN": (72, 82, 92),
        "CENTER": (0, 86, 102),
        "DIMENSION": (16, 67, 128),
        "SECTION": (145, 24, 31),
        "HATCH": (145, 24, 31),
        "NOTES": (24, 31, 39),
        "TITLE_BLOCK": (18, 26, 35),
        "DATUM": (76, 37, 108),
        "KEEP_OUT": (99, 34, 90),
        "HARNESS": (83, 42, 110),
    }
    for layer_name, rgb in preview_layer_rgb.items():
        if layer_name in document.layers:
            document.layers.get(layer_name).rgb = rgb

    # The source uses the portable single-stroke "txt" face, which is correct for
    # CAD but becomes sub-pixel after an A3 sheet is fitted to a 1100 px reviewer.
    # A condensed bold face in the in-memory render copy preserves text height and
    # frame layout while giving small notes a two-pixel-class raster stroke.
    preview_text_style = "AICAD_PREVIEW_BOLD"
    if preview_text_style not in document.styles:
        document.styles.new(
            preview_text_style,
            dxfattribs={"font": "DejaVuSansCondensed-Bold.ttf", "width": 0.9},
        )
    for entity in document.modelspace().query("TEXT MTEXT"):
        if entity.dxf.layer in {"NOTES", "TITLE_BLOCK", "DIMENSION"}:
            entity.dxf.style = preview_text_style
        # Text stays neutral and darker than #333333; semantic colour remains on
        # the associated linework, leaders, centres and section outlines.
        entity.dxf.true_color = ezdxf.colors.rgb2int((25, 31, 38))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    qsave(
        document.modelspace(),
        output_path,
        bg="#FFFFFF",
        dpi=300,
        size_inches=(16.54, 11.69),
    )
    return {
        "subjectId": subject_id,
        "kind": "drawingPreview",
        "path": output_path.as_posix(),
        "previewOf": dxf_path.as_posix(),
        "sourceSha256": sha256_file(dxf_path),
        "previewSha256": sha256_file(output_path),
        "renderer": "ezdxf.addons.drawing.matplotlib.qsave",
        "rendererStyle": "high-contrast-semantic-layers-bold-text-v2",
        "dpi": 300,
        "page": "A3 landscape",
    }


def write_preview_manifest(root: Path, rows: list[dict[str, Any]]) -> Path:
    path = root / "reports" / "visual-preview-manifest.json"
    normalized = []
    for row in rows:
        copy = dict(row)
        for key in ("path", "previewOf"):
            copy[key] = Path(copy[key]).resolve().relative_to(root.resolve()).as_posix()
        normalized.append(copy)
    document = {
        "schema": "aicad_factory_visual_preview_manifest_v1",
        "sourceBinding": "previewOf + sourceSha256",
        "previews": normalized,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

