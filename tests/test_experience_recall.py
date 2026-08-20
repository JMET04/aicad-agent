from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "agent-plugin" / "aicad-agent" / "rules"
CATALOG = RULES / "experience_recall_catalog.json"
REGISTRY = RULES / "engineering_domain_registry.json"
NORMATIVE = RULES / "normative_governance_rules.json"

sys.path.insert(0, str(ROOT / "src"))

from aicad.engine import PlanError
from aicad.experience import (
    EXPECTED_LOCKS,
    populate_coverage_for_test,
    recall_experience,
    validate_coverage_ledger,
)


def design_context(
    domain: str,
    *,
    spaces: list[str] | None = None,
    product_families: list[str] | None = None,
    risk_tags: list[str] | None = None,
    change_tags: list[str] | None = None,
    requested_outputs: list[str] | None = None,
) -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    domain_spaces = registry["domains"][domain]["spaces"]
    return {
        "schema": "aicad_design_context_v1",
        "contextId": f"CTX_{domain.upper()}",
        "domain": domain,
        "spaces": list(spaces if spaces is not None else domain_spaces),
        "deliveryStage": "engineering_review",
        "productFamilies": list(product_families or []),
        "riskTags": list(risk_tags or []),
        "changeTags": list(change_tags or []),
        "requestedOutputs": list(requested_outputs or []),
        "applicableStandards": [
            {
                "standard": "PROJECT-SPEC",
                "edition": "CONTROLLED",
                "scope": domain,
                "authority": "approved_engineering_input",
            }
        ],
        "assumptions": [],
        "locks": dict(EXPECTED_LOCKS),
    }


def recall(domain: str, **context_overrides: object) -> dict:
    return recall_experience(
        design_context(domain, **context_overrides),
        CATALOG,
        RULES,
    )


def entry_for(ledger: dict, coverage_key: str) -> dict:
    return next(row for row in ledger["entries"] if row["coverageKey"] == coverage_key)


def write_evidence(
    evidence_root: Path,
    relative_path: str,
    *,
    content: bytes = b"controlled test evidence\n",
    kind: str = "test",
) -> dict:
    path = evidence_root.joinpath(*Path(relative_path).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": Path(relative_path).as_posix(),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "kind": kind,
    }


class ExperienceRecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context_schema = json.loads(
            (ROOT / "schema" / "aicad-experience-context.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.ledger_schema = json.loads(
            (ROOT / "schema" / "aicad-review-coverage-ledger.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.normative = json.loads(NORMATIVE.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.context_schema)
        Draft202012Validator.check_schema(cls.ledger_schema)

    def test_all_registered_domains_recall_maturity_and_exact_domain_pack(self) -> None:
        expected_domains = {
            "general",
            "architecture",
            "packaging",
            "mechanical",
            "electronics",
            "sheet_metal",
            "civil",
            "structural",
            "electrical",
            "plumbing",
            "hvac",
            "process_piping",
            "product_design",
        }
        self.assertEqual(set(self.registry["domains"]), expected_domains)
        self.assertEqual(set(self.normative["domainPacks"]), expected_domains)

        for domain in sorted(expected_domains):
            with self.subTest(domain=domain):
                result = recall(domain)
                self.assertTrue(result["ok"])
                profile = result["domainProfile"]
                registered = self.registry["domains"][domain]
                self.assertEqual(profile["id"], domain)
                self.assertEqual(profile["label"], registered["label"])
                self.assertEqual(profile["maturity"], registered["maturity"])
                self.assertEqual(profile["spaces"], registered["spaces"])
                self.assertEqual(
                    profile["nativeGenerationBoundary"],
                    registered["nativeGenerationBoundary"],
                )
                self.assertTrue(profile["productionReleaseBlocked"])
                self.assertTrue(profile["professionalReleaseBlocked"])
                self.assertTrue(profile["specialistEvidenceRequired"])
                self.assertTrue(result["coverageInventory"])

                expected_pack = {
                    f"domain-pack:{domain}:{item}"
                    for item in self.normative["domainPacks"][domain]
                }
                actual_pack = {
                    row["coverageKey"]
                    for row in result["coverageInventory"]
                    if row["coverageKey"].startswith(f"domain-pack:{domain}:")
                }
                self.assertEqual(actual_pack, expected_pack)

    def test_2d_and_3d_are_legal_controlled_space_tags(self) -> None:
        context = design_context("mechanical", spaces=["3d", "2d"])
        result = recall_experience(context, CATALOG, RULES)
        self.assertEqual(result["context"]["spaces"], ["2d", "3d"])

    def test_unknown_domain_fails_closed_against_registry(self) -> None:
        context = design_context("general")
        context["contextId"] = "CTX_UNKNOWN_DOMAIN"
        context["domain"] = "unknown_engineering_domain"
        with self.assertRaisesRegex(PlanError, "domain"):
            recall_experience(context, CATALOG, RULES)

    def test_context_and_generated_ledger_validate_against_public_schemas(self) -> None:
        context = design_context(
            "mechanical",
            product_families=["handheld_device"],
            risk_tags=["battery", "radio"],
            change_tags=["geometry"],
            requested_outputs=["review_html"],
        )
        Draft202012Validator(self.context_schema).validate(context)
        result = recall_experience(context, CATALOG, RULES)
        Draft202012Validator(self.ledger_schema).validate(result["coverageTemplate"])

    def test_populated_ledger_binds_real_evidence_and_never_grants_release(self) -> None:
        result = recall("civil")
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            ledger = populate_coverage_for_test(result, evidence_root=evidence_root)
            Draft202012Validator(self.ledger_schema).validate(ledger)
            self.assertTrue(ledger["entries"])
            for row in ledger["entries"]:
                self.assertEqual(row["status"], "pass")
                self.assertTrue(row["evidenceRefs"])
                for evidence in row["evidenceRefs"]:
                    self.assertEqual(set(evidence), {"path", "size", "sha256", "kind"})
                    self.assertFalse(Path(evidence["path"]).is_absolute())
                    self.assertNotIn("..", Path(evidence["path"]).parts)
                    path = evidence_root.joinpath(*Path(evidence["path"]).parts)
                    content = path.read_bytes()
                    self.assertEqual(evidence["size"], len(content))
                    self.assertEqual(
                        evidence["sha256"], hashlib.sha256(content).hexdigest()
                    )
                    self.assertIn(evidence["kind"], {"calculation", "inspection", "native_host", "test", "authority", "review"})
            validation = validate_coverage_ledger(result, ledger, evidence_root=evidence_root)
            self.assertTrue(validation["ok"])
            self.assertTrue(
                all(value is False for value in validation["readinessBoundary"].values())
            )

    def test_mechanical_and_electronics_preflight_inventory_is_exact(self) -> None:
        expected_counts = {"mechanical": 54, "electronics": 63}
        for domain, expected_count in expected_counts.items():
            with self.subTest(domain=domain):
                result = recall(domain)
                keys = [
                    row["coverageKey"]
                    for row in result["coverageInventory"]
                    if row["coverageKey"].startswith("preflight:")
                ]
                self.assertEqual(len(keys), expected_count)
                self.assertEqual(len(keys), len(set(keys)))
                self.assertTrue(all(row["required"] for row in result["coverageInventory"] if row["coverageKey"] in keys))

    def test_packaging_recall_contains_every_controlled_packaging_rule_once(self) -> None:
        result = recall("packaging")
        expected = {f"rule:packaging:PKG-G{index:03d}" for index in range(1, 26)}
        actual = {
            row["coverageKey"]
            for row in result["coverageInventory"]
            if row["coverageKey"].startswith("rule:packaging:PKG-G")
        }
        self.assertEqual(actual, expected)
        self.assertEqual(
            len([row for row in result["coverageInventory"] if row["coverageKey"] in expected]),
            25,
        )

    def test_civil_recall_contains_every_controlled_civil_rule_once(self) -> None:
        result = recall("civil")
        expected = {f"rule:civil:CIV-G{index:03d}" for index in range(1, 21)}
        actual = {
            row["coverageKey"]
            for row in result["coverageInventory"]
            if row["coverageKey"].startswith("rule:civil:CIV-G")
        }
        self.assertEqual(actual, expected)
        self.assertEqual(
            len([row for row in result["coverageInventory"] if row["coverageKey"] in expected]),
            20,
        )

    def test_tag_and_collection_order_do_not_change_context_fingerprint(self) -> None:
        first = design_context(
            "mechanical",
            spaces=["3d", "2d"],
            product_families=["handheld_device", "enclosure"],
            risk_tags=["battery", "interface"],
            change_tags=["geometry", "material"],
            requested_outputs=["review_html", "dxf"],
        )
        first["applicableStandards"].append(
            {
                "standard": "ISO-TEST",
                "edition": "2026",
                "scope": "dimensions",
                "authority": "selected_standard",
            }
        )
        first["assumptions"] = [
            {
                "id": "ASM_A",
                "statement": "first controlled assumption",
                "impact": "geometry",
                "confirmationPolicy": "confirm_before_release",
            },
            {
                "id": "ASM_B",
                "statement": "second controlled assumption",
                "impact": "material",
                "confirmationPolicy": "disclosed_default",
            },
        ]
        second = copy.deepcopy(first)
        for field in (
            "spaces",
            "productFamilies",
            "riskTags",
            "changeTags",
            "requestedOutputs",
            "applicableStandards",
            "assumptions",
        ):
            second[field].reverse()

        recalled_first = recall_experience(first, CATALOG, RULES)
        recalled_second = recall_experience(second, CATALOG, RULES)
        self.assertEqual(recalled_first["context"], recalled_second["context"])
        self.assertEqual(
            recalled_first["contextFingerprint"], recalled_second["contextFingerprint"]
        )
        self.assertEqual(
            recalled_first["catalogFingerprint"], recalled_second["catalogFingerprint"]
        )

    def test_required_cards_are_never_truncated_by_max_cards(self) -> None:
        context = design_context(
            "mechanical",
            spaces=["2d", "3d"],
            product_families=["handheld_device"],
            risk_tags=["battery", "radio"],
        )
        result = recall_experience(context, CATALOG, RULES, max_cards=1)
        returned_required = {row["id"] for row in result["cards"] if row["required"]}
        self.assertEqual(
            returned_required,
            {"EXP-GLOBAL-001", "EXP-GLOBAL-002", "EXP-MECH-001"},
        )
        self.assertGreater(len(result["cards"]), 1)

    def test_candidate_lessons_remain_advisory_and_cannot_fill_coverage(self) -> None:
        context = design_context(
            "mechanical",
            spaces=["3d"],
            product_families=["handheld_device"],
            change_tags=["geometry"],
        )
        baseline = recall_experience(context, CATALOG, RULES)
        bundle = {
            "schema": "aicad_lesson_bundle_v1",
            "safetyLocks": dict(EXPECTED_LOCKS),
            "lessons": [
                {
                    "lessonId": "LESSON-TEST-001",
                    "failureAlias": "handheld_device geometry regression",
                    "failingCheck": "geometry",
                    "symptom": "handheld enclosure mismatch",
                    "rootCause": "geometry changed without interface revalidation",
                    "correction": "revalidate handheld_device geometry and interfaces",
                    "domain": "mechanical",
                    "candidateRule": {"id": "CANDIDATE-TEST-001"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            bundle_path = Path(directory) / "candidate-lessons.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            recalled = recall_experience(
                context,
                CATALOG,
                RULES,
                candidate_lesson_bundles=[bundle_path],
            )

        self.assertEqual(recalled["coverageInventory"], baseline["coverageInventory"])
        self.assertEqual(recalled["coverageTemplate"], baseline["coverageTemplate"])
        self.assertEqual(len(recalled["candidateLessons"]), 1)
        candidate = recalled["candidateLessons"][0]
        self.assertEqual(candidate["authority"], "review_only_candidate")
        self.assertFalse(candidate["maySatisfyCoverage"])
        self.assertFalse(candidate["automaticPromotion"])
        self.assertEqual(candidate["safetyLocks"], EXPECTED_LOCKS)
        self.assertNotIn(
            candidate["candidateRuleId"],
            {row["coverageKey"] for row in recalled["coverageInventory"]},
        )

        with tempfile.TemporaryDirectory() as evidence_directory:
            evidence_root = Path(evidence_directory)
            forged = populate_coverage_for_test(recalled, evidence_root=evidence_root)
            extra = copy.deepcopy(forged["entries"][0])
            extra["coverageKey"] = f"candidate:{candidate['candidateRuleId']}"
            forged["entries"].append(extra)
            with self.assertRaisesRegex(PlanError, "inventory is not exact"):
                validate_coverage_ledger(recalled, forged, evidence_root=evidence_root)

    def test_coverage_ledger_rejects_missing_duplicate_and_extra_keys(self) -> None:
        result = recall("mechanical", change_tags=["geometry"])
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            valid = populate_coverage_for_test(result, evidence_root=evidence_root)

            missing = copy.deepcopy(valid)
            missing["entries"].pop()
            with self.assertRaisesRegex(PlanError, "inventory is not exact"):
                validate_coverage_ledger(result, missing, evidence_root=evidence_root)

            duplicate = copy.deepcopy(valid)
            duplicate["entries"].append(copy.deepcopy(duplicate["entries"][0]))
            with self.assertRaisesRegex(PlanError, "duplicate key"):
                validate_coverage_ledger(result, duplicate, evidence_root=evidence_root)

            extra = copy.deepcopy(valid)
            extra_row = copy.deepcopy(extra["entries"][0])
            extra_row["coverageKey"] = "forged:extra-rule"
            extra["entries"].append(extra_row)
            with self.assertRaisesRegex(PlanError, "inventory is not exact"):
                validate_coverage_ledger(result, extra, evidence_root=evidence_root)

    def test_pass_requires_evidence(self) -> None:
        result = recall("mechanical")
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            ledger = populate_coverage_for_test(result, evidence_root=evidence_root)
            affected = ledger["entries"][0]
            affected["evidenceRefs"] = []
            validation = validate_coverage_ledger(result, ledger, evidence_root=evidence_root)
            self.assertFalse(validation["ok"])
            self.assertEqual(validation["status"], "blocked")
            failure = next(
                row
                for row in validation["failures"]
                if row["coverageKey"] == affected["coverageKey"]
            )
            self.assertIn("pass_requires_evidence", failure["reasons"])

    def test_affected_pass_must_be_revalidated_after_change(self) -> None:
        result = recall("mechanical", change_tags=["geometry"])
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            ledger = populate_coverage_for_test(result, evidence_root=evidence_root)
            spec = next(
                row
                for row in result["coverageInventory"]
                if "geometry" in row["invalidatedBy"] or "*" in row["invalidatedBy"]
            )
            affected = entry_for(ledger, spec["coverageKey"])
            affected["validatedChangeTags"] = []
            validation = validate_coverage_ledger(result, ledger, evidence_root=evidence_root)
            self.assertFalse(validation["ok"])
            failure = next(
                row
                for row in validation["failures"]
                if row["coverageKey"] == spec["coverageKey"]
            )
            self.assertIn("affected_change_not_revalidated", failure["reasons"])

    def test_not_applicable_requires_permission_evidence_and_rationale(self) -> None:
        result = recall("mechanical")
        allowed = next(
            row for row in result["coverageInventory"] if row["allowNotApplicable"]
        )
        forbidden = next(
            row for row in result["coverageInventory"] if not row["allowNotApplicable"]
        )

        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            authority_ref = write_evidence(evidence_root, "authority/not-applicable.json", kind="authority")
            accepted = populate_coverage_for_test(result, evidence_root=evidence_root)
            accepted_row = entry_for(accepted, allowed["coverageKey"])
            accepted_row.update(
                {
                    "status": "not_applicable",
                    "evidenceRefs": [copy.deepcopy(authority_ref)],
                    "rationale": "Approved project scope excludes this optional gate.",
                }
            )
            accepted_validation = validate_coverage_ledger(result, accepted, evidence_root=evidence_root)
            self.assertTrue(accepted_validation["ok"])
            self.assertEqual(accepted_validation["counts"]["notApplicable"], 1)

            prohibited = populate_coverage_for_test(result, evidence_root=evidence_root)
            prohibited_row = entry_for(prohibited, forbidden["coverageKey"])
            prohibited_row.update(
                {
                    "status": "not_applicable",
                    "evidenceRefs": [copy.deepcopy(authority_ref)],
                    "rationale": "Attempted waiver.",
                }
            )
            prohibited_validation = validate_coverage_ledger(result, prohibited, evidence_root=evidence_root)
            self.assertFalse(prohibited_validation["ok"])
            prohibited_failure = next(
                row
                for row in prohibited_validation["failures"]
                if row["coverageKey"] == forbidden["coverageKey"]
            )
            self.assertIn("not_applicable_forbidden", prohibited_failure["reasons"])

            unsupported = populate_coverage_for_test(result, evidence_root=evidence_root)
            unsupported_row = entry_for(unsupported, allowed["coverageKey"])
            unsupported_row.update(
                {"status": "not_applicable", "evidenceRefs": [], "rationale": ""}
            )
            unsupported_validation = validate_coverage_ledger(result, unsupported, evidence_root=evidence_root)
            self.assertFalse(unsupported_validation["ok"])
            unsupported_failure = next(
                row
                for row in unsupported_validation["failures"]
                if row["coverageKey"] == allowed["coverageKey"]
            )
            self.assertIn(
                "not_applicable_requires_authority_and_rationale",
                unsupported_failure["reasons"],
            )

    def test_evidence_refs_reject_strings_missing_files_and_forged_metadata(self) -> None:
        result = recall("civil")
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            valid = populate_coverage_for_test(result, evidence_root=evidence_root)
            original = copy.deepcopy(valid["entries"][0]["evidenceRefs"][0])
            missing = copy.deepcopy(original)
            missing.update({"path": "missing.bin", "size": 1, "sha256": hashlib.sha256(b"x").hexdigest()})
            bad_size = copy.deepcopy(original)
            bad_size["size"] += 1
            bad_hash = copy.deepcopy(original)
            bad_hash["sha256"] = "0" * 64
            bad_kind = copy.deepcopy(original)
            bad_kind["kind"] = "visual_guess"
            escape = copy.deepcopy(original)
            escape["path"] = "../outside-evidence.bin"
            absolute = copy.deepcopy(original)
            absolute["path"] = str((evidence_root / "absolute.bin").resolve())
            cases = [
                ("legacy_string", "evidence://legacy/string"),
                ("missing", missing),
                ("bad_size", bad_size),
                ("bad_hash", bad_hash),
                ("bad_kind", bad_kind),
                ("path_escape", escape),
                ("absolute_path", absolute),
            ]
            for name, evidence_ref in cases:
                ledger = copy.deepcopy(valid)
                ledger["entries"][0]["evidenceRefs"] = [evidence_ref]
                with self.subTest(case=name):
                    if name == "legacy_string":
                        self.assertTrue(list(Draft202012Validator(self.ledger_schema).iter_errors(ledger)))
                    with self.assertRaisesRegex(PlanError, "(?i)evidence|path|size|sha256|kind"):
                        validate_coverage_ledger(result, ledger, evidence_root=evidence_root)

    def test_pending_coverage_never_unlocks_any_readiness_or_authorization(self) -> None:
        result = recall("civil")
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            validation = validate_coverage_ledger(result, result["coverageTemplate"], evidence_root=evidence_root)
            self.assertFalse(validation["ok"])
            self.assertEqual(validation["status"], "blocked")
            self.assertTrue(validation["failures"])
            self.assertTrue(
                all(value is False for value in validation["readinessBoundary"].values())
            )
            self.assertTrue(
                all(value is False for value in result["readinessBoundary"].values())
            )

    def test_missing_catalog_rule_reference_fails_closed(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog["cards"][0]["ruleRefs"][0]["ruleId"] = "MISSING-RULE"
        with tempfile.TemporaryDirectory() as directory:
            bad_catalog = Path(directory) / "bad-experience-catalog.json"
            bad_catalog.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(PlanError, "references missing rule"):
                recall_experience(design_context("mechanical"), bad_catalog, RULES)


if __name__ == "__main__":
    unittest.main()
