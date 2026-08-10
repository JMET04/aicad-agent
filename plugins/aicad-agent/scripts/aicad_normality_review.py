from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


LOCKS = {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True}
LAYER_COLORS = {"CUT": "#d62828", "SLOT": "#c026d3", "CREASE": "#2563eb", "GLUE": "#15803d"}
FACE_LABELS = {
    "BODY_PANEL_1": "面板1", "BODY_PANEL_2": "面板2", "BODY_PANEL_3": "面板3", "BODY_PANEL_4": "面板4",
    "BOTTOM_CRASH_P1": "下主锁底片1", "BOTTOM_CRASH_P2": "下辅锁底片2",
    "BOTTOM_CRASH_P3": "下主锁底片3", "BOTTOM_CRASH_P4": "下辅锁底片4",
    "TOP_DUST_PANEL_2": "上防尘摇翼2", "TOP_TUCK_PANEL_3": "上主插舌摇盖",
    "TOP_DUST_PANEL_4": "上防尘摇翼4", "SIDE_GLUE_FLAP": "侧糊口",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_point(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-number point")
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(item) for item in point):
        raise ValueError(f"{label} must be finite")
    return point


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def build_catalog(geometry: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    entities = geometry["entities"]
    edges = []
    endpoint_map: dict[str, tuple[float, float]] = {}
    for index, entity in enumerate(entities, 1):
        start = finite_point(entity["start"], f"{entity['id']}.start")
        end = finite_point(entity["end"], f"{entity['id']}.end")
        endpoint_map[f"{entity['id']}.start"] = start
        endpoint_map[f"{entity['id']}.end"] = end
        edges.append({
            "id": f"D{index:02d}", "sourceId": entity["id"], "layer": entity["layer"],
            "start": list(start), "end": list(end), "purpose": entity["purpose"],
            "reasoning": entity["reasoning"], "dependencies": entity["dependencies"],
        })
    corners = []
    vertex_points: dict[str, tuple[float, float]] = {}
    for index, vertex in enumerate(template["vertices"], 1):
        references = list(vertex["refs"])
        if not references or references[0] not in endpoint_map:
            raise ValueError(f"vertex {vertex['id']} has no resolvable production endpoint")
        point = endpoint_map[references[0]]
        mismatch = max(math.dist(point, endpoint_map[reference]) for reference in references)
        if mismatch > float(template["toleranceMm"]):
            raise ValueError(f"vertex {vertex['id']} endpoint mismatch {mismatch}")
        vertex_points[str(vertex["id"])] = point
        corners.append({
            "id": f"C{index:02d}", "sourceId": vertex["id"], "point": list(point),
            "purpose": vertex["purpose"], "refs": references,
        })
    faces = []
    for feature in template["features"]:
        if not feature.get("countsAsFace"):
            continue
        faces.append({
            "id": f"F{len(faces) + 1:02d}", "sourceId": feature["id"],
            "label": FACE_LABELS.get(str(feature["id"]), str(feature["id"])),
            "purpose": feature["purpose"],
            "polygon": [list(vertex_points[str(vertex_id)]) for vertex_id in feature["polygonVertexIds"]],
            "entityIds": feature["entityIds"],
        })
    return {
        "schema": "aicad_normality_review_catalog_v1",
        "profile": {"id": template["profileId"], "version": template["profileVersion"]},
        "closureSystem": template["closureSystem"],
        "coordinateSystem": {"units": "mm", "origin": [0, 0], "yAxis": "up"},
        "edges": edges, "corners": corners, "faces": faces, "locks": dict(LOCKS),
    }


def model_bounds(catalog: dict[str, Any]) -> tuple[float, float, float, float]:
    points = [finite_point(point, "catalog point") for edge in catalog["edges"] for point in (edge["start"], edge["end"])]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def draw_dashed(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], fill: str, width: int) -> None:
    length = math.dist(start, end)
    if length <= 0:
        return
    dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
    cursor, dash, gap = 0.0, 18.0, 10.0
    while cursor < length:
        finish = min(cursor + dash, length)
        a = start[0] + dx * cursor, start[1] + dy * cursor
        b = start[0] + dx * finish, start[1] + dy * finish
        draw.line([a, b], fill=fill, width=width)
        cursor += dash + gap


def render_png(catalog: dict[str, Any], target: Path) -> dict[str, Any]:
    width, height = 2600, 1600
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    min_x, min_y, max_x, max_y = model_bounds(catalog)
    left, top, right, bottom = 130, 300, 2470, 1280
    scale = min((right - left) / (max_x - min_x), (bottom - top) / (max_y - min_y))
    x0 = left + ((right - left) - (max_x - min_x) * scale) / 2
    y0 = top + ((bottom - top) - (max_y - min_y) * scale) / 2

    def project(point: list[float] | tuple[float, float]) -> tuple[float, float]:
        return x0 + (float(point[0]) - min_x) * scale, y0 + (max_y - float(point[1])) * scale

    title, subtitle, label_font, small = load_font(54, True), load_font(28), load_font(24, True), load_font(20)
    draw.text((130, 55), "顶插舌 / 底自锁折叠纸盒展开图", fill="#111827", font=title)
    draw.text((130, 130), "ECMA A60.20.00.03　上部：插舌开合　下部：两点预粘自动锁底（非上下镜像）", fill="#334155", font=subtitle)
    draw.text((130, 180), "红=切割　洋红=开槽　蓝虚线=压痕　绿=胶区　边D01-D70 / 角C01-C60 / 面F01-F12可在HTML中逐项点选", fill="#475569", font=small)
    for face in catalog["faces"]:
        fill = "#eff6ff"
        if face["sourceId"].startswith("BOTTOM"):
            fill = "#fff7ed"
        elif face["sourceId"].startswith("TOP"):
            fill = "#f0fdf4"
        elif face["sourceId"] == "SIDE_GLUE_FLAP":
            fill = "#dcfce7"
        draw.polygon([project(point) for point in face["polygon"]], fill=fill)
    for edge in catalog["edges"]:
        start, end = project(edge["start"]), project(edge["end"])
        color = LAYER_COLORS.get(edge["layer"], "#111827")
        if edge["layer"] == "CREASE":
            draw_dashed(draw, start, end, color, 4)
        else:
            draw.line([start, end], fill=color, width=6 if edge["layer"] in {"CUT", "SLOT"} else 4)
    for face in catalog["faces"]:
        polygon = [project(point) for point in face["polygon"]]
        cx, cy = sum(p[0] for p in polygon) / len(polygon), sum(p[1] for p in polygon) / len(polygon)
        text_value = f"{face['id']} {face['label']}"
        current_font = label_font
        if face["sourceId"] == "SIDE_GLUE_FLAP":
            text_value = f"{face['id']}\n侧糊口"
            current_font = load_font(15, True)
        box = draw.multiline_textbbox((0, 0), text_value, font=current_font, spacing=1, align="center")
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.rounded_rectangle((cx - tw / 2 - 7, cy - th / 2 - 5, cx + tw / 2 + 7, cy + th / 2 + 5), radius=7, fill="white", outline="#cbd5e1", width=2)
        draw.multiline_text((cx - tw / 2, cy - th / 2), text_value, fill="#0f172a", font=current_font, spacing=1, align="center")
    note_y = 1360
    draw.rounded_rectangle((130, note_y - 30, 2470, 1540), radius=16, fill="#f8fafc", outline="#cbd5e1", width=2)
    draw.text((160, note_y), "结构判断：上、下闭合分别建模。上主插舌轮廓须连续且无内凹腰；下锁底须保留锁口、折叠对角线和预粘胶区。", fill="#0f172a", font=small)
    draw.text((160, note_y + 48), "当前状态：仅供审阅。未开启接受、规则启用或包装放行；不代表材料强度、刀模公差或量产验收。", fill="#7f1d1d", font=small)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)
    corners = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    return {
        "mode": image.mode, "sizePx": [width, height],
        "cornerPixels": [list(image.getpixel(point)) for point in corners],
        "whiteOpaqueBackground": image.mode == "RGB" and all(image.getpixel(point) == (255, 255, 255) for point in corners),
    }


