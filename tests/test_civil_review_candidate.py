from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.civil import (  # noqa: E402
    EXPECTED_LOCKS,
    EXTERNAL_WORK_REQUIRED,
    MAPPING_RULE,
    RELEASE_BOUNDARY,
    validate_civil_review_candidate,
)


SCHEMA_PATH = ROOT / "schema" / "aicad-civil-review-candidate.schema.json"


def _write_source(root: Path, source_id: str, kind: str) -> dict:
    relative = f"sources/{source_id.casefold()}.json"
    target = root.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "sourceId": source_id,
            "kind": kind,
            "revision": "CONTROLLED-R1",
            "content": "Controlled civil review fixture; not a production approval.",
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    target.write_bytes(payload)
    return {
        "id": source_id,
        "kind": kind,
        "description": f"Controlled {kind} evidence for civil review.",
        "path": relative,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def valid_candidate(evidence_root: Path) -> dict:
    sources = [
        _write_source(evidence_root, "AUTH_CRS", "coordinate_authority"),
        _write_source(evidence_root, "SURVEY_CTRL", "survey_control"),
        _write_source(evidence_root, "ALIGN_BASIS", "alignment_basis"),
        _write_source(evidence_root, "PROFILE_BASIS", "profile_basis"),
        _write_source(evidence_root, "DRAIN_BASIS", "drainage_basis"),
        _write_source(evidence_root, "UTILITY_REC", "utility_record"),
        _write_source(evidence_root, "GEOTECH_RPT", "geotechnical_report"),
    ]
    return {
        "schema": "aicad_civil_review_candidate_v1",
        "candidateId": "CIVIL_REVIEW_001",
        "project": {
            "name": "Controlled coordination corridor",
            "jurisdiction": {
                "countryCode": "CN",
                "administrativeArea": "Shanghai Municipality",
                "authority": "Declared project review authority",
                "codeBasis": "Project-specific controlled civil design basis revision R1",
            },
            "stage": "preliminary_design_review",
        },
        "coordinateReference": {
            "horizontal": {
                "type": "epsg",
                "epsg": 4547,
                "localGrid": None,
                "datum": "CGCS2000",
                "epoch": {
                    "status": "declared",
                    "value": 2025.0,
                    "sourceId": "AUTH_CRS",
                    "rationale": "Epoch frozen by the controlled coordinate authority source.",
                },
            },
            "vertical": {
                "datum": "1985 National Height Datum",
                "geoid": {
                    "status": "declared",
                    "model": "Project geoid model revision R1",
                    "sourceId": "AUTH_CRS",
                    "rationale": "Geoid model frozen by the coordinate authority source.",
                },
            },
            "localMapping": {
                "drawingUnit": "mm",
                "groundUnit": "m",
                "millimetresPerGroundMetre": 1000,
                "groundScaleFactor": 1.0,
                "rotationDegrees": 0.0,
                "mappingRule": MAPPING_RULE,
                "origin": {
                    "drawingXmm": 0.0,
                    "drawingYmm": 0.0,
                    "groundEastingM": 500000.0,
                    "groundNorthingM": 3400000.0,
                    "groundElevationM": 100.0,
                    "surveyControlId": "CTRL_A",
                },
            },
            "siteBounds": {
                "minEastingM": 499990.0,
                "maxEastingM": 500300.0,
                "minNorthingM": 3399990.0,
                "maxNorthingM": 3400300.0,
                "minElevationM": 90.0,
                "maxElevationM": 120.0,
            },
        },
        "sources": sources,
        "surveyControls": [
            {
                "id": "CTRL_A",
                "eastingM": 500000.0,
                "northingM": 3400000.0,
                "elevationM": 100.0,
                "horizontalDatum": "CGCS2000",
                "verticalDatum": "1985 National Height Datum",
                "observationType": "field_observed",
                "status": "verified",
                "sourceId": "SURVEY_CTRL",
            },
            {
                "id": "CTRL_B",
                "eastingM": 500100.0,
                "northingM": 3400000.0,
                "elevationM": 100.5,
                "horizontalDatum": "CGCS2000",
                "verticalDatum": "1985 National Height Datum",
                "observationType": "field_observed",
                "status": "verified",
                "sourceId": "SURVEY_CTRL",
            },
        ],
        "alignment": {
            "id": "ALIGN_MAIN",
            "sourceId": "ALIGN_BASIS",
            "stationToleranceM": 0.001,
            "joinToleranceM": 0.02,
            "segments": [
                {
                    "id": "SEG_A",
                    "startStationM": 0.0,
                    "endStationM": 100.0,
                    "start": {"eastingM": 500000.0, "northingM": 3400000.0},
                    "end": {"eastingM": 500100.0, "northingM": 3400000.0},
                },
                {
                    "id": "SEG_B",
                    "startStationM": 100.0,
                    "endStationM": 200.0,
                    "start": {"eastingM": 500100.0, "northingM": 3400000.0},
                    "end": {"eastingM": 500200.0, "northingM": 3400000.0},
                },
            ],
        },
        "profile": {
            "id": "PROFILE_MAIN",
            "sourceId": "PROFILE_BASIS",
            "stationToleranceM": 0.001,
            "points": [
                {"stationM": 0.0, "elevationM": 100.0},
                {"stationM": 100.0, "elevationM": 101.0},
                {"stationM": 200.0, "elevationM": 100.5},
            ],
        },
        "drainage": {
            "id": "DRAIN_MAIN",
            "sourceId": "DRAIN_BASIS",
            "flowDirection": "increasing_station",
            "minimumSlope": 0.001,
            "maximumSlope": 0.05,
            "points": [
                {"stationM": 0.0, "invertElevationM": 99.0},
                {"stationM": 100.0, "invertElevationM": 98.0},
                {"stationM": 200.0, "invertElevationM": 97.0},
            ],
        },
        "disciplineSources": {
            "utilitySourceIds": ["UTILITY_REC"],
            "geotechnicalSourceIds": ["GEOTECH_RPT"],
            "limitations": (
                "Utility and geotechnical records are coordination inputs only; field verification, "
                "specialist analysis and construction release remain external."
            ),
        },
        "locks": dict(EXPECTED_LOCKS),
    }


def failure_codes(report: dict) -> set[str]:
    return {row["code"] for row in report["failures"]}


class CivilReviewCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.schema_validator = Draft202012Validator(cls.schema)

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="aicad-civil-review-evidence-"
        )
        self.evidence_root = Path(self._temporary_directory.name)
        self.candidate = valid_candidate(self.evidence_root)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def validate(self, candidate: dict | None = None, evidence_root: Path | None = None) -> dict:
        return validate_civil_review_candidate(
            self.candidate if candidate is None else candidate,
            self.evidence_root if evidence_root is None else evidence_root,
        )

    def test_positive_candidate_matches_schema_and_only_unlocks_review_candidate(self) -> None:
        self.schema_validator.validate(self.candidate)
        report = self.validate()
        self.assertEqual(report["status"], "review_candidate", report)
        self.assertEqual(report["outputClass"], "review_candidate")
        self.assertEqual(report["authorizedOutput"], "review_candidate")
        self.assertTrue(report["reviewCandidateEligible"])
        self.assertFalse(report["failures"])
        self.assertEqual(report["releaseBoundary"], RELEASE_BOUNDARY)
        self.assertTrue(all(value is False for key, value in RELEASE_BOUNDARY.items() if key != "reviewOnly"))
        self.assertEqual(report["externalWorkRequired"], EXTERNAL_WORK_REQUIRED)
        self.assertEqual(report["conclusion"], "civil_review_candidate_only")
        self.assertNotIn("ready", json.dumps(report, ensure_ascii=False).casefold())

    def test_explicit_local_grid_is_accepted_when_authority_bound(self) -> None:
        horizontal = self.candidate["coordinateReference"]["horizontal"]
        horizontal.update(
            {
                "type": "local_grid",
                "epsg": None,
                "localGrid": {
                    "name": "Project Local Grid PLG-01",
                    "definition": "Origin, axes, rotation and scale fixed by AUTH_CRS revision R1.",
                    "authoritySourceId": "AUTH_CRS",
                },
            }
        )
        self.schema_validator.validate(self.candidate)
        self.assertEqual(self.validate()["status"], "review_candidate")

    def test_jurisdiction_and_review_stage_must_be_controlled(self) -> None:
        jurisdiction = self.candidate["project"]["jurisdiction"]
        jurisdiction["countryCode"] = "China"
        jurisdiction["authority"] = "TBD"
        self.candidate["project"]["stage"] = "construction"
        codes = failure_codes(self.validate())
        self.assertTrue(
            {
                "jurisdiction_country_invalid",
                "jurisdiction_declaration_invalid",
                "project_stage_invalid",
            }.issubset(codes)
        )

    def test_controlled_evidence_root_is_mandatory(self) -> None:
        report = validate_civil_review_candidate(self.candidate, None)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("evidence_root_required", failure_codes(report))
        self.assertFalse(report["releaseBoundary"]["productionArtifactExposureGranted"])

    def test_missing_file_and_forged_hash_are_reported_together(self) -> None:
        missing = self.candidate["sources"][0]
        self.evidence_root.joinpath(*missing["path"].split("/")).unlink()
        self.candidate["sources"][1]["sha256"] = "0" * 64
        report = self.validate()
        codes = failure_codes(report)
        self.assertIn("source_file_missing", codes)
        self.assertIn("source_sha256_mismatch", codes)
        self.assertGreaterEqual(report["counts"]["failures"], 2)

    def test_evidence_path_escape_and_absolute_path_are_rejected(self) -> None:
        outside = self.evidence_root.parent / "outside-civil-evidence.txt"
        outside.write_text("outside controlled root", encoding="utf-8")
        try:
            first = self.candidate["sources"][0]
            first["path"] = "../outside-civil-evidence.txt"
            second = self.candidate["sources"][1]
            second["path"] = str(outside.resolve())
            third = self.candidate["sources"][2]
            third["path"] = "sources/alignment.json:alternate-stream"
            report = self.validate()
            unsafe = [row for row in report["failures"] if row["code"] == "source_path_unsafe"]
            self.assertEqual(len(unsafe), 3, report)
        finally:
            outside.unlink(missing_ok=True)

    def test_symlink_or_junction_source_is_rejected_when_supported(self) -> None:
        source = self.candidate["sources"][0]
        target = self.evidence_root.joinpath(*source["path"].split("/"))
        link = target.with_name("authority-link.json")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable on this host")
        source["path"] = "sources/authority-link.json"
        report = self.validate()
        self.assertIn("source_file_reparse_forbidden", failure_codes(report))

    def test_crs_datum_epoch_and_geoid_failures_are_aggregated(self) -> None:
        horizontal = self.candidate["coordinateReference"]["horizontal"]
        horizontal["epsg"] = 42
        horizontal["datum"] = "unknown"
        horizontal["epoch"] = {
            "status": "unresolved",
            "value": None,
            "sourceId": None,
            "rationale": "",
        }
        vertical = self.candidate["coordinateReference"]["vertical"]
        vertical["datum"] = "TBD"
        vertical["geoid"] = {
            "status": "unresolved",
            "model": None,
            "sourceId": None,
            "rationale": "",
        }
        codes = failure_codes(self.validate())
        self.assertTrue(
            {
                "horizontal_crs_invalid",
                "horizontal_datum_invalid",
                "epoch_unresolved",
                "vertical_datum_invalid",
                "geoid_unresolved",
            }.issubset(codes)
        )

    def test_survey_controls_must_be_real_distinct_datum_matched_and_in_bounds(self) -> None:
        first = self.candidate["surveyControls"][0]
        first["observationType"] = "design_assumed"
        first["horizontalDatum"] = "WGS84"
        first["eastingM"] = 999999.0
        self.candidate["surveyControls"].pop()
        self.candidate["coordinateReference"]["localMapping"]["origin"]["surveyControlId"] = "MISSING"
        codes = failure_codes(self.validate())
        self.assertTrue(
            {
                "survey_control_count_insufficient",
                "survey_control_not_real_verified",
                "survey_control_datum_mismatch",
                "survey_control_outside_site_bounds",
                "local_origin_control_missing",
            }.issubset(codes)
        )

    def test_origin_must_match_referenced_control_and_mm_ground_mapping_is_exact(self) -> None:
        mapping = self.candidate["coordinateReference"]["localMapping"]
        mapping["origin"]["drawingXmm"] = 10.0
        mapping["origin"]["groundEastingM"] += 1.0
        mapping["millimetresPerGroundMetre"] = 1
        codes = failure_codes(self.validate())
        self.assertIn("local_origin_not_zero", codes)
        self.assertIn("local_origin_control_mismatch", codes)
        self.assertIn("local_mapping_invalid", codes)

    def test_alignment_station_and_geometry_breaks_are_both_reported(self) -> None:
        second = self.candidate["alignment"]["segments"][1]
        second["startStationM"] = 105.0
        second["start"]["eastingM"] = 500110.0
        codes = failure_codes(self.validate())
        self.assertIn("alignment_station_discontinuity", codes)
        self.assertIn("alignment_geometry_discontinuity", codes)

    def test_profile_station_order_and_extent_are_checked_without_forcing_elevation_monotonicity(self) -> None:
        report = self.validate()
        self.assertNotIn("profile_station_non_monotonic", failure_codes(report))
        self.candidate["profile"]["points"][0]["stationM"] = -10.0
        self.candidate["profile"]["points"][2]["stationM"] = 50.0
        codes = failure_codes(self.validate())
        self.assertIn("profile_station_outside_alignment", codes)
        self.assertIn("profile_station_non_monotonic", codes)

    def test_drainage_station_monotonicity_uphill_and_slope_are_checked(self) -> None:
        points = self.candidate["drainage"]["points"]
        points[1]["invertElevationM"] = 99.2
        points[2]["stationM"] = 90.0
        codes = failure_codes(self.validate())
        self.assertIn("drainage_uphill", codes)
        self.assertIn("drainage_slope_out_of_range", codes)
        self.assertIn("drainage_station_non_monotonic", codes)

    def test_utility_and_geotechnical_sources_are_required_and_kind_checked(self) -> None:
        discipline = self.candidate["disciplineSources"]
        discipline["utilitySourceIds"] = []
        discipline["geotechnicalSourceIds"] = ["UTILITY_REC"]
        codes = failure_codes(self.validate())
        self.assertIn("discipline_source_missing", codes)
        self.assertIn("discipline_source_invalid", codes)

    def test_open_release_lock_never_grants_production_or_professional_release(self) -> None:
        self.candidate["locks"]["productionRelease"] = True
        report = self.validate()
        self.assertIn("safety_locks_invalid", failure_codes(report))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["releaseBoundary"]["productionArtifactExposureGranted"])
        self.assertFalse(report["releaseBoundary"]["professionalReleaseGranted"])
        self.assertFalse(report["releaseBoundary"]["constructionUseGranted"])

    def test_many_independent_faults_are_returned_in_one_report(self) -> None:
        self.candidate["project"]["stage"] = "construction"
        self.candidate["coordinateReference"]["horizontal"]["epsg"] = None
        self.candidate["surveyControls"] = []
        self.candidate["alignment"]["segments"] = []
        self.candidate["profile"]["points"] = []
        self.candidate["drainage"]["points"] = []
        self.candidate["disciplineSources"]["utilitySourceIds"] = []
        self.candidate["locks"]["professionalRelease"] = True
        report = self.validate()
        self.assertEqual(report["status"], "blocked")
        self.assertGreaterEqual(len(failure_codes(report)), 8, report)
        self.assertIsNone(report.get("authorizedOutput"))
        self.assertFalse(report["reviewCandidateEligible"])


if __name__ == "__main__":
    unittest.main()
