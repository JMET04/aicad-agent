from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Iterable

from .manufacturing_release import (
    NATIVE_LOG_SCHEMA,
    SUPPLIER_CONFIRMATION_SCHEMA,
    SUPPLIER_SCHEMA,
    _Context,
    _evidence,
    _exact_keys,
    _identifier,
    _json_from_row,
    _list,
)
from .manufacturing_recipients import neutral_rfq_recipient


def finite_vector(ctx: _Context, value: Any, location: str) -> list[float] | None:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
        or any(not math.isfinite(float(item)) for item in value)
    ):
        ctx.fail(
            "coordinate_vector_invalid",
            location,
            "Coordinate vector must contain exactly three finite numbers.",
            "Declare the frozen origin and unit basis vectors numerically.",
        )
        return None
    return [float(item) for item in value]


def coordinate_systems(
    ctx: _Context, release_basis: dict[str, Any], units: str
) -> dict[str, dict[str, Any]]:
    systems: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(
        _list(ctx, release_basis.get("coordinateSystems"), "releaseBasis.coordinateSystems")
    ):
        location = f"releaseBasis.coordinateSystems[{index}]"
        item = _exact_keys(
            ctx,
            raw,
            {"id", "units", "handedness", "origin", "xAxis", "yAxis", "zAxis", "description"},
            location,
        )
        identifier = _identifier(ctx, item.get("id"), location + ".id")
        if identifier in systems:
            ctx.fail(
                "coordinate_system_duplicate",
                location + ".id",
                f"Coordinate system {identifier!r} is duplicated.",
                "Give each frozen coordinate system one unique identifier.",
            )
        if item.get("units") != units:
            ctx.fail(
                "coordinate_units_mismatch",
                location + ".units",
                "Coordinate-system units do not match the package release basis.",
                "Convert the geometry or declare the one exact package unit consistently.",
            )
        if item.get("handedness") != "right":
            ctx.fail(
                "coordinate_handedness_invalid",
                location + ".handedness",
                "Factory handoff requires an explicit right-handed basis.",
                "Transform and document the package in a right-handed manufacturing coordinate system.",
            )
        description = item.get("description")
        if not isinstance(description, str) or len(description.strip()) < 8:
            ctx.fail(
                "coordinate_description_missing",
                location + ".description",
                "Coordinate origin/use description is too short.",
                "State the physical datum/origin and how the factory must interpret the axes.",
            )
        origin = finite_vector(ctx, item.get("origin"), location + ".origin")
        x_axis = finite_vector(ctx, item.get("xAxis"), location + ".xAxis")
        y_axis = finite_vector(ctx, item.get("yAxis"), location + ".yAxis")
        z_axis = finite_vector(ctx, item.get("zAxis"), location + ".zAxis")
        if origin is not None and x_axis is not None and y_axis is not None and z_axis is not None:
            norm = lambda vector: math.sqrt(sum(component * component for component in vector))
            dot = lambda left, right: sum(a * b for a, b in zip(left, right))
            cross_xy = [
                x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1],
                x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
                x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0],
            ]
            orthonormal = (
                all(abs(norm(axis) - 1.0) <= 1e-6 for axis in (x_axis, y_axis, z_axis))
                and all(
                    abs(value) <= 1e-6
                    for value in (dot(x_axis, y_axis), dot(x_axis, z_axis), dot(y_axis, z_axis))
                )
                and all(abs(a - b) <= 1e-6 for a, b in zip(cross_xy, z_axis))
            )
            if not orthonormal:
                ctx.fail(
                    "coordinate_basis_invalid",
                    location,
                    "Axes are not an orthonormal right-handed basis.",
                    "Correct the unit axes so X×Y=Z and all axes are mutually perpendicular.",
                )
        systems[identifier] = item
    return systems


_PLACEHOLDER = re.compile(
    r"(?i)\b(?:todo|tbd|unresolved|placeholder|dummy|example|unknown|synthetic|self[- ]?reported)\b"
)


def _real_authority_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value.strip()) >= 8
        and _PLACEHOLDER.search(value) is None
        and (
            value.startswith("https://")
            or value.startswith("supplier-signed:")
            or value.startswith("supplier-portal:")
        )
    )


