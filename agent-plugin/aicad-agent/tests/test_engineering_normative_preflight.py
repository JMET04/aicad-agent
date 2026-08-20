from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "scripts" / "aicad_engineering_preflight.py"
SPEC = importlib.util.spec_from_file_location("aicad_engineering_preflight", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot import engineering normative preflight")
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


def _canonical_gate_sha256(gate_path: str, gate: dict) -> str:
    payload = json.dumps(
        {"gatePath": gate_path, "canonicalGate": gate},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_evidence(root: Path, relative_path: str, payload: bytes) -> dict:
    target = root.joinpath(*relative_path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "path": relative_path,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def valid_contract(domain: str, evidence_root: Path) -> dict:
    contract = PREFLIGHT.build_template(domain)
    contract["contractId"] = f"{domain.upper()}_NORMATIVE_PREFLIGHT_EVIDENCED"
    source_files = {
        "STD_AUTHORITY": (
            f"sources/{domain}/controlled-standards.txt",
            (
                f"Controlled standards authority for {domain}; edition, scope, jurisdiction, "
                "and applicability decisions are frozen at revision STD-R1.\n"
            ).encode("utf-8"),
            "text/plain",
            "STD-R1",
            "Controlled standards edition, scope, jurisdiction, and applicability evidence.",
        ),
        "ENG_INPUT": (
            f"sources/{domain}/approved-engineering-input.json",
            json.dumps(
                {
                    "domain": domain,
                    "revision": "ENG-R1",
                    "status": "approved",
                    "basis": "Controlled design basis, interfaces, calculations, and process capability.",
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8"),
            "application/json",
            "ENG-R1",
            "Approved design basis, calculations, interfaces, and process-capability evidence.",
        ),
    }
    for source in contract["sources"]:
        relative_path, payload, media_type, revision, description = source_files[source["id"]]
        source.update(_write_evidence(evidence_root, relative_path, payload))
        source.update({
            "description": description,
            "mediaType": media_type,
            "authorityRevision": revision,
        })

    first_standard = contract["applicableStandards"][0]["standard"]
    for standard in contract["applicableStandards"]:
        standard["scopeDecision"] = (
            "Applicable to the declared controlled-generation scope and frozen authority revision."
        )

    _, _, _, inventory = PREFLIGHT._canonical_context(domain)
    for row in contract["ruleApplications"]:
        canonical_gate = inventory[row["gatePath"]]
        row["disposition"] = "constrained"
        row["requirement"] = PREFLIGHT._requirement_text(row["gatePath"], canonical_gate)
        row["canonicalGateSha256"] = _canonical_gate_sha256(row["gatePath"], canonical_gate)
        row["generationConstraint"] = (
            f"Constrain {row['gatePath']} to the cited controlled evidence before geometry generation."
        )
        row["verificationMethod"] = (
            f"Run the registered canonical rule check for {row['gatePath']} and preserve its evidence."
        )
        row["verifierId"] = "canonical_rule_check"
        row["standardIds"] = [first_standard]
    return contract


class EngineeringNormativePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = json.loads((PLUGIN / "rules" / "production_readiness_rules.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((PLUGIN / "rules" / "engineering_normative_preflight.schema.json").read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="aicad-preflight-evidence-")
        self.evidence_root = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def contract(self, domain: str) -> dict:
        return valid_contract(domain, self.evidence_root)

    def evaluate(self, contract: dict, evidence_root: Path | None = None) -> dict:
        root = self.evidence_root if evidence_root is None else evidence_root
        return PREFLIGHT.evaluate(contract, root)

    def assert_failed_with_text(self, report: dict, *fragments: str) -> None:
        self.assertEqual(report["status"], "failed", report)
        rendered = json.dumps(report.get("failures", []), ensure_ascii=False, sort_keys=True).casefold()
        for fragment in fragments:
            self.assertIn(fragment.casefold(), rendered, report)

    def test_mechanical_and_electronics_positive_contracts_pass_without_readiness_overclaim(self) -> None:
        expected = {"mechanical": 54, "electronics": 63}
        for domain, gate_count in expected.items():
            with self.subTest(domain=domain):
                contract = self.contract(domain)
                Draft202012Validator(self.schema).validate(contract)
                report = self.evaluate(contract)
                self.assertEqual(report["status"], "pass", report)
                self.assertTrue(report["checks"]["sourceFilesExistAndMatchDeclaredHashes"])
                self.assertTrue(report["checks"]["canonicalGateContentAndFingerprintMatch"])
                self.assertEqual(report["counts"]["canonicalGates"], gate_count)
                self.assertEqual(report["counts"]["contractGates"], gate_count)
                self.assertEqual(report["conclusion"], "normative_preflight_ready_for_controlled_generation_only")
                self.assertTrue(report["generationGate"]["nextStageAllowed"])
                self.assertFalse(report["generationGate"]["artifactExposureAllowed"])
                self.assertEqual(
                    report["readinessBoundary"],
                    {
                        "evidenceContractReady": False,
                        "technicalPackageReady": False,
                        "productionReleaseEligible": False,
                        "manufacturingAuthorized": False,
                        "fabricationAuthorized": False,
                    },
                )

    def test_template_is_exact_but_unresolved_and_fails_closed(self) -> None:
        for domain in ("mechanical", "electronics"):
            with self.subTest(domain=domain):
                draft = PREFLIGHT.build_template(domain)
                report = self.evaluate(draft)
                self.assertEqual(report["status"], "failed")
                self.assertFalse(report["generationGate"]["nextStageAllowed"])
                gate_failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
                self.assertEqual(len(gate_failure["details"]["unresolved"]), len(draft["ruleApplications"]))

    def test_every_canonical_generation_gate_has_an_individual_missing_gate_regression(self) -> None:
        for domain in ("mechanical", "electronics"):
            baseline = self.contract(domain)
            for index, application in enumerate(baseline["ruleApplications"]):
                with self.subTest(domain=domain, gate=application["gatePath"]):
                    candidate = copy.deepcopy(baseline)
                    del candidate["ruleApplications"][index]
                    report = self.evaluate(candidate)
                    self.assertEqual(report["status"], "failed")
                    failure = next(item for item in report["failures"] if item["code"] == "gate_inventory_mismatch")
                    self.assertEqual(failure["details"]["missing"], [application["gatePath"]])

    def test_duplicate_extra_and_cross_domain_gate_paths_fail_exact_inventory(self) -> None:
        contract = self.contract("mechanical")
        contract["ruleApplications"].append(copy.deepcopy(contract["ruleApplications"][0]))
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_inventory_mismatch")
        self.assertEqual(failure["details"]["duplicates"], [contract["ruleApplications"][0]["gatePath"]])

        contract = self.contract("mechanical")
        contract["ruleApplications"][0]["gatePath"] = "electronics.intent.wholeIntent"
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_inventory_mismatch")
        self.assertEqual(failure["details"]["extra"], ["electronics.intent.wholeIntent"])

    def test_intent_cannot_be_not_applicable_but_a_design_gate_can_with_authority(self) -> None:
        contract = self.contract("mechanical")
        shared = next(row for row in contract["ruleApplications"] if row["gatePath"].startswith("shared.rules."))
        shared["disposition"] = "not_applicable"
        shared["notApplicableRationale"] = "Approved authority attempted to waive a mandatory shared canonical gate."
        shared.pop("generationConstraint")
        report = self.evaluate(contract)
        self.assertIn("gate_application_invalid", [item["code"] for item in report["failures"]])

        contract = self.contract("mechanical")
        intent = next(row for row in contract["ruleApplications"] if ".intent." in row["gatePath"])
        intent["disposition"] = "not_applicable"
        intent["notApplicableRationale"] = "Approved authority attempted to waive a mandatory design-intent gate."
        intent.pop("generationConstraint")
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
        self.assertEqual(failure["details"]["intentMarkedNotApplicable"], [intent["gatePath"]])

        contract = self.contract("mechanical")
        fatigue = next(row for row in contract["ruleApplications"] if row["gatePath"].endswith(".fatigueApplicabilityAndResult"))
        fatigue["disposition"] = "not_applicable"
        fatigue["notApplicableRationale"] = "Approved engineering input proves no cyclic duty in the declared life envelope."
        fatigue.pop("generationConstraint")
        fatigue["verifierId"] = "authority_review"
        self.assertEqual(self.evaluate(contract)["status"], "pass")

    def test_missing_standard_wrong_standard_source_and_version_drift_fail(self) -> None:
        contract = self.contract("electronics")
        removed = contract["applicableStandards"].pop()
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "standards_ledger_incomplete")
        self.assertIn(
            (removed["standard"], removed["status"], removed["applicability"]),
            map(tuple, failure["details"]["missing"]),
        )

        contract = self.contract("electronics")
        contract["applicableStandards"][0]["sourceId"] = "ENG_INPUT"
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "standards_ledger_incomplete")
        self.assertEqual(failure["details"]["invalidStandardSource"], [contract["applicableStandards"][0]["standard"]])

        contract = self.contract("electronics")
        contract["canonicalRulesVersion"] = "999.0.0"
        report = self.evaluate(contract)
        self.assertIn("canonical_rules_identity_mismatch", [item["code"] for item in report["failures"]])

    def test_reference_only_binding_unknown_standard_unresolved_conflict_and_open_lock_fail(self) -> None:
        contract = self.contract("mechanical")
        for source_id, kind, relative_path, payload in (
            ("IMG", "reference_image", "sources/mechanical/reference-image.png", b"not-a-real-image-but-controlled-test-evidence"),
            ("CAD_REF", "reference_cad", "sources/mechanical/reference-cad.step", b"ISO-10303-21; controlled test evidence"),
        ):
            source = {
                "id": source_id,
                "kind": kind,
                "description": "Controlled reference-only evidence with no governing authority.",
                "mediaType": "application/octet-stream",
                "authorityRevision": "REF-R1",
            }
            source.update(_write_evidence(self.evidence_root, relative_path, payload))
            contract["sources"].append(source)
        row = contract["ruleApplications"][0]
        row["sourceIds"] = ["IMG", "CAD_REF"]
        row["standardIds"] = ["UNKNOWN-EDITION"]
        contract["conflicts"] = [{"id": "C1", "sourceIds": ["IMG", "ENG_INPUT"], "status": "unresolved"}]
        report = self.evaluate(contract)
        gate_failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
        self.assertEqual(gate_failure["details"]["missingAuthoritativeSourceBinding"], [row["gatePath"]])
        self.assertEqual(gate_failure["details"]["unknownStandardReferences"], [f"{row['gatePath']}:UNKNOWN-EDITION"])
        self.assertIn("unresolved_source_conflict", [item["code"] for item in report["failures"]])

        contract = self.contract("mechanical")
        contract["locks"]["manufacturingAuthorized"] = True
        report = self.evaluate(contract)
        self.assertFalse(report["checks"]["schemaValid"])
        self.assertFalse(report["generationGate"]["nextStageAllowed"])

    def test_controlled_evidence_root_is_required_and_must_exist_as_a_directory(self) -> None:
        contract = self.contract("mechanical")
        self.assert_failed_with_text(
            PREFLIGHT.evaluate(contract, None),
            "controlled_evidence_root_required",
        )

        missing_root = self.evidence_root / "root-does-not-exist"
        self.assert_failed_with_text(
            PREFLIGHT.evaluate(contract, missing_root),
            "evidence_root_missing",
        )

        root_file = self.evidence_root / "not-a-directory.txt"
        root_file.write_text("controlled file, not a root", encoding="utf-8")
        self.assert_failed_with_text(
            PREFLIGHT.evaluate(contract, root_file),
            "evidence_root_not_directory",
        )

    def test_missing_source_file_fails_even_when_declared_metadata_looks_valid(self) -> None:
        contract = self.contract("mechanical")
        source = contract["sources"][0]
        self.evidence_root.joinpath(*source["path"].split("/")).unlink()
        report = self.evaluate(contract)
        self.assert_failed_with_text(report, "source_file_missing")
        self.assertFalse(report["checks"]["sourceFilesExistAndMatchDeclaredHashes"])

    def test_absolute_traversal_and_backslash_source_paths_fail_closed(self) -> None:
        mutations = {
            "absolute": lambda source: str(
                self.evidence_root.joinpath(*source["path"].split("/")).resolve()
            ).replace("\\", "/"),
            "traversal": lambda source: f"../{Path(source['path']).name}",
            "backslash": lambda source: source["path"].replace("/", "\\"),
        }
        for label, mutate in mutations.items():
            with self.subTest(path_form=label):
                contract = self.contract("mechanical")
                source = contract["sources"][0]
                source["path"] = mutate(source)
                self.assert_failed_with_text(self.evaluate(contract), "unsafe_or_nonportable_path")

    def test_source_symlink_is_rejected_when_platform_supports_symlinks(self) -> None:
        contract = self.contract("mechanical")
        source = contract["sources"][0]
        target = self.evidence_root.joinpath(*source["path"].split("/"))
        link = target.with_name("controlled-standards-link.txt")
        try:
            os.symlink(target, link)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symlink creation unavailable on this platform: {exc}")
        source["path"] = link.relative_to(self.evidence_root).as_posix()
        self.assert_failed_with_text(self.evaluate(contract), "link_or_junction_forbidden")

    def test_content_change_after_contract_invalidates_old_size_and_hash(self) -> None:
        contract = self.contract("electronics")
        source = contract["sources"][0]
        target = self.evidence_root.joinpath(*source["path"].split("/"))
        target.write_bytes(target.read_bytes() + b"\npost-contract mutation")
        self.assert_failed_with_text(self.evaluate(contract), "size_mismatch", "sha256_mismatch")

    def test_declared_size_and_hash_must_both_match_real_content(self) -> None:
        contract = self.contract("electronics")
        contract["sources"][0]["size"] += 1
        self.assert_failed_with_text(self.evaluate(contract), "size_mismatch")

        contract = self.contract("electronics")
        contract["sources"][0]["sha256"] = "f" * 64
        self.assert_failed_with_text(self.evaluate(contract), "sha256_mismatch")

    def test_boilerplate_placeholders_cannot_masquerade_as_resolved_evidence(self) -> None:
        contract = self.contract("mechanical")
        source = contract["sources"][0]
        source["authorityRevision"] = "UNRESOLVED"
        source["mediaType"] = "unresolved/type"
        row = contract["ruleApplications"][0]
        row["generationConstraint"] = "TODO replace with an approved canonical geometry constraint before generation."
        row["verificationMethod"] = "UNRESOLVED placeholder verifier text must never satisfy this production gate."
        report = self.evaluate(contract)
        self.assert_failed_with_text(
            report,
            "authority_revision_unresolved",
            "media_type_unresolved",
            f"{row['gatePath']}:generationConstraint",
            f"{row['gatePath']}:verificationMethod",
        )

    def test_tampered_canonical_requirement_and_fingerprint_are_both_reported(self) -> None:
        contract = self.contract("mechanical")
        row = contract["ruleApplications"][0]
        row["requirement"] += " Tampered local relaxation."
        row["canonicalGateSha256"] = "0" * 64
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
        self.assertEqual(failure["details"]["canonicalRequirementMismatch"], [row["gatePath"]])
        self.assertEqual(failure["details"]["canonicalGateFingerprintMismatch"], [row["gatePath"]])
        self.assertFalse(report["checks"]["canonicalGateContentAndFingerprintMatch"])

    def test_unresolved_verifier_blocks_otherwise_complete_gate(self) -> None:
        contract = self.contract("electronics")
        row = contract["ruleApplications"][0]
        row["verifierId"] = "unresolved"
        report = self.evaluate(contract)
        failure = next(item for item in report["failures"] if item["code"] == "gate_application_invalid")
        self.assertEqual(failure["details"]["invalidVerifier"], [row["gatePath"]])

    def test_missing_required_authority_source_kind_is_non_compensatory(self) -> None:
        contract = self.contract("electronics")
        standard_source = next(row for row in contract["sources"] if row["id"] == "STD_AUTHORITY")
        standard_source["kind"] = "reference_cad"
        report = self.evaluate(contract)
        source_failure = next(item for item in report["failures"] if item["code"] == "source_inventory_invalid")
        self.assertEqual(source_failure["details"]["missingRequiredKinds"], ["selected_standard"])
        self.assertIn("standards_ledger_incomplete", [item["code"] for item in report["failures"]])
        self.assertIn("gate_application_invalid", [item["code"] for item in report["failures"]])

    def test_multiple_independent_faults_are_reported_in_one_evaluation(self) -> None:
        contract = self.contract("mechanical")
        contract["canonicalRulesVersion"] = "999.0.0"
        contract["authorityOrder"] = list(reversed(contract["authorityOrder"]))
        source = contract["sources"][0]
        target = self.evidence_root.joinpath(*source["path"].split("/"))
        target.write_bytes(target.read_bytes() + b" mutated")
        row = contract["ruleApplications"][0]
        row["requirement"] += " Tampered."
        row["canonicalGateSha256"] = "0" * 64
        row["verifierId"] = "unresolved"
        row["generationConstraint"] = "TODO replace with a real constraint before any geometry generation occurs."
        contract["conflicts"] = [{
            "id": "C-MULTI",
            "sourceIds": ["STD_AUTHORITY", "ENG_INPUT"],
            "status": "unresolved",
        }]
        report = self.evaluate(contract)
        codes = {item["code"] for item in report["failures"]}
        self.assertTrue({
            "canonical_rules_identity_mismatch",
            "authority_order_mismatch",
            "source_inventory_invalid",
            "gate_application_invalid",
            "unresolved_source_conflict",
        }.issubset(codes), report)
        self.assertFalse(report["generationGate"]["nextStageAllowed"])

    def test_rule_inventory_declares_one_canonical_preflight_not_a_second_rule_catalog(self) -> None:
        policy = self.rules["generationPreflightPolicy"]
        self.assertEqual(policy["canonicalProfileByDomain"], {
            "mechanical": "mechanicalManufacturingProfileV3",
            "electronics": "electronicsFabricationProfileV3",
        })
        self.assertEqual(policy["includedSections"], ["intent", "design", "manufacturingDefinition"])
        self.assertEqual(policy["sharedRuleIds"], ["PROD-G001", "PROD-G002", "PROD-G003", "PROD-G004", "PROD-G005", "PROD-G006", "PROD-G013"])
        self.assertTrue(policy["exactGateInventoryRequired"])
        self.assertFalse(policy["technicalReadinessGranted"])
        self.assertFalse(policy["artifactExposureGranted"])
        self.assertFalse((PLUGIN / "rules" / "mechanical_rules_duplicate.json").exists())
        self.assertFalse((PLUGIN / "rules" / "electronics_rules_duplicate.json").exists())


if __name__ == "__main__":
    unittest.main()
