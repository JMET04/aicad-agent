from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_architecture_document_set_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_architecture_document_set_qa", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


STOREYS = (
    ("LF", "Lower floor", -3200.0),
    ("MF", "Main floor", 0.0),
    ("UF", "Upper floor", 3400.0),
)


def canonical_sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def authority_axes(equal_spacing: bool) -> dict[str, list[dict[str, object]]]:
    vertical = [0.0, 6000.0, 12000.0, 18000.0] if equal_spacing else [0.0, 8400.0, 10500.0, 18800.0]
    horizontal = [0.0, 5000.0, 10000.0] if equal_spacing else [0.0, 7200.0, 14900.0]
    return {
        "vertical": [
            {"id": str(index + 1), "coordinateMm": coordinate}
            for index, coordinate in enumerate(vertical)
        ],
        "horizontal": [
            {"id": chr(ord("A") + index), "coordinateMm": coordinate}
            for index, coordinate in enumerate(horizontal)
        ],
    }


def candidate_axes(storey_id: str, axes: dict[str, list[dict[str, object]]]) -> dict[str, list[dict[str, object]]]:
    return {
        direction: [
            {
                **row,
                "supportEntityIds": [f"{storey_id}-{direction[0].upper()}-{row['id']}-SUPPORT"],
            }
            for row in rows
        ]
        for direction, rows in axes.items()
    }


def refresh_modifier(contract: dict[str, object]) -> None:
    modifier = contract["modifier"]
    assert isinstance(modifier, dict)
    digest = QA.document_set_digest(contract)
    selectors = "".join(
        f'<button data-storey-id="{storey_id}">{storey_id}</button>\n'
        for storey_id in modifier["storeySelectorIds"]
    )
    html = (
        "<!doctype html>\n"
        f'<html data-aicad-modifier-mode="{modifier["mode"]}" '
        f'data-artifact-role="{modifier["artifactRole"]}" '
        f'data-selection-scope-mode="{modifier["selectionScopeMode"]}" '
        f'data-default-storey-id="{modifier["defaultStoreyId"]}" '
        f'data-active-storey-id="{modifier["activeStoreyId"]}">\n'
        f'<head><meta name="aicad-document-set-sha256" content="{digest}"></head>\n'
        f"<body>\n{selectors}</body>\n</html>\n"
    )
    html_path = Path(str(modifier["htmlPath"]))
    html_path.write_text(html, encoding="utf-8")
    html_sha = file_sha(html_path)
    modifier["htmlSha256"] = html_sha
    modifier["openTargetPath"] = str(html_path)
    modifier["openTargetSha256"] = html_sha
    modifier["embeddedDocumentSetSha256"] = digest