def supplier_release_records(
    ctx: _Context,
    handoff_ctx: _Context,
    release_basis: dict[str, Any],
    units: str,
    coordinate_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate public/qualified capability authority separately from per-package confirmation."""
    profiles: dict[str, dict[str, Any]] = {}
    confirmations: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_list(ctx, release_basis.get("suppliers"), "releaseBasis.suppliers")):
        location = f"releaseBasis.suppliers[{index}]"
        neutral = neutral_rfq_recipient(ctx, raw, location, units, coordinate_ids)
        if neutral is not None:
            supplier_id, profile = neutral
            if supplier_id in profiles:
                ctx.fail(
                    "supplier_duplicate",
                    location + ".supplierId",
                    f"RFQ recipient {supplier_id!r} is duplicated.",
                    "Keep one controlled unassigned RFQ recipient profile.",
                )
            profiles[supplier_id] = profile
            continue
        item = _exact_keys(
            ctx,
            raw,
            {"supplierId", "capabilityEvidence", "authorityEvidence"},
            location,
            optional={"packageConfirmationEvidence", "confirmationAuthorityEvidence"},
        )
        supplier_id = _identifier(ctx, item.get("supplierId"), location + ".supplierId")
        if supplier_id in profiles:
            ctx.fail(
                "supplier_duplicate", location + ".supplierId",
                f"Supplier {supplier_id!r} is duplicated.",
                "Keep one hash-bound authority/profile record per supplier identifier.",
            )
        authority_row = _evidence(
            ctx, item.get("authorityEvidence"), location + ".authorityEvidence", "authority_document"
        )
        profile_row = _evidence(
            ctx, item.get("capabilityEvidence"), location + ".capabilityEvidence", "json"
        )
        profile = _json_from_row(ctx, profile_row, location + ".capabilityEvidence")
        _exact_keys(
            ctx,
            profile,
            {
                "schema", "supplierId", "status", "revision", "units",
                "coordinateSystemIds", "capabilities", "nativeFormats",
                "sourceAuthority", "documentId", "issuedBy", "issuedAt", "validUntil",
                "authoritySha256",
            },
            location + ".capabilityEvidence.document",
        )
        if profile.get("schema") != SUPPLIER_SCHEMA or profile.get("supplierId") != supplier_id:
            ctx.fail(
                "supplier_profile_identity_mismatch", location,
                "Supplier capability schema/identity differs from the declared supplier.",
                f"Export a {SUPPLIER_SCHEMA} profile for the exact supplierId.",
            )
        if profile.get("status") not in {
            "public_capability_record", "qualified_capability_record",
            "confirmed_for_factory_handoff_candidate",
        }:
            ctx.fail(
                "supplier_capability_status_invalid", location + ".capabilityEvidence.status",
                "Capability status is not a controlled public/qualified record state.",
                "Use a truthful public_capability_record or qualified_capability_record; package confirmation is a separate gate.",
            )
        if profile.get("units") != [units]:
            ctx.fail(
                "supplier_units_unsupported", location + ".capabilityEvidence.units",
                "Supplier capability profile does not support the exact package unit.",
                "Bind an authority-backed profile for the package unit or convert the whole package.",
            )
        profile_coordinates = profile.get("coordinateSystemIds")
        if (
            not isinstance(profile_coordinates, list)
            or not profile_coordinates
            or any(not isinstance(value, str) for value in profile_coordinates)
            or len(profile_coordinates) != len(set(profile_coordinates))
            or not set(profile_coordinates).issubset(coordinate_ids)
        ):
            ctx.fail(
                "supplier_coordinate_support_invalid", location + ".capabilityEvidence.coordinateSystemIds",
                "Supplier profile coordinate inventory is empty, duplicated or references unknown systems.",
                "Record the reviewed package datum identifiers without inventing an external acceptance.",
            )
        for key in ("capabilities", "nativeFormats"):
            values = profile.get(key)
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value.strip() or _PLACEHOLDER.search(value) for value in values)
                or len(values) != len(set(values))
            ):
                ctx.fail(
                    "supplier_inventory_invalid", location + f".capabilityEvidence.{key}",
                    f"Supplier {key} must be a non-empty, authority-backed, duplicate-free inventory.",
                    "Extract the exact supported processes/formats from the controlled supplier authority document.",
                )
        authority_sha = authority_row.get("actualSha256")
        if not authority_row.get("pass") or profile.get("authoritySha256") != authority_sha:
            ctx.fail(
                "supplier_authority_hash_mismatch", location,
                "Capability profile does not bind the exact controlled supplier authority bytes.",
                "Snapshot the real supplier source and bind its current SHA-256 in authoritySha256.",
            )
        for key in ("sourceAuthority", "documentId", "issuedBy", "revision"):
            value = profile.get(key)
            valid = _real_authority_text(value) if key == "sourceAuthority" else (
                isinstance(value, str) and len(value.strip()) >= 3 and _PLACEHOLDER.search(value) is None
            )
            if not valid or (key == "issuedBy" and re.search(r"(?i)\b(?:aicad|project team|internal)\b", value)):
                ctx.fail(
                    "supplier_authority_or_attestation_invalid", location + f".capabilityEvidence.{key}",
                    f"Supplier evidence field {key} is missing, self-authored, or placeholder text.",
                    "Bind an attributable supplier-owned URL/document identifier, issuer and revision.",
                )
        try:
            issued = date.fromisoformat(str(profile.get("issuedAt")))
            valid_until = date.fromisoformat(str(profile.get("validUntil")))
            dates_valid = issued <= date.today() <= valid_until
        except ValueError:
            dates_valid = False
        if not dates_valid:
            ctx.fail(
                "supplier_capability_date_invalid", location + ".capabilityEvidence",
                "Supplier capability issue/validity dates are invalid, future-issued or expired.",
                "Refresh the controlled supplier authority record and its profile.",
            )
        profiles[supplier_id] = profile

        receipt_ref = item.get("packageConfirmationEvidence")
        confirmation_authority_ref = item.get("confirmationAuthorityEvidence")
        if receipt_ref is not None or confirmation_authority_ref is not None:
            receipt_row = _evidence(
                handoff_ctx, receipt_ref,
                location + ".packageConfirmationEvidence", "json",
            )
            confirmation_authority_row = _evidence(
                handoff_ctx, confirmation_authority_ref,
                location + ".confirmationAuthorityEvidence", "authority_document",
            )
            confirmations[supplier_id] = {
                "location": location,
                "receiptRow": receipt_row,
                "authorityRow": confirmation_authority_row,
            }
    return profiles, confirmations


def validate_supplier_confirmations(
    ctx: _Context,
    confirmations: dict[str, dict[str, Any]],
    used_supplier_ids: set[str],
    *,
    package_id: str,
    revision: str,
    expected_sha256_by_location: dict[str, str],
) -> None:
    for supplier_id in sorted(used_supplier_ids):
        record = confirmations.get(supplier_id)
        if record is None:
            ctx.fail(
                "supplier_package_confirmation_missing", f"suppliers.{supplier_id}",
                "No real supplier confirmation is bound to this exact package/revision.",
                "Obtain a supplier portal/signed confirmation for this package; do not convert a public capability page into acceptance.",
            )
            continue
        location = str(record["location"])
        receipt_row = record["receiptRow"]
        authority_row = record["authorityRow"]
        document = _json_from_row(ctx, receipt_row, location + ".packageConfirmationEvidence")
        _exact_keys(
            ctx,
            document,
            {
                "schema", "supplierId", "packageId", "releaseRevision", "status",
                "sourceAuthority", "documentId", "issuedBy", "issuedAt", "validUntil",
                "authoritySha256", "acknowledgedArtifactSha256ByLocation",
            },
            location + ".packageConfirmationEvidence.document",
        )
        expected = {
            "schema": SUPPLIER_CONFIRMATION_SCHEMA,
            "supplierId": supplier_id,
            "packageId": package_id,
            "releaseRevision": revision,
            "status": "confirmed_for_factory_handoff",
        }
        for key, value in expected.items():
            if document.get(key) != value:
                ctx.fail(
                    "supplier_confirmation_identity_invalid", location + f".packageConfirmationEvidence.{key}",
                    f"Per-package supplier confirmation {key} does not equal {value!r}.",
                    "Obtain a new supplier-owned confirmation for the exact frozen package and revision.",
                )
        if document.get("acknowledgedArtifactSha256ByLocation") != expected_sha256_by_location:
            ctx.fail(
                "supplier_confirmation_artifact_closure_mismatch", location,
                "Supplier confirmation does not acknowledge the exact current artifact hash map.",
                "Submit the frozen package again and bind the supplier response to every current artifact hash.",
            )
        if (
            not authority_row.get("pass")
            or document.get("authoritySha256") != authority_row.get("actualSha256")
        ):
            ctx.fail(
                "supplier_confirmation_authority_hash_mismatch", location,
                "Confirmation receipt does not bind the exact supplier-owned portal/signed source.",
                "Export the real supplier response and bind its SHA-256.",
            )
        if not _real_authority_text(document.get("sourceAuthority")):
            ctx.fail(
                "supplier_confirmation_source_invalid", location + ".packageConfirmationEvidence.sourceAuthority",
                "Supplier confirmation source is missing, non-authoritative or placeholder text.",
                "Use the supplier portal URL or signed-document locator.",
            )
        issued_by = document.get("issuedBy")
        if (
            not isinstance(issued_by, str)
            or len(issued_by.strip()) < 3
            or _PLACEHOLDER.search(issued_by)
            or re.search(r"(?i)\b(?:aicad|project team|internal)\b", issued_by)
        ):
            ctx.fail(
                "supplier_confirmation_issuer_invalid", location + ".packageConfirmationEvidence.issuedBy",
                "Per-package confirmation is not attributable to the supplier.",
                "Bind a supplier-issued portal receipt or signed document.",
            )
        try:
            issued = date.fromisoformat(str(document.get("issuedAt")))
            valid_until = date.fromisoformat(str(document.get("validUntil")))
            dates_valid = issued <= date.today() <= valid_until
        except ValueError:
            dates_valid = False
        if not dates_valid:
            ctx.fail(
                "supplier_confirmation_date_invalid", location + ".packageConfirmationEvidence",
                "Per-package supplier confirmation is future-issued, expired or has invalid dates.",
                "Obtain a current supplier confirmation for this frozen release.",
            )


def require_subject_basis(
    ctx: _Context,
    subject: dict[str, Any],
    location: str,
    coordinate_systems: dict[str, dict[str, Any]],
    suppliers: dict[str, dict[str, Any]],
    supplier_fields: Iterable[str],
    required_capabilities: Iterable[str],
) -> None:
    coordinate_id = subject.get("coordinateSystemId")
    if coordinate_id not in coordinate_systems:
        ctx.fail(
            "subject_coordinate_unknown",
            location + ".coordinateSystemId",
            "Subject references an unknown coordinate system.",
            "Bind the subject to one frozen release-basis coordinate system.",
        )
    for supplier_field in supplier_fields:
        supplier_id = subject.get(supplier_field)
        if isinstance(supplier_id, str) and supplier_id:
            ctx.used_supplier_ids.add(supplier_id)
        profile = suppliers.get(supplier_id)
        if profile is None:
            ctx.fail(
                "subject_supplier_unknown",
                location + f".{supplier_field}",
                "Subject references an unknown supplier capability profile.",
                "Add a current hash-bound supplier profile or correct the supplierId.",
            )
            continue
        capabilities = profile.get("capabilities")
        missing = sorted(set(required_capabilities) - set(capabilities if isinstance(capabilities, list) else []))
        if missing:
            ctx.fail(
                "supplier_capability_missing",
                location + f".{supplier_field}",
                "Supplier lacks required capabilities: " + ", ".join(missing),
                "Qualify a capable supplier or obtain updated capability evidence covering every process.",
            )
        supported_coordinates = profile.get("coordinateSystemIds")
        if not isinstance(supported_coordinates, list) or coordinate_id not in supported_coordinates:
            ctx.fail(
                "supplier_coordinate_mismatch",
                location + f".{supplier_field}",
                "Supplier does not confirm the subject coordinate system.",
                "Align the supplier capability record and the released subject datum definition.",
            )


def hash_map(rows: dict[str, dict[str, Any]], roles: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for role in roles:
        row = rows.get(role, {})
        if row.get("pass") and isinstance(row.get("actualSha256"), str):
            result[role] = row["actualSha256"]
    return result


def validate_native_log(
    ctx: _Context,
    row: dict[str, Any],
    location: str,
    *,
    gate: str,
    subject_id: str,
    revision: str,
    inputs: dict[str, str],
    outputs: dict[str, str],
) -> None:
    document = _json_from_row(ctx, row, location)
    _exact_keys(
        ctx,
        document,
        {
            "schema", "gate", "status", "nativeTool", "subjectId", "revision",
            "inputSha256ByRole", "outputSha256ByRole", "checks",
        },
        location + ".document",
    )
    valid = True
    expected_scalars = {
        "schema": NATIVE_LOG_SCHEMA,
        "gate": gate,
        "status": "pass",
        "subjectId": subject_id,
        "revision": revision,
    }
    for key, expected in expected_scalars.items():
        if document.get(key) != expected:
            valid = False
            ctx.fail(
                "native_log_identity_or_status_invalid",
                location + f".{key}",
                f"Native log {key} does not equal {expected!r}.",
                "Rerun the exact native-host gate for this subject/revision and export its passing JSON log.",
            )
    native_tool = _exact_keys(
        ctx, document.get("nativeTool"), {"name", "version", "nativeExecution"},
        location + ".nativeTool",
    )
    if (
        native_tool.get("nativeExecution") is not True
        or not isinstance(native_tool.get("name"), str)
        or not native_tool.get("name", "").strip()
        or not isinstance(native_tool.get("version"), str)
        or not native_tool.get("version", "").strip()
        or _PLACEHOLDER.search(str(native_tool.get("name", ""))) is not None
        or _PLACEHOLDER.search(str(native_tool.get("version", ""))) is not None
        or re.search(r"\d", str(native_tool.get("version", ""))) is None
    ):
        valid = False
        ctx.fail(
            "native_tool_execution_unproven",
            location + ".nativeTool",
            "Native tool name/version/execution proof is missing.",
            "Run the authoritative CAD/EDA host; synthetic or unavailable-host logs cannot pass.",
        )
    for key, expected in (("inputSha256ByRole", inputs), ("outputSha256ByRole", outputs)):
        if document.get(key) != expected:
            valid = False
            ctx.fail(
                "native_log_artifact_binding_mismatch",
                location + f".{key}",
                "Native log does not bind the exact current input/output hash map.",
                "Rerun the native operation after final artifacts are frozen and export an exact hash map with no missing or extra roles.",
            )
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        valid = False
        ctx.fail(
            "native_log_checks_missing",
            location + ".checks",
            "Native log has no executed checks.",
            "Run the native gate and export its complete non-empty check inventory.",
        )
    else:
        check_ids: list[str] = []
        for index, check in enumerate(checks):
            check_location = f"{location}.checks[{index}]"
            item = _exact_keys(ctx, check, {"id", "status", "detail"}, check_location)
            if (
                not isinstance(item.get("id"), str)
                or not item.get("id", "").strip()
                or item.get("status") != "pass"
                or not isinstance(item.get("detail"), str)
                or not item.get("detail", "").strip()
                or _PLACEHOLDER.search(str(item.get("detail", ""))) is not None
            ):
                valid = False
                ctx.fail(
                    "native_log_check_failed",
                    check_location,
                    "Every native-host check must be named, passing and explained.",
                    "Resolve the host-reported failure and rerun the native gate.",
                )
            check_ids.append(str(item.get("id", "")))
        if len(check_ids) != len(set(check_ids)):
            valid = False
            ctx.fail(
                "native_log_check_duplicate",
                location + ".checks",
                "Native log check identifiers are duplicated.",
                "Export one distinct result row per native-host check.",
            )
    ctx.check(
        f"native-log:{gate}:{subject_id}:{revision}",
        bool(valid and row.get("pass")),
        {"path": row.get("path"), "inputRoles": sorted(inputs), "outputRoles": sorted(outputs)},
    )
