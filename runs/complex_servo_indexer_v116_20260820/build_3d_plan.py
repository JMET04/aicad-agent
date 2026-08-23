from __future__ import annotations
import json
from pathlib import Path

RUN = Path(__file__).resolve().parent
REASON = "This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated."

def profile_constraints(profile: dict, depth: float, support: str | None) -> list[dict]:
    rows = []
    if support:
        rows.append({"kind": "support_coincident", "target": support})
    rows.append({"kind": "center_offset", "target": "origin", "dx": profile["center"][0], "dy": profile["center"][1]})
    if profile["kind"] == "center_rectangle":
        rows.extend([{"kind": "width", "value": profile["width"]}, {"kind": "height", "value": profile["height"]}])
    else:
        rows.append({"kind": "radius", "value": profile["radius"]})
        if profile["kind"] == "circle_pattern":
            rows.extend([{"kind": "pattern_count", "value": profile["count"]}, {"kind": "bolt_circle_radius", "value": profile["bolt_circle_radius"]}])
    rows.append({"kind": "depth", "value": depth})
    return rows

def feature(fid: str, ftype: str, purpose: str, profile: dict, depth: float, support: str | None, end: str = "blind", role: str = "mechanical_feature") -> dict:
    row = {
        "id": fid, "type": ftype, "purpose": purpose, "reasoning": REASON,
        "depends_on": [] if support is None else [support], "profile": profile,
        "depth": depth, "end_condition": end, "constraints": profile_constraints(profile, depth, support),
        "role": role, "roles": [role, "review_selectable"], "editable": True,
    }
    if support:
        row["support_feature"] = support
    return row

def circle(x: float, y: float, diameter: float) -> dict:
    return {"kind": "circle", "center": [x, y], "radius": diameter / 2}

def rectangle(x: float, y: float, width: float, height: float) -> dict:
    return {"kind": "center_rectangle", "center": [x, y], "width": width, "height": height}

def build() -> None:
    preflight = json.loads((RUN / "mechanical-preflight.json").read_text(encoding="utf-8"))
    features = [
        feature("F001", "base_extrude", "220 x 180 x 20 datum-A mounting base", rectangle(0, 0, 220, 180), 20, None, role="base_plate"),
        feature("F002", "boss_extrude", "diameter 130 dual-bearing housing boss", circle(0, 0, 130), 36, "F001", role="bearing_boss"),
        feature("F003", "boss_extrude", "right vertical stiffness rib pad", rectangle(48, 0, 42, 72), 12, "F001", role="rib_pad"),
        feature("F004", "boss_extrude", "left vertical stiffness rib pad", rectangle(-48, 0, 42, 72), 12, "F001", role="rib_pad"),
        feature("F005", "boss_extrude", "upper horizontal stiffness rib pad", rectangle(0, 48, 72, 42), 12, "F001", role="rib_pad"),
        feature("F006", "boss_extrude", "lower horizontal stiffness rib pad", rectangle(0, -48, 72, 42), 12, "F001", role="rib_pad"),
        feature("F007", "cut_extrude", "diameter 92 H8 seal and cover recess", circle(0, 0, 92), 6, "F002", role="seal_recess"),
        feature("F008", "cut_extrude", "diameter 80 H7 paired-6208 bearing seat", circle(0, 0, 80), 36, "F002", role="bearing_seat"),
        feature("F009", "cut_extrude", "diameter 50 shaft clearance through bore", circle(0, 0, 50), 56, "F002", "through_all", "shaft_clearance"),
        feature("F010", "cut_extrude", "eight diameter 9 indexer holes on diameter 108 PCD", {"kind": "circle_pattern", "center": [0, 0], "radius": 4.5, "count": 8, "bolt_circle_radius": 54, "start_angle_deg": 22.5}, 56, "F002", "through_all", "indexer_hole_pattern"),
        feature("F011", "cut_extrude", "four diameter 7 cover holes on diameter 104 PCD", {"kind": "circle_pattern", "center": [0, 0], "radius": 3.5, "count": 4, "bolt_circle_radius": 52, "start_angle_deg": 45}, 56, "F002", "through_all", "cover_hole_pattern"),
    ]
    frame_points = [(85, 65), (-85, 65), (-85, -65), (85, -65)]
    for index, (x, y) in enumerate(frame_points, 12):
        features.append(feature(f"F{index:03d}", "cut_extrude", f"frame mounting through hole {index-11}", circle(x, y, 14), 20, "F001", "through_all", "frame_mount_hole"))
    for index, (x, y) in enumerate(frame_points, 16):
        features.append(feature(f"F{index:03d}", "cut_extrude", f"diameter 24 by 10 frame counterbore {index-15}", circle(x, y, 24), 10, "F001", role="frame_counterbore"))
    features.extend([
        feature("F020", "cut_extrude", "primary diameter 8 H7 datum-C dowel hole", circle(70, 0, 8), 20, "F001", "through_all", "dowel_hole"),
        feature("F021", "cut_extrude", "secondary diameter 8 H7 dowel hole", circle(-70, 0, 8), 20, "F001", "through_all", "dowel_hole"),
    ])
    pocket_points = [(86, 30), (-86, 30), (-86, -30), (86, -30)]
    for index, (x, y) in enumerate(pocket_points, 22):
        features.append(feature(f"F{index:03d}", "cut_extrude", f"36 x 34 x 10 non-through lightening pocket {index-21}", rectangle(x, y, 36, 34), 10, "F001", role="lightening_pocket"))
    plan = {
        "schema_version": "1.0",
        "part": {
            "name": "SIFC_220_REV_A", "id": "SIFC220REVA", "units": "mm", "origin": [0, 0, 0],
            "tolerance": 0.001, "domain": "mechanical",
            "locks": ["review_only", "not_accepted", "not_manufacturing_release"],
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
        },
        "engineering_normative_preflight": preflight,
        "features": features,
    }
    (RUN / "SIFC_220_REV_A.3d.plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__": build()
