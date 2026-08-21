from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
import unittest
from collections import Counter
import tempfile
from pathlib import Path, PurePosixPath

import ezdxf
from build123d import import_brep
from PIL import Image


REPOSITORY = Path(__file__).resolve().parents[1]
ROOT = REPOSITORY / "projects" / "magic-wand" / "mechanical" / "factory-rfq"
MAGIC_ROOT = REPOSITORY / "projects" / "magic-wand"
REPORTS = ROOT / "reports"
OUTPUTS = ROOT / "outputs"

PART_IDS = (
    "MW-M-001A",
    "MW-M-001B",
    "MW-M-002",
    "MW-M-003",
    "MW-M-004",
    "MW-M-005",
    "MW-P-001",
    "MW-M-101",
    "MW-M-102",
)
ASSEMBLY_COMPONENT_COUNTS = {"MW-A-001": 7, "MW-A-101": 2}
PART_NATIVE_OUTPUT_ROLES = {
    "step",
    "manufacturingDrawing",
    "drawingPreview",
    "modelPreview",
}
ASSEMBLY_NATIVE_OUTPUT_ROLES = {
    "step",
    "assemblyDrawing",
    "explodedDrawing",
    "sectionDrawing",
    "assemblyPreview2d",
    "assemblyPreview3d",
    "assemblyWorkInstruction",
    "inspectionPlan",
    "moldingInput",
    "bom",
    "positions",
}
REQUIRED_DXF_LAYERS = {
    "BORDER",
    "OUTLINE",
    "VISIBLE",
    "HIDDEN",
    "CENTER",
    "DIMENSION",
    "SECTION",
    "NOTES",
    "TITLE_BLOCK",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_root_artifact(record: dict) -> Path:
    path = ROOT / record["path"]
    assert path.is_file(), record
    assert path.stat().st_size == record["sizeBytes"]
    assert sha256(path) == record["sha256"]
    return path


def verify_magic_artifact(record: dict) -> Path:
    relative = PurePosixPath(record["path"])
    assert not relative.is_absolute()
    assert ".." not in relative.parts
    path = MAGIC_ROOT / Path(*relative.parts)
    assert path.is_file(), record
    assert path.stat().st_size == record["size"]
    assert sha256(path) == record["sha256"]
    return path


def test_release_inventory_and_temporary_cleanup() -> None:
    design = load_json(ROOT / "factory-design-input.json")
    assert set(design["parts"]) == set(PART_IDS)
    assert len(list((OUTPUTS / "2d").glob("*.dxf"))) == 16
    assert len(list((OUTPUTS / "3d").glob("*.SLDPRT"))) == 9
    assert len(list((OUTPUTS / "3d").glob("*.SLDASM"))) == 2
    assert len(list((OUTPUTS / "3d").glob("*.step"))) == 13
    assert len(list((REPORTS / "geometry").glob("*.brep"))) == 9
    assert len(list((OUTPUTS / "previews").glob("*.png"))) == 29

    forbidden_tokens = ("test_upper", "test_asm", "_probe", "_patch_probe", "native-input")
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT).as_posix().lower()
        assert not any(token in relative for token in forbidden_tokens), relative
        assert path.suffix.lower() not in {".err", ".glb"}, relative
        assert path.name != "__pycache__", relative


def test_all_authoritative_breps_are_valid_single_solids() -> None:
    breps = sorted((REPORTS / "geometry").glob("*.brep"))
    assert len(breps) == 9
    assert {path.name.split("_")[0] for path in breps} == set(PART_IDS)
    for path in breps:
        shape = import_brep(path)
        assert shape.is_valid, path.name
        assert len(shape.solids()) == 1, path.name
        assert shape.volume > 0.0, path.name


def test_true_brep_sections_cover_critical_features() -> None:
    report = load_json(REPORTS / "brep-section-intersection-report.json")
    assert report["schema"] == "aicad_factory_brep_section_intersections_v2"
    assert report["passed"] is True
    assert report["missingFeatureIds"] == []
    assert set(report["requiredFeatureIds"]) <= set(report["coveredFeatureIds"])
    assert len(report["sections"]) >= 14
    for section in report["sections"]:
        lower, upper = section["subjectBboxAxisRange"]
        assert lower <= section["coordinate"] <= upper, section["sectionId"]
        assert section["planeWithinSubjectBbox"] is True
        assert section["decorativeHatchUsed"] is False
        assert section["sourceType"] == "build123d BREP boolean intersection"
        intersection = section["intersection"]
        assert intersection["valid"] is True
        assert intersection["solid_count"] > 0
        assert intersection["volume_mm3"] > 0.0
        assert intersection["edge_count"] > 0
        assert section["featureIdsCovered"]


def test_dxf_semantic_layers_and_text_frame_closure() -> None:
    audit = load_json(REPORTS / "drawing-text-frame-audit.json")
    assert audit["schema"] == "aicad_factory_drawing_text_frame_audit_v3"
    assert audit["drawing_count"] == 16
    assert audit["passed"] is True
    assert audit["overflow_count"] == 0
    assert audit["truncated_count"] == 0
    assert audit["undersize_count"] == 0
    assert audit["minimum_print_text_height_mm"] >= 1.8
    assert all(frame["overflow"] is False for frame in audit["frames"])
    assert all(frame["bbox_method"] == "ezdxf_actual_glyph_extents" for frame in audit["frames"])
    assert all(row["textClosure"] and not row["truncated"] for row in audit["inputClosure"])
    assert all(row["normalizedInputSha256"] == row["normalizedEmittedSha256"] for row in audit["inputClosure"])

    layer_contract = audit["required_layers"]
    dxfs = sorted((OUTPUTS / "2d").glob("*.dxf"))
    assert len(dxfs) == 16
    for path in dxfs:
        document = ezdxf.readfile(path)
        names = {layer.dxf.name for layer in document.layers}
        assert REQUIRED_DXF_LAYERS <= names, path.name
        for name in REQUIRED_DXF_LAYERS:
            layer = document.layers.get(name)
            expected = layer_contract[name]
            assert layer.dxf.color == expected["color"], (path.name, name)
            assert layer.dxf.linetype == expected["linetype"], (path.name, name)
            assert layer.dxf.lineweight == expected["lineweight"], (path.name, name)
        texts = list(document.modelspace().query("TEXT MTEXT"))
        assert texts, path.name
        assert min(float(entity.dxf.height) for entity in texts) >= 1.8


def test_feature_bound_dimension_catalog_is_complete() -> None:
    catalog = load_json(REPORTS / "feature-dimension-catalog.json")
    assert catalog["schema"] == "aicad_feature_bound_factory_dimension_catalog_v1"
    subjects = {row["subjectId"]: row for row in catalog["subjects"]}
    assert set(subjects) == set(PART_IDS)
    for subject_id, subject in subjects.items():
        assert subject["rowCount"] == len(subject["rows"])
        assert subject["rowCount"] >= 8
        feature_ids = [row["featureId"] for row in subject["rows"]]
        assert len(feature_ids) == len(set(feature_ids))
        characteristics = {row["characteristic"] for row in subject["rows"]}
        assert "DATUM SYSTEM" in characteristics
        assert "BREP ENVELOPE" in characteristics
        for row in subject["rows"]:
            assert row["locationXYZ"]
            assert row["source"]
            assert row["geometryProbe"]
    for subject_id in set(PART_IDS) - {"MW-P-001"}:
        characteristics = {row["characteristic"] for row in subjects[subject_id]["rows"]}
        assert "MOLD PULL / PARTING" in characteristics
        assert "GENERAL DRAFT / RADII" in characteristics
        assert "SIDE ACTIONS" in characteristics


def test_solidworks_part_native_reopen_and_hash_closure() -> None:
    for part_id in PART_IDS:
        raw_path = REPORTS / "native" / f"{part_id}_solidworks-execution.json"
        raw_text = raw_path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        assert raw["status"] == "pass"
        assert raw["nativeTool"]["version"] == "34.0.0"
        assert raw["nativeTool"]["nativeExecution"] is True
        assert "executable" not in raw["nativeTool"]
        assert not re.search(r"(?i)\b[A-Z]:[\\/]", raw_text)
        assert raw["nativeReopen"]["errorCode"] == 0
        assert raw["nativeReopen"]["warningCode"] == 0
        assert raw["nativeReopen"]["warningNames"] == []
        assert raw["nativeReopen"]["bodyCount"] == 1
        assert raw["source"]["metrics"]["valid"] is True
        assert raw["source"]["metrics"]["solidCount"] == 1
        assert raw["finalStep"]["metrics"]["valid"] is True
        assert raw["finalStep"]["metrics"]["solidCount"] == 1
        verify_root_artifact(raw["source"])
        verify_root_artifact(raw["nativeCad"])
        verify_root_artifact(raw["finalStep"])

        core = load_json(REPORTS / "native" / f"{part_id}_native-reopen-log.json")
        assert core["schema"] == "aicad_native_tool_execution_log_v1"
        assert core["gate"] == "mechanical_part_native_reopen"
        assert core["status"] == "pass"
        assert set(core["inputSha256ByRole"]) == {"nativeCad"}
        assert set(core["outputSha256ByRole"]) == PART_NATIVE_OUTPUT_ROLES