def _svg_text(x: float, y: float, value: str, css_class: str, data_id: str = "") -> str:
    attribute = f' data-id="{html.escape(data_id)}"' if data_id else ""
    return f'<text x="{x:.6f}" y="{y:.6f}" class="{css_class}"{attribute}>{html.escape(value)}</text>'


def svg_document(catalog: dict[str, Any], interactive: bool) -> str:
    min_x, min_y, max_x, max_y = model_bounds(catalog)
    pad_x, pad_top, pad_bottom = 55.0, 80.0, 45.0
    view_w, view_h = max_x - min_x + 2 * pad_x, max_y - min_y + pad_top + pad_bottom

    def project(point: list[float] | tuple[float, float]) -> tuple[float, float]:
        return pad_x + float(point[0]) - min_x, pad_top + max_y - float(point[1])

    body = [
        f'<svg id="cadCanvas" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w:.6f} {view_h:.6f}" role="img" aria-label="上插舌下自锁纸盒展开图">',
        '<rect class="opaque-bg" x="0" y="0" width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(pad_x, 30, "顶插舌 / 底自锁折叠纸盒展开图", "drawing-title"),
        _svg_text(pad_x, 55, "ECMA A60.20.00.03 · 上部插舌开合 / 下部两点预粘自动锁底（非上下镜像）", "drawing-subtitle"),
    ]
    for face in catalog["faces"]:
        points = " ".join(f"{x:.6f},{y:.6f}" for x, y in map(project, face["polygon"]))
        body.append(f'<polygon points="{points}" class="face-fill face-{html.escape(face["id"])}" data-face-id="{html.escape(face["id"])}"/>')
    for edge in catalog["edges"]:
        x1, y1 = project(edge["start"])
        x2, y2 = project(edge["end"])
        attrs = f'x1="{x1:.6f}" y1="{y1:.6f}" x2="{x2:.6f}" y2="{y2:.6f}"'
        body.append(
            f'<g class="cad-edge" data-edge-id="{edge["id"]}" data-source-id="{html.escape(edge["sourceId"])}" '
            f'data-layer="{edge["layer"]}" data-model-start="{edge["start"][0]},{edge["start"][1]}" data-model-end="{edge["end"][0]},{edge["end"][1]}">'
            f'<line class="cad-visible layer-{edge["layer"]}" {attrs}/>'
            + (f'<line class="cad-hit" {attrs}/>' if interactive else "") + "</g>"
        )
        body.append(_svg_text((x1 + x2) / 2 + 3, (y1 + y2) / 2 - 3, edge["id"], "edge-label review-label", edge["id"]))
    for corner in catalog["corners"]:
        x, y = project(corner["point"])
        body.append(f'<circle cx="{x:.6f}" cy="{y:.6f}" r="2.4" class="corner-dot review-label" data-id="{corner["id"]}"/>')
        body.append(_svg_text(x + 3, y + 8, corner["id"], "corner-label review-label", corner["id"]))
    for face in catalog["faces"]:
        points = list(map(project, face["polygon"]))
        cx, cy = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
        label = f"{face['id']} 糊口" if face["sourceId"] == "SIDE_GLUE_FLAP" else f"{face['id']} {face['label']}"
        css_class = f"face-label face-label-{face['id']} review-label"
        body.append(_svg_text(cx, cy, label, css_class, face["id"]))
    body.append("</svg>")
    return "\n".join(body)


def render_svg(catalog: dict[str, Any], target: Path) -> None:
    style = """
<style>
.drawing-title{font:700 21px "Microsoft YaHei",sans-serif;fill:#111827}.drawing-subtitle{font:12px "Microsoft YaHei",sans-serif;fill:#475569}
.face-fill{fill:#f8fafc;stroke:none}.face-F05,.face-F06,.face-F07,.face-F08{fill:#fff7ed}.face-F09,.face-F10,.face-F11{fill:#f0fdf4}.face-F12{fill:#dcfce7}
.cad-visible{fill:none;vector-effect:non-scaling-stroke}.layer-CUT{stroke:#d62828;stroke-width:2}.layer-SLOT{stroke:#c026d3;stroke-width:2}.layer-CREASE{stroke:#2563eb;stroke-width:1.5;stroke-dasharray:7 5}.layer-GLUE{stroke:#15803d;stroke-width:1.5}
.edge-label,.corner-label,.face-label{font-family:"Microsoft YaHei",sans-serif;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}.edge-label{font-size:5px;fill:#334155}.corner-label{font-size:4px;fill:#7c3aed}.face-label{font-size:9px;font-weight:700;text-anchor:middle;fill:#0f172a}.face-label-F12{font-size:5px}.corner-dot{fill:#7c3aed;stroke:#fff;stroke-width:1}
</style>"""
    target.write_text(svg_document(catalog, interactive=False).replace(">", ">" + style, 1) + "\n", encoding="utf-8")


