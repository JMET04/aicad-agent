"""Strict adapters from domain delivery manifests to the frozen core schema."""

from __future__ import annotations

import copy
import math
import json
import re
from typing import Any


PART_ROLES = {
    "nativeCad",
    "step",
    "manufacturingDrawing",
    "drawingPreview",
    "modelPreview",
    "nativeReopenLog",
}
ASSEMBLY_ROLES = {
    "nativeAssembly",
    "step",
    "assemblyDrawing",
    "explodedDrawing",
    "sectionDrawing",
    "assemblyPreview2d",
    "assemblyPreview3d",
    "assemblyWorkInstruction",
    "inspectionPlan",
    "moldingInput",
    "bom",
    "positions",
    "interferenceLog",
    "nativeReopenLog",
}

WAND_INTERFACE_SCHEMA = "aicad_wand_electromechanical_interface_v1"
WAND_INTERFACE_STATUS = "FROZEN"
WAND_REQUIRED_REFS = {"SW1", "J1", "J2", "J3", "U1", "L1", "F1", "H1", "H2"}
WAND_ABSENT_REFS = {"H3", "H4"}
WAND_USB_CONTACT_NAMES = {
    "A1", "B12", "A4", "B9", "A5", "B5", "A6", "B6",
    "A7", "B7", "A8", "B8", "A9", "B4", "A12", "B1",
}
WAND_PER_REF_COMMON = {
    "ref", "manufacturer", "mpn", "authorityEvidence", "sourceCenterMm",
    "caseCenterMm", "rotationDeg", "bodyEnvelopeMm", "maximumHeightMm",
    "padOrHoleGeometry", "roundTripCoordinateEvidence",
}


def _domain(manifest: dict[str, Any], key: str) -> Any:
    value = manifest.get(key)
    if value is not None:
        return value
    mechanical = manifest.get("mechanical")
    return mechanical.get(key) if isinstance(mechanical, dict) else None


def _coordinate(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("mechanical coordinateSystem must be an object")
    required = (
        "id", "units", "handedness", "origin", "xAxis", "yAxis", "zAxis", "description"
    )
    if all(key in row for key in required):
        return {key: copy.deepcopy(row[key]) for key in required}
    identifier = row.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("mechanical coordinateSystem.id is missing")
    origin_text = row.get("origin")
    positive_z = row.get("positive_z", row.get("positiveZ"))
    positive_y = row.get("positive_y", row.get("positiveY"))
    if not all(isinstance(value, str) and value.strip() for value in (origin_text, positive_z, positive_y)):
        raise ValueError("mechanical textual origin/+Y/+Z datum definition is incomplete")
    return {
        "id": identifier,
        "units": "mm",
        "handedness": "right",
        "origin": [0.0, 0.0, 0.0],
        "xAxis": [1.0, 0.0, 0.0],
        "yAxis": [0.0, 1.0, 0.0],
        "zAxis": [0.0, 0.0, 1.0],
        "description": (
            f"Origin: {origin_text}; +Y: {positive_y}; +Z: {positive_z}; "
            "+X completes the documented right-handed manufacturing basis."
        ),
    }


def _process(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("mechanical part process is missing")
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "_", value.strip()).strip("_.:-")
    if not normalized or len(normalized) > 127:
        raise ValueError(f"mechanical process is not a portable identifier: {value!r}")
    return normalized.casefold()


def _basic_ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not {"path", "size", "sha256"}.issubset(value):
        raise ValueError(f"{label} lacks an exact evidence reference")
    return {key: copy.deepcopy(value[key]) for key in ("path", "size", "sha256")}


def _preview(
    subject: dict[str, Any],
    *,
    preview_role: str,
    target_role: str,
    subject_id: str,
) -> dict[str, Any]:
    artifacts = subject.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError(f"{subject_id} artifacts are missing")
    preview = _basic_ref(artifacts.get(preview_role), f"{subject_id}.{preview_role}")
    target = _basic_ref(artifacts.get(target_role), f"{subject_id}.{target_role}")
    source_rows = subject.get("previews")
    matches = [
        row
        for row in source_rows
        if isinstance(row, dict)
        and row.get("path") == preview["path"]
        and row.get("previewOfRole") == target_role
        and row.get("subjectId") == subject_id
    ] if isinstance(source_rows, list) else []
    embedded = artifacts.get(preview_role)
    if isinstance(embedded, dict) and {
        "previewOfRole", "subjectId", "sourceSha256"
    }.issubset(embedded):
        binding = embedded
    elif len(matches) == 1:
        binding = matches[0]
    else:
        raise ValueError(
            f"{subject_id}.{preview_role} needs one exact subject/role preview binding"
        )
    if binding.get("sourceSha256") != target["sha256"]:
        raise ValueError(f"{subject_id}.{preview_role} source SHA does not match {target_role}")
    return {
        **preview,
        "previewOfRole": target_role,
        "subjectId": subject_id,
        "sourceSha256": target["sha256"],
    }


def adapt_mechanical_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    coordinate_value = manifest.get("coordinateSystems", manifest.get("coordinateSystem"))
    coordinate_rows = coordinate_value if isinstance(coordinate_value, list) else [coordinate_value]
    coordinates = [_coordinate(row) for row in coordinate_rows]
    if len({row["id"] for row in coordinates}) != len(coordinates):
        raise ValueError("mechanical coordinate-system IDs are duplicated")
    coordinate_id = coordinates[0]["id"]
    raw_parts = _domain(manifest, "parts")
    raw_assemblies = _domain(manifest, "assemblies")
    if not isinstance(raw_parts, list) or not isinstance(raw_assemblies, list):
        raise ValueError("mechanical parts/assemblies arrays are missing")
    parts: list[dict[str, Any]] = []
    for raw in raw_parts:
        if not isinstance(raw, dict):
            raise ValueError("mechanical part row must be an object")
        part_id = raw.get("partId")
        if not isinstance(part_id, str) or not part_id:
            raise ValueError("mechanical partId is missing")
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, dict) or not PART_ROLES.issubset(artifacts):
            raise ValueError(f"{part_id} core artifact-role closure is incomplete")
        core_artifacts = {
            role: _basic_ref(artifacts[role], f"{part_id}.{role}")
            for role in sorted(PART_ROLES - {"drawingPreview", "modelPreview"})
        }
        core_artifacts["drawingPreview"] = _preview(
            raw,
            preview_role="drawingPreview",
            target_role="manufacturingDrawing",
            subject_id=part_id,
        )
        core_artifacts["modelPreview"] = _preview(
            raw,
            preview_role="modelPreview",
            target_role="step",
            subject_id=part_id,
        )
        parts.append(
            {
                "partId": part_id,
                "revision": raw.get("revision"),
                "coordinateSystemId": raw.get("coordinateSystemId", coordinate_id),
                "supplierId": "unassigned_rfq_recipient",
                "process": _process(raw.get("process")),
                "artifacts": core_artifacts,
            }
        )
    assemblies: list[dict[str, Any]] = []
    for raw in raw_assemblies:
        if not isinstance(raw, dict):
            raise ValueError("mechanical assembly row must be an object")
        assembly_id = raw.get("assemblyId")
        if not isinstance(assembly_id, str) or not assembly_id:
            raise ValueError("mechanical assemblyId is missing")
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, dict) or not ASSEMBLY_ROLES.issubset(artifacts):
            raise ValueError(f"{assembly_id} core artifact-role closure is incomplete")
        core_artifacts = {
            role: _basic_ref(artifacts[role], f"{assembly_id}.{role}")
            for role in sorted(ASSEMBLY_ROLES - {"assemblyPreview2d", "assemblyPreview3d"})
        }
        core_artifacts["assemblyPreview2d"] = _preview(
            raw,
            preview_role="assemblyPreview2d",
            target_role="assemblyDrawing",
            subject_id=assembly_id,
        )
        core_artifacts["assemblyPreview3d"] = _preview(
            raw,
            preview_role="assemblyPreview3d",
            target_role="step",
            subject_id=assembly_id,
        )
        assemblies.append(
            {
                "assemblyId": assembly_id,
                "revision": raw.get("revision"),
                "coordinateSystemId": raw.get("coordinateSystemId", coordinate_id),
                "supplierId": "unassigned_rfq_recipient",
                "artifacts": core_artifacts,
            }
        )
    return {"coordinateSystems": coordinates, "parts": parts, "assemblies": assemblies}