def test_solidworks_assemblies_are_resolved_and_transform_closed() -> None:
    for assembly_id, component_count in ASSEMBLY_COMPONENT_COUNTS.items():
        raw_path = REPORTS / "native" / f"{assembly_id}_solidworks-execution.json"
        raw_text = raw_path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        assert raw["status"] == "pass"
        assert raw["nativeTool"]["version"] == "34.0.0"
        assert "executable" not in raw["nativeTool"]
        assert not re.search(r"(?i)\b[A-Z]:[\\/]", raw_text)
        assert raw["nativeReopen"]["errorCode"] == 0
        assert raw["nativeReopen"]["warningCode"] == 0
        assert raw["nativeReopen"]["warningNames"] == []
        assert raw["nativeReopen"]["componentCount"] == component_count
        assert len(raw["componentClosure"]) == component_count
        assert all(row["suppressionStateName"] == "swComponentFullyResolved" for row in raw["componentClosure"])
        assert all(row["referencedConfiguration"] for row in raw["componentClosure"])
        assert all(row["transformMatches"] for row in raw["componentClosure"])
        assert all(max(abs(value) for value in row["translationDeltaMm"]) <= 1e-6 for row in raw["componentClosure"])
        assert raw["finalStep"]["metrics"]["valid"] is True
        assert raw["finalStep"]["metrics"]["solidCount"] == component_count
        verify_root_artifact(raw["nativeAssembly"])
        verify_root_artifact(raw["finalStep"])
        verify_root_artifact(raw["positionsEvidence"])
        verify_root_artifact(raw["interferenceEvidence"])

        core = load_json(REPORTS / "native" / f"{assembly_id}_native-reopen-log.json")
        assert core["gate"] == "mechanical_assembly_native_reopen"
        assert core["status"] == "pass"
        assert set(core["inputSha256ByRole"]) == {"nativeAssembly"}
        assert set(core["outputSha256ByRole"]) == ASSEMBLY_NATIVE_OUTPUT_ROLES


def test_exact_brep_interference_reports_are_closed() -> None:
    allowed = {"clear", "contact_no_positive_volume", "intended_process_interference"}
    for assembly_id in ASSEMBLY_COMPONENT_COUNTS:
        detail = load_json(REPORTS / f"{assembly_id}_brep-interference-report.json")
        assert detail["schema"] == "aicad_factory_brep_interference_report_v2"
        assert detail["passed"] is True
        assert detail["unexpectedInterferenceCount"] == 0
        assert detail["algorithm"] == "exact Open CASCADE BREP common-volume and minimum-distance evaluation"
        assert detail["rows"]
        assert all(row["classification"] in allowed for row in detail["rows"])
        core = load_json(REPORTS / "native" / f"{assembly_id}_interference-log.json")
        assert core["gate"] == "mechanical_assembly_interference"
        assert core["status"] == "pass"
        assert core["outputSha256ByRole"] == {}


def test_source_bound_previews_and_1100px_legibility() -> None:
    manifest = load_json(REPORTS / "visual-preview-manifest.json")
    assert manifest["schema"] == "aicad_factory_visual_preview_manifest_v1"
    rows = manifest["previews"]
    assert len(rows) == 29
    assert {row["subjectId"] for row in rows} == set(PART_IDS) | set(ASSEMBLY_COMPONENT_COUNTS)
    for row in rows:
        preview_path = ROOT / row["path"]
        source_path = ROOT / row["previewOf"]
        assert preview_path.is_file()
        assert source_path.is_file()
        assert sha256(preview_path) == row["previewSha256"]
        assert sha256(source_path) == row["sourceSha256"]
        with Image.open(preview_path) as image:
            assert image.width >= 2000 and image.height >= 1500
            assert image.getbbox() is not None
            if row["kind"] == "drawingPreview":
                assert row["rendererStyle"] == "high-contrast-semantic-layers-bold-text-v2"
                rgb = image.convert("RGB")
                colours = Counter(rgb.getdata())
                assert colours[(0, 0, 0)] > 100
                assert colours[(25, 31, 38)] > 100
                semantic_counts = sum(
                    colours[colour]
                    for colour in ((72, 82, 92), (0, 86, 102), (16, 67, 128), (145, 24, 31))
                )
                assert semantic_counts > 500
                fitted = rgb.copy()
                fitted.thumbnail((1100, 1100), Image.Resampling.LANCZOS)
                technical_strip = fitted.crop((0, int(fitted.height * 0.72), fitted.width, fitted.height))
                dark_pixels = sum(1 for r, g, b in technical_strip.getdata() if max(r, g, b) < 150)
                assert dark_pixels > 500


def test_assembly_bom_awi_inspection_and_molding_documents() -> None:
    for assembly_id, component_count in ASSEMBLY_COMPONENT_COUNTS.items():
        documents = OUTPUTS / "documents"
        bom = load_json(documents / f"{assembly_id}_manufacturing-bom.json")
        positions = load_json(documents / f"{assembly_id}_assembly-positions.json")
        molding = load_json(documents / f"{assembly_id}_molding-input.json")
        assert bom["schema"] == "aicad_manufacturing_bom_v1"
        assert len(bom["rows"]) == component_count
        assert positions["schema"] == "aicad_assembly_positions_v1"
        assert len(positions["instances"]) == component_count
        assert molding["schema"] == "aicad_molding_input_v1"
        assert len(molding["toolingInputs"]) == 7
        for suffix in ("assembly-work-instruction.pdf", "inspection-plan.pdf"):
            pdf = documents / f"{assembly_id}_{suffix}"
            assert pdf.stat().st_size > 1000
            assert pdf.read_bytes().startswith(b"%PDF")