def build_contract(directory: Path, equal_spacing: bool = False) -> dict[str, object]:
    axes = authority_axes(equal_spacing)
    authority = {
        "schema": "aicad_axis_authority_catalog_v1",
        "revision": "AUTH-R1",
        "authorityStatus": "project_authority",
        "storeys": [
            {"storeyId": storey_id, **copy.deepcopy(axes)}
            for storey_id, _title, _elevation in STOREYS
        ],
    }
    authority_path = directory / "axis-authority.json"
    write_json(authority_path, authority)
    authority_sha = file_sha(authority_path)

    documents: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    for storey_id, _title, _elevation in STOREYS:
        candidates = candidate_axes(storey_id, axes)
        plan = {
            "schema_version": "2.0",
            "drawing": {"id": f"DOC-{storey_id}", "domain": "architecture"},
            "storeyId": storey_id,
            "axes": copy.deepcopy(candidates),
            "steps": [],
        }
        plan_path = directory / f"{storey_id}.plan.json"
        write_json(plan_path, plan)
        plan_sha = canonical_sha(plan)
        view = {
            "schema_version": "1.1",
            "space": "2d",
            "domain": "architecture",
            "source_sha256": plan_sha,
            "views": [{"id": f"{storey_id}-PLAN", "storeyId": storey_id}],
        }
        view_path = directory / f"{storey_id}.view.json"
        write_json(view_path, view)
        documents.append(
            {
                "documentId": f"DOC-{storey_id}",
                "storeyId": storey_id,
                "sheetId": f"A-{101 + len(documents)}",
                "planPath": str(plan_path),
                "planCanonicalSha256": plan_sha,
                "viewPackagePath": str(view_path),
                "viewPackageSha256": file_sha(view_path),
            }
        )
        bindings.append(
            {
                "storeyId": storey_id,
                "mode": "external_authority_catalog",
                "authorityStatus": "project_authority",
                "sourcePath": str(authority_path),
                "sourceSha256": authority_sha,
                "sourceRevision": "AUTH-R1",
                "regularityPolicy": "authority_result_not_assumed",
                "candidateAxes": candidates,
            }
        )

    html_path = directory / "document-set.review.html"
    zeros = "0" * 64
    contract: dict[str, object] = {
        "schema": "aicad_architectural_document_set_v1",
        "projectId": "ARCH-DOCSET-REGRESSION",
        "deliveryStage": "construction_candidate",
        "requestedStoreys": [
            {"id": storey_id, "title": title, "elevationMm": elevation}
            for storey_id, title, elevation in STOREYS
        ],
        "documents": documents,
        "axisAuthorityBindings": bindings,
        "modifier": {
            "mode": "document_set_switcher",
            "artifactRole": "interactive_drawing_modifier",
            "htmlPath": str(html_path),
            "htmlSha256": zeros,
            "openTargetPath": str(html_path),
            "openTargetSha256": zeros,
            "embeddedDocumentSetSha256": zeros,
            "storeySelectorIds": [row[0] for row in STOREYS],
            "defaultStoreyId": "MF",
            "activeStoreyId": "MF",
            "selectionScopeMode": "document_scoped",
        },
        "safetyLocks": {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
        },
    }
    refresh_modifier(contract)
    return contract


def synchronize_wrong_equal_grid(contract: dict[str, object]) -> None:
    wrong_axes = authority_axes(equal_spacing=True)
    bindings = {
        row["storeyId"]: row
        for row in contract["axisAuthorityBindings"]
    }
    for storey_id, binding in bindings.items():
        binding["candidateAxes"] = candidate_axes(str(storey_id), wrong_axes)
    for document in contract["documents"]:
        storey_id = str(document["storeyId"])
        plan_path = Path(str(document["planPath"]))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["axes"] = copy.deepcopy(bindings[storey_id]["candidateAxes"])
        write_json(plan_path, plan)
        plan_sha = canonical_sha(plan)
        document["planCanonicalSha256"] = plan_sha
        view_path = Path(str(document["viewPackagePath"]))
        view = json.loads(view_path.read_text(encoding="utf-8"))
        view["source_sha256"] = plan_sha
        write_json(view_path, view)
        document["viewPackageSha256"] = file_sha(view_path)
    refresh_modifier(contract)


