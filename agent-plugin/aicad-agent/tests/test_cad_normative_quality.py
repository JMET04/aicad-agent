from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "scripts" / "aicad_normative_quality_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_normative_quality_qa", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)


def _support_binding(document_id: str) -> dict:
    coordinates = ((0.0, 0.0), (6000.0, 4000.0), (12000.0, 0.0))
    source = [
        {
            "id": f"A-{document_id}-{index}",
            "xMm": x,
            "yMm": y,
            "sourceEntityId": f"COL-{document_id}-{index}",
        }
        for index, (x, y) in enumerate(coordinates, 1)
    ]
    target = [
        {
            "id": f"S-{document_id}-{index}",
            "xMm": x,
            "yMm": y,
            "sourceEntityId": source[index - 1]["id"],
        }
        for index, (x, y) in enumerate(coordinates, 1)
    ]
    return {
        "documentId": document_id,
        "transferPolicy": "exact_bidirectional_xy_pair_set",
        "cartesianExpansionAllowed": False,
        "source": source,
        "target": target,
    }


def _annotation_layout() -> dict:
    stages = ("axis_bubbles", "chain_dimensions", "overall_dimensions", "notes")
    viewports = []
    for viewport_id, width, height in (
        ("desktop_1920x1200", 1920, 1200),
        ("compact_1280x800", 1280, 800),
    ):
        reservations = [
            {
                "id": f"{viewport_id}-content",
                "ownerId": "OWNER-content",
                "stage": "content",
                "leftPx": 20.0,
                "topPx": 120.0,
                "rightPx": min(float(width) - 20.0, 900.0),
                "bottomPx": min(float(height) - 20.0, 700.0),
            }
        ]
        boxes = []
        for index, stage in enumerate(stages):
            left = 20.0 + index * 220.0
            owner = f"OWNER-{stage}"
            reservation_id = f"{viewport_id}-{stage}"
            reservations.append(
                {
                    "id": reservation_id,
                    "ownerId": owner,
                    "stage": stage,
                    "leftPx": left,
                    "topPx": 20.0,
                    "rightPx": left + 200.0,
                    "bottomPx": 90.0,
                }
            )
            boxes.append(
                {
                    "id": f"{reservation_id}-TEXT",
                    "ownerId": owner,
                    "reservationId": reservation_id,
                    "stage": stage,
                    "leftPx": left + 10.0,
                    "topPx": 35.0,
                    "rightPx": left + 150.0,
                    "bottomPx": 65.0,
                    "textHeightPx": 10.0,
                }
            )
        viewports.append(
            {
                "id": viewport_id,
                "widthPx": width,
                "heightPx": height,
                "collisionCount": 0,
                "clippedCount": 0,
                "horizontalOverflowPx": 0,
                "reservations": reservations,
                "boxes": boxes,
            }
        )
    return {
        "placementPolicy": "forward_reservation_no_backtracking",
        "reservationOrder": ["content", "axis_bubbles", "chain_dimensions", "overall_dimensions", "notes"],
        "viewports": viewports,
    }


def _selection_arbitration() -> dict:
    return {
        "distanceMetric": "visible_primitive_screen_distance",
        "maximumCandidateDistancePx": 8,
        "distanceBucketPx": 1.5,
        "priorityTableVersion": "aicad_semantic_pick_priority_v1",
        "paintOrderAuthority": False,
        "repeatPickPolicy": "cycle_all_candidates_at_same_pointer",
        "documentScope": "document_scoped",
        "qaCases": [
            {
                "id": "OVERLAP-1",
                "activeDocumentId": "DOC-MF",
                "candidates": [
                    {"id": "DIM-1", "documentId": "DOC-MF", "semanticType": "DIMENSION", "distancePx": 0.8, "semanticPriority": 250},
                    {"id": "WALL-1", "documentId": "DOC-MF", "semanticType": "WALL", "distancePx": 1.0, "semanticPriority": 900},
                    {"id": "GRID-1", "documentId": "DOC-MF", "semanticType": "GRID", "distancePx": 1.7, "semanticPriority": 100},
                    {"id": "FAR", "documentId": "DOC-MF", "semanticType": "COLUMN", "distancePx": 8.1, "semanticPriority": 900},
                    {"id": "FOREIGN", "documentId": "DOC-UF", "semanticType": "COLUMN", "distancePx": 0.0, "semanticPriority": 900},
                ],
                "expectedCycle": ["WALL-1", "DIM-1", "GRID-1"],
            }
        ],
    }


