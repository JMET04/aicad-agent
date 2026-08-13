from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_production_readiness_qa_v3.py"
SPEC = importlib.util.spec_from_file_location("aicad_production_readiness_qa_v3", SCRIPT)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)
RULES = json.loads((ROOT / "rules" / "production_readiness_rules.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "rules" / "production_readiness_contract_v3.schema.json").read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put_pointer(document: dict, pointer: str, value: object) -> None:
    current = document
    tokens = pointer.lstrip("/").split("/")
    for token in tokens[:-1]:
        current = current.setdefault(token, {})
    current[tokens[-1]] = value


class Fixture:
    def __init__(self, root: Path, discipline: str) -> None:
        self.root = root
        self.discipline = discipline
        self.profile = RULES[
            "mechanicalManufacturingProfileV3"
            if discipline == "mechanical"
            else "electronicsFabricationProfileV3"
        ]
        self.closure_profile = RULES["artifactClosureProfilesV3"][discipline]
        if discipline == "mechanical":
            self.subjects = [
                {"partId": "BODY", "subjectType": "manufactured_part", "revision": "A"},
                {"partId": "CARRIER", "subjectType": "manufactured_part", "revision": "A"},
                {"partId": "ASSEMBLY", "subjectType": "mechanical_assembly", "revision": "A"},
            ]
        else:
            self.subjects = [
                {"partId": "PCB-001", "subjectType": "pcb_design", "revision": "A"},
            ]
        self.subject_by_id = {row["partId"]: row for row in self.subjects}
        artifacts_dir = root / "artifacts"
        artifacts_dir.mkdir(parents=True)
        self.artifacts: list[dict] = []
        self.expected: list[dict] = []
        self.artifact_rows: list[dict] = []

        def add(kind: str, suffix: str, part_id: str | None = None) -> dict:
            stem = f"{part_id or 'PACKAGE'}-{kind}-{suffix}".lower()
            artifact_id = stem.replace("_", "-")
            extension = {
                "mechanical_bom": ".json",
                "product_structure_manifest": ".json",
                "kicad_board": ".kicad_pcb",
                "native_board_inventory": ".json",
                "cam_output_manifest": ".json",
            }.get(kind, ".fixture")
            path = artifacts_dir / f"{stem}{extension}"
            path.write_bytes(f"{discipline}:{part_id}:{kind}:{suffix}".encode())
            relative = path.relative_to(root).as_posix()
            revision = self.subject_by_id[part_id]["revision"] if part_id else "A"
            candidate = {
                "artifactId": artifact_id,
                "kind": kind,
                "path": relative,
                "revision": revision,
                "sha256": sha(path),
            }
            expected = {
                "artifactId": artifact_id,
                "kind": kind,
                "path": relative,
                "revision": revision,
            }
            subject_type = None
            if part_id is not None:
                candidate["partId"] = part_id
                expected["partId"] = part_id
                subject_type = self.subject_by_id[part_id]["subjectType"]
            self.artifacts.append(candidate)
            self.expected.append(expected)
            self.artifact_rows.append({
                "artifactId": artifact_id,
                "kind": kind,
                "partId": part_id,
                "subjectType": subject_type,
                "revision": revision,
                "path": relative,
                "actualSha256": candidate["sha256"],
                "sizeBytes": path.stat().st_size,
                "pass": True,
            })
            return candidate

        def rewrite_text(artifact_id: str, content: str) -> None:
            candidate = next(row for row in self.artifacts if row["artifactId"] == artifact_id)
            path = root / candidate["path"]
            path.write_text(content, encoding="utf-8")
            digest = sha(path)
            candidate["sha256"] = digest
            artifact_row = next(
                row for row in self.artifact_rows if row["artifactId"] == artifact_id
            )
            artifact_row["actualSha256"] = digest
            artifact_row["sizeBytes"] = path.stat().st_size

        def rewrite_json(artifact_id: str, document: dict) -> None:
            rewrite_text(
                artifact_id, json.dumps(document, ensure_ascii=False, sort_keys=True)
            )

        if discipline == "mechanical":
            for subject in self.subjects:
                for kind in self.closure_profile["perSubjectRequiredKinds"][subject["subjectType"]]:
                    add(kind, "source", subject["partId"])
            for kind in self.closure_profile["packageRequiredKinds"]:
                add(kind, "package")
            bom_subject_rows = [
                {
                    "partId": subject["partId"],
                    "subjectType": subject["subjectType"],
                    "revision": subject["revision"],
                    "quantity": 1,
                    "artifactIds": sorted(
                        row["artifactId"] for row in self.artifacts
                        if row.get("partId") == subject["partId"]
                    ),
                }
                for subject in self.subjects
            ]
            machine_bom = next(
                row for row in self.artifacts if row["kind"] == "mechanical_bom"
            )
            rewrite_json(machine_bom["artifactId"], {
                "schema": "aicad_machine_mechanical_bom_v1",
                "discipline": "mechanical",
                "subjectRows": copy.deepcopy(bom_subject_rows),
            })
            manifest = next(
                row for row in self.artifacts if row["kind"] == "product_structure_manifest"
            )
            rewrite_json(manifest["artifactId"], {
                "schema": "aicad_product_structure_manifest_v1",
                "discipline": "mechanical",
                "artifactSubjects": copy.deepcopy(self.subjects),
                "mechanicalBomSha256ByArtifactId": {
                    row["artifactId"]: row["sha256"]
                    for row in self.artifacts
                    if row["kind"] == "mechanical_bom" and row.get("partId") is None
                },
                "bomSubjectRows": copy.deepcopy(bom_subject_rows),
            })
        else:
            subject = self.subjects[0]
            for kind in self.closure_profile["perSubjectRequiredKinds"][subject["subjectType"]]:
                add(kind, "source", subject["partId"])
            for layer in ("f-cu", "in1-cu", "in2-cu", "b-cu"):
                add("gerber_layer", layer, subject["partId"])
            for drill in ("pth", "npth"):
                add("drill", drill, subject["partId"])
            for kind in self.closure_profile["packageRequiredKinds"]:
                if kind not in {"gerber_layer", "drill"}:
                    add(kind, "package")
            board = next(
                row for row in self.artifacts if row["kind"] == "kicad_board"
            )
            rewrite_text(board["artifactId"], """(kicad_pcb
  (version 20240108)
  (generator pcbnew)
  (layers
    (0 \"F.Cu\" signal)
    (2 \"In1.Cu\" power)
    (4 \"In2.Cu\" power)
    (31 \"B.Cu\" signal))
  (footprint \"fixture\"
    (layer \"F.Cu\")
    (pad \"1\" thru_hole circle
      (at 0 0) (size 2 2) (drill 1) (layers \"*.Cu\" \"*.Mask\"))
    (pad \"\" np_thru_hole circle
      (at 5 0) (size 3 3) (drill 3) (layers \"*.Cu\" \"*.Mask\"))))
""")
            board_inventory = next(
                row for row in self.artifacts if row["kind"] == "native_board_inventory"
            )
            rewrite_json(board_inventory["artifactId"], {
                "schema": "aicad_native_board_fabrication_inventory_v1",
                "discipline": "electronics",
                "partId": subject["partId"],
                "revision": subject["revision"],
                "kicadBoardSha256ByArtifactId": {
                    row["artifactId"]: row["sha256"]
                    for row in self.artifacts
                    if row["kind"] == "kicad_board"
                    and row.get("partId") == subject["partId"]
                },
                "copperLayers": ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"],
                "designDrillRequirements": {"plated": True, "nonPlated": True},
            })
            cam_manifest = next(
                row for row in self.artifacts if row["kind"] == "cam_output_manifest"
            )
            rewrite_json(cam_manifest["artifactId"], {
                "schema": "aicad_cam_output_manifest_v1",
                "discipline": "electronics",
                "partId": subject["partId"],
                "revision": subject["revision"],
                "gerberLayers": [
                    {
                        "artifactId": row["artifactId"],
                        "sha256": row["sha256"],
                        "layerName": layer_name,
                    }
                    for row, layer_name in zip(
                        [item for item in self.artifacts if item["kind"] == "gerber_layer"],
                        ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
                        strict=True,
                    )
                ],
                "drillOutputs": [
                    {
                        "artifactId": row["artifactId"],
                        "sha256": row["sha256"],
                        "drillType": "non_plated" if "npth" in row["artifactId"] else "plated",
                    }
                    for row in self.artifacts
                    if row["kind"] == "drill" and row.get("partId") == subject["partId"]
                ],
                "jobFileSha256ByArtifactId": {
                    row["artifactId"]: row["sha256"]
                    for row in self.artifacts
                    if row["kind"] == "job_file" and row.get("partId") == subject["partId"]
                },
                "designDrillRequirements": {"plated": True, "nonPlated": True},
            })

        self.artifact_set_sha = QA._artifact_set_sha(self.artifact_rows)
        self.document: dict = {
            "artifactSetSha256": self.artifact_set_sha,
            "release": {
                "reviewer": {
                    "name": "Fixture reviewer",
                    "credential": "FIXTURE-ONLY",
                    "scope": discipline,
                },
                "record": {
                    "id": "FIXTURE-REVIEW-1",
                    "signatureType": "recorded-not-cryptographically-verified",
                    "signatureValue": "fixture-record",
                },
            },
        }
        for gates in self.profile.values():
            for gate in gates.values():
                predicate = gate.get("predicate")
                if predicate == "non_empty_string":
                    value: object = "KiCad fixture version"
                elif predicate == "artifact_sha256_map":
                    selected = QA._selector_rows(self.artifact_rows, gate["artifactSelector"])
                    value = {row["artifactId"]: row["actualSha256"] for row in selected}
                elif predicate == "artifact_true_map":
                    selected = QA._selector_rows(self.artifact_rows, gate["artifactSelector"])
                    value = {row["artifactId"]: True for row in selected}
                else:
                    value = copy.deepcopy(gate["expectedValue"])
                put_pointer(self.document, gate["jsonPointer"], value)

        evidence_dir = root / "evidence"
        evidence_dir.mkdir()
        self.report_paths: dict[str, Path] = {}
        kinds = {gate["kind"] for gates in self.profile.values() for gate in gates.values()}
        for kind in kinds:
            path = evidence_dir / f"{kind}.json"
            path.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
            self.report_paths[kind] = path
        evidence: dict = {}
        for group, gates in self.profile.items():
            evidence[group] = {}
            for name, gate in gates.items():
                path = self.report_paths[gate["kind"]]
                evidence[group][name] = {"evidenceRef": {
                    "kind": gate["kind"],
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha(path),
                }}
        self.contract = {
            "schema": "aicad_production_readiness_contract_v3",
            "project": {"id": f"fixture-{discipline}", "title": f"Fixture {discipline}"},
            "requestedStage": "manufacturing" if discipline == "mechanical" else "fabrication",
            "discipline": discipline,
            "strictProductionOnly": True,
            "evidence": evidence,
            "artifactSubjects": copy.deepcopy(self.subjects),
            "expectedArtifactClosure": copy.deepcopy(self.expected),
            "candidateArtifacts": copy.deepcopy(self.artifacts),
            "safetyLocks": {
                "reviewOnly": True,
                "accepted": False,
                "ruleEnabled": False,
                "packagingGated": True,
                "comparativeSuperiorityClaimAllowed": False,
            },
        }

    def set_gate_value(self, group: str, name: str, value: object) -> None:
        gate = self.profile[group][name]
        kind = gate["kind"]
        path = self.report_paths[kind]
        document = json.loads(path.read_text(encoding="utf-8"))
        put_pointer(document, gate["jsonPointer"], value)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        digest = sha(path)
        for gates in self.contract["evidence"].values():
            for record in gates.values():
                if record["evidenceRef"]["kind"] == kind:
                    record["evidenceRef"]["sha256"] = digest

    def artifact(self, kind: str, part_id: str | None = None, occurrence: int = 0) -> dict:
        matches = [
            row for row in self.contract["candidateArtifacts"]
            if row["kind"] == kind and row.get("partId") == part_id
        ]
        return matches[occurrence]

    def remove_artifact(self, artifact_id: str, remove_expected: bool = False) -> None:
        self.contract["candidateArtifacts"] = [
            row for row in self.contract["candidateArtifacts"]
            if row["artifactId"] != artifact_id
        ]
        if remove_expected:
            self.contract["expectedArtifactClosure"] = [
                row for row in self.contract["expectedArtifactClosure"]
                if row["artifactId"] != artifact_id
            ]

    def rewrite_candidate_json(self, artifact_id: str, document: dict) -> None:
        candidate = next(
            row for row in self.contract["candidateArtifacts"]
            if row["artifactId"] == artifact_id
        )
        path = self.root / candidate["path"]
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        candidate["sha256"] = sha(path)


class ProductionReadinessV3Tests(unittest.TestCase):
    def fixture(self, discipline: str) -> tuple[tempfile.TemporaryDirectory, Fixture]:
        temp = tempfile.TemporaryDirectory(dir=ROOT)
        return temp, Fixture(Path(temp.name), discipline)

    def test_schema_and_complete_profiles_are_evidence_contracts_not_readiness_or_authorization(self) -> None:
        Draft202012Validator.check_schema(SCHEMA)
        for discipline in ("mechanical", "electronics"):
            with self.subTest(discipline=discipline):
                temp, fixture = self.fixture(discipline)
                try:
                    result = QA.evaluate(fixture.contract, fixture.root)
                    self.assertEqual("evidence_contract_ready", result["status"])
                    self.assertTrue(result["evidenceContractReady"])
                    self.assertEqual([], result["evidenceContractFailedGates"])
                    self.assertFalse(result["independentEvidenceAuthenticityVerified"])
                    self.assertFalse(result["nativeExecutionReplayedByThisQA"])
                    self.assertFalse(result["technicalPackageReady"])
                    self.assertFalse(result["productionCandidateDeliverable"])
                    self.assertEqual([], result["exposedArtifacts"])
                    self.assertFalse(result["productionReleaseEligible"])
                    self.assertFalse(result["manufacturingAuthorized"])
                    self.assertFalse(result["fabricationAuthorized"])
                    self.assertFalse(result["safetyLocks"]["comparativeSuperiorityClaimAllowed"])
                finally:
                    temp.cleanup()

    def test_release_evidence_is_separate_and_non_authorizing(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            fixture.set_gate_value("release", "recordedApprovalSignaturePresent", False)
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertTrue(result["evidenceContractReady"])
            self.assertEqual([], result["evidenceContractFailedGates"])
            self.assertIn(
                "release.recordedApprovalSignaturePresent",
                result["recordedApprovalEvidenceFailedGates"],
            )
            self.assertFalse(result["recordedApprovalEvidencePresentAndHashBound"])
            self.assertFalse(result["technicalPackageReady"])
            self.assertFalse(result["productionReleaseEligible"])
            markdown = QA.render_markdown(result)
            self.assertIn("Recorded approval evidence not complete", markdown)
            self.assertNotIn("Blocking evidence-contract gates", markdown)
        finally:
            temp.cleanup()

    def test_each_non_release_gate_is_non_compensatory(self) -> None:
        for discipline in ("mechanical", "electronics"):
            temp = tempfile.TemporaryDirectory(dir=ROOT)
            try:
                for group, gates in RULES[
                    "mechanicalManufacturingProfileV3"
                    if discipline == "mechanical"
                    else "electronicsFabricationProfileV3"
                ].items():
                    if group == "release":
                        continue
                    for name, gate in gates.items():
                        with self.subTest(discipline=discipline, gate=f"{group}.{name}"):
                            fixture = Fixture(Path(temp.name) / f"case-{group}-{name}", discipline)
                            predicate = gate.get("predicate")
                            expected = gate["expectedValue"]
                            if predicate == "non_empty_string":
                                bad: object = "   "
                            elif predicate == "artifact_sha256_map":
                                current = copy.deepcopy(QA._pointer(fixture.document, gate["jsonPointer"]))
                                current.pop(next(iter(current)))
                                bad = current
                            elif predicate == "artifact_true_map":
                                current = copy.deepcopy(QA._pointer(fixture.document, gate["jsonPointer"]))
                                current[next(iter(current))] = False
                                bad = current
                            elif predicate == "contains_expected_rows":
                                bad = copy.deepcopy(expected[1:])
                            elif expected == 100:
                                bad = 99
                            elif expected == 0:
                                bad = 1
                            elif expected == []:
                                bad = ["waiver"]
                            elif expected is True:
                                bad = False
                            else:
                                bad = None
                            fixture.set_gate_value(group, name, bad)
                            result = QA.evaluate(fixture.contract, fixture.root)
                            self.assertFalse(result["evidenceContractReady"])
                            self.assertIn(f"{group}.{name}", result["evidenceContractFailedGates"])
                            self.assertFalse(result["technicalPackageReady"])
            finally:
                temp.cleanup()

    def test_repeated_mechanical_kinds_are_granular_and_pass(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertTrue(result["evidenceContractReady"])
            for kind in ("native_cad", "neutral_step", "manufacturing_drawing"):
                rows = [row for row in fixture.contract["candidateArtifacts"] if row["kind"] == kind]
                self.assertEqual(3, len(rows))
                self.assertEqual({"BODY", "CARRIER", "ASSEMBLY"}, {row["partId"] for row in rows})
        finally:
            temp.cleanup()

    def test_missing_carrier_cad_step_or_drawing_blocks_even_if_expected_list_is_also_trimmed(self) -> None:
        for kind in ("native_cad", "neutral_step", "manufacturing_drawing"):
            with self.subTest(kind=kind):
                temp, fixture = self.fixture("mechanical")
                try:
                    row = fixture.artifact(kind, "CARRIER")
                    fixture.remove_artifact(row["artifactId"], remove_expected=True)
                    result = QA.evaluate(fixture.contract, fixture.root)
                    closure = result["gateResults"][
                        "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
                    ]["evidence"]["closureFailures"]
                    self.assertIn(f"subject_required_kind_missing:CARRIER:{kind}", closure)
                    self.assertFalse(result["evidenceContractReady"])
                finally:
                    temp.cleanup()

    def test_multiple_manufactured_parts_require_assembly_subject_and_its_three_sources(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            fixture.contract["artifactSubjects"] = [
                row for row in fixture.contract["artifactSubjects"]
                if row["partId"] != "ASSEMBLY"
            ]
            assembly_ids = {
                row["artifactId"] for row in fixture.contract["candidateArtifacts"]
                if row.get("partId") == "ASSEMBLY"
            }
            fixture.contract["candidateArtifacts"] = [
                row for row in fixture.contract["candidateArtifacts"]
                if row["artifactId"] not in assembly_ids
            ]
            fixture.contract["expectedArtifactClosure"] = [
                row for row in fixture.contract["expectedArtifactClosure"]
                if row["artifactId"] not in assembly_ids
            ]
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertIn("multi_part_package_missing_mechanical_assembly_subject", failures)
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_product_structure_manifest_blocks_simultaneous_carrier_subject_and_artifact_omission(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            fixture.contract["artifactSubjects"] = [
                row for row in fixture.contract["artifactSubjects"] if row["partId"] != "CARRIER"
            ]
            carrier_ids = {
                row["artifactId"] for row in fixture.contract["candidateArtifacts"]
                if row.get("partId") == "CARRIER"
            }
            fixture.contract["candidateArtifacts"] = [
                row for row in fixture.contract["candidateArtifacts"]
                if row["artifactId"] not in carrier_ids
            ]
            fixture.contract["expectedArtifactClosure"] = [
                row for row in fixture.contract["expectedArtifactClosure"]
                if row["artifactId"] not in carrier_ids
            ]
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(item.startswith("product_structure_subject_set_mismatch:") for item in failures))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_product_structure_bom_rows_cannot_omit_carrier_while_subjects_and_artifacts_remain(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            manifest = fixture.artifact("product_structure_manifest")
            path = fixture.root / manifest["path"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["bomSubjectRows"] = [
                row for row in document["bomSubjectRows"]
                if row["partId"] != "CARRIER"
            ]
            fixture.rewrite_candidate_json(manifest["artifactId"], document)
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(
                item.startswith("product_structure_bom_subject_rows_mismatch:")
                for item in failures
            ))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_parsed_machine_bom_cannot_omit_carrier_while_manifest_still_declares_it(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            machine_bom = fixture.artifact("mechanical_bom")
            bom_path = fixture.root / machine_bom["path"]
            bom_document = json.loads(bom_path.read_text(encoding="utf-8"))
            bom_document["subjectRows"] = [
                row for row in bom_document["subjectRows"] if row["partId"] != "CARRIER"
            ]
            fixture.rewrite_candidate_json(machine_bom["artifactId"], bom_document)
            manifest = fixture.artifact("product_structure_manifest")
            manifest_path = fixture.root / manifest["path"]
            manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_document["mechanicalBomSha256ByArtifactId"] = {
                machine_bom["artifactId"]: machine_bom["sha256"]
            }
            fixture.rewrite_candidate_json(manifest["artifactId"], manifest_document)
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(
                item.startswith("mechanical_bom_subject_rows_mismatch:")
                for item in failures
            ))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_expected_closure_and_candidates_are_an_exact_bijection(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            missing = fixture.artifact("native_cad", "CARRIER")
            fixture.remove_artifact(missing["artifactId"])
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertIn(f"expected_artifact_missing:{missing['artifactId']}", failures)
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_duplicate_artifact_id_and_casefolded_path_are_rejected_while_kind_repetition_is_allowed(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            first, second = fixture.contract["candidateArtifacts"][:2]
            second["artifactId"] = first["artifactId"]
            second["path"] = first["path"].upper()
            result = QA.evaluate(fixture.contract, fixture.root)
            duplicates = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["duplicateIdentityOrPath"]
            self.assertTrue(any(item.startswith("artifactId:") for item in duplicates))
            self.assertTrue(any(item.startswith("path:") for item in duplicates))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_duplicate_subject_id_and_unknown_expected_part_id_are_rejected(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            fixture.contract["artifactSubjects"][1]["partId"] = "body"
            fixture.contract["expectedArtifactClosure"][0]["partId"] = "UNKNOWN"
            result = QA.evaluate(fixture.contract, fixture.root)
            evidence = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]
            self.assertTrue(any(item.startswith("partId:") for item in evidence["duplicateIdentityOrPath"]))
            self.assertTrue(any(
                item.startswith("expected_artifact_part_id_not_declared:")
                for item in evidence["closureFailures"]
            ))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_part_id_swap_and_hash_swap_each_fail_closed(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            body = fixture.artifact("native_cad", "BODY")
            carrier = fixture.artifact("native_cad", "CARRIER")
            body["partId"], carrier["partId"] = carrier["partId"], body["partId"]
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(item.startswith("expected_artifact_identity_mismatch:") for item in failures))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

        temp, fixture = self.fixture("mechanical")
        try:
            body = fixture.artifact("native_cad", "BODY")
            carrier = fixture.artifact("native_cad", "CARRIER")
            body["sha256"], carrier["sha256"] = carrier["sha256"], body["sha256"]
            result = QA.evaluate(fixture.contract, fixture.root)
            artifact_rows = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["artifacts"]
            self.assertGreaterEqual(sum(not row["pass"] for row in artifact_rows), 2)
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_source_hash_map_must_bind_every_selected_artifact_id(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            gate = fixture.profile["verification"]["nativeCadSourceHashBinding"]
            current = copy.deepcopy(QA._pointer(fixture.document, gate["jsonPointer"]))
            current.pop(next(key for key in current if "carrier" in key))
            fixture.set_gate_value("verification", "nativeCadSourceHashBinding", current)
            result = QA.evaluate(fixture.contract, fixture.root)
            row = result["gateResults"]["verification.nativeCadSourceHashBinding"]
            required_map = row["evidence"]["expectedValue"]["requiredArtifactSha256ById"]
            self.assertEqual(3, len(required_map))
            self.assertEqual("fail", row["status"])
        finally:
            temp.cleanup()

    def test_native_reopen_map_is_per_artifact_not_one_boolean(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            gate = fixture.profile["host"]["nativeCadSaveReopen"]
            current = copy.deepcopy(QA._pointer(fixture.document, gate["jsonPointer"]))
            current[next(key for key in current if "carrier" in key)] = False
            fixture.set_gate_value("host", "nativeCadSaveReopen", current)
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertIn("host.nativeCadSaveReopen", result["evidenceContractFailedGates"])
        finally:
            temp.cleanup()

    def test_electronics_keeps_granular_gerber_and_drill_files(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertTrue(result["evidenceContractReady"])
            self.assertEqual(
                4,
                sum(row["kind"] == "gerber_layer" for row in fixture.contract["candidateArtifacts"]),
            )
            self.assertEqual(
                2,
                sum(row["kind"] == "drill" for row in fixture.contract["candidateArtifacts"]),
            )
            self.assertFalse(any(row["kind"] == "gerber_archive" for row in fixture.contract["candidateArtifacts"]))
        finally:
            temp.cleanup()

    def test_missing_declared_gerber_or_drill_and_swapped_cam_hashes_fail(self) -> None:
        for kind in ("gerber_layer", "drill"):
            with self.subTest(kind=kind):
                temp, fixture = self.fixture("electronics")
                try:
                    row = fixture.artifact(kind, "PCB-001")
                    fixture.remove_artifact(row["artifactId"])
                    result = QA.evaluate(fixture.contract, fixture.root)
                    failures = result["gateResults"][
                        "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
                    ]["evidence"]["closureFailures"]
                    self.assertIn(f"expected_artifact_missing:{row['artifactId']}", failures)
                    self.assertFalse(result["evidenceContractReady"])
                finally:
                    temp.cleanup()

        temp, fixture = self.fixture("electronics")
        try:
            first = fixture.artifact("gerber_layer", "PCB-001", occurrence=0)
            second = fixture.artifact("gerber_layer", "PCB-001", occurrence=1)
            first["sha256"], second["sha256"] = second["sha256"], first["sha256"]
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_cam_manifest_blocks_simultaneous_expected_and_candidate_output_omission(self) -> None:
        cases = (("gerber_layer", 1, "cam_manifest_gerber_set_mismatch:"),
                 ("drill", 1, "cam_manifest_drill_set_mismatch:"))
        for kind, occurrence, expected_failure in cases:
            with self.subTest(kind=kind):
                temp, fixture = self.fixture("electronics")
                try:
                    row = fixture.artifact(kind, "PCB-001", occurrence=occurrence)
                    fixture.remove_artifact(row["artifactId"], remove_expected=True)
                    result = QA.evaluate(fixture.contract, fixture.root)
                    failures = result["gateResults"][
                        "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
                    ]["evidence"]["closureFailures"]
                    self.assertTrue(any(item.startswith(expected_failure) for item in failures))
                    self.assertFalse(result["evidenceContractReady"])
                finally:
                    temp.cleanup()

    def test_cam_manifest_requires_non_plated_output_when_design_declares_it(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            row = fixture.artifact("drill", "PCB-001", occurrence=1)
            fixture.remove_artifact(row["artifactId"], remove_expected=True)
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(item.startswith("cam_manifest_non_plated_output_missing:") for item in failures))
        finally:
            temp.cleanup()

    def test_parsed_board_blocks_npth_omission_even_if_both_candidate_manifests_are_weakened(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            npth = fixture.artifact("drill", "PCB-001", occurrence=1)
            fixture.remove_artifact(npth["artifactId"], remove_expected=True)
            board_inventory = fixture.artifact("native_board_inventory", "PCB-001")
            inventory_path = fixture.root / board_inventory["path"]
            inventory_document = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory_document["designDrillRequirements"]["nonPlated"] = False
            fixture.rewrite_candidate_json(board_inventory["artifactId"], inventory_document)
            cam_manifest = fixture.artifact("cam_output_manifest", "PCB-001")
            path = fixture.root / cam_manifest["path"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["designDrillRequirements"]["nonPlated"] = False
            document["drillOutputs"] = [
                row for row in document["drillOutputs"]
                if row["artifactId"] != npth["artifactId"]
            ]
            fixture.rewrite_candidate_json(cam_manifest["artifactId"], document)
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(
                item.startswith("cam_manifest_board_drill_requirements_mismatch:")
                for item in failures
            ))
            self.assertTrue(any(
                item.startswith("cam_manifest_non_plated_output_missing:")
                for item in failures
            ))
            self.assertTrue(any(
                item.startswith("native_board_inventory_native_parse_mismatch:")
                for item in failures
            ))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_parsed_board_blocks_copper_layer_omission_even_if_candidate_inventories_are_weakened(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            copper = fixture.artifact("gerber_layer", "PCB-001", occurrence=1)
            fixture.remove_artifact(copper["artifactId"], remove_expected=True)
            board_inventory = fixture.artifact("native_board_inventory", "PCB-001")
            inventory_path = fixture.root / board_inventory["path"]
            inventory_document = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory_document["copperLayers"] = [
                layer for layer in inventory_document["copperLayers"] if layer != "In1.Cu"
            ]
            fixture.rewrite_candidate_json(board_inventory["artifactId"], inventory_document)
            cam_manifest = fixture.artifact("cam_output_manifest", "PCB-001")
            cam_path = fixture.root / cam_manifest["path"]
            cam_document = json.loads(cam_path.read_text(encoding="utf-8"))
            cam_document["gerberLayers"] = [
                row for row in cam_document["gerberLayers"]
                if row["artifactId"] != copper["artifactId"]
            ]
            fixture.rewrite_candidate_json(cam_manifest["artifactId"], cam_document)
            result = QA.evaluate(fixture.contract, fixture.root)
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            self.assertTrue(any(
                item.startswith("native_board_inventory_native_parse_mismatch:")
                for item in failures
            ))
            self.assertTrue(any(
                item.startswith("cam_manifest_board_copper_layer_set_mismatch:")
                for item in failures
            ))
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_artifact_set_digest_binds_id_part_revision_path_size_and_hash(self) -> None:
        base = [{
            "artifactId": "body-cad",
            "kind": "native_cad",
            "partId": "BODY",
            "subjectType": "manufactured_part",
            "revision": "A",
            "path": "a/part.sldprt",
            "actualSha256": "a" * 64,
            "sizeBytes": 10,
        }]
        slash = copy.deepcopy(base)
        slash[0]["path"] = "a\\part.sldprt"
        self.assertEqual(QA._artifact_set_sha(base), QA._artifact_set_sha(slash))
        for key, value in (
            ("artifactId", "carrier-cad"),
            ("partId", "CARRIER"),
            ("revision", "B"),
            ("path", "b/part.sldprt"),
            ("sizeBytes", 11),
            ("actualSha256", "b" * 64),
        ):
            changed = copy.deepcopy(base)
            changed[0][key] = value
            self.assertNotEqual(QA._artifact_set_sha(base), QA._artifact_set_sha(changed), key)

    def test_artifact_set_mismatch_blocks_all_bound_evidence(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            path = fixture.report_paths["native_host_report"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["artifactSetSha256"] = "0" * 64
            path.write_text(json.dumps(document), encoding="utf-8")
            digest = sha(path)
            for gates in fixture.contract["evidence"].values():
                for record in gates.values():
                    if record["evidenceRef"]["kind"] == "native_host_report":
                        record["evidenceRef"]["sha256"] = digest
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertFalse(result["evidenceContractReady"])
            self.assertTrue(any(
                row["evidence"].get("reason") == "evidence_artifact_set_mismatch"
                for row in result["gateResults"].values()
            ))
        finally:
            temp.cleanup()

    def test_standard_rows_are_required_subsets_and_allow_authority_metadata(self) -> None:
        for discipline in ("mechanical", "electronics"):
            with self.subTest(discipline=discipline):
                temp, fixture = self.fixture(discipline)
                try:
                    required = copy.deepcopy(
                        fixture.profile["intent"]["currentStandardsLedger"]["expectedValue"]
                    )
                    enriched = [
                        {**row, "authorityUrl": f"https://authority.invalid/{index}"}
                        for index, row in enumerate(required)
                    ]
                    enriched.append({
                        "standard": "PROJECT-SPEC-001",
                        "status": "project",
                        "applicability": "project-specific addition",
                        "authorityUrl": "https://authority.invalid/project",
                    })
                    fixture.set_gate_value("intent", "currentStandardsLedger", enriched)
                    self.assertTrue(QA.evaluate(fixture.contract, fixture.root)["evidenceContractReady"])

                    fixture.set_gate_value("intent", "currentStandardsLedger", enriched[1:])
                    failing = QA.evaluate(fixture.contract, fixture.root)
                    self.assertIn("intent.currentStandardsLedger", failing["evidenceContractFailedGates"])
                finally:
                    temp.cleanup()

    def test_paths_are_portable_and_cannot_escape_contract_directory(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            for field in ("candidateArtifacts", "expectedArtifactClosure"):
                for bad in ("../escape.step", "C:/outside.step", "/outside.step"):
                    with self.subTest(field=field, path=bad):
                        contract = copy.deepcopy(fixture.contract)
                        contract[field][0]["path"] = bad
                        with self.assertRaises(ValidationError):
                            Draft202012Validator(SCHEMA).validate(contract)
        finally:
            temp.cleanup()

    def test_contract_cannot_supply_rule_owned_predicates_or_expected_values(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            for key, value in (
                ("expectedValue", 99),
                ("passed", True),
                ("jsonPointer", "/caller/chosen"),
                ("artifactSelector", {"kind": "bom"}),
            ):
                with self.subTest(key=key):
                    contract = copy.deepcopy(fixture.contract)
                    contract["evidence"]["design"]["completeRouting"]["evidenceRef"][key] = value
                    with self.assertRaises(ValidationError):
                        Draft202012Validator(SCHEMA).validate(contract)
        finally:
            temp.cleanup()

    def test_extra_gate_inventory_is_rejected(self) -> None:
        temp, fixture = self.fixture("mechanical")
        try:
            fixture.contract["evidence"]["design"]["callerInventedPass"] = copy.deepcopy(
                fixture.contract["evidence"]["design"]["constraintCompile"]
            )
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertEqual("fail", result["gateResults"]["inventory.design"]["status"])
            self.assertFalse(result["evidenceContractReady"])
        finally:
            temp.cleanup()

    def test_reports_contain_only_portable_paths(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            result = QA.evaluate(fixture.contract, fixture.root)
            payload = json.dumps(result, ensure_ascii=False)
            self.assertNotIn(str(fixture.root.resolve()), payload)
            self.assertEqual("rules/production_readiness_rules.json", result["rules"]["path"])
            self.assertEqual(
                "rules/production_readiness_contract_v3.schema.json",
                result["contractSchema"]["path"],
            )
        finally:
            temp.cleanup()

    def test_all_v3_gates_are_bound_and_no_legacy_kind_only_source_binding_remains(self) -> None:
        for profile_name in ("mechanicalManufacturingProfileV3", "electronicsFabricationProfileV3"):
            for group, gates in RULES[profile_name].items():
                for name, gate in gates.items():
                    with self.subTest(profile=profile_name, gate=f"{group}.{name}"):
                        self.assertTrue(gate.get("bindArtifactSet"))
                        self.assertNotIn("sourceArtifactKind", gate)
                        if gate.get("predicate") in {"artifact_sha256_map", "artifact_true_map"}:
                            self.assertIn("artifactSelector", gate)

    def test_named_mechanical_direct_application_gates_are_persistent(self) -> None:
        profile = RULES["mechanicalManufacturingProfileV3"]
        self.assertTrue({
            "operatingEnvelopeDutyCycleAndDesignLifeAuthority",
            "assemblyConfigurationAndInterfaceAuthority",
            "safetyRegulatoryAndRiskApplicabilityResolved",
        }.issubset(profile["intent"]))
        self.assertTrue({
            "analysisInputUnitsAndProvenance",
            "analysisRecomputedFromDeclaredInputs",
            "criticalLoadPathCoverage",
            "loadCombinationAndAbnormalCaseCoverage",
            "analysisEquationInputOutputMarginTrace",
            "fastenerPreloadSlipAndCapacity",
            "bearingLife",
            "thermalEnvelope",
            "failureModesAndResidualRiskControls",
            "assemblyServiceAndToolClearance",
        }.issubset(profile["design"]))
        self.assertTrue({
            "threadsStandardPartsAndFastenerDefinition",
            "undefinedEdgesDeburrAndSharpEdgeControl",
            "assemblyBomItemRevisionAndQuantityClosure",
            "criticalCharacteristicProcessCapabilityAndMeasurementMethod",
        }.issubset(profile["manufacturingDefinition"]))
        self.assertTrue({
            "drawingFeatureBoundDimensionsDatumsFcfsFitsAndRoughness",
            "drawingVisualLegibilityCollisionScaleAndSheetClosure",
            "modelDrawingInspectionRevisionAndConfigurationIdentity",
            "nativeMaterialDatabaseAssignmentAndReadback",
            "derivedOnlyOrCustomPropertyMaterialEvidenceCount",
            "nativeCadSourceHashBinding",
            "neutralStepSourceHashBinding",
            "manufacturingDrawingSourceHashBinding",
        }.issubset(profile["verification"]))

    def test_each_pcb_owns_native_assembly_fabrication_and_cam_outputs(self) -> None:
        closure = RULES["artifactClosureProfilesV3"]["electronics"]
        required = {
            "kicad_project", "kicad_schematic", "kicad_board", "native_board_inventory",
            "job_file", "cam_output_manifest", "bom", "pick_and_place", "assembly_drawing",
            "fabrication_drawing", "schematic_pdf", "board_3d",
        }
        self.assertTrue(required.issubset(closure["perSubjectRequiredKinds"]["pcb_design"]))
        self.assertTrue(required.issubset(closure["subjectScopedKinds"]))
        self.assertTrue(required.isdisjoint(closure["packageRequiredKinds"]))
        self.assertIn("fabrication_drawing", RULES["requiredArtifactKindsV3"]["electronics"])
        self.assertIn("fabrication_drawing", SCHEMA["$defs"]["artifactKind"]["enum"])
        temp, fixture = self.fixture("electronics")
        try:
            evidence = QA.evaluate(fixture.contract, fixture.root)["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]
            self.assertEqual(closure["perSubjectRequiredKinds"], evidence["perSubjectRequiredKinds"])
            self.assertEqual(closure["subjectScopedKinds"], evidence["subjectScopedKinds"])
            self.assertEqual(closure["packageRequiredKinds"], evidence["packageRequiredKinds"])
        finally:
            temp.cleanup()

    def test_pcb_outputs_cannot_be_omitted_from_both_expected_and_candidate_closure(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            required_outputs = (
                "bom", "pick_and_place", "assembly_drawing", "fabrication_drawing",
                "schematic_pdf", "board_3d",
            )
            for kind in required_outputs:
                fixture.remove_artifact(
                    fixture.artifact(kind, "PCB-001")["artifactId"], remove_expected=True
                )
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertFalse(result["evidenceContractReady"])
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            for kind in required_outputs:
                self.assertIn(f"subject_required_kind_missing:PCB-001:{kind}", failures)
        finally:
            temp.cleanup()

    def test_second_pcb_cannot_borrow_first_pcb_outputs(self) -> None:
        temp, fixture = self.fixture("electronics")
        try:
            fixture.contract["artifactSubjects"].append({
                "partId": "PCB-002", "subjectType": "pcb_design", "revision": "A",
            })
            result = QA.evaluate(fixture.contract, fixture.root)
            self.assertFalse(result["evidenceContractReady"])
            failures = result["gateResults"][
                "artifacts.expectedClosureHashesSubjectsKindsAndUniqueness"
            ]["evidence"]["closureFailures"]
            for kind in RULES["artifactClosureProfilesV3"]["electronics"]["perSubjectRequiredKinds"]["pcb_design"]:
                self.assertIn(f"subject_required_kind_missing:PCB-002:{kind}", failures)
            for kind in ("gerber_layer", "drill"):
                self.assertIn(f"subject_required_kind_missing:PCB-002:{kind}", failures)
        finally:
            temp.cleanup()

    def test_named_electronics_direct_application_gates_are_persistent(self) -> None:
        profile = RULES["electronicsFabricationProfileV3"]
        self.assertTrue({
            "powerEnvironmentInterfacesAndAcceptanceAuthority",
            "regulatorySafetyAndEnvironmentalApplicabilityResolved",
            "productClassAssemblyClassAndAcceptanceCriteriaResolved",
            "transientAbnormalAndImmunityProfilesFrozen",
        }.issubset(profile["intent"]))
        self.assertTrue({
            "symbolPinNumberFunctionElectricalTypeParity",
            "exactOrderedMpnAndSymbolAliasResolution",
            "padNetBidirectionalParity",
            "componentRatingsDeratingAndWorstCase",
            "powerBudgetStartupSequencingAndFaultRecovery",
            "protectionCoordinationAndTransientEnergy",
            "analogAccuracyFilterClampAndAdcDriveBudget",
            "clockResetProgrammingAndProtocolConstraints",
            "groundingIsolationAndCommonModeBoundary",
            "connectorTerminalWireToolAndEnclosureAccessibility",
            "mountingFastenerHeadKeepoutAndHeightEnvelope",
        }.issubset(profile["design"]))
        self.assertTrue({
            "bomValueQuantityFootprintMpnParity",
            "solderMaskPasteSilkscreenPolarityAndFabNotes",
            "platedNonplatedDrillSlotAndCastellationSemantics",
        }.issubset(profile["manufacturingDefinition"]))
        self.assertTrue({
            "nativeSymbolPinMappingErrors",
            "nativeFootprintPadNumberMappingErrors",
            "schematicVisualLegibilityAndPageUse",
            "pcbFunctionalPlacementZonesAndAccessibility",
            "board3dEnclosureConnectorAndHeightCollision",
            "camIndependentReadbackAndLayerDrillClosure",
            "outputManifestBidirectionalClosure",
        }.issubset(profile["verification"]))

    def test_skill_text_has_no_mojibake_or_readiness_overclaim(self) -> None:
        for relative in (
            "skills/aicad-draw/SKILL.md",
            "skills/aicad-model-3d/SKILL.md",
            "README.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("paths閳", text)
            self.assertNotIn("technicalPackageReady=true", text)
            self.assertNotIn("external review and signature may complete production evidence", text)
            self.assertIn("evidenceContractReady", text)


if __name__ == "__main__":
    unittest.main()
