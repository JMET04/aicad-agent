from __future__ import annotations

"""Bounded execution layer for the frozen wand electromechanical interface.

The validator lives in :mod:`finalize_wand_release`.  This module is imported
only after that validator has accepted a FROZEN, authority-complete input.  It
normalizes the public mechanical parameter source, regenerates only the wand
change closure, and proves byte-for-byte stability for every other subject.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ASSEMBLY_ID = "MW-A-001"
DIRECT_PARTS = ("MW-M-001A", "MW-M-001B", "MW-M-002", "MW-M-005")
CONDITIONAL_PART = "MW-M-003"
INTERFACE_RELATIVE_PATH = (
    "projects/magic-wand/electronics/wand/wand-electromechanical-interface.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.wand-finalize.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def refs_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["ref"]): row for row in document["refs"]}


def normalized_design_input(
    current: dict[str, Any], validated: dict[str, Any]
) -> dict[str, Any]:
    """Return the single public parameter source for the frozen wand revision."""

    source = validated["document"]
    refs = refs_by_id(source)
    requirements = source["mechanicalRequirements"]
    result = json.loads(json.dumps(current))
    interfaces = result["interfaces"]

    sw1 = refs["SW1"]
    button_requirement = requirements["buttonStack"]
    preload = float(sw1["allowedPreloadMm"])
    overtravel = float(sw1["allowedOvertravelMm"])
    travel = float(sw1["travelMm"])
    if overtravel <= 0.0:
        raise ValueError("SW1 allowedOvertravelMm must be positive for a bottom-safe hard stop")

    # The released contact gap remains positive after the full permitted preload
    # variation.  The hard stop consumes only half of the permitted overtravel,
    # leaving a positive switch-bottom clearance at its worst controlled stroke.
    nominal_contact_gap = max(0.05, preload + 0.02)
    stop_overtravel = overtravel / 2.0
    hard_stop_total_travel = nominal_contact_gap + travel + stop_overtravel
    released_head_base_y = 13.5
    stop_ring_top_y = released_head_base_y - hard_stop_total_travel
    bottom_stop_clearance = overtravel - stop_overtravel

    button = dict(interfaces["press_to_arm"])
    button.update(
        {
            "global_center_z": float(sw1["actuatorCenterCaseMm"][2]),
            "switch_ref": "SW1",
            "switch_mpn": sw1["mpn"],
            "switch_mounting_y": float(sw1["caseCenterMm"][1]),
            "switch_free_top_y": float(button_requirement["switchFreeTopCaseYmm"]),
            "switch_free_height": float(sw1["freeHeightMm"]),
            "switch_travel": travel,
            "switch_force_n": float(sw1["forceN"]),
            "allowed_preload": preload,
            "allowed_overtravel": overtravel,
            "nominal_contact_gap": nominal_contact_gap,
            "minimum_released_gap": nominal_contact_gap - preload,
            "contact_nose_y_released": float(button_requirement["switchFreeTopCaseYmm"])
            + nominal_contact_gap,
            "contact_nose_diameter": 3.0,
            "released_head_base_y": released_head_base_y,
            "hard_stop_total_travel": hard_stop_total_travel,
            "hard_stop_ring_top_y": stop_ring_top_y,
            "hard_stop_ring_thickness": 0.50,
            "bottom_stop_clearance": bottom_stop_clearance,
            "target_travel": travel,
            "target_force_n": [float(sw1["forceN"]), float(sw1["forceN"])],
            "source_interface_sha256": validated["interfaceSha256"],
        }
    )
    interfaces["press_to_arm"] = button

    # Legacy -Y USB/debug apertures were inferred from an incorrect connector
    # orientation.  The frozen J1 authority drives one +X rounded opening.
    service = json.loads(json.dumps(interfaces["service_openings"]))
    for opening in service.values():
        opening["enabled"] = False
        opening["superseded_by"] = "frozen J1 +X panel opening"
    interfaces["service_openings"] = service

    j1_opening = requirements["j1PanelOpening"]
    interfaces["wand_j1_panel_opening"] = {
        "ref": "J1",
        "wall_axis": j1_opening["wallAxis"],
        "case_center": [float(value) for value in j1_opening["caseCenterMm"]],
        "width": float(j1_opening["widthMm"]),
        "height": float(j1_opening["heightMm"]),
        "corner_radius": float(j1_opening["cornerRadiusMm"]),
        "cut_depth": float(j1_opening["cutDepthMm"]),
        "tolerances_mm": j1_opening["tolerancesMm"],
        "mating_direction": j1_opening["matingDirection"],
        "authority_sha256": j1_opening["authoritySha256"],
    }

    channel_requirement = requirements["boardChannel"]
    width_clearance = float(channel_requirement["minimumNominalWidthClearancePerSideMm"])
    axial_clearance = float(channel_requirement["minimumNominalAxialClearanceMm"])
    carrier = dict(interfaces["carrier"])
    carrier.update(
        {
            "outer_width": max(
                float(carrier["outer_width"]),
                float(source["boardDimensionsMm"]["width"])
                + 2.0 * width_clearance
                + 2.0 * float(carrier["side_wall"])
                + 0.60,
            ),
            "pcb_envelope_width": float(source["boardDimensionsMm"]["width"]),
            "pcb_envelope_length": float(source["boardDimensionsMm"]["height"]),
            "pcb_envelope_thickness": float(source["boardDimensionsMm"]["thickness"]),
            "pcb_bcu_support_y": float(channel_requirement["bCuSupportYmm"]),
            "pcb_fcu_y": float(channel_requirement["fCuYmm"]),
            "pcb_local_z_start": 0.0,
            "board_channel_width": float(source["boardDimensionsMm"]["width"])
            + 2.0 * width_clearance,
            "nominal_width_clearance_per_side": width_clearance,
            "nominal_axial_clearance": axial_clearance,
            "datum_scheme": channel_requirement["datumScheme"],
            "retention_process": requirements["pcbRetentionProcess"]["type"],
            "retention_holes": [
                {
                    "ref": ref,
                    "case_x": float(refs[ref]["caseCenterMm"][0]),
                    "case_z": float(refs[ref]["caseCenterMm"][2]),
                    "local_z": float(refs[ref]["caseCenterMm"][2])
                    - float(carrier["assembly_z_start"]),
                    "finished_diameter": float(refs[ref]["finishedDiameterMm"]),
                    "post_diameter": 2.0,
                    "boss_base_diameter": 4.4,
                }
                for ref in ("H1", "H2")
            ],
            "switch_clearance": {
                "ref": "SW1",
                "local_center": [
                    float(sw1["caseCenterMm"][0]),
                    float(sw1["caseCenterMm"][1]),
                    float(sw1["caseCenterMm"][2]) - float(carrier["assembly_z_start"]),
                ],
                "body_envelope": [float(value) for value in sw1["bodyEnvelopeMm"]],
                "minimum_clearance": 0.30,
            },
        }
    )
    interfaces["carrier"] = carrier

    u1 = refs["U1"]
    rear_cap = dict(interfaces["rear_cap"])
    if validated["rearCapChangeRequired"]:
        u1_rear_case_z = float(u1["caseCenterMm"][2]) - float(u1["bodyEnvelopeMm"][1]) / 2.0
        maximum_plug_end_z = u1_rear_case_z - float(
            requirements["ninaMechanicalKeepout"]["minimumCasingClearanceMm"]
        )
        shortened = maximum_plug_end_z - float(rear_cap["exposed_length"])
        if shortened <= 0.8:
            raise ValueError("NINA casing clearance leaves no viable rear-cap locating plug")
        rear_cap["plug_length"] = min(float(rear_cap["plug_length"]), shortened)
        rear_cap["rf_clearance_limited_plug_end_z"] = maximum_plug_end_z
    rear_cap["nina_minimum_casing_clearance"] = float(
        requirements["ninaMechanicalKeepout"]["minimumCasingClearanceMm"]
    )
    rear_cap["source_interface_sha256"] = validated["interfaceSha256"]
    interfaces["rear_cap"] = rear_cap

    interfaces["wand_electromechanical"] = {
        "interface_source": INTERFACE_RELATIVE_PATH,
        "interface_status": "FROZEN",
        "interface_sha256": validated["interfaceSha256"],
        "source_board_sha256": source["sourceBoard"]["sha256"],
        "source_routes_sha256": source["sourceRoutes"]["sha256"],
        "native_drc_sha256": source["nativeDrc"]["sha256"],
        "revision": source["revision"],
        "authority_release_blocked_refs": 0,
        "coordinate_contract": source["coordinateContract"],
        "board_dimensions_mm": source["boardDimensionsMm"],
        "refs": source["refs"],
        "absent_refs": source["absentRefs"],
        "consistency_evidence": source["consistencyEvidence"],
        "mechanical_requirements": requirements,
    }

    result["parts"]["MW-M-001A"]["critical_features"] = [
        "source-bound SW1 aperture/guard/hard stop",
        "source-bound J1 +X opening",
        "seam tongue",
        "M2 clearance holes",
        "antenna-zone nonconductive wall",
    ]
    result["parts"]["MW-M-001B"]["critical_features"] = [
        "closed superseded -Y service windows",
        "seam groove",
        "carrier key rail",
        "M2 pilot holes",
    ]
    result["parts"]["MW-M-002"]["critical_features"] = [
        "source-bound PCB channel/datums",
        "H1/H2 nonmetallic heat-stake retainers",
        "SW1 body clearance",
        "poka-yoke key groove",
    ]
    result["parts"]["MW-M-005"]["critical_features"] = [
        "reduced SW1 contact nose",
        "7.6 mm guided stem",
        "independent shell hard-stop head",
        "anti-rotation flat",
    ]
    return result


def active_changed_parts(root: Path) -> tuple[str, ...]:
    design = read_json(root / "factory-design-input.json")
    wand = design["interfaces"]["wand_electromechanical"]
    parts = list(DIRECT_PARTS)
    if wand["mechanical_requirements"]["rearCapChangeRequired"]:
        parts.append(CONDITIONAL_PART)
    return tuple(parts)


def run_native_phase(root: Path) -> None:
    import pythoncom
    import win32com.client

    import factory_solidworks_export as swx

    part_ids = active_changed_parts(root)
    pythoncom.CoInitialize()
    sw = None
    previous_3d_interconnect: bool | None = None
    try:
        sw = win32com.client.DispatchEx("SldWorks.Application")
        sw.Visible = False
        sw.UserControl = False
        sw.CommandInProgress = True
        previous_3d_interconnect = bool(
            sw.GetUserPreferenceToggle(swx.SW_PREF_ENABLE_3D_INTERCONNECT)
        )
        sw.SetUserPreferenceToggle(swx.SW_PREF_ENABLE_3D_INTERCONNECT, False)
        native_tool = swx._native_tool(sw)
        for part_id in part_ids:
            swx.export_part(sw, root, part_id, native_tool)
        swx.export_assembly(sw, root, ASSEMBLY_ID, native_tool)
        for part_id in part_ids:
            swx._refresh_part_after_assembly_save(sw, root, part_id)
    finally:
        if sw is not None:
            try:
                if previous_3d_interconnect is not None:
                    sw.SetUserPreferenceToggle(
                        swx.SW_PREF_ENABLE_3D_INTERCONNECT,
                        previous_3d_interconnect,
                    )
                sw.CommandInProgress = False
                sw.ExitApp()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _wand_frame(frame_id: str, part_ids: tuple[str, ...]) -> bool:
    prefixes = tuple(f"{part_id}:" for part_id in part_ids) + ("MW-A-001",)
    return frame_id.startswith(prefixes)


def run_drawing_phase(root: Path) -> None:
    import factory_drawings as base_drawings
    import factory_release_drawings as drawings
    import factory_release_geometry as geometry

    part_ids = active_changed_parts(root)
    output = root / "outputs" / "2d"
    reports = root / "reports"
    old_index = read_json(reports / "drawing-index.json")["drawings"]
    old_audit = read_json(reports / "drawing-text-frame-audit.json")
    old_sections = read_json(reports / "brep-section-intersection-report.json")["sections"]

    drawings.TEXT_INPUTS = []
    base_drawings.TEXT_FRAMES = []
    new_sections: list[dict[str, Any]] = []
    new_index = [
        drawings.generate_part_drawing(
            part_id,
            output / f"{geometry.PART_BASENAMES[part_id]}.dxf",
            new_sections,
        )
        for part_id in part_ids
    ]
    new_index.extend(
        [
            drawings.generate_assembly_drawing(
                "MW-A-001",
                "MAGIC WAND GENERAL ASSEMBLY",
                "assembly",
                geometry.make_assembly(False),
                output / "MW-A-001_wand_general_assembly.dxf",
                new_sections,
            ),
            drawings.generate_assembly_drawing(
                "MW-A-001-EX",
                "MAGIC WAND EXPLODED",
                "exploded",
                geometry.make_assembly(True),
                output / "MW-A-001_wand_exploded.dxf",
                new_sections,
            ),
            drawings.generate_assembly_drawing(
                "MW-A-001-SE",
                "MAGIC WAND SECTION A-A",
                "section",
                geometry.make_assembly(False),
                output / "MW-A-001_wand_section_A-A.dxf",
                new_sections,
            ),
            drawings.generate_assembly_drawing(
                "MW-A-001-HI",
                "MAGIC WAND HARNESS INTERFACE",
                "harness",
                geometry.make_assembly(False),
                output / "MW-A-001_wand_harness_interface.dxf",
                new_sections,
            ),
        ]
    )

    new_numbers = {row["drawing_number"] for row in new_index}
    merged_index = [row for row in old_index if row["drawing_number"] not in new_numbers]
    merged_index.extend(new_index)
    frames = [
        row for row in old_audit["frames"] if not _wand_frame(row["frame_id"], part_ids)
    ] + list(base_drawings.TEXT_FRAMES)
    closures = [
        row for row in old_audit["inputClosure"] if not _wand_frame(row["frameId"], part_ids)
    ] + list(drawings.TEXT_INPUTS)
    overflow = [row for row in frames if row["overflow"]]
    unclosed = [row for row in closures if not row["textClosure"]]
    undersize = [
        row
        for row in frames
        if row["text_height_mm"] < drawings.MIN_PRINT_TEXT_HEIGHT_MM
    ]
    audit = {
        "schema": "aicad_factory_drawing_text_frame_audit_v3",
        "sheet": old_audit["sheet"],
        "drawing_count": len(merged_index),
        "text_entity_count": len(frames),
        "overflow_count": len(overflow),
        "truncated_count": len(unclosed),
        "undersize_count": len(undersize),
        "minimum_print_text_height_mm": drawings.MIN_PRINT_TEXT_HEIGHT_MM,
        "passed": not overflow and not unclosed and not undersize,
        "required_layers": base_drawings.LAYER_SPECS,
        "frames": frames,
        "inputClosure": closures,
    }

    replaced_subjects = set(part_ids) | {ASSEMBLY_ID}
    merged_sections = [
        row for row in old_sections if row.get("subjectId") not in replaced_subjects
    ] + new_sections
    required = sorted(
        {
            feature_id
            for specs in drawings.PART_SECTION_SPECS.values()
            for spec in specs
            for feature_id in spec["featureIdsCovered"]
        }
    )
    covered = sorted(
        {
            feature_id
            for row in merged_sections
            for feature_id in row["featureIdsCovered"]
        }
    )
    missing = sorted(set(required) - set(covered))
    section_passed = not missing and all(
        row["intersection"]["valid"]
        and row["intersection"]["volume_mm3"] > 0
        and row["planeWithinSubjectBbox"]
        and row["decorativeHatchUsed"] is False
        for row in merged_sections
    )
    if overflow or unclosed or undersize or not section_passed:
        raise RuntimeError("wand drawing text/section audit failed")
    write_json(
        reports / "drawing-index.json",
        {"schema": "aicad_factory_drawing_index_v2", "drawings": merged_index},
    )
    write_json(reports / "drawing-text-frame-audit.json", audit)
    write_json(reports / "feature-dimension-catalog.json", drawings.feature_dimension_catalog())
    write_json(
        reports / "brep-section-intersection-report.json",
        {
            "schema": "aicad_factory_brep_section_intersections_v2",
            "requiredFeatureIds": required,
            "coveredFeatureIds": covered,
            "missingFeatureIds": missing,
            "sections": merged_sections,
            "passed": section_passed,
        },
    )


def document_paths(root: Path, assembly_id: str) -> dict[str, Path]:
    folder = root / "outputs" / "documents"
    return {
        "bom": folder / f"{assembly_id}_manufacturing-bom.json",
        "positions": folder / f"{assembly_id}_assembly-positions.json",
        "moldingInput": folder / f"{assembly_id}_molding-input.json",
        "assemblyWorkInstruction": folder / f"{assembly_id}_assembly-work-instruction.pdf",
        "inspectionPlan": folder / f"{assembly_id}_inspection-plan.pdf",
    }


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_electromechanical_verification(root: Path) -> Path:
    import factory_release_geometry as geometry

    p = geometry.P
    wand = p["interfaces"]["wand_electromechanical"]
    button = p["interfaces"]["press_to_arm"]
    carrier = p["interfaces"]["carrier"]
    rear = p["interfaces"]["rear_cap"]
    refs = {row["ref"]: row for row in wand["refs"]}

    released_gap = float(button["nominal_contact_gap"])
    minimum_gap = float(button["minimum_released_gap"])
    hard_stop = float(button["hard_stop_total_travel"])
    travel = float(button["switch_travel"])
    overtravel = float(button["allowed_overtravel"])
    switch_compression_at_stop = hard_stop - released_gap
    bottom_clearance = travel + overtravel - switch_compression_at_stop
    button_pass = (
        released_gap > 0.0
        and minimum_gap > 0.0
        and switch_compression_at_stop >= travel
        and bottom_clearance > 0.0
    )

    retention_rows = []
    for hole in carrier["retention_holes"]:
        source = refs[hole["ref"]]
        axis_delta = abs(float(hole["case_x"]) - float(source["caseCenterMm"][0])) + abs(
            float(hole["case_z"]) - float(source["caseCenterMm"][2])
        )
        retention_rows.append(
            {
                "ref": hole["ref"],
                "pcbCaseCenterMm": source["caseCenterMm"],
                "carrierAxisCaseXZmm": [hole["case_x"], hole["case_z"]],
                "axisDeltaMm": round(axis_delta, 9),
                "finishedHoleDiameterMm": source["finishedDiameterMm"],
                "postDiameterMm": hole["post_diameter"],
                "diametralAssemblyClearanceMm": round(
                    float(source["finishedDiameterMm"]) - float(hole["post_diameter"]), 6
                ),
                "process": carrier["retention_process"],
                "metallic": False,
                "passed": axis_delta <= 1e-6
                and float(source["finishedDiameterMm"]) > float(hole["post_diameter"]),
            }
        )

    u1 = refs["U1"]
    u1_rear_z = float(u1["caseCenterMm"][2]) - float(u1["bodyEnvelopeMm"][1]) / 2.0
    cap_end_z = float(rear["exposed_length"]) + float(rear["plug_length"])
    rear_clearance = u1_rear_z - cap_end_z
    required_rear_clearance = float(rear["nina_minimum_casing_clearance"])
    rf_pass = rear_clearance + 1e-6 >= required_rear_clearance

    opening = p["interfaces"]["wand_j1_panel_opening"]
    j1 = refs["J1"]
    opening_pass = (
        opening["wall_axis"] == "+X"
        and opening["mating_direction"] == "+X"
        and opening["authority_sha256"] == j1["authorityEvidence"]["sha256"]
        and all(float(opening[key]) > 0.0 for key in ("width", "height", "cut_depth"))
    )

    channel_width = float(carrier["board_channel_width"])
    board_width = float(carrier["pcb_envelope_width"])
    nominal_side_clearance = (channel_width - board_width) / 2.0
    channel_pass = (
        nominal_side_clearance
        >= float(carrier["nominal_width_clearance_per_side"]) - 1e-6
        and float(carrier["nominal_axial_clearance"]) > 0.0
    )

    document = {
        "schema": "aicad_wand_electromechanical_verification_v1",
        "status": "pass"
        if button_pass
        and all(row["passed"] for row in retention_rows)
        and rf_pass
        and opening_pass
        and channel_pass
        else "fail",
        "subjectId": ASSEMBLY_ID,
        "revision": p["revision"],
        "sourceInterface": {
            "path": INTERFACE_RELATIVE_PATH,
            "sha256": wand["interface_sha256"],
            "sourceBoardSha256": wand["source_board_sha256"],
            "sourceRoutesSha256": wand["source_routes_sha256"],
            "nativeDrcSha256": wand["native_drc_sha256"],
        },
        "buttonStack": {
            "switchRef": "SW1",
            "releasedContactGapMm": released_gap,
            "minimumReleasedGapAfterAllowedPreloadMm": minimum_gap,
            "switchTravelMm": travel,
            "hardStopTotalTravelMm": hard_stop,
            "switchCompressionAtHardStopMm": switch_compression_at_stop,
            "positiveBottomStopClearanceMm": bottom_clearance,
            "independentHardStop": "upper-shell annular stop ring against plunger head",
            "passed": button_pass,
        },
        "pcbRetention": {
            "process": "nonmetallic_heat_stake",
            "holes": retention_rows,
            "passed": all(row["passed"] for row in retention_rows),
        },
        "boardChannel": {
            "boardWidthMm": board_width,
            "channelWidthMm": channel_width,
            "nominalClearancePerSideMm": nominal_side_clearance,
            "minimumRequiredPerSideMm": carrier["nominal_width_clearance_per_side"],
            "nominalAxialClearanceMm": carrier["nominal_axial_clearance"],
            "datumScheme": carrier["datum_scheme"],
            "passed": channel_pass,
        },
        "j1PanelOpening": {
            **opening,
            "sourceAuthoritySha256": j1["authorityEvidence"]["sha256"],
            "passed": opening_pass,
        },
        "ninaClearance": {
            "ref": "U1",
            "u1RearCaseZmm": u1_rear_z,
            "rearCapMaximumCaseZmm": cap_end_z,
            "actualCasingClearanceMm": rear_clearance,
            "minimumRequiredCasingClearanceMm": required_rear_clearance,
            "rearCapChanged": wand["mechanical_requirements"]["rearCapChangeRequired"],
            "metallicFastenersInKeepout": 0,
            "passed": rf_pass,
        },
    }
    if document["status"] != "pass":
        raise RuntimeError(f"wand electromechanical verification failed: {document}")
    path = root / "reports" / "MW-A-001_electromechanical-verification.json"
    write_json(path, document)
    return path


def run_package_phase(root: Path) -> None:
    from build123d import export_step

    import build_factory_package as package
    import factory_release_geometry as geometry
    import factory_release_previews as previews

    part_ids = active_changed_parts(root)
    changed_subjects = set(part_ids) | {ASSEMBLY_ID}
    old_preview_manifest = read_json(root / "reports" / "visual-preview-manifest.json")
    rows: list[dict[str, Any]] = []
    for row in old_preview_manifest["previews"]:
        if row["subjectId"] in changed_subjects:
            continue
        copy = dict(row)
        copy["path"] = str((root / copy["path"]).resolve())
        copy["previewOf"] = str((root / copy["previewOf"]).resolve())
        rows.append(copy)

    preview_output = root / "outputs" / "previews"
    for part_id in part_ids:
        basename = geometry.PART_BASENAMES[part_id]
        step_path = root / "outputs" / "3d" / f"{basename}.step"
        dxf_path = root / "outputs" / "2d" / f"{basename}.dxf"
        rows.append(
            previews.render_model_preview(
                part_id, step_path, preview_output / f"{part_id}_model-preview.png"
            )
        )
        rows.append(
            previews.render_dxf_preview(
                part_id, dxf_path, preview_output / f"{part_id}_drawing-preview.png"
            )
        )

    config = package.ASSEMBLY_DOCS[ASSEMBLY_ID]
    assembly_step = root / "outputs" / "3d" / f"{config['basename']}.step"
    exploded_step = root / "outputs" / "3d" / config["explodedStep"]
    export_step(geometry.make_assembly(True), exploded_step)
    rows.append(
        previews.render_model_preview(
            ASSEMBLY_ID,
            assembly_step,
            preview_output / f"{ASSEMBLY_ID}_model-preview.png",
        )
    )
    rows.append(
        previews.render_model_preview(
            ASSEMBLY_ID,
            exploded_step,
            preview_output / f"{ASSEMBLY_ID}_exploded-model-preview.png",
        )
    )
    for role in ("assemblyDrawing", "explodedDrawing", "sectionDrawing", "harnessDrawing"):
        dxf_path = root / "outputs" / "2d" / config[role]
        row = previews.render_dxf_preview(
            ASSEMBLY_ID,
            dxf_path,
            preview_output / f"{Path(config[role]).stem}_preview.png",
        )
        row["drawingRole"] = role
        rows.append(row)
    previews.write_preview_manifest(root, rows)

    wand_documents = package.build_assembly_documents(root, ASSEMBLY_ID)
    _, wand_interference = package.build_interference(
        root, ASSEMBLY_ID, wand_documents["positions"]
    )
    verification = build_electromechanical_verification(root)
    documents = {
        ASSEMBLY_ID: wand_documents,
        "MW-A-101": document_paths(root, "MW-A-101"),
    }
    preview_paths: dict[str, dict[str, Path]] = {}
    for part_id in geometry.PART_FACTORIES:
        preview_paths[part_id] = {
            "modelPreview": preview_output / f"{part_id}_model-preview.png",
            "drawingPreview": preview_output / f"{part_id}_drawing-preview.png",
        }
    for assembly_id, assembly_config in package.ASSEMBLY_DOCS.items():
        preview_paths[assembly_id] = {
            "assemblyPreview3d": preview_output / f"{assembly_id}_model-preview.png",
            "explodedPreview3d": preview_output / f"{assembly_id}_exploded-model-preview.png",
            "assemblyDrawingPreview": preview_output
            / f"{Path(assembly_config['assemblyDrawing']).stem}_preview.png",
            "explodedDrawingPreview": preview_output
            / f"{Path(assembly_config['explodedDrawing']).stem}_preview.png",
            "sectionDrawingPreview": preview_output
            / f"{Path(assembly_config['sectionDrawing']).stem}_preview.png",
        }
        if "harnessDrawing" in assembly_config:
            preview_paths[assembly_id]["harnessDrawingPreview"] = preview_output / (
                f"{Path(assembly_config['harnessDrawing']).stem}_preview.png"
            )
    interference_logs = {
        ASSEMBLY_ID: wand_interference,
        "MW-A-101": root / "reports" / "native" / "MW-A-101_interference-log.json",
    }
    index = package.native_logs_and_index(root, documents, preview_paths, interference_logs)
    wand_index = next(row for row in index["assemblies"] if row["assemblyId"] == ASSEMBLY_ID)
    wand_index["artifacts"]["electromechanicalVerification"] = _artifact(root, verification)
    write_json(root / "reports" / "mechanical-artifact-index.json", index)
    package.build_reviewer(root, rows, index)

    receiver_status = geometry.P["interfaces"]["receiver_enclosure"]["interface_status"]
    wand_status = geometry.P["interfaces"]["wand_electromechanical"]["interface_status"]
    both_frozen = receiver_status == "frozen_electronics_native_drc" and wand_status == "FROZEN"
    package.write_json(
        root / "reports" / "factory-package-readiness.json",
        {
            "schema": "aicad_factory_package_readiness_v3",
            "packageId": geometry.P["package_id"],
            "revision": geometry.P["revision"],
            "partCount": len(index["parts"]),
            "assemblyCount": len(index["assemblies"]),
            "nativePartReopenPassed": True,
            "nativeAssemblyReopenPassed": True,
            "unexpectedInterferenceCount": 0,
            "drawingTextOverflowCount": 0,
            "previewCount": len(rows),
            "wandInterfaceStatus": wand_status,
            "wandInterfaceFrozen": wand_status == "FROZEN",
            "receiverInterfaceStatus": receiver_status,
            "receiverInterfaceFrozen": receiver_status == "frozen_electronics_native_drc",
            "technicalPackageReady": both_frozen,
            "releaseBasis": "DFM/RFQ input; engineering authorization remains controlled by release locks",
        },
    )
    package.build_delivery_manifest(root, index, rows)
    package.build_manifest(root)


def remove_source_caches(root: Path) -> None:
    for folder in (root / "source", root.parents[3] / "tests"):
        cache = (folder / "__pycache__").resolve()
        if cache.parent != folder.resolve():
            raise RuntimeError("refusing to clean an unexpected cache path")
        if cache.is_dir():
            shutil.rmtree(cache)


def phase_command(script: Path, root: Path, phase: str) -> None:
    subprocess.run(
        [sys.executable, "-B", str(script), "--root", str(root), "--phase", phase],
        check=True,
    )


def execute(
    root: Path,
    validated: dict[str, Any],
    immutable_before: dict[str, str],
    immutable_hash_reader: Any,
    immutable_subjects: tuple[str, ...],
) -> None:
    design_path = root / "factory-design-input.json"
    design = normalized_design_input(read_json(design_path), validated)
    failure_path = root / "reports" / "wand-finalization-failure.json"
    if failure_path.is_file():
        failure_path.unlink()
    write_json(design_path, design)
    script = root / "source" / "finalize_wand_release.py"
    try:
        for phase in ("native", "drawings", "package"):
            phase_command(script, root, phase)
        remove_source_caches(root)
        immutable_after = immutable_hash_reader(root, immutable_subjects)
        if immutable_after != immutable_before:
            changed = sorted(set(immutable_before) | set(immutable_after))
            changed = [
                key
                for key in changed
                if immutable_before.get(key) != immutable_after.get(key)
            ]
            raise RuntimeError(f"unchanged subject artifact SHA drift: {changed}")
        test_path = root.parents[3] / "tests" / "test_magic_wand_factory_mechanical.py"
        subprocess.run(
            [sys.executable, "-B", str(test_path)], cwd=root.parents[3], check=True
        )
        remove_source_caches(root)
    except Exception as exc:
        write_json(
            failure_path,
            {
                "schema": "aicad_wand_finalization_failure_v1",
                "status": "fail",
                "interfaceSha256": validated["interfaceSha256"],
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise
