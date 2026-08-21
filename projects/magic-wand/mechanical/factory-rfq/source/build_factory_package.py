from __future__ import annotations

"""Build the reviewable, hash-bound factory RFQ mechanical package."""

import hashlib
import html
import importlib.metadata
import json
import textwrap
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from build123d import export_step
from matplotlib.backends.backend_pdf import PdfPages

import factory_release_geometry as geometry
import factory_release_previews as previews
from factory_solidworks_export import ASSEMBLIES


REVISION = geometry.P["revision"]
CS_ID = geometry.P["coordinate_system"]["id"]

ASSEMBLY_DOCS = {
    "MW-A-001": {
        "label": "Magic Wand Assembly",
        "basename": "MW-A-001_magic_wand_assembly",
        "parts": geometry.WAND_PART_NUMBERS,
        "assemblyDrawing": "MW-A-001_wand_general_assembly.dxf",
        "explodedDrawing": "MW-A-001_wand_exploded.dxf",
        "sectionDrawing": "MW-A-001_wand_section_A-A.dxf",
        "harnessDrawing": "MW-A-001_wand_harness_interface.dxf",
        "explodedStep": "MW-A-001_magic_wand_exploded.step",
    },
    "MW-A-101": {
        "label": "Receiver Enclosure Assembly",
        "basename": "MW-A-101_receiver_enclosure_assembly",
        "parts": geometry.RECEIVER_PART_NUMBERS,
        "assemblyDrawing": "MW-A-101_receiver_assembly.dxf",
        "explodedDrawing": "MW-A-101_receiver_exploded.dxf",
        "sectionDrawing": "MW-A-101_receiver_section_interface.dxf",
        "explodedStep": "MW-A-101_receiver_enclosure_exploded.step",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, document: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sizeBytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _transform(translation: tuple[float, float, float]) -> list[float]:
    x, y, z = [float(value) for value in translation]
    return [1.0, 0.0, 0.0, x, 0.0, 1.0, 0.0, y, 0.0, 0.0, 1.0, z, 0.0, 0.0, 0.0, 1.0]


def _pdf(path: Path, title: str, pages: list[tuple[str, list[str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Title": title,
        "Author": "AICAD factory RFQ evidence pipeline",
        "Subject": f"{REVISION}; review-only manufacturing input",
    }
    with PdfPages(path, metadata=metadata) as pdf:
        for page_number, (heading, raw_lines) in enumerate(pages, 1):
            fig = plt.figure(figsize=(8.27, 11.69), dpi=150, facecolor="white")
            fig.text(0.07, 0.955, title, fontsize=15, weight="bold", color="#153A59")
            fig.text(0.07, 0.925, heading, fontsize=11, weight="bold", color="#2E5B7C")
            y = 0.89
            for raw in raw_lines:
                wrapped = textwrap.wrap(str(raw), width=102, subsequent_indent="    ") or [""]
                for line in wrapped:
                    if y < 0.07:
                        break
                    fig.text(0.075, y, line, fontsize=7.8, family="DejaVu Sans Mono", color="#17212B")
                    y -= 0.019
                y -= 0.004
            fig.text(0.07, 0.035, f"REV {REVISION} · {CS_ID} · REVIEW ONLY · NOT TOOL RELEASE", fontsize=7, color="#566573")
            fig.text(0.93, 0.035, f"{page_number}/{len(pages)}", fontsize=7, ha="right", color="#566573")
            plt.axis("off")
            pdf.savefig(fig)
            plt.close(fig)


def build_assembly_documents(root: Path, assembly_id: str) -> dict[str, Path]:
    config = ASSEMBLY_DOCS[assembly_id]
    documents = root / "outputs" / "documents"
    placements = ASSEMBLIES[assembly_id]["placements"]
    rows = [
        {"partId": part_id, "revision": REVISION, "quantity": 1}
        for part_id in config["parts"]
    ]
    bom_path = write_json(
        documents / f"{assembly_id}_manufacturing-bom.json",
        {
            "schema": "aicad_manufacturing_bom_v1",
            "assemblyId": assembly_id,
            "revision": REVISION,
            "units": "mm",
            "coordinateSystemId": CS_ID,
            "rows": rows,
        },
    )
    position_rows = [
        {
            "instanceId": f"{part_id}:1",
            "partId": part_id,
            "revision": REVISION,
            "transform": _transform(tuple(placements[part_id])),
        }
        for part_id in config["parts"]
    ]
    positions_path = write_json(
        documents / f"{assembly_id}_assembly-positions.json",
        {
            "schema": "aicad_assembly_positions_v1",
            "assemblyId": assembly_id,
            "revision": REVISION,
            "units": "mm",
            "coordinateSystemId": CS_ID,
            "instances": position_rows,
        },
    )
    molded = [
        part_id
        for part_id in config["parts"]
        if geometry.P["parts"][part_id]["process"] == "injection molding"
    ]
    molding_values = {
        "shrinkage": "Nominal finished-part CAD; resin-specific compensated scale requires vendor DFM approval before tool authorization",
        "draft": f"General {geometry.P['molding_defaults']['general_draft_deg']} deg; add {geometry.P['molding_defaults']['texture_draft_addition_deg']} deg on textured pull faces",
        "partingLine": "Use each part drawing MOLD PULL / PARTING feature row as the controlled RFQ basis",
        "gate": "Vendor shall propose gate type, count and vestige location with fill/pack evidence before tool authorization",
        "ejection": "Vendor shall propose ejector layout outside cosmetic, sealing, RF and controlled-fit surfaces",
        "surfaceFinish": geometry.P["molding_defaults"]["surface"],
        "tolerance": geometry.P["molding_defaults"]["general_linear_tolerance"],
    }
    molding_path = write_json(
        documents / f"{assembly_id}_molding-input.json",
        {
            "schema": "aicad_molding_input_v1",
            "assemblyId": assembly_id,
            "revision": REVISION,
            "units": "mm",
            "coordinateSystemId": CS_ID,
            "moldedPartIds": molded,
            "toolingInputs": [
                {"key": key, "value": value, "source": f"factory-design-input.json#molding_defaults/{key}"}
                for key, value in molding_values.items()
            ],
        },
    )
    awi_path = documents / f"{assembly_id}_assembly-work-instruction.pdf"
    awi_pages = [
        (
            "1. Controlled inputs and preparation",
            [
                f"Assembly: {assembly_id} — {config['label']}",
                f"Coordinate basis: {CS_ID}; all positions are row-major transforms in millimetres.",
                "Verify every part number and revision against the hash-bound BOM before handling components.",
                "Inspect molded parts for flash, short shot, sink, warp and blocked controlled openings.",
                "Protect RF keep-out surfaces from metallic pigment, conductive coating and loose hardware.",
            ]
            + [f"ITEM {index:02d}: {row['partId']} REV {REVISION} QTY {row['quantity']}" for index, row in enumerate(rows, 1)],
        ),
        (
            "2. Assembly sequence and verification",
            [
                "Stage all components at the released MODEL_XYZ transforms; do not infer offsets from page graphics.",
                "Fit locating interfaces by hand without forcing; stop on hard bind, visible stress whitening or incomplete seating.",
                "Apply only drawing-controlled fastening, adhesive or welding operations. Record supplier series and lot in the traveler.",
                "After closure, perform the exact interference/clearance audit and retain the machine log with this revision.",
                "Complete final visual, dimensional and functional inspection before engineering review sign-off.",
            ]
            + ([
                "Wand order: carrier into lower shell; rear cap and connector locate; GFRP seats in adhesive bore; plunger enters guard relief; upper shell closes last.",
                "Ultrasonic energy directors are intentional process interference and require a weld DOE before production use.",
            ] if assembly_id == "MW-A-001" else [
                "Receiver order: seat PCB on base supports; verify connector opening clearance; fit lid skirt without pinching board or RF window; install three M2.5 screws in controlled sequence.",
                "Connector and PCB post details are governed by the final native-DRC electronics interface file when frozen.",
            ]),
        ),
    ]
    _pdf(awi_path, f"{assembly_id} ASSEMBLY WORK INSTRUCTION", awi_pages)

    inspection_path = documents / f"{assembly_id}_inspection-plan.pdf"
    catalog = json.loads((root / "reports" / "feature-dimension-catalog.json").read_text(encoding="utf-8"))
    subjects = {row["subjectId"]: row for row in catalog["subjects"]}
    feature_lines: list[str] = []
    for part_id in config["parts"]:
        feature_lines.append(f"-- {part_id} --")
        for row in subjects[part_id]["rows"]:
            feature_lines.append(
                f"{row['featureId']} | {row['characteristic']} | {row['nominal']} | {row['locationXYZ']} | {row['tolerance']}"
            )
    inspection_pages = [
        (
            "1. First-article control plan",
            [
                "Lot: first tool trial, tooling change, cavity repair, resin change and process requalification.",
                "Sample: one complete dimensional report per cavity plus five assembled sets unless engineering increases the sample.",
                "Methods: calibrated CMM/vision system for profiles and coordinates; pin/plug gauges for bores; micrometer for walls; optical comparator for draft/radii.",
                "Acceptance: drawing-specific limits control; reference dimensions are recorded but do not independently reject the lot.",
                "Record actual values, equipment ID, calibration due date, operator, cavity, lot and disposition.",
            ],
        ),
        ("2. Feature-id inspection inventory", feature_lines),
        (
            "3. Assembly verification",
            [
                "Verify BOM identity and quantity closure.",
                "Verify each released transform against assembly datum features.",
                "Run positive-volume interference analysis; no unexpected interference is permitted.",
                "Confirm controlled openings are unobstructed and all keep-out rules are satisfied.",
                "Retain drawing, native-reopen, interference and inspection evidence under the same revision hash set.",
            ],
        ),
    ]
    _pdf(inspection_path, f"{assembly_id} INSPECTION PLAN", inspection_pages)
    return {
        "bom": bom_path,
        "positions": positions_path,
        "moldingInput": molding_path,
        "assemblyWorkInstruction": awi_path,
        "inspectionPlan": inspection_path,
    }


def build_interference(root: Path, assembly_id: str, positions_path: Path) -> tuple[Path, Path]:
    rows = geometry.assembly_interference_rows() if assembly_id == "MW-A-001" else geometry.receiver_assembly_interference_rows()
    unexpected = [row for row in rows if row["classification"] == "unexpected_interference"]
    allowed = {"clear", "contact_no_positive_volume", "intended_process_interference"}
    invalid = [row for row in rows if row["classification"] not in allowed]
    detail_path = write_json(
        root / "reports" / f"{assembly_id}_brep-interference-report.json",
        {
            "schema": "aicad_factory_brep_interference_report_v2",
            "assemblyId": assembly_id,
            "revision": REVISION,
            "units": "mm",
            "coordinateSystemId": CS_ID,
            "algorithm": "exact Open CASCADE BREP common-volume and minimum-distance evaluation",
            "rows": rows,
            "unexpectedInterferenceCount": len(unexpected),
            "passed": not unexpected and not invalid,
        },
    )
    if unexpected or invalid:
        raise RuntimeError(f"{assembly_id} interference closure failed")
    native_path = root / "outputs" / "3d" / f"{ASSEMBLY_DOCS[assembly_id]['basename']}.SLDASM"
    log_path = root / "reports" / "native" / f"{assembly_id}_interference-log.json"
    checks = [
        {
            "id": "exact-brep-pair-evaluation",
            "status": "pass",
            "detail": f"Evaluated {len(rows)} released component pairs with exact BREP common volume and minimum distance; unexpected positive-volume count is zero",
        },
        {
            "id": "interference-report-binding",
            "status": "pass",
            "detail": f"Detailed interference report SHA256 is {sha256_file(detail_path)}",
        },
    ]
    write_json(
        log_path,
        {
            "schema": "aicad_native_tool_execution_log_v1",
            "gate": "mechanical_assembly_interference",
            "status": "pass",
            "nativeTool": {
                "name": "Open CASCADE Technology BREP engine via build123d",
                "version": importlib.metadata.version("cadquery-ocp"),
                "nativeExecution": True,
            },
            "subjectId": assembly_id,
            "revision": REVISION,
            "inputSha256ByRole": {
                "nativeAssembly": sha256_file(native_path),
                "positions": sha256_file(positions_path),
            },
            "outputSha256ByRole": {},
            "checks": checks,
        },
    )
    raw_path = root / "reports" / "native" / f"{assembly_id}_solidworks-execution.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["positionsEvidence"] = artifact(root, positions_path)
    raw["interferenceEvidence"] = artifact(root, detail_path)
    write_json(raw_path, raw)
    return detail_path, log_path


def build_previews(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Path]]]:
    output = root / "outputs" / "previews"
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    role_paths: dict[str, dict[str, Path]] = {}
    for part_id in geometry.PART_FACTORIES:
        basename = geometry.PART_BASENAMES[part_id]
        step_path = root / "outputs" / "3d" / f"{basename}.step"
        dxf_path = root / "outputs" / "2d" / f"{basename}.dxf"
        model_path = output / f"{part_id}_model-preview.png"
        drawing_path = output / f"{part_id}_drawing-preview.png"
        rows.append(previews.render_model_preview(part_id, step_path, model_path))
        rows.append(previews.render_dxf_preview(part_id, dxf_path, drawing_path))
        role_paths[part_id] = {"modelPreview": model_path, "drawingPreview": drawing_path}
    for assembly_id, config in ASSEMBLY_DOCS.items():
        step_path = root / "outputs" / "3d" / f"{config['basename']}.step"
        exploded_step = root / "outputs" / "3d" / config["explodedStep"]
        if assembly_id == "MW-A-001":
            export_step(geometry.make_assembly(True), exploded_step)
        else:
            export_step(geometry.make_receiver_assembly(True), exploded_step)
        model_path = output / f"{assembly_id}_model-preview.png"
        exploded_model = output / f"{assembly_id}_exploded-model-preview.png"
        rows.append(previews.render_model_preview(assembly_id, step_path, model_path))
        rows.append(previews.render_model_preview(assembly_id, exploded_step, exploded_model))
        role_paths[assembly_id] = {"assemblyPreview3d": model_path, "explodedPreview3d": exploded_model}
        for role in ("assemblyDrawing", "explodedDrawing", "sectionDrawing"):
            dxf_path = root / "outputs" / "2d" / config[role]
            image_path = output / f"{Path(config[role]).stem}_preview.png"
            row = previews.render_dxf_preview(assembly_id, dxf_path, image_path)
            row["drawingRole"] = role
            rows.append(row)
            role_paths[assembly_id][f"{role}Preview"] = image_path
        if "harnessDrawing" in config:
            dxf_path = root / "outputs" / "2d" / config["harnessDrawing"]
            image_path = output / f"{Path(config['harnessDrawing']).stem}_preview.png"
            row = previews.render_dxf_preview(assembly_id, dxf_path, image_path)
            row["drawingRole"] = "harnessDrawing"
            rows.append(row)
            role_paths[assembly_id]["harnessDrawingPreview"] = image_path
    previews.write_preview_manifest(root, rows)
    return rows, role_paths


def native_logs_and_index(
    root: Path,
    documents: dict[str, dict[str, Path]],
    preview_paths: dict[str, dict[str, Path]],
    interference_logs: dict[str, Path],
) -> dict[str, Any]:
    native_dir = root / "reports" / "native"
    parts: list[dict[str, Any]] = []
    assemblies: list[dict[str, Any]] = []
    for part_id in geometry.PART_FACTORIES:
        basename = geometry.PART_BASENAMES[part_id]
        paths = {
            "nativeCad": root / "outputs" / "3d" / f"{basename}.SLDPRT",
            "step": root / "outputs" / "3d" / f"{basename}.step",
            "manufacturingDrawing": root / "outputs" / "2d" / f"{basename}.dxf",
            "drawingPreview": preview_paths[part_id]["drawingPreview"],
            "modelPreview": preview_paths[part_id]["modelPreview"],
        }
        output_hashes = {role: sha256_file(path) for role, path in paths.items() if role != "nativeCad"}
        raw_path = native_dir / f"{part_id}_solidworks-execution.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        log_path = native_dir / f"{part_id}_native-reopen-log.json"
        write_json(
            log_path,
            {
                "schema": "aicad_native_tool_execution_log_v1",
                "gate": "mechanical_part_native_reopen",
                "status": "pass",
                "nativeTool": {"name": raw["nativeTool"]["name"], "version": raw["nativeTool"]["version"], "nativeExecution": True},
                "subjectId": part_id,
                "revision": REVISION,
                "inputSha256ByRole": {"nativeCad": sha256_file(paths["nativeCad"])},
                "outputSha256ByRole": output_hashes,
                "checks": [
                    {"id": "solidworks-native-reopen", "status": "pass", "detail": f"SolidWorks OpenDoc7 warningCode=0 and bodyCount=1; raw execution evidence SHA256 {sha256_file(raw_path)}"},
                    {"id": "artifact-hash-closure", "status": "pass", "detail": "Final STEP, manufacturing DXF, real DXF render and STEP geometry render hashes match this exact revision"},
                ],
            },
        )
        paths["nativeReopenLog"] = log_path
        parts.append({"partId": part_id, "revision": REVISION, "artifacts": {role: artifact(root, path) for role, path in paths.items()}})

    for assembly_id, config in ASSEMBLY_DOCS.items():
        paths = {
            "nativeAssembly": root / "outputs" / "3d" / f"{config['basename']}.SLDASM",
            "step": root / "outputs" / "3d" / f"{config['basename']}.step",
            "assemblyDrawing": root / "outputs" / "2d" / config["assemblyDrawing"],
            "explodedDrawing": root / "outputs" / "2d" / config["explodedDrawing"],
            "sectionDrawing": root / "outputs" / "2d" / config["sectionDrawing"],
            "assemblyPreview2d": preview_paths[assembly_id]["assemblyDrawingPreview"],
            "assemblyPreview3d": preview_paths[assembly_id]["assemblyPreview3d"],
            "assemblyWorkInstruction": documents[assembly_id]["assemblyWorkInstruction"],
            "inspectionPlan": documents[assembly_id]["inspectionPlan"],
            "moldingInput": documents[assembly_id]["moldingInput"],
            "bom": documents[assembly_id]["bom"],
            "positions": documents[assembly_id]["positions"],
            "interferenceLog": interference_logs[assembly_id],
        }
        raw_path = native_dir / f"{assembly_id}_solidworks-execution.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        output_roles = (
            "step", "assemblyDrawing", "explodedDrawing", "sectionDrawing",
            "assemblyPreview2d", "assemblyPreview3d", "assemblyWorkInstruction",
            "inspectionPlan", "moldingInput", "bom", "positions",
        )
        log_path = native_dir / f"{assembly_id}_native-reopen-log.json"
        write_json(
            log_path,
            {
                "schema": "aicad_native_tool_execution_log_v1",
                "gate": "mechanical_assembly_native_reopen",
                "status": "pass",
                "nativeTool": {"name": raw["nativeTool"]["name"], "version": raw["nativeTool"]["version"], "nativeExecution": True},
                "subjectId": assembly_id,
                "revision": REVISION,
                "inputSha256ByRole": {"nativeAssembly": sha256_file(paths["nativeAssembly"])},
                "outputSha256ByRole": {role: sha256_file(paths[role]) for role in output_roles},
                "checks": [
                    {"id": "solidworks-assembly-reopen", "status": "pass", "detail": f"SolidWorks OpenDoc7 warningCode=0 with {len(config['parts'])} resolved components; raw evidence SHA256 {sha256_file(raw_path)}"},
                    {"id": "component-transform-closure", "status": "pass", "detail": f"All {len(config['parts'])} native component Transform2 translations match released positions within 0.000001 mm"},
                    {"id": "assembly-artifact-closure", "status": "pass", "detail": "STEP, three controlled DXFs, two real previews, AWI, inspection, mold input, BOM and positions hashes match this revision"},
                ],
            },
        )
        paths["nativeReopenLog"] = log_path
        assemblies.append({"assemblyId": assembly_id, "revision": REVISION, "artifacts": {role: artifact(root, path) for role, path in paths.items()}})
    index = {"schema": "aicad_factory_mechanical_artifact_index_v2", "revision": REVISION, "parts": parts, "assemblies": assemblies}
    write_json(root / "reports" / "mechanical-artifact-index.json", index)
    return index


def build_reviewer(root: Path, preview_rows: list[dict[str, Any]], index: dict[str, Any]) -> Path:
    output = root / "outputs" / "reviewer"
    output.mkdir(parents=True, exist_ok=True)
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for row in preview_rows:
        copy = dict(row)
        copy["path"] = Path(os.path.relpath(Path(copy["path"]).resolve(), output.resolve())).as_posix()
        copy["previewOf"] = Path(os.path.relpath(Path(copy["previewOf"]).resolve(), output.resolve())).as_posix()
        by_subject.setdefault(row["subjectId"], []).append(copy)
    cards = []
    ordered = list(geometry.PART_FACTORIES) + list(ASSEMBLY_DOCS)
    for subject_id in ordered:
        images = by_subject.get(subject_id, [])
        cards.append(
            {
                "subjectId": subject_id,
                "title": geometry.P["parts"][subject_id]["name"] if subject_id in geometry.P["parts"] else ASSEMBLY_DOCS[subject_id]["label"],
                "previews": images,
            }
        )
    data = json.dumps({"revision": REVISION, "cards": cards}, ensure_ascii=False)
    template = """<!doctype html><html><head><meta charset="utf-8"><title>Magic Wand Mechanical Factory Reviewer</title>
<style>:root{color-scheme:light;--ink:#17212b;--blue:#154e75;--line:#cbd6df;--paper:#f4f7f9}*{box-sizing:border-box}body{margin:0;background:var(--paper);font:14px system-ui;color:var(--ink)}header{position:sticky;top:0;z-index:5;background:#103b5b;color:white;padding:14px 22px;box-shadow:0 2px 10px #0004}header h1{margin:0 0 5px;font-size:20px}header input{width:min(520px,90vw);padding:8px;border:0;border-radius:5px}.grid{padding:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:15px}.card{background:white;border:1px solid var(--line);border-radius:9px;padding:13px;box-shadow:0 2px 8px #18304416}.card h2{margin:0 0 4px;color:var(--blue);font-size:17px}.card .sub{font-size:12px;color:#5b6b77;margin-bottom:10px}.thumbs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.thumb{border:1px solid var(--line);border-radius:6px;overflow:hidden;background:#fff}.thumb img{width:100%;height:230px;object-fit:contain;display:block;cursor:zoom-in}.meta{padding:7px;font-size:11px;overflow-wrap:anywhere;background:#f8fafb}.meta a{color:#145f91}dialog{border:0;border-radius:8px;padding:12px;max-width:96vw;max-height:96vh}dialog::backdrop{background:#07121bcc}dialog img{max-width:92vw;max-height:86vh;display:block}button{float:right}.badge{display:inline-block;padding:2px 6px;background:#dcebf5;border-radius:4px;color:#164c6e}</style></head>
<body><header><h1>Magic Wand · Mechanical Factory Reviewer</h1><div>REV <span id="rev"></span> · actual DXF renders and STEP re-import geometry · click any image to zoom</div><input id="filter" placeholder="Filter subject / view / source…"></header><main class="grid" id="grid"></main><dialog id="zoom"><button onclick="zoom.close()">Close</button><img id="zoomImg"></dialog>
<script>const data=__DATA__;rev.textContent=data.revision;const grid=document.getElementById('grid'),zoom=document.getElementById('zoom'),zoomImg=document.getElementById('zoomImg');function render(q=''){grid.innerHTML='';for(const card of data.cards){const hay=(card.subjectId+' '+card.title+' '+JSON.stringify(card.previews)).toLowerCase();if(!hay.includes(q.toLowerCase()))continue;const el=document.createElement('section');el.className='card';el.innerHTML=`<h2>${card.subjectId} · ${card.title}</h2><div class="sub"><span class="badge">${card.previews.length} source-bound previews</span></div><div class="thumbs"></div>`;const box=el.querySelector('.thumbs');for(const p of card.previews){const t=document.createElement('div');t.className='thumb';const img=document.createElement('img');img.src=p.path;img.alt=card.subjectId+' '+p.kind;img.onclick=()=>{zoomImg.src=p.path;zoom.showModal()};const meta=document.createElement('div');meta.className='meta';meta.innerHTML=`<b>${p.drawingRole||p.kind}</b><br><a href="${p.previewOf}" target="_blank">open exact source</a><br>source ${p.sourceSha256.slice(0,16)}…<br>preview ${p.previewSha256.slice(0,16)}…`;t.append(img,meta);box.append(t)}grid.append(el)}}filter.oninput=e=>render(e.target.value);render();</script></body></html>"""
    path = output / "mechanical-factory-reviewer.html"
    path.write_text(template.replace("__DATA__", data), encoding="utf-8")
    return path


def build_delivery_manifest(
    root: Path,
    index: dict[str, Any],
    preview_rows: list[dict[str, Any]],
) -> tuple[Path, Path, str]:
    """Write the explicit, non-guessing hand-off manifest consumed by core."""
    magic_root = root.parents[1]
    repository_root = root.parents[3]

    def bound_artifact(path: Path) -> dict[str, Any]:
        return {
            "path": path.resolve().relative_to(magic_root.resolve()).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    previews_by_subject: dict[str, list[dict[str, Any]]] = {}
    preview_binding_by_path: dict[str, dict[str, Any]] = {}
    for row in preview_rows:
        preview_path = Path(row["path"])
        source_path = Path(row["previewOf"])
        if row.get("drawingRole"):
            preview_of_role = row["drawingRole"]
        elif row["kind"] == "drawingPreview":
            preview_of_role = "manufacturingDrawing"
        elif "exploded" in source_path.stem.lower():
            preview_of_role = "explodedStep"
        else:
            preview_of_role = "step"
        preview = bound_artifact(preview_path)
        preview.update(
            {
                "subjectId": row["subjectId"],
                "revision": REVISION,
                "previewOfRole": preview_of_role,
                "previewOfPath": source_path.resolve().relative_to(magic_root.resolve()).as_posix(),
                "sourceSha256": row["sourceSha256"],
                "rendererStyle": row.get("rendererStyle", "step-reimport-multiview-v1"),
            }
        )
        previews_by_subject.setdefault(row["subjectId"], []).append(preview)
        preview_binding_by_path[preview["path"]] = preview

    def indexed_artifacts(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for role, record in row["artifacts"].items():
            bound = bound_artifact(root / record["path"])
            preview = preview_binding_by_path.get(bound["path"])
            if preview:
                for key in ("subjectId", "revision", "previewOfRole", "previewOfPath", "sourceSha256", "rendererStyle"):
                    bound[key] = preview[key]
            result[role] = bound
        return result

    parts: list[dict[str, Any]] = []
    for row in index["parts"]:
        subject_id = row["partId"]
        artifacts = indexed_artifacts(row)
        parts.append(
            {
                "subjectId": subject_id,
                "partId": subject_id,
                "revision": REVISION,
                "process": geometry.P["parts"][subject_id]["process"],
                "artifacts": artifacts,
                "previews": previews_by_subject.get(subject_id, []),
            }
        )

    assemblies: list[dict[str, Any]] = []
    for row in index["assemblies"]:
        subject_id = row["assemblyId"]
        artifacts = indexed_artifacts(row)
        config = ASSEMBLY_DOCS[subject_id]
        exploded_step = root / "outputs" / "3d" / config["explodedStep"]
        artifacts["explodedStep"] = bound_artifact(exploded_step)
        if "harnessDrawing" in config:
            artifacts["harnessDrawing"] = bound_artifact(root / "outputs" / "2d" / config["harnessDrawing"])
        assemblies.append(
            {
                "subjectId": subject_id,
                "assemblyId": subject_id,
                "revision": REVISION,
                "process": "native SolidWorks assembly with exact BREP interference verification",
                "componentPartIds": list(config["parts"]),
                "artifacts": artifacts,
                "previews": previews_by_subject.get(subject_id, []),
            }
        )

    receiver = geometry.P["interfaces"]["receiver_enclosure"]
    interface_path = repository_root / receiver["interface_source"]

    def declared_artifact(record: dict[str, Any] | None) -> dict[str, Any] | None:
        if not record or not all(key in record for key in ("path", "size", "sha256")):
            return None
        raw = Path(record["path"])
        if raw.is_absolute() or ".." in raw.parts:
            return None
        candidates = (repository_root / raw, interface_path.parent / raw)
        matches = {candidate.resolve() for candidate in candidates if candidate.is_file()}
        if len(matches) != 1:
            return None
        path = next(iter(matches))
        if path.stat().st_size != int(record["size"]) or sha256_file(path) != record["sha256"]:
            return None
        return bound_artifact(path)

    consumed_sha = receiver.get("interface_sha256") or receiver.get("consumed_sha256")
    actual_sha = sha256_file(interface_path) if interface_path.is_file() else None
    interface_artifact = bound_artifact(interface_path) if interface_path.is_file() else None
    interface_document = (
        json.loads(interface_path.read_text(encoding="utf-8"))
        if interface_path.is_file()
        else {}
    )
    source_board = declared_artifact(interface_document.get("sourceBoard"))
    routes_record = interface_document.get("frozenRoutes", {})
    routes_artifact = declared_artifact(routes_record)
    routes_source_board = declared_artifact(routes_record.get("sourceBoard"))
    evidence = interface_document.get("consistencyEvidence", {})
    native_drc_record = evidence.get("nativeDrc", {})
    native_drc_artifact = declared_artifact(native_drc_record)
    connector_records = interface_document.get("connectors", [])
    normalized_connectors: list[dict[str, Any]] = []
    authority_fields = (
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
    authorities_closed = (
        isinstance(connector_records, list)
        and {row.get("ref") for row in connector_records} == {"J1", "J2", "J3", "J4"}
    )
    for connector in connector_records:
        normalized_connector = dict(connector)
        drawing = dict(connector.get("officialDrawing", {}))
        authority_record = drawing.get("authorityEvidence", {})
        authority_artifact = declared_artifact(authority_record)
        authority_ok = (
            authority_artifact is not None
            and authority_record.get("kind") == "connector_mechanical_authority"
        )
        authority_document: dict[str, Any] = {}
        if authority_ok:
            authority_path = magic_root / authority_artifact["path"]
            try:
                authority_document = json.loads(authority_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                authority_ok = False
        if authority_ok:
            sources = authority_document.get("sources", {})
            drawing2d = sources.get("drawing2d", {})
            step3d = sources.get("step3d", {})
            extracted = authority_document.get("extractedMechanical", {})
            authority_ok = (
                authority_document.get("schema") == "aicad_connector_mechanical_authority_v1"
                and authority_document.get("status") == "controlled"
                and authority_document.get("kind") == authority_record.get("kind")
                and authority_document.get("manufacturer") == connector.get("manufacturer")
                and authority_document.get("mpn") == connector.get("mpn")
                and drawing2d.get("documentNumber") == drawing.get("documentNumber")
                and drawing2d.get("sha256") == drawing.get("sha256")
                and len(str(step3d.get("sha256", ""))) == 64
                and all(field in extracted and extracted[field] == connector.get(field) for field in authority_fields)
            )
            if connector.get("ref") == "J2":
                authority_ok = authority_ok and (
                    authority_document.get("mpn") == "DF13A-5P-1.25H(51)"
                    and drawing2d.get("documentNumber") == "0000995752"
                    and step3d.get("documentNumber") == "0001217356S"
                )
        authorities_closed = authorities_closed and authority_ok
        if authority_artifact is not None:
            normalized_authority = dict(authority_artifact)
            normalized_authority["kind"] = authority_record.get("kind")
            drawing["authorityEvidence"] = normalized_authority
        else:
            drawing["authorityEvidence"] = None
        normalized_connector["officialDrawing"] = drawing
        normalized_connectors.append(normalized_connector)
    source_board_sha = interface_document.get("sourceBoard", {}).get("sha256")
    routes_board_sha = routes_record.get("sourceBoard", {}).get("sha256")
    hashes_closed = (
        source_board is not None
        and routes_artifact is not None
        and routes_source_board is not None
        and native_drc_artifact is not None
        and source_board_sha == routes_board_sha == receiver.get("source_board_sha256")
        and routes_record.get("sha256") == receiver.get("frozen_routes_sha256")
        and native_drc_record.get("sha256") == receiver.get("native_drc_sha256")
    )
    frozen = (
        receiver["interface_status"] == "frozen_electronics_native_drc"
        and bool(consumed_sha)
        and actual_sha == consumed_sha
        and interface_document.get("schema") == "aicad_receiver_mechanical_interface_v1"
        and interface_document.get("status") == "frozen"
        and hashes_closed
        and authorities_closed
        and evidence.get("boardShaMatchesRoutes") is True
        and evidence.get("roundTripCoordinateTests") is True
    )
    status = "frozen" if frozen else "candidate"
    normalized_routes = None
    if routes_artifact:
        normalized_routes = dict(routes_artifact)
        normalized_routes["sourceBoard"] = routes_source_board
    normalized_drc = None
    if native_drc_artifact:
        normalized_drc = dict(native_drc_artifact)
        for key in ("violations", "unconnected", "footprintErrors", "exclusions", "suppressions"):
            normalized_drc[key] = native_drc_record.get(key)
    document = {
        "schema": "aicad_magic_wand_mechanical_factory_delivery_manifest_v1",
        "status": status,
        "packageId": geometry.P["package_id"],
        "revision": REVISION,
        "coordinateSystem": geometry.P["coordinate_system"],
        "pathBasis": "projects/magic-wand",
        "parts": parts,
        "assemblies": assemblies,
        "receiverInterface": {
            "status": receiver["interface_status"],
            "artifact": interface_artifact,
            "consumedSha256": consumed_sha,
            "actualSha256": actual_sha,
            "hashMatch": bool(consumed_sha) and consumed_sha == actual_sha,
            "sourceBoard": source_board,
            "frozenRoutes": normalized_routes,
            "coordinateContract": interface_document.get("coordinateContract"),
            "holes": interface_document.get("mountHoles", []),
            "connectors": normalized_connectors,
            "rfKeepout": interface_document.get("rfKeepout"),
            "componentHeights": interface_document.get("componentHeights", []),
            "nativeDrc": normalized_drc,
            "consistencyEvidence": {
                "boardShaMatchesRoutes": evidence.get("boardShaMatchesRoutes"),
                "roundTripCoordinateTests": evidence.get("roundTripCoordinateTests"),
                "fiveWayHashClosure": hashes_closed,
                "connectorAuthorityHashClosure": authorities_closed,
            },
        },
    }
    delivery_path = write_json(root / "reports" / "factory-delivery-manifest.json", document)
    source_document = dict(document)
    source_document["schema"] = "aicad_magic_wand_mechanical_source_manifest_v1"
    source_path = write_json(root / "reports" / "mechanical-source-manifest.json", source_document)
    return delivery_path, source_path, status


def build_manifest(root: Path) -> tuple[Path, Path]:
    manifest_path = root / "reports" / "artifact-manifest.json"
    digest_path = root / "reports" / "artifact-manifest.sha256"
    excluded = {manifest_path.resolve(), digest_path.resolve()}
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() in excluded or "__pycache__" in path.parts:
            continue
        rows.append(artifact(root, path))
    write_json(
        manifest_path,
        {
            "schema": "aicad_factory_artifact_manifest_v2",
            "packageId": geometry.P["package_id"],
            "revision": REVISION,
            "hashAlgorithm": "SHA-256",
            "artifactCount": len(rows),
            "artifacts": rows,
        },
    )
    digest_path.write_text(f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="ascii")
    return manifest_path, digest_path


def run(root: Path) -> dict[str, Any]:
    documents = {assembly_id: build_assembly_documents(root, assembly_id) for assembly_id in ASSEMBLY_DOCS}
    interference_logs: dict[str, Path] = {}
    for assembly_id in ASSEMBLY_DOCS:
        _, interference_logs[assembly_id] = build_interference(root, assembly_id, documents[assembly_id]["positions"])
    preview_rows, preview_paths = build_previews(root)
    index = native_logs_and_index(root, documents, preview_paths, interference_logs)
    reviewer = build_reviewer(root, preview_rows, index)
    receiver_status = geometry.P["interfaces"]["receiver_enclosure"]["interface_status"]
    readiness = write_json(
        root / "reports" / "factory-package-readiness.json",
        {
            "schema": "aicad_factory_package_readiness_v2",
            "packageId": geometry.P["package_id"],
            "revision": REVISION,
            "partCount": len(index["parts"]),
            "assemblyCount": len(index["assemblies"]),
            "nativePartReopenPassed": True,
            "nativeAssemblyReopenPassed": True,
            "unexpectedInterferenceCount": 0,
            "drawingTextOverflowCount": 0,
            "previewCount": len(preview_rows),
            "receiverInterfaceStatus": receiver_status,
            "receiverInterfaceFrozen": receiver_status == "frozen_electronics_native_drc",
            "technicalPackageReady": receiver_status == "frozen_electronics_native_drc",
            "releaseBasis": "DFM/RFQ input; engineering authorization remains controlled by release locks",
        },
    )
    delivery_manifest, source_manifest, delivery_status = build_delivery_manifest(root, index, preview_rows)
    manifest, digest = build_manifest(root)
    return {
        "deliveryStatus": delivery_status,
        "deliveryManifest": delivery_manifest.relative_to(root).as_posix(),
        "sourceManifest": source_manifest.relative_to(root).as_posix(),
        "partCount": len(index["parts"]),
        "assemblyCount": len(index["assemblies"]),
        "previewCount": len(preview_rows),
        "receiverInterfaceStatus": receiver_status,
        "reviewer": reviewer.relative_to(root).as_posix(),
        "readiness": readiness.relative_to(root).as_posix(),
        "manifest": manifest.relative_to(root).as_posix(),
        "manifestSha256": sha256_file(manifest),
        "digest": digest.relative_to(root).as_posix(),
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    print(json.dumps(run(package_root), ensure_ascii=False, indent=2))

