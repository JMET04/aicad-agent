from __future__ import annotations

import copy
import hashlib
import io
import importlib.util
import json
import re
import struct
import tempfile
import unittest
import sys
import zlib
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch


class _Raises:
    def __init__(self, expected: type[BaseException], match: str | None = None) -> None:
        self.expected = expected
        self.match = match

    def __enter__(self) -> "_Raises":
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc_type is None:
            raise AssertionError(f"{self.expected.__name__} was not raised")
        if not issubclass(exc_type, self.expected):
            return False
        if self.match and (exc is None or re.search(self.match, str(exc)) is None):
            raise AssertionError(f"exception did not match {self.match!r}: {exc}")
        return True


class _StdlibRaises:
    CaptureFixture = Any

    @staticmethod
    def raises(expected: type[BaseException], match: str | None = None) -> _Raises:
        return _Raises(expected, match)


pytest = _StdlibRaises()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aicad import cli
from aicad.manufacturing_release import _Context, _preview_evidence
from aicad.manufacturing_validation import validate_manufacturing_release_package
from aicad.manufacturing_workflow import (
    build_manufacturing_release_package,
    render_manufacturing_release_review,
    validate_manufacturing_release_review_html,
)


def _write(root: Path, relative: str, data: str | bytes) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    path.write_bytes(payload)
    return {
        "path": relative.replace("\\", "/"),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _svg(source_sha: str, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360" '
        f'data-aicad-source-sha256="{source_sha}">'
        '<rect x="15" y="15" width="610" height="330" fill="white" stroke="black" stroke-width="4"/>'
        '<path d="M80 250 L240 70 L530 255 Z" fill="none" stroke="#176477" stroke-width="7"/>'
        f'<title>{label}</title></svg>'
    )


def _preview(root: Path, relative: str, source: dict[str, object], role: str, subject: str) -> dict[str, object]:
    row = _write(root, relative, _svg(str(source["sha256"]), subject + " " + role))
    return {
        **row,
        "previewOfRole": role,
        "subjectId": subject,
        "sourceSha256": source["sha256"],
    }


def _native_log(
    root: Path,
    relative: str,
    *,
    gate: str,
    subject: str,
    revision: str,
    tool: str,
    version: str,
    inputs: dict[str, dict[str, object]],
    outputs: dict[str, dict[str, object]],
) -> dict[str, object]:
    document = {
        "schema": "aicad_native_tool_execution_log_v1",
        "gate": gate,
        "status": "pass",
        "nativeTool": {"name": tool, "version": version, "nativeExecution": True},
        "subjectId": subject,
        "revision": revision,
        "inputSha256ByRole": {key: value["sha256"] for key, value in inputs.items()},
        "outputSha256ByRole": {key: value["sha256"] for key, value in outputs.items()},
        "checks": [
            {
                "id": gate + ":executed",
                "status": "pass",
                "detail": f"{tool} {version} reopened the exact source and completed the named gate.",
            }
        ],
    }
    return _write(root, relative, json.dumps(document, ensure_ascii=False, indent=2))


def _supplier(
    root: Path,
    *,
    supplier_id: str,
    coordinate_ids: list[str],
    capabilities: list[str],
    formats: list[str],
) -> dict[str, object]:
    authority = _write(
        root,
        f"supplier/{supplier_id}-authority.html",
        "<html><body><h1>Official manufacturing capabilities</h1>"
        + "<p>Published process, file-format, material and dimensional capability record.</p>" * 8
        + "</body></html>",
    )
    today = date.today()
    profile = {
        "schema": "aicad_supplier_capability_v1",
        "supplierId": supplier_id,
        "status": "public_capability_record",
        "revision": "2026.08",
        "units": ["mm"],
        "coordinateSystemIds": coordinate_ids,
        "capabilities": capabilities,
        "nativeFormats": formats,
        "sourceAuthority": f"https://capabilities.moldworks-industrial.com/{supplier_id}/capabilities",
        "documentId": f"{supplier_id}-CAP-2026-08",
        "issuedBy": supplier_id,
        "issuedAt": today.isoformat(),
        "validUntil": (today + timedelta(days=365)).isoformat(),
        "authoritySha256": authority["sha256"],
    }
    capability = _write(
        root,
        f"supplier/{supplier_id}-profile.json",
        json.dumps(profile, ensure_ascii=False, indent=2),
    )
    return {
        "supplierId": supplier_id,
        "capabilityEvidence": capability,
        "authorityEvidence": authority,
    }


def _pdf(label: str) -> str:
    return "%PDF-1.4\n% AICAD controlled " + label + "\n1 0 obj<<>>endobj\n%%EOF\n"


def _dxf(label: str) -> str:
    return "0\nSECTION\n2\nENTITIES\n999\n" + label + "\n0\nENDSEC\n0\nEOF\n"

def _solidworks_blob(kind: bytes) -> bytes:
    return kind[:4].ljust(4, b"X") + b"\x00\x00\x00\x04" + bytes(range(256)) * 20

def _png_bytes(source_sha: str | None, *, solid: bool, single_pixel: bool = False) -> bytes:
    width, height = 96, 72

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)
        for x in range(width):
            if solid or (single_pixel and (x, y) != (0, 0)):
                pixel = (42, 86, 110)
            else:
                pixel = (42, 86, 110) if (x + y) % 2 else (230, 190, 65)
            scanlines.extend(pixel)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if source_sha is not None:
        payload += chunk(b"tEXt", b"aicad-source-sha256\x00" + source_sha.encode("ascii"))
    payload += chunk(b"IDAT", zlib.compress(bytes(scanlines)))
    payload += chunk(b"IEND", b"")
    return payload




