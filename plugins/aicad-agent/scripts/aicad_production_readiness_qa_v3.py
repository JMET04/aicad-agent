#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "rules" / "production_readiness_rules.json"
SCHEMA_PATH = ROOT / "rules" / "production_readiness_contract_v3.schema.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve(path_value: str, base_dir: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        raise ValueError("absolute_paths_are_forbidden")
    resolved = (base_dir / candidate).resolve()
    if not resolved.is_relative_to(base_dir.resolve()):
        raise ValueError("path_escapes_contract_directory")
    return resolved


def _pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _artifact_set_sha(rows: list[dict[str, Any]]) -> str:
    portable = [
        {
            "artifactId": row["artifactId"],
            "kind": row["kind"],
            "partId": row.get("partId"),
            "subjectType": row.get("subjectType"),
            "revision": row["revision"],
            "path": row["path"].replace("\\", "/"),
            "sha256": row["actualSha256"],
            "sizeBytes": row["sizeBytes"],
        }
        for row in rows
    ]
    portable.sort(key=lambda item: (item["artifactId"].casefold(), item["path"].casefold()))
    encoded = json.dumps(portable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifactId": row["artifactId"],
        "kind": row["kind"],
        "partId": row.get("partId"),
        "revision": row["revision"],
        "path": row["path"].replace("\\", "/"),
    }


def _duplicate_values(values: list[str]) -> list[str]:
    folded = [value.casefold() for value in values]
    return sorted(value for value, count in Counter(folded).items() if count > 1)


def _exact_sha256_map(actual: Any, rows: list[dict[str, Any]]) -> bool:
    expected = {row["artifactId"]: row["actualSha256"] for row in rows if row.get("pass")}
    return (
        isinstance(actual, dict)
        and set(actual) == set(expected)
        and all(
            isinstance(actual[key], str)
            and actual[key].lower() == value.lower()
            for key, value in expected.items()
        )
    )


def _subject_rows_match_candidates(
    actual_rows: Any,
    subjects: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> tuple[bool, dict[str, list[str]]]:
    expected_artifact_ids_by_part = {
        subject["partId"]: sorted(
            item["artifactId"] for item in rows
            if item.get("partId") == subject["partId"]
        )
        for subject in subjects
    }
    shape_pass = (
        isinstance(actual_rows, list)
        and all(
            isinstance(item, dict)
            and set(item) == {
                "partId", "subjectType", "revision", "quantity", "artifactIds"
            }
            and isinstance(item.get("partId"), str)
            and isinstance(item.get("subjectType"), str)
            and isinstance(item.get("revision"), str)
            and isinstance(item.get("quantity"), int)
            and not isinstance(item.get("quantity"), bool)
            and item["quantity"] > 0
            and isinstance(item.get("artifactIds"), list)
            and all(isinstance(artifact_id, str) for artifact_id in item["artifactIds"])
            for item in actual_rows
        )
    )
    if not shape_pass:
        return False, expected_artifact_ids_by_part
    actual_part_ids = [item["partId"] for item in actual_rows]
    if _duplicate_values(actual_part_ids):
        return False, expected_artifact_ids_by_part
    actual_by_part = {item["partId"]: item for item in actual_rows}
    passed = (
        set(actual_by_part) == {subject["partId"] for subject in subjects}
        and all(
            actual_by_part[subject["partId"]]["subjectType"] == subject["subjectType"]
            and actual_by_part[subject["partId"]]["revision"] == subject["revision"]
            and not _duplicate_values(actual_by_part[subject["partId"]]["artifactIds"])
            and sorted(actual_by_part[subject["partId"]]["artifactIds"])
            == expected_artifact_ids_by_part[subject["partId"]]
            for subject in subjects
        )
    )
    return passed, expected_artifact_ids_by_part


def _parse_kicad_board_inventory(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    root: list[Any] = []
    stack: list[list[Any]] = [root]
    for token in tokens:
        if token == "(":
            child: list[Any] = []
            stack[-1].append(child)
            stack.append(child)
        elif token == ")":
            if len(stack) == 1:
                raise ValueError("unexpected_closing_parenthesis")
            stack.pop()
        else:
            if token.startswith('"'):
                token = json.loads(token)
            stack[-1].append(token)
    if len(stack) != 1:
        raise ValueError("unterminated_parenthesis")
    boards = [item for item in root if isinstance(item, list) and item[:1] == ["kicad_pcb"]]
    if len(boards) != 1:
        raise ValueError("expected_one_kicad_pcb_root")
    board = boards[0]
    layer_tables = [
        item for item in board
        if isinstance(item, list) and item[:1] == ["layers"]
    ]
    if len(layer_tables) != 1:
        raise ValueError("expected_one_layers_table")
    copper_layers = sorted({
        str(item[1])
        for item in layer_tables[0][1:]
        if isinstance(item, list)
        and len(item) >= 3
        and isinstance(item[1], str)
        and item[1].endswith(".Cu")
    })
    if not copper_layers or "F.Cu" not in copper_layers or "B.Cu" not in copper_layers:
        raise ValueError("invalid_copper_layer_inventory")
    plated = False
    non_plated = False
    pending: list[list[Any]] = [board]
    while pending:
        expression = pending.pop()
        pending.extend(item for item in expression if isinstance(item, list))
        if expression[:1] == ["pad"] and len(expression) >= 3:
            plated = plated or expression[2] == "thru_hole"
            non_plated = non_plated or expression[2] == "np_thru_hole"
        elif expression[:1] == ["via"]:
            plated = True
    return {
        "copperLayers": copper_layers,
        "designDrillRequirements": {"plated": plated, "nonPlated": non_plated},
    }


def _verify_candidate_declared_closure_consistency(
    discipline: str,
    rows: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    base_dir: Path,
    closure_profile: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    evidence: list[dict[str, Any]] = []
    spec = closure_profile["candidateClosureManifest"]
    manifests = [row for row in rows if row["kind"] == spec["kind"]]

    if discipline == "mechanical":
        bom_spec = closure_profile["machineReadableBom"]
        all_bom_rows = [row for row in rows if row["kind"] == bom_spec["kind"]]
        package_bom_rows = [row for row in all_bom_rows if row.get("partId") is None]
        if len(package_bom_rows) != 1:
            failures.append(
                f"mechanical_bom_count_mismatch:expected=1:actual={len(package_bom_rows)}"
            )
        if len(all_bom_rows) != len(package_bom_rows):
            failures.append("mechanical_bom_must_be_package_scoped")
        machine_bom_subject_rows: list[dict[str, Any]] | None = None
        for bom_row in package_bom_rows:
            bom_record: dict[str, Any] = {
                "artifactId": bom_row["artifactId"],
                "kind": bom_row["kind"],
                "path": bom_row["path"],
                "hashPass": bom_row.get("pass") is True,
                "evidenceRole": "machine_readable_bom",
            }
            if not bom_row.get("pass"):
                failures.append(f"mechanical_bom_unavailable:{bom_row['artifactId']}")
                evidence.append(bom_record)
                continue
            try:
                bom_document = _load(_resolve(bom_row["path"], base_dir))
            except Exception as exc:
                failures.append(f"mechanical_bom_unreadable:{bom_row['artifactId']}")
                bom_record["error"] = str(exc)
                evidence.append(bom_record)
                continue
            bom_schema_pass = (
                set(bom_document) == {"schema", "discipline", "subjectRows"}
                and bom_document.get("schema") == bom_spec["schema"]
                and bom_document.get("discipline") == "mechanical"
            )
            bom_subject_rows = bom_document.get("subjectRows")
            bom_rows_pass, expected_ids = _subject_rows_match_candidates(
                bom_subject_rows, subjects, rows
            )
            if bom_schema_pass and bom_rows_pass:
                machine_bom_subject_rows = bom_subject_rows
            bom_record.update({
                "schemaPass": bom_schema_pass,
                "subjectRowsPass": bom_rows_pass,
                "actualSubjectRows": bom_subject_rows,
                "expectedSubjectArtifactIdsByPartId": expected_ids,
            })
            if not bom_schema_pass:
                failures.append(f"mechanical_bom_schema_mismatch:{bom_row['artifactId']}")
            if not bom_rows_pass:
                failures.append(f"mechanical_bom_subject_rows_mismatch:{bom_row['artifactId']}")
            evidence.append(bom_record)

        package_manifests = [row for row in manifests if row.get("partId") is None]
        if len(package_manifests) != 1:
            failures.append(
                f"product_structure_manifest_count_mismatch:expected=1:actual={len(package_manifests)}"
            )
        if len(manifests) != len(package_manifests):
            failures.append("product_structure_manifest_must_be_package_scoped")
        for row in package_manifests:
            record: dict[str, Any] = {
                "artifactId": row["artifactId"],
                "kind": row["kind"],
                "path": row["path"],
                "hashPass": row.get("pass") is True,
            }
            if not row.get("pass"):
                failures.append(f"product_structure_manifest_unavailable:{row['artifactId']}")
                evidence.append(record)
                continue
            try:
                document = _load(_resolve(row["path"], base_dir))
            except Exception as exc:
                failures.append(f"product_structure_manifest_unreadable:{row['artifactId']}")
                record["error"] = str(exc)
                evidence.append(record)
                continue
            schema_pass = (
                set(document) == {
                    "schema", "discipline", "artifactSubjects",
                    "mechanicalBomSha256ByArtifactId", "bomSubjectRows",
                }
                and document.get("schema") == spec["schema"]
                and document.get("discipline") == "mechanical"
            )
            expected_subjects = sorted(
                subjects,
                key=lambda item: (item["partId"].casefold(), item["subjectType"], item["revision"]),
            )
            actual_subjects = document.get("artifactSubjects")
            subject_set_pass = (
                isinstance(actual_subjects, list)
                and all(isinstance(item, dict) for item in actual_subjects)
                and sorted(
                    actual_subjects,
                    key=lambda item: (
                        str(item.get("partId", "")).casefold(),
                        str(item.get("subjectType", "")),
                        str(item.get("revision", "")),
                    ),
                ) == expected_subjects
            )
            bom_map_pass = _exact_sha256_map(
                document.get("mechanicalBomSha256ByArtifactId"), package_bom_rows
            )
            actual_bom_subject_rows = document.get("bomSubjectRows")
            bom_subject_rows_pass, expected_artifact_ids_by_part = (
                _subject_rows_match_candidates(actual_bom_subject_rows, subjects, rows)
            )
            machine_bom_rows_match = (
                bom_subject_rows_pass
                and machine_bom_subject_rows is not None
                and sorted(actual_bom_subject_rows, key=lambda item: item["partId"].casefold())
                == sorted(machine_bom_subject_rows, key=lambda item: item["partId"].casefold())
            )
            record.update({
                "schemaPass": schema_pass,
                "subjectSetPass": subject_set_pass,
                "expectedArtifactSubjects": expected_subjects,
                "actualArtifactSubjects": actual_subjects,
                "mechanicalBomMapPass": bom_map_pass,
                "expectedMechanicalBomSha256ByArtifactId": {
                    item["artifactId"]: item["actualSha256"] for item in package_bom_rows if item.get("pass")
                },
                "bomSubjectRowsPass": bom_subject_rows_pass,
                "bomSubjectRowsMatchMachineBom": machine_bom_rows_match,
                "actualBomSubjectRows": actual_bom_subject_rows,
                "expectedBomSubjectArtifactIdsByPartId": expected_artifact_ids_by_part,
            })
            if not schema_pass:
                failures.append(f"product_structure_manifest_schema_mismatch:{row['artifactId']}")
            if not subject_set_pass:
                failures.append(f"product_structure_subject_set_mismatch:{row['artifactId']}")
            if not bom_map_pass:
                failures.append(f"product_structure_bom_map_mismatch:{row['artifactId']}")
            if not bom_subject_rows_pass:
                failures.append(f"product_structure_bom_subject_rows_mismatch:{row['artifactId']}")
            if not machine_bom_rows_match:
                failures.append(f"product_structure_machine_bom_rows_mismatch:{row['artifactId']}")
            evidence.append(record)
        return sorted(set(failures)), evidence

    pcb_subjects = [row for row in subjects if row["subjectType"] == "pcb_design"]
    inventory_spec = closure_profile["candidateBoardInventory"]
    inventory_rows = [row for row in rows if row["kind"] == inventory_spec["kind"]]
    inventory_by_part: dict[str, list[dict[str, Any]]] = {}
    board_inventory_by_part: dict[str, dict[str, Any]] = {}
    for subject in pcb_subjects:
        part_id = subject["partId"]
        board_rows = [
            row for row in rows
            if row["kind"] == inventory_spec["sourceKind"]
            and row.get("partId") == part_id
        ]
        if len(board_rows) != 1:
            failures.append(
                f"kicad_board_count_mismatch:{part_id}:expected=1:actual={len(board_rows)}"
            )
        for board_row in board_rows:
            board_record: dict[str, Any] = {
                "artifactId": board_row["artifactId"],
                "kind": board_row["kind"],
                "partId": part_id,
                "path": board_row["path"],
                "hashPass": board_row.get("pass") is True,
                "evidenceRole": "independent_kicad_board_parse",
            }
            if not board_row.get("pass"):
                failures.append(f"kicad_board_unavailable:{board_row['artifactId']}")
                evidence.append(board_record)
                continue
            try:
                parsed_inventory = _parse_kicad_board_inventory(
                    _resolve(board_row["path"], base_dir)
                )
            except Exception as exc:
                failures.append(f"kicad_board_native_parse_failed:{board_row['artifactId']}")
                board_record["error"] = str(exc)
                evidence.append(board_record)
                continue
            board_inventory_by_part[part_id] = parsed_inventory
            board_record.update({
                "nativeParsePass": True,
                "parsedCopperLayers": parsed_inventory["copperLayers"],
                "parsedDesignDrillRequirements": parsed_inventory["designDrillRequirements"],
            })
            evidence.append(board_record)

    for row in inventory_rows:
        part_id = row.get("partId")
        if part_id is None:
            failures.append(f"native_board_inventory_missing_part_id:{row['artifactId']}")
            continue
        inventory_by_part.setdefault(part_id, []).append(row)
    for subject in pcb_subjects:
        part_id = subject["partId"]
        selected_inventories = inventory_by_part.get(part_id, [])
        if len(selected_inventories) != 1:
            failures.append(
                f"native_board_inventory_count_mismatch:{part_id}:expected=1:actual={len(selected_inventories)}"
            )
        for row in selected_inventories:
            record: dict[str, Any] = {
                "artifactId": row["artifactId"],
                "kind": row["kind"],
                "partId": part_id,
                "path": row["path"],
                "hashPass": row.get("pass") is True,
            }
            if not row.get("pass"):
                failures.append(f"native_board_inventory_unavailable:{row['artifactId']}")
                evidence.append(record)
                continue
            try:
                document = _load(_resolve(row["path"], base_dir))
            except Exception as exc:
                failures.append(f"native_board_inventory_unreadable:{row['artifactId']}")
                record["error"] = str(exc)
                evidence.append(record)
                continue
            identity_pass = (
                set(document) == {
                    "schema", "discipline", "partId", "revision",
                    "kicadBoardSha256ByArtifactId", "copperLayers",
                    "designDrillRequirements",
                }
                and document.get("schema") == inventory_spec["schema"]
                and document.get("discipline") == "electronics"
                and document.get("partId") == part_id
                and document.get("revision") == subject["revision"]
            )
            board_rows = [
                item for item in rows
                if item["kind"] == inventory_spec["sourceKind"]
                and item.get("partId") == part_id
            ]
            board_map_pass = _exact_sha256_map(
                document.get("kicadBoardSha256ByArtifactId"), board_rows
            )
            requirements = document.get("designDrillRequirements")
            requirements_shape_pass = (
                isinstance(requirements, dict)
                and set(requirements) == {"plated", "nonPlated"}
                and isinstance(requirements.get("plated"), bool)
                and isinstance(requirements.get("nonPlated"), bool)
                and any(requirements.values())
            )
            copper_layers = document.get("copperLayers")
            copper_shape_pass = (
                isinstance(copper_layers, list)
                and all(isinstance(layer, str) and layer.endswith(".Cu") for layer in copper_layers)
                and len(copper_layers) == len({layer.casefold() for layer in copper_layers})
                and "F.Cu" in copper_layers
                and "B.Cu" in copper_layers
            )
            parsed_inventory = board_inventory_by_part.get(part_id)
            native_parse_match = (
                parsed_inventory is not None
                and requirements_shape_pass
                and copper_shape_pass
                and requirements == parsed_inventory["designDrillRequirements"]
                and sorted(copper_layers) == parsed_inventory["copperLayers"]
            )
            record.update({
                "identityPass": identity_pass,
                "kicadBoardArtifactSetPass": board_map_pass,
                "designDrillRequirementsShapePass": requirements_shape_pass,
                "copperLayersShapePass": copper_shape_pass,
                "nativeBoardParseMatch": native_parse_match,
                "declaredDesignDrillRequirements": requirements,
                "declaredCopperLayers": copper_layers,
                "parsedNativeBoardInventory": parsed_inventory,
            })
            if not identity_pass:
                failures.append(f"native_board_inventory_identity_mismatch:{row['artifactId']}")
            if not board_map_pass:
                failures.append(f"native_board_inventory_board_map_mismatch:{row['artifactId']}")
            if not requirements_shape_pass:
                failures.append(f"native_board_inventory_drill_requirements_invalid:{row['artifactId']}")
            if not copper_shape_pass:
                failures.append(f"native_board_inventory_copper_layers_invalid:{row['artifactId']}")
            if not native_parse_match:
                failures.append(f"native_board_inventory_native_parse_mismatch:{row['artifactId']}")
            evidence.append(record)
    unexpected_inventory_parts = set(inventory_by_part) - {
        row["partId"] for row in pcb_subjects
    }
    for part_id in sorted(unexpected_inventory_parts):
        failures.append(f"native_board_inventory_part_id_not_declared:{part_id}")

    manifest_by_part: dict[str, list[dict[str, Any]]] = {}
    for row in manifests:
        part_id = row.get("partId")
        if part_id is None:
            failures.append(f"cam_output_manifest_missing_part_id:{row['artifactId']}")
            continue
        manifest_by_part.setdefault(part_id, []).append(row)
    for subject in pcb_subjects:
        part_id = subject["partId"]
        selected_manifests = manifest_by_part.get(part_id, [])
        if len(selected_manifests) != 1:
            failures.append(
                f"cam_output_manifest_count_mismatch:{part_id}:expected=1:actual={len(selected_manifests)}"
            )
        for row in selected_manifests:
            record = {
                "artifactId": row["artifactId"], "kind": row["kind"], "partId": part_id,
                "path": row["path"], "hashPass": row.get("pass") is True,
            }
            if not row.get("pass"):
                failures.append(f"cam_output_manifest_unavailable:{row['artifactId']}")
                evidence.append(record)
                continue
            try:
                document = _load(_resolve(row["path"], base_dir))
            except Exception as exc:
                failures.append(f"cam_output_manifest_unreadable:{row['artifactId']}")
                record["error"] = str(exc)
                evidence.append(record)
                continue
            identity_pass = (
                document.get("schema") == spec["schema"]
                and document.get("discipline") == "electronics"
                and document.get("partId") == part_id
                and document.get("revision") == subject["revision"]
            )
            gerber_rows = [item for item in rows if item["kind"] == "gerber_layer" and item.get("partId") == part_id]
            drill_rows = [item for item in rows if item["kind"] == "drill" and item.get("partId") == part_id]
            job_rows = [item for item in rows if item["kind"] == spec["sourceKind"] and item.get("partId") == part_id]
            gerber_outputs = document.get("gerberLayers")
            gerber_map: dict[str, str] = {}
            gerber_layer_names: list[str] = []
            gerber_shape_pass = isinstance(gerber_outputs, list)
            if gerber_shape_pass:
                for item in gerber_outputs:
                    if not (
                        isinstance(item, dict)
                        and set(item) == {"artifactId", "sha256", "layerName"}
                        and isinstance(item["artifactId"], str)
                        and isinstance(item["sha256"], str)
                        and isinstance(item["layerName"], str)
                        and item["layerName"]
                    ):
                        gerber_shape_pass = False
                        break
                    gerber_map[item["artifactId"]] = item["sha256"]
                    gerber_layer_names.append(item["layerName"])
                if len(gerber_map) != len(gerber_outputs) or _duplicate_values(gerber_layer_names):
                    gerber_shape_pass = False
            gerber_pass = gerber_shape_pass and _exact_sha256_map(gerber_map, gerber_rows)
            parsed_board_inventory = board_inventory_by_part.get(part_id)
            parsed_copper_layers = (
                parsed_board_inventory["copperLayers"] if parsed_board_inventory else None
            )
            cam_copper_layers = sorted(
                layer for layer in gerber_layer_names if layer.endswith(".Cu")
            )
            copper_layer_closure_pass = (
                parsed_copper_layers is not None and cam_copper_layers == parsed_copper_layers
            )
            job_pass = _exact_sha256_map(document.get("jobFileSha256ByArtifactId"), job_rows)
            drill_outputs = document.get("drillOutputs")
            drill_map: dict[str, str] = {}
            drill_roles: list[tuple[str, str]] = []
            drill_shape_pass = isinstance(drill_outputs, list)
            if drill_shape_pass:
                for item in drill_outputs:
                    if not (
                        isinstance(item, dict)
                        and set(item) == {"artifactId", "sha256", "drillType"}
                        and isinstance(item["artifactId"], str)
                        and isinstance(item["sha256"], str)
                        and item["drillType"] in {"plated", "non_plated", "mixed"}
                    ):
                        drill_shape_pass = False
                        break
                    drill_map[item["artifactId"]] = item["sha256"]
                    drill_roles.append((item["artifactId"], item["drillType"]))
                if len(drill_map) != len(drill_outputs):
                    drill_shape_pass = False
            drill_map_pass = drill_shape_pass and _exact_sha256_map(drill_map, drill_rows)
            requirements = document.get("designDrillRequirements")
            requirements_pass = (
                isinstance(requirements, dict)
                and set(requirements) == {"plated", "nonPlated"}
                and isinstance(requirements.get("plated"), bool)
                and isinstance(requirements.get("nonPlated"), bool)
                and any(requirements.values())
            )
            board_requirements = (
                parsed_board_inventory["designDrillRequirements"]
                if parsed_board_inventory else None
            )
            requirements_authority_pass = (
                requirements_pass and requirements == board_requirements
            )
            candidate_drill_ids = {
                item["artifactId"] for item in drill_rows if item.get("pass")
            }
            plated_pass = board_requirements is not None and (
                not board_requirements["plated"] or any(
                    artifact_id in candidate_drill_ids and role in {"plated", "mixed"}
                    for artifact_id, role in drill_roles
                )
            )
            non_plated_pass = board_requirements is not None and (
                not board_requirements["nonPlated"] or any(
                    artifact_id in candidate_drill_ids and role in {"non_plated", "mixed"}
                    for artifact_id, role in drill_roles
                )
            )
            record.update({
                "identityPass": identity_pass, "gerberArtifactSetPass": gerber_pass,
                "boardCopperLayerClosurePass": copper_layer_closure_pass,
                "parsedBoardCopperLayers": parsed_copper_layers,
                "drillArtifactSetPass": drill_map_pass, "jobArtifactSetPass": job_pass,
                "designDrillRequirementsPass": requirements_pass,
                "boardDrillRequirementsMatch": requirements_authority_pass,
                "platedOutputPresentWhenRequired": plated_pass,
                "nonPlatedOutputPresentWhenRequired": non_plated_pass,
                "declaredDesignDrillRequirements": requirements,
                "parsedBoardDesignDrillRequirements": board_requirements,
            })
            if not identity_pass:
                failures.append(f"cam_output_manifest_identity_mismatch:{row['artifactId']}")
            if not gerber_pass:
                failures.append(f"cam_manifest_gerber_set_mismatch:{row['artifactId']}")
            if not copper_layer_closure_pass:
                failures.append(f"cam_manifest_board_copper_layer_set_mismatch:{row['artifactId']}")
            if not drill_map_pass:
                failures.append(f"cam_manifest_drill_set_mismatch:{row['artifactId']}")
            if not job_pass:
                failures.append(f"cam_manifest_job_set_mismatch:{row['artifactId']}")
            if not requirements_pass:
                failures.append(f"cam_manifest_drill_requirements_invalid:{row['artifactId']}")
            if not requirements_authority_pass:
                failures.append(f"cam_manifest_board_drill_requirements_mismatch:{row['artifactId']}")
            if not plated_pass:
                failures.append(f"cam_manifest_plated_output_missing:{row['artifactId']}")
            if not non_plated_pass:
                failures.append(f"cam_manifest_non_plated_output_missing:{row['artifactId']}")
            evidence.append(record)
    unexpected_parts = set(manifest_by_part) - {row["partId"] for row in pcb_subjects}
    for part_id in sorted(unexpected_parts):
        failures.append(f"cam_output_manifest_part_id_not_declared:{part_id}")
    return sorted(set(failures)), evidence


def _verify_artifacts(
    contract: dict[str, Any],
    base_dir: Path,
    required_kinds: set[str],
    closure_profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None, list[str], list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    duplicates: list[str] = []

    subjects = contract["artifactSubjects"]
    duplicate_subjects = _duplicate_values([row["partId"] for row in subjects])
    duplicates.extend(f"partId:{value}" for value in duplicate_subjects)
    subject_by_id = {row["partId"]: row for row in subjects}
    allowed_types = set(closure_profile["allowedSubjectTypes"])
    for subject in subjects:
        if subject["subjectType"] not in allowed_types:
            failures.append(f"subject_type_not_allowed:{subject['partId']}:{subject['subjectType']}")
    required_subject_type = closure_profile["requiredSubjectTypeAtLeastOne"]
    if not any(row["subjectType"] == required_subject_type for row in subjects):
        failures.append(f"required_subject_type_missing:{required_subject_type}")
    threshold = closure_profile.get("requireAssemblyWhenManufacturedPartCountGreaterThan")
    if threshold is not None:
        manufactured_count = sum(row["subjectType"] == "manufactured_part" for row in subjects)
        if manufactured_count > threshold and not any(
            row["subjectType"] == "mechanical_assembly" for row in subjects
        ):
            failures.append("multi_part_package_missing_mechanical_assembly_subject")

    subject_scoped_kinds = set(closure_profile["subjectScopedKinds"])
    expected_rows: list[dict[str, Any]] = []
    for item in contract["expectedArtifactClosure"]:
        normalized = dict(item)
        try:
            path = _resolve(item["path"], base_dir)
            normalized["path"] = path.relative_to(base_dir.resolve()).as_posix()
        except ValueError as exc:
            failures.append(f"expected_path:{item['artifactId']}:{exc}")
            normalized["path"] = item["path"].replace("\\", "/")
        part_id = item.get("partId")
        subject = subject_by_id.get(part_id) if part_id is not None else None
        if part_id is not None and subject is None:
            failures.append(
                f"expected_artifact_part_id_not_declared:{item['artifactId']}:{part_id}"
            )
        elif subject is not None and item["revision"] != subject["revision"]:
            failures.append(f"expected_artifact_revision_mismatch:{item['artifactId']}:{part_id}")
        if item["kind"] in subject_scoped_kinds and part_id is None:
            failures.append(f"expected_subject_scoped_artifact_missing_part_id:{item['artifactId']}")
        expected_rows.append(normalized)
    duplicates.extend(
        f"expected_artifactId:{value}"
        for value in _duplicate_values([row["artifactId"] for row in expected_rows])
    )
    duplicates.extend(
        f"expected_path:{value}"
        for value in _duplicate_values([row["path"] for row in expected_rows])
    )

    rows: list[dict[str, Any]] = []
    for item in contract["candidateArtifacts"]:
        part_id = item.get("partId")
        subject = subject_by_id.get(part_id) if part_id is not None else None
        try:
            path = _resolve(item["path"], base_dir)
        except ValueError as exc:
            rows.append({
                "artifactId": item["artifactId"],
                "kind": item["kind"],
                "partId": part_id,
                "subjectType": subject.get("subjectType") if subject else None,
                "revision": item["revision"],
                "path": item["path"].replace("\\", "/"),
                "exists": False,
                "sizeBytes": None,
                "declaredSha256": item["sha256"].lower(),
                "actualSha256": None,
                "pass": False,
                "reason": str(exc),
            })
            continue
        exists = path.is_file()
        actual = _sha256(path) if exists else None
        size = path.stat().st_size if exists else None
        portable_path = path.relative_to(base_dir.resolve()).as_posix()
        row = {
            "artifactId": item["artifactId"],
            "kind": item["kind"],
            "partId": part_id,
            "subjectType": subject.get("subjectType") if subject else None,
            "revision": item["revision"],
            "path": portable_path,
            "exists": exists,
            "sizeBytes": size,
            "declaredSha256": item["sha256"].lower(),
            "actualSha256": actual,
            "pass": exists and actual == item["sha256"].lower(),
        }
        if part_id is not None and subject is None:
            row["pass"] = False
            row["reason"] = "artifact_part_id_not_declared"
            failures.append(f"artifact_part_id_not_declared:{item['artifactId']}:{part_id}")
        elif subject is not None and item["revision"] != subject["revision"]:
            row["pass"] = False
            row["reason"] = "artifact_revision_does_not_match_subject"
            failures.append(f"artifact_revision_mismatch:{item['artifactId']}:{part_id}")
        rows.append(row)

    duplicates.extend(
        f"artifactId:{value}" for value in _duplicate_values([row["artifactId"] for row in rows])
    )
    duplicates.extend(f"path:{value}" for value in _duplicate_values([row["path"] for row in rows]))

    expected_by_id = {row["artifactId"].casefold(): row for row in expected_rows}
    candidate_by_id = {row["artifactId"].casefold(): row for row in rows}
    for artifact_id in sorted(expected_by_id.keys() - candidate_by_id.keys()):
        failures.append(f"expected_artifact_missing:{artifact_id}")
    for artifact_id in sorted(candidate_by_id.keys() - expected_by_id.keys()):
        failures.append(f"unexpected_artifact_not_in_expected_closure:{artifact_id}")
    for artifact_id in sorted(expected_by_id.keys() & candidate_by_id.keys()):
        expected_identity = _identity(expected_by_id[artifact_id])
        candidate_identity = _identity(candidate_by_id[artifact_id])
        if expected_identity != candidate_identity:
            failures.append(f"expected_artifact_identity_mismatch:{artifact_id}")

    counts = Counter(row["kind"] for row in rows)
    for kind in sorted(required_kinds):
        if counts[kind] < 1:
            failures.append(f"required_kind_missing:{kind}")

    for row in rows:
        if row["kind"] in subject_scoped_kinds and row.get("partId") is None:
            failures.append(f"subject_scoped_artifact_missing_part_id:{row['artifactId']}")

    per_subject = closure_profile["perSubjectRequiredKinds"]
    for subject in subjects:
        for kind in per_subject.get(subject["subjectType"], []):
            if not any(
                row["kind"] == kind and row.get("partId") == subject["partId"]
                for row in rows
            ):
                failures.append(f"subject_required_kind_missing:{subject['partId']}:{kind}")

    per_subject_at_least_one = closure_profile.get("perSubjectRequiredKindAtLeastOne", {})
    for subject in subjects:
        for kind in per_subject_at_least_one.get(subject["subjectType"], []):
            if not any(
                row["kind"] == kind and row.get("partId") == subject["partId"]
                for row in rows
            ):
                failures.append(f"subject_required_kind_missing:{subject['partId']}:{kind}")

    for kind in closure_profile["packageRequiredKinds"]:
        if not any(row["kind"] == kind and row.get("partId") is None for row in rows):
            failures.append(f"package_required_kind_missing:{kind}")

    consistency_failures, consistency_evidence = _verify_candidate_declared_closure_consistency(
        contract["discipline"], rows, subjects, base_dir, closure_profile
    )
    failures.extend(consistency_failures)
    valid = bool(rows) and all(row["pass"] for row in rows) and not failures and not duplicates
    return rows, _artifact_set_sha(rows) if valid else None, sorted(set(failures)), sorted(set(duplicates)), consistency_evidence


def _selector_rows(rows: list[dict[str, Any]], selector: dict[str, Any]) -> list[dict[str, Any]]:
    selected = [
        row for row in rows
        if row.get("pass") and row["kind"] == selector["kind"]
    ]
    subject_types = selector.get("subjectTypes")
    if subject_types is not None:
        allowed = set(subject_types)
        selected = [row for row in selected if row.get("subjectType") in allowed]
    selected.sort(key=lambda row: row["artifactId"].casefold())
    return selected


def _contains_expected_rows(actual: Any, expected: list[dict[str, Any]]) -> bool:
    if not isinstance(actual, list):
        return False
    return all(
        any(
            isinstance(candidate, dict)
            and all(candidate.get(key) == value for key, value in required.items())
            for candidate in actual
        )
        for required in expected
    )


def _verify_gate(
    reference: dict[str, Any],
    gate: dict[str, Any],
    base_dir: Path,
    artifact_set_sha: str | None,
    artifact_rows: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    try:
        path = _resolve(reference["path"], base_dir)
    except ValueError as exc:
        return False, {
            "kind": reference["kind"],
            "expectedKind": gate["kind"],
            "path": reference["path"],
            "reason": str(exc),
        }
    exists = path.is_file()
    actual_hash = _sha256(path) if exists else None
    result: dict[str, Any] = {
        "kind": reference["kind"],
        "expectedKind": gate["kind"],
        "path": path.relative_to(base_dir.resolve()).as_posix(),
        "exists": exists,
        "declaredSha256": reference["sha256"].lower(),
        "actualSha256": actual_hash,
    }
    result["hashPass"] = exists and actual_hash == reference["sha256"].lower()
    result["kindPass"] = reference["kind"] == gate["kind"]
    if not result["hashPass"]:
        result["reason"] = "evidence_file_missing_or_hash_mismatch"
        return False, result
    if not result["kindPass"]:
        result["reason"] = "evidence_kind_does_not_match_rule"
        return False, result
    try:
        document = _load(path)
        actual_value = _pointer(document, gate["jsonPointer"])
    except Exception as exc:
        result["reason"] = "evidence_read_or_rule_pointer_failure"
        result["error"] = str(exc)
        return False, result
    if reference["kind"] == "review_release":
        try:
            reviewer = document["release"]["reviewer"]
            record = document["release"]["record"]
            required_values = {
                "reviewer.name": reviewer["name"],
                "reviewer.credential": reviewer["credential"],
                "reviewer.scope": reviewer["scope"],
                "record.id": record["id"],
                "record.signatureType": record["signatureType"],
                "record.signatureValue": record["signatureValue"],
            }
        except (KeyError, TypeError) as exc:
            result["reason"] = "recorded_approval_metadata_missing"
            result["error"] = str(exc)
            return False, result
        blank = sorted(
            name for name, value in required_values.items()
            if not isinstance(value, str) or not value.strip()
        )
        result["recordedApprovalMetadataPresent"] = not blank
        result["blankRecordedApprovalMetadata"] = blank
        result["cryptographicTrustChainVerified"] = False
        if blank:
            result["reason"] = "recorded_approval_metadata_blank"
            return False, result

    expected_value = gate["expectedValue"]
    predicate = gate.get("predicate")
    selector = gate.get("artifactSelector")
    if predicate == "non_empty_string":
        value_pass = isinstance(actual_value, str) and bool(actual_value.strip())
        expectation: Any = {"predicate": "non_empty_string"}
    elif predicate == "contains_expected_rows":
        value_pass = _contains_expected_rows(actual_value, expected_value)
        expectation = {
            "predicate": "contains_expected_rows",
            "requiredRowSubsets": expected_value,
        }
    elif predicate in {"artifact_sha256_map", "artifact_true_map"}:
        if not isinstance(selector, dict):
            result["reason"] = "rule_artifact_selector_missing"
            return False, result
        selected = _selector_rows(artifact_rows, selector)
        if not selected:
            result["reason"] = "rule_artifact_selector_empty"
            result["artifactSelector"] = selector
            return False, result
        selected_ids = [row["artifactId"] for row in selected]
        if predicate == "artifact_sha256_map":
            required_map = {
                row["artifactId"]: row["actualSha256"]
                for row in selected
            }
            value_pass = (
                isinstance(actual_value, dict)
                and set(actual_value) == set(required_map)
                and all(
                    isinstance(actual_value[key], str)
                    and actual_value[key].lower() == value.lower()
                    for key, value in required_map.items()
                )
            )
            expectation = {
                "predicate": predicate,
                "artifactSelector": selector,
                "requiredArtifactSha256ById": required_map,
            }
        else:
            value_pass = (
                isinstance(actual_value, dict)
                and set(actual_value) == set(selected_ids)
                and all(actual_value[key] is True for key in selected_ids)
            )
            expectation = {
                "predicate": predicate,
                "artifactSelector": selector,
                "requiredTrueByArtifactId": {key: True for key in selected_ids},
            }
    else:
        value_pass = actual_value == expected_value
        expectation = expected_value
    result.update({
        "jsonPointer": gate["jsonPointer"],
        "expectedValue": expectation,
        "actualValue": actual_value,
        "valuePass": value_pass,
    })
    if not result["valuePass"]:
        result["reason"] = "rule_owned_expected_value_mismatch"
        return False, result
    if gate.get("bindArtifactSet"):
        try:
            reported_set = _pointer(document, "/artifactSetSha256")
        except Exception as exc:
            result["reason"] = "artifact_set_binding_missing"
            result["error"] = str(exc)
            return False, result
        result.update({
            "artifactSetPointer": "/artifactSetSha256",
            "reportedArtifactSetSha256": str(reported_set).lower(),
            "actualArtifactSetSha256": artifact_set_sha,
            "artifactSetPass": bool(artifact_set_sha)
            and str(reported_set).lower() == artifact_set_sha,
        })
        if not result["artifactSetPass"]:
            result["reason"] = "evidence_artifact_set_mismatch"
            return False, result
    return True, result


def evaluate(contract: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    base_dir = (base_dir or Path.cwd()).resolve()
    schema = _load(SCHEMA_PATH)
    rules = _load(RULES_PATH)
    jsonschema.Draft202012Validator(schema).validate(contract)

    discipline = contract["discipline"]
    profile_name = (
        "mechanicalManufacturingProfileV3"
        if discipline == "mechanical"
        else "electronicsFabricationProfileV3"
    )
    profile = rules[profile_name]
    required_kinds = set(rules["requiredArtifactKindsV3"][discipline])
    closure_profile = rules["artifactClosureProfilesV3"][discipline]
    artifact_rows, artifact_set_sha, artifact_failures, duplicate_identity, manifest_evidence = _verify_artifacts(
        contract, base_dir, required_kinds, closure_profile
    )
    artifact_pass = artifact_set_sha is not None
    gate_results: dict[str, dict[str, Any]] = {
        "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness": {
            "status": "pass" if artifact_pass else "fail",
            "evidence": {
                "artifacts": artifact_rows,
                "artifactSubjects": contract["artifactSubjects"],
                "expectedArtifactClosure": contract["expectedArtifactClosure"],
                "requiredKindsAtLeastOne": sorted(required_kinds),
                "perSubjectRequiredKinds": closure_profile["perSubjectRequiredKinds"],
                "perSubjectRequiredKindAtLeastOne": closure_profile.get("perSubjectRequiredKindAtLeastOne", {}),
                "subjectScopedKinds": closure_profile["subjectScopedKinds"],
                "packageRequiredKinds": closure_profile["packageRequiredKinds"],
                "closureFailures": artifact_failures,
                "candidateDeclaredClosureConsistencyEvidence": manifest_evidence,
                "duplicateIdentityOrPath": duplicate_identity,
            },
        }
    }

    evidence = contract["evidence"]
    expected_groups = set(profile)
    actual_groups = set(evidence)
    if expected_groups != actual_groups:
        gate_results["inventory.groups"] = {
            "status": "fail",
            "evidence": {
                "missing": sorted(expected_groups - actual_groups),
                "extra": sorted(actual_groups - expected_groups),
            },
        }
    for group, gate_specs in profile.items():
        supplied = evidence.get(group, {})
        expected_names = set(gate_specs)
        actual_names = set(supplied)
        if expected_names != actual_names:
            gate_results[f"inventory.{group}"] = {
                "status": "fail",
                "evidence": {
                    "missing": sorted(expected_names - actual_names),
                    "extra": sorted(actual_names - expected_names),
                },
            }
        for name, gate in gate_specs.items():
            record = supplied.get(name)
            if not isinstance(record, dict):
                gate_results[f"{group}.{name}"] = {
                    "status": "fail",
                    "evidence": {"reason": "missing_required_gate"},
                }
                continue
            passed, gate_evidence = _verify_gate(
                record["evidenceRef"],
                gate,
                base_dir,
                artifact_set_sha,
                artifact_rows,
            )
            gate_results[f"{group}.{name}"] = {
                "status": "pass" if passed else "fail",
                "evidence": gate_evidence,
            }

    failed = [name for name, row in gate_results.items() if row["status"] != "pass"]

    def is_release_failure(name: str) -> bool:
        return name.startswith("release.") or name == "inventory.release"

    evidence_contract_failed = [name for name in failed if not is_release_failure(name)]
    recorded_approval_failed = [name for name in failed if is_release_failure(name)]
    evidence_contract_ready = not evidence_contract_failed
    recorded_approval_evidence = not recorded_approval_failed
    status = "evidence_contract_ready" if evidence_contract_ready else "evidence_contract_incomplete"
    lessons = [] if evidence_contract_ready else [{
        "ruleId": "PROD-G013",
        "symptom": (
            f"{len(evidence_contract_failed)} non-compensatory evidence-contract gates "
            "lack valid evidence."
        ),
        "rootCause": (
            "Engineering, manufacturing, native-host or exact artifact-closure evidence "
            "was not completely bound to the canonical rules and artifact set."
        ),
        "correction": (
            "Correct every failed evidence-contract gate and regenerate evidence hashes; "
            "do not substitute a score, waiver, archive-only shortcut or passed=true."
        ),
        "preventionRule": (
            "PROD-G013: one failed non-release evidence-contract gate blocks "
            "evidence-contract-ready status; only the canonical inventory owns expected values."
        ),
        "failedGates": evidence_contract_failed,
    }]
    return {
        "schema": "aicad_production_readiness_validation_v3",
        "status": status,
        "project": contract["project"],
        "requestedStage": contract["requestedStage"],
        "discipline": discipline,
        "strictProductionOnly": True,
        "deliveryDisposition": (
            "evidence_contract_review_only"
            if evidence_contract_ready
            else "blocker_report_only"
        ),
        "evidenceContractReady": evidence_contract_ready,
        "independentEvidenceAuthenticityVerified": False,
        "nativeExecutionReplayedByThisQA": False,
        "technicalPackageReady": False,
        "recordedApprovalEvidencePresentAndHashBound": recorded_approval_evidence,
        "externalReleaseCryptographicTrustChainVerified": False,
        "productionReleaseEligible": False,
        "productionCandidateDeliverable": False,
        "manufacturingAuthorized": False,
        "fabricationAuthorized": False,
        "productionCandidateArtifactAllowed": False,
        "automaticAcceptanceAllowed": False,
        "artifactSetSha256": artifact_set_sha,
        "artifactSubjects": contract["artifactSubjects"],
        "expectedArtifactClosure": contract["expectedArtifactClosure"],
        "gateResults": gate_results,
        "failedGates": failed,
        "evidenceContractFailedGates": evidence_contract_failed,
        "recordedApprovalEvidenceFailedGates": recorded_approval_failed,
        "candidateArtifacts": contract["candidateArtifacts"],
        "technicalReviewArtifacts": [],
        "exposedArtifacts": [],
        "rootCauseLessons": lessons,
        "rules": {
            "path": "rules/production_readiness_rules.json",
            "sha256": _sha256(RULES_PATH),
            "profile": profile_name,
        },
        "contractSchema": {
            "path": "rules/production_readiness_contract_v3.schema.json",
            "sha256": _sha256(SCHEMA_PATH),
        },
        "safetyLocks": {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
            "comparativeSuperiorityClaimAllowed": False,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    title = "Mechanical" if result["discipline"] == "mechanical" else "PCB"
    rows = [
        f"# AICAD {title} evidence-contract gate",
        "",
        f"- Status: **{result['status']}**",
        f"- Disposition: {result['deliveryDisposition']}",
        f"- Evidence contract ready: {str(result['evidenceContractReady']).lower()}",
        "- Independent evidence authenticity verified: false",
        "- Native execution replayed by this QA: false",
        "- Technical candidate artifacts exposed: false",
        "- Production release eligible: false",
        f"- Artifact-set SHA-256: {result.get('artifactSetSha256') or 'unavailable'}",
        "",
        "## Evidence binding results",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    rows.extend(
        f"| {name} | {record['status']} |"
        for name, record in result["gateResults"].items()
    )
    if result["evidenceContractFailedGates"]:
        rows.extend([
            "",
            "## Blocking evidence-contract gates",
            "",
            *[f"- {name}" for name in result["evidenceContractFailedGates"]],
        ])
    if result["recordedApprovalEvidenceFailedGates"]:
        rows.extend([
            "",
            "## Recorded approval evidence not complete",
            "",
            "These fields do not change the evidence-contract conclusion and do not authorize release.",
            "",
            *[f"- {name}" for name in result["recordedApprovalEvidenceFailedGates"]],
        ])
    rows.extend([
        "",
        "Every non-release evidence-contract gate is non-compensatory.",
        "Recorded approval evidence is not cryptographic trust-chain verification or production authorization.",
        "Safety locks remain reviewOnly=true, accepted=false, ruleEnabled=false, packagingGated=true, comparativeSuperiorityClaimAllowed=false.",
    ])
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the canonical mechanical/PCB evidence contract without granting "
            "technical or production readiness."
        )
    )
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    contract_path = args.contract.resolve()
    result = evaluate(_load(contract_path), contract_path.parent)
    output = args.output or contract_path.with_suffix(".production-validation-v3.json")
    markdown = args.markdown or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown.write_text(render_markdown(result), encoding="utf-8-sig")
    try:
        output_display = output.resolve().relative_to(contract_path.parent).as_posix()
    except ValueError:
        output_display = output.name
    try:
        markdown_display = markdown.resolve().relative_to(contract_path.parent).as_posix()
    except ValueError:
        markdown_display = markdown.name
    print(json.dumps({
        "ok": result["evidenceContractReady"],
        "status": result["status"],
        "evidenceContractReady": result["evidenceContractReady"],
        "technicalPackageReady": result["technicalPackageReady"],
        "productionReleaseEligible": result["productionReleaseEligible"],
        "deliveryDisposition": result["deliveryDisposition"],
        "output": output_display,
        "markdown": markdown_display,
    }, ensure_ascii=False))
    return 0 if result["evidenceContractReady"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
