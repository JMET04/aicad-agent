from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine3d import CompiledPlan3D, ResolvedFeature3D


def _profile_payload(feature: ResolvedFeature3D) -> dict[str, Any]:
    profile = feature.profile
    return {
        "kind": profile.kind,
        "center_x_mm": profile.center[0],
        "center_y_mm": profile.center[1],
        "width_mm": profile.width,
        "height_mm": profile.height,
        "radius_mm": profile.radius,
        "count": profile.count,
        "bolt_circle_radius_mm": profile.bolt_circle_radius,
        "start_angle_deg": profile.start_angle_deg,
        "circles": [{"x_mm": item.center[0], "y_mm": item.center[1], "radius_mm": item.radius} for item in profile.primitives],
    }


def host_payload(plan: CompiledPlan3D, output_sldprt: Path, output_step: Path, template_path: Path | None) -> dict[str, Any]:
    return {
        "protocol": "AICAD_SOLIDWORKS_1",
        "source_sha256": plan.source_hash,
        "part_name": plan.name,
        "units": plan.units,
        "tolerance_mm": plan.tolerance,
        "template_path": str(template_path.resolve()) if template_path else None,
        "output_sldprt": str(output_sldprt.resolve()),
        "output_step": str(output_step.resolve()),
        "features": [
            {
                "id": feature.id,
                "type": feature.type,
                "purpose": feature.purpose,
                "reasoning": feature.reasoning,
                "depends_on": list(feature.depends_on),
                "support_feature": feature.support_feature,
                "support_top_z_mm": feature.support_top_z,
                "resulting_top_z_mm": feature.resulting_top_z,
                "depth_mm": feature.depth,
                "end_condition": feature.end_condition,
                "profile": _profile_payload(feature),
                "expected": {
                    "volume_before_mm3": feature.expected_volume_before,
                    "volume_after_mm3": feature.expected_volume_after,
                    "volume_delta_mm3": feature.expected_volume_delta,
                    "bbox_mm": list(feature.expected_bbox),
                    "solid_body_count": feature.expected_body_count,
                },
            }
            for feature in plan.features
        ],
    }


def write_3d_audit(plan: CompiledPlan3D, path: Path) -> None:
    rows = [
        f"# {plan.name} - AICAD 3D feature audit", "", f"- Source SHA-256: `{plan.source_hash}`",
        f"- Origin: `(0,0,0)`", f"- Units: `{plan.units}`", f"- Tolerance: `{plan.tolerance:g} mm`",
        f"- Feature count: `{len(plan.features)}`", "",
        "| # | ID | Type | Purpose | Dependency | Profile | Depth/end | Expected volume delta | Reasoning |",
        "|---:|---|---|---|---|---|---|---:|---|",
    ]
    clean = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    for index, feature in enumerate(plan.features, 1):
        profile = feature.profile
        if profile.kind == "center_rectangle":
            profile_text = f"rectangle {profile.width:g}x{profile.height:g} at {profile.center}"
        elif profile.kind == "circle":
            profile_text = f"circle R{profile.radius:g} at {profile.center}"
        else:
            profile_text = f"{profile.count}x R{profile.radius:g} on PCD {2 * float(profile.bolt_circle_radius):g}"
        rows.append(
            f"| {index} | `{feature.id}` | `{feature.type}` | {clean(feature.purpose)} | "
            f"`{feature.support_feature or 'principal_plane'}` | {profile_text} | {feature.depth:g} / {feature.end_condition} | "
            f"{feature.expected_volume_delta:g} mm3 | {clean(feature.reasoning)} |"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def export_plan3d(plan: CompiledPlan3D, output_dir: Path, stem: str, template_path: Path | None) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "source": output_dir / f"{stem}.aicad3d.plan.json",
        "execution": output_dir / f"{stem}.swplan.json",
        "audit": output_dir / f"{stem}.3d.audit.md",
        "sldprt": output_dir / f"{stem}.SLDPRT",
        "step": output_dir / f"{stem}.step",
        "host_report": output_dir / f"{stem}.solidworks-report.json",
        "reopen_report": output_dir / f"{stem}.reopen-report.json",
        "manifest": output_dir / f"{stem}.3d.manifest.json",
    }
    payload = host_payload(plan, paths["sldprt"], paths["step"], template_path)
    paths["execution"].write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_3d_audit(plan, paths["audit"])
    manifest = {
        "schema_version": "1.0", "name": plan.name, "source_sha256": plan.source_hash,
        "feature_count": len(plan.features), "feature_types": {kind: sum(feature.type == kind for feature in plan.features) for kind in ("base_extrude", "boss_extrude", "cut_extrude")},
        "expected_final_volume_mm3": plan.features[-1].expected_volume_after,
        "expected_final_bbox_mm": list(plan.features[-1].expected_bbox),
        "artifacts": {key: str(value.resolve()) for key, value in paths.items() if key != "manifest"},
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths
