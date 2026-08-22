from __future__ import annotations

import collections
import math
import re
from pathlib import Path
from typing import Any

from .manufacturing_basis import (
    coordinate_systems,
    hash_map,
    require_subject_basis,
    supplier_release_records,
    validate_native_log,
    validate_supplier_confirmations,
)
from .manufacturing_documents import validate_molding_input
from .manufacturing_release import (
    PACKAGE_SCHEMA,
    VALIDATION_SCHEMA,
    _ASSEMBLY_ROLES,
    _Context,
    _PART_ROLES,
    _PCB_LAYER,
    _PCB_ROLES,
    _canonical_sha256,
    _evidence,
    _exact_keys,
    _identifier,
    _json_from_row,
    _list,
    _preview_evidence,
)
from .manufacturing_recipients import RFQ_RECIPIENT_STATUS


def _record_review_subject(
    ctx: _Context,
    *,
    subject_type: str,
    subject_id: str,
    revision: str,
    rows: dict[str, dict[str, Any]],
    previews: dict[str, tuple[str, str]],
) -> None:
    preview_rows: list[dict[str, Any]] = []
    for preview_role, (view, target_role) in previews.items():
        preview = rows.get(preview_role, {})
        target = rows.get(target_role, {})
        binding_pass = (
            preview.get("subjectId") == subject_id
            and preview.get("previewOfRole") == target_role
            and isinstance(target.get("actualSha256"), str)
            and preview.get("sourceSha256") == target.get("actualSha256")
        )
        preview["sourceBindingPass"] = binding_pass
        if not binding_pass:
            preview["pass"] = False
            ctx.fail(
                "preview_source_binding_mismatch",
                f"{subject_type}.{subject_id}.{preview_role}",
                "Actual preview subject/source role/SHA-256 does not match its hash-bound target artifact.",
                "Regenerate the subject preview from the exact current drawing, STEP or KiCad source and bind its source hash.",
            )
        preview_rows.append(
            {
                "role": preview_role,
                "view": view,
                "path": preview.get("path"),
                "resolvedPath": preview.get("resolvedPath"),
                "sha256": preview.get("actualSha256"),
                "pass": preview.get("pass") is True,
                "sourceBindingPass": binding_pass,
                "targetRole": target_role,
                "targetPath": target.get("path"),
                "targetResolvedPath": target.get("resolvedPath"),
                "targetSha256": target.get("actualSha256"),
                "targetPass": target.get("pass") is True,
            }
        )
    links = [
        {
            "role": role,
            "kind": row.get("kind"),
            "path": row.get("path"),
            "resolvedPath": row.get("resolvedPath"),
            "sha256": row.get("actualSha256"),
            "pass": row.get("pass") is True,
        }
        for role, row in sorted(rows.items())
    ]
    ctx.review_subjects.append(
        {
            "subjectKey": f"{subject_type}:{subject_id}:{revision}",
            "subjectType": subject_type,
            "subjectId": subject_id,
            "revision": revision,
            "previews": preview_rows,
            "links": links,
        }
    )


def _artifact_roles(
    ctx: _Context,
    value: Any,
    roles: dict[str, str],
    location: str,
) -> dict[str, dict[str, Any]]:
    artifacts = _exact_keys(ctx, value, set(roles), location)
    return {
        role: (
            _preview_evidence(ctx, artifacts.get(role), f"{location}.{role}")
            if kind == "preview"
            else _evidence(ctx, artifacts.get(role), f"{location}.{role}", kind)
        )
        for role, kind in roles.items()
    }


def _require_supplier_formats(
    ctx: _Context,
    supplier: dict[str, Any] | None,
    rows: dict[str, dict[str, Any]],
    roles: list[str],
    location: str,
) -> None:
    if supplier is None:
        return
    declared = supplier.get("nativeFormats")
    supported = {str(value).casefold() for value in declared} if isinstance(declared, list) else set()
    required = {
        Path(str(rows[role].get("path", ""))).suffix.casefold()
        for role in roles
        if role in rows and rows[role].get("path")
    }
    missing = sorted(required - supported)
    if missing:
        ctx.fail(
            "supplier_native_format_missing",
            location,
            "Supplier does not confirm required native/exchange formats: " + ", ".join(missing),
            "Obtain supplier format confirmation or export the complete package in qualified formats.",
        )


