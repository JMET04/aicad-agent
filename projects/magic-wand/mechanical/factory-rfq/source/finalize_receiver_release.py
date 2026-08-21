from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PART_IDS = ("MW-M-101", "MW-M-102")
ASSEMBLY_ID = "MW-A-101"
WAND_FILE_PREFIXES = (
    "MW-M-001A",
    "MW-M-001B",
    "MW-M-002",
    "MW-M-003",
    "MW-M-004",
    "MW-M-005",
    "MW-P-001",
    "MW-A-001",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.receiver-finalize.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def close(actual: float, expected: float, tolerance: float = 1e-6) -> bool:
    return math.isclose(float(actual), float(expected), abs_tol=tolerance)


def point(value: Any, field: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must be a two-number array")
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a two-number array") from exc


def resolve_artifact_path(repository: Path, interface_path: Path, raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"artifact path must be portable and relative: {raw}")
    candidates = [repository / relative, interface_path.parent / relative]
    matches = {candidate.resolve() for candidate in candidates if candidate.is_file()}
    if len(matches) != 1:
        raise ValueError(f"artifact path does not resolve uniquely: {raw}")
    return next(iter(matches))


def validate_artifact(
    repository: Path,
    interface_path: Path,
    record: dict[str, Any],
    label: str,
) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be an artifact object")
    if not {"path", "size", "sha256"} <= set(record):
        raise ValueError(f"{label} requires path/size/sha256")
    path = resolve_artifact_path(repository, interface_path, str(record["path"]))
    if path.stat().st_size != int(record["size"]):
        raise ValueError(f"{label} size mismatch")
    if sha256_file(path) != str(record["sha256"]).lower():
        raise ValueError(f"{label} SHA-256 mismatch")
    return path


def _values_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return close(float(actual), float(expected))
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(key in actual and _values_match(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list) and isinstance(actual, list):
        return len(actual) == len(expected) and all(
            _values_match(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected)
        )
    return actual == expected


def validate_connector_authority(
    repository: Path,
    interface_path: Path,
    connector: dict[str, Any],
) -> dict[str, Any]:
    ref = str(connector["ref"])
    drawing = connector.get("officialDrawing", {})
    if not all(drawing.get(key) for key in ("url", "documentNumber", "revision", "sha256")):
        raise ValueError(f"{ref} official drawing evidence is incomplete")
    if len(str(drawing["sha256"])) != 64:
        raise ValueError(f"{ref} official drawing SHA is invalid")
    evidence = drawing.get("authorityEvidence", {})
    if evidence.get("kind") != "connector_mechanical_authority":
        raise ValueError(f"{ref} authority evidence kind is not controlled")
    authority_path = validate_artifact(
        repository,
        interface_path,
        evidence,
        f"{ref}.officialDrawing.authorityEvidence",
    )
    authority = read_json(authority_path)
    if authority.get("schema") != "aicad_connector_mechanical_authority_v1":
        raise ValueError(f"{ref} connector authority schema is not controlled")
    if authority.get("status") != "controlled":
        raise ValueError(f"{ref} connector authority status is not controlled")
    if authority.get("kind") != evidence["kind"]:
        raise ValueError(f"{ref} connector authority kind mismatch")
    if authority.get("manufacturer") != connector.get("manufacturer"):
        raise ValueError(f"{ref} connector authority manufacturer mismatch")
    if authority.get("mpn") != connector.get("mpn"):
        raise ValueError(f"{ref} connector authority MPN mismatch")

    sources = authority.get("sources", {})
    drawing_source = sources.get("drawing2d", {})
    step_source = sources.get("step3d", {})
    for source_name, source in (("drawing2d", drawing_source), ("step3d", step_source)):
        if not source.get("documentNumber") or len(str(source.get("sha256", ""))) != 64:
            raise ValueError(f"{ref} authority {source_name} source is incomplete")
    if drawing_source.get("documentNumber") != drawing.get("documentNumber"):
        raise ValueError(f"{ref} authority drawing document number mismatch")
    if str(drawing_source.get("sha256")).lower() != str(drawing.get("sha256")).lower():
        raise ValueError(f"{ref} authority drawing SHA mismatch")

    extracted = authority.get("extractedMechanical", {})
    driving_fields = (
        "sourceDatumMm",
        "mechanicalDatumMm",
        "caseDatumMm",
        "panel",
        "wallAxis",
        "panelNormal",
        "tangentAxis",
        "tangentCenterMm",
        "zCenterMm",
        "widthMm",
        "heightMm",
        "cornerRadiusMm",
        "cutDepthMm",
        "tolerancesMm",
        "bodyEnvelopeMm",
        "matingEnvelopeMm",
        "unmateClearanceMm",
        "matingDirection",
    )
    for field in driving_fields:
        if field not in connector or field not in extracted:
            raise ValueError(f"{ref} authority extracted field {field} is missing")
        if not _values_match(extracted[field], connector[field]):
            raise ValueError(f"{ref} authority extracted field {field} mismatch")

    if ref == "J2":
        if authority.get("mpn") != "DF13A-5P-1.25H(51)":
            raise ValueError("J2 authority MPN is not DF13A-5P-1.25H(51)")
        if drawing_source.get("documentNumber") != "0000995752":
            raise ValueError("J2 authority 2D document is not 0000995752")
        if step_source.get("documentNumber") != "0001217356S":
            raise ValueError("J2 authority STEP document is not 0001217356S")
    return authority


def validate_receiver_interface(repository: Path, interface_path: Path) -> dict[str, Any]:
    document = read_json(interface_path)
    if document.get("schema") != "aicad_receiver_mechanical_interface_v1":
        raise ValueError("unexpected receiver interface schema")
    if document.get("status") != "frozen":
        raise ValueError("receiver interface status is not frozen")

    dimensions = document.get("boardDimensionsMm", {})
    expected_dimensions = {"width": 50.0, "height": 42.0, "thickness": 1.6}
    for key, expected in expected_dimensions.items():
        if not close(dimensions.get(key, float("nan")), expected):
            raise ValueError(f"boardDimensionsMm.{key} is not {expected}")

    source_board_path = validate_artifact(
        repository, interface_path, document.get("sourceBoard", {}), "sourceBoard"
    )
    routes = document.get("frozenRoutes", {})
    routes_path = validate_artifact(repository, interface_path, routes, "frozenRoutes")
    route_source = routes.get("sourceBoard", {})
    validate_artifact(repository, interface_path, route_source, "frozenRoutes.sourceBoard")
    if route_source.get("sha256") != document["sourceBoard"].get("sha256"):
        raise ValueError("sourceBoard SHA does not match frozenRoutes.sourceBoard SHA")

    contract = document.get("coordinateContract", {})
    source = contract.get("source", {})
    mechanical = contract.get("mechanical", {})
    forward = contract.get("forwardTransform", {})
    inverse = contract.get("inverseTransform", {})
    case = contract.get("caseTransform", {})
    if source != {
        "origin": "top-left",
        "xAxis": "right",
        "yAxis": "down",
        "units": "mm",
        "boardHeightMm": 42,
    }:
        raise ValueError("coordinateContract.source is not the controlled KiCad frame")
    if mechanical != {
        "origin": "bottom-left",
        "xAxis": "right",
        "yAxis": "up",
        "units": "mm",
    }:
        raise ValueError("coordinateContract.mechanical is not bottom-left/y-up")
    if forward != {"x": "x_source", "y": "42-y_source"}:
        raise ValueError("coordinateContract.forwardTransform changed")
    if inverse != {"x": "x_mechanical", "y": "42-y_mechanical"}:
        raise ValueError("coordinateContract.inverseTransform changed")
    if case.get("translationMm") != [-25, -21]:
        raise ValueError("coordinateContract.caseTransform translation changed")
    if case.get("x") != "x_mechanical-25" or case.get("y") != "y_mechanical-21":
        raise ValueError("coordinateContract.caseTransform equations changed")

    tests = contract.get("tests", [])
    if not tests:
        raise ValueError("coordinateContract.tests is empty")
    for test in tests:
        if isinstance(test, dict) and test.get("status") not in (None, "pass", "passed"):
            raise ValueError("coordinateContract contains a failed test")
        if isinstance(test, dict) and "passed" in test and test["passed"] is not True:
            raise ValueError("coordinateContract contains a failed test")

    mount_holes = document.get("mountHoles", [])
    if len(mount_holes) != 4:
        raise ValueError("exactly four frozen receiver mount holes are required")
    for index, hole in enumerate(mount_holes):
        source_xy = point(hole.get("sourceCenterMm"), f"mountHoles[{index}].sourceCenterMm")
        mechanical_xy = point(
            hole.get("mechanicalCenterMm"), f"mountHoles[{index}].mechanicalCenterMm"
        )
        case_xy = point(hole.get("caseCenterMm"), f"mountHoles[{index}].caseCenterMm")
        expected_mechanical = (source_xy[0], 42.0 - source_xy[1])
        expected_case = (source_xy[0] - 25.0, 21.0 - source_xy[1])
        if not all(close(a, b) for a, b in zip(mechanical_xy, expected_mechanical)):
            raise ValueError(f"mount hole {hole.get('ref')} forward transform mismatch")
        if not all(close(a, b) for a, b in zip(case_xy, expected_case)):
            raise ValueError(f"mount hole {hole.get('ref')} case transform mismatch")
        if not close(42.0 - mechanical_xy[1], source_xy[1]):
            raise ValueError(f"mount hole {hole.get('ref')} inverse transform mismatch")
        if hole.get("type") != "NPTH" or hole.get("plating") is not False:
            raise ValueError(f"mount hole {hole.get('ref')} is not NPTH")
        if not close(hole.get("finishedDiameterMm", float("nan")), 2.4):
            raise ValueError(f"mount hole {hole.get('ref')} diameter changed")

    connectors = document.get("connectors", [])
    if {row.get("ref") for row in connectors} != {"J1", "J2", "J3", "J4"}:
        raise ValueError("frozen connector set must be exactly J1/J2/J3/J4")
    wall_to_panel = {"-X": "left", "+X": "right", "-Y": "bottom", "+Y": "top"}
    for connector in connectors:
        ref = str(connector["ref"])
        source_xy = point(connector.get("sourceDatumMm"), f"{ref}.sourceDatumMm")
        mechanical_xy = point(
            connector.get("mechanicalDatumMm"), f"{ref}.mechanicalDatumMm"
        )
        case_xy = point(connector.get("caseDatumMm"), f"{ref}.caseDatumMm")
        expected_mechanical = (source_xy[0], 42.0 - source_xy[1])
        expected_case = (source_xy[0] - 25.0, 21.0 - source_xy[1])
        if not all(close(a, b) for a, b in zip(mechanical_xy, expected_mechanical)):
            raise ValueError(f"{ref} forward transform mismatch")
        if not all(close(a, b) for a, b in zip(case_xy, expected_case)):
            raise ValueError(f"{ref} case transform mismatch")
        if connector.get("wallAxis") not in wall_to_panel:
            raise ValueError(f"{ref} wallAxis is invalid")
        if str(connector.get("panel", "")).lower() != wall_to_panel[connector["wallAxis"]]:
            raise ValueError(f"{ref} panel/wallAxis mismatch")
        expected_tangent = case_xy[1] if connector["wallAxis"] in ("-X", "+X") else case_xy[0]
        if not close(connector.get("tangentCenterMm", float("nan")), expected_tangent):
            raise ValueError(f"{ref} tangent center mismatch")
        for key in ("zCenterMm", "widthMm", "heightMm", "cutDepthMm"):
            if float(connector.get(key, 0.0)) <= 0.0:
                raise ValueError(f"{ref}.{key} must be positive")
        radius = float(connector.get("cornerRadiusMm", -1.0))
        if radius < 0.0 or radius > min(float(connector["widthMm"]), float(connector["heightMm"])) / 2:
            raise ValueError(f"{ref}.cornerRadiusMm is invalid")
        validate_connector_authority(repository, interface_path, connector)
    j2 = next(row for row in connectors if row["ref"] == "J2")
    if j2.get("mpn") != "DF13A-5P-1.25H(51)" or j2.get("wallAxis") != "-Y":
        raise ValueError("J2 is not the controlled DF13A bottom-edge interface")

    keepout = document.get("rfKeepout", {})
    source_polygon = keepout.get("sourcePolygonMm", [])
    mechanical_polygon = keepout.get("mechanicalPolygonMm", [])
    case_polygon = keepout.get("casePolygonMm", [])
    if not source_polygon or not (
        len(source_polygon) == len(mechanical_polygon) == len(case_polygon)
    ):
        raise ValueError("RF keep-out polygons are incomplete")
    for index, raw_source in enumerate(source_polygon):
        source_xy = point(raw_source, f"rfKeepout.sourcePolygonMm[{index}]")
        mechanical_xy = point(
            mechanical_polygon[index], f"rfKeepout.mechanicalPolygonMm[{index}]"
        )
        case_xy = point(case_polygon[index], f"rfKeepout.casePolygonMm[{index}]")
        if not all(close(a, b) for a, b in zip(mechanical_xy, (source_xy[0], 42.0 - source_xy[1]))):
            raise ValueError("RF keep-out forward transform mismatch")
        if not all(close(a, b) for a, b in zip(case_xy, (source_xy[0] - 25.0, 21.0 - source_xy[1]))):
            raise ValueError("RF keep-out case transform mismatch")

    evidence = document.get("consistencyEvidence", {})
    if evidence.get("boardShaMatchesRoutes") is not True:
        raise ValueError("board/routes SHA consistency evidence failed")
    if evidence.get("roundTripCoordinateTests") is not True:
        raise ValueError("round-trip coordinate evidence failed")
    native_drc = evidence.get("nativeDrc", {})
    native_drc_path = validate_artifact(
        repository, interface_path, native_drc, "consistencyEvidence.nativeDrc"
    )
    for key in ("violations", "unconnected", "footprintErrors", "exclusions", "suppressions"):
        if int(native_drc.get(key, -1)) != 0:
            raise ValueError(f"native DRC {key} is not zero")

    return {
        "document": document,
        "interfaceSha256": sha256_file(interface_path),
        "sourceBoardPath": source_board_path,
        "routesPath": routes_path,
        "nativeDrcPath": native_drc_path,
    }


def normalized_design_interface(
    current: dict[str, Any], validated: dict[str, Any]
) -> dict[str, Any]:
    source = validated["document"]
    result = dict(current)
    dimensions = source["boardDimensionsMm"]
    board = dict(result["board"])
    board.update(
        {
            "outline_x": float(dimensions["width"]),
            "outline_y": float(dimensions["height"]),
            "thickness": float(dimensions["thickness"]),
            "mount_holes": [
                {
                    "ref": row["ref"],
                    "x": float(row["mechanicalCenterMm"][0]),
                    "y": float(row["mechanicalCenterMm"][1]),
                    "case_center": [float(value) for value in row["caseCenterMm"]],
                    "finished_diameter": float(row["finishedDiameterMm"]),
                    "tolerance_mm": row["toleranceMm"],
                    "type": row["type"],
                    "plating": row["plating"],
                }
                for row in source["mountHoles"]
            ],
        }
    )
    component_heights = source.get("componentHeights", [])
    numeric_heights = [
        float(row[key])
        for row in component_heights
        for key in ("heightMm", "topHeightMm", "maximumHeightMm")
        if key in row
    ]
    if numeric_heights:
        board["maximum_top_component_height"] = max(numeric_heights)

    openings = []
    for row in source["connectors"]:
        openings.append(
            {
                "ref": row["ref"],
                "manufacturer": row["manufacturer"],
                "mpn": row["mpn"],
                "wall_axis": row["wallAxis"],
                "panel": row["panel"],
                "panel_normal": row["panelNormal"],
                "tangent_axis": row["tangentAxis"],
                "mechanical_center": [
                    float(row["caseDatumMm"][0]),
                    float(row["caseDatumMm"][1]),
                    float(row["zCenterMm"]),
                ],
                "source_datum": row["sourceDatumMm"],
                "board_mechanical_datum": row["mechanicalDatumMm"],
                "panel_width": float(row["widthMm"]),
                "panel_height": float(row["heightMm"]),
                "corner_radius": float(row["cornerRadiusMm"]),
                "cut_depth": float(row["cutDepthMm"]),
                "tolerances_mm": row["tolerancesMm"],
                "mating_direction": row["matingDirection"],
                "body_envelope_mm": row["bodyEnvelopeMm"],
                "mating_envelope_mm": row["matingEnvelopeMm"],
                "unmate_clearance_mm": row["unmateClearanceMm"],
                "official_drawing": row["officialDrawing"],
            }
        )

    result.update(
        {
            "interface_status": "frozen_electronics_native_drc",
            "interface_sha256": validated["interfaceSha256"],
            "source_board_sha256": source["sourceBoard"]["sha256"],
            "frozen_routes_sha256": source["frozenRoutes"]["sha256"],
            "native_drc_sha256": source["consistencyEvidence"]["nativeDrc"]["sha256"],
            "coordinate_mapping": "KiCad top-left/y-down -> board bottom-left/y-up by x'=x,y'=42-y; then case-center translation (-25,-21)",
            "coordinate_contract": source["coordinateContract"],
            "board": board,
            "connector_openings": openings,
            "rf_keepout": {
                "source_status": "frozen_electronics_native_drc",
                "source_xy_polygon": source["rfKeepout"]["sourcePolygonMm"],
                "board_xy_polygon": source["rfKeepout"]["mechanicalPolygonMm"],
                "case_xy_polygon": source["rfKeepout"]["casePolygonMm"],
                "height_mm": source["rfKeepout"]["heightMm"],
                "mechanical_rules": current["rf_keepout"]["mechanical_rules"],
            },
        }
    )
    return result


def wand_hashes(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for folder in (root / "outputs", root / "reports"):
        for path in folder.rglob("*"):
            if path.is_file() and path.name.startswith(WAND_FILE_PREFIXES):
                rows[path.relative_to(root).as_posix()] = sha256_file(path)
    return rows


def run_native_phase(root: Path) -> None:
    import pythoncom
    import win32com.client

    import factory_solidworks_export as swx

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
        for part_id in PART_IDS:
            swx.export_part(sw, root, part_id, native_tool)
        swx.export_assembly(sw, root, ASSEMBLY_ID, native_tool)
        for part_id in PART_IDS:
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


def is_receiver_frame(frame_id: str) -> bool:
    return frame_id.startswith(("MW-M-101:", "MW-M-102:", "MW-A-101"))


def run_drawing_phase(root: Path) -> None:
    import factory_drawings as base_drawings
    import factory_release_drawings as drawings
    import factory_release_geometry as geometry

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
        for part_id in PART_IDS
    ]
    new_index.extend(
        [
            drawings.generate_assembly_drawing(
                "MW-A-101",
                "RECEIVER ENCLOSURE ASSEMBLY",
                "assembly",
                geometry.make_receiver_assembly(False),
                output / "MW-A-101_receiver_assembly.dxf",
                new_sections,
            ),
            drawings.generate_assembly_drawing(
                "MW-A-101-EX",
                "RECEIVER ENCLOSURE EXPLODED",
                "exploded",
                geometry.make_receiver_assembly(True),
                output / "MW-A-101_receiver_exploded.dxf",
                new_sections,
            ),
            drawings.generate_assembly_drawing(
                "MW-A-101-SE",
                "RECEIVER ENCLOSURE SECTION / INTERFACE",
                "section_interface",
                geometry.make_receiver_assembly(False),
                output / "MW-A-101_receiver_section_interface.dxf",
                new_sections,
            ),
        ]
    )

    new_numbers = {row["drawing_number"] for row in new_index}
    merged_index = [row for row in old_index if row["drawing_number"] not in new_numbers]
    merged_index.extend(new_index)
    frames = [
        row for row in old_audit["frames"] if not is_receiver_frame(row["frame_id"])
    ] + list(base_drawings.TEXT_FRAMES)
    closures = [
        row for row in old_audit["inputClosure"] if not is_receiver_frame(row["frameId"])
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

    merged_sections = [
        row
        for row in old_sections
        if row.get("subjectId") not in {"MW-M-101", "MW-M-102", "MW-A-101"}
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
    section_report = {
        "schema": "aicad_factory_brep_section_intersections_v2",
        "requiredFeatureIds": required,
        "coveredFeatureIds": covered,
        "missingFeatureIds": missing,
        "sections": merged_sections,
        "passed": section_passed,
    }
    if not audit["passed"] or not section_passed:
        raise RuntimeError("receiver drawing text/section audit failed")
    write_json(
        reports / "drawing-index.json",
        {"schema": "aicad_factory_drawing_index_v2", "drawings": merged_index},
    )
    write_json(reports / "drawing-text-frame-audit.json", audit)
    write_json(reports / "feature-dimension-catalog.json", drawings.feature_dimension_catalog())
    write_json(reports / "brep-section-intersection-report.json", section_report)


def document_paths(root: Path, assembly_id: str) -> dict[str, Path]:
    folder = root / "outputs" / "documents"
    return {
        "bom": folder / f"{assembly_id}_manufacturing-bom.json",
        "positions": folder / f"{assembly_id}_assembly-positions.json",
        "moldingInput": folder / f"{assembly_id}_molding-input.json",
        "assemblyWorkInstruction": folder / f"{assembly_id}_assembly-work-instruction.pdf",
        "inspectionPlan": folder / f"{assembly_id}_inspection-plan.pdf",
    }


def run_package_phase(root: Path) -> None:
    from build123d import export_step

    import build_factory_package as package
    import factory_release_geometry as geometry
    import factory_release_previews as previews

    old_preview_manifest = read_json(root / "reports" / "visual-preview-manifest.json")
    rows: list[dict[str, Any]] = []
    for row in old_preview_manifest["previews"]:
        if row["subjectId"] in {*PART_IDS, ASSEMBLY_ID}:
            continue
        copy = dict(row)
        copy["path"] = str((root / copy["path"]).resolve())
        copy["previewOf"] = str((root / copy["previewOf"]).resolve())
        rows.append(copy)

    preview_output = root / "outputs" / "previews"
    for part_id in PART_IDS:
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
    export_step(geometry.make_receiver_assembly(True), exploded_step)
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
    for role in ("assemblyDrawing", "explodedDrawing", "sectionDrawing"):
        dxf_path = root / "outputs" / "2d" / config[role]
        row = previews.render_dxf_preview(
            ASSEMBLY_ID,
            dxf_path,
            preview_output / f"{Path(config[role]).stem}_preview.png",
        )
        row["drawingRole"] = role
        rows.append(row)
    previews.write_preview_manifest(root, rows)

    receiver_documents = package.build_assembly_documents(root, ASSEMBLY_ID)
    _, receiver_interference = package.build_interference(
        root, ASSEMBLY_ID, receiver_documents["positions"]
    )
    documents = {
        "MW-A-001": document_paths(root, "MW-A-001"),
        ASSEMBLY_ID: receiver_documents,
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
        "MW-A-001": root / "reports" / "native" / "MW-A-001_interference-log.json",
        ASSEMBLY_ID: receiver_interference,
    }
    index = package.native_logs_and_index(
        root, documents, preview_paths, interference_logs
    )
    package.build_reviewer(root, rows, index)
    receiver_status = geometry.P["interfaces"]["receiver_enclosure"]["interface_status"]
    if receiver_status != "frozen_electronics_native_drc":
        raise RuntimeError("normalized receiver interface is not frozen")
    package.write_json(
        root / "reports" / "factory-package-readiness.json",
        {
            "schema": "aicad_factory_package_readiness_v2",
            "packageId": geometry.P["package_id"],
            "revision": geometry.P["revision"],
            "partCount": len(index["parts"]),
            "assemblyCount": len(index["assemblies"]),
            "nativePartReopenPassed": True,
            "nativeAssemblyReopenPassed": True,
            "unexpectedInterferenceCount": 0,
            "drawingTextOverflowCount": 0,
            "previewCount": len(rows),
            "receiverInterfaceStatus": receiver_status,
            "receiverInterfaceFrozen": True,
            "technicalPackageReady": True,
            "releaseBasis": "DFM/RFQ input; engineering authorization remains controlled by release locks",
        },
    )
    package.build_delivery_manifest(root, index, rows)
    package.build_manifest(root)


def remove_source_cache(root: Path) -> None:
    cache = (root / "source" / "__pycache__").resolve()
    source = (root / "source").resolve()
    if cache.parent != source:
        raise RuntimeError("refusing to clean an unexpected cache path")
    if cache.is_dir():
        shutil.rmtree(cache)


def phase_command(script: Path, root: Path, phase: str) -> None:
    subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--phase", phase],
        check=True,
    )


def execute_finalization(root: Path, interface_path: Path, validated: dict[str, Any]) -> None:
    design_path = root / "factory-design-input.json"
    original_design = design_path.read_bytes()
    design = json.loads(original_design.decode("utf-8"))
    design["interfaces"]["receiver_enclosure"] = normalized_design_interface(
        design["interfaces"]["receiver_enclosure"], validated
    )
    before_wand = wand_hashes(root)
    script = Path(__file__).resolve()
    try:
        write_json(design_path, design)
        for phase in ("native", "drawings", "package"):
            phase_command(script, root, phase)
        remove_source_cache(root)
        after_wand = wand_hashes(root)
        if after_wand != before_wand:
            changed = sorted(set(before_wand) | set(after_wand))
            changed = [key for key in changed if before_wand.get(key) != after_wand.get(key)]
            raise RuntimeError(f"wand artifact SHA changed during receiver-only run: {changed}")
        test_path = root.parents[3] / "tests" / "test_magic_wand_factory_mechanical.py"
        subprocess.run([sys.executable, str(test_path)], cwd=root.parents[3], check=True)
    except Exception:
        design_path.write_bytes(original_design)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed receiver mechanical finalizer")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--interface", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--phase", choices=("native", "drawings", "package"))
    args = parser.parse_args()
    root = args.root.resolve()
    if args.phase:
        {"native": run_native_phase, "drawings": run_drawing_phase, "package": run_package_phase}[
            args.phase
        ](root)
        return 0
    if args.interface is None:
        parser.error("--interface is required unless --phase is used")
    interface_path = args.interface.resolve()
    repository = root.parents[3]
    validated = validate_receiver_interface(repository, interface_path)
    if not args.validate_only:
        execute_finalization(root, interface_path, validated)
    print(
        json.dumps(
            {
                "schema": validated["document"]["schema"],
                "status": validated["document"]["status"],
                "interfaceSha256": validated["interfaceSha256"],
                "sourceBoardSha256": validated["document"]["sourceBoard"]["sha256"],
                "routesSha256": validated["document"]["frozenRoutes"]["sha256"],
                "validatedOnly": args.validate_only,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