def build_contract() -> dict:
    requested = ["DOC-LF", "DOC-MF", "DOC-UF"]
    return {
        "schema": "aicad_cad_normative_quality_contract_v1",
        "contractId": "CLIFF_VILLA_NORMATIVE_001",
        "domain": "architecture",
        "inputHashes": [
            {"id": "design-basis", "sha256": "a" * 64},
            {"id": "source-plans", "sha256": "b" * 64},
        ],
        "structuralSupportMode": "required",
        "structuralSupportBindings": [_support_binding(document_id) for document_id in requested],
        "annotationLayout": _annotation_layout(),
        "selectionArbitration": _selection_arbitration(),
        "documentSet": {
            "requestedIds": requested,
            "renderedIds": list(requested),
            "sourceIds": list(requested),
            "selectionScope": "document_scoped",
            "switchClearsSelection": True,
            "freshnessHashesMatch": True,
        },
        "releaseClosure": {
            "builtInHiddenSameVolumeStaging": True,
            "independentVerifierPassed": True,
            "atomicRenameWithRollback": True,
            "manifestPolicy": "all_release_files_except_manifest_self",
            "postPublishWrites": False,
            "inputHashesMatch": True,
        },
        "textTransport": {
            "executionIdsAscii": True,
            "humanTextEncoding": "UTF-8",
            "nativeTextBijection": True,
            "replacementCharacterCount": 0,
        },
        "safetyLocks": {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
        },
    }