def manifests_equivalent(primary: dict[str, Any], compatibility: dict[str, Any]) -> bool:
    """The two mechanical manifests may differ only in their schema name."""
    left = copy.deepcopy(primary)
    right = copy.deepcopy(compatibility)
    left.pop("schema", None)
    right.pop("schema", None)
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _point2(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be one [x,y] point")
    return _number(value[0], label + "[0]"), _number(value[1], label + "[1]")


def _point_close(actual: tuple[float, float], expected: tuple[float, float], label: str) -> None:
    if any(abs(left - right) > 1e-6 for left, right in zip(actual, expected)):
        raise ValueError(f"{label} transform mismatch: {actual!r} != {expected!r}")


def _mapped_point(row: dict[str, Any], label: str) -> None:
    source = _point2(row.get("sourceKicadXY"), label + ".sourceKicadXY")
    board = _point2(row.get("boardBottomLeftXY"), label + ".boardBottomLeftXY")
    case = _point2(row.get("caseMechanicalXY"), label + ".caseMechanicalXY")
    if not (0.0 <= source[0] <= 50.0 and 0.0 <= source[1] <= 42.0):
        raise ValueError(f"{label}.sourceKicadXY lies outside the 50x42 mm board")
    _point_close(board, (source[0], 42.0 - source[1]), label + ".source_to_board")
    _point_close(case, (board[0] - 25.0, board[1] - 21.0), label + ".board_to_case")
    reverse_board = (case[0] + 25.0, case[1] + 21.0)
    reverse_source = (reverse_board[0], 42.0 - reverse_board[1])
    _point_close(reverse_board, board, label + ".case_to_board")
    _point_close(reverse_source, source, label + ".board_to_source")
    if row.get("transformMatch") is not True:
        raise ValueError(f"{label}.transformMatch must be true after recomputation")


def validate_receiver_coordinate_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("mechanical receiverInterface must be an object")
    if value.get("status") != "frozen_electronics_native_drc":
        raise ValueError("mechanical receiverInterface.status is not frozen_electronics_native_drc")
    contract = value.get("coordinateContract")
    if not isinstance(contract, dict):
        raise ValueError("mechanical receiverInterface.coordinateContract is missing")
    expected_frames = {
        "source": {"id": "KICAD_BOARD_XY", "origin": "top-left", "x": "right", "y": "down"},
        "intermediate": {"id": "PCB_BOTTOM_LEFT_XY", "origin": "bottom-left", "x": "right", "y": "up"},
        "target": {"id": "RECEIVER_CASE_XY", "origin": "case-center", "x": "right", "y": "up"},
    }
    for key, expected in expected_frames.items():
        frame = contract.get(key)
        if not isinstance(frame, dict) or any(frame.get(name) != datum for name, datum in expected.items()):
            raise ValueError(f"receiver coordinateContract.{key} frame is not the frozen basis")
        if frame.get("units", "mm") != "mm":
            raise ValueError(f"receiver coordinateContract.{key}.units must be mm")
    board_size = contract.get("boardSizeMm")
    if not isinstance(board_size, list) or len(board_size) != 3:
        raise ValueError("receiver coordinateContract.boardSizeMm must be [50,42,1.6]")
    if any(abs(_number(actual, "boardSizeMm") - expected) > 1e-6 for actual, expected in zip(board_size, (50.0, 42.0, 1.6))):
        raise ValueError("receiver coordinateContract.boardSizeMm must be [50,42,1.6]")
    equations = contract.get("equations")
    if equations != [
        "x_board=x_k",
        "y_board=42-y_k",
        "x_case=x_board-25",
        "y_case=y_board-21",
    ]:
        raise ValueError("receiver coordinate transform equations are incomplete or reordered")
    shift = _point2(contract.get("caseShiftMm"), "coordinateContract.caseShiftMm")
    _point_close(shift, (-25.0, -21.0), "coordinateContract.caseShiftMm")
    if contract.get("transformVerified") is not True:
        raise ValueError("receiver coordinateContract.transformVerified must be true")

    holes = value.get("holes")
    connectors = value.get("connectors")
    if not isinstance(holes, list) or not holes or not isinstance(connectors, list) or not connectors:
        raise ValueError("receiver interface needs non-empty holes and connectors")
    hole_ids: set[str] = set()
    for index, row in enumerate(holes):
        label = f"receiverInterface.holes[{index}]"
        required = {
            "id", "sourceKicadXY", "boardBottomLeftXY", "caseMechanicalXY",
            "diameterMm", "transformMatch",
        }
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"{label} is incomplete")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in hole_ids:
            raise ValueError(f"{label}.id is missing or duplicated")
        hole_ids.add(identifier)
        if _number(row.get("diameterMm"), label + ".diameterMm") <= 0:
            raise ValueError(f"{label}.diameterMm must be positive")
        _mapped_point(row, label)

    connector_ids: set[str] = set()
    for index, row in enumerate(connectors):
        label = f"receiverInterface.connectors[{index}]"
        required = {
            "ref", "sourceKicadXY", "boardBottomLeftXY", "caseMechanicalXY",
            "panel", "panelNormal", "tangentCenterMm", "zCenterMm",
            "openingWidthMm", "openingHeightMm", "cornerRadiusMm", "cutDepthMm",
            "transformMatch",
        }
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"{label} is incomplete")
        identifier = row.get("ref")
        if not isinstance(identifier, str) or not identifier or identifier in connector_ids:
            raise ValueError(f"{label}.ref is missing or duplicated")
        connector_ids.add(identifier)
        for key in (
            "tangentCenterMm", "zCenterMm", "openingWidthMm", "openingHeightMm",
            "cornerRadiusMm", "cutDepthMm",
        ):
            number = _number(row.get(key), label + "." + key)
            if key in {"openingWidthMm", "openingHeightMm", "cutDepthMm"} and number <= 0:
                raise ValueError(f"{label}.{key} must be positive")
            if key == "cornerRadiusMm" and number < 0:
                raise ValueError(f"{label}.{key} cannot be negative")
        if not isinstance(row.get("panel"), str) or not isinstance(row.get("panelNormal"), str):
            raise ValueError(f"{label} panel metadata is missing")
        _mapped_point(row, label)

    keepout = value.get("rfKeepout")
    if not isinstance(keepout, dict) or keepout.get("transformMatch") is not True:
        raise ValueError("receiverInterface.rfKeepout is missing or not transform-matched")
    source_polygon = keepout.get("sourceKicadPolygon")
    board_polygon = keepout.get("boardBottomLeftPolygon")
    case_polygon = keepout.get("caseMechanicalPolygon")
    if not all(isinstance(row, list) for row in (source_polygon, board_polygon, case_polygon)):
        raise ValueError("receiver RF keepout polygon arrays are missing")
    if len(source_polygon) < 3 or len({len(source_polygon), len(board_polygon), len(case_polygon)}) != 1:
        raise ValueError("receiver RF keepout polygon closure is incomplete")
    for index, (source_value, board_value, case_value) in enumerate(zip(source_polygon, board_polygon, case_polygon)):
        source = _point2(source_value, f"rfKeepout.source[{index}]")
        board = _point2(board_value, f"rfKeepout.board[{index}]")
        case = _point2(case_value, f"rfKeepout.case[{index}]")
        _point_close(board, (source[0], 42.0 - source[1]), f"rfKeepout.source_to_board[{index}]")
        _point_close(case, (board[0] - 25.0, board[1] - 21.0), f"rfKeepout.board_to_case[{index}]")
        reverse_source = (case[0] + 25.0, 42.0 - (case[1] + 21.0))
        _point_close(reverse_source, source, f"rfKeepout.case_to_source[{index}]")
    return {
        "coordinateContract": copy.deepcopy(contract),
        "holes": copy.deepcopy(holes),
        "connectors": copy.deepcopy(connectors),
        "rfKeepout": copy.deepcopy(keepout),
    }