def test_factory_delivery_manifest_is_explicit_and_hash_closed() -> None:
    delivery = load_json(REPORTS / "factory-delivery-manifest.json")
    source = load_json(REPORTS / "mechanical-source-manifest.json")
    assert delivery["schema"] == "aicad_magic_wand_mechanical_factory_delivery_manifest_v1"
    assert source["schema"] == "aicad_magic_wand_mechanical_source_manifest_v1"
    delivery_copy = dict(delivery)
    source_copy = dict(source)
    delivery_copy.pop("schema")
    source_copy.pop("schema")
    assert delivery_copy == source_copy
    assert delivery["status"] in {"candidate", "frozen"}
    assert delivery["pathBasis"] == "projects/magic-wand"
    assert len(delivery["parts"]) == 9
    assert len(delivery["assemblies"]) == 2
    assert {row["subjectId"] for row in delivery["parts"]} == set(PART_IDS)
    assert {row["subjectId"] for row in delivery["assemblies"]} == set(ASSEMBLY_COMPONENT_COUNTS)
    for subject in delivery["parts"] + delivery["assemblies"]:
        assert subject["revision"] == delivery["revision"]
        assert subject["process"]
        for role, record in subject["artifacts"].items():
            verify_magic_artifact(record)
            if role in {"drawingPreview", "modelPreview", "assemblyPreview2d", "assemblyPreview3d"}:
                assert record["subjectId"] == subject["subjectId"]
                assert record["revision"] == delivery["revision"]
                assert record["previewOfRole"]
                assert len(record["sourceSha256"]) == 64
        assert subject["previews"]
        for preview in subject["previews"]:
            verify_magic_artifact(preview)
            source_path = MAGIC_ROOT / Path(*PurePosixPath(preview["previewOfPath"]).parts)
            assert source_path.is_file()
            assert sha256(source_path) == preview["sourceSha256"]
            assert preview["previewOfRole"]