class CadNormativeQualityTests(unittest.TestCase):
    def test_schema_is_self_contained_and_positive_contract_passes(self) -> None:
        schema = json.loads((PLUGIN / "rules" / "cad_normative_quality_contract.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(build_contract())
        result = QA.evaluate(build_contract())
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(row["pass"] for row in result["checks"].values()))
        self.assertTrue(result["externalReleaseVerifierRequired"])
        self.assertFalse(
            result["checks"]["release_declaration_requires_external_verifier"]["evidence"]["independentlyProvenByThisQA"]
        )

    def test_cartesian_expansion_and_missing_reverse_support_are_rejected(self) -> None:
        contract = build_contract()
        binding = contract["structuralSupportBindings"][0]
        xs = sorted({row["xMm"] for row in binding["source"]})
        ys = sorted({row["yMm"] for row in binding["source"]})
        binding["target"] = [
            {
                "id": f"S-{x}-{y}",
                "xMm": x,
                "yMm": y,
                "sourceEntityId": binding["source"][0]["id"],
            }
            for x in xs
            for y in ys
        ]
        result = QA.evaluate(contract)
        check = result["checks"]["structural_support_bidirectional_pair_set"]
        self.assertFalse(check["pass"])
        self.assertTrue(any("Cartesian expansion" in value for value in check["evidence"]["failures"]))

        contract = build_contract()
        contract["structuralSupportBindings"][1]["target"].pop()
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["structural_support_bidirectional_pair_set"]["pass"])

    def test_support_provenance_and_document_binding_are_derived(self) -> None:
        contract = build_contract()
        contract["structuralSupportBindings"][0]["target"][0]["sourceEntityId"] = "MISSING-SOURCE"
        contract["structuralSupportBindings"][1]["documentId"] = "DOC-LF"
        result = QA.evaluate(contract)
        failures = result["checks"]["structural_support_bidirectional_pair_set"]["evidence"]["failures"]
        self.assertTrue(any("provenance" in value for value in failures))
        self.assertTrue(any("bijection" in value for value in failures))

        contract = build_contract()
        target = contract["structuralSupportBindings"][0]["target"]
        target[0]["sourceEntityId"], target[1]["sourceEntityId"] = (
            target[1]["sourceEntityId"], target[0]["sourceEntityId"]
        )
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["structural_support_bidirectional_pair_set"]["pass"])

    def test_not_applicable_support_requires_explicit_waiver(self) -> None:
        contract = build_contract()
        contract["domain"] = "pcb"
        contract["structuralSupportMode"] = "not_applicable"
        contract["structuralSupportBindings"] = []
        contract["structuralSupportWaiverReason"] = "PCB review has no building structural support transfer relationship."
        self.assertEqual(QA.evaluate(contract)["status"], "pass")
        contract.pop("structuralSupportWaiverReason")
        self.assertEqual(QA.evaluate(contract)["status"], "failed")

        contract = build_contract()
        contract["structuralSupportMode"] = "not_applicable"
        contract["structuralSupportBindings"] = []
        contract["structuralSupportWaiverReason"] = "Architecture cannot silently waive its support transfer evidence."
        self.assertEqual(QA.evaluate(contract)["status"], "failed")

    def test_future_reservation_intrusion_and_real_box_collision_are_rejected(self) -> None:
        contract = build_contract()
        compact = contract["annotationLayout"]["viewports"][1]
        compact["reservations"][1].update({"leftPx": 150.0, "rightPx": 350.0})
        compact["boxes"][1].update({"leftPx": 160.0, "rightPx": 300.0})
        compact["boxes"][2].update(
            {
                "leftPx": compact["boxes"][1]["leftPx"],
                "topPx": compact["boxes"][1]["topPx"],
                "rightPx": compact["boxes"][1]["rightPx"],
                "bottomPx": compact["boxes"][1]["bottomPx"],
                "textHeightPx": 8.0,
            }
        )
        compact["boxes"][3]["rightPx"] = 1300.0
        result = QA.evaluate(contract)
        check = result["checks"]["forward_annotation_reservation_dual_viewport"]
        self.assertFalse(check["pass"])
        failures = check["evidence"]["failures"]
        self.assertTrue(any("foreign" in value or "future" in value for value in failures))
        self.assertTrue(any("collide" in value for value in failures))
        self.assertTrue(any("clipped" in value for value in failures))

    def test_reported_counts_do_not_replace_derived_annotation_checks(self) -> None:
        contract = build_contract()
        compact = contract["annotationLayout"]["viewports"][1]
        compact["collisionCount"] = 0
        compact["clippedCount"] = 0
        compact["horizontalOverflowPx"] = 0
        compact["boxes"][0]["reservationId"] = compact["reservations"][2]["id"]
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["forward_annotation_reservation_dual_viewport"]["pass"])

        contract = build_contract()
        compact = contract["annotationLayout"]["viewports"][1]
        compact["boxes"][1]["ownerId"] = compact["boxes"][0]["ownerId"]
        compact["boxes"][1]["reservationId"] = compact["boxes"][0]["reservationId"]
        compact["boxes"][1]["stage"] = compact["boxes"][0]["stage"]
        for key in ("leftPx", "topPx", "rightPx", "bottomPx"):
            compact["boxes"][1][key] = compact["boxes"][0][key]
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["forward_annotation_reservation_dual_viewport"]["pass"])

        contract = build_contract()
        for viewport in contract["annotationLayout"]["viewports"]:
            viewport["reservations"] = [viewport["reservations"][-1]]
            viewport["boxes"] = [viewport["boxes"][-1]]
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["forward_annotation_reservation_dual_viewport"]["pass"])

    def test_pick_is_input_order_independent_typed_and_document_scoped(self) -> None:
        contract = build_contract()
        contract["selectionArbitration"]["qaCases"][0]["candidates"].reverse()
        result = QA.evaluate(contract)
        check = result["checks"]["semantic_distance_pick_arbitration"]
        self.assertTrue(check["pass"])
        self.assertEqual(check["evidence"]["cases"][0]["derivedCycle"], ["WALL-1", "DIM-1", "GRID-1"])

        contract["selectionArbitration"]["qaCases"][0]["candidates"][0]["semanticPriority"] = 999
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["semantic_distance_pick_arbitration"]["pass"])

    def test_empty_evidence_and_duplicate_input_hash_ids_fail(self) -> None:
        contract = build_contract()
        contract["selectionArbitration"]["qaCases"] = []
        self.assertEqual(QA.evaluate(contract)["status"], "failed")

        contract = build_contract()
        contract["inputHashes"][1]["id"] = contract["inputHashes"][0]["id"]
        result = QA.evaluate(contract)
        self.assertFalse(result["checks"]["input_hash_ids_unique"]["pass"])

    def test_rule_inventory_points_only_to_canonical_qa(self) -> None:
        rules = json.loads((PLUGIN / "rules" / "cad_normative_quality_rules.json").read_text(encoding="utf-8"))
        self.assertEqual([row["id"] for row in rules["rules"]], [f"CAD-Q{index:03d}" for index in range(1, 8)])
        self.assertEqual(rules["qaTool"], "scripts/aicad_normative_quality_qa.py")
        self.assertTrue(rules["externalReleaseVerifierRequired"])


if __name__ == "__main__":
    unittest.main()