def _validate_assembly_documents(
    ctx: _Context,
    assembly_id: str,
    revision: str,
    units: str,
    coordinate_id: str,
    rows: dict[str, dict[str, Any]],
    location: str,
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    bom = _json_from_row(ctx, rows["bom"], location + ".artifacts.bom")
    _exact_keys(
        ctx,
        bom,
        {"schema", "assemblyId", "revision", "units", "coordinateSystemId", "rows"},
        location + ".artifacts.bom.document",
    )
    if (
        bom.get("schema") != "aicad_manufacturing_bom_v1"
        or bom.get("assemblyId") != assembly_id
        or bom.get("revision") != revision
        or bom.get("units") != units
        or bom.get("coordinateSystemId") != coordinate_id
    ):
        ctx.fail(
            "assembly_bom_identity_mismatch",
            location + ".artifacts.bom",
            "BOM schema/assembly/revision/unit/coordinate identity does not match the assembly.",
            "Regenerate the exact machine-readable BOM from the released native assembly.",
        )
    bom_counts: dict[tuple[str, str], int] = {}
    for index, raw in enumerate(_list(ctx, bom.get("rows"), location + ".artifacts.bom.rows")):
        row_location = f"{location}.artifacts.bom.rows[{index}]"
        item = _exact_keys(ctx, raw, {"partId", "revision", "quantity"}, row_location)
        part_id = _identifier(ctx, item.get("partId"), row_location + ".partId")
        part_revision = _identifier(
            ctx, item.get("revision"), row_location + ".revision", revision=True
        )
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            ctx.fail(
                "bom_quantity_invalid",
                row_location + ".quantity",
                "BOM quantity must be a positive integer.",
                "Correct the released assembly BOM and regenerate it from the native assembly.",
            )
            quantity = 0
        key = (part_id, part_revision)
        if key in bom_counts:
            ctx.fail(
                "bom_subject_duplicate",
                row_location,
                f"BOM subject {part_id}/{part_revision} is duplicated.",
                "Consolidate identical subject rows into one exact positive quantity.",
            )
        bom_counts[key] = quantity

    positions = _json_from_row(ctx, rows["positions"], location + ".artifacts.positions")
    _exact_keys(
        ctx,
        positions,
        {"schema", "assemblyId", "revision", "units", "coordinateSystemId", "instances"},
        location + ".artifacts.positions.document",
    )
    if (
        positions.get("schema") != "aicad_assembly_positions_v1"
        or positions.get("assemblyId") != assembly_id
        or positions.get("revision") != revision
        or positions.get("units") != units
        or positions.get("coordinateSystemId") != coordinate_id
    ):
        ctx.fail(
            "assembly_positions_identity_mismatch",
            location + ".artifacts.positions",
            "Position schema/assembly/revision/unit/coordinate identity does not match the assembly.",
            "Export exact component placements from the released native assembly.",
        )
    position_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    instance_ids: set[str] = set()
    for index, raw in enumerate(
        _list(ctx, positions.get("instances"), location + ".artifacts.positions.instances")
    ):
        row_location = f"{location}.artifacts.positions.instances[{index}]"
        item = _exact_keys(
            ctx, raw, {"instanceId", "partId", "revision", "transform"}, row_location
        )
        instance_id = _identifier(ctx, item.get("instanceId"), row_location + ".instanceId")
        part_id = _identifier(ctx, item.get("partId"), row_location + ".partId")
        part_revision = _identifier(
            ctx, item.get("revision"), row_location + ".revision", revision=True
        )
        transform = item.get("transform")
        if (
            not isinstance(transform, list)
            or len(transform) != 16
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in transform)
            or any(not math.isfinite(float(value)) for value in transform)
        ):
            ctx.fail(
                "assembly_transform_invalid",
                row_location + ".transform",
                "Assembly placement must be one finite 4×4 transform (16 row-major values).",
                "Re-export instance placements from the native assembly coordinate system.",
            )
        if instance_id in instance_ids:
            ctx.fail(
                "assembly_instance_duplicate",
                row_location + ".instanceId",
                f"Assembly instance {instance_id!r} is duplicated.",
                "Give every physical occurrence one unique stable instanceId.",
            )
        instance_ids.add(instance_id)
        position_counts[(part_id, part_revision)] += 1
    if dict(position_counts) != bom_counts:
        ctx.fail(
            "assembly_bom_position_closure_mismatch",
            location,
            "BOM quantities and positioned instance counts are not identical.",
            "Reconcile native assembly occurrences, BOM rows and position export before handoff.",
        )
    return bom_counts, dict(position_counts)


