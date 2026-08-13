from __future__ import annotations

import copy
import hashlib
import io
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator


PLUGIN = Path(__file__).resolve().parents[1]
REPOSITORY = PLUGIN.parent.parent
for candidate in (PLUGIN / "runtime" / "src", REPOSITORY / "src"):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from aicad.continuous_learning import (  # noqa: E402
    EXPECTED_CANDIDATE_LOCKS,
    audit_lesson_bundle,
    audit_promotion_ledger,
    canonical_failure_report,
    controlled_learning_output_path,
    file_entry,
    harvest_lesson_bundle,
    merge_lesson_events,
    safe_relative_path,
)
from aicad.reporting import ReportInvariantError  # noqa: E402


QA_PATH = PLUGIN / "scripts" / "aicad_continuous_learning_qa.py"
HARVESTER_PATH = PLUGIN / "scripts" / "aicad_lesson_harvester.py"
RULES_PATH = PLUGIN / "rules" / "continuous_learning_rules.json"
EVENT_SCHEMA_PATH = PLUGIN / "rules" / "learning_event.schema.json"
LEDGER_SCHEMA_PATH = PLUGIN / "rules" / "learning_approval_ledger.schema.json"

SPEC = importlib.util.spec_from_file_location("aicad_continuous_learning_qa", QA_PATH)
assert SPEC and SPEC.loader
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)

HARVESTER_SPEC = importlib.util.spec_from_file_location("aicad_lesson_harvester", HARVESTER_PATH)
assert HARVESTER_SPEC and HARVESTER_SPEC.loader
HARVESTER = importlib.util.module_from_spec(HARVESTER_SPEC)
HARVESTER_SPEC.loader.exec_module(HARVESTER)


