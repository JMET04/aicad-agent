from __future__ import annotations

import re
from typing import Any

from .manufacturing_release import (
    _Context,
    _evidence,
    _exact_keys,
    _identifier,
    _json_from_row,
)


RFQ_RECIPIENT_ID = "unassigned_rfq_recipient"
RFQ_RECIPIENT_SCHEMA = "aicad_rfq_recipient_profile_v1"
RFQ_RECIPIENT_STATUS = "rfq_recipient_unassigned"

_PLACEHOLDER = re.compile(
    r"(?i)\b(?:todo|tbd|unresolved|placeholder|dummy|example|unknown|synthetic|self[- ]?reported)\b"
)


def neutral_rfq_recipient(
    ctx: _Context,
    raw: Any,
    location: str,
    units: str,
    coordinate_ids: set[str],
) -> tuple[str, dict[str, Any]] | None:
    """Return a project-authored RFQ recipient profile, never supplier authority.

    This profile can describe a neutral mechanical RFQ target. It intentionally
    cannot contain supplier confirmations or supplier-owned authority evidence.
    """
    if not isinstance(raw, dict) or "recipientProfile" not in raw:
        return None
    item = _exact_keys(ctx, raw, {"supplierId", "recipientProfile"}, location)
    supplier_id = _identifier(ctx, item.get("supplierId"), location + ".supplierId")
    row = _evidence(
        ctx,
        item.get("recipientProfile"),
        location + ".recipientProfile",
        "json",
    )
    document = _json_from_row(ctx, row, location + ".recipientProfile")
    _exact_keys(
        ctx,
        document,
        {
            "schema",
            "recipientId",
            "status",
            "revision",
            "units",
            "coordinateSystemIds",
            "processRequirements",
            "nativeFormats",
            "authorship",
            "supplierAuthorityClaimed",
        },
        location + ".recipientProfile.document",
    )
    if supplier_id != RFQ_RECIPIENT_ID or document.get("recipientId") != RFQ_RECIPIENT_ID:
        ctx.fail(
            "neutral_rfq_recipient_identity_invalid",
            location,
            "Neutral RFQ recipient must use the controlled unassigned recipient identity.",
            f"Use supplierId/recipientId={RFQ_RECIPIENT_ID!r} or bind a real supplier authority record.",
        )
    expected = {
        "schema": RFQ_RECIPIENT_SCHEMA,
        "status": RFQ_RECIPIENT_STATUS,
        "authorship": "project_rfq_requirements",
        "supplierAuthorityClaimed": False,
    }
    for key, value in expected.items():
        if document.get(key) != value:
            ctx.fail(
                "neutral_rfq_recipient_contract_invalid",
                location + f".recipientProfile.{key}",
                f"Neutral RFQ recipient {key} must equal {value!r}.",
                "Keep this project-authored recipient profile explicitly unassigned and free of supplier authority claims.",
            )
    _identifier(ctx, document.get("revision"), location + ".recipientProfile.revision", revision=True)
    if document.get("units") != [units]:
        ctx.fail(
            "neutral_rfq_units_invalid",
            location + ".recipientProfile.units",
            "Neutral RFQ recipient does not freeze the exact package unit.",
            "Declare exactly the release-basis unit in the project RFQ requirements.",
        )
    coordinates = document.get("coordinateSystemIds")
    if (
        not isinstance(coordinates, list)
        or not coordinates
        or any(not isinstance(value, str) for value in coordinates)
        or len(coordinates) != len(set(coordinates))
        or not set(coordinates).issubset(coordinate_ids)
    ):
        ctx.fail(
            "neutral_rfq_coordinate_inventory_invalid",
            location + ".recipientProfile.coordinateSystemIds",
            "Neutral RFQ coordinate inventory is empty, duplicated or references an unknown datum.",
            "List the exact controlled package coordinate-system identifiers.",
        )
    for key in ("processRequirements", "nativeFormats"):
        values = document.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() or _PLACEHOLDER.search(value) for value in values)
            or len(values) != len(set(values))
        ):
            ctx.fail(
                "neutral_rfq_inventory_invalid",
                location + f".recipientProfile.{key}",
                f"Neutral RFQ {key} must be a non-empty, duplicate-free, non-placeholder inventory.",
                "State the actual process and exchange-format requirements without naming or impersonating a supplier.",
            )
    profile = {
        **document,
        "supplierId": supplier_id,
        "capabilities": document.get("processRequirements", []),
        "_recipientStatus": RFQ_RECIPIENT_STATUS,
    }
    return supplier_id, profile
