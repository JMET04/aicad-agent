"""Fail-closed validation for a civil engineering review candidate.

This module does not generate a civil design and does not certify one.  It
checks that a small coordination slice is explicit, source-bound and
geometrically self-consistent enough to be shown to a civil reviewer.  A
successful report authorizes only the output class ``review_candidate``.

LandXML authoring, hydraulic modelling, construction documents and licensed
professional signing/sealing deliberately remain outside this boundary.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_ID = "aicad_civil_review_candidate_v1"
REPORT_SCHEMA_ID = "aicad_civil_review_report_v1"
OUTPUT_CLASS = "review_candidate"

EXPECTED_LOCKS = {
    "reviewOnly": True,
    "productionRelease": False,
    "professionalRelease": False,
    "constructionUse": False,
}

RELEASE_BOUNDARY = {
    "reviewOnly": True,
    "productionArtifactExposureGranted": False,
    "professionalReleaseGranted": False,
    "constructionUseGranted": False,
    "signedOrSealed": False,
}

EXTERNAL_WORK_REQUIRED = {
    "landXmlGeneration": "external_civil_tool_required",
    "hydraulicAnalysis": "external_specialist_model_required",
    "constructionDocuments": "external_professional_release_required",
    "professionalSeal": "external_licensed_professional_required",
}

MAPPING_RULE = (
    "ground_xy_m=origin_m+R(rotation_deg)*(drawing_xy_mm-origin_xy_mm)"
    "/1000*groundScaleFactor"
)

_TOP_FIELDS = frozenset(
    {
        "schema",
        "candidateId",
        "project",
        "coordinateReference",
        "sources",
        "surveyControls",
        "alignment",
        "profile",
        "drainage",
        "disciplineSources",
        "locks",
    }
)
_PROJECT_FIELDS = frozenset({"name", "jurisdiction", "stage"})
_JURISDICTION_FIELDS = frozenset(
    {"countryCode", "administrativeArea", "authority", "codeBasis"}
)
_COORDINATE_FIELDS = frozenset(
    {"horizontal", "vertical", "localMapping", "siteBounds"}
)
_HORIZONTAL_FIELDS = frozenset({"type", "epsg", "localGrid", "datum", "epoch"})
_LOCAL_GRID_FIELDS = frozenset({"name", "definition", "authoritySourceId"})
_STATUS_REFERENCE_FIELDS = frozenset({"status", "value", "sourceId", "rationale"})
_VERTICAL_FIELDS = frozenset({"datum", "geoid"})
_GEOID_FIELDS = frozenset({"status", "model", "sourceId", "rationale"})
_LOCAL_MAPPING_FIELDS = frozenset(
    {
        "drawingUnit",
        "groundUnit",
        "millimetresPerGroundMetre",
        "groundScaleFactor",
        "rotationDegrees",
        "mappingRule",
        "origin",
    }
)
_ORIGIN_FIELDS = frozenset(
    {
        "drawingXmm",
        "drawingYmm",
        "groundEastingM",
        "groundNorthingM",
        "groundElevationM",
        "surveyControlId",
    }
)
_BOUNDS_FIELDS = frozenset(
    {
        "minEastingM",
        "maxEastingM",
        "minNorthingM",
        "maxNorthingM",
        "minElevationM",
        "maxElevationM",
    }
)
_SOURCE_FIELDS = frozenset({"id", "kind", "description", "path", "size", "sha256"})
_CONTROL_FIELDS = frozenset(
    {
        "id",
        "eastingM",
        "northingM",
        "elevationM",
        "horizontalDatum",
        "verticalDatum",
        "observationType",
        "status",
        "sourceId",
    }
)
_ALIGNMENT_FIELDS = frozenset(
    {"id", "sourceId", "stationToleranceM", "joinToleranceM", "segments"}
)
_SEGMENT_FIELDS = frozenset(
    {"id", "startStationM", "endStationM", "start", "end"}
)
_HORIZONTAL_POINT_FIELDS = frozenset({"eastingM", "northingM"})
_PROFILE_FIELDS = frozenset({"id", "sourceId", "stationToleranceM", "points"})
_PROFILE_POINT_FIELDS = frozenset({"stationM", "elevationM"})
_DRAINAGE_FIELDS = frozenset(
    {"id", "sourceId", "flowDirection", "minimumSlope", "maximumSlope", "points"}
)
_DRAINAGE_POINT_FIELDS = frozenset({"stationM", "invertElevationM"})
_DISCIPLINE_FIELDS = frozenset(
    {"utilitySourceIds", "geotechnicalSourceIds", "limitations"}
)

_SOURCE_KINDS = {
    "survey_control",
    "coordinate_authority",
    "utility_record",
    "geotechnical_report",
    "alignment_basis",
    "profile_basis",
    "drainage_basis",
}
_PROJECT_STAGES = {
    "concept_review",
    "survey_review",
    "preliminary_design_review",
    "detailed_design_review",
}
_STABLE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_.-]{2,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_PLACEHOLDERS = {
    "unknown",
    "unresolved",
    "tbd",
    "todo",
    "placeholder",
    "n/a",
    "na",
    "none",
    "datum",
}


def _failure(
    failures: list[dict[str, Any]],
    code: str,
    path: str,
    message: str,
    **details: Any,
) -> None:
    item: dict[str, Any] = {"code": code, "path": path, "message": message}
    if details:
        item["details"] = details
    failures.append(item)


def _as_mapping(
    value: object,
    path: str,
    expected: frozenset[str],
    failures: list[dict[str, Any]],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _failure(failures, "object_required", path, "A JSON object is required.")
        return {}
    actual = set(value)
    if actual != expected:
        _failure(
            failures,
            "field_inventory_mismatch",
            path,
            "Object fields must match the controlled contract exactly.",
            missing=sorted(expected - actual),
            extra=sorted(str(key) for key in actual - expected),
        )
    return value


def _as_array(
    value: object,
    path: str,
    failures: list[dict[str, Any]],
) -> list[Any]:
    if not isinstance(value, list):
        _failure(failures, "array_required", path, "A JSON array is required.")
        return []
    return value


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _number(
    value: object,
    path: str,
    failures: list[dict[str, Any]],
) -> float | None:
    if not _is_number(value):
        _failure(failures, "finite_number_required", path, "A finite number is required.")
        return None
    return float(value)


def _meaningful_text(
    value: object,
    path: str,
    failures: list[dict[str, Any]],
    *,
    code: str = "controlled_text_required",
) -> str | None:
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() in _PLACEHOLDERS:
        _failure(
            failures,
            code,
            path,
            "Non-placeholder controlled text is required.",
        )
        return None
    return value.strip()


def _stable_id(
    value: object,
    path: str,
    failures: list[dict[str, Any]],
) -> str | None:
    if not isinstance(value, str) or not _STABLE_ID_RE.fullmatch(value):
        _failure(
            failures,
            "stable_id_required",
            path,
            "A stable uppercase ASCII engineering identifier is required.",
        )
        return None
    return value


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)
    except OSError:
        return False


def _controlled_evidence_root(
    evidence_root: str | os.PathLike[str] | None,
    failures: list[dict[str, Any]],
) -> tuple[Path | None, Path | None]:
    if evidence_root is None:
        _failure(
            failures,
            "evidence_root_required",
            "$.sources",
            "A controlled evidence root is required.",
        )
        return None, None
    try:
        root = Path(evidence_root)
    except TypeError:
        _failure(
            failures,
            "evidence_root_invalid",
            "$.sources",
            "The controlled evidence root is not path-like.",
        )
        return None, None
    if not root.exists():
        _failure(
            failures,
            "evidence_root_missing",
            "$.sources",
            "The controlled evidence root does not exist.",
        )
        return None, None
    if not root.is_dir():
        _failure(
            failures,
            "evidence_root_not_directory",
            "$.sources",
            "The controlled evidence root must be a directory.",
        )
        return None, None
    if _is_reparse(root):
        _failure(
            failures,
            "evidence_root_reparse_forbidden",
            "$.sources",
            "A symlink or junction cannot be the controlled evidence root.",
        )
        return None, None
    try:
        return root, root.resolve(strict=True)
    except OSError:
        _failure(
            failures,
            "evidence_root_unresolvable",
            "$.sources",
            "The controlled evidence root cannot be resolved.",
        )
        return None, None


def _safe_relative_path(value: object) -> tuple[PurePosixPath | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, "path must be non-empty text"
    if "\\" in value or ":" in value or _WINDOWS_DRIVE_RE.match(value):
        return None, (
            "path must use relative POSIX separators and may not include a drive "
            "or alternate-data-stream separator"
        )
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None, "path must remain below the controlled evidence root"
    return relative, None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_file(
    row: Mapping[str, Any],
    path: str,
    root: Path | None,
    resolved_root: Path | None,
    failures: list[dict[str, Any]],
) -> None:
    relative, reason = _safe_relative_path(row.get("path"))
    if reason is not None:
        _failure(failures, "source_path_unsafe", f"{path}.path", reason)
        return

    declared_size = row.get("size")
    if isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size < 0:
        _failure(
            failures,
            "source_size_invalid",
            f"{path}.size",
            "Source size must be a non-negative integer byte count.",
        )
    declared_sha = row.get("sha256")
    if not isinstance(declared_sha, str) or not _SHA256_RE.fullmatch(declared_sha):
        _failure(
            failures,
            "source_sha256_invalid",
            f"{path}.sha256",
            "Source SHA-256 must be 64 lowercase hexadecimal characters.",
        )

    if root is None or resolved_root is None or relative is None:
        return
    target = root.joinpath(*relative.parts)
    if not target.exists():
        _failure(
            failures,
            "source_file_missing",
            f"{path}.path",
            "The declared source file does not exist below the evidence root.",
            declaredPath=str(relative),
        )
        return

    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_reparse(cursor):
            _failure(
                failures,
                "source_file_reparse_forbidden",
                f"{path}.path",
                "Source paths may not traverse a symlink or junction.",
                declaredPath=str(relative),
            )
            return
    try:
        resolved = target.resolve(strict=True)
    except OSError:
        _failure(
            failures,
            "source_file_unresolvable",
            f"{path}.path",
            "The declared source file cannot be resolved.",
        )
        return
    if resolved == resolved_root or resolved_root not in resolved.parents:
        _failure(
            failures,
            "source_file_outside_evidence_root",
            f"{path}.path",
            "The declared source resolves outside the controlled evidence root.",
        )
        return
    if not target.is_file():
        _failure(
            failures,
            "source_not_file",
            f"{path}.path",
            "The declared source must be a regular file.",
        )
        return
    try:
        actual_size = target.stat().st_size
        actual_sha = _sha256_file(target)
    except OSError:
        _failure(
            failures,
            "source_file_unreadable",
            f"{path}.path",
            "The declared source file cannot be read.",
        )
        return
    if declared_size != actual_size:
        _failure(
            failures,
            "source_size_mismatch",
            f"{path}.size",
            "Declared source size does not match the controlled file.",
            declared=declared_size,
            actual=actual_size,
        )
    if declared_sha != actual_sha:
        _failure(
            failures,
            "source_sha256_mismatch",
            f"{path}.sha256",
            "Declared SHA-256 does not match the controlled file.",
            declared=declared_sha,
            actual=actual_sha,
        )


def _source_reference(
    source_id: object,
    path: str,
    allowed_kinds: set[str],
    sources: Mapping[str, Mapping[str, Any]],
    failures: list[dict[str, Any]],
    code: str,
) -> None:
    if not isinstance(source_id, str) or source_id not in sources:
        _failure(
            failures,
            code,
            path,
            "The referenced controlled source does not exist.",
            sourceId=source_id,
            allowedKinds=sorted(allowed_kinds),
        )
        return
    actual_kind = sources[source_id].get("kind")
    if actual_kind not in allowed_kinds:
        _failure(
            failures,
            code,
            path,
            "The controlled source has the wrong evidence kind.",
            sourceId=source_id,
            actualKind=actual_kind,
            allowedKinds=sorted(allowed_kinds),
        )


def _point_in_bounds(
    easting: float | None,
    northing: float | None,
    elevation: float | None,
    bounds: Mapping[str, float] | None,
) -> bool:
    if bounds is None or easting is None or northing is None:
        return True
    if not (
        bounds["minEastingM"] <= easting <= bounds["maxEastingM"]
        and bounds["minNorthingM"] <= northing <= bounds["maxNorthingM"]
    ):
        return False
    return elevation is None or bounds["minElevationM"] <= elevation <= bounds["maxElevationM"]


def _category_ok(failures: list[dict[str, Any]], prefixes: tuple[str, ...]) -> bool:
    return not any(item["code"].startswith(prefixes) for item in failures)


def validate_civil_review_candidate(
    value: object,
    evidence_root: str | os.PathLike[str] | None,
) -> dict[str, Any]:
    """Validate a source-bound civil review candidate and aggregate failures.

    The function intentionally returns a report instead of raising on the first
    defect so that a reviewer can correct several independent civil-data issues
    in one pass.
    """

    failures: list[dict[str, Any]] = []
    root, resolved_root = _controlled_evidence_root(evidence_root, failures)
    candidate = _as_mapping(value, "$", _TOP_FIELDS, failures)

    if candidate.get("schema") != SCHEMA_ID:
        _failure(
            failures,
            "schema_identity_invalid",
            "$.schema",
            f"Schema must be {SCHEMA_ID}.",
        )
    candidate_id = _stable_id(candidate.get("candidateId"), "$.candidateId", failures)

    project = _as_mapping(candidate.get("project"), "$.project", _PROJECT_FIELDS, failures)
    _meaningful_text(project.get("name"), "$.project.name", failures)
    stage = project.get("stage")
    if stage not in _PROJECT_STAGES:
        _failure(
            failures,
            "project_stage_invalid",
            "$.project.stage",
            "Only a declared review stage is allowed; construction/issue stages are external.",
            allowed=sorted(_PROJECT_STAGES),
        )
    jurisdiction = _as_mapping(
        project.get("jurisdiction"),
        "$.project.jurisdiction",
        _JURISDICTION_FIELDS,
        failures,
    )
    country = jurisdiction.get("countryCode")
    if not isinstance(country, str) or not _COUNTRY_RE.fullmatch(country):
        _failure(
            failures,
            "jurisdiction_country_invalid",
            "$.project.jurisdiction.countryCode",
            "Jurisdiction countryCode must be ISO-style uppercase alpha-2 text.",
        )
    for field in ("administrativeArea", "authority", "codeBasis"):
        _meaningful_text(
            jurisdiction.get(field),
            f"$.project.jurisdiction.{field}",
            failures,
            code="jurisdiction_declaration_invalid",
        )

    sources_raw = _as_array(candidate.get("sources"), "$.sources", failures)
    if not sources_raw:
        _failure(
            failures,
            "source_inventory_empty",
            "$.sources",
            "At least one controlled source is required.",
        )
    sources: dict[str, Mapping[str, Any]] = {}
    duplicate_source_ids: set[str] = set()
    for index, raw in enumerate(sources_raw):
        source_path = f"$.sources[{index}]"
        row = _as_mapping(raw, source_path, _SOURCE_FIELDS, failures)
        source_id = _stable_id(row.get("id"), f"{source_path}.id", failures)
        if source_id is not None:
            if source_id in sources:
                duplicate_source_ids.add(source_id)
            else:
                sources[source_id] = row
        if row.get("kind") not in _SOURCE_KINDS:
            _failure(
                failures,
                "source_kind_invalid",
                f"{source_path}.kind",
                "Source kind is outside the controlled civil evidence vocabulary.",
            )
        _meaningful_text(row.get("description"), f"{source_path}.description", failures)
        _validate_source_file(row, source_path, root, resolved_root, failures)
    if duplicate_source_ids:
        _failure(
            failures,
            "source_id_duplicate",
            "$.sources",
            "Controlled source IDs must be unique.",
            duplicateIds=sorted(duplicate_source_ids),
        )

    coordinate = _as_mapping(
        candidate.get("coordinateReference"),
        "$.coordinateReference",
        _COORDINATE_FIELDS,
        failures,
    )
    horizontal = _as_mapping(
        coordinate.get("horizontal"),
        "$.coordinateReference.horizontal",
        _HORIZONTAL_FIELDS,
        failures,
    )
    horizontal_type = horizontal.get("type")
    horizontal_datum = _meaningful_text(
        horizontal.get("datum"),
        "$.coordinateReference.horizontal.datum",
        failures,
        code="horizontal_datum_invalid",
    )
    if horizontal_type == "epsg":
        epsg = horizontal.get("epsg")
        if isinstance(epsg, bool) or not isinstance(epsg, int) or not 1000 <= epsg <= 999999:
            _failure(
                failures,
                "horizontal_crs_invalid",
                "$.coordinateReference.horizontal.epsg",
                "EPSG mode requires an integer EPSG code from 1000 through 999999.",
            )
        if horizontal.get("localGrid") is not None:
            _failure(
                failures,
                "horizontal_crs_invalid",
                "$.coordinateReference.horizontal.localGrid",
                "EPSG mode requires localGrid to be null.",
            )
    elif horizontal_type == "local_grid":
        if horizontal.get("epsg") is not None:
            _failure(
                failures,
                "horizontal_crs_invalid",
                "$.coordinateReference.horizontal.epsg",
                "Local-grid mode requires epsg to be null.",
            )
        local_grid = _as_mapping(
            horizontal.get("localGrid"),
            "$.coordinateReference.horizontal.localGrid",
            _LOCAL_GRID_FIELDS,
            failures,
        )
        _meaningful_text(
            local_grid.get("name"),
            "$.coordinateReference.horizontal.localGrid.name",
            failures,
            code="horizontal_crs_invalid",
        )
        _meaningful_text(
            local_grid.get("definition"),
            "$.coordinateReference.horizontal.localGrid.definition",
            failures,
            code="horizontal_crs_invalid",
        )
        _source_reference(
            local_grid.get("authoritySourceId"),
            "$.coordinateReference.horizontal.localGrid.authoritySourceId",
            {"coordinate_authority"},
            sources,
            failures,
            "horizontal_crs_source_invalid",
        )
    else:
        _failure(
            failures,
            "horizontal_crs_invalid",
            "$.coordinateReference.horizontal.type",
            "Horizontal CRS must be EPSG or an explicitly defined local grid.",
        )

    epoch = _as_mapping(
        horizontal.get("epoch"),
        "$.coordinateReference.horizontal.epoch",
        _STATUS_REFERENCE_FIELDS,
        failures,
    )
    epoch_status = epoch.get("status")
    if epoch_status == "declared":
        epoch_value = _number(
            epoch.get("value"), "$.coordinateReference.horizontal.epoch.value", failures
        )
        if epoch_value is not None and not 1900.0 <= epoch_value <= 2200.0:
            _failure(
                failures,
                "epoch_value_invalid",
                "$.coordinateReference.horizontal.epoch.value",
                "Declared coordinate epoch is outside the controlled review range 1900..2200.",
            )
        _source_reference(
            epoch.get("sourceId"),
            "$.coordinateReference.horizontal.epoch.sourceId",
            {"coordinate_authority", "survey_control"},
            sources,
            failures,
            "epoch_source_invalid",
        )
    elif epoch_status == "not_applicable":
        if epoch.get("value") is not None or epoch.get("sourceId") is not None:
            _failure(
                failures,
                "epoch_not_applicable_invalid",
                "$.coordinateReference.horizontal.epoch",
                "Not-applicable epoch must have null value and sourceId.",
            )
        _meaningful_text(
            epoch.get("rationale"),
            "$.coordinateReference.horizontal.epoch.rationale",
            failures,
            code="epoch_not_applicable_invalid",
        )
    else:
        _failure(
            failures,
            "epoch_unresolved",
            "$.coordinateReference.horizontal.epoch.status",
            "Coordinate epoch must be declared or explicitly not applicable.",
        )

    vertical = _as_mapping(
        coordinate.get("vertical"),
        "$.coordinateReference.vertical",
        _VERTICAL_FIELDS,
        failures,
    )
    vertical_datum = _meaningful_text(
        vertical.get("datum"),
        "$.coordinateReference.vertical.datum",
        failures,
        code="vertical_datum_invalid",
    )
    geoid = _as_mapping(
        vertical.get("geoid"),
        "$.coordinateReference.vertical.geoid",
        _GEOID_FIELDS,
        failures,
    )
    geoid_status = geoid.get("status")
    if geoid_status == "declared":
        _meaningful_text(
            geoid.get("model"),
            "$.coordinateReference.vertical.geoid.model",
            failures,
            code="geoid_model_invalid",
        )
        _source_reference(
            geoid.get("sourceId"),
            "$.coordinateReference.vertical.geoid.sourceId",
            {"coordinate_authority", "survey_control"},
            sources,
            failures,
            "geoid_source_invalid",
        )
    elif geoid_status == "not_applicable":
        if geoid.get("model") is not None or geoid.get("sourceId") is not None:
            _failure(
                failures,
                "geoid_not_applicable_invalid",
                "$.coordinateReference.vertical.geoid",
                "Not-applicable geoid must have null model and sourceId.",
            )
        _meaningful_text(
            geoid.get("rationale"),
            "$.coordinateReference.vertical.geoid.rationale",
            failures,
            code="geoid_not_applicable_invalid",
        )
    else:
        _failure(
            failures,
            "geoid_unresolved",
            "$.coordinateReference.vertical.geoid.status",
            "Geoid status must be declared or explicitly not applicable.",
        )

    bounds_raw = _as_mapping(
        coordinate.get("siteBounds"),
        "$.coordinateReference.siteBounds",
        _BOUNDS_FIELDS,
        failures,
    )
    parsed_bounds: dict[str, float] = {}
    for field in _BOUNDS_FIELDS:
        parsed = _number(
            bounds_raw.get(field), f"$.coordinateReference.siteBounds.{field}", failures
        )
        if parsed is not None:
            parsed_bounds[field] = parsed
    bounds: Mapping[str, float] | None = None
    if len(parsed_bounds) == len(_BOUNDS_FIELDS):
        invalid_axes = []
        for minimum, maximum, axis in (
            ("minEastingM", "maxEastingM", "easting"),
            ("minNorthingM", "maxNorthingM", "northing"),
            ("minElevationM", "maxElevationM", "elevation"),
        ):
            if parsed_bounds[minimum] >= parsed_bounds[maximum]:
                invalid_axes.append(axis)
        if invalid_axes:
            _failure(
                failures,
                "site_bounds_invalid",
                "$.coordinateReference.siteBounds",
                "Every site-bound minimum must be less than its maximum.",
                invalidAxes=invalid_axes,
            )
        else:
            bounds = parsed_bounds

    local_mapping = _as_mapping(
        coordinate.get("localMapping"),
        "$.coordinateReference.localMapping",
        _LOCAL_MAPPING_FIELDS,
        failures,
    )
    mapping_constants = {
        "drawingUnit": "mm",
        "groundUnit": "m",
        "millimetresPerGroundMetre": 1000,
        "mappingRule": MAPPING_RULE,
    }
    for field, expected in mapping_constants.items():
        if local_mapping.get(field) != expected:
            _failure(
                failures,
                "local_mapping_invalid",
                f"$.coordinateReference.localMapping.{field}",
                "The mm-to-ground-m mapping constant is not exact.",
                expected=expected,
            )
    scale = _number(
        local_mapping.get("groundScaleFactor"),
        "$.coordinateReference.localMapping.groundScaleFactor",
        failures,
    )
    if scale is not None and scale <= 0:
        _failure(
            failures,
            "local_mapping_invalid",
            "$.coordinateReference.localMapping.groundScaleFactor",
            "Ground scale factor must be greater than zero.",
        )
    rotation = _number(
        local_mapping.get("rotationDegrees"),
        "$.coordinateReference.localMapping.rotationDegrees",
        failures,
    )
    if rotation is not None and not -360 <= rotation <= 360:
        _failure(
            failures,
            "local_mapping_invalid",
            "$.coordinateReference.localMapping.rotationDegrees",
            "Mapping rotation must be within -360..360 degrees.",
        )
    origin = _as_mapping(
        local_mapping.get("origin"),
        "$.coordinateReference.localMapping.origin",
        _ORIGIN_FIELDS,
        failures,
    )
    drawing_x = _number(
        origin.get("drawingXmm"),
        "$.coordinateReference.localMapping.origin.drawingXmm",
        failures,
    )
    drawing_y = _number(
        origin.get("drawingYmm"),
        "$.coordinateReference.localMapping.origin.drawingYmm",
        failures,
    )
    if (drawing_x is not None and abs(drawing_x) > 1e-9) or (
        drawing_y is not None and abs(drawing_y) > 1e-9
    ):
        _failure(
            failures,
            "local_origin_not_zero",
            "$.coordinateReference.localMapping.origin",
            "The controlled drawing origin must be exactly (0 mm, 0 mm).",
        )
    origin_e = _number(
        origin.get("groundEastingM"),
        "$.coordinateReference.localMapping.origin.groundEastingM",
        failures,
    )
    origin_n = _number(
        origin.get("groundNorthingM"),
        "$.coordinateReference.localMapping.origin.groundNorthingM",
        failures,
    )
    origin_z = _number(
        origin.get("groundElevationM"),
        "$.coordinateReference.localMapping.origin.groundElevationM",
        failures,
    )
    if not _point_in_bounds(origin_e, origin_n, origin_z, bounds):
        _failure(
            failures,
            "local_origin_outside_site_bounds",
            "$.coordinateReference.localMapping.origin",
            "Controlled local origin lies outside the declared site bounds.",
        )

    controls_raw = _as_array(candidate.get("surveyControls"), "$.surveyControls", failures)
    if len(controls_raw) < 2:
        _failure(
            failures,
            "survey_control_count_insufficient",
            "$.surveyControls",
            "At least two field-observed, verified survey controls are required.",
            actual=len(controls_raw),
        )
    controls: dict[str, dict[str, Any]] = {}
    duplicate_control_ids: set[str] = set()
    control_coordinates: list[tuple[str, float, float, float]] = []
    for index, raw in enumerate(controls_raw):
        control_path = f"$.surveyControls[{index}]"
        row = _as_mapping(raw, control_path, _CONTROL_FIELDS, failures)
        control_id = _stable_id(row.get("id"), f"{control_path}.id", failures)
        if control_id is not None:
            if control_id in controls:
                duplicate_control_ids.add(control_id)
            else:
                controls[control_id] = dict(row)
        easting = _number(row.get("eastingM"), f"{control_path}.eastingM", failures)
        northing = _number(row.get("northingM"), f"{control_path}.northingM", failures)
        elevation = _number(row.get("elevationM"), f"{control_path}.elevationM", failures)
        if control_id is not None and easting is not None and northing is not None and elevation is not None:
            control_coordinates.append((control_id, easting, northing, elevation))
        if not _point_in_bounds(easting, northing, elevation, bounds):
            _failure(
                failures,
                "survey_control_outside_site_bounds",
                control_path,
                "Survey control lies outside the declared site bounds.",
            )
        if row.get("observationType") != "field_observed" or row.get("status") != "verified":
            _failure(
                failures,
                "survey_control_not_real_verified",
                control_path,
                "Only field-observed and verified survey controls satisfy this boundary.",
            )
        control_h_datum = _meaningful_text(
            row.get("horizontalDatum"),
            f"{control_path}.horizontalDatum",
            failures,
            code="survey_control_datum_invalid",
        )
        control_v_datum = _meaningful_text(
            row.get("verticalDatum"),
            f"{control_path}.verticalDatum",
            failures,
            code="survey_control_datum_invalid",
        )
        if (
            horizontal_datum is not None
            and control_h_datum is not None
            and horizontal_datum.casefold() != control_h_datum.casefold()
        ) or (
            vertical_datum is not None
            and control_v_datum is not None
            and vertical_datum.casefold() != control_v_datum.casefold()
        ):
            _failure(
                failures,
                "survey_control_datum_mismatch",
                control_path,
                "Survey control datums must match the declared project datums.",
            )
        _source_reference(
            row.get("sourceId"),
            f"{control_path}.sourceId",
            {"survey_control"},
            sources,
            failures,
            "survey_control_source_invalid",
        )
    if duplicate_control_ids:
        _failure(
            failures,
            "survey_control_id_duplicate",
            "$.surveyControls",
            "Survey control IDs must be unique.",
            duplicateIds=sorted(duplicate_control_ids),
        )
    if len(control_coordinates) >= 2:
        maximum_baseline = max(
            math.hypot(first[1] - second[1], first[2] - second[2])
            for first_index, first in enumerate(control_coordinates)
            for second in control_coordinates[first_index + 1 :]
        )
        if maximum_baseline <= 0.01:
            _failure(
                failures,
                "survey_controls_not_distinct",
                "$.surveyControls",
                "Survey control network must contain at least two distinct horizontal points.",
                maximumBaselineM=maximum_baseline,
            )

    origin_control_id = origin.get("surveyControlId")
    if not isinstance(origin_control_id, str) or origin_control_id not in controls:
        _failure(
            failures,
            "local_origin_control_missing",
            "$.coordinateReference.localMapping.origin.surveyControlId",
            "Local mapping origin must reference one declared survey control.",
        )
    elif all(value is not None for value in (origin_e, origin_n, origin_z)):
        control = controls[origin_control_id]
        control_values = (control.get("eastingM"), control.get("northingM"), control.get("elevationM"))
        if all(_is_number(value) for value in control_values):
            horizontal_delta = math.hypot(
                float(control_values[0]) - float(origin_e),
                float(control_values[1]) - float(origin_n),
            )
            vertical_delta = abs(float(control_values[2]) - float(origin_z))
            if horizontal_delta > 0.02 or vertical_delta > 0.03:
                _failure(
                    failures,
                    "local_origin_control_mismatch",
                    "$.coordinateReference.localMapping.origin",
                    "Local origin does not match its survey control within 0.02 m horizontal and 0.03 m vertical.",
                    horizontalDeltaM=horizontal_delta,
                    verticalDeltaM=vertical_delta,
                )

    alignment = _as_mapping(
        candidate.get("alignment"), "$.alignment", _ALIGNMENT_FIELDS, failures
    )
    _stable_id(alignment.get("id"), "$.alignment.id", failures)
    _source_reference(
        alignment.get("sourceId"),
        "$.alignment.sourceId",
        {"alignment_basis", "survey_control"},
        sources,
        failures,
        "alignment_source_invalid",
    )
    station_tolerance = _number(
        alignment.get("stationToleranceM"), "$.alignment.stationToleranceM", failures
    )
    join_tolerance = _number(
        alignment.get("joinToleranceM"), "$.alignment.joinToleranceM", failures
    )
    if station_tolerance is None or not 0 < station_tolerance <= 1:
        _failure(
            failures,
            "alignment_tolerance_invalid",
            "$.alignment.stationToleranceM",
            "Alignment station tolerance must be greater than 0 and no more than 1 m.",
        )
        station_tolerance = 1e-6
    if join_tolerance is None or not 0 < join_tolerance <= 1:
        _failure(
            failures,
            "alignment_tolerance_invalid",
            "$.alignment.joinToleranceM",
            "Alignment join tolerance must be greater than 0 and no more than 1 m.",
        )
        join_tolerance = 1e-6
    segments_raw = _as_array(alignment.get("segments"), "$.alignment.segments", failures)
    if not segments_raw:
        _failure(
            failures,
            "alignment_empty",
            "$.alignment.segments",
            "At least one alignment segment is required.",
        )
    segment_ids: set[str] = set()
    parsed_segments: list[dict[str, Any]] = []
    for index, raw in enumerate(segments_raw):
        segment_path = f"$.alignment.segments[{index}]"
        row = _as_mapping(raw, segment_path, _SEGMENT_FIELDS, failures)
        segment_id = _stable_id(row.get("id"), f"{segment_path}.id", failures)
        if segment_id is not None:
            if segment_id in segment_ids:
                _failure(
                    failures,
                    "alignment_segment_id_duplicate",
                    f"{segment_path}.id",
                    "Alignment segment IDs must be unique.",
                )
            segment_ids.add(segment_id)
        start_station = _number(
            row.get("startStationM"), f"{segment_path}.startStationM", failures
        )
        end_station = _number(
            row.get("endStationM"), f"{segment_path}.endStationM", failures
        )
        start = _as_mapping(
            row.get("start"), f"{segment_path}.start", _HORIZONTAL_POINT_FIELDS, failures
        )
        end = _as_mapping(
            row.get("end"), f"{segment_path}.end", _HORIZONTAL_POINT_FIELDS, failures
        )
        start_e = _number(start.get("eastingM"), f"{segment_path}.start.eastingM", failures)
        start_n = _number(start.get("northingM"), f"{segment_path}.start.northingM", failures)
        end_e = _number(end.get("eastingM"), f"{segment_path}.end.eastingM", failures)
        end_n = _number(end.get("northingM"), f"{segment_path}.end.northingM", failures)
        if start_station is not None and end_station is not None and end_station <= start_station + station_tolerance:
            _failure(
                failures,
                "alignment_station_order_invalid",
                segment_path,
                "Each alignment segment must have increasing station.",
            )
        if not _point_in_bounds(start_e, start_n, None, bounds) or not _point_in_bounds(
            end_e, end_n, None, bounds
        ):
            _failure(
                failures,
                "alignment_outside_site_bounds",
                segment_path,
                "Alignment endpoint lies outside the declared site bounds.",
            )
        if all(item is not None for item in (start_e, start_n, end_e, end_n)) and math.hypot(
            end_e - start_e, end_n - start_n
        ) <= join_tolerance:
            _failure(
                failures,
                "alignment_zero_length_geometry",
                segment_path,
                "Alignment segment geometry is zero-length within join tolerance.",
            )
        parsed_segments.append(
            {
                "startStationM": start_station,
                "endStationM": end_station,
                "startE": start_e,
                "startN": start_n,
                "endE": end_e,
                "endN": end_n,
            }
        )
    for index in range(1, len(parsed_segments)):
        previous = parsed_segments[index - 1]
        current = parsed_segments[index]
        if previous["endStationM"] is not None and current["startStationM"] is not None:
            station_gap = current["startStationM"] - previous["endStationM"]
            if abs(station_gap) > station_tolerance:
                _failure(
                    failures,
                    "alignment_station_discontinuity",
                    f"$.alignment.segments[{index}]",
                    "Adjacent alignment station ranges are disconnected.",
                    stationGapM=station_gap,
                    toleranceM=station_tolerance,
                )
        coordinate_values = (
            previous["endE"],
            previous["endN"],
            current["startE"],
            current["startN"],
        )
        if all(item is not None for item in coordinate_values):
            join_gap = math.hypot(
                current["startE"] - previous["endE"],
                current["startN"] - previous["endN"],
            )
            if join_gap > join_tolerance:
                _failure(
                    failures,
                    "alignment_geometry_discontinuity",
                    f"$.alignment.segments[{index}]",
                    "Adjacent alignment segment endpoints are disconnected.",
                    joinGapM=join_gap,
                    toleranceM=join_tolerance,
                )
    alignment_extent: tuple[float, float] | None = None
    if parsed_segments and parsed_segments[0]["startStationM"] is not None and parsed_segments[-1]["endStationM"] is not None:
        alignment_extent = (
            parsed_segments[0]["startStationM"],
            parsed_segments[-1]["endStationM"],
        )

    profile = _as_mapping(candidate.get("profile"), "$.profile", _PROFILE_FIELDS, failures)
    _stable_id(profile.get("id"), "$.profile.id", failures)
    _source_reference(
        profile.get("sourceId"),
        "$.profile.sourceId",
        {"profile_basis", "survey_control"},
        sources,
        failures,
        "profile_source_invalid",
    )
    profile_tolerance = _number(
        profile.get("stationToleranceM"), "$.profile.stationToleranceM", failures
    )
    if profile_tolerance is None or not 0 < profile_tolerance <= 1:
        _failure(
            failures,
            "profile_tolerance_invalid",
            "$.profile.stationToleranceM",
            "Profile station tolerance must be greater than 0 and no more than 1 m.",
        )
        profile_tolerance = 1e-6
    profile_points_raw = _as_array(profile.get("points"), "$.profile.points", failures)
    if len(profile_points_raw) < 2:
        _failure(
            failures,
            "profile_point_count_insufficient",
            "$.profile.points",
            "At least two profile points are required.",
        )
    previous_profile_station: float | None = None
    for index, raw in enumerate(profile_points_raw):
        point_path = f"$.profile.points[{index}]"
        row = _as_mapping(raw, point_path, _PROFILE_POINT_FIELDS, failures)
        station_value = _number(row.get("stationM"), f"{point_path}.stationM", failures)
        elevation_value = _number(row.get("elevationM"), f"{point_path}.elevationM", failures)
        if (
            station_value is not None
            and previous_profile_station is not None
            and station_value <= previous_profile_station + profile_tolerance
        ):
            _failure(
                failures,
                "profile_station_non_monotonic",
                point_path,
                "Profile stations must be strictly increasing in listed order.",
            )
        if station_value is not None:
            previous_profile_station = station_value
            if alignment_extent is not None and not (
                alignment_extent[0] - profile_tolerance
                <= station_value
                <= alignment_extent[1] + profile_tolerance
            ):
                _failure(
                    failures,
                    "profile_station_outside_alignment",
                    point_path,
                    "Profile station lies outside the alignment station extent.",
                )
        if elevation_value is not None and bounds is not None and not (
            bounds["minElevationM"] <= elevation_value <= bounds["maxElevationM"]
        ):
            _failure(
                failures,
                "profile_elevation_outside_site_bounds",
                point_path,
                "Profile elevation lies outside the declared site bounds.",
            )

    drainage = _as_mapping(
        candidate.get("drainage"), "$.drainage", _DRAINAGE_FIELDS, failures
    )
    _stable_id(drainage.get("id"), "$.drainage.id", failures)
    _source_reference(
        drainage.get("sourceId"),
        "$.drainage.sourceId",
        {"drainage_basis", "survey_control"},
        sources,
        failures,
        "drainage_source_invalid",
    )
    flow_direction = drainage.get("flowDirection")
    if flow_direction not in {"increasing_station", "decreasing_station"}:
        _failure(
            failures,
            "drainage_flow_direction_invalid",
            "$.drainage.flowDirection",
            "Drainage flow direction must be explicitly tied to station order.",
        )
    minimum_slope = _number(
        drainage.get("minimumSlope"), "$.drainage.minimumSlope", failures
    )
    maximum_slope = _number(
        drainage.get("maximumSlope"), "$.drainage.maximumSlope", failures
    )
    if (
        minimum_slope is None
        or maximum_slope is None
        or minimum_slope < 0
        or maximum_slope <= 0
        or minimum_slope > maximum_slope
        or maximum_slope > 1
    ):
        _failure(
            failures,
            "drainage_slope_limits_invalid",
            "$.drainage",
            "Drainage slope limits must satisfy 0 <= minimum <= maximum <= 1 with maximum > 0.",
        )
    drainage_points_raw = _as_array(drainage.get("points"), "$.drainage.points", failures)
    if len(drainage_points_raw) < 2:
        _failure(
            failures,
            "drainage_point_count_insufficient",
            "$.drainage.points",
            "At least two drainage invert points are required.",
        )
    drainage_points: list[tuple[float | None, float | None]] = []
    for index, raw in enumerate(drainage_points_raw):
        point_path = f"$.drainage.points[{index}]"
        row = _as_mapping(raw, point_path, _DRAINAGE_POINT_FIELDS, failures)
        station_value = _number(row.get("stationM"), f"{point_path}.stationM", failures)
        invert_value = _number(
            row.get("invertElevationM"), f"{point_path}.invertElevationM", failures
        )
        if station_value is not None and alignment_extent is not None and not (
            alignment_extent[0] - station_tolerance
            <= station_value
            <= alignment_extent[1] + station_tolerance
        ):
            _failure(
                failures,
                "drainage_station_outside_alignment",
                point_path,
                "Drainage station lies outside the alignment station extent.",
            )
        if invert_value is not None and bounds is not None and not (
            bounds["minElevationM"] <= invert_value <= bounds["maxElevationM"]
        ):
            _failure(
                failures,
                "drainage_elevation_outside_site_bounds",
                point_path,
                "Drainage invert lies outside the declared site bounds.",
            )
        drainage_points.append((station_value, invert_value))
    for index in range(1, len(drainage_points)):
        previous_station, previous_invert = drainage_points[index - 1]
        current_station, current_invert = drainage_points[index]
        if previous_station is None or current_station is None:
            continue
        station_delta = current_station - previous_station
        expected_order = (
            station_delta > station_tolerance
            if flow_direction == "increasing_station"
            else station_delta < -station_tolerance
        )
        if not expected_order:
            _failure(
                failures,
                "drainage_station_non_monotonic",
                f"$.drainage.points[{index}]",
                "Drainage stations must be strictly monotonic along the declared flow direction.",
                stationDeltaM=station_delta,
            )
            continue
        if previous_invert is None or current_invert is None:
            continue
        run = abs(station_delta)
        drop = previous_invert - current_invert
        if drop < -1e-9:
            _failure(
                failures,
                "drainage_uphill",
                f"$.drainage.points[{index}]",
                "Drainage invert rises along the declared gravity-flow direction.",
                elevationRiseM=-drop,
            )
        slope = drop / run
        if (
            minimum_slope is not None
            and maximum_slope is not None
            and (slope < minimum_slope - 1e-12 or slope > maximum_slope + 1e-12)
        ):
            _failure(
                failures,
                "drainage_slope_out_of_range",
                f"$.drainage.points[{index}]",
                "Drainage segment slope lies outside the declared controlled range.",
                slope=slope,
                minimumSlope=minimum_slope,
                maximumSlope=maximum_slope,
            )

    discipline = _as_mapping(
        candidate.get("disciplineSources"),
        "$.disciplineSources",
        _DISCIPLINE_FIELDS,
        failures,
    )
    for field, kind in (
        ("utilitySourceIds", "utility_record"),
        ("geotechnicalSourceIds", "geotechnical_report"),
    ):
        references = _as_array(discipline.get(field), f"$.disciplineSources.{field}", failures)
        if not references:
            _failure(
                failures,
                "discipline_source_missing",
                f"$.disciplineSources.{field}",
                f"At least one controlled {kind} source is required.",
            )
        if len(references) != len({item for item in references if isinstance(item, str)}):
            _failure(
                failures,
                "discipline_source_duplicate",
                f"$.disciplineSources.{field}",
                "Discipline source IDs must be unique.",
            )
        for index, source_id in enumerate(references):
            _source_reference(
                source_id,
                f"$.disciplineSources.{field}[{index}]",
                {kind},
                sources,
                failures,
                "discipline_source_invalid",
            )
    _meaningful_text(
        discipline.get("limitations"),
        "$.disciplineSources.limitations",
        failures,
        code="discipline_limitations_missing",
    )

    locks = _as_mapping(candidate.get("locks"), "$.locks", frozenset(EXPECTED_LOCKS), failures)
    if dict(locks) != EXPECTED_LOCKS:
        _failure(
            failures,
            "safety_locks_invalid",
            "$.locks",
            "Civil candidate safety locks must remain exactly review-only and release-closed.",
            expected=EXPECTED_LOCKS,
        )

    checks = {
        "contractShapeValid": _category_ok(
            failures,
            ("schema_", "object_", "array_", "field_", "stable_id", "finite_number"),
        ),
        "jurisdictionAndStageDeclared": _category_ok(failures, ("jurisdiction_", "project_stage")),
        "coordinateReferenceControlled": _category_ok(
            failures,
            (
                "horizontal_",
                "vertical_",
                "epoch_",
                "geoid_",
                "local_mapping",
                "local_origin",
                "site_bounds",
            ),
        ),
        "sourceEvidenceBound": _category_ok(failures, ("evidence_root", "source_")),
        "surveyControlNetworkBound": _category_ok(failures, ("survey_control", "survey_controls")),
        "alignmentContinuous": _category_ok(failures, ("alignment_",)),
        "profileStationsMonotonic": _category_ok(failures, ("profile_",)),
        "drainageGravityMonotonic": _category_ok(failures, ("drainage_",)),
        "utilityAndGeotechnicalSourcesBound": _category_ok(failures, ("discipline_",)),
        "reviewOnlyLockClosed": _category_ok(failures, ("safety_locks",)),
    }
    eligible = not failures
    return {
        "schema": REPORT_SCHEMA_ID,
        "candidateId": candidate_id,
        "status": OUTPUT_CLASS if eligible else "blocked",
        "outputClass": OUTPUT_CLASS,
        "authorizedOutput": OUTPUT_CLASS if eligible else None,
        "reviewCandidateEligible": eligible,
        "failures": failures,
        "checks": checks,
        "counts": {
            "failures": len(failures),
            "sources": len(sources_raw),
            "surveyControls": len(controls_raw),
            "alignmentSegments": len(segments_raw),
            "profilePoints": len(profile_points_raw),
            "drainagePoints": len(drainage_points_raw),
        },
        "coordinateMappingBoundary": {
            "drawingUnit": "mm",
            "groundUnit": "m",
            "millimetresPerGroundMetre": 1000,
            "mappingRule": MAPPING_RULE,
            "originHorizontalControlToleranceM": 0.02,
            "originVerticalControlToleranceM": 0.03,
        },
        "releaseBoundary": dict(RELEASE_BOUNDARY),
        "externalWorkRequired": dict(EXTERNAL_WORK_REQUIRED),
        "conclusion": (
            "civil_review_candidate_only"
            if eligible
            else "civil_review_candidate_blocked"
        ),
    }


__all__ = [
    "EXPECTED_LOCKS",
    "EXTERNAL_WORK_REQUIRED",
    "MAPPING_RULE",
    "OUTPUT_CLASS",
    "RELEASE_BOUNDARY",
    "REPORT_SCHEMA_ID",
    "SCHEMA_ID",
    "validate_civil_review_candidate",
]