class ArchitecturalDocumentSetTests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema = json.loads(
            (ROOT / "rules" / "architectural_document_set.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)

    def test_three_storey_document_set_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            result = QA.evaluate(contract, directory)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(row["pass"] for row in result["checks"].values()))
        self.assertEqual(result["rulesApplied"], ["ARCH-D048", "ARCH-D049", "ARCH-D050", "ARCH-D051"])

    def test_authority_derived_equal_spacing_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory, equal_spacing=True)
            result = QA.evaluate(contract, directory)
        self.assertEqual(result["status"], "pass")
        evidence = result["checks"]["independent_axis_authority_binding"]["evidence"]
        self.assertTrue(
            all(
                binding["equalSpacingObserved"] == {"vertical": True, "horizontal": True}
                for binding in evidence["bindings"]
            )
        )

    def test_synchronized_wrong_equal_grid_is_rejected_by_independent_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory, equal_spacing=False)
            synchronize_wrong_equal_grid(contract)
            result = QA.evaluate(contract, directory)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["checks"]["plan_view_source_hash_freshness"]["pass"])
        self.assertFalse(result["checks"]["independent_axis_authority_binding"]["pass"])
        self.assertTrue(result["checks"]["modifier_document_set_complete"]["pass"])

    def test_missing_storeys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            contract["documents"] = [
                row for row in contract["documents"] if row["storeyId"] == "MF"
            ]
            refresh_modifier(contract)
            result = QA.evaluate(contract, directory)
        self.assertFalse(result["checks"]["requested_storey_document_bijection"]["pass"])

    def test_duplicate_main_floor_cannot_satisfy_three_storeys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            for row in contract["documents"]:
                row["storeyId"] = "MF"
            refresh_modifier(contract)
            result = QA.evaluate(contract, directory)
        self.assertFalse(result["checks"]["requested_storey_document_bijection"]["pass"])

    def test_single_floor_modifier_is_rejected_for_three_storeys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            contract["modifier"]["storeySelectorIds"] = ["MF"]
            refresh_modifier(contract)
            result = QA.evaluate(contract, directory)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["checks"]["requested_storey_document_bijection"]["pass"])
        self.assertFalse(result["checks"]["modifier_document_set_complete"]["pass"])

    def test_stale_view_source_hash_is_rejected_even_when_view_bytes_are_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            document = contract["documents"][0]
            view_path = Path(str(document["viewPackagePath"]))
            view = json.loads(view_path.read_text(encoding="utf-8"))
            view["source_sha256"] = "0" * 64
            write_json(view_path, view)
            document["viewPackageSha256"] = file_sha(view_path)
            refresh_modifier(contract)
            result = QA.evaluate(contract, directory)
        self.assertFalse(result["checks"]["plan_view_source_hash_freshness"]["pass"])
        self.assertTrue(result["checks"]["modifier_document_set_complete"]["pass"])

    def test_reused_main_floor_files_cannot_impersonate_other_storeys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            main = next(row for row in contract["documents"] if row["storeyId"] == "MF")
            for document in contract["documents"]:
                document["planPath"] = main["planPath"]
                document["planCanonicalSha256"] = main["planCanonicalSha256"]
                document["viewPackagePath"] = main["viewPackagePath"]
                document["viewPackageSha256"] = main["viewPackageSha256"]
            refresh_modifier(contract)
            result = QA.evaluate(contract, directory)
        self.assertFalse(result["checks"]["plan_view_source_hash_freshness"]["pass"])

    def test_contract_axes_cannot_hide_different_actual_plan_axes_or_supports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            document = contract["documents"][0]
            plan_path = Path(str(document["planPath"]))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["axes"]["vertical"][1]["coordinateMm"] += 500.0
            plan["axes"]["horizontal"][0]["supportEntityIds"] = ["UNRELATED-SUPPORT"]
            write_json(plan_path, plan)
            plan_sha = canonical_sha(plan)
            document["planCanonicalSha256"] = plan_sha
            view_path = Path(str(document["viewPackagePath"]))
            view = json.loads(view_path.read_text(encoding="utf-8"))
            view["source_sha256"] = plan_sha
            write_json(view_path, view)
            document["viewPackageSha256"] = file_sha(view_path)
            refresh_modifier(contract)
            result = QA.evaluate(contract, directory)
        self.assertTrue(result["checks"]["plan_view_source_hash_freshness"]["pass"])
        self.assertFalse(result["checks"]["independent_axis_authority_binding"]["pass"])

    def test_wrong_open_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            contract = build_contract(directory)
            stale_path = directory / "stale.review.html"
            stale_path.write_text("<html>stale</html>\n", encoding="utf-8")
            contract["modifier"]["openTargetPath"] = str(stale_path)
            contract["modifier"]["openTargetSha256"] = file_sha(stale_path)
            result = QA.evaluate(contract, directory)
        self.assertTrue(result["checks"]["modifier_document_set_complete"]["pass"])
        self.assertFalse(result["checks"]["modifier_open_target_freshness"]["pass"])


if __name__ == "__main__":
    unittest.main()