def receiver_interface_semantics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("sourceBoard"), dict):
        raise ValueError("receiver interface sourceBoard is missing")
    validated = validate_receiver_coordinate_contract(
        {**value, "status": "frozen_electronics_native_drc"}
    )
    return {"sourceBoard": copy.deepcopy(value["sourceBoard"]), **validated}
def _required_fields(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = sorted(fields - set(value))
    if missing:
        raise ValueError(f"{label} is missing required fields: {missing}")
    return value


def _point3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be one [x,y,z] point")
    return (
        _number(value[0], label + "[0]"),
        _number(value[1], label + "[1]"),
        _number(value[2], label + "[2]"),
    )


def _exact_kind_ref(value: Any, label: str) -> dict[str, Any]:
    row = _required_fields(value, {"path", "size", "sha256", "kind"}, label)
    if not isinstance(row["path"], str) or not row["path"]:
        raise ValueError(f"{label}.path must be non-empty")
    size = row["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError(f"{label}.size must be a positive integer")
    digest = row["sha256"]
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ValueError(f"{label}.sha256 must be one lowercase SHA-256")
    if not isinstance(row["kind"], str) or not row["kind"].strip():
        raise ValueError(f"{label}.kind must be a non-empty controlled identity")
    return row


def _positive_sequence(value: Any, length: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} must contain exactly {length} numbers")
    result = tuple(_number(item, label) for item in value)
    if any(item <= 0.0 for item in result):
        raise ValueError(f"{label} values must be positive")
    return result


def _same_artifact_identity(left: Any, right: Any) -> bool:
    keys = ("path", "size", "sha256", "kind")
    return isinstance(left, dict) and isinstance(right, dict) and all(
        left.get(key) == right.get(key) for key in keys
    )


def _wand_source_to_case(row: dict[str, Any], label: str) -> None:
    source_x, source_y = _point2(row.get("sourceCenterMm"), label + ".sourceCenterMm")
    case_x, case_y, case_z = _point3(row.get("caseCenterMm"), label + ".caseCenterMm")
    if not (0.0 <= source_x <= 15.0 and 0.0 <= source_y <= 80.0):
        raise ValueError(f"{label}.sourceCenterMm lies outside the 15x80 mm board")
    _point_close((case_x, case_z), (source_x - 7.5, source_y + 9.0), label + ".source_to_case")
    _point_close((case_x + 7.5, case_z - 9.0), (source_x, source_y), label + ".case_to_source")
    if not math.isfinite(case_y):
        raise ValueError(f"{label}.caseCenterMm[1] must be finite")
    evidence = row.get("roundTripCoordinateEvidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("passed") is not True
        or _number(evidence.get("toleranceMm"), label + ".roundTripCoordinateEvidence.toleranceMm") > 1e-6
    ):
        raise ValueError(f"{label}.roundTripCoordinateEvidence did not prove the 1e-6 mm round trip")


def validate_wand_coordinate_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("wand interface must be an object")
    contract = value.get("coordinateContract")
    if not isinstance(contract, dict):
        raise ValueError("wand coordinateContract is missing")
    expected_source = {
        "origin": "top-left",
        "xAxis": "right",
        "yAxis": "down",
        "units": "mm",
        "boardWidthMm": 15.0,
        "boardHeightMm": 80.0,
    }
    if contract.get("source") != expected_source:
        raise ValueError("wand coordinateContract.source is not the frozen top-left/right/down basis")
    if contract.get("forwardTransform") != {
        "X": "x_source-7.5",
        "Y": "heightFromBCu",
        "Z": "y_source+9.0",
    }:
        raise ValueError("wand forward coordinate transform changed")
    if contract.get("inverseTransform") != {
        "x_source": "X+7.5",
        "y_source": "Z-9.0",
        "heightFromBCu": "Y",
    }:
        raise ValueError("wand inverse coordinate transform changed")
    tolerance = _number(
        contract.get("requiredRoundTripToleranceMm"),
        "wand coordinateContract.requiredRoundTripToleranceMm",
    )
    if tolerance <= 0.0 or tolerance > 1e-6:
        raise ValueError("wand coordinate round-trip tolerance must be positive and no looser than 1e-6 mm")
    tests = contract.get("roundTripTests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("wand coordinateContract.roundTripTests must be non-empty")
    for index, row in enumerate(tests):
        if not isinstance(row, dict) or row.get("passed") is not True:
            raise ValueError(f"wand coordinateContract.roundTripTests[{index}] did not pass")
        if {"sourceCenterMm", "caseCenterMm"}.issubset(row):
            _wand_source_to_case(
                {
                    **row,
                    "roundTripCoordinateEvidence": {
                        "passed": True,
                        "toleranceMm": tolerance,
                    },
                },
                f"wand coordinateContract.roundTripTests[{index}]",
            )
    return copy.deepcopy(contract)


def _wand_ref_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("wand refs must be an array of objects")
    identifiers = [row.get("ref") for row in value]
    if (
        any(not isinstance(identifier, str) or not identifier for identifier in identifiers)
        or len(identifiers) != len(set(identifiers))
        or set(identifiers) != WAND_REQUIRED_REFS
    ):
        raise ValueError(f"wand refs must be exactly {sorted(WAND_REQUIRED_REFS)}")
    return {str(row["ref"]): row for row in value}


def _validate_wand_switch(row: dict[str, Any]) -> None:
    required = {
        "freeHeightMm", "travelMm", "forceN", "actuatorCenterCaseMm",
        "actuationNormal", "fourPhysicalPadGeometry", "logicalTerminalPairMap",
        "allowedPreloadMm", "allowedOvertravelMm",
    }
    _required_fields(row, required, "wand SW1")
    if row.get("manufacturer") != "ALPS Alpine" or row.get("mpn") != "SKQGAFE010":
        raise ValueError("wand SW1 must be the controlled ALPS Alpine SKQGAFE010")
    _point_close(_point2(row["sourceCenterMm"], "wand SW1.sourceCenterMm"), (7.5, 63.0), "wand SW1 source")
    if abs(_number(row.get("rotationDeg"), "wand SW1.rotationDeg") - 90.0) > 1e-6:
        raise ValueError("wand SW1 rotation must be 90 degrees")
    if abs(_number(row["freeHeightMm"], "wand SW1.freeHeightMm") - 1.5) > 1e-6:
        raise ValueError("wand SW1 free height must be 1.5 mm")
    if abs(_number(row["travelMm"], "wand SW1.travelMm") - 0.25) > 1e-6:
        raise ValueError("wand SW1 travel must be 0.25 mm")
    if _number(row["forceN"], "wand SW1.forceN") <= 0.0:
        raise ValueError("wand SW1 force must be positive")
    _point3(row["actuatorCenterCaseMm"], "wand SW1.actuatorCenterCaseMm")
    if not isinstance(row["actuationNormal"], str) or not row["actuationNormal"]:
        raise ValueError("wand SW1 actuation normal is missing")
    pads = row["fourPhysicalPadGeometry"]
    if not isinstance(pads, list) or len(pads) != 4:
        raise ValueError("wand SW1 must preserve all four physical pads")
    pairs = row["logicalTerminalPairMap"]
    if not isinstance(pairs, list) or len(pairs) != 2:
        raise ValueError("wand SW1 must preserve the two logical terminal pairs")
    for key in ("allowedPreloadMm", "allowedOvertravelMm"):
        if _number(row[key], "wand SW1." + key) < 0.0:
            raise ValueError(f"wand SW1.{key} cannot be negative")


def _validate_wand_j1(row: dict[str, Any]) -> None:
    required = {
        "officialDrawingNumber", "sixteenContactPads", "fourShellDipStakes",
        "locatingHoles", "matingFaceMm", "matingDirection", "matingEnvelopeMm",
        "unmateClearanceMm", "panelOpening",
    }
    _required_fields(row, required, "wand J1")
    if row.get("manufacturer") != "JAE" or row.get("mpn") != "DX07S016JA1R1500":
        raise ValueError("wand J1 must be JAE DX07S016JA1R1500")
    if row.get("officialDrawingNumber") != "SJ121837":
        raise ValueError("wand J1 drawing authority must be SJ121837")
    _point_close(_point2(row["sourceCenterMm"], "wand J1.sourceCenterMm"), (12.5, 38.0), "wand J1 source")
    if abs(_number(row.get("rotationDeg"), "wand J1.rotationDeg") - 90.0) > 1e-6:
        raise ValueError("wand J1 rotation must be 90 degrees")
    if row.get("matingDirection") != "+X":
        raise ValueError("wand J1 mating direction must be +X")
    contacts = row["sixteenContactPads"]
    names = [item.get("name") for item in contacts] if isinstance(contacts, list) and all(
        isinstance(item, dict) for item in contacts
    ) else []
    if len(names) != 16 or len(set(names)) != 16 or set(names) != WAND_USB_CONTACT_NAMES:
        raise ValueError("wand J1 sixteen-contact physical-pad closure failed")
    stakes = row["fourShellDipStakes"]
    if (
        not isinstance(stakes, list)
        or len(stakes) != 4
        or any(not isinstance(item, dict) or item.get("type") != "DIP" for item in stakes)
    ):
        raise ValueError("wand J1 must preserve four DIP shell stakes")
    locators = row["locatingHoles"]
    if not isinstance(locators, list) or len(locators) != 2:
        raise ValueError("wand J1 must preserve both locating holes")
    opening = row["panelOpening"]
    if (
        not isinstance(opening, dict)
        or opening.get("wallAxis") != "+X"
        or opening.get("matingDirection", "+X") != "+X"
    ):
        raise ValueError("wand J1 panel opening must be bound to the +X wall/mating axis")


def _validate_wand_holes(rows: dict[str, dict[str, Any]]) -> None:
    for ref, expected in (("H1", (7.5, 19.5)), ("H2", (7.5, 77.0))):
        row = rows[ref]
        _point_close(_point2(row["sourceCenterMm"], f"wand {ref}.sourceCenterMm"), expected, f"wand {ref} source")
        if abs(_number(row.get("finishedDiameterMm"), f"wand {ref}.finishedDiameterMm") - 2.4) > 1e-6:
            raise ValueError(f"wand {ref} finished diameter must be 2.4 mm")
        if row.get("type") != "NPTH" or row.get("plating") is not False:
            raise ValueError(f"wand {ref} must be a non-plated NPTH")


def _validate_wand_nina(row: dict[str, Any]) -> None:
    required = {
        "antennaFeedCorner", "antennaDirection", "fullGroundEvidence",
        "mechanicalKeepoutSolid", "caseClearanceEvidence",
    }
    _required_fields(row, required, "wand U1")
    if row.get("mpn") != "NINA-B302-00B-00":
        raise ValueError("wand U1 must be the controlled NINA-B302-00B-00")
    if not isinstance(row["antennaFeedCorner"], str) or not row["antennaFeedCorner"]:
        raise ValueError("wand U1 antenna feed corner is missing")
    if not isinstance(row["antennaDirection"], str) or not row["antennaDirection"]:
        raise ValueError("wand U1 antenna direction is missing")
    for key in ("fullGroundEvidence", "mechanicalKeepoutSolid", "caseClearanceEvidence"):
        _exact_kind_ref(row[key], "wand U1." + key)


def _validate_wand_mechanical_requirements(
    value: Any,
    rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required = {
        "rearCapChangeRequired", "pcbRetentionProcess", "buttonStack",
        "boardChannel", "j1PanelOpening", "ninaMechanicalKeepout",
    }
    requirements = _required_fields(value, required, "wand mechanicalRequirements")
    if not isinstance(requirements["rearCapChangeRequired"], bool):
        raise ValueError("wand rearCapChangeRequired must be boolean")

    retention = _required_fields(
        requirements["pcbRetentionProcess"],
        {
            "type", "holeRefs", "metallicFastenersAllowed",
            "minimumAntennaMetalClearanceMm", "supplierProcessValidationRequired",
        },
        "wand pcbRetentionProcess",
    )
    if (
        retention["type"] != "nonmetallic_heat_stake"
        or retention["holeRefs"] != ["H1", "H2"]
        or retention["metallicFastenersAllowed"] is not False
        or _number(retention["minimumAntennaMetalClearanceMm"], "wand retention clearance") < 10.0
        or retention["supplierProcessValidationRequired"] is not True
    ):
        raise ValueError("wand PCB retention is not the frozen nonmetallic H1/H2 heat-stake contract")

    button = _required_fields(
        requirements["buttonStack"],
        {
            "switchRef", "actuatorCenterCaseMm", "actuationNormal",
            "switchFreeTopCaseYmm", "switchTravelMm", "allowedPreloadMm",
            "allowedOvertravelMm", "independentHardStopRequired",
            "bottomStopClearanceRequired",
        },
        "wand buttonStack",
    )
    switch = rows["SW1"]
    if (
        button["switchRef"] != "SW1"
        or _point3(button["actuatorCenterCaseMm"], "wand buttonStack.actuatorCenterCaseMm")
        != _point3(switch["actuatorCenterCaseMm"], "wand SW1.actuatorCenterCaseMm")
        or button["actuationNormal"] != switch["actuationNormal"]
        or abs(_number(button["switchTravelMm"], "wand buttonStack.switchTravelMm") - 0.25) > 1e-6
        or abs(_number(button["allowedPreloadMm"], "wand buttonStack.allowedPreloadMm") - _number(switch["allowedPreloadMm"], "wand SW1.allowedPreloadMm")) > 1e-6
        or abs(_number(button["allowedOvertravelMm"], "wand buttonStack.allowedOvertravelMm") - _number(switch["allowedOvertravelMm"], "wand SW1.allowedOvertravelMm")) > 1e-6
        or button["independentHardStopRequired"] is not True
        or button["bottomStopClearanceRequired"] is not True
    ):
        raise ValueError("wand button stack is not cross-bound to the controlled SW1 travel/hard stop")
    _number(button["switchFreeTopCaseYmm"], "wand buttonStack.switchFreeTopCaseYmm")

    channel = _required_fields(
        requirements["boardChannel"],
        {
            "boardEnvelopeMm", "bCuSupportYmm", "fCuYmm", "caseZStartMm",
            "datumScheme", "minimumNominalWidthClearancePerSideMm",
            "minimumNominalAxialClearanceMm", "positiveWorstCaseClearanceRequired",
        },
        "wand boardChannel",
    )
    if not isinstance(channel["boardEnvelopeMm"], (list, dict)) or not channel["boardEnvelopeMm"]:
        raise ValueError("wand board channel envelope is empty")
    for key in ("bCuSupportYmm", "fCuYmm", "caseZStartMm"):
        _number(channel[key], "wand boardChannel." + key)
    if (
        channel["datumScheme"] != "one_side_width_datum_opposite_clearance_one_axial_stop"
        or _number(channel["minimumNominalWidthClearancePerSideMm"], "wand channel width clearance") <= 0.0
        or _number(channel["minimumNominalAxialClearanceMm"], "wand channel axial clearance") <= 0.0
        or channel["positiveWorstCaseClearanceRequired"] is not True
    ):
        raise ValueError("wand board channel lacks positive-clearance datum closure")

    opening = _required_fields(
        requirements["j1PanelOpening"],
        {
            "ref", "wallAxis", "caseCenterMm", "widthMm", "heightMm",
            "cornerRadiusMm", "cutDepthMm", "tolerancesMm", "matingDirection",
            "authoritySha256",
        },
        "wand j1PanelOpening",
    )
    if (
        opening["ref"] != "J1"
        or opening["wallAxis"] != "+X"
        or opening["matingDirection"] != "+X"
        or _point3(opening["caseCenterMm"], "wand j1PanelOpening.caseCenterMm")
        != _point3(rows["J1"]["caseCenterMm"], "wand J1.caseCenterMm")
        or _number(opening["widthMm"], "wand J1 opening width") <= 0.0
        or _number(opening["heightMm"], "wand J1 opening height") <= 0.0
        or _number(opening["cornerRadiusMm"], "wand J1 opening corner radius") < 0.0
        or _number(opening["cutDepthMm"], "wand J1 opening cut depth") <= 0.0
        or opening["authoritySha256"] != rows["J1"]["authorityEvidence"]["sha256"]
    ):
        raise ValueError("wand J1 mechanical opening is not authority/SHA/+X bound")
    if not isinstance(opening["tolerancesMm"], (list, dict)) or not opening["tolerancesMm"]:
        raise ValueError("wand J1 opening tolerances are missing")

    nina = _required_fields(
        requirements["ninaMechanicalKeepout"],
        {
            "ref", "artifact", "minimumHighLargeMetalClearanceMm",
            "minimumCasingClearanceMm", "forbiddenClasses", "fullGroundRequired",
            "rearCapIntersectionRequiresChange",
        },
        "wand ninaMechanicalKeepout",
    )
    artifact = _exact_kind_ref(nina["artifact"], "wand ninaMechanicalKeepout.artifact")
    forbidden = nina["forbiddenClasses"]
    if (
        nina["ref"] != "U1"
        or not _same_artifact_identity(artifact, rows["U1"]["mechanicalKeepoutSolid"])
        or _number(nina["minimumHighLargeMetalClearanceMm"], "wand NINA metal clearance") < 10.0
        or _number(nina["minimumCasingClearanceMm"], "wand NINA casing clearance") < 5.0
        or not isinstance(forbidden, list)
        or not forbidden
        or not any("metal" in str(item).casefold() for item in forbidden)
        or nina["fullGroundRequired"] is not True
        or not isinstance(nina["rearCapIntersectionRequiresChange"], bool)
    ):
        raise ValueError("wand NINA keepout is not bound to full-ground/10 mm metal/5 mm casing rules")
    return copy.deepcopy(requirements)

def _validate_wand_frozen_contract_exact(
    rows: dict[str, dict[str, Any]],
    requirements: dict[str, Any],
) -> None:
    sw1 = rows["SW1"]
    if tuple(sw1["bodyEnvelopeMm"]) != (5.2, 5.2, 1.5):
        raise ValueError("wand SW1 controlled body envelope changed")
    if _point3(sw1["actuatorCenterCaseMm"], "wand SW1 actuator") != (0.0, 3.1, 72.0):
        raise ValueError("wand SW1 actuator center must be case X0/Y3.1/Z72")
    if sw1["actuationNormal"] != "+Y" or abs(_point3(sw1["caseCenterMm"], "wand SW1 case")[1] - 1.6) > 1e-6:
        raise ValueError("wand SW1 must actuate +Y from the F.Cu Y=1.6 datum")
    if sw1["padOrHoleGeometry"] != sw1["fourPhysicalPadGeometry"]:
        raise ValueError("wand SW1 common geometry does not mirror its four physical pads")

    j1 = rows["J1"]
    geometry = j1["padOrHoleGeometry"]
    if (
        not isinstance(geometry, dict)
        or geometry.get("contactPads") != j1["sixteenContactPads"]
        or geometry.get("shellDipStakes") != j1["fourShellDipStakes"]
        or geometry.get("locatingHoles") != j1["locatingHoles"]
        or abs(_point3(j1["caseCenterMm"], "wand J1 case")[1] - 1.6) > 1e-6
    ):
        raise ValueError("wand J1 common/contact/shell/locator geometry mirror failed")

    expected_mpns = {
        "J2": "SM03B-SRSS-TB(LF)(SN)",
        "J3": "SM02B-SRSS-TB(LF)(SN)",
        "U1": "NINA-B302-00B-00",
        "L1": "XFL4020-222MEC",
        "F1": "MF-FSMF050X-2",
    }
    expected_envelopes = {
        "U1": (10.0, 15.0, 4.23),
        "L1": (4.3, 4.3, 2.1),
        "F1": (1.85, 1.05, 1.0),
        "H1": (2.4, 2.4, 1.6),
        "H2": (2.4, 2.4, 1.6),
    }
    expected_heights = {"U1": 4.23, "L1": 2.1, "F1": 1.0, "H1": 0.0, "H2": 0.0}
    for ref, mpn in expected_mpns.items():
        if rows[ref]["mpn"] != mpn:
            raise ValueError(f"wand {ref} MPN is not the frozen {mpn}")
    for ref, envelope in expected_envelopes.items():
        if any(
            abs(actual - expected) > 1e-6
            for actual, expected in zip(_positive_sequence(rows[ref]["bodyEnvelopeMm"], 3, ref), envelope)
        ):
            raise ValueError(f"wand {ref} maximum body envelope changed")
        if abs(_number(rows[ref]["maximumHeightMm"], ref + ".maximumHeightMm") - expected_heights[ref]) > 1e-6:
            raise ValueError(f"wand {ref} maximum body height changed")

    for ref, signal_count in (("J2", 3), ("J3", 2)):
        row = rows[ref]
        if not isinstance(row.get("matingDirection"), str) or not row["matingDirection"]:
            raise ValueError(f"wand {ref} matingDirection is missing")
        geometry = row["padOrHoleGeometry"]
        if (
            not isinstance(geometry, dict)
            or not isinstance(geometry.get("signalPads"), list)
            or len(geometry["signalPads"]) != signal_count
            or not isinstance(geometry.get("reinforcementPads"), list)
            or len(geometry["reinforcementPads"]) != 2
        ):
            raise ValueError(f"wand {ref} JST signal/reinforcement pad closure failed")

    for ref in ("H1", "H2"):
        hole_geometry = rows[ref]["padOrHoleGeometry"]
        if (
            not isinstance(hole_geometry, dict)
            or hole_geometry.get("type") != "NPTH"
            or abs(_number(hole_geometry.get("finishedDiameterMm"), ref + ".hole") - 2.4) > 1e-6
        ):
            raise ValueError(f"wand {ref} common hole geometry mirror failed")

    retention = requirements["pcbRetentionProcess"]
    if abs(_number(retention["minimumAntennaMetalClearanceMm"], "wand retention clearance") - 10.0) > 1e-6:
        raise ValueError("wand retention antenna metal clearance must be exactly 10 mm")

    button = requirements["buttonStack"]
    if (
        button["actuationNormal"] != "+Y"
        or abs(_number(button["switchFreeTopCaseYmm"], "wand button free top") - 3.1) > 1e-6
        or abs(_number(button["switchTravelMm"], "wand button travel") - sw1["travelMm"]) > 1e-6
    ):
        raise ValueError("wand button stack does not exactly mirror SW1 actuator/free-top/travel")

    channel = requirements["boardChannel"]
    if (
        channel["boardEnvelopeMm"] != [15.0, 80.0, 1.6]
        or abs(_number(channel["bCuSupportYmm"], "wand channel B.Cu") - 0.0) > 1e-6
        or abs(_number(channel["fCuYmm"], "wand channel F.Cu") - 1.6) > 1e-6
        or abs(_number(channel["caseZStartMm"], "wand channel case Z") - 9.0) > 1e-6
    ):
        raise ValueError("wand board channel envelope/support planes/case datum changed")

    if requirements["j1PanelOpening"] != j1["panelOpening"]:
        raise ValueError("wand j1PanelOpening must exactly mirror J1.panelOpening")

    nina = requirements["ninaMechanicalKeepout"]
    expected_forbidden = {
        "metal_fastener", "conductive_coating", "battery_cell", "shield_can",
        "cable_bundle", "GFRP_spine",
    }
    if (
        abs(_number(nina["minimumHighLargeMetalClearanceMm"], "wand NINA metal clearance") - 10.0) > 1e-6
        or abs(_number(nina["minimumCasingClearanceMm"], "wand NINA casing clearance") - 5.0) > 1e-6
        or set(nina["forbiddenClasses"]) != expected_forbidden
        or requirements["rearCapChangeRequired"] is not nina["rearCapIntersectionRequiresChange"]
    ):
        raise ValueError("wand NINA exact keepout/forbidden/rear-cap mirror changed")


def wand_interface_semantics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("wand interface must be an object")
    top_level = {
        "schema", "status", "revision", "authorityReleaseBlockedRefs",
        "sourceBoard", "sourceRoutes", "nativeDrc", "coordinateContract",
        "boardDimensionsMm", "refs", "absentRefs", "consistencyEvidence",
        "mechanicalRequirements",
    }
    _required_fields(value, top_level, "wand interface")
    if value.get("schema") != WAND_INTERFACE_SCHEMA:
        raise ValueError("wand interface schema is not aicad_wand_electromechanical_interface_v1")
    if value.get("status") != WAND_INTERFACE_STATUS:
        raise ValueError("wand interface status must be exactly FROZEN")
    blocked = value.get("authorityReleaseBlockedRefs")
    if isinstance(blocked, bool) or not isinstance(blocked, int) or blocked != 0:
        raise ValueError("wand authorityReleaseBlockedRefs must be the integer 0")
    if not isinstance(value.get("revision"), str) or not value["revision"]:
        raise ValueError("wand interface revision is missing")

    source_board = _exact_kind_ref(value["sourceBoard"], "wand sourceBoard")
    source_routes = _exact_kind_ref(value["sourceRoutes"], "wand sourceRoutes")
    route_board = _exact_kind_ref(source_routes.get("sourceBoard"), "wand sourceRoutes.sourceBoard")
    if not _same_artifact_identity(source_board, route_board):
        raise ValueError("wand sourceBoard and sourceRoutes.sourceBoard are not identical")
    native_drc = _exact_kind_ref(value["nativeDrc"], "wand nativeDrc")
    for key in ("violations", "unconnected", "footprintErrors", "exclusions", "suppressions"):
        count = native_drc.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count != 0:
            raise ValueError(f"wand nativeDrc.{key} must be the integer 0")
    if native_drc.get("ignoredRules") != []:
        raise ValueError("wand nativeDrc.ignoredRules must be an empty array")

    dimensions = _required_fields(
        value["boardDimensionsMm"],
        {"width", "height", "thickness", "tolerances"},
        "wand boardDimensionsMm",
    )
    for key, expected in (("width", 15.0), ("height", 80.0), ("thickness", 1.6)):
        if abs(_number(dimensions[key], "wand boardDimensionsMm." + key) - expected) > 1e-6:
            raise ValueError(f"wand boardDimensionsMm.{key} must be {expected}")
    if not isinstance(dimensions["tolerances"], (dict, list)) or not dimensions["tolerances"]:
        raise ValueError("wand boardDimensionsMm.tolerances must be non-empty")
    contract = validate_wand_coordinate_contract(value)

    rows = _wand_ref_map(value["refs"])
    if not isinstance(value["absentRefs"], list) or set(value["absentRefs"]) != WAND_ABSENT_REFS:
        raise ValueError("wand absentRefs must be exactly H3/H4")
    for ref, row in rows.items():
        _required_fields(row, WAND_PER_REF_COMMON, "wand " + ref)
        _exact_kind_ref(row["authorityEvidence"], f"wand {ref}.authorityEvidence")
        if not isinstance(row["manufacturer"], str) or not row["manufacturer"]:
            raise ValueError(f"wand {ref}.manufacturer is missing")
        if not isinstance(row["mpn"], str) or not row["mpn"]:
            raise ValueError(f"wand {ref}.mpn is missing")
        _wand_source_to_case(row, "wand " + ref)
        _positive_sequence(row["bodyEnvelopeMm"], 3, f"wand {ref}.bodyEnvelopeMm")
        if _number(row["maximumHeightMm"], f"wand {ref}.maximumHeightMm") < 0.0:
            raise ValueError(f"wand {ref}.maximumHeightMm cannot be negative")
        geometry = row["padOrHoleGeometry"]
        if not isinstance(geometry, (dict, list)) or not geometry:
            raise ValueError(f"wand {ref}.padOrHoleGeometry is empty")

    _validate_wand_switch(rows["SW1"])
    _validate_wand_j1(rows["J1"])
    _validate_wand_holes(rows)
    _validate_wand_nina(rows["U1"])

    consistency = value["consistencyEvidence"]
    if not isinstance(consistency, dict):
        raise ValueError("wand consistencyEvidence must be an object")
    for key in ("boardShaMatchesRoutes", "roundTripCoordinateTests", "authorityHashClosure"):
        if consistency.get(key) is not True:
            raise ValueError(f"wand consistencyEvidence.{key} must be true")
    if consistency.get("mechanicalRequirementMirrorChecks") is not True:
        raise ValueError("wand consistencyEvidence.mechanicalRequirementMirrorChecks must be true")

    requirements = _validate_wand_mechanical_requirements(
        value["mechanicalRequirements"], rows
    )
    _validate_wand_frozen_contract_exact(rows, requirements)
    return {
        "schema": value["schema"],
        "status": value["status"],
        "revision": value["revision"],
        "authorityReleaseBlockedRefs": blocked,
        "sourceBoard": copy.deepcopy(source_board),
        "sourceRoutes": copy.deepcopy(source_routes),
        "nativeDrc": copy.deepcopy(native_drc),
        "coordinateContract": contract,
        "boardDimensionsMm": copy.deepcopy(dimensions),
        "refs": copy.deepcopy(value["refs"]),
        "absentRefs": copy.deepcopy(value["absentRefs"]),
        "consistencyEvidence": copy.deepcopy(consistency),
        "mechanicalRequirements": requirements,
    }