def mechanical_package(root: Path) -> dict[str, object]:
    supplier = _supplier(
        root,
        supplier_id="MoldWorks",
        coordinate_ids=["MECH-CS"],
        capabilities=["injection_molding", "mechanical_assembly"],
        formats=[".sldprt", ".sldasm", ".step", ".dxf"],
    )
    part: dict[str, dict[str, object]] = {}
    part["nativeCad"] = _write(root, "mechanical/P1/P1.sldprt", _solidworks_blob(b"PART"))
    part["step"] = _write(
        root,
        "mechanical/P1/P1.step",
        "ISO-10303-21;\nHEADER;ENDSEC;\nDATA;#1=PRODUCT('P1','','',());ENDSEC;\nEND-ISO-10303-21;\n",
    )
    part["manufacturingDrawing"] = _write(root, "mechanical/P1/P1.dxf", _dxf("P1 drawing"))
    part["drawingPreview"] = _preview(
        root, "mechanical/P1/P1-drawing.svg", part["manufacturingDrawing"], "manufacturingDrawing", "P1"
    )
    part["modelPreview"] = _preview(root, "mechanical/P1/P1-model.svg", part["step"], "step", "P1")
    part["nativeReopenLog"] = _native_log(
        root,
        "mechanical/P1/P1-reopen.json",
        gate="mechanical_part_native_reopen",
        subject="P1",
        revision="B",
        tool="SOLIDWORKS",
        version="2025 SP3",
        inputs={"nativeCad": part["nativeCad"]},
        outputs={key: part[key] for key in ("step", "manufacturingDrawing", "drawingPreview", "modelPreview")},
    )

    assembly: dict[str, dict[str, object]] = {}
    assembly["nativeAssembly"] = _write(root, "mechanical/A1/A1.sldasm", _solidworks_blob(b"ASMB"))
    assembly["step"] = _write(
        root,
        "mechanical/A1/A1.step",
        "ISO-10303-21;\nHEADER;ENDSEC;\nDATA;#1=PRODUCT('A1','','',());ENDSEC;\nEND-ISO-10303-21;\n",
    )
    for role in ("assemblyDrawing", "explodedDrawing", "sectionDrawing"):
        assembly[role] = _write(root, f"mechanical/A1/{role}.dxf", _dxf(role))
    assembly["assemblyPreview2d"] = _preview(
        root, "mechanical/A1/A1-2d.svg", assembly["assemblyDrawing"], "assemblyDrawing", "A1"
    )
    assembly["assemblyPreview3d"] = _preview(
        root, "mechanical/A1/A1-3d.svg", assembly["step"], "step", "A1"
    )
    assembly["assemblyWorkInstruction"] = _write(root, "mechanical/A1/awi.pdf", _pdf("AWI"))
    assembly["inspectionPlan"] = _write(root, "mechanical/A1/inspection.pdf", _pdf("inspection"))
    assembly["bom"] = _write(
        root,
        "mechanical/A1/bom.json",
        json.dumps(
            {
                "schema": "aicad_manufacturing_bom_v1",
                "assemblyId": "A1",
                "revision": "B",
                "units": "mm",
                "coordinateSystemId": "MECH-CS",
                "rows": [{"partId": "P1", "revision": "B", "quantity": 1}],
            }
        ),
    )
    assembly["positions"] = _write(
        root,
        "mechanical/A1/positions.json",
        json.dumps(
            {
                "schema": "aicad_assembly_positions_v1",
                "assemblyId": "A1",
                "revision": "B",
                "units": "mm",
                "coordinateSystemId": "MECH-CS",
                "instances": [
                    {
                        "instanceId": "P1-1",
                        "partId": "P1",
                        "revision": "B",
                        "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                    }
                ],
            }
        ),
    )
    tooling = [
        {"key": key, "value": value, "source": "MoldWorks engineering datasheet MW-42"}
        for key, value in {
            "shrinkage": "0.55 percent",
            "draft": "1.5 degrees minimum",
            "partingLine": "frozen perimeter PL-01",
            "gate": "submarine gate G-01",
            "ejection": "four ejector pins EJ-01",
            "surfaceFinish": "SPI B-2",
            "tolerance": "ISO 20457 TG6",
        }.items()
    ]
    assembly["moldingInput"] = _write(
        root,
        "mechanical/A1/molding.json",
        json.dumps(
            {
                "schema": "aicad_molding_input_v1",
                "assemblyId": "A1",
                "revision": "B",
                "units": "mm",
                "coordinateSystemId": "MECH-CS",
                "moldedPartIds": ["P1"],
                "toolingInputs": tooling,
            }
        ),
    )
    assembly["interferenceLog"] = _native_log(
        root,
        "mechanical/A1/interference.json",
        gate="mechanical_assembly_interference",
        subject="A1",
        revision="B",
        tool="SOLIDWORKS",
        version="2025 SP3",
        inputs={"nativeAssembly": assembly["nativeAssembly"], "positions": assembly["positions"]},
        outputs={},
    )
    reopen_outputs = {
        key: assembly[key]
        for key in (
            "step", "assemblyDrawing", "explodedDrawing", "sectionDrawing",
            "assemblyPreview2d", "assemblyPreview3d", "assemblyWorkInstruction",
            "inspectionPlan", "moldingInput", "bom", "positions",
        )
    }
    assembly["nativeReopenLog"] = _native_log(
        root,
        "mechanical/A1/reopen.json",
        gate="mechanical_assembly_native_reopen",
        subject="A1",
        revision="B",
        tool="SOLIDWORKS",
        version="2025 SP3",
        inputs={"nativeAssembly": assembly["nativeAssembly"]},
        outputs=reopen_outputs,
    )
    return {
        "schema": "aicad_manufacturing_release_package_v1",
        "packageId": "fixture-mechanical",
        "releaseBasis": {
            "revision": "B",
            "units": "mm",
            "coordinateSystems": [
                {
                    "id": "MECH-CS",
                    "units": "mm",
                    "handedness": "right",
                    "origin": [0, 0, 0],
                    "xAxis": [1, 0, 0],
                    "yAxis": [0, 1, 0],
                    "zAxis": [0, 0, 1],
                    "description": "Assembly datum at lower shell center with Z along product axis.",
                }
            ],
            "suppliers": [supplier],
        },
        "mechanical": {
            "parts": [
                {
                    "partId": "P1",
                    "revision": "B",
                    "coordinateSystemId": "MECH-CS",
                    "supplierId": "MoldWorks",
                    "process": "injection_molding",
                    "artifacts": part,
                }
            ],
            "assemblies": [
                {
                    "assemblyId": "A1",
                    "revision": "B",
                    "coordinateSystemId": "MECH-CS",
                    "supplierId": "MoldWorks",
                    "artifacts": assembly,
                }
            ],
        },
    }


def _bind_confirmation(root: Path, package: dict[str, object]) -> None:
    initial = validate_manufacturing_release_package(package, root)
    acknowledged = {
        row["location"]: row["actualSha256"]
        for row in initial["artifacts"]
        if row.get("pass") is True
    }
    authority = _write(
        root,
        "supplier/MoldWorks-package-confirmation.html",
        "<html><body><h1>Supplier portal package acknowledgement</h1>"
        + "<p>Package fixture-mechanical revision B and attached hashes reviewed.</p>" * 8
        + "</body></html>",
    )
    today = date.today()
    receipt = _write(
        root,
        "supplier/MoldWorks-package-confirmation.json",
        json.dumps(
            {
                "schema": "aicad_supplier_package_confirmation_v1",
                "supplierId": "MoldWorks",
                "packageId": "fixture-mechanical",
                "releaseRevision": "B",
                "status": "confirmed_for_factory_handoff",
                "sourceAuthority": "supplier-portal:MoldWorks/order/RFQ-2042",
                "documentId": "RFQ-2042",
                "issuedBy": "MoldWorks",
                "issuedAt": today.isoformat(),
                "validUntil": (today + timedelta(days=120)).isoformat(),
                "authoritySha256": authority["sha256"],
                "acknowledgedArtifactSha256ByLocation": acknowledged,
            },
            indent=2,
        ),
    )
    supplier = package["releaseBasis"]["suppliers"][0]
    supplier["packageConfirmationEvidence"] = receipt
    supplier["confirmationAuthorityEvidence"] = authority


def test_mechanical_digital_candidate_is_not_supplier_handoff(tmp_path: Path) -> None:
    package = mechanical_package(tmp_path)
    report = validate_manufacturing_release_package(package, tmp_path)
    assert report["ok"] is True
    assert report["factoryRfqCandidateReady"] is True
    assert report["prototypeFabricationCandidateReady"] is False
    assert report["digitalPackageReady"] is True
    assert report["factoryHandoffReady"] is False
    assert report["status"] == "digital_manufacturing_candidate"
    assert report["artifactClosureSha256"]
    assert {row["code"] for row in report["handoffFailures"]} == {
        "supplier_package_confirmation_missing"
    }
    assert report["productionReady"] is False
    assert report["toolSteelCutAuthorized"] is False
    assert report["massProductionAuthorized"] is False
    assert report["counts"]["actualPreviewsExpected"] == 4
    assert report["counts"]["actualPreviewsVerified"] == 4


def test_exact_real_supplier_confirmation_unlocks_handoff_only(tmp_path: Path) -> None:
    package = mechanical_package(tmp_path)
    _bind_confirmation(tmp_path, package)
    report = validate_manufacturing_release_package(package, tmp_path)
    assert report["factoryHandoffReady"] is True
    assert report["status"] == "factory_handoff_candidate"
    assert report["productionReady"] is False
    assert report["toolSteelCutAuthorized"] is False
    assert report["massProductionAuthorized"] is False
    assert report["handoffArtifactClosureSha256"]
    assert report["handoffArtifactClosureSha256"] != report["artifactClosureSha256"]


def test_coordinate_native_and_preview_mutations_fail_closed(tmp_path: Path) -> None:
    package = mechanical_package(tmp_path)
    coordinate_mutation = copy.deepcopy(package)
    coordinate_mutation["releaseBasis"]["coordinateSystems"][0]["yAxis"] = [1, 0, 0]
    report = validate_manufacturing_release_package(coordinate_mutation, tmp_path)
    assert report["factoryRfqCandidateReady"] is False
    assert "coordinate_basis_invalid" in {row["code"] for row in report["failures"]}

    preview_mutation = copy.deepcopy(package)
    preview_mutation["mechanical"]["parts"][0]["artifacts"]["drawingPreview"]["sourceSha256"] = "0" * 64
    report = validate_manufacturing_release_package(preview_mutation, tmp_path)
    codes = {row["code"] for row in report["failures"]}
    assert "preview_source_binding_mismatch" in codes
    assert "svg_preview_source_metadata_missing" in codes

    native_mutation = copy.deepcopy(package)
    log_ref = native_mutation["mechanical"]["parts"][0]["artifacts"]["nativeReopenLog"]
    log_path = tmp_path / log_ref["path"]
    log = json.loads(log_path.read_text(encoding="utf-8"))
    log["nativeTool"]["nativeExecution"] = False
    native_mutation["mechanical"]["parts"][0]["artifacts"]["nativeReopenLog"] = _write(
        tmp_path, str(log_ref["path"]), json.dumps(log, indent=2)
    )
    report = validate_manufacturing_release_package(native_mutation, tmp_path)
    assert "native_tool_execution_unproven" in {row["code"] for row in report["failures"]}


def test_reviewer_renders_only_actual_hash_bound_subject_previews(tmp_path: Path) -> None:
    package = mechanical_package(tmp_path)
    report = validate_manufacturing_release_package(package, tmp_path)
    page = render_manufacturing_release_review(report)
    contract = validate_manufacturing_release_review_html(page)
    assert contract["contract"] == "aicad_manufacturing_release_candidate_reviewer_v2"
    assert contract["subjectCount"] == 2
    assert contract["actualPreviewRendered"] == 4
    assert contract["actualPreviewClosurePass"] is True
    assert page.count('class="actual-preview"') == 4
    assert 'class="cad-sheet"' not in page
    assert 'data-legend-only="true"' in page
    assert "overflow-wrap:anywhere" in page

    with pytest.raises(Exception, match="DOM closure mismatch"):
        validate_manufacturing_release_review_html(page.replace('class="actual-preview"', 'class="removed-preview"', 1))
    with pytest.raises(Exception, match="generic line-grammar"):
        validate_manufacturing_release_review_html(page.replace("</body>", '<div class="cad-sheet"></div></body>'))


def test_build_and_portable_cli_emit_digital_manifest_and_handoff_blockers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = mechanical_package(tmp_path)
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    assert cli.main([
        "manufacturing-release-validate", str(package_path), "--evidence-root", str(tmp_path)
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["factoryRfqCandidateReady"] is True
    assert payload["factoryHandoffReady"] is False

    output = tmp_path / "built-review"
    result = build_manufacturing_release_package(package, tmp_path, output, "fixture")
    assert result["ok"] is True
    assert any(path.endswith("digital-manufacturing-candidate.json") for path in result["files"])
    assert any(path.endswith("blockers.json") for path in result["files"])
    assert not any(path.endswith("factory-handoff-candidate.json") for path in result["files"])
    review = Path(result["reviewHtml"]).read_text(encoding="utf-8")
    assert validate_manufacturing_release_review_html(review)["actualPreviewClosurePass"] is True


def test_mcp_tools_dispatch_and_schema_resource_are_real(tmp_path: Path) -> None:
    script = Path("agent-plugin/aicad-agent/scripts/aicad_agent.py").resolve()
    spec = importlib.util.spec_from_file_location("aicad_agent_manufacturing_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool_names = {row["name"] for row in module.TOOLS}
    assert {
        "aicad_get_manufacturing_release_schema",
        "aicad_validate_manufacturing_release_package",
        "aicad_build_manufacturing_release_package",
        "aicad_open_manufacturing_release_review",
    }.issubset(tool_names)
    listed = module._handle_mcp(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}}
    )
    listed_names = {row["name"] for row in listed["result"]["tools"]}
    assert tool_names <= listed_names
    package = mechanical_package(tmp_path)
    result = module._dispatch_tool(
        "aicad_validate_manufacturing_release_package",
        {"package": package, "evidence_root": str(tmp_path)},
    )
    assert result["ok"] is True
    assert result["factoryHandoffReady"] is False
    built = module._dispatch_tool(
        "aicad_build_manufacturing_release_package",
        {
            "package": package,
            "evidence_root": str(tmp_path),
            "output_dir": str(tmp_path / "mcp-built"),
            "name": "mcp-fixture",
            "review_launch": "never",
        },
    )
    assert built["ok"] is True
    assert built["reviewContract"]["actualPreviewClosurePass"] is True
    opened = module._dispatch_tool(
        "aicad_open_manufacturing_release_review",
        {"review_html": built["reviewHtml"], "review_launch": "never"},
    )
    assert opened["ok"] is True
    assert opened["productionReady"] is False
    resource = module._handle_mcp(
        {"jsonrpc": "2.0", "id": 7, "method": "resources/read", "params": {"uri": "aicad://manufacturing-release-schema"}}
    )
    assert resource["result"]["contents"][0]["mimeType"] == "application/schema+json"


def test_schema_has_exact_preview_and_supplier_authority_roles() -> None:
    schema = json.loads(
        Path("schema/aicad-manufacturing-release-package.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$defs"]["previewEvidence"]["required"] == [
        "path", "size", "sha256", "previewOfRole", "subjectId", "sourceSha256"
    ]
    variants = schema["$defs"]["supplier"]["oneOf"]
    assert set(variants[0]["required"]) == {"supplierId", "capabilityEvidence", "authorityEvidence"}
    assert set(variants[1]["required"]) == {"supplierId", "recipientProfile"}
    assert {"assemblyPreview2d", "assemblyPreview3d"}.issubset(
        schema["$defs"]["mechanicalAssemblyArtifacts"]["required"]
    )
    assert {
        "schematicPreview", "boardPreview", "assemblyPreview", "fabricationPreview", "modelPreview3d"
    }.issubset(schema["$defs"]["pcbArtifacts"]["required"])


class ManufacturingReleaseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_mechanical_candidate_without_supplier_handoff(self) -> None:
        test_mechanical_digital_candidate_is_not_supplier_handoff(self.root)

    def test_exact_supplier_confirmation_unlocks_handoff_only(self) -> None:
        test_exact_real_supplier_confirmation_unlocks_handoff_only(self.root)

    def test_coordinate_native_and_preview_mutations_fail_closed(self) -> None:
        test_coordinate_native_and_preview_mutations_fail_closed(self.root)

    def test_native_random_or_tiny_payload_cannot_claim_solidworks(self) -> None:
        package = mechanical_package(self.root)
        native = _write(self.root, "mechanical/P1/P1.sldprt", b"A" * 128)
        package["mechanical"]["parts"][0]["artifacts"]["nativeCad"] = native
        report = validate_manufacturing_release_package(package, self.root)
        self.assertFalse(report["factoryRfqCandidateReady"])
        self.assertIn("artifact_format_invalid", {row["code"] for row in report["failures"]})

    def test_unassigned_neutral_recipient_allows_rfq_but_never_handoff(self) -> None:
        package = mechanical_package(self.root)
        recipient_document = {
            "schema": "aicad_rfq_recipient_profile_v1",
            "recipientId": "unassigned_rfq_recipient",
            "status": "rfq_recipient_unassigned",
            "revision": "B",
            "units": ["mm"],
            "coordinateSystemIds": ["MECH-CS"],
            "processRequirements": ["injection_molding", "mechanical_assembly"],
            "nativeFormats": [".sldprt", ".sldasm", ".step", ".dxf"],
            "authorship": "project_rfq_requirements",
            "supplierAuthorityClaimed": False,
        }
        recipient = _write(
            self.root,
            "rfq/unassigned-recipient.json",
            json.dumps(recipient_document, indent=2),
        )
        package["releaseBasis"]["suppliers"] = [{
            "supplierId": "unassigned_rfq_recipient",
            "recipientProfile": recipient,
        }]
        package["mechanical"]["parts"][0]["supplierId"] = "unassigned_rfq_recipient"
        package["mechanical"]["assemblies"][0]["supplierId"] = "unassigned_rfq_recipient"
        report = validate_manufacturing_release_package(package, self.root)
        self.assertTrue(report["factoryRfqCandidateReady"])
        self.assertFalse(report["factoryHandoffReady"])
        self.assertFalse(report["toolSteelCutAuthorized"])
        self.assertFalse(report["massProductionAuthorized"])

    def test_partial_candidate_has_non_null_scoped_closure(self) -> None:
        package = mechanical_package(self.root)
        package["electronics"] = {"pcbs": []}
        report = validate_manufacturing_release_package(package, self.root)
        self.assertTrue(report["factoryRfqCandidateReady"])
        self.assertFalse(report["prototypeFabricationCandidateReady"])
        self.assertEqual(report["status"], "partial_digital_candidate")
        self.assertIsNotNone(report["artifactClosureSha256"])
        self.assertIsNotNone(report["domainArtifactClosureSha256"]["mechanical"])
        self.assertIsNone(report["domainArtifactClosureSha256"]["electronics"])
        self.assertFalse(any(value.startswith("electronics.") for value in report["candidateArtifactLocations"]))

    def test_reviewer_actual_preview_dom_and_portability(self) -> None:
        package = mechanical_package(self.root)
        report = validate_manufacturing_release_package(package, self.root)
        review_dir = self.root / "public" / "review"
        review_dir.mkdir(parents=True)
        page = render_manufacturing_release_review(report, review_dir)
        contract = validate_manufacturing_release_review_html(page)
        self.assertEqual(contract["actualPreviewRendered"], 4)
        self.assertNotIn("file://", page.casefold())
        self.assertIsNone(re.search(r"[A-Za-z]:[/\\\\]", page))
        source_url = re.search(r'<img class="actual-preview" src="([^"]+)"', page).group(1)
        nonportable = page.replace(source_url, "/machine-bound-preview.svg")
        with self.assertRaisesRegex(Exception, "non-portable"):
            validate_manufacturing_release_review_html(nonportable)
    def test_electronics_only_partial_candidate_has_non_null_scoped_closure(self) -> None:
        package = mechanical_package(self.root)
        package["mechanical"] = {"parts": [], "assemblies": []}
        package["electronics"] = {"pcbs": [{"patched": "electronics digital closure"}]}
        evidence = _write(self.root, "electronics/E1/E1.kicad_pcb", "(kicad_pcb (layers (0 \"F.Cu\" signal)))")

        def electronic_closure(ctx: Any, value: Any, coordinates: Any, suppliers: Any) -> int:
            ctx.artifacts.append({
                "location": "electronics.pcbs[0].artifacts.board",
                "kind": "kicad_board",
                "path": evidence["path"],
                "actualSize": evidence["size"],
                "actualSha256": evidence["sha256"],
                "pass": True,
            })
            return 1

        with patch("aicad.manufacturing_validation._electronics", side_effect=electronic_closure):
            report = validate_manufacturing_release_package(package, self.root)
        self.assertFalse(report["factoryRfqCandidateReady"])
        self.assertTrue(report["prototypeFabricationCandidateReady"])
        self.assertEqual(report["status"], "partial_digital_candidate")
        self.assertIsNotNone(report["artifactClosureSha256"])
        self.assertIsNone(report["domainArtifactClosureSha256"]["mechanical"])
        self.assertIsNotNone(report["domainArtifactClosureSha256"]["electronics"])

    def test_png_preview_requires_distributed_pixels_and_structured_metadata(self) -> None:
        source_sha = "a" * 64
        correct = _png_bytes(source_sha, solid=False)
        marker = b"aicad-source-sha256\x00" + source_sha.encode("ascii")
        cases = [
            ("solid.png", _png_bytes(source_sha, solid=True), "artifact_format_invalid"),
            ("single-pixel.png", _png_bytes(source_sha, solid=False, single_pixel=True), "artifact_format_invalid"),
            ("missing-metadata.png", _png_bytes(None, solid=False), "png_preview_source_metadata_missing"),
            ("wrong-metadata.png", _png_bytes("b" * 64, solid=False), "png_preview_source_metadata_missing"),
            ("trailing-marker.png", _png_bytes(None, solid=False) + marker, "artifact_format_invalid"),
        ]
        hidden_chunk = bytearray(correct)
        text_offset = hidden_chunk.find(b"tEXt")
        hidden_chunk[text_offset:text_offset + 4] = b"vpAg"
        chunk_start = text_offset - 4
        length = int.from_bytes(hidden_chunk[chunk_start:text_offset], "big")
        crc_offset = text_offset + 4 + length
        crc = zlib.crc32(bytes(hidden_chunk[text_offset:crc_offset])) & 0xFFFFFFFF
        hidden_chunk[crc_offset:crc_offset + 4] = crc.to_bytes(4, "big")
        cases.append(("unknown-chunk-marker.png", bytes(hidden_chunk), "png_preview_source_metadata_missing"))
        for filename, payload, expected_code in cases:
            with self.subTest(filename=filename):
                reference = _write(self.root, "preview/" + filename, payload)
                ctx = _Context(self.root)
                row = _preview_evidence(
                    ctx,
                    {
                        **reference,
                        "previewOfRole": "step",
                        "subjectId": "P1",
                        "sourceSha256": source_sha,
                    },
                    "preview",
                )
                self.assertFalse(row["pass"])
                self.assertIn(expected_code, {failure["code"] for failure in ctx.failures})

    def test_svg_source_hash_must_be_exact_root_attribute(self) -> None:
        source_sha = "c" * 64
        base = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{marker}<rect x="2" y="2" width="96" height="96"/><path d="M5 5L95 95"/></svg>'
        for filename, marker in (
            ("comment.svg", f'<!-- data-aicad-source-sha256="{source_sha}" -->'),
            ("child.svg", f'<g data-aicad-source-sha256="{source_sha}"></g>'),
        ):
            with self.subTest(filename=filename):
                reference = _write(self.root, "preview/" + filename, base.format(marker=marker))
                ctx = _Context(self.root)
                row = _preview_evidence(ctx, {**reference, "previewOfRole": "step", "subjectId": "P1", "sourceSha256": source_sha}, "preview")
                self.assertFalse(row["pass"])
                self.assertIn("svg_preview_source_metadata_missing", {failure["code"] for failure in ctx.failures})


    def test_cli_build_manifest_and_mcp_surface(self) -> None:
        package = mechanical_package(self.root)
        package_path = self.root / "package.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli.main([
                "manufacturing-release-validate",
                str(package_path),
                "--evidence-root",
                str(self.root),
            ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output.getvalue())["factoryRfqCandidateReady"])
        cli_build_dir = self.root / "cli-built-review"
        output = io.StringIO()
        with redirect_stdout(output):
            build_exit = cli.main([
                "manufacturing-release-build",
                str(package_path),
                "--evidence-root", str(self.root),
                "--out", str(cli_build_dir),
                "--name", "cli-fixture",
            ])
        self.assertEqual(build_exit, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["artifactClosureSha256"])
        self.assertTrue(any(path.endswith("digital-manufacturing-candidate.json") for path in result["files"]))
        portable_validation = Path(result["files"][0]).read_text(encoding="utf-8")
        self.assertNotIn("file://", portable_validation.casefold())
        self.assertNotIn(str(self.root), portable_validation)
        output = io.StringIO()
        cli_review = self.root / "cli-review.html"
        with redirect_stdout(output):
            review_exit = cli.main([
                "manufacturing-release-review",
                str(package_path),
                "--evidence-root", str(self.root),
                "--output", str(cli_review),
                "--review-launch", "never",
            ])
        self.assertEqual(review_exit, 0)
        self.assertTrue(cli_review.is_file())
        self.assertTrue(json.loads(output.getvalue())["candidateReviewerMayOpen"])
        test_mcp_tools_dispatch_and_schema_resource_are_real(self.root)

    def test_schema_preview_supplier_and_neutral_recipient_contracts(self) -> None:
        schema = json.loads(Path("schema/aicad-manufacturing-release-package.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            schema["$defs"]["previewEvidence"]["required"],
            ["path", "size", "sha256", "previewOfRole", "subjectId", "sourceSha256"],
        )
        supplier_variants = schema["$defs"]["supplier"]["oneOf"]
        self.assertEqual(len(supplier_variants), 2)
        self.assertEqual(
            supplier_variants[1]["properties"]["supplierId"]["const"],
            "unassigned_rfq_recipient",
        )


if __name__ == "__main__":
    unittest.main()