def render_html(catalog: dict[str, Any], target: Path) -> None:
    payload = json.dumps(catalog, ensure_ascii=False).replace("</", "<\\/")
    svg = svg_document(catalog, interactive=True)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>上插舌 / 下自锁 CAD 逐项审查</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#e2e8f0;color:#0f172a;font-family:"Microsoft YaHei",system-ui,sans-serif}}
.app{{display:grid;grid-template-columns:330px minmax(700px,1fr) 360px;gap:14px;padding:14px;min-height:100vh}}.panel,.stage{{background:white;border:1px solid #cbd5e1;border-radius:14px;box-shadow:0 8px 24px #0f172a14}}
.panel{{padding:18px;overflow:auto}}h1{{font-size:22px;margin:0 0 8px}}h2{{font-size:16px;margin:22px 0 8px}}p,.hint{{font-size:13px;line-height:1.65;color:#475569}}.status{{padding:10px;border-radius:9px;background:#fef2f2;color:#991b1b;font-weight:700;font-size:13px}}
.stage{{min-width:0;overflow:auto;padding:10px}}.canvas-wrap{{min-width:1000px}}svg{{display:block;width:100%;height:auto;background:white}}
.drawing-title{{font:700 21px "Microsoft YaHei",sans-serif;fill:#111827}}.drawing-subtitle{{font:12px "Microsoft YaHei",sans-serif;fill:#475569}}
.face-fill{{fill:#f8fafc;stroke:none}}.face-F05,.face-F06,.face-F07,.face-F08{{fill:#fff7ed}}.face-F09,.face-F10,.face-F11{{fill:#f0fdf4}}.face-F12{{fill:#dcfce7}}
.cad-visible{{fill:none;vector-effect:non-scaling-stroke;transition:.12s}}.layer-CUT{{stroke:#d62828;stroke-width:2}}.layer-SLOT{{stroke:#c026d3;stroke-width:2}}.layer-CREASE{{stroke:#2563eb;stroke-width:1.5;stroke-dasharray:7 5}}.layer-GLUE{{stroke:#15803d;stroke-width:1.5}}
.cad-hit{{stroke:transparent;stroke-width:13;fill:none;vector-effect:non-scaling-stroke;cursor:pointer}}.cad-edge:hover .cad-visible{{stroke-width:4}}.cad-edge.selected .cad-visible{{stroke:#f59e0b;stroke-width:6}}
.edge-label,.corner-label,.face-label{{font-family:"Microsoft YaHei",sans-serif;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;pointer-events:none}}.edge-label{{font-size:5px;fill:#334155}}.corner-label{{font-size:4px;fill:#7c3aed}}.face-label{{font-size:9px;font-weight:700;text-anchor:middle;fill:#0f172a}}.face-label-F12{{font-size:5px}}.corner-dot{{fill:#7c3aed;stroke:#fff;stroke-width:1;pointer-events:none}}
body:not(.show-edges) .edge-label,body:not(.show-corners) .corner-label,body:not(.show-corners) .corner-dot,body:not(.show-faces) .face-label{{display:none}}
.toolbar{{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0}}button{{border:1px solid #94a3b8;background:white;color:#0f172a;border-radius:8px;padding:8px 10px;cursor:pointer;font:inherit}}button:hover{{background:#f1f5f9}}button.active{{background:#0f172a;color:white}}button.primary{{background:#2563eb;color:white;border-color:#2563eb}}
.selected-list{{display:grid;gap:7px}}.item{{border:1px solid #cbd5e1;border-radius:9px;padding:9px;font-size:12px}}.item b{{display:block;margin-bottom:4px}}.relations{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.relations button{{text-align:left}}.relations button.satisfied::after{{content:" · 已满足";color:#15803d;font-weight:700}}
textarea{{width:100%;min-height:105px;border:1px solid #94a3b8;border-radius:9px;padding:10px;resize:vertical;font:inherit}}pre{{white-space:pre-wrap;word-break:break-word;background:#f8fafc;border:1px solid #e2e8f0;border-radius:9px;padding:10px;font-size:11px;max-height:260px;overflow:auto}}.hidden{{display:none}}
@media(max-width:1180px){{.app{{grid-template-columns:290px minmax(650px,1fr)}}.right{{grid-column:1/-1}}}}
</style></head>
<body class="show-faces"><main class="app">
<aside class="panel"><h1>逐项结构审查</h1><div class="status">仅供审阅 · 未接受 · 规则未启用 · 包装未放行</div>
<p>直接点击线段即可选择；不需要按 Shift。最多同时保留两条线。高亮线与原线复用同一组 SVG 坐标，因此不会发生偏移。</p>
<div class="toolbar"><button id="toggleEdges">边号 D</button><button id="toggleCorners">角号 C</button><button id="toggleFaces" class="active">面号 F</button><button id="clearSelection">清空选择</button></div>
<h2>当前选择</h2><div id="selectedList" class="selected-list"><span class="hint">尚未选择对象</span></div>
<h2>结构族</h2><p><b>ECMA A60.20.00.03</b><br>上部：插舌开合<br>下部：两点预粘自动锁底<br>上下闭合：明确非镜像</p><p>颜色：红切割、洋红开槽、蓝虚线压痕、绿胶区。</p></aside>
<section class="stage"><div class="canvas-wrap">{svg}</div></section>
<aside class="panel right"><h2>两线关系</h2><div id="relationHint" class="hint">选择两条线后，关系选项会立即出现。</div>
<div id="relations" class="relations hidden"></div><h2>文字纠错</h2><textarea id="correctionText" placeholder="例如：D33 与 D37 应平行；上主插舌不得向中间凹；下部必须是自锁底。"></textarea>
<div class="toolbar"><button id="addText" class="primary">加入纠错意图</button><button id="downloadDraft">导出纠错 JSON</button></div>
<h2>审计草稿</h2><pre id="draft">尚无纠错意图。所有操作仅生成审阅草稿，不直接改写生产几何。</pre></aside>
</main>
<script>
const catalog={payload};const selected=[];const drafts=[];
const relationDefinitions=[["parallel","平行"],["perpendicular","垂直"],["collinear","共线"],["coincident_endpoint","端点重合"],["equal_length","等长"],["symmetric_link","对称/联动"]];
const edgeMap=new Map(catalog.edges.map(edge=>[edge.id,edge]));
function vector(edge){{return [edge.end[0]-edge.start[0],edge.end[1]-edge.start[1]]}}function length(edge){{const [x,y]=vector(edge);return Math.hypot(x,y)}}
function currentRelations(a,b){{const [ax,ay]=vector(a),[bx,by]=vector(b),tol=1e-6;const cross=ax*by-ay*bx,dot=ax*bx+ay*by;const parallel=Math.abs(cross)<=tol*Math.max(1,length(a)*length(b));const pointLine=Math.abs((b.start[0]-a.start[0])*ay-(b.start[1]-a.start[1])*ax);const endpoint=[a.start,a.end].some(p=>[b.start,b.end].some(q=>Math.hypot(p[0]-q[0],p[1]-q[1])<=tol));return {{parallel,perpendicular:Math.abs(dot)<=tol*Math.max(1,length(a)*length(b)),collinear:parallel&&pointLine<=tol*Math.max(1,length(a)),coincident_endpoint:endpoint,equal_length:Math.abs(length(a)-length(b))<=tol,symmetric_link:false}}}}
function renderSelection(){{document.querySelectorAll(".cad-edge").forEach(group=>group.classList.toggle("selected",selected.includes(group.dataset.edgeId)));const list=document.getElementById("selectedList");if(!selected.length)list.innerHTML='<span class="hint">尚未选择对象</span>';else list.innerHTML=selected.map(id=>{{const e=edgeMap.get(id);return '<div class="item"><b>'+id+' · '+e.sourceId+'</b>'+e.layer+' · '+e.purpose+'<br>('+e.start.join(", ")+') → ('+e.end.join(", ")+')</div>'}}).join("");const box=document.getElementById("relations"),hint=document.getElementById("relationHint");if(selected.length!==2){{box.classList.add("hidden");hint.textContent="选择两条线后，关系选项会立即出现。";return}}const a=edgeMap.get(selected[0]),b=edgeMap.get(selected[1]),state=currentRelations(a,b);hint.textContent=selected.join(" + ")+"：请选择要表达的数学关系。";box.classList.remove("hidden");box.innerHTML=relationDefinitions.map(([key,label])=>'<button data-relation="'+key+'" class="'+(state[key]?"satisfied":"")+'">'+label+'</button>').join("");box.querySelectorAll("button").forEach(button=>button.addEventListener("click",()=>addRelation(button.dataset.relation,button.textContent.replace(" · 已满足",""),state[button.dataset.relation]))) }}
function addRelation(key,label,satisfied){{drafts.push({{type:"relationship",relation:key,label,members:[...selected],alreadySatisfied:!!satisfied,status:satisfied?"verified_existing":"candidate_intent",locks:catalog.locks}});renderDraft()}}
function renderDraft(){{document.getElementById("draft").textContent=drafts.length?JSON.stringify({{schema:"aicad_review_correction_draft_v1",profile:catalog.profile,closureSystem:catalog.closureSystem,intents:drafts,locks:catalog.locks}},null,2):"尚无纠错意图。所有操作仅生成审阅草稿，不直接改写生产几何。"}}
document.querySelectorAll(".cad-edge").forEach(group=>group.querySelector(".cad-hit").addEventListener("click",event=>{{event.stopPropagation();const id=group.dataset.edgeId,index=selected.indexOf(id);if(index>=0)selected.splice(index,1);else{{if(selected.length===2)selected.shift();selected.push(id)}}renderSelection()}}));
document.getElementById("clearSelection").onclick=()=>{{selected.splice(0);renderSelection()}};
for(const [buttonId,className] of [["toggleEdges","show-edges"],["toggleCorners","show-corners"],["toggleFaces","show-faces"]])document.getElementById(buttonId).onclick=event=>{{document.body.classList.toggle(className);event.currentTarget.classList.toggle("active")}};
document.getElementById("addText").onclick=()=>{{const input=document.getElementById("correctionText"),text=input.value.trim();if(!text)return;drafts.push({{type:"natural_language",text,selectedEdges:[...selected],status:"candidate_intent",locks:catalog.locks}});input.value="";renderDraft()}};
document.getElementById("downloadDraft").onclick=()=>{{const value={{schema:"aicad_review_correction_draft_v1",profile:catalog.profile,closureSystem:catalog.closureSystem,intents:drafts,locks:catalog.locks}},blob=new Blob([JSON.stringify(value,null,2)],{{type:"application/json;charset=utf-8"}}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="aicad-correction-draft.json";link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)}};
renderSelection();
</script></body></html>"""
    target.write_text(document, encoding="utf-8")


def validate_review(geometry: dict[str, Any], template: dict[str, Any], proof: dict[str, Any], catalog: dict[str, Any], png_evidence: dict[str, Any], svg_path: Path, html_path: Path, visual_inspection_reviewed: bool) -> dict[str, Any]:
    source_ids = [str(item["id"]) for item in geometry["entities"]]
    catalog_ids = [str(item["sourceId"]) for item in catalog["edges"]]
    coordinates_match = all(edge["start"] == geometry["entities"][index]["start"] and edge["end"] == geometry["entities"][index]["end"] for index, edge in enumerate(catalog["edges"]))
    svg_text, html_text = svg_path.read_text(encoding="utf-8"), html_path.read_text(encoding="utf-8")
    checks = {
        "sourceNormalityProofPass": proof.get("status") == "pass",
        "edgeCatalogExactAndOrdered": source_ids == catalog_ids and coordinates_match,
        "edgeCount70": len(catalog["edges"]) == 70,
        "cornerCount60": len(catalog["corners"]) == 60,
        "faceCount12": len(catalog["faces"]) == 12,
        "typedClosuresAsymmetric": template["closureSystem"].get("top") != template["closureSystem"].get("bottom") and template["closureSystem"].get("asymmetric") is True,
        "pngWhiteOpaqueRgb": png_evidence["whiteOpaqueBackground"],
        "svgHasNativeChineseText": "<text" in svg_text and "顶插舌" in svg_text and "自动锁底" in svg_text,
        "htmlUsesOneCoordinateSetForVisibleAndHitLines": 'class="cad-visible' in html_text and 'class="cad-hit"' in html_text and "data-model-start" in html_text,
        "plainClickTwoEdgeSelectionAndRelations": "if(selected.length===2)selected.shift()" in html_text and "relationDefinitions" in html_text,
        "allLabelsPresent": all(edge["id"] in html_text for edge in catalog["edges"]) and all(corner["id"] in html_text for corner in catalog["corners"]) and all(face["id"] in html_text for face in catalog["faces"]),
        "originalResolutionVisualInspectionRecorded": visual_inspection_reviewed,
        "locksClosed": all(catalog["locks"].get(key) == value for key, value in LOCKS.items()),
    }
    return {
        "schema": "aicad_normality_review_validation_v1", "status": "pass" if all(checks.values()) else "failed",
        "checks": checks, "counts": {"edges": len(catalog["edges"]), "corners": len(catalog["corners"]), "faces": len(catalog["faces"])},
        "closureSystem": template["closureSystem"], "png": png_evidence, "locks": dict(LOCKS),
        "visualInspection": {
            "status": "pass" if visual_inspection_reviewed else "pending_manual_view_image",
            "method": "full-sheet view plus title/top-closure/bottom-lock detail crops",
            "result": "white opaque background; Chinese title and face labels readable; top tuck profile has no inward waist; bottom lock notches, diagonals and glue zones visible; no critical label/geometry overlap" if visual_inspection_reviewed else "not yet recorded",
        },
    }


def write_validation_markdown(report: dict[str, Any], target: Path) -> None:
    lines = [
        "# AICAD 正常性审查面验证", "", f"- 自动检查状态：**{report['status'].upper()}**",
        f"- 对象：边 {report['counts']['edges']}、角 {report['counts']['corners']}、结构面 {report['counts']['faces']}",
        f"- 闭合：上={report['closureSystem']['top']}；下={report['closureSystem']['bottom']}；非镜像={report['closureSystem']['asymmetric']}",
        "", "## 自动门禁", "",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} — {name}" for name, passed in report["checks"].items())
    lines.extend(["", "## 边界", "", "白底、原生中文文本、对象数量、可点击命中线与可见线同坐标已自动检查。最终是否存在视觉遮挡仍须通过原始分辨率人工查看后回填，不得由自动检查冒充。", "", "reviewOnly=true, accepted=false, ruleEnabled=false, packagingGated=true"])
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a white, Chinese-readable and directly selectable review surface from a proved AICAD structure family")
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--name", default="normality_review")
    parser.add_argument("--visual-inspection-reviewed", action="store_true")
    args = parser.parse_args()
    geometry, template, proof = read_json(args.geometry), read_json(args.template), read_json(args.proof)
    if proof.get("status") != "pass":
        raise ValueError("review surface generation is blocked until the normality proof passes")
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = build_catalog(geometry, template)
    catalog_path, png_path = out_dir / f"{args.name}.object_catalog.json", out_dir / f"{args.name}.png"
    svg_path, html_path = out_dir / f"{args.name}.svg", out_dir / f"{args.name}.html"
    validation_json, validation_md = out_dir / f"{args.name}.validation.json", out_dir / f"{args.name}.validation.md"
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    png_evidence = render_png(catalog, png_path)
    render_svg(catalog, svg_path)
    render_html(catalog, html_path)
    validation = validate_review(geometry, template, proof, catalog, png_evidence, svg_path, html_path, args.visual_inspection_reviewed)
    validation_json.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_validation_markdown(validation, validation_md)
    artifact_paths = [catalog_path, png_path, svg_path, html_path, validation_json, validation_md]
    manifest = {
        "schema": "aicad_normality_review_manifest_v1", "status": validation["status"], "profile": catalog["profile"],
        "files": [{"path": path.name, "sha256": sha256(path), "sizeBytes": path.stat().st_size} for path in artifact_paths],
        "locks": dict(LOCKS),
    }
    manifest_path = out_dir / f"{args.name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": validation["status"], "html": str(html_path), "png": str(png_path), "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0 if validation["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
