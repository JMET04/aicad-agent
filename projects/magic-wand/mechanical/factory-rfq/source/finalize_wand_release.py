from __future__ import annotations

"""Fail-closed validator and bounded executor for the wand redesign.

No geometry or package write occurs until the electronics interface is final,
authority-complete, and accepted by every exact gate below.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


INTERFACE_SCHEMA = "aicad_wand_electromechanical_interface_v1"
FROZEN_STATUS = "FROZEN"
ASSEMBLY_ID = "MW-A-001"
DIRECT_CHANGED_PARTS = ("MW-M-001A", "MW-M-001B", "MW-M-002", "MW-M-005")
CONDITIONAL_CHANGED_PART = "MW-M-003"
ALWAYS_UNCHANGED_SUBJECTS = (
    "MW-M-004",
    "MW-P-001",
    "MW-M-101",
    "MW-M-102",
    "MW-A-101",
)
ALL_SUBJECTS = (
    "MW-M-001A",
    "MW-M-001B",
    "MW-M-002",
    "MW-M-003",
    "MW-M-004",
    "MW-M-005",
    "MW-P-001",
    "MW-M-101",
    "MW-M-102",
    "MW-A-001",
    "MW-A-101",
)
REQUIRED_REFS = {"SW1", "J1", "J2", "J3", "U1", "L1", "F1", "H1", "H2"}
ABSENT_REFS = {"H3", "H4"}
CONTACT_NAMES = {
    "A1",
    "B12",
    "A4",
    "B9",
    "A5",
    "B5",
    "A6",
    "B6",
    "A7",
    "B7",
    "A8",
    "B8",
    "A9",
    "B4",
    "A12",
    "B1",
}
AUTHORITY_FIELDS_BY_REF: dict[str, tuple[str, ...]] = {
    "SW1": (
        "bodyEnvelopeMm",
        "freeHeightMm",
        "travelMm",
        "forceN",
        "allowedPreloadMm",
        "allowedOvertravelMm",
        "fourPhysicalPadGeometry",
        "logicalTerminalPairMap",
    ),
    "J1": (
        "officialDrawingNumber",
        "bodyEnvelopeMm",
        "sixteenContactPads",
        "fourShellDipStakes",
        "locatingHoles",
        "matingFaceMm",
        "matingDirection",
        "matingEnvelopeMm",
        "unmateClearanceMm",
        "panelOpening",
    ),
    "J2": ("bodyEnvelopeMm", "maximumHeightMm", "padOrHoleGeometry", "matingDirection"),
    "J3": ("bodyEnvelopeMm", "maximumHeightMm", "padOrHoleGeometry", "matingDirection"),
    "U1": (
        "bodyEnvelopeMm",
        "maximumHeightMm",
        "antennaFeedCorner",
        "antennaDirection",
        "fullGroundEvidence",
        "mechanicalKeepoutSolid",
        "caseClearanceEvidence",
    ),
    "L1": ("bodyEnvelopeMm", "maximumHeightMm"),
    "F1": ("bodyEnvelopeMm", "maximumHeightMm"),
    "H1": (
        "sourceCenterMm",
        "caseCenterMm",
        "finishedDiameterMm",
        "type",
        "plating",
    ),
    "H2": (
        "sourceCenterMm",
        "caseCenterMm",
        "finishedDiameterMm",
        "type",
        "plating",
    ),
}




INPUT_FIELD_CONTRACT: dict[str, Any] = {
    "topLevel": [
        "schema",
        "status",
        "revision",
        "authorityReleaseBlockedRefs",
        "sourceBoard",
        "sourceRoutes",
        "nativeDrc",
        "coordinateContract",
        "boardDimensionsMm",
        "refs",
        "absentRefs",
        "consistencyEvidence",
        "mechanicalRequirements",
    ],
    "releaseGate": {
        "schema": INTERFACE_SCHEMA,
        "status": FROZEN_STATUS,
        "authorityReleaseBlockedRefs": 0,
        "nativeDrcCounts": {
            "violations": 0,
            "unconnected": 0,
            "footprintErrors": 0,
            "exclusions": 0,
            "suppressions": 0,
            "ignoredRules": [],
        },
    },
    "coordinateContract": {
        "source": {
            "origin": "top-left",
            "xAxis": "right",
            "yAxis": "down",
            "units": "mm",
            "boardWidthMm": 15.0,
            "boardHeightMm": 80.0,
        },
        "forwardTransform": {"X": "x_source-7.5", "Y": "heightFromBCu", "Z": "y_source+9.0"},
        "inverseTransform": {"x_source": "X+7.5", "y_source": "Z-9.0", "heightFromBCu": "Y"},
        "requiredRoundTripToleranceMm": 1e-6,
    },
    "boardDimensionsMm": {"width": 15.0, "height": 80.0, "thickness": 1.6, "required": ["tolerances"]},
    "refs": sorted(REQUIRED_REFS),
    "absentRefs": sorted(ABSENT_REFS),
    "authorityEvidence": {
        "authorityRequired": [
            "schema",
            "status",
            "kind",
            "manufacturer",
            "mpn",
            "releaseBlocked",
            "sourceArtifacts",
            "extractionEvidence",
            "extractedMechanical",
        ],
        "sourceArtifactRequired": ["path", "size", "sha256", "kind"],
        "extractionEvidenceRequired": [
            "documentNumber",
            "page",
            "section",
            "sourceArtifactSha256",
            "extractedFields",
        ],
        "mechanicalFieldsByRef": {
            ref: list(fields) for ref, fields in AUTHORITY_FIELDS_BY_REF.items()
        },
        "J1RequiredSourceKinds": ["controlled_2d_drawing", "controlled_3d_step"],
    },
    "perRefCommon": [
        "ref",
        "manufacturer",
        "mpn",
        "authorityEvidence",
        "sourceCenterMm",
        "caseCenterMm",
        "rotationDeg",
        "bodyEnvelopeMm",
        "maximumHeightMm",
        "padOrHoleGeometry",
        "roundTripCoordinateEvidence",
    ],
    "SW1Specific": [
        "freeHeightMm",
        "travelMm",
        "forceN",
        "actuatorCenterCaseMm",
        "actuationNormal",
        "fourPhysicalPadGeometry",
        "logicalTerminalPairMap",
        "allowedPreloadMm",
        "allowedOvertravelMm",
    ],
    "J1Specific": [
        "officialDrawingNumber",
        "sixteenContactPads",
        "fourShellDipStakes",
        "locatingHoles",
        "matingFaceMm",
        "matingDirection",
        "matingEnvelopeMm",
        "unmateClearanceMm",
        "panelOpening",
    ],
    "JSTSpecific": ["matingDirection"],
    "knownMaximumBodyEnvelopeMm": {
        "U1": [10.0, 15.0, 4.23],
        "L1": [4.3, 4.3, 2.1],
        "F1": [1.85, 1.05, 1.0],
        "H1": [2.4, 2.4, 1.6],
        "H2": [2.4, 2.4, 1.6],
    },
    "knownMaximumHeightMm": {
        "U1": 4.23,
        "L1": 2.1,
        "F1": 1.0,
        "H1": 0.0,
        "H2": 0.0,
    },
    "NINASpecific": [
        "antennaFeedCorner",
        "antennaDirection",
        "fullGroundEvidence",
        "mechanicalKeepoutSolid",
        "caseClearanceEvidence",
    ],
    "mechanicalRequirements": {
        "rearCapChangeRequired": "boolean",
        "pcbRetentionProcess": {
            "type": "nonmetallic_heat_stake",
            "holeRefs": ["H1", "H2"],
            "metallicFastenersAllowed": False,
            "minimumAntennaMetalClearanceMm": 10.0,
            "supplierProcessValidationRequired": True,
        },
        "buttonStack": {
            "required": [
                "switchRef",
                "actuatorCenterCaseMm",
                "actuationNormal",
                "switchFreeTopCaseYmm",
                "switchTravelMm",
                "allowedPreloadMm",
                "allowedOvertravelMm",
                "independentHardStopRequired",
                "bottomStopClearanceRequired",
            ]
        },
        "boardChannel": {
            "required": [
                "boardEnvelopeMm",
                "bCuSupportYmm",
                "fCuYmm",
                "caseZStartMm",
                "datumScheme",
                "minimumNominalWidthClearancePerSideMm",
                "minimumNominalAxialClearanceMm",
                "positiveWorstCaseClearanceRequired",
            ],
            "datumScheme": "one_side_width_datum_opposite_clearance_one_axial_stop",
        },
        "j1PanelOpening": {
            "required": [
                "ref",
                "wallAxis",
                "caseCenterMm",
                "widthMm",
                "heightMm",
                "cornerRadiusMm",
                "cutDepthMm",
                "tolerancesMm",
                "matingDirection",
                "authoritySha256",
            ]
        },
        "ninaMechanicalKeepout": {
            "required": [
                "ref",
                "artifact",
                "minimumHighLargeMetalClearanceMm",
                "minimumCasingClearanceMm",
                "forbiddenClasses",
                "fullGroundRequired",
                "rearCapIntersectionRequiresChange",
            ]
        },
    },
}


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


def close(actual: Any, expected: float, tolerance: float = 1e-6) -> bool:
    try:
        return math.isclose(float(actual), expected, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def point2(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-number array")
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a two-number array") from exc


def point3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be a three-number array")
    try:
        return float(value[0]), float(value[1]), float(value[2])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a three-number array") from exc


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
    record: Any,
    label: str,
) -> Path:
    if not isinstance(record, dict) or not {"path", "size", "sha256", "kind"} <= set(record):
        raise ValueError(f"{label} requires path/size/sha256/kind")
    if not isinstance(record["kind"], str) or not record["kind"].strip():
        raise ValueError(f"{label}.kind must be a non-empty controlled identity")
    path = resolve_artifact_path(repository, interface_path, str(record["path"]))
    if path.stat().st_size != int(record["size"]):
        raise ValueError(f"{label} size mismatch")
    digest = str(record["sha256"]).lower()
    if len(digest) != 64 or sha256_file(path) != digest:
        raise ValueError(f"{label} SHA-256 mismatch")
    return path


def require_fields(record: Any, fields: list[str], label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be an object")
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"{label} missing exact fields: {missing}")
    return record


def values_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return close(actual, float(expected))
    if isinstance(expected, dict) and isinstance(actual, dict):
        return set(actual) == set(expected) and all(
            values_match(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list) and isinstance(actual, list):
        return len(actual) == len(expected) and all(
            values_match(a, e) for a, e in zip(actual, expected)
        )
    return actual == expected


def validate_authority(
    repository: Path,
    interface_path: Path,
    record: dict[str, Any],
    ref: str,
) -> dict[str, Any]:
    evidence = record.get("authorityEvidence")
    path = validate_artifact(repository, interface_path, evidence, f"{ref}.authorityEvidence")
    authority = read_json(path)
    contract = INPUT_FIELD_CONTRACT["authorityEvidence"]
    require_fields(authority, contract["authorityRequired"], f"{ref}.authority")
    if not isinstance(authority.get("schema"), str) or not authority["schema"].startswith("aicad_"):
        raise ValueError(f"{ref} authority schema is not controlled")
    if authority.get("status") not in {"controlled", "FROZEN"}:
        raise ValueError(f"{ref} authority status is not controlled")
    if authority.get("releaseBlocked") is not False:
        raise ValueError(f"{ref} authority remains release-blocked")
    if not isinstance(authority.get("kind"), str) or not authority["kind"].strip():
        raise ValueError(f"{ref} authority kind is empty")
    if authority.get("manufacturer") != record.get("manufacturer"):
        raise ValueError(f"{ref} authority manufacturer mismatch")
    if authority.get("mpn") != record.get("mpn"):
        raise ValueError(f"{ref} authority MPN mismatch")

    source_artifacts = authority.get("sourceArtifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        raise ValueError(f"{ref} authority has no real sourceArtifacts")
    source_sha_by_kind: dict[str, set[str]] = {}
    source_shas: set[str] = set()
    for index, source_record in enumerate(source_artifacts):
        require_fields(
            source_record,
            contract["sourceArtifactRequired"],
            f"{ref}.authority.sourceArtifacts[{index}]",
        )
        validate_artifact(
            repository,
            path,
            source_record,
            f"{ref}.authority.sourceArtifacts[{index}]",
        )
        source_sha = str(source_record["sha256"]).lower()
        source_shas.add(source_sha)
        source_sha_by_kind.setdefault(str(source_record["kind"]), set()).add(source_sha)
    if len(source_shas) != len(source_artifacts):
        raise ValueError(f"{ref} authority sourceArtifacts contain duplicate self-signatures")

    extraction = authority.get("extractionEvidence")
    if not isinstance(extraction, list) or not extraction:
        raise ValueError(f"{ref} authority extractionEvidence is empty")
    extracted_field_union: set[str] = set()
    extracted_fields_by_source_sha: dict[str, set[str]] = {}
    for index, row in enumerate(extraction):
        require_fields(
            row,
            contract["extractionEvidenceRequired"],
            f"{ref}.authority.extractionEvidence[{index}]",
        )
        if not isinstance(row["documentNumber"], str) or not row["documentNumber"].strip():
            raise ValueError(f"{ref} extraction documentNumber is empty")
        page = row["page"]
        if not (
            (isinstance(page, int) and not isinstance(page, bool) and page > 0)
            or (isinstance(page, str) and page.strip())
        ):
            raise ValueError(f"{ref} extraction page is not controlled")
        if not isinstance(row["section"], str) or not row["section"].strip():
            raise ValueError(f"{ref} extraction section is empty")
        if str(row["sourceArtifactSha256"]).lower() not in source_shas:
            raise ValueError(f"{ref} extraction is not bound to a real sourceArtifact SHA")
        fields = row["extractedFields"]
        if not isinstance(fields, list) or not fields or any(
            not isinstance(field, str) or not field.strip() for field in fields
        ):
            raise ValueError(f"{ref} extraction extractedFields is empty")
        extracted_field_union.update(fields)
        source_sha = str(row["sourceArtifactSha256"]).lower()
        extracted_fields_by_source_sha.setdefault(source_sha, set()).update(fields)

    required_fields = set(AUTHORITY_FIELDS_BY_REF[ref])
    if not required_fields <= extracted_field_union:
        raise ValueError(
            f"{ref} authority extraction does not cover mechanical fields: "
            f"{sorted(required_fields - extracted_field_union)}"
        )
    extracted = authority.get("extractedMechanical")
    if not isinstance(extracted, dict):
        raise ValueError(f"{ref} authority extractedMechanical is not an object")
    for field in required_fields:
        expected = record.get(field)
        if ref == "J1" and field == "panelOpening" and isinstance(expected, dict):
            # authoritySha256 binds the completed authority JSON and therefore
            # cannot be embedded inside that JSON without a hash self-reference.
            # Every actual opening driver remains mirrored and source-extracted.
            expected = {
                key: value for key, value in expected.items() if key != "authoritySha256"
            }
        if field not in extracted or not values_match(extracted[field], expected):
            raise ValueError(f"{ref} authority extractedMechanical.{field} mismatch")

    if ref == "J1":
        required_kinds = set(contract["J1RequiredSourceKinds"])
        if not required_kinds <= set(source_sha_by_kind):
            raise ValueError("J1 authority must bind controlled 2D drawing and 3D STEP sources")
        drawing_fields = {
            "officialDrawingNumber", "sixteenContactPads", "fourShellDipStakes",
            "locatingHoles", "panelOpening",
        }
        model_fields = {"bodyEnvelopeMm", "matingEnvelopeMm", "unmateClearanceMm"}
        drawing_covered = set().union(
            *(extracted_fields_by_source_sha.get(sha, set())
              for sha in source_sha_by_kind["controlled_2d_drawing"])
        )
        model_covered = set().union(
            *(extracted_fields_by_source_sha.get(sha, set())
              for sha in source_sha_by_kind["controlled_3d_step"])
        )
        if not drawing_fields <= drawing_covered or not model_fields <= model_covered:
            raise ValueError("J1 2D/3D sources are not bound to their extracted mechanical fields")
    if ref == "U1":
        keepout_sha = str(record["mechanicalKeepoutSolid"]["sha256"]).lower()
        if keepout_sha not in source_shas:
            raise ValueError("U1 authority sourceArtifacts do not bind the mechanical keepout solid")
        if "mechanicalKeepoutSolid" not in extracted_fields_by_source_sha.get(keepout_sha, set()):
            raise ValueError("U1 keepout source is not bound to its extractedMechanical field")
    return authority


def ref_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = document.get("refs")
    if not isinstance(refs, list) or any(not isinstance(row, dict) for row in refs):
        raise ValueError("refs must be an array of objects")
    rows = {str(row.get("ref")): row for row in refs}
    if set(rows) != REQUIRED_REFS:
        raise ValueError(f"refs must be exactly {sorted(REQUIRED_REFS)}")
    return rows


def validate_source_to_case(record: dict[str, Any], ref: str) -> None:
    source_x, source_y = point2(record.get("sourceCenterMm"), f"{ref}.sourceCenterMm")
    case_x, case_y, case_z = point3(record.get("caseCenterMm"), f"{ref}.caseCenterMm")
    if not close(case_x, source_x - 7.5) or not close(case_z, source_y + 9.0):
        raise ValueError(f"{ref} source-to-case transform mismatch")
    if not close(source_x, case_x + 7.5) or not close(source_y, case_z - 9.0):
        raise ValueError(f"{ref} case-to-source round trip mismatch")
    if not math.isfinite(case_y):
        raise ValueError(f"{ref}.caseCenterMm Y is not finite")


def validate_common_ref(
    repository: Path,
    interface_path: Path,
    record: dict[str, Any],
    ref: str,
) -> None:
    require_fields(record, INPUT_FIELD_CONTRACT["perRefCommon"], ref)
    validate_authority(repository, interface_path, record, ref)
    validate_source_to_case(record, ref)
    envelope = record.get("bodyEnvelopeMm")
    if not isinstance(envelope, list) or len(envelope) != 3:
        raise ValueError(f"{ref}.bodyEnvelopeMm must be a three-number array")
    if any(not math.isfinite(float(value)) or float(value) <= 0.0 for value in envelope):
        raise ValueError(f"{ref}.bodyEnvelopeMm must be positive")
    maximum_height = float(record.get("maximumHeightMm", -1.0))
    if not math.isfinite(maximum_height) or maximum_height < 0.0:
        raise ValueError(f"{ref}.maximumHeightMm is invalid")
    geometry = record.get("padOrHoleGeometry")
    if not isinstance(geometry, (dict, list)) or not geometry:
        raise ValueError(f"{ref}.padOrHoleGeometry is empty")
    round_trip = record.get("roundTripCoordinateEvidence")
    if not isinstance(round_trip, dict) or round_trip.get("passed") is not True:
        raise ValueError(f"{ref}.roundTripCoordinateEvidence did not pass")
    if float(round_trip.get("toleranceMm", -1.0)) > 1e-6:
        raise ValueError(f"{ref}.roundTripCoordinateEvidence tolerance is too loose")



def validate_switch(record: dict[str, Any]) -> None:
    require_fields(record, INPUT_FIELD_CONTRACT["SW1Specific"], "SW1")
    if record.get("manufacturer") != "ALPS Alpine" or record.get("mpn") != "SKQGAFE010":
        raise ValueError("SW1 is not the controlled SKQGAFE010")
    if point2(record["sourceCenterMm"], "SW1.sourceCenterMm") != (7.5, 63.0):
        raise ValueError("SW1 source center changed")
    if not close(record.get("rotationDeg"), 90.0):
        raise ValueError("SW1 rotation changed")
    body = record.get("bodyEnvelopeMm")
    if not isinstance(body, list) or len(body) != 3 or not all(
        close(actual, expected) for actual, expected in zip(body, (5.2, 5.2, 1.5))
    ):
        raise ValueError("SW1 body is not 5.2 x 5.2 x 1.5 mm")
    if not close(record.get("freeHeightMm"), 1.5) or not close(record.get("travelMm"), 0.25):
        raise ValueError("SW1 free height/travel changed")
    pads = record.get("fourPhysicalPadGeometry")
    actuator = point3(record.get("actuatorCenterCaseMm"), "SW1.actuatorCenterCaseMm")
    if not all(close(actual, expected) for actual, expected in zip(actuator, (0.0, 3.1, 72.0))):
        raise ValueError("SW1 actuator center is not case X0/Y3.1/Z72")
    if record.get("actuationNormal") != "+Y":
        raise ValueError("SW1 actuation normal is not +Y")
    case_center = point3(record.get("caseCenterMm"), "SW1.caseCenterMm")
    if not close(case_center[1], 1.6):
        raise ValueError("SW1 mounting datum is not on F.Cu Y=1.6")

    if not isinstance(pads, list) or len(pads) != 4:
        raise ValueError("SW1 must contain four physical terminal pads")
    if record.get("padOrHoleGeometry") != pads:
        raise ValueError("SW1 common pad geometry does not mirror its four terminals")
    pairs = record.get("logicalTerminalPairMap")
    if not isinstance(pairs, list) or len(pairs) != 2:
        raise ValueError("SW1 logical terminal pair map must contain two pairs")
    if float(record.get("allowedPreloadMm", -1.0)) < 0.0:
        raise ValueError("SW1 allowed preload is invalid")
    if float(record.get("allowedOvertravelMm", -1.0)) < 0.0:
        raise ValueError("SW1 allowed overtravel is invalid")
    validate_source_to_case(record, "SW1")


def validate_j1(record: dict[str, Any]) -> None:
    require_fields(record, INPUT_FIELD_CONTRACT["J1Specific"], "J1")
    if record.get("manufacturer") != "JAE" or record.get("mpn") != "DX07S016JA1R1500":
        raise ValueError("J1 is not the controlled DX07S016JA1R1500")
    if record.get("officialDrawingNumber") != "SJ121837":
        raise ValueError("J1 official drawing number is not SJ121837")
    if point2(record["sourceCenterMm"], "J1.sourceCenterMm") != (12.5, 38.0):
        raise ValueError("J1 source center changed")
    if not close(record.get("rotationDeg"), 90.0) or record.get("matingDirection") != "+X":
        raise ValueError("J1 rotation/mating direction changed")
    contacts = record.get("sixteenContactPads")
    names = {str(row.get("name")) for row in contacts} if isinstance(contacts, list) else set()
    if not isinstance(contacts, list) or len(contacts) != 16 or names != CONTACT_NAMES:
        raise ValueError("J1 sixteen-contact pad closure failed")
    stakes = record.get("fourShellDipStakes")
    if not isinstance(stakes, list) or len(stakes) != 4:
        raise ValueError("J1 four shell DIP stakes are incomplete")
    if any(str(row.get("type")) != "DIP" for row in stakes):
        raise ValueError("J1 shell stakes are not all DIP")
    if not isinstance(record.get("locatingHoles"), list) or not record["locatingHoles"]:
        raise ValueError("J1 locating-hole authority is empty")
    geometry = record.get("padOrHoleGeometry")
    if not isinstance(geometry, dict):
        raise ValueError("J1 padOrHoleGeometry must be an object")
    if geometry.get("contactPads") != contacts:
        raise ValueError("J1 common contact-pad geometry does not mirror sixteenContactPads")
    if geometry.get("shellDipStakes") != stakes:
        raise ValueError("J1 common shell geometry does not mirror fourShellDipStakes")
    if geometry.get("locatingHoles") != record["locatingHoles"]:
        raise ValueError("J1 common locating geometry does not mirror locatingHoles")

    opening = record.get("panelOpening")
    if not isinstance(opening, dict) or opening.get("wallAxis") != "+X":
        raise ValueError("J1 panel opening is not bound to the +X wall")
    case_center = point3(record.get("caseCenterMm"), "J1.caseCenterMm")
    if not close(case_center[1], 1.6):
        raise ValueError("J1 mounting datum is not on F.Cu Y=1.6")

    validate_source_to_case(record, "J1")


def validate_mount_hole(record: dict[str, Any], ref: str, source: tuple[float, float]) -> None:
    if point2(record.get("sourceCenterMm"), f"{ref}.sourceCenterMm") != source:
        raise ValueError(f"{ref} source center changed")
    if not close(record.get("finishedDiameterMm"), 2.4):
        raise ValueError(f"{ref} finished diameter is not 2.4 mm")
    if record.get("type") != "NPTH" or record.get("plating") is not False:
        raise ValueError(f"{ref} is not an unplated NPTH")
    geometry = record.get("padOrHoleGeometry")
    if geometry.get("type") != "NPTH" or not close(geometry.get("finishedDiameterMm"), 2.4):
        raise ValueError(f"{ref} common hole geometry does not mirror the frozen hole")
    validate_source_to_case(record, ref)



def validate_known_ref_envelopes(rows: dict[str, dict[str, Any]]) -> None:
    expected_mpns = {
        "J2": "SM03B-SRSS-TB(LF)(SN)",
        "J3": "SM02B-SRSS-TB(LF)(SN)",
        "U1": "NINA-B302-00B-00",
        "L1": "XFL4020-222MEC",
        "F1": "MF-FSMF050X-2",
    }
    for ref, expected in expected_mpns.items():
        if rows[ref].get("mpn") != expected:
            raise ValueError(f"{ref} MPN is not the controlled {expected}")

    envelopes = INPUT_FIELD_CONTRACT["knownMaximumBodyEnvelopeMm"]
    heights = INPUT_FIELD_CONTRACT["knownMaximumHeightMm"]
    for ref, expected in envelopes.items():
        actual = rows[ref].get("bodyEnvelopeMm")
        if not isinstance(actual, list) or len(actual) != 3 or not all(
            close(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected)
        ):
            raise ValueError(f"{ref} controlled maximum body envelope changed")
        if not close(rows[ref].get("maximumHeightMm"), heights[ref]):
            raise ValueError(f"{ref} controlled maximum height changed")

    for ref, signal_count in (("J2", 3), ("J3", 2)):
        record = rows[ref]
        require_fields(record, INPUT_FIELD_CONTRACT["JSTSpecific"], ref)
        if not isinstance(record["matingDirection"], str) or not record["matingDirection"]:
            raise ValueError(f"{ref}.matingDirection is empty")
        geometry = record.get("padOrHoleGeometry")
        if not isinstance(geometry, dict):
            raise ValueError(f"{ref}.padOrHoleGeometry must be an object")
        signal_pads = geometry.get("signalPads")
        reinforcement_pads = geometry.get("reinforcementPads")
        if not isinstance(signal_pads, list) or len(signal_pads) != signal_count:
            raise ValueError(f"{ref} signal-pad count is not {signal_count}")
        if not isinstance(reinforcement_pads, list) or len(reinforcement_pads) != 2:
            raise ValueError(f"{ref} must contain two reinforcement pads")


def validate_wand_interface(repository: Path, interface_path: Path) -> dict[str, Any]:
    document = read_json(interface_path)
    if document.get("schema") != INTERFACE_SCHEMA:
        raise ValueError("unexpected wand interface schema")
    if document.get("status") != FROZEN_STATUS:
        raise ValueError(f"wand interface status must be exactly {FROZEN_STATUS}")
    blocked = document.get("authorityReleaseBlockedRefs")
    if isinstance(blocked, bool) or not isinstance(blocked, int) or blocked != 0:
        raise ValueError("authorityReleaseBlockedRefs must be the integer 0")
    require_fields(document, INPUT_FIELD_CONTRACT["topLevel"], "interface")

    dimensions = document["boardDimensionsMm"]
    require_fields(dimensions, ["width", "height", "thickness", "tolerances"], "boardDimensionsMm")
    for key, expected in (("width", 15.0), ("height", 80.0), ("thickness", 1.6)):
        if not close(dimensions.get(key), expected):
            raise ValueError(f"boardDimensionsMm.{key} is not {expected}")

    source_board_path = validate_artifact(repository, interface_path, document["sourceBoard"], "sourceBoard")
    routes_path = validate_artifact(repository, interface_path, document["sourceRoutes"], "sourceRoutes")
    route_board = document["sourceRoutes"].get("sourceBoard")
    validate_artifact(repository, interface_path, route_board, "sourceRoutes.sourceBoard")
    if route_board.get("sha256") != document["sourceBoard"].get("sha256"):
        raise ValueError("sourceBoard SHA does not match sourceRoutes.sourceBoard SHA")

    native_drc = document["nativeDrc"]
    native_drc_path = validate_artifact(repository, interface_path, native_drc, "nativeDrc")
    for field in ("violations", "unconnected", "footprintErrors", "exclusions", "suppressions"):
        if native_drc.get(field) != 0:
            raise ValueError(f"nativeDrc.{field} is not the integer 0")
    if native_drc.get("ignoredRules") != []:
        raise ValueError("nativeDrc.ignoredRules must be an empty array")

    contract = document["coordinateContract"]
    source = contract.get("source")
    if source != INPUT_FIELD_CONTRACT["coordinateContract"]["source"]:
        raise ValueError("coordinateContract.source changed")
    if contract.get("forwardTransform") != INPUT_FIELD_CONTRACT["coordinateContract"]["forwardTransform"]:
        raise ValueError("coordinateContract.forwardTransform changed")
    if contract.get("inverseTransform") != INPUT_FIELD_CONTRACT["coordinateContract"]["inverseTransform"]:
        raise ValueError("coordinateContract.inverseTransform changed")
    tests = contract.get("roundTripTests")
    if not isinstance(tests, list) or not tests or any(row.get("passed") is not True for row in tests):
        raise ValueError("coordinateContract.roundTripTests is empty or failed")

    rows = ref_map(document)
    if set(document["absentRefs"]) != ABSENT_REFS:
        raise ValueError("absentRefs must be exactly H3/H4")
    for ref, record in rows.items():
        validate_common_ref(repository, interface_path, record, ref)
    validate_switch(rows["SW1"])
    validate_j1(rows["J1"])
    validate_mount_hole(rows["H1"], "H1", (7.5, 19.5))
    validate_mount_hole(rows["H2"], "H2", (7.5, 77.0))
    validate_known_ref_envelopes(rows)

    u1 = require_fields(rows["U1"], INPUT_FIELD_CONTRACT["NINASpecific"], "U1")
    if u1.get("mpn") != "NINA-B302-00B-00":
        raise ValueError("U1 is not the controlled NINA-B302-00B-00")
    for field in ("fullGroundEvidence", "mechanicalKeepoutSolid", "caseClearanceEvidence"):
        validate_artifact(repository, interface_path, u1[field], f"U1.{field}")

    evidence = document["consistencyEvidence"]
    for field in (
        "boardShaMatchesRoutes",
        "roundTripCoordinateTests",
        "authorityHashClosure",
        "mechanicalRequirementMirrorChecks",
    ):
        if evidence.get(field) is not True:
            raise ValueError(f"consistencyEvidence.{field} did not pass")

    requirement_contract = INPUT_FIELD_CONTRACT["mechanicalRequirements"]
    requirements = require_fields(
        document["mechanicalRequirements"],
        list(requirement_contract),
        "mechanicalRequirements",
    )
    rear_cap_change = requirements.get("rearCapChangeRequired")
    if not isinstance(rear_cap_change, bool):
        raise ValueError("mechanicalRequirements.rearCapChangeRequired must be boolean")

    retention = require_fields(
        requirements["pcbRetentionProcess"],
        list(requirement_contract["pcbRetentionProcess"]),
        "mechanicalRequirements.pcbRetentionProcess",
    )
    if retention["type"] != "nonmetallic_heat_stake":
        raise ValueError("PCB retention type must be nonmetallic_heat_stake")
    if retention["holeRefs"] != ["H1", "H2"] or retention["metallicFastenersAllowed"] is not False:
        raise ValueError("PCB retention must use only H1/H2 without metallic fasteners")
    if not close(retention["minimumAntennaMetalClearanceMm"], 10.0):
        raise ValueError("PCB retention antenna metal clearance is not 10 mm")
    if retention["supplierProcessValidationRequired"] is not True:
        raise ValueError("PCB retention supplier process validation is not required")

    button = require_fields(
        requirements["buttonStack"],
        requirement_contract["buttonStack"]["required"],
        "mechanicalRequirements.buttonStack",
    )
    if button["switchRef"] != "SW1" or button["actuationNormal"] != "+Y":
        raise ValueError("buttonStack is not bound to SW1/+Y")
    actuator = point3(button["actuatorCenterCaseMm"], "buttonStack.actuatorCenterCaseMm")
    sw1_actuator = point3(rows["SW1"]["actuatorCenterCaseMm"], "SW1.actuatorCenterCaseMm")
    if not all(close(actual, expected) for actual, expected in zip(actuator, sw1_actuator)):
        raise ValueError("buttonStack actuator center does not mirror SW1")
    for field, sw1_field in (
        ("switchFreeTopCaseYmm", None),
        ("switchTravelMm", "travelMm"),
        ("allowedPreloadMm", "allowedPreloadMm"),
        ("allowedOvertravelMm", "allowedOvertravelMm"),
    ):
        expected = sw1_actuator[1] if sw1_field is None else rows["SW1"][sw1_field]
        if not close(button[field], float(expected)):
            raise ValueError(f"buttonStack.{field} does not mirror SW1")
    if button["independentHardStopRequired"] is not True or button["bottomStopClearanceRequired"] is not True:
        raise ValueError("buttonStack independent hard-stop/bottom-clearance gates are not required")

    channel = require_fields(
        requirements["boardChannel"],
        requirement_contract["boardChannel"]["required"],
        "mechanicalRequirements.boardChannel",
    )
    board_envelope = channel["boardEnvelopeMm"]
    if not isinstance(board_envelope, list) or len(board_envelope) != 3 or not all(
        close(actual, expected) for actual, expected in zip(board_envelope, (15.0, 80.0, 1.6))
    ):
        raise ValueError("boardChannel.boardEnvelopeMm changed")
    if not close(channel["bCuSupportYmm"], 0.0) or not close(channel["fCuYmm"], 1.6):
        raise ValueError("boardChannel copper support planes changed")
    if not close(channel["caseZStartMm"], 9.0):
        raise ValueError("boardChannel case Z start changed")
    if channel["datumScheme"] != requirement_contract["boardChannel"]["datumScheme"]:
        raise ValueError("boardChannel datum scheme changed")
    if float(channel["minimumNominalWidthClearancePerSideMm"]) <= 0.0:
        raise ValueError("boardChannel width clearance is not positive")
    if float(channel["minimumNominalAxialClearanceMm"]) <= 0.0:
        raise ValueError("boardChannel axial clearance is not positive")
    if channel["positiveWorstCaseClearanceRequired"] is not True:
        raise ValueError("boardChannel worst-case clearance gate is not required")

    j1_opening = require_fields(
        requirements["j1PanelOpening"],
        requirement_contract["j1PanelOpening"]["required"],
        "mechanicalRequirements.j1PanelOpening",
    )
    if j1_opening != rows["J1"]["panelOpening"]:
        raise ValueError("j1PanelOpening does not exactly mirror J1.panelOpening")
    if j1_opening["ref"] != "J1" or j1_opening["wallAxis"] != "+X":
        raise ValueError("j1PanelOpening is not the J1 +X wall opening")
    if j1_opening["matingDirection"] != "+X":
        raise ValueError("j1PanelOpening mating direction changed")
    if j1_opening["authoritySha256"] != rows["J1"]["authorityEvidence"]["sha256"]:
        raise ValueError("j1PanelOpening authority SHA mismatch")
    for field in ("widthMm", "heightMm", "cutDepthMm"):
        if float(j1_opening[field]) <= 0.0:
            raise ValueError(f"j1PanelOpening.{field} must be positive")
    if float(j1_opening["cornerRadiusMm"]) < 0.0:
        raise ValueError("j1PanelOpening.cornerRadiusMm is negative")

    nina_keepout = require_fields(
        requirements["ninaMechanicalKeepout"],
        requirement_contract["ninaMechanicalKeepout"]["required"],
        "mechanicalRequirements.ninaMechanicalKeepout",
    )
    if nina_keepout["ref"] != "U1" or nina_keepout["fullGroundRequired"] is not True:
        raise ValueError("ninaMechanicalKeepout is not bound to U1/full ground")
    validate_artifact(repository, interface_path, nina_keepout["artifact"], "ninaMechanicalKeepout.artifact")
    if nina_keepout["artifact"]["sha256"] != u1["mechanicalKeepoutSolid"]["sha256"]:
        raise ValueError("ninaMechanicalKeepout artifact does not mirror U1")
    if not close(nina_keepout["minimumHighLargeMetalClearanceMm"], 10.0):
        raise ValueError("NINA high/large metal clearance is not 10 mm")
    if not close(nina_keepout["minimumCasingClearanceMm"], 5.0):
        raise ValueError("NINA casing clearance is not 5 mm")
    forbidden = {
        "metal_fastener",
        "conductive_coating",
        "battery_cell",
        "shield_can",
        "cable_bundle",
        "GFRP_spine",
    }
    if set(nina_keepout["forbiddenClasses"]) != forbidden:
        raise ValueError("NINA mechanical forbidden-class set changed")
    if not isinstance(nina_keepout["rearCapIntersectionRequiresChange"], bool):
        raise ValueError("NINA rear-cap intersection result must be boolean")
    if rear_cap_change is not nina_keepout["rearCapIntersectionRequiresChange"]:
        raise ValueError("rearCapChangeRequired does not mirror NINA intersection")

    return {
        "document": document,
        "interfaceSha256": sha256_file(interface_path),
        "sourceBoardPath": source_board_path,
        "routesPath": routes_path,
        "nativeDrcPath": native_drc_path,
        "rearCapChangeRequired": rear_cap_change,
    }


def changed_subjects(validated: dict[str, Any]) -> tuple[str, ...]:
    parts = list(DIRECT_CHANGED_PARTS)
    if validated["rearCapChangeRequired"]:
        parts.append(CONDITIONAL_CHANGED_PART)
    return tuple(parts + [ASSEMBLY_ID])


def immutable_subjects(validated: dict[str, Any]) -> tuple[str, ...]:
    mutable = set(changed_subjects(validated))
    return tuple(subject for subject in ALL_SUBJECTS if subject not in mutable)


def subject_artifact_hashes(root: Path, subjects: tuple[str, ...]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for folder_name in ("outputs", "reports"):
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.name.startswith(subjects):
                rows[path.relative_to(root).as_posix()] = sha256_file(path)
    return rows


def assert_zero_drift(before: dict[str, str], after: dict[str, str]) -> None:
    if before == after:
        return
    changed = sorted(set(before) | set(after))
    changed = [key for key in changed if before.get(key) != after.get(key)]
    raise RuntimeError(f"unchanged subject artifact SHA drift: {changed}")


def execution_plan(root: Path, validated: dict[str, Any]) -> dict[str, Any]:
    mutable = changed_subjects(validated)
    immutable = immutable_subjects(validated)
    baseline = subject_artifact_hashes(root, immutable)
    return {
        "schema": "aicad_wand_only_finalizer_plan_v1",
        "status": "validated_frozen_input_execution_ready",
        "interfaceSha256": validated["interfaceSha256"],
        "changedSubjects": list(mutable),
        "unchangedSubjects": list(immutable),
        "unchangedArtifactCount": len(baseline),
        "unchangedArtifactSha256ByPath": baseline,
        "phases": [
            "normalize_design_input",
            "changed_part_BREP_STEP_SLDPRT_native_reopen",
            "MW-A-001_STEP_SLDASM_native_reopen",
            "electromechanical_interference_and_button_stack",
            "meaningful_true_sections_and_DXF",
            "source_bound_2D_3D_previews",
            "BOM_AWI_inspection_molding_and_positions",
            "reviewer_and_dual_manifests",
            "dedicated_tests_and_zero_drift_assertion",
        ],
    }


def execute_finalization(root: Path, validated: dict[str, Any]) -> None:
    from wand_release_execution import execute

    immutable = immutable_subjects(validated)
    before = subject_artifact_hashes(root, immutable)
    execute(
        root,
        validated,
        before,
        subject_artifact_hashes,
        immutable,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed wand electromechanical finalizer")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--interface", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--print-contract", action="store_true")
    parser.add_argument("--phase", choices=("native", "drawings", "package"))
    args = parser.parse_args()
    root = args.root.resolve()
    if args.phase:
        from wand_release_execution import (
            run_drawing_phase,
            run_native_phase,
            run_package_phase,
        )

        {"native": run_native_phase, "drawings": run_drawing_phase, "package": run_package_phase}[
            args.phase
        ](root)
        return 0
    if args.print_contract:
        print(json.dumps(INPUT_FIELD_CONTRACT, ensure_ascii=False, indent=2))
        return 0
    if args.interface is None:
        parser.error("--interface is required unless --print-contract or --phase is used")
    interface_path = args.interface.resolve()
    repository = root.parents[3]
    validated = validate_wand_interface(repository, interface_path)
    plan = execution_plan(root, validated)
    if not args.validate_only:
        execute_finalization(root, validated)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