def _mechanical(
    ctx: _Context,
    value: Any,
    units: str,
    coordinates: dict[str, dict[str, Any]],
    suppliers: dict[str, dict[str, Any]],
) -> tuple[int, set[tuple[str, str]]]:
    mechanical = _exact_keys(ctx, value, {"parts", "assemblies"}, "mechanical")
    declared_parts: set[tuple[str, str]] = set()
    molded_parts: set[tuple[str, str]] = set()
    covered_parts: set[tuple[str, str]] = set()
    subject_count = 0
    for index, raw in enumerate(_list(ctx, mechanical.get("parts"), "mechanical.parts")):
        location = f"mechanical.parts[{index}]"
        part = _exact_keys(
            ctx,
            raw,
            {"partId", "revision", "coordinateSystemId", "supplierId", "process", "artifacts"},
            location,
        )
        part_id = _identifier(ctx, part.get("partId"), location + ".partId")
        revision = _identifier(ctx, part.get("revision"), location + ".revision", revision=True)
        _identifier(ctx, part.get("coordinateSystemId"), location + ".coordinateSystemId")
        supplier_id = _identifier(ctx, part.get("supplierId"), location + ".supplierId")
        process = _identifier(ctx, part.get("process"), location + ".process")
        identity = (part_id, revision)
        if identity in declared_parts:
            ctx.fail(
                "mechanical_part_duplicate",
                location,
                f"Manufactured part {part_id}/{revision} is duplicated.",
                "Declare every manufactured part/revision exactly once.",
            )
        declared_parts.add(identity)
        if process == "injection_molding":
            molded_parts.add(identity)
        require_subject_basis(
            ctx, part, location, coordinates, suppliers, ["supplierId"], [process]
        )
        rows = _artifact_roles(ctx, part.get("artifacts"), _PART_ROLES, location + ".artifacts")
        _require_supplier_formats(
            ctx, suppliers.get(supplier_id), rows,
            ["nativeCad", "step", "manufacturingDrawing"],
            location + ".supplierId",
        )
        validate_native_log(
            ctx,
            rows["nativeReopenLog"],
            location + ".artifacts.nativeReopenLog",
            gate="mechanical_part_native_reopen",
            subject_id=part_id,
            revision=revision,
            inputs=hash_map(rows, ["nativeCad"]),
            outputs=hash_map(rows, ["step", "manufacturingDrawing", "drawingPreview", "modelPreview"]),
        )
        _record_review_subject(
            ctx, subject_type="mechanicalPart", subject_id=part_id, revision=revision,
            rows=rows,
            previews={
                "drawingPreview": ("2d", "manufacturingDrawing"),
                "modelPreview": ("3d", "step"),
            },
        )
        subject_count += 1

    assemblies: set[tuple[str, str]] = set()
    for index, raw in enumerate(_list(ctx, mechanical.get("assemblies"), "mechanical.assemblies")):
        location = f"mechanical.assemblies[{index}]"
        assembly = _exact_keys(
            ctx,
            raw,
            {"assemblyId", "revision", "coordinateSystemId", "supplierId", "artifacts"},
            location,
        )
        assembly_id = _identifier(ctx, assembly.get("assemblyId"), location + ".assemblyId")
        revision = _identifier(
            ctx, assembly.get("revision"), location + ".revision", revision=True
        )
        coordinate_id = _identifier(
            ctx, assembly.get("coordinateSystemId"), location + ".coordinateSystemId"
        )
        supplier_id = _identifier(ctx, assembly.get("supplierId"), location + ".supplierId")
        identity = (assembly_id, revision)
        if identity in assemblies:
            ctx.fail(
                "mechanical_assembly_duplicate",
                location,
                f"Assembly {assembly_id}/{revision} is duplicated.",
                "Declare every required assembly/revision exactly once.",
            )
        assemblies.add(identity)
        require_subject_basis(
            ctx, assembly, location, coordinates, suppliers, ["supplierId"], ["mechanical_assembly"]
        )
        rows = _artifact_roles(ctx, assembly.get("artifacts"), _ASSEMBLY_ROLES, location + ".artifacts")
        _require_supplier_formats(
            ctx, suppliers.get(supplier_id), rows,
            [
                "nativeAssembly", "step", "assemblyDrawing", "explodedDrawing", "sectionDrawing",
            ],
            location + ".supplierId",
        )
        bom_counts, _ = _validate_assembly_documents(
            ctx, assembly_id, revision, units, coordinate_id, rows, location
        )
        unknown_bom_parts = sorted(set(bom_counts) - declared_parts)
        if unknown_bom_parts:
            ctx.fail(
                "assembly_bom_subject_undeclared", location + ".artifacts.bom",
                "Assembly BOM contains undeclared package subjects: "
                + ", ".join(f"{part}/{part_revision}" for part, part_revision in unknown_bom_parts),
                "Declare every manufactured/purchased occurrence as a package part with native/exchange/drawing evidence.",
            )
        molded_in_assembly = {
            part_id
            for (part_id, part_revision) in bom_counts
            if (part_id, part_revision) in molded_parts
        }
        validate_molding_input(
            ctx, rows["moldingInput"], location + ".artifacts.moldingInput",
            assembly_id=assembly_id, revision=revision, units=units,
            coordinate_system_id=coordinate_id, molded_part_ids=molded_in_assembly,
        )
        covered_parts.update(identity for identity in bom_counts if identity in declared_parts)
        validate_native_log(
            ctx,
            rows["interferenceLog"],
            location + ".artifacts.interferenceLog",
            gate="mechanical_assembly_interference",
            subject_id=assembly_id,
            revision=revision,
            inputs=hash_map(rows, ["nativeAssembly", "positions"]),
            outputs={},
        )
        validate_native_log(
            ctx,
            rows["nativeReopenLog"],
            location + ".artifacts.nativeReopenLog",
            gate="mechanical_assembly_native_reopen",
            subject_id=assembly_id,
            revision=revision,
            inputs=hash_map(rows, ["nativeAssembly"]),
            outputs=hash_map(
                rows,
                [
                    "step", "assemblyDrawing", "explodedDrawing", "sectionDrawing",
                    "assemblyPreview2d", "assemblyPreview3d", "assemblyWorkInstruction",
                    "inspectionPlan", "moldingInput", "bom", "positions",
                ],
            ),
        )
        _record_review_subject(
            ctx, subject_type="mechanicalAssembly", subject_id=assembly_id, revision=revision,
            rows=rows,
            previews={
                "assemblyPreview2d": ("2d", "assemblyDrawing"),
                "assemblyPreview3d": ("3d", "step"),
            },
        )
        subject_count += 1
    missing_assembly_coverage = sorted(declared_parts - covered_parts)
    if missing_assembly_coverage:
        ctx.fail(
            "manufactured_part_not_in_any_assembly",
            "mechanical",
            "Manufactured parts absent from every assembly BOM: "
            + ", ".join(f"{part}/{revision}" for part, revision in missing_assembly_coverage),
            "Add every manufactured part to at least one released assembly BOM/position set.",
        )
    return subject_count, declared_parts


