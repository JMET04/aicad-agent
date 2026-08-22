from __future__ import annotations

import re
from typing import Any

from .manufacturing_release import _Context, _exact_keys, _json_from_row, _list


_MOLDING_INPUT_KEYS = {
    "shrinkage",
    "draft",
    "partingLine",
    "gate",
    "ejection",
    "surfaceFinish",
    "tolerance",
}
_PLACEHOLDER = re.compile(
    r"(?i)\b(?:todo|tbd|unresolved|placeholder|dummy|example|unknown)\b"
)


def validate_molding_input(
    ctx: _Context,
    row: dict[str, Any],
    location: str,
    *,
    assembly_id: str,
    revision: str,
    units: str,
    coordinate_system_id: str,
    molded_part_ids: set[str],
) -> None:
    document = _json_from_row(ctx, row, location)
    _exact_keys(
        ctx,
        document,
        {
            "schema", "assemblyId", "revision", "units", "coordinateSystemId",
            "moldedPartIds", "toolingInputs",
        },
        location + ".document",
    )
    if (
        document.get("schema") != "aicad_molding_input_v1"
        or document.get("assemblyId") != assembly_id
        or document.get("revision") != revision
        or document.get("units") != units
        or document.get("coordinateSystemId") != coordinate_system_id
    ):
        ctx.fail(
            "molding_input_identity_mismatch",
            location,
            "Molding input schema/assembly/revision/unit/coordinate identity does not match.",
            "Regenerate the tooling input from the released assembly and frozen mold coordinate basis.",
        )
    declared_parts = document.get("moldedPartIds")
    if (
        not isinstance(declared_parts, list)
        or any(not isinstance(value, str) or not value for value in declared_parts)
        or len(declared_parts) != len(set(declared_parts))
        or set(declared_parts) != molded_part_ids
    ):
        ctx.fail(
            "molding_part_closure_mismatch",
            location + ".moldedPartIds",
            "Molded-part inventory does not exactly equal injection-molded parts in this assembly BOM.",
            "Regenerate the mold subject list from the exact BOM; do not omit or add parts.",
        )
    inputs = _list(ctx, document.get("toolingInputs"), location + ".toolingInputs")
    by_key: dict[str, str] = {}
    for index, raw in enumerate(inputs):
        item_location = f"{location}.toolingInputs[{index}]"
        item = _exact_keys(ctx, raw, {"key", "value", "source"}, item_location)
        key = item.get("key")
        value = item.get("value")
        source = item.get("source")
        if key not in _MOLDING_INPUT_KEYS:
            ctx.fail(
                "molding_input_key_invalid",
                item_location + ".key",
                f"Unknown or duplicated mold input key {key!r}.",
                "Provide exactly shrinkage, draft, partingLine, gate, ejection, surfaceFinish and tolerance.",
            )
        elif key in by_key:
            ctx.fail(
                "molding_input_key_duplicate",
                item_location + ".key",
                f"Mold input {key!r} is duplicated.",
                "Keep one controlled value per mandatory mold input.",
            )
        if (
            not isinstance(value, str)
            or len(value.strip()) < 2
            or _PLACEHOLDER.search(value)
            or not isinstance(source, str)
            or len(source.strip()) < 3
            or _PLACEHOLDER.search(source)
        ):
            ctx.fail(
                "molding_input_placeholder_or_source_missing",
                item_location,
                "Mold input value/source is missing or placeholder text.",
                "Bind a real value and its engineering/supplier DFM source for this exact revision.",
            )
        if isinstance(key, str):
            by_key[key] = str(value)
    missing = sorted(_MOLDING_INPUT_KEYS - set(by_key))
    extra = sorted(set(by_key) - _MOLDING_INPUT_KEYS)
    if missing or extra:
        ctx.fail(
            "molding_input_exact_inventory_mismatch",
            location + ".toolingInputs",
            f"Mold input inventory mismatch; missing={missing}, extra={extra}.",
            "Complete the canonical seven mold-opening inputs before RFQ/DFM handoff.",
        )