def test_wand_finalizer_contract_and_zero_drift_are_fail_closed() -> None:
    module_path = ROOT / "source" / "finalize_wand_release.py"
    spec = importlib.util.spec_from_file_location("finalize_wand_release_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous_bytecode_policy = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_bytecode_policy
    assert module.INTERFACE_SCHEMA == "aicad_wand_electromechanical_interface_v1"
    assert module.FROZEN_STATUS == "FROZEN"

    with tempfile.TemporaryDirectory(prefix="wand-finalizer-") as temporary:
        repository = Path(temporary)
        interface_path = repository / "interfaces" / "wand-electromechanical-interface.json"

        def write_document(path: Path, value: dict) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

        def artifact(relative: str, payload: bytes, kind: str) -> dict:
            path = repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "kind": kind,
            }

        def authority(record: dict) -> dict:
            ref = record["ref"]
            source_artifacts = []
            if ref == "J1":
                source_artifacts.extend(
                    [
                        artifact(f"sources/{ref}-drawing.pdf", b"J1 controlled drawing", "controlled_2d_drawing"),
                        artifact(f"sources/{ref}-model.step", b"J1 controlled model", "controlled_3d_step"),
                    ]
                )
            elif ref == "U1":
                source_artifacts.extend(
                    [
                        artifact(f"sources/{ref}-datasheet.pdf", b"U1 controlled datasheet", "controlled_2d_drawing"),
                        dict(record["mechanicalKeepoutSolid"]),
                    ]
                )
            else:
                source_artifacts.append(
                    artifact(
                        f"sources/{ref}-drawing.pdf",
                        f"{ref} controlled source".encode(),
                        "controlled_2d_drawing",
                    )
                )
            extracted_fields = list(module.AUTHORITY_FIELDS_BY_REF[ref])
            extracted = {
                field: json.loads(json.dumps(record[field])) for field in extracted_fields
            }
            if ref == "J1":
                extracted["panelOpening"].pop("authoritySha256", None)
                drawing_fields = [
                    field
                    for field in extracted_fields
                    if field not in {"bodyEnvelopeMm", "matingEnvelopeMm", "unmateClearanceMm"}
                ]
                extraction = [
                    {"documentNumber": "SJ121837", "page": 2, "section": "recommended PCB and shell stakes", "sourceArtifactSha256": source_artifacts[0]["sha256"], "extractedFields": drawing_fields},
                    {"documentNumber": "J1-STEP", "page": "3D model", "section": "body and mating envelopes", "sourceArtifactSha256": source_artifacts[1]["sha256"], "extractedFields": ["bodyEnvelopeMm", "matingEnvelopeMm", "unmateClearanceMm"]},
                ]
            else:
                extraction = [{
                    "documentNumber": f"{ref}-DOC",
                    "page": 1,
                    "section": "mechanical dimensions",
                    "sourceArtifactSha256": source_artifacts[-1]["sha256"],
                    "extractedFields": extracted_fields,
                }]
            value = {
                "schema": "aicad_component_mechanical_authority_v1",
                "status": "controlled",
                "kind": "component_mechanical_authority",
                "releaseBlocked": False,
                "manufacturer": record["manufacturer"],
                "mpn": record["mpn"],
                "sourceArtifacts": source_artifacts,
                "extractionEvidence": extraction,
                "extractedMechanical": extracted,
            }
            payload = (json.dumps(value, indent=2) + "\n").encode()
            return artifact(f"authorities/{ref}.json", payload, "component_mechanical_authority")

        def common_ref(
            ref: str,
            manufacturer: str,
            mpn: str,
            source_xy: tuple[float, float],
            y_height: float = 1.6,
        ) -> dict:
            return {
                "ref": ref,
                "manufacturer": manufacturer,
                "mpn": mpn,
                "sourceCenterMm": list(source_xy),
                "caseCenterMm": [source_xy[0] - 7.5, y_height, source_xy[1] + 9.0],
                "rotationDeg": 0.0,
                "bodyEnvelopeMm": [1.0, 1.0, 1.0],
                "maximumHeightMm": 1.0,
                "padOrHoleGeometry": {"synthetic": True},
                "roundTripCoordinateEvidence": {"passed": True, "toleranceMm": 1e-6},
            }

        source_board = artifact("artifacts/wand.kicad_pcb", b"board", "kicad_board")
        source_routes = artifact("artifacts/wand-routes.json", b"routes", "frozen_routes")
        source_routes["sourceBoard"] = dict(source_board)
        native_drc = artifact("artifacts/wand-native-drc.json", b"drc", "kicad_native_drc")
        native_drc.update(
            {
                "violations": 0,
                "unconnected": 0,
                "footprintErrors": 0,
                "exclusions": 0,
                "suppressions": 0,
                "ignoredRules": [],
            }
        )

        sw1 = common_ref("SW1", "ALPS Alpine", "SKQGAFE010", (7.5, 63.0))
        sw1.update(
            {
                "rotationDeg": 90.0,
                "bodyEnvelopeMm": [5.2, 5.2, 1.5],
                "freeHeightMm": 1.5,
                "travelMm": 0.25,
                "forceN": 0.98,
                "actuatorCenterCaseMm": [0.0, 3.1, 72.0],
                "actuationNormal": "+Y",
                "fourPhysicalPadGeometry": [{"name": str(index)} for index in range(1, 5)],
                "padOrHoleGeometry": [{"name": str(index)} for index in range(1, 5)],
                "logicalTerminalPairMap": [["1", "2"], ["3", "4"]],
                "allowedPreloadMm": 0.02,
                "allowedOvertravelMm": 0.03,
            }
        )
        j1 = common_ref("J1", "JAE", "DX07S016JA1R1500", (12.5, 38.0))
        j1.update(
            {
                "rotationDeg": 90.0,
                "officialDrawingNumber": "SJ121837",
                "sixteenContactPads": [{"name": name} for name in sorted(module.CONTACT_NAMES)],
                "fourShellDipStakes": [{"type": "DIP"} for _ in range(4)],
                "locatingHoles": [{"diameterMm": 0.7}],
                "matingFaceMm": [13.5, 2.5, 47.0],
                "matingDirection": "+X",
                "bodyEnvelopeMm": [8.0, 7.0, 3.5],
                "matingEnvelopeMm": [10.0, 8.0, 4.0],
                "unmateClearanceMm": 15.0,
                "panelOpening": {
                    "ref": "J1",
                    "wallAxis": "+X",
                    "caseCenterMm": [13.5, 2.5, 47.0],
                    "widthMm": 9.5,
                    "heightMm": 3.5,
                    "cornerRadiusMm": 0.8,
                    "cutDepthMm": 4.0,
                    "tolerancesMm": {"profile": 0.15},
                    "matingDirection": "+X",
                    "authoritySha256": "",
                },
                "padOrHoleGeometry": {
                    "contactPads": [{"name": name} for name in sorted(module.CONTACT_NAMES)],
                    "shellDipStakes": [{"type": "DIP"} for _ in range(4)],
                    "locatingHoles": [{"diameterMm": 0.7}],
                },
            }
        )
        j2 = common_ref("J2", "JST", "SM03B-SRSS-TB(LF)(SN)", (7.5, 50.0))
        j2.update(
            {
                "matingDirection": "side_entry",
                "padOrHoleGeometry": {
                    "signalPads": [{"name": str(index)} for index in range(1, 4)],
                    "reinforcementPads": [{"name": "MP1"}, {"name": "MP2"}],
                },
            }
        )
        j3 = common_ref("J3", "JST", "SM02B-SRSS-TB(LF)(SN)", (7.5, 56.0))
        j3.update(
            {
                "matingDirection": "side_entry",
                "padOrHoleGeometry": {
                    "signalPads": [{"name": str(index)} for index in range(1, 3)],
                    "reinforcementPads": [{"name": "MP1"}, {"name": "MP2"}],
                },
            }
        )
        u1 = common_ref("U1", "u-blox", "NINA-B302-00B-00", (7.5, 10.5))
        u1.update(
            {
                "antennaFeedCorner": "pins_15_16_at_host_corner",
                "antennaDirection": "outward",
                "fullGroundEvidence": artifact("evidence/u1-ground.json", b"ground", "native_ground_evidence"),
                "mechanicalKeepoutSolid": artifact("evidence/u1-keepout.brep", b"keepout", "brep_keepout"),
                "caseClearanceEvidence": artifact("evidence/u1-case.json", b"case", "case_clearance_evidence"),
                "bodyEnvelopeMm": [10.0, 15.0, 4.23],
                "maximumHeightMm": 4.23,
            }
        )
        l1 = common_ref("L1", "Coilcraft", "XFL4020-222MEC", (7.5, 30.0))
        l1.update({"bodyEnvelopeMm": [4.3, 4.3, 2.1], "maximumHeightMm": 2.1})
        f1 = common_ref("F1", "Bourns", "MF-FSMF050X-2", (7.5, 34.0))
        f1.update({"bodyEnvelopeMm": [1.85, 1.05, 1.0], "maximumHeightMm": 1.0})
        h1 = common_ref("H1", "PCB FAB", "NPTH-D2.4", (7.5, 19.5), 0.0)
        h1.update(
            {
                "finishedDiameterMm": 2.4,
                "type": "NPTH",
                "plating": False,
                "bodyEnvelopeMm": [2.4, 2.4, 1.6],
                "maximumHeightMm": 0.0,
                "padOrHoleGeometry": {"finishedDiameterMm": 2.4, "type": "NPTH"},
            }
        )
        h2 = common_ref("H2", "PCB FAB", "NPTH-D2.4", (7.5, 77.0), 0.0)
        h2.update(
            {
                "finishedDiameterMm": 2.4,
                "type": "NPTH",
                "plating": False,
                "bodyEnvelopeMm": [2.4, 2.4, 1.6],
                "maximumHeightMm": 0.0,
                "padOrHoleGeometry": {"finishedDiameterMm": 2.4, "type": "NPTH"},
            }
        )

        all_refs = [sw1, j1, j2, j3, u1, l1, f1, h1, h2]
        for record in all_refs:
            record["authorityEvidence"] = authority(record)
        j1["panelOpening"]["authoritySha256"] = j1["authorityEvidence"]["sha256"]

        interface = {
            "schema": module.INTERFACE_SCHEMA,
            "status": module.FROZEN_STATUS,
            "revision": "TEST",
            "authorityReleaseBlockedRefs": 0,
            "sourceBoard": source_board,
            "sourceRoutes": source_routes,
            "nativeDrc": native_drc,
            "coordinateContract": {
                "source": module.INPUT_FIELD_CONTRACT["coordinateContract"]["source"],
                "forwardTransform": module.INPUT_FIELD_CONTRACT["coordinateContract"]["forwardTransform"],
                "inverseTransform": module.INPUT_FIELD_CONTRACT["coordinateContract"]["inverseTransform"],
                "roundTripTests": [{"passed": True}],
            },
            "boardDimensionsMm": {
                "width": 15.0,
                "height": 80.0,
                "thickness": 1.6,
                "tolerances": {"width": 0.1, "height": 0.1, "thickness": 0.1},
            },
            "refs": all_refs,
            "absentRefs": ["H3", "H4"],
            "consistencyEvidence": {
                "boardShaMatchesRoutes": True,
                "roundTripCoordinateTests": True,
                "authorityHashClosure": True,
                "mechanicalRequirementMirrorChecks": True,
            },
            "mechanicalRequirements": {
                "rearCapChangeRequired": False,
                "pcbRetentionProcess": {
                    "type": "nonmetallic_heat_stake",
                    "holeRefs": ["H1", "H2"],
                    "metallicFastenersAllowed": False,
                    "minimumAntennaMetalClearanceMm": 10.0,
                    "supplierProcessValidationRequired": True,
                },
                "buttonStack": {
                    "switchRef": "SW1",
                    "actuatorCenterCaseMm": [0.0, 3.1, 72.0],
                    "actuationNormal": "+Y",
                    "switchFreeTopCaseYmm": 3.1,
                    "switchTravelMm": 0.25,
                    "allowedPreloadMm": 0.02,
                    "allowedOvertravelMm": 0.03,
                    "independentHardStopRequired": True,
                    "bottomStopClearanceRequired": True,
                },
                "boardChannel": {
                    "boardEnvelopeMm": [15.0, 80.0, 1.6],
                    "bCuSupportYmm": 0.0,
                    "fCuYmm": 1.6,
                    "caseZStartMm": 9.0,
                    "datumScheme": "one_side_width_datum_opposite_clearance_one_axial_stop",
                    "minimumNominalWidthClearancePerSideMm": 0.2,
                    "minimumNominalAxialClearanceMm": 0.5,
                    "positiveWorstCaseClearanceRequired": True,
                },
                "j1PanelOpening": dict(j1["panelOpening"]),
                "ninaMechanicalKeepout": {
                    "ref": "U1",
                    "artifact": dict(u1["mechanicalKeepoutSolid"]),
                    "minimumHighLargeMetalClearanceMm": 10.0,
                    "minimumCasingClearanceMm": 5.0,
                    "forbiddenClasses": [
                        "metal_fastener",
                        "conductive_coating",
                        "battery_cell",
                        "shield_can",
                        "cable_bundle",
                        "GFRP_spine",
                    ],
                    "fullGroundRequired": True,
                    "rearCapIntersectionRequiresChange": False,
                },
            },
        }
        write_document(interface_path, interface)
        validated = module.validate_wand_interface(repository, interface_path)
        assert validated["rearCapChangeRequired"] is False
        assert module.changed_subjects(validated) == (*module.DIRECT_CHANGED_PARTS, "MW-A-001")

        # An authority JSON cannot self-sign arbitrary values: its real source
        # file SHA and its document/page/section field extraction must close.
        sw1_evidence = sw1["authorityEvidence"]
        sw1_authority_path = repository / sw1_evidence["path"]
        sw1_authority = json.loads(sw1_authority_path.read_text(encoding="utf-8"))
        sw1_source_path = repository / sw1_authority["sourceArtifacts"][0]["path"]
        sw1_source_original = sw1_source_path.read_bytes()
        sw1_source_path.write_bytes(b"X" + sw1_source_original[1:])
        try:
            module.validate_wand_interface(repository, interface_path)
        except ValueError as exc:
            assert "sourceArtifacts[0] SHA-256 mismatch" in str(exc)
        else:
            raise AssertionError("tampered real authority source was not rejected")
        sw1_source_path.write_bytes(sw1_source_original)

        j2_evidence = j2["authorityEvidence"]
        j2_authority_path = repository / j2_evidence["path"]
        j2_authority_original = j2_authority_path.read_bytes()
        j2_authority = json.loads(j2_authority_original.decode("utf-8"))
        j2_authority["extractionEvidence"][0]["extractedFields"].remove("matingDirection")
        j2_authority_mutated = (json.dumps(j2_authority, indent=2) + "\n").encode()
        j2_authority_path.write_bytes(j2_authority_mutated)
        j2_evidence_original = dict(j2_evidence)
        j2_evidence.update(
            {
                "size": len(j2_authority_mutated),
                "sha256": hashlib.sha256(j2_authority_mutated).hexdigest(),
            }
        )
        write_document(interface_path, interface)
        try:
            module.validate_wand_interface(repository, interface_path)
        except ValueError as exc:
            assert "does not cover mechanical fields" in str(exc)
        else:
            raise AssertionError("missing extracted mechanical field was not rejected")
        j2_authority_path.write_bytes(j2_authority_original)
        j2_evidence.clear()
        j2_evidence.update(j2_evidence_original)
        write_document(interface_path, interface)
        module.validate_wand_interface(repository, interface_path)

        interface["status"] = "CANDIDATE"
        write_document(interface_path, interface)
        try:
            module.validate_wand_interface(repository, interface_path)
        except ValueError as exc:
            assert "status must be exactly FROZEN" in str(exc)
        else:
            raise AssertionError("candidate wand interface was not rejected")

        try:
            module.assert_zero_drift({"MW-M-004.step": "before"}, {"MW-M-004.step": "after"})
        except RuntimeError as exc:
            assert "SHA drift" in str(exc)
        else:
            raise AssertionError("immutable artifact drift was not rejected")