def _board_fabrication_layers(ctx: _Context, row: dict[str, Any], location: str) -> set[str]:
    if not row.get("pass") or not isinstance(row.get("resolvedPath"), str):
        return set()
    try:
        text = Path(row["resolvedPath"]).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        ctx.fail(
            "kicad_board_unreadable",
            location,
            "Hash-bound KiCad board cannot be parsed as native text.",
            "Save/reopen the real board in KiCad and export the current native file.",
        )
        return set()
    names = set(_PCB_LAYER.findall(text))
    fabrication = {
        name
        for name in names
        if name.endswith((".Cu", ".Paste", ".SilkS", ".Mask")) or name == "Edge.Cuts"
    }
    if not fabrication or "F.Cu" not in fabrication or "B.Cu" not in fabrication or "Edge.Cuts" not in fabrication:
        ctx.fail(
            "kicad_fabrication_layer_inventory_invalid",
            location,
            "Native board does not expose the minimum fabrication-layer inventory.",
            "Correct the KiCad board stack/layer table and rerun native DRC/CAM export.",
        )
    return fabrication


def _validate_gerber_job(
    ctx: _Context,
    row: dict[str, Any],
    gerber_rows: dict[str, dict[str, Any]],
    location: str,
) -> None:
    document = _json_from_row(ctx, row, location)
    attributes = document.get("FilesAttributes")
    if not isinstance(attributes, list) or not attributes:
        ctx.fail(
            "gerber_job_inventory_missing", location,
            "Gerber job has no FilesAttributes inventory.",
            "Export the native KiCad Gerber job together with the exact current layer files.",
        )
        return
    actual: list[str] = []
    for index, item in enumerate(attributes):
        if not isinstance(item, dict) or not isinstance(item.get("Path"), str):
            ctx.fail(
                "gerber_job_entry_invalid", f"{location}.FilesAttributes[{index}]",
                "Gerber job file entry has no path.",
                "Regenerate the Gerber job from KiCad CAM export.",
            )
            continue
        actual.append(Path(item["Path"].replace("\\", "/")).name.casefold())
    expected = sorted(
        Path(str(item.get("path", ""))).name.casefold()
        for item in gerber_rows.values()
        if item.get("path")
    )
    if len(actual) != len(set(actual)) or sorted(actual) != expected:
        ctx.fail(
            "gerber_job_layer_closure_mismatch", location,
            "Gerber job paths do not exactly equal the hash-bound native fabrication-layer Gerbers.",
            "Remove stale/extra CAM files and re-export one job entry per exact Gerber artifact.",
        )