EXPECTED_FAILURE_ALIASES = {
    "mechanical.sw_default_material_mass_vs_hydro_density",
    "mechanical.custom_property_claimed_as_native_material",
    "mechanical.6306_bearing_life_shortfall",
    "mechanical.eccentric_80mm_moment_omitted",
    "mechanical.hardcoded_anchor_bore_thread_grease_parameters",
    "mechanical.allowed_pair_whitelist_arbitrary_overlap",
    "mechanical.same_name_assembly_import_pollution",
    "mechanical.thermal_fit_wrong_object_path",
    "mechanical.thermal_fit_wrong_temperature_sign",
    "mechanical.thermal_fit_touchline_zero_margin",
    "mechanical.carrier_missing_native_step_drawing_assembly_closure",
    "mechanical.dxf_text_claimed_as_native_dimension",
    "mechanical.native_drawing_dimension_closure_incomplete",
    "mechanical.dwg_private_author_metadata",
    "mechanical.autocad_core_process_residual",
    "mechanical.release_manifest_artifacts_files_scope_mismatch",
    "electronics.stage_b_imported_old_stage_a",
    "electronics.stage_b_fallback_when_accepted_a_missing",
    "electronics.erc_severity_or_ignored_compensation",
    "electronics.erc_zero_missing_datasheet_passive",
    "electronics.thvd1450_drb_footprint_alias_ambiguity",
    "electronics.stm32_vbus_wrong_pin",
    "electronics.bav199_dual_diode_wrong_clamp",
    "electronics.bav199_rail_backpower",
    "electronics.opa4388_unpowered_vid_exceeded",
    "electronics.tvs3301_85c_surge_rating_shortfall",
    "electronics.four_local_surges_modeled_as_80a_common_neck",
    "electronics.ads_aingnd_bias_matching_model_incomplete",
    "electronics.input_100ohm_accuracy_definition_conflict",
    "electronics.illegal_nt_agnd_reference_renamed",
    "electronics.per_ic_local_decoupling_not_closed",
    "electronics.mcu_vdda_vssa_missing_10n_1u_with_erc_zero",
    "electronics.dedicated_power_pair_decoupling_missing_with_erc_zero",
    "electronics.rs485_missing_local_100n_with_erc_zero",
    "electronics.thvd2410_sm712_coordination_unqualified",
    "electronics.shield_conductor_collapsed_into_signal_gnd",
    "electronics.connector_exact_opn_pitch_accumulated_error",
    "electronics.power_contract_ambiguous_continuous_load_shortcut",
    "electronics.erc_bom_pass_generalized_to_full_system_pass",
    "electronics.repair_claim_precedes_native_bom_netlist_change",
    "electronics.canonical_private_netlist_separation_missing",
    "electronics.one_page_schematic_tiny_font_collisions",
    "electronics.two_page_schematic_duplicate_or_blank_overview",
    "electronics.contract_errata_overlay",
    "electronics.contract_r1_r2_r3_coexistence",
    "electronics.absolute_d_temp_kicad_dependency",
    "electronics.native_netlist_source_absolute_path",
    "electronics.relative_cli_path_resolved_against_cwd",
    "electronics.gate_report_mixed_artifact_candidate",
    "electronics.stage_a_model_native_proc_bom_same_source_risk",
    "electronics.allow_missing_courtyard_bypass",
    "electronics.netlist_parity_not_bidirectional",
    "electronics.fabricator_stackup_authority_unknown",
    "electronics.mechanical_icd_authority_unknown",
    "electronics.sm712_clamp_exceeds_thvd1450_absmax",
    "electronics.j3_missing_shield_chassis_contract_pins",
    "electronics.phoenix_5p08_order_code_on_p5p00_footprint",
    "electronics.j1_p5p08_claimed_but_actual_bom_p5p00",
    "electronics.u5_pin_authority_comment_mislabels_d8",
    "electronics.full_system_authority_only_covers_analog_subset",
    "electronics.maximum_load_uses_30v_times_pptc_hold",
    "electronics.contract_references_deleted_tps2116_tlvh431",
    "electronics.contract_references_old_usb_divider",
    "electronics.contract_references_old_10ksps_rate",
    "electronics.local_analog_pass_generalized_to_system_pass",
    "electronics.nonisolated_returns_treated_as_independent",
    "electronics.tlv755_actual_board_thermal_margin_not_bound",
    "electronics.24v_input_surge_chain_not_closed",
    "electronics.usb_vbus_contract_stale_active_high_divider",
    "electronics.q1_family_name_not_exact_orderable_opn",
    "electronics.usb_cc1_cc2_esd_coverage_missing",
    "electronics.q1_candidate_contract_reauthored_exact_opn",
    "electronics.usb_cc_esd_array_bypassed_while_other_usb_checks_green",
    "electronics.hierarchical_child_schematic_omitted_from_acceptance_hash",
    "electronics.unbound_contract_reauthored_kicad_version",
    "electronics.authority_manifest_self_declared_pdf_hash_and_mpn_coverage",
    "electronics.authority_pdf_suffix_contains_access_denied_html",
    "electronics.pad_net_parity_collapsed_duplicate_pad_occurrences",
    "electronics.stage_b_extra_unbound_pad_mpn_or_land_pattern",
    "electronics.stage_b_executed_stage_a_generator",
    "electronics.accepted_manifest_old_role_alias_accepted",
    "electronics.drc_consumer_downgraded_severity_or_added_exclusion",
    "electronics.stage_a_technical_acceptance_misread_as_fabrication_authorization",
    "electronics.stage_b_reused_compact_legacy_board_without_zone_authority",
    "electronics.drc_warning_severity_downgrade_accepted",
    "electronics.drc_ignored_check_or_exclusion_accepted",
    "electronics.stage_b_accepted_project_byte_drift",
    "electronics.stage_b_legacy_100x80_capacity_reaccepted",
    "electronics.stage_b_m3_npth_or_service_zone_mutated",
    "electronics.stage_b_functional_zone_or_courtyard_overlap_mutated",
    "electronics.technical_gate_authorization_boolean_true",
    "release.relative_path_wrong_working_directory",
    "release.mixed_artifact_closure",
    "release.manifest_sha_one_way_only",
    "release.errata_overlay_canonical_contract",
    "release.nonportable_machine_absolute_path",
    "release.source_input_freshness_missing",
    "release.public_final_written_before_complete",
    "release.showcase_empty_manifest",
    "release.showcase_arbitrary_directory",
    "release.showcase_sensitive_binary",
    "release.showcase_symlink_escape",
    "release.showcase_stale_output_residue",
    "release.showcase_incomplete_roles",
    "release.showcase_duplicate_slug",
    "release.readme_links_not_verified",
    "release.showcase_review_local_links_not_copied",
    "release.windows_subprocess_utf8_decode_implicit_locale",
    "release.mutating_tests_parallel_with_final_scan",
    "release.pycache_polluted_release",
    "release.rule_catalog_invalid_json",
    "release.stage_gate_matrix_stale_candidate_path_hardcoded",
    "release.system_temp_capacity_exhausted_during_regression",
    "release.failed_stage_a_finalization_left_stale_manifest_live",
    "release.stage_b_matrix_and_files_rewritten_together_without_independent_aggregate",
    "release.evidence_pass_field_overwrote_independent_verdict",
    "release.accepted_gate_requirements_matrix_mixed_revisions",
    "release.stage_b_missing_acceptance_wrote_before_failure",
    "release.preacceptance_test_overwrote_historical_stage_b_baseline",
    "release.stage_b_probe_next_cache_alternate_implementations",
    "release.valid_acceptance_targeted_immutable_stage_b_baseline",
    "release.stage_bc_extra_consumer_entrypoint",
    "release.source_closure_policy_literals_self_matched",
    "release.continuous_learning_catalog_schema_unverified",
    "release.continuous_learning_catalog_duplicate_rule_id",
    "release.continuous_learning_alias_dangling_or_domain_mismatched",
    "release.continuous_learning_prevention_rule_unaliased",
    "release.continuous_learning_required_regression_missing",
    "release.continuous_learning_minimal_fixture_bypassed_semantics",
    "release.learning_schema_document_presence_without_structure_validation",
    "release.learning_schema_dangling_local_ref",
    "release.learning_schema_required_property_not_declared",
    "release.installer_preferred_stale_materialized_plugin",
    "release.installer_accepted_plugin_integration_version_mismatch",
    "release.installer_mutated_destination_before_source_verification",
    "release.plugin_and_manifest_agreed_on_stale_version",
    "release.component_versions_not_bound_to_requested_release",
    "release.concurrent_learning_alias_inventory_merge_dropped_existing_entries",
    "release.guarded_patch_self_created_duplicate_anchor",
    "release.continuous_learning_authorization_source_string_only",
    "release.continuous_learning_harvester_guard_call_presence_only",
    "release.release_metadata_non_object_crashed_verifier",
    "electronics.local_label_substitution_preserved_erc_but_broke_native_topology_and_visual_qa",
    "electronics.hidden_kicad_labels_remained_pdf_text_and_increased_collisions",
    "electronics.physical_series_rewire_preserved_erc_but_dropped_named_native_nets",
    "electronics.independent_label_lane_reroute_increased_pdf_collisions_despite_erc",
    "release.continuous_learning_runtime_alias_unstable_or_wrong_domain",
    "release.continuous_learning_runtime_extra_key_bypassed_schema",
    "release.continuous_learning_postwrite_audit_left_invalid_candidate",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ContinuousLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        for relative, content in {
            "fixtures/reproducer.txt": "minimum reproducer\n",
            "evidence/failure.json": "{\"failed\":true}\n",
            "sources/input.json": "{\"value\":1}\n",
            "artifacts/candidate.bin": "candidate bytes\n",
            "approvals/rule.txt": "reviewer A approval\n",
            "approvals/regression.txt": "reviewer B approval\n",
            "regression/results.json": "{\"red\":true,\"green\":true}\n",
        }.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        self.report = self._report()
        report_path = self.root / "reports" / "failure.json"
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps(self.report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _entry(self, relative: str) -> dict[str, object]:
        return file_entry(self.root, relative)

    def _report(self) -> dict[str, object]:
        closure = lambda policy, relative: {"policy": policy, "entries": [self._entry(relative)]}
        return {
            "schema": "aicad_test_failure_report_v1",
            "reportId": "REPORT-ROOT-PATH-001",
            "status": "failed",
            "failedChecks": [
                {
                    "failureId": "FAIL-ROOT-PATH-001",
                    "failureAlias": "release.relative_path_wrong_working_directory",
                    "domain": "release",
                    "failingCheck": "relative CLI output containment",
                    "symptom": "output escaped the requested root",
                    "rootCause": "relative path used process CWD",
                    "correction": "resolve every relative argument against explicit root",
                    "candidateRule": {
                        "id": "REL-G023",
                        "requirement": "resolve against explicit root",
                        "prevention": "reject unsafe paths and foreign-CWD writes",
                        "regressionTest": "launch from a foreign CWD",
                        "safetyLocks": dict(EXPECTED_CANDIDATE_LOCKS),
                    },
                    "reproducer": self._entry("fixtures/reproducer.txt"),
                    "evidenceClosure": closure("exact_declared_evidence", "evidence/failure.json"),
                    "sourceInputClosure": closure("exact_declared_inputs", "sources/input.json"),
                    "affectedArtifactClosure": closure("exact_declared_artifacts", "artifacts/candidate.bin"),
                }
            ],
            "safetyLocks": dict(EXPECTED_CANDIDATE_LOCKS),
        }

    def _bundle(self) -> dict[str, object]:
        return harvest_lesson_bundle(self.root, "reports/failure.json")

    def _write_bundle(self) -> dict[str, object]:
        bundle = self._bundle()
        path = self.root / "learning" / "bundle.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return bundle

    def _ledger(self) -> dict[str, object]:
        return {
            "schema": "aicad_learning_approval_ledger_v1",
            "candidateBundle": self._entry("learning/bundle.json"),
            "sourceVersion": "1.12.0",
            "targetVersion": "1.13.0",
            "targetRuleId": "REL-G023",
            "approvalRecords": [
                {
                    "role": "candidate_rule_reviewer",
                    "reviewerId": "reviewer-a",
                    "decision": "approved",
                    "candidateBundleSha256": self._entry("learning/bundle.json")["sha256"],
                    "targetRuleId": "REL-G023",
                    "targetVersion": "1.13.0",
                    "approvalEvidence": self._entry("approvals/rule.txt"),
                },
                {
                    "role": "regression_reviewer",
                    "reviewerId": "reviewer-b",
                    "decision": "approved",
                    "candidateBundleSha256": self._entry("learning/bundle.json")["sha256"],
                    "targetRuleId": "REL-G023",
                    "targetVersion": "1.13.0",
                    "approvalEvidence": self._entry("approvals/regression.txt"),
                },
            ],
            "regressionEvidence": {
                "report": self._entry("regression/results.json"),
                "redBeforeFix": True,
                "greenAfterFix": True,
                "unrelatedSuitesPass": True,
            },
            "changePolicy": {
                "weakensExistingRules": False,
                "deletesTests": False,
                "removesAuthoritativeRules": False,
                "modifiesInstalledPlugin": False,
                "automaticPromotion": False,
            },
            "safetyLocks": dict(EXPECTED_CANDIDATE_LOCKS),
        }

    def test_schema_accepts_report_bundle_and_ledger(self) -> None:
        event_schema = json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
        ledger_schema = json.loads(LEDGER_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(event_schema).validate(self.report)
        bundle = self._write_bundle()
        Draft202012Validator(event_schema).validate(bundle)
        Draft202012Validator(ledger_schema).validate(self._ledger())

    def test_runtime_rejects_unstable_or_cross_domain_failure_aliases(self) -> None:
        invalid_aliases = (
            "Release.relative_path_wrong_working_directory",
            "release.Relative_path_wrong_working_directory",
            "release.relative path wrong working directory",
            " release.relative_path_wrong_working_directory",
            "electronics.relative_path_wrong_working_directory",
        )
        for alias in invalid_aliases:
            report = self._report()
            report["failedChecks"][0]["failureAlias"] = alias
            with self.subTest(surface="report", alias=alias), self.assertRaises(ReportInvariantError):
                canonical_failure_report(self.root, report)

        bundle = self._bundle()
        for alias in invalid_aliases:
            candidate = copy.deepcopy(bundle)
            candidate["lessons"][0]["failureAlias"] = alias
            with self.subTest(surface="bundle", alias=alias), self.assertRaises(ReportInvariantError):
                audit_lesson_bundle(self.root, candidate)

        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        novel = {
            "lessons": [{
                "failureAlias": "release.new_runtime_failure",
                "domain": "release",
                "candidateRule": {"id": "REL-G023"},
            }]
        }
        self.assertEqual(
            QA._audit_bundle_aliases(novel, rules)["novelReviewOnlyAliases"],
            ["release.new_runtime_failure"],
        )
        for alias, domain in (
            ("Release.new_runtime_failure", "release"),
            ("release.new runtime failure", "release"),
            ("electronics.new_runtime_failure", "release"),
        ):
            invalid_novel = copy.deepcopy(novel)
            invalid_novel["lessons"][0]["failureAlias"] = alias
            invalid_novel["lessons"][0]["domain"] = domain
            with self.subTest(surface="novel", alias=alias), self.assertRaises(ReportInvariantError):
                QA._audit_bundle_aliases(invalid_novel, rules)

    def test_runtime_rejects_extra_keys_across_report_bundle_and_ledger(self) -> None:
        report_mutations: list[dict[str, object]] = []
        for path in (
            ("top",), ("failedCheck",), ("candidateRule",), ("reproducer",), ("closure",),
        ):
            candidate = self._report()
            if path == ("top",):
                candidate["selfApproved"] = True
            elif path == ("failedCheck",):
                candidate["failedChecks"][0]["ignored"] = True
            elif path == ("candidateRule",):
                candidate["failedChecks"][0]["candidateRule"]["enabled"] = True
            elif path == ("reproducer",):
                candidate["failedChecks"][0]["reproducer"]["trusted"] = True
            else:
                candidate["failedChecks"][0]["evidenceClosure"]["fallback"] = []
            report_mutations.append(candidate)
        for candidate in report_mutations:
            with self.subTest(surface="report"), self.assertRaises(ReportInvariantError):
                canonical_failure_report(self.root, candidate)

        bundle = self._bundle()
        bundle_mutations: list[dict[str, object]] = []
        for location in ("top", "sourceReport", "mapping", "lesson", "coverage"):
            candidate = copy.deepcopy(bundle)
            if location == "top":
                candidate["accepted"] = True
            elif location == "sourceReport":
                candidate["sourceReports"][0]["trusted"] = True
            elif location == "mapping":
                candidate["sourceReports"][0]["mappings"][0]["fallback"] = True
            elif location == "lesson":
                candidate["lessons"][0]["promoted"] = True
            else:
                candidate["failureLessonClosure"]["ignoredFailures"] = []
            bundle_mutations.append(candidate)
        for candidate in bundle_mutations:
            with self.subTest(surface="bundle"), self.assertRaises(ReportInvariantError):
                audit_lesson_bundle(self.root, candidate)

        self._write_bundle()
        ledger = self._ledger()
        ledger_mutations: list[dict[str, object]] = []
        for location in ("top", "candidateBundle", "approval", "regression", "changePolicy"):
            candidate = copy.deepcopy(ledger)
            if location == "top":
                candidate["authenticated"] = True
            elif location == "candidateBundle":
                candidate["candidateBundle"]["trusted"] = True
            elif location == "approval":
                candidate["approvalRecords"][0]["authenticated"] = True
            elif location == "regression":
                candidate["regressionEvidence"]["waived"] = False
            else:
                candidate["changePolicy"]["manualOnly"] = True
            ledger_mutations.append(candidate)
        for candidate in ledger_mutations:
            with self.subTest(surface="ledger"), self.assertRaises(ReportInvariantError):
                audit_promotion_ledger(self.root, candidate, current_version="1.12.0")

    def test_harvester_audits_in_memory_before_atomic_write(self) -> None:
        output = self.root / "learning" / "invalid-candidate.json"
        argv = [
            str(HARVESTER_PATH), "reports/failure.json", "--root", str(self.root),
            "--output", "learning/invalid-candidate.json",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                HARVESTER, "audit_lesson_bundle",
                side_effect=ReportInvariantError("forced in-memory candidate audit failure"),
            ),
            patch.object(HARVESTER, "_atomic_json") as atomic_write,
            redirect_stderr(io.StringIO()),
        ):
            return_code = HARVESTER.main()
        self.assertEqual(return_code, 2)
        atomic_write.assert_not_called()
        self.assertFalse(output.exists())
        self.assertFalse(output.parent.exists())

    def test_harvest_is_deterministic_idempotent_and_has_no_time_or_absolute_path(self) -> None:
        first = self._bundle()
        second = harvest_lesson_bundle(self.root, "reports/failure.json", existing=first)
        self.assertEqual(first, second)
        rendered = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn("observedAt", rendered)
        self.assertRegex(first["lessons"][0]["lessonId"], r"^LESSON-[0-9A-F]{24}$")
        self.assertEqual(audit_lesson_bundle(self.root, first)["status"], "pass")

    def test_report_lesson_closure_rejects_missing_extra_and_mixed_events(self) -> None:
        bundle = self._bundle()
        missing = copy.deepcopy(bundle)
        missing["lessons"] = []
        with self.assertRaises(ReportInvariantError):
            audit_lesson_bundle(self.root, missing)
        extra = copy.deepcopy(bundle)
        injected = copy.deepcopy(extra["lessons"][0])
        injected["lessonId"] = "LESSON-" + "A" * 24
        extra["lessons"].append(injected)
        with self.assertRaises(ReportInvariantError):
            audit_lesson_bundle(self.root, extra)
        mixed = copy.deepcopy(bundle)
        mixed["lessons"][0]["correction"] = "content from another candidate"
        with self.assertRaises(ReportInvariantError):
            audit_lesson_bundle(self.root, mixed)

    def test_same_lesson_id_conflict_fails(self) -> None:
        event = self._bundle()["lessons"][0]
        changed = copy.deepcopy(event)
        changed["correction"] = "different correction"
        with self.assertRaises(ReportInvariantError):
            merge_lesson_events([event], [changed])

    def test_path_hash_lock_and_link_fail_closed(self) -> None:
        for unsafe in ("../escape.json", "/absolute.json", "D:/Temp/file.json", "dir\\file.json", "./file.json"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ReportInvariantError):
                safe_relative_path(unsafe)
        wrong_hash = copy.deepcopy(self.report)
        wrong_hash["failedChecks"][0]["reproducer"]["sha256"] = "0" * 64
        (self.root / "reports/failure.json").write_text(json.dumps(wrong_hash), encoding="utf-8")
        with self.assertRaises(ReportInvariantError):
            self._bundle()

    def test_symlink_escape_is_rejected_when_supported(self) -> None:
        outside_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(outside_dir, ignore_errors=True))
        outside = outside_dir / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "fixtures" / "escape.txt"
        try:
            os.symlink(outside, link)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        report = self._report()
        report["failedChecks"][0]["reproducer"] = {
            "path": "fixtures/escape.txt",
            "size": outside.stat().st_size,
            "sha256": sha(outside),
        }
        (self.root / "reports/failure.json").write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises(ReportInvariantError):
            self._bundle()

    def test_link_detection_is_fail_closed_without_os_symlink_privilege(self) -> None:
        with patch("aicad.continuous_learning._path_has_link", return_value=True):
            with self.assertRaises(ReportInvariantError):
                file_entry(self.root, "fixtures/reproducer.txt")

    def test_candidate_lock_mutation_fails(self) -> None:
        for field, value in {"reviewOnly": False, "accepted": True, "ruleEnabled": True, "packagingGated": False}.items():
            report = self._report()
            report["failedChecks"][0]["candidateRule"]["safetyLocks"][field] = value
            (self.root / "reports/failure.json").write_text(json.dumps(report), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(ReportInvariantError):
                self._bundle()

    def test_promotion_preflight_binds_two_reviewers_bundle_rule_and_new_version_only(self) -> None:
        self._write_bundle()
        ledger = self._ledger()
        result = audit_promotion_ledger(self.root, ledger, current_version="1.12.0")
        self.assertTrue(result["recordedPromotionPreconditionsComplete"])
        self.assertTrue(result["recordedApprovalEvidenceStructurallyValid"])
        self.assertTrue(result["manualPromotionRequiresExternalAuthenticatedReview"])
        self.assertFalse(result["independentApprovalAuthenticityVerified"])
        self.assertFalse(result["externalAuthenticatedReviewVerified"])
        self.assertFalse(result["promotionEligibleForManualApplication"])
        self.assertFalse(result["promotionPerformed"])
        self.assertFalse(result["authoritativeRulesModified"])
        self.assertFalse(result["installedPluginModified"])
        for field in ("technicalPackageReady", "productionReleaseEligible", "manufacturingAuthorized", "fabricationAuthorized"):
            self.assertFalse(result[field], field)
        mutations = []
        same_reviewer = copy.deepcopy(ledger)
        same_reviewer["approvalRecords"][1]["reviewerId"] = "reviewer-a"
        mutations.append(same_reviewer)
        old_version = copy.deepcopy(ledger)
        old_version["targetVersion"] = "1.12.0"
        old_version["approvalRecords"][0]["targetVersion"] = "1.12.0"
        old_version["approvalRecords"][1]["targetVersion"] = "1.12.0"
        mutations.append(old_version)
        wrong_rule = copy.deepcopy(ledger)
        wrong_rule["approvalRecords"][0]["targetRuleId"] = "REL-G024"
        mutations.append(wrong_rule)
        wrong_bundle = copy.deepcopy(ledger)
        wrong_bundle["approvalRecords"][0]["candidateBundleSha256"] = "0" * 64
        mutations.append(wrong_bundle)
        for candidate in mutations:
            with self.subTest(candidate=candidate), self.assertRaises(ReportInvariantError):
                audit_promotion_ledger(self.root, candidate, current_version="1.12.0")

    def test_cli_resolves_against_root_and_does_not_mutate_plugin_authority(self) -> None:
        protected = [RULES_PATH, PLUGIN / ".codex-plugin" / "plugin.json", Path(__file__)]
        before = {path: sha(path) for path in protected}
        foreign = self.root / "foreign-cwd"
        foreign.mkdir()
        completed = subprocess.run(
            [
                sys.executable, "-B", str(HARVESTER_PATH), "reports/failure.json",
                "--root", str(self.root), "--output", "learning/bundle.json",
            ],
            cwd=foreign,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.root / "learning/bundle.json").is_file())
        self.assertFalse((foreign / "learning/bundle.json").exists())
        after = {path: sha(path) for path in protected}
        self.assertEqual(before, after)
        self.assertNotIn(str(self.root), (self.root / "learning/bundle.json").read_text(encoding="utf-8"))

    def test_candidate_output_is_json_below_learning_and_cannot_overwrite_authority(self) -> None:
        self.assertEqual(controlled_learning_output_path("learning/candidates.json"), "learning/candidates.json")
        for unsafe in (
            "candidate.json", "rules/continuous_learning_rules.json", "tests/test_continuous_learning.py",
            ".codex-plugin/plugin.json", "learning/not-json.txt",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(ReportInvariantError):
                controlled_learning_output_path(unsafe)
        protected = [RULES_PATH, PLUGIN / ".codex-plugin" / "plugin.json", Path(__file__)]
        before = {path: sha(path) for path in protected}
        completed = subprocess.run(
            [
                sys.executable, "-B", str(HARVESTER_PATH), "reports/failure.json",
                "--root", str(self.root), "--output", "rules/continuous_learning_rules.json",
            ],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertFalse((self.root / "rules/continuous_learning_rules.json").exists())
        self.assertEqual(before, {path: sha(path) for path in protected})

    def test_rule_catalog_invalid_json_fails_before_semantic_audit(self) -> None:
        text = RULES_PATH.read_text(encoding="utf-8")
        strict = json.loads(text)
        self.assertEqual(QA.audit_rule_catalog(strict)["status"], "pass")
        invalid = text.replace("    },\n    {\n      \"id\": \"ELEC-G049\"", "    }\n    {\n      \"id\": \"ELEC-G049\"", 1)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(invalid)

    def test_rule_catalog_rejects_incomplete_rules_unstable_aliases_or_orphans(self) -> None:
        payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        missing_regression = copy.deepcopy(payload)
        del missing_regression["preventionRules"][0]["requiredRegression"]
        unstable_alias = copy.deepcopy(payload)
        unstable_alias["failureAliases"][0]["alias"] = "Mechanical Not Stable"
        orphan = copy.deepcopy(payload)
        target_rule = orphan["preventionRules"][0]["id"]
        orphan["failureAliases"] = [row for row in orphan["failureAliases"] if row["ruleId"] != target_rule]
        missing_external_review = copy.deepcopy(payload)
        missing_external_review["promotionPolicy"]["requiresExternalAuthenticatedReview"] = False
        wrong_domain = copy.deepcopy(payload)
        wrong_domain["failureAliases"][0]["domain"] = "electronics"
        missing_control = copy.deepcopy(payload)
        missing_control["controls"].pop()
        extra_top_level = copy.deepcopy(payload)
        extra_top_level["selfApproved"] = True
        for candidate in (
            missing_regression, unstable_alias, orphan, missing_external_review,
            wrong_domain, missing_control, extra_top_level,
        ):
            with self.subTest(), self.assertRaises(ReportInvariantError):
                QA.audit_rule_catalog(candidate)

    def test_latest_electronics_and_release_lessons_are_stably_bound(self) -> None:
        payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        rules = {row["id"]: row for row in payload["preventionRules"]}
        aliases = {row["alias"]: row for row in payload["failureAliases"]}
        expected = {
            "electronics.repair_claim_precedes_native_bom_netlist_change": "ELEC-G054",
            "electronics.canonical_private_netlist_separation_missing": "ELEC-G055",
            "electronics.erc_bom_pass_generalized_to_full_system_pass": "ELEC-G046",
            "electronics.dedicated_power_pair_decoupling_missing_with_erc_zero": "ELEC-G032",
            "electronics.thvd2410_sm712_coordination_unqualified": "ELEC-G041",
            "electronics.shield_conductor_collapsed_into_signal_gnd": "ELEC-G042",
            "electronics.connector_exact_opn_pitch_accumulated_error": "ELEC-G042",
            "electronics.full_system_authority_only_covers_analog_subset": "ELEC-G043",
            "electronics.power_contract_ambiguous_continuous_load_shortcut": "ELEC-G044",
            "electronics.usb_vbus_contract_stale_active_high_divider": "ELEC-G051",
            "electronics.q1_family_name_not_exact_orderable_opn": "ELEC-G052",
            "release.stage_gate_matrix_stale_candidate_path_hardcoded": "REL-G033",
            "electronics.drc_warning_severity_downgrade_accepted": "ELEC-G061",
            "electronics.stage_b_legacy_100x80_capacity_reaccepted": "ELEC-G063",
            "electronics.technical_gate_authorization_boolean_true": "ELEC-G064",
            "electronics.stage_a_technical_acceptance_misread_as_fabrication_authorization": "ELEC-G064",
            "electronics.stage_b_reused_compact_legacy_board_without_zone_authority": "ELEC-G063",
            "release.valid_acceptance_targeted_immutable_stage_b_baseline": "REL-G038",
            "release.stage_bc_extra_consumer_entrypoint": "REL-G039",
            "release.source_closure_policy_literals_self_matched": "REL-G039",
            "electronics.hidden_kicad_labels_remained_pdf_text_and_increased_collisions": "ELEC-G065",
            "electronics.physical_series_rewire_preserved_erc_but_dropped_named_native_nets": "ELEC-G065",
            "electronics.independent_label_lane_reroute_increased_pdf_collisions_despite_erc": "ELEC-G065",
        }
        for alias, rule_id in expected.items():
            self.assertEqual(aliases[alias]["ruleId"], rule_id)
            self.assertTrue(rules[rule_id]["requiredRegression"])

    def test_seed_rule_catalog_has_exact_actual_failure_alias_inventory(self) -> None:
        payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        result = QA.audit_rule_catalog(payload)
        aliases = {row["alias"] for row in payload["failureAliases"]}
        self.assertEqual(aliases, EXPECTED_FAILURE_ALIASES)
        self.assertEqual(result["failureAliasCount"], len(EXPECTED_FAILURE_ALIASES))
        self.assertEqual(payload["candidateSafetyLocks"], EXPECTED_CANDIDATE_LOCKS)
        for row in payload["controls"]:
            self.assertTrue(row["requirement"])
            self.assertTrue(row["requiredRegression"])
        for row in payload["preventionRules"]:
            self.assertTrue(row["symptom"])
            self.assertTrue(row["rootCause"])
            self.assertTrue(row["prevention"])
            self.assertTrue(row["requiredRegression"])
        rules_by_id = {row["id"]: row for row in payload["preventionRules"]}
        label_scope_rule = rules_by_id["ELEC-G065"]
        self.assertIn("global/local label scope", label_scope_rule["prevention"])
        self.assertIn("native-topology", label_scope_rule["prevention"])
        self.assertIn("PDF visual QA", label_scope_rule["prevention"])
        self.assertIn(
            "test_stage_a_local_label_substitution_preserves_erc_but_fails_native_topology_and_pdf_qa",
            label_scope_rule["requiredRegression"],
        )
        rendered = json.dumps(payload, ensure_ascii=False).lower()
        self.assertNotIn("acl", rendered)
        aliases_by_name = {row["alias"]: row for row in payload["failureAliases"]}
        self.assertEqual(
            {aliases_by_name[alias]["ruleId"] for alias in (
                "electronics.hidden_kicad_labels_remained_pdf_text_and_increased_collisions",
                "electronics.physical_series_rewire_preserved_erc_but_dropped_named_native_nets",
                "electronics.independent_label_lane_reroute_increased_pdf_collisions_despite_erc",
            )},
            {"ELEC-G065"},
        )
        self.assertNotIn("quota", rendered)


if __name__ == "__main__":
    unittest.main()