def test_receiver_interface_freeze_is_fail_closed() -> None:
    design = load_json(ROOT / "factory-design-input.json")
    receiver = design["interfaces"]["receiver_enclosure"]
    delivery = load_json(REPORTS / "factory-delivery-manifest.json")
    if receiver["interface_status"] != "frozen_electronics_native_drc":
        raise unittest.SkipTest("electronics receiver interface is not final/frozen yet")
    interface_path = REPOSITORY / receiver["interface_source"]
    assert interface_path.is_file()
    interface = load_json(interface_path)
    assert interface["schema"] == "aicad_receiver_mechanical_interface_v1"
    assert interface["status"] == "frozen"
    assert receiver["interface_sha256"] == sha256(interface_path)
    assert delivery["status"] == "frozen"
    assert delivery["receiverInterface"]["hashMatch"] is True
    assert delivery["receiverInterface"]["consumedSha256"] == sha256(interface_path)
    assert delivery["receiverInterface"]["artifact"]["sha256"] == sha256(interface_path)

    contract = interface["coordinateContract"]
    assert contract["source"] == {"origin": "top-left", "xAxis": "right", "yAxis": "down", "units": "mm", "boardHeightMm": 42}
    assert contract["mechanical"] == {"origin": "bottom-left", "xAxis": "right", "yAxis": "up", "units": "mm"}
    assert contract["forwardTransform"] == {"x": "x_source", "y": "42-y_source"}
    assert contract["inverseTransform"] == {"x": "x_mechanical", "y": "42-y_mechanical"}
    assert contract["caseTransform"]["translationMm"] == [-25, -21]
    assert len(interface["mountHoles"]) == 4
    assert {row["ref"] for row in interface["connectors"]} == {"J1", "J2", "J3", "J4"}
    coordinates = [
        *[(row, "sourceCenterMm", "mechanicalCenterMm", "caseCenterMm") for row in interface["mountHoles"]],
        *[(row, "sourceDatumMm", "mechanicalDatumMm", "caseDatumMm") for row in interface["connectors"]],
    ]
    for row, source_key, mechanical_key, case_key in coordinates:
        source_x, source_y = row[source_key]
        mechanical_x, mechanical_y = row[mechanical_key]
        case_x, case_y = row[case_key]
        assert math.isclose(mechanical_x, source_x, abs_tol=1e-6)
        assert math.isclose(mechanical_y, 42 - source_y, abs_tol=1e-6)
        assert math.isclose(case_x, source_x - 25, abs_tol=1e-6)
        assert math.isclose(case_y, 21 - source_y, abs_tol=1e-6)
        assert math.isclose(source_y, 42 - mechanical_y, abs_tol=1e-6)
    j2 = next(row for row in interface["connectors"] if row["ref"] == "J2")
    assert j2["mpn"] == "DF13A-5P-1.25H(51)"
    assert j2["wallAxis"] == "-Y" and j2["panel"] == "bottom"
    driving_fields = (
        "sourceDatumMm",
        "mechanicalDatumMm",
        "caseDatumMm",
        "panel",
        "wallAxis",
        "panelNormal",
        "tangentAxis",
        "tangentCenterMm",
        "zCenterMm",
        "widthMm",
        "heightMm",
        "cornerRadiusMm",
        "cutDepthMm",
        "tolerancesMm",
        "bodyEnvelopeMm",
        "matingEnvelopeMm",
        "unmateClearanceMm",
        "matingDirection",
    )
    authorities = {}
    for connector in interface["connectors"]:
        evidence = connector["officialDrawing"]["authorityEvidence"]
        assert evidence["kind"] == "connector_mechanical_authority"
        relative = PurePosixPath(evidence["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        candidates = [
            REPOSITORY / Path(*relative.parts),
            interface_path.parent / Path(*relative.parts),
        ]
        matches = {path.resolve() for path in candidates if path.is_file()}
        assert len(matches) == 1
        authority_path = next(iter(matches))
        assert authority_path.stat().st_size == evidence["size"]
        assert sha256(authority_path) == evidence["sha256"]
        authority = load_json(authority_path)
        authorities[connector["ref"]] = authority
        assert authority["schema"] == "aicad_connector_mechanical_authority_v1"
        assert authority["status"] == "controlled"
        assert authority["kind"] == evidence["kind"]
        assert authority["manufacturer"] == connector["manufacturer"]
        assert authority["mpn"] == connector["mpn"]
        assert authority["sources"]["drawing2d"]["documentNumber"] == connector["officialDrawing"]["documentNumber"]
        assert authority["sources"]["drawing2d"]["sha256"] == connector["officialDrawing"]["sha256"]
        assert len(authority["sources"]["step3d"]["sha256"]) == 64
        assert all(authority["extractedMechanical"][field] == connector[field] for field in driving_fields)
    assert authorities["J2"]["mpn"] == "DF13A-5P-1.25H(51)"
    assert authorities["J2"]["sources"]["drawing2d"]["documentNumber"] == "0000995752"
    assert authorities["J2"]["sources"]["step3d"]["documentNumber"] == "0001217356S"
    board_sha = interface["sourceBoard"]["sha256"]
    assert board_sha == interface["frozenRoutes"]["sourceBoard"]["sha256"]
    assert board_sha == receiver["source_board_sha256"]
    assert board_sha == delivery["receiverInterface"]["sourceBoard"]["sha256"]
    assert board_sha == delivery["receiverInterface"]["frozenRoutes"]["sourceBoard"]["sha256"]
    assert delivery["receiverInterface"]["consistencyEvidence"]["fiveWayHashClosure"] is True
    assert delivery["receiverInterface"]["consistencyEvidence"]["connectorAuthorityHashClosure"] is True
    native_drc = interface["consistencyEvidence"]["nativeDrc"]
    assert all(native_drc[key] == 0 for key in ("violations", "unconnected", "footprintErrors", "exclusions", "suppressions"))


def test_artifact_manifest_and_portability_scan() -> None:
    manifest_path = REPORTS / "artifact-manifest.json"
    manifest = load_json(manifest_path)
    assert manifest["schema"] == "aicad_factory_artifact_manifest_v2"
    assert manifest["artifactCount"] == len(manifest["artifacts"])
    for record in manifest["artifacts"]:
        verify_root_artifact(record)
    digest_line = (REPORTS / "artifact-manifest.sha256").read_text(encoding="ascii").strip()
    assert digest_line == f"{sha256(manifest_path)}  {manifest_path.name}"

    scan_paths = [ROOT / "factory-design-input.json"]
    scan_paths += sorted((ROOT / "source").glob("*.py"))
    scan_paths += sorted(REPORTS.rglob("*.json"))
    scan_paths += [OUTPUTS / "reviewer" / "mechanical-factory-reviewer.html"]
    for path in scan_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(r"(?i)\b[A-Z]:[\\/]", text), path
        assert not re.search(r"(?i)[\\/]Users[\\/]", text), path


if __name__ == "__main__":
    failures: list[tuple[str, BaseException]] = []
    skipped: list[tuple[str, str]] = []
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
        except unittest.SkipTest as exc:
            skipped.append((name, str(exc)))
            print(f"SKIP {name}: {exc}")
        except BaseException as exc:
            failures.append((name, exc))
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"SUMMARY passed={len(tests) - len(failures) - len(skipped)} skipped={len(skipped)} failed={len(failures)}")
    if failures:
        raise SystemExit(1)