def _electronics(
    ctx: _Context,
    value: Any,
    coordinates: dict[str, dict[str, Any]],
    suppliers: dict[str, dict[str, Any]],
) -> int:
    electronics = _exact_keys(ctx, value, {"pcbs"}, "electronics")
    pcb_ids: set[str] = set()
    count = 0
    for index, raw in enumerate(_list(ctx, electronics.get("pcbs"), "electronics.pcbs")):
        location = f"electronics.pcbs[{index}]"
        pcb = _exact_keys(
            ctx,
            raw,
            {
                "pcbId", "revision", "coordinateSystemId", "fabricationSupplierId",
                "assemblySupplierId", "fabricationLayers", "artifacts", "gerbers",
            },
            location,
        )
        pcb_id = _identifier(ctx, pcb.get("pcbId"), location + ".pcbId")
        revision = _identifier(ctx, pcb.get("revision"), location + ".revision", revision=True)
        _identifier(ctx, pcb.get("coordinateSystemId"), location + ".coordinateSystemId")
        fabrication_supplier_id = _identifier(
            ctx, pcb.get("fabricationSupplierId"), location + ".fabricationSupplierId"
        )
        assembly_supplier_id = _identifier(
            ctx, pcb.get("assemblySupplierId"), location + ".assemblySupplierId"
        )
        if pcb_id in pcb_ids:
            ctx.fail(
                "pcb_duplicate",
                location,
                f"PCB ID {pcb_id!r} is duplicated even if its revision differs.",
                "Give every independently manufactured board one unique stable pcbId.",
            )
        pcb_ids.add(pcb_id)
        for supplier_field, supplier_id in (
            ("fabricationSupplierId", fabrication_supplier_id),
            ("assemblySupplierId", assembly_supplier_id),
        ):
            profile = suppliers.get(supplier_id)
            if isinstance(profile, dict) and profile.get("_recipientStatus") == RFQ_RECIPIENT_STATUS:
                ctx.fail(
                    "neutral_rfq_recipient_forbidden_for_pcb",
                    location + f".{supplier_field}",
                    "An unassigned mechanical RFQ recipient cannot authorize PCB prototype fabrication or assembly.",
                    "Bind a real authority-backed PCB supplier capability record before claiming prototype fabrication candidacy.",
                )
        require_subject_basis(
            ctx, pcb, location, coordinates, suppliers, ["fabricationSupplierId"], ["pcb_fabrication"]
        )
        require_subject_basis(
            ctx, pcb, location, coordinates, suppliers, ["assemblySupplierId"], ["pcb_assembly"]
        )
        rows = _artifact_roles(ctx, pcb.get("artifacts"), _PCB_ROLES, location + ".artifacts")
        _require_supplier_formats(
            ctx, suppliers.get(fabrication_supplier_id), rows,
            ["board", "jobFile", "pthDrill", "npthDrill", "connectivityNetlist"], location + ".fabricationSupplierId",
        )
        _require_supplier_formats(
            ctx, suppliers.get(assembly_supplier_id), rows,
            ["board", "bom", "cpl", "model3d"], location + ".assemblySupplierId",
        )

        declared_layers_raw = _list(
            ctx, pcb.get("fabricationLayers"), location + ".fabricationLayers"
        )
        declared_layers = [value for value in declared_layers_raw if isinstance(value, str)]
        if len(declared_layers) != len(declared_layers_raw) or len(declared_layers) != len(set(declared_layers)):
            ctx.fail(
                "fabrication_layer_inventory_invalid",
                location + ".fabricationLayers",
                "Fabrication layers must be unique strings.",
                "Copy the exact unique fabrication-layer inventory from the native board.",
            )
        native_layers = _board_fabrication_layers(ctx, rows["board"], location + ".artifacts.board")
        copper_layers = {layer for layer in native_layers if layer.endswith(".Cu")}
        mandatory_non_copper = {
            "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "F.Paste", "B.Paste", "Edge.Cuts",
        }
        if len(copper_layers) not in {2, 4}:
            ctx.fail(
                "pcb_copper_layer_count_unsupported",
                location + ".fabricationLayers",
                f"Exact factory workflow accepts 2 or 4 copper layers; native board has {len(copper_layers)}.",
                "Resolve the board stackup and use the matching 2-layer or 4-layer canonical CAM inventory.",
            )
        missing_non_copper = sorted(mandatory_non_copper - native_layers)
        if missing_non_copper:
            ctx.fail(
                "pcb_mandatory_gerber_layer_missing",
                location + ".fabricationLayers",
                "Native board lacks mandatory Gerber layers: " + ", ".join(missing_non_copper),
                "Enable/export F/B mask, F/B silk, F/B paste and Edge.Cuts in addition to every copper layer.",
            )
        if set(declared_layers) != native_layers:
            ctx.fail(
                "fabrication_layer_native_closure_mismatch",
                location + ".fabricationLayers",
                "Declared fabrication layers do not exactly match the native KiCad board.",
                "Regenerate the layer inventory from the hash-bound board; do not omit internal copper, paste, mask, silk or edge layers.",
            )

        gerber_rows: dict[str, dict[str, Any]] = {}
        for gerber_index, raw_gerber in enumerate(
            _list(ctx, pcb.get("gerbers"), location + ".gerbers")
        ):
            gerber_location = f"{location}.gerbers[{gerber_index}]"
            gerber = _exact_keys(ctx, raw_gerber, {"layer", "artifact"}, gerber_location)
            layer = gerber.get("layer")
            if not isinstance(layer, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{2,64}", layer):
                ctx.fail(
                    "gerber_layer_name_invalid",
                    gerber_location + ".layer",
                    "Gerber layer name is missing or non-portable.",
                    "Use the exact native KiCad layer name.",
                )
                layer = ""
            if layer in gerber_rows:
                ctx.fail(
                    "gerber_layer_duplicate",
                    gerber_location + ".layer",
                    f"Gerber layer {layer!r} is duplicated.",
                    "Provide exactly one Gerber artifact per native fabrication layer.",
                )
            gerber_rows[layer] = _evidence(
                ctx, gerber.get("artifact"), gerber_location + ".artifact", "gerber"
            )
        if set(gerber_rows) != set(declared_layers):
            ctx.fail(
                "gerber_layer_closure_mismatch",
                location + ".gerbers",
                "Gerber inventory does not exactly equal the declared/native fabrication layers.",
                "Export one Gerber for every layer and remove stale or extra layer files.",
            )
        _validate_gerber_job(ctx, rows["jobFile"], gerber_rows, location + ".artifacts.jobFile")

        validate_native_log(
            ctx,
            rows["ercLog"],
            location + ".artifacts.ercLog",
            gate="electronics_erc",
            subject_id=pcb_id,
            revision=revision,
            inputs=hash_map(rows, ["project", "schematic"]),
            outputs=hash_map(rows, ["schematicPdf"]),
        )
        validate_native_log(
            ctx,
            rows["drcLog"],
            location + ".artifacts.drcLog",
            gate="electronics_drc",
            subject_id=pcb_id,
            revision=revision,
            inputs=hash_map(rows, ["project", "board"]),
            outputs={},
        )
        validate_native_log(
            ctx,
            rows["nativeReopenLog"],
            location + ".artifacts.nativeReopenLog",
            gate="electronics_native_reopen_and_export",
            subject_id=pcb_id,
            revision=revision,
            inputs=hash_map(rows, ["project", "schematic", "board"]),
            outputs=hash_map(
                rows,
                [
                    "assemblyDrawing", "fabricationDrawing", "assemblyNotes",
                    "fabricationNotes", "model3d", "bom", "cpl",
                    "schematicPreview", "boardPreview", "assemblyPreview",
                    "fabricationPreview", "modelPreview3d",
                ],
            ),
        )
        cam_outputs = hash_map(
            rows, ["jobFile", "pthDrill", "npthDrill", "connectivityNetlist"]
        )
        for layer, row in gerber_rows.items():
            if row.get("pass") and isinstance(row.get("actualSha256"), str):
                cam_outputs[f"gerber:{layer}"] = row["actualSha256"]
        validate_native_log(
            ctx,
            rows["camLog"],
            location + ".artifacts.camLog",
            gate="electronics_cam_export",
            subject_id=pcb_id,
            revision=revision,
            inputs=hash_map(rows, ["project", "board"]),
            outputs=cam_outputs,
        )
        _record_review_subject(
            ctx, subject_type="pcb", subject_id=pcb_id, revision=revision, rows=rows,
            previews={
                "schematicPreview": ("2d", "schematicPdf"),
                "boardPreview": ("2d", "board"),
                "assemblyPreview": ("2d", "assemblyDrawing"),
                "fabricationPreview": ("2d", "fabricationDrawing"),
                "modelPreview3d": ("3d", "model3d"),
            },
        )
        count += 1
    return count


def validate_manufacturing_release_package(
    package: Any,
    evidence_root: str | Path | None,
) -> dict[str, Any]:
    root: Path | None = None
    root_issue: tuple[str, str, str, str] | None = None
    if evidence_root is None:
        root_issue = (
            "controlled_evidence_root_required",
            "evidenceRoot",
            "A controlled evidence root is mandatory.",
            "Pass the directory containing every hash-bound release artifact.",
        )
    else:
        candidate = Path(evidence_root).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            root_issue = (
                "evidence_root_missing",
                "evidenceRoot",
                "Controlled evidence root does not exist.",
                "Create/populate the release evidence directory before validation.",
            )
        else:
            if not resolved.is_dir():
                root_issue = (
                    "evidence_root_not_directory",
                    "evidenceRoot",
                    "Controlled evidence root is not a directory.",
                    "Pass the directory containing the final artifacts, not a file.",
                )
            elif _is_root_reparse(resolved):
                root_issue = (
                    "evidence_root_link_forbidden",
                    "evidenceRoot",
                    "Controlled evidence root cannot be a symlink or junction.",
                    "Use a real, directly controlled directory.",
                )
            else:
                root = resolved
    ctx = _Context(root)
    handoff_ctx = _Context(root)
    if root_issue:
        ctx.fail(*root_issue)
    document = _exact_keys(
        ctx,
        package,
        {"schema", "packageId", "releaseBasis"},
        "$",
        optional={"mechanical", "electronics"},
    )
    if document.get("schema") != PACKAGE_SCHEMA:
        ctx.fail(
            "package_schema_invalid",
            "schema",
            f"Package schema must be {PACKAGE_SCHEMA}.",
            "Start from the canonical manufacturing release package schema.",
        )
    package_id = _identifier(ctx, document.get("packageId"), "packageId")
    release_basis = _exact_keys(
        ctx,
        document.get("releaseBasis"),
        {"revision", "units", "coordinateSystems", "suppliers"},
        "releaseBasis",
    )
    revision = _identifier(
        ctx, release_basis.get("revision"), "releaseBasis.revision", revision=True
    )
    units = release_basis.get("units")
    if units not in {"mm", "inch"}:
        ctx.fail(
            "release_units_invalid",
            "releaseBasis.units",
            "Release basis must freeze units as mm or inch.",
            "Choose one unit system and convert every subject and manufacturing document consistently.",
        )
        units = ""
    coordinates = coordinate_systems(ctx, release_basis, str(units))
    suppliers, confirmations = supplier_release_records(
        ctx, handoff_ctx, release_basis, str(units), set(coordinates)
    )
    if "mechanical" not in document and "electronics" not in document:
        ctx.fail(
            "manufacturing_domain_missing",
            "$",
            "Package contains neither a mechanical nor electronics manufacturing inventory.",
            "Declare at least one complete mechanical or PCB release inventory.",
        )
    mechanical_count = 0
    pcb_count = 0
    if "mechanical" in document:
        mechanical_count, _ = _mechanical(
            ctx, document.get("mechanical"), str(units), coordinates, suppliers
        )
    if "electronics" in document:
        pcb_count = _electronics(ctx, document.get("electronics"), coordinates, suppliers)
    artifact_pass = bool(ctx.artifacts) and all(row.get("pass") for row in ctx.artifacts)
    mechanical_artifacts = [row for row in ctx.artifacts if str(row.get("location", "")).startswith("mechanical.")]
    electronics_artifacts = [row for row in ctx.artifacts if str(row.get("location", "")).startswith("electronics.")]
    ctx.check(
        "controlled-evidence:path-size-sha256-format",
        artifact_pass,
        {"artifactCount": len(ctx.artifacts), "allArtifactsPass": artifact_pass},
    )
    failures = sorted(
        ctx.failures,
        key=lambda item: (item["location"].casefold(), item["code"].casefold(), item["message"]),
    )
    subject_count = mechanical_count + pcb_count
    base_failures = [
        row for row in failures
        if not row["location"].startswith(("mechanical", "electronics"))
    ]
    mechanical_failures = [row for row in failures if row["location"].startswith("mechanical")]
    electronics_failures = [row for row in failures if row["location"].startswith("electronics")]
    factory_rfq_ready = (
        "mechanical" in document
        and mechanical_count > 0
        and not base_failures
        and not mechanical_failures
        and bool(mechanical_artifacts)
        and all(row.get("pass") for row in mechanical_artifacts)
    )
    prototype_fabrication_ready = (
        "electronics" in document
        and pcb_count > 0
        and not base_failures
        and not electronics_failures
        and bool(electronics_artifacts)
        and all(row.get("pass") for row in electronics_artifacts)
    )
    digital_package_ready = (
        subject_count > 0
        and ("mechanical" not in document or factory_rfq_ready)
        and ("electronics" not in document or prototype_fabrication_ready)
    )
    candidate_ready = factory_rfq_ready or prototype_fabrication_ready
    base_artifacts = [
        row for row in ctx.artifacts
        if not str(row.get("location", "")).startswith(("mechanical.", "electronics."))
    ]
    candidate_artifacts = [*base_artifacts]
    if factory_rfq_ready:
        candidate_artifacts.extend(mechanical_artifacts)
    if prototype_fabrication_ready:
        candidate_artifacts.extend(electronics_artifacts)
    candidate_artifacts = [row for row in candidate_artifacts if row.get("pass") is True]

    def artifact_closure(rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        closure_rows = [
            {
                "location": row["location"],
                "kind": row["kind"],
                "path": row["path"],
                "size": row.get("actualSize"),
                "sha256": row.get("actualSha256"),
            }
            for row in sorted(rows, key=lambda item: item["location"].casefold())
        ]
        return _canonical_sha256(closure_rows)

    closure_sha = artifact_closure(candidate_artifacts) if candidate_ready else None
    domain_closures = {
        "mechanical": artifact_closure(mechanical_artifacts) if factory_rfq_ready else None,
        "electronics": artifact_closure(electronics_artifacts) if prototype_fabrication_ready else None,
    }
    candidate_artifact_locations = sorted(str(row["location"]) for row in candidate_artifacts)
    expected_confirmation_hashes = {
        str(row["location"]): str(row["actualSha256"])
        for row in sorted(ctx.artifacts, key=lambda item: item["location"].casefold())
        if row.get("pass") and isinstance(row.get("actualSha256"), str)
    }
    validate_supplier_confirmations(
        handoff_ctx,
        confirmations,
        ctx.used_supplier_ids,
        package_id=package_id,
        revision=revision,
        expected_sha256_by_location=expected_confirmation_hashes,
    )
    handoff_failures = sorted(
        [*handoff_ctx.failures, *handoff_ctx.handoff_failures],
        key=lambda item: (item["location"].casefold(), item["code"].casefold(), item["message"]),
    )
    factory_ready = (
        digital_package_ready
        and not handoff_failures
        and bool(handoff_ctx.artifacts)
        and all(row.get("pass") for row in handoff_ctx.artifacts)
    )
    handoff_closure_sha = (
        artifact_closure([*ctx.artifacts, *handoff_ctx.artifacts]) if factory_ready else None
    )
    preview_expected = sum(len(subject["previews"]) for subject in ctx.review_subjects)
    preview_verified = sum(
        1
        for subject in ctx.review_subjects
        for preview in subject["previews"]
        if preview.get("pass") and preview.get("targetPass")
    )
    partial_candidate = candidate_ready and not digital_package_ready
    return {
        "ok": candidate_ready,
        "schema": VALIDATION_SCHEMA,
        "packageId": package_id,
        "releaseRevision": revision,
        "status": (
            "factory_handoff_candidate" if factory_ready
            else "digital_manufacturing_candidate" if digital_package_ready
            else "partial_digital_candidate" if partial_candidate
            else "blocked"
        ),
        "factoryRfqCandidateReady": factory_rfq_ready,
        "prototypeFabricationCandidateReady": prototype_fabrication_ready,
        "digitalPackageReady": digital_package_ready,
        "factoryHandoffReady": factory_ready,
        "artifactDisposition": (
            "factory_handoff_candidate" if factory_ready
            else "digital_manufacturing_candidate" if digital_package_ready
            else "partial_digital_candidate" if partial_candidate
            else "blocker_report_only"
        ),
        "candidateReviewerMayOpen": True,
        "candidateReviewerStatus": "ready_candidate_review" if candidate_ready else "blocker_review",
        "productionReady": False,
        "productionReleaseAuthorized": False,
        "toolSteelCutAuthorized": False,
        "massProductionAuthorized": False,
        "externalProfessionalSignoffRequired": True,
        "nativeExecutionReplayedByThisValidator": False,
        "selfReportedReadinessAccepted": False,
        "counts": {
            "mechanicalSubjects": mechanical_count,
            "pcbs": pcb_count,
            "artifacts": len(ctx.artifacts),
            "failures": len(failures),
            "actualPreviewsExpected": preview_expected,
            "actualPreviewsVerified": preview_verified,
        },
        "artifactClosureSha256": closure_sha,
        "handoffArtifactClosureSha256": handoff_closure_sha,
        "domainArtifactClosureSha256": domain_closures,
        "candidateArtifactLocations": candidate_artifact_locations,
        "artifacts": ctx.artifacts,
        "confirmationArtifacts": handoff_ctx.artifacts,
        "reviewSubjects": ctx.review_subjects,
        "checks": ctx.checks,
        "failures": failures,
        "handoffFailures": handoff_failures,
        "requiredActions": [
            {"code": item["code"], "location": item["location"], "action": item["repair"]}
            for item in failures
        ],
        "handoffRequiredActions": [
            {"code": item["code"], "location": item["location"], "action": item["repair"]}
            for item in handoff_failures
        ],
        "safetyLocks": {
            "reviewOnly": True,
            "accepted": False,
            "productionReleaseAuthorized": False,
            "toolSteelCutAuthorized": False,
            "massProductionAuthorized": False,
            "externalSignoffRequired": True,
        },
        "evidenceRoot": str(root) if root else None,
    }


def _is_root_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return path.is_symlink()
