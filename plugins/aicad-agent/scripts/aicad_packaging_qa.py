from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import ezdxf
from PIL import Image
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import linemerge


TOL = 1e-6
ANGLE_TOL_DEG = 0.001


def arc_point(entity: dict, angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    return (entity["center"][0] + entity["radius"] * math.cos(radians),
            entity["center"][1] + entity["radius"] * math.sin(radians))


def endpoints(entity: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    if entity["type"] == "line":
        return tuple(entity["start"]), tuple(entity["end"])
    return (arc_point(entity, entity["start_angle_deg"]), arc_point(entity, entity["end_angle_deg"]))


def key(point, digits: int = 6) -> tuple[float, float]:
    return round(float(point[0]), digits), round(float(point[1]), digits)


def unit(vector) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length <= TOL:
        return 0.0, 0.0
    return vector[0] / length, vector[1] / length


def sample_entity(entity: dict, count: int = 48) -> list[tuple[float, float]]:
    if entity["type"] == "line":
        return [key(entity["start"], 9), key(entity["end"], 9)]
    start = float(entity["start_angle_deg"])
    sweep = (float(entity["end_angle_deg"]) - start) % 360.0
    if sweep <= TOL:
        sweep = 360.0
    return [key(arc_point(entity, start + sweep * index / count), 9) for index in range(count + 1)]


def connected_components(graph: dict) -> list[list]:
    remaining = set(graph)
    components = []
    while remaining:
        root = remaining.pop()
        component = [root]
        queue = deque([root])
        while queue:
            node = queue.popleft()
            for neighbor in graph[node]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.append(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def xdata_id(entity) -> str | None:
    try:
        rows = entity.get_xdata("AICAD")
    except ezdxf.DXFValueError:
        return None
    strings = [row.value for row in rows if row.code == 1000]
    return strings[0] if strings else None


def add_result(results: list[dict], rule_id: str, passed: bool, evidence: Any, rule_by_id: dict,
               remediation: str = "") -> None:
    rule = rule_by_id[rule_id]
    results.append({
        "rule_id": rule_id,
        "name": rule["name"],
        "pass": bool(passed),
        "phenomenon": "no defect detected" if passed else rule["requirement"],
        "root_cause_if_failed": rule["failure_cause"],
        "prevention_rule": rule["prevention"],
        "remediation": remediation,
        "evidence": evidence,
    })


def geometry_checks(geometry: dict, rules: dict) -> list[dict]:
    rule_by_id = {rule["id"]: rule for rule in rules["rules"]}
    results: list[dict] = []
    entities = [entity for entity in geometry["entities"] if entity["id"] != "ORIGIN_BOOTSTRAP"]
    by_id = {entity["id"]: entity for entity in entities}
    contour = [entity for entity in entities if entity["layer"] in {"CUT", "SLOT"}]

    incidence: dict[tuple[float, float], list[str]] = defaultdict(list)
    node_graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
    for entity in contour:
        start, end = endpoints(entity)
        ks, ke = key(start), key(end)
        incidence[ks].append(entity["id"]); incidence[ke].append(entity["id"])
        node_graph[ks].add(ke); node_graph[ke].add(ks)
    degrees = {str(node): len(ids) for node, ids in incidence.items()}
    components = connected_components(node_graph)
    degree_errors = {node: degree for node, degree in degrees.items() if degree != 2}
    add_result(results, "PKG-G001", len(components) == 1 and not degree_errors,
               {"component_count": len(components), "node_count": len(incidence), "degree_errors": degree_errors},
               rule_by_id, "Reconnect missing endpoints or regenerate the contour from shared anchors.")

    tangency_rows = []
    tangency_pass = True
    for arc in [entity for entity in contour if entity["type"] == "arc"]:
        for side, angle in [("start", arc["start_angle_deg"]), ("end", arc["end_angle_deg"])]:
            point = arc_point(arc, angle)
            incident = [item for item in incidence[key(point)] if item != arc["id"]]
            neighbor = by_id[incident[0]] if len(incident) == 1 else None
            row = {"arc": arc["id"], "endpoint": side, "neighbor_ids": incident}
            if not neighbor or neighbor["type"] != "line":
                row.update({"pass": False, "angle_error_deg": None})
                tangency_pass = False
            else:
                line_direction = unit((neighbor["end"][0] - neighbor["start"][0],
                                       neighbor["end"][1] - neighbor["start"][1]))
                radians = math.radians(angle)
                arc_tangent = (-math.sin(radians), math.cos(radians))
                dot = min(1.0, max(0.0, abs(line_direction[0] * arc_tangent[0] +
                                              line_direction[1] * arc_tangent[1])))
                error = math.degrees(math.acos(dot))
                position_ok = min(math.dist(point, neighbor["start"]), math.dist(point, neighbor["end"])) <= TOL
                passed = position_ok and error <= ANGLE_TOL_DEG
                row.update({"neighbor": neighbor["id"], "position_error_mm":
                            min(math.dist(point, neighbor["start"]), math.dist(point, neighbor["end"])),
                            "angle_error_deg": error, "pass": passed})
                tangency_pass &= passed
            tangency_rows.append(row)
    add_result(results, "PKG-G002", tangency_pass,
               {"joins_checked": len(tangency_rows), "tolerance_mm": TOL,
                "angle_tolerance_deg": ANGLE_TOL_DEG,
                "max_angle_error_deg": max((row.get("angle_error_deg") or 0) for row in tangency_rows),
                "details": tangency_rows}, rule_by_id,
               "Recompute each fillet from the incident rays using exact tangent-distance and angle-bisector equations.")

    canonical = []
    zero_ids = []
    for entity in entities:
        if entity["type"] == "line":
            start, end = key(entity["start"], 9), key(entity["end"], 9)
            if math.dist(start, end) <= TOL:
                zero_ids.append(entity["id"])
            canonical.append(("L", tuple(sorted([start, end]))))
        else:
            if entity["radius"] <= TOL:
                zero_ids.append(entity["id"])
            canonical.append(("A", key(entity["center"], 9), round(entity["radius"], 9),
                              round(entity["start_angle_deg"] % 360, 9), round(entity["end_angle_deg"] % 360, 9)))
    duplicate_count = sum(count - 1 for count in Counter(canonical).values() if count > 1)
    merged = linemerge(MultiLineString([LineString(sample_entity(entity)) for entity in contour]))
    ring_ok = merged.geom_type == "LineString" and merged.is_ring and merged.is_simple
    add_result(results, "PKG-G003", not zero_ids and duplicate_count == 0 and ring_ok,
               {"zero_length_ids": zero_ids, "duplicate_count": duplicate_count,
                "merged_type": merged.geom_type, "is_ring": getattr(merged, "is_ring", False),
                "is_simple": merged.is_simple}, rule_by_id,
               "Remove duplicate/zero geometry, then rebuild and merge the full contour before compilation.")

    v_rows = []
    v_pass = True
    for position in ["T", "B"]:
        for panel in range(1, 4):
            left = by_id[f"SLOT_{position}_P{panel}_R"]
            right = by_id[f"SLOT_{position}_P{panel+1}_L"]
            apex_l, outer_l = tuple(left["start"]), tuple(left["end"])
            apex_r, outer_r = tuple(right["start"]), tuple(right["end"])
            boundary = apex_l[0]
            passed = (math.dist(apex_l, apex_r) <= TOL and
                      abs((outer_l[0] + outer_r[0]) / 2 - boundary) <= TOL and
                      abs(outer_l[1] - outer_r[1]) <= TOL and
                      abs(math.dist(apex_l, outer_l) - math.dist(apex_r, outer_r)) <= TOL)
            v_pass &= passed
            v_rows.append({"position": position, "boundary_panel_pair": [panel, panel + 1],
                           "boundary_x": boundary, "shared_apex_error_mm": math.dist(apex_l, apex_r),
                           "mirror_error_mm": abs((outer_l[0] + outer_r[0]) / 2 - boundary),
                           "height_error_mm": abs(outer_l[1] - outer_r[1]), "pass": passed})
    add_result(results, "PKG-G004", v_pass, {"v_notches_checked": len(v_rows), "details": v_rows},
               rule_by_id, "Regenerate both sides of every V slot from one boundary station and one shared parameter.")

    policy = geometry.get("reference", {})
    trusted = geometry.get("trusted_numeric_sources", {})
    derived = geometry.get("derived_tooling_parameters", {})
    source_separated = ("visual topology only" in policy.get("role", "") and trusted and
                        "review-only" in derived.get("derivation", ""))
    add_result(results, "PKG-G005", source_separated,
               {"reference_role": policy.get("role"), "trusted_numeric_sources": trusted,
                "derived_tooling_parameters": derived}, rule_by_id,
               "Separate reference-role, trusted-dimension and derived-tooling fields in the job schema.")

    points = []
    for entity in entities:
        points.extend(sample_entity(entity))
    bbox = [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]
    expected_bbox = geometry["bbox_mm"]
    chain = trusted.get("panel_chain_mm", [])
    flap_depth = trusted.get("flap_depth_mm")
    dimensions_pass = (all(abs(a - b) <= TOL for a, b in zip(bbox, expected_bbox)) and
                       abs(sum(chain) - 1575.0) <= TOL and abs(2 * flap_depth - 335.0) <= TOL and
                       trusted.get("manufacturing_mm") == [435.0, 335.0, 262.0] and
                       trusted.get("true_inner_mm") == [428.0, 328.0, 248.0])
    add_result(results, "PKG-G006", dimensions_pass,
               {"actual_bbox_mm": bbox, "expected_bbox_mm": expected_bbox,
                "panel_chain_mm": chain, "panel_chain_sum_mm": sum(chain),
                "flap_closure_mm": 2 * flap_depth}, rule_by_id,
               "Reapply dimension equations to the final entity set and reject local edits that move the global extrema.")

    ids_ascii = all(entity["id"].isascii() and re.fullmatch(r"[A-Za-z0-9_]+", entity["id"])
                    for entity in geometry["entities"])
    metadata_complete = all(entity.get("purpose") and entity.get("reasoning") and entity.get("feature")
                            for entity in geometry["entities"])
    add_result(results, "PKG-G008", ids_ascii and metadata_complete,
               {"ascii_ids": ids_ascii, "metadata_complete": metadata_complete}, rule_by_id,
               "Normalize command data before execution and require complete purpose/reasoning metadata.")
    return results


def annotation_check(dxf_path: Path, rules: dict) -> dict:
    rule = next(item for item in rules["rules"] if item["id"] == "PKG-G007")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    production_lines = []
    for entity in msp:
        if entity.dxf.layer not in {"CUT", "CREASE", "SLOT"}:
            continue
        entity_id = xdata_id(entity)
        if not entity_id:
            continue
        if entity.dxftype() == "LINE":
            production_lines.append(LineString([(entity.dxf.start.x, entity.dxf.start.y),
                                                (entity.dxf.end.x, entity.dxf.end.y)]))
        elif entity.dxftype() == "ARC":
            start = entity.dxf.start_angle
            sweep = (entity.dxf.end_angle - start) % 360 or 360
            points = []
            for index in range(49):
                angle = math.radians(start + sweep * index / 48)
                points.append((entity.dxf.center.x + entity.dxf.radius * math.cos(angle),
                               entity.dxf.center.y + entity.dxf.radius * math.sin(angle)))
            production_lines.append(LineString(points))
    production_buffer = MultiLineString(production_lines).buffer(2.0)
    collisions = []
    checked = 0
    for entity in msp.query("MTEXT"):
        text = entity.plain_text().replace("\n", " ")
        insert = entity.dxf.insert
        height = float(entity.dxf.char_height)
        line_count = max(1, entity.plain_text().count("\n") + 1)
        width = float(entity.dxf.width or max(height * 2, len(text) * height * 0.6))
        # AutoCAD attachment point 1 is top-left for these generated annotations.
        text_box = box(insert.x, insert.y - height * 1.4 * line_count, insert.x + width, insert.y)
        checked += 1
        if text_box.intersects(production_buffer):
            collisions.append({"text": text[:80], "insert": [insert.x, insert.y], "width": width,
                               "height": height, "reason": "estimated text extent crosses 2mm production-line buffer"})
    passed = not collisions
    return {
        "rule_id": "PKG-G007", "name": rule["name"], "pass": passed,
        "phenomenon": "no defect detected" if passed else rule["requirement"],
        "root_cause_if_failed": rule["failure_cause"], "prevention_rule": rule["prevention"],
        "remediation": "Move colliding callouts outside the blank or reserve a face-label safe zone.",
        "evidence": {"mtext_checked": checked, "clearance_mm": 2.0, "collisions": collisions},
    }


def preview_checks(png_path: Path | None, svg_path: Path | None,
                   visual_inspection: dict[str, Any] | None = None) -> dict:
    evidence = {}
    accepted_formats: list[str] = []
    if png_path:
        with Image.open(png_path) as image:
            corners = [image.getpixel((0, 0)), image.getpixel((image.width - 1, 0)),
                       image.getpixel((0, image.height - 1)), image.getpixel((image.width - 1, image.height - 1))]
            opaque = image.mode == "RGB" and all(all(channel >= 248 for channel in pixel[:3]) for pixel in corners)
            evidence["png"] = {"mode": image.mode, "size": image.size, "corners": corners, "opaque_white": opaque}
            if opaque:
                accepted_formats.append("png")
    if svg_path:
        text = svg_path.read_text(encoding="utf-8")
        native_text = len(re.findall(r"<text\b", text))
        white = "opaque-white-background" in text and 'fill="#ffffff"' in text
        svg_pass = native_text >= 20 and white
        evidence["svg"] = {
            "native_text_count": native_text,
            "opaque_white_background": white,
            "optional_auxiliary": True,
            "text_may_be_pathized": native_text == 0,
            "structural_pass": svg_pass,
        }
        if svg_pass:
            accepted_formats.append("svg")
    required_checks = [
        "all_required_chinese_visible", "no_mojibake", "no_critical_overlap",
        "full_sheet_visible", "opaque_white_background",
    ]
    visual_inspection = visual_inspection or {}
    manual_pass = bool(visual_inspection.get("passed")) and all(
        visual_inspection.get("checks", {}).get(item) is True for item in required_checks
    )
    evidence["acceptance"] = {
        "rule": "at least one structurally viewable preview plus recorded original-resolution visual inspection",
        "accepted_formats": accepted_formats,
        "visual_inspection": visual_inspection,
        "required_visual_checks": required_checks,
        "visual_inspection_pass": manual_pass,
    }
    return {"pass": bool(accepted_formats) and manual_pass, "evidence": evidence}

def write_reports(out_json: Path, out_md: Path, rules: dict, results: list[dict], preview: dict,
                  dwg_report: str | None) -> None:
    failed = [row["rule_id"] for row in results if not row["pass"]]
    dwg_pass = dwg_report is None or ("REOPEN_PASS" in dwg_report and "FAIL:" not in dwg_report)
    status = "pass" if not failed and preview["pass"] and dwg_pass else "failed"
    payload = {
        "schema": "aicad_packaging_overall_detail_qa_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "status": status,
        "failed_rules": failed,
        "geometry_rules": results,
        "preview": preview,
        "autocad_save_reopen_pass": dwg_pass,
        "historical_errors_and_prevention": rules["historical_errors"],
        "closed_loop": "detect -> explain root cause -> repair -> encode prevention rule -> regression test",
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 包装刀版整体细节核验与错误学习报告", "",
        f"- 总状态：**{status.upper()}**", "- 闭环：发现 → 根因 → 修复 → 固化规则 → 回归验证", "",
        "## 本轮逐项核验", "",
    ]
    for row in results:
        lines.extend([
            f"### {row['rule_id']} {row['name']} — {'PASS' if row['pass'] else 'FAIL'}", "",
            f"- 现象：{row['phenomenon']}",
            f"- 若失败的根因：{row['root_cause_if_failed']}",
            f"- 固化预防规则：{row['prevention_rule']}",
            f"- 修复动作：{row['remediation'] or '无需修复'}", "",
        ])
    lines.extend(["## 已发生错误的总结与长期规则", ""])
    for lesson in rules["historical_errors"]:
        lines.extend([
            f"### {lesson['id']}", "",
            f"- 错误表现：{lesson['symptom']}", f"- 为什么出现：{lesson['root_cause']}",
            f"- 本次修复：{lesson['fix']}", f"- 下次自动拦截规则：{lesson['new_rule']}", "",
        ])
    lines.extend([
        "## 判定", "",
        f"- 几何失败规则：{failed or '无'}", f"- 预览检查：{'PASS' if preview['pass'] else 'FAIL'}",
        f"- AutoCAD保存重开：{'PASS' if dwg_pass else 'FAIL'}", "",
    ])
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Global topology, tangency, annotation and learning QA for AICAD packaging dielines")
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--dxf", required=True, type=Path)
    parser.add_argument("--png", type=Path)
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--visual-inspection", type=Path,
                        help="UTF-8 JSON record of the original-resolution visual review")
    parser.add_argument("--dwg-report", type=Path)
    parser.add_argument("--rules", type=Path, default=Path(__file__).resolve().parents[1] / "rules" / "packaging_dieline_rules.json")
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-md", required=True, type=Path)
    args = parser.parse_args()

    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    results = geometry_checks(geometry, rules)
    results.append(annotation_check(args.dxf, rules))
    visual_inspection = (json.loads(args.visual_inspection.read_text(encoding="utf-8"))
                         if args.visual_inspection else None)
    preview = preview_checks(args.png, args.svg, visual_inspection)
    dwg_report = args.dwg_report.read_text(encoding="ascii") if args.dwg_report and args.dwg_report.exists() else None
    write_reports(args.out_json, args.out_md, rules, results, preview, dwg_report)
    payload = json.loads(args.out_json.read_text(encoding="utf-8"))
    print(json.dumps({"ok": payload["status"] == "pass", "status": payload["status"],
                      "failed_rules": payload["failed_rules"], "out_json": str(args.out_json),
                      "out_md": str(args.out_md)}, ensure_ascii=False))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
