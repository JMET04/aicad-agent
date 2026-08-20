from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[2]
PLUGIN_ROOT = REPO_ROOT / "agent-plugin" / "aicad-agent"
PARAMETERS_PATH = ROOT / "design-parameters.json"
DESIGN_BASIS_PATH = ROOT / "authority" / "engineering-design-basis.json"
STANDARDS_PATH = ROOT / "authority" / "selected-standards-scope.json"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_row(source_id: str, kind: str, description: str, relative_path: str, revision: str) -> dict[str, Any]:
    path = ROOT / relative_path
    return {
        "id": source_id,
        "kind": kind,
        "description": description,
        "path": relative_path,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "mediaType": "application/json",
        "authorityRevision": revision,
    }


def load_preflight_builder() -> Any:
    source = PLUGIN_ROOT / "scripts" / "aicad_engineering_preflight.py"
    spec = importlib.util.spec_from_file_location("mw_aicad_engineering_preflight", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load AICAD preflight builder: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate_generation_constraint(gate_path: str) -> str:
    key = gate_path.casefold()
    if any(word in key for word in ("load", "strength", "stiffness", "fatigue", "factorofsafety")):
        return (
            "Keep structural acceptance locked; bind LC01 through LC04 from MW-MECH-DB-001 and require material-property, "
            "coupon and calculation evidence before any strength, stiffness, fatigue or safety-factor claim."
        )
    if any(word in key for word in ("fastener", "bearing", "thread", "joint")):
        return (
            "Generate an explicit zero-item baseline for fasteners, bearings and threads; if any such item is introduced, "
            "invalidate this preflight and require a revised interface, sizing and verification record."
        )
    if any(word in key for word in ("thermal", "temperature")):
        return (
            "Constrain this review prototype to the 5 to 40 degree C dry indoor envelope and keep thermal, battery and "
            "polymer-temperature acceptance locked until representative enclosure testing is attached."
        )
    if any(word in key for word in ("material", "process", "stock", "coating", "finish", "surface")):
        return (
            "Use only the review-grade material and process labels in design-parameters.json; preserve lot, orientation, "
            "conditioning, coating and final-process qualification as release-blocking evidence items."
        )
    if any(word in key for word in ("tolerance", "datum", "geometr", "fit", "dimension", "edge")):
        return (
            "Drive every critical dimension from design-parameters.json, use datum A rear plane, datum B common axis and "
            "datum C actuator radial plane, and retain explicit inspection limits without inferring production capability."
        )
    if any(word in key for word in ("assembly", "service", "tool", "inspection", "measurement")):
        return (
            "Preserve sliding assembly access, positive declared clearances and the inspection sequence in ASSEMBLY_DFM_TEST.md; "
            "block hammer assembly, hidden interference and unmeasured critical interfaces."
        )
    if any(word in key for word in ("risk", "safety", "abnormal")):
        return (
            "Keep press-to-arm, supervised indoor use and all six release locks active; forbid impact use, mains switching, "
            "direct propulsion control and any acceptance statement without physical risk review."
        )
    if any(word in key for word in ("bom", "revision", "quantity", "drawing", "sheet", "title", "detail")):
        return (
            "Generate revision-A part plans, drawing plans, BOM quantities and hash manifest from the one parameter source; "
            "require exact part-number and revision parity before exposing a later manufacturing candidate."
        )
    return (
        "Bind this canonical gate to MW-MECH-DB-001 and MW-MECH-STD-001, preserve review-only locks, and verify the "
        "parameter-derived plan and evidence manifest before allowing the next controlled generation stage."
    )


def gate_verification_method(gate_path: str) -> str:
    key = gate_path.casefold()
    if any(word in key for word in ("inspection", "measurement", "tolerance", "fit", "datum", "dimension")):
        return "Run the deterministic package tests, then inspect the listed critical characteristic with the method in ASSEMBLY_DFM_TEST.md."
    if any(word in key for word in ("native", "materialdatabase", "drawingannotation")):
        return "Require SolidWorks save/reopen, native material readback and feature-bound annotation evidence; absence keeps native authority false."
    return "Run the deterministic package tests and AICAD validator, compare source hashes, and retain human engineering review as a separate gate."


def build_preflight() -> dict[str, Any]:
    module = load_preflight_builder()
    preflight = module.build_template("mechanical")
    preflight["contractId"] = "MW_MECHANICAL_CONTROLLED_GENERATION_PREFLIGHT_A"
    preflight["revision"] = 1
    preflight["deliveryStage"] = "review"
    preflight["sources"] = [
        source_row(
            "STD_AUTHORITY",
            "selected_standard",
            "Controlled review-scope selection of the canonical mechanical standards ledger; compliance is not asserted.",
            "authority/selected-standards-scope.json",
            "MW-MECH-STD-001-A",
        ),
        source_row(
            "ENG_INPUT",
            "approved_engineering_input",
            "Task-authorized controlled prototype design basis; external professional release approval is outside this authority.",
            "authority/engineering-design-basis.json",
            "MW-MECH-DB-001-A",
        ),
    ]
    for standard in preflight["applicableStandards"]:
        standard["scopeDecision"] = (
            "Selected for review-stage GPS and drawing control only; obtain a controlled copy and confirm edition, scope and jurisdiction before release."
        )
    for application in preflight["ruleApplications"]:
        gate_path = application["gatePath"]
        application["disposition"] = "constrained"
        application["generationConstraint"] = gate_generation_constraint(gate_path)
        application["verificationMethod"] = gate_verification_method(gate_path)
        application["verifierId"] = "canonical_rule_check"
    return preflight


def feature_circle(
    feature_id: str,
    feature_type: str,
    radius: float,
    depth: float,
    purpose: str,
    reasoning: str,
    depends_on: list[str],
    support_feature: str | None = None,
    end_condition: str = "blind",
) -> dict[str, Any]:
    feature: dict[str, Any] = {
        "id": feature_id,
        "type": feature_type,
        "purpose": purpose,
        "reasoning": reasoning,
        "depends_on": depends_on,
        "profile": {"kind": "circle", "center": [0, 0], "radius": radius},
        "depth": depth,
        "end_condition": end_condition,
        "constraints": [
            {"kind": "center_offset", "target": "origin", "dx": 0, "dy": 0},
            {"kind": "radius", "value": radius},
            {"kind": "depth", "value": depth},
        ],
        "role": "outline" if feature_type == "base_extrude" else ("boss" if feature_type == "boss_extrude" else "hole"),
    }
    if support_feature is not None:
        feature["support_feature"] = support_feature
        feature["constraints"].insert(0, {"kind": "support_coincident", "target": support_feature})
    return feature


def feature_rectangle(
    feature_id: str,
    feature_type: str,
    width: float,
    height: float,
    depth: float,
    purpose: str,
    reasoning: str,
    depends_on: list[str],
    support_feature: str | None = None,
    end_condition: str = "blind",
) -> dict[str, Any]:
    feature: dict[str, Any] = {
        "id": feature_id,
        "type": feature_type,
        "purpose": purpose,
        "reasoning": reasoning,
        "depends_on": depends_on,
        "profile": {"kind": "center_rectangle", "center": [0, 0], "width": width, "height": height},
        "depth": depth,
        "end_condition": end_condition,
        "constraints": [
            {"kind": "center_offset", "target": "origin", "dx": 0, "dy": 0},
            {"kind": "width", "value": width},
            {"kind": "height", "value": height},
            {"kind": "depth", "value": depth},
        ],
        "role": "outline" if feature_type == "base_extrude" else ("boss" if feature_type == "boss_extrude" else "pocket"),
    }
    if support_feature is not None:
        feature["support_feature"] = support_feature
        feature["constraints"].insert(0, {"kind": "support_coincident", "target": support_feature})
    return feature


def part_plan(name: str, part_id: str, preflight: dict[str, Any], features: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "part": {
            "name": name,
            "id": part_id,
            "units": "mm",
            "origin": [0, 0, 0],
            "tolerance": 0.001,
            "domain": "mechanical",
            "locks": [
                "review_only_prototype",
                "native_topology_requires_host_reopen",
                "manufacturing_release_forbidden",
            ],
            "review_policy": {
                "reviewOnly": True,
                "accepted": False,
                "ruleEnabled": False,
                "domainGated": True,
            },
        },
        "engineering_normative_preflight": copy.deepcopy(preflight),
        "features": features,
    }


def build_3d_plans(params: dict[str, Any], preflight: dict[str, Any]) -> dict[str, dict[str, Any]]:
    shell = params["handle_shell"]
    carrier = params["internal_carrier"]
    cap = params["rear_end_cap"]
    connector = params["rod_connector"]
    return {
        "handle_shell.plan.json": part_plan(
            "magic_wand_handle_shell_axial_prototype",
            shell["part_number"],
            preflight,
            [
                feature_circle(
                    "F001", "base_extrude", shell["outer_diameter"] / 2, shell["length"],
                    "Create the nonconductive cylindrical grip shell envelope.",
                    "The origin-centered outer cylinder establishes the common wand axis and the positive-Z shell length.",
                    [],
                ),
                feature_circle(
                    "F002", "cut_extrude", shell["inner_diameter"] / 2, shell["length"],
                    "Create the axial electronics and carrier cavity.",
                    "A concentric through cut leaves the exact declared radial wall and an open tube for sliding assembly.",
                    ["F001"], "F001", "through_all",
                ),
            ],
        ),
        "internal_carrier.plan.json": part_plan(
            "magic_wand_internal_carrier_axial_cage_prototype",
            carrier["part_number"],
            preflight,
            [
                feature_rectangle(
                    "F001", "base_extrude", carrier["outer_width"], carrier["outer_height"], carrier["length"],
                    "Create the carrier outer sliding envelope.",
                    "The centered rectangle stays inside the circular shell bore with a computed positive corner clearance.",
                    [],
                ),
                feature_rectangle(
                    "F002", "cut_extrude", carrier["inner_width"], carrier["inner_height"], carrier["length"],
                    "Create the axial module tunnel and four connected carrier walls.",
                    "The centered through cut leaves the declared uniform rectangular wall while preserving one connected body.",
                    ["F001"], "F001", "through_all",
                ),
            ],
        ),
        "rear_end_cap.plan.json": part_plan(
            "magic_wand_rear_nonconductive_end_cap_prototype",
            cap["part_number"],
            preflight,
            [
                feature_circle(
                    "F001", "base_extrude", cap["flange_diameter"] / 2, cap["exposed_length"],
                    "Create the rear exposed nonconductive flange.",
                    "The flange closes the rear grip end and preserves the full handle diameter at the antenna end.",
                    [],
                ),
                feature_circle(
                    "F002", "boss_extrude", cap["plug_diameter"] / 2, cap["plug_insertion_length"],
                    "Create the concentric sliding plug.",
                    "The smaller boss fits inside the shell bore with the declared diametral prototype clearance.",
                    ["F001"], "F001",
                ),
            ],
        ),
        "rod_connector.plan.json": part_plan(
            "magic_wand_rod_connector_axial_prototype",
            connector["part_number"],
            preflight,
            [
                feature_circle(
                    "F001", "base_extrude", connector["collar_diameter"] / 2, connector["exposed_length"],
                    "Create the external transition collar.",
                    "The collar continues the handle outer diameter over the exact exposed transition length.",
                    [],
                ),
                feature_circle(
                    "F002", "boss_extrude", connector["plug_diameter"] / 2, connector["plug_insertion_length"],
                    "Create the shell insertion plug.",
                    "The smaller concentric boss enters the shell bore with positive diametral clearance and keeps one body.",
                    ["F001"], "F001",
                ),
                feature_circle(
                    "F003", "cut_extrude", connector["spine_bore_diameter"] / 2, connector["total_length"],
                    "Create the continuous GFRP spine adhesive bore.",
                    "The concentric through bore preserves a positive annular wall and lets the spine extend behind the collar.",
                    ["F001", "F002"], "F002", "through_all",
                ),
            ],
        ),
    }


def line_step(
    step_id: str,
    start: dict[str, Any],
    target: tuple[float, float] | None,
    vector: tuple[float, float] | None,
    purpose: str,
    reasoning: str,
    layer: str,
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    construction: dict[str, Any]
    if target is not None:
        construction = {"kind": "to_point", "target": {"point": [target[0], target[1]]}}
    elif vector is not None:
        construction = {"kind": "vector", "dx": vector[0], "dy": vector[1]}
    else:
        raise ValueError("line needs target or vector")
    return {
        "id": step_id,
        "type": "line",
        "purpose": purpose,
        "reasoning": reasoning,
        "start": start,
        "construction": construction,
        "constraints": constraints,
        "layer": layer,
        "role": {"OUTLINE": "outline", "HIDDEN": "interface", "CENTER": "datum", "SHAFT": "shaft", "KEEP_OUT": "interface", "NOTE_FRAME": "interface"}.get(layer, "interface"),
        "editable": True,
    }


def rectangle_steps(prefix: str, x: float, y: float, width: float, height: float, layer: str, role: str) -> list[dict[str, Any]]:
    p1 = (x, y)
    p2 = (x + width, y)
    p3 = (x + width, y + height)
    p4 = (x, y + height)
    first_start = {"ref": "origin"} if p1 == (0, 0) else {"point": [x, y]}
    first_constraints: list[dict[str, Any]] = [
        {"kind": "horizontal"},
        {"kind": "length", "value": width},
    ]
    if p1 != (0, 0):
        first_constraints.append({"kind": "start_offset", "target": "origin", "dx": x, "dy": y})
    steps = [
        line_step(prefix + "1", first_start, None, (width, 0), role + " lower edge", "Starts the closed typed outline from a controlled datum.", layer, first_constraints),
        line_step(prefix + "2", {"ref": prefix + "1.end"}, p3, None, role + " far edge", "Continues from the preceding endpoint and fixes the transverse extent.", layer, [
            {"kind": "start_coincident", "target": prefix + "1.end"}, {"kind": "vertical"}, {"kind": "length", "value": height}
        ]),
        line_step(prefix + "3", {"ref": prefix + "2.end"}, p4, None, role + " upper edge", "Returns parallel to the first edge with the same exact length.", layer, [
            {"kind": "start_coincident", "target": prefix + "2.end"}, {"kind": "horizontal"}, {"kind": "length", "value": width}
        ]),
        line_step(prefix + "4", {"ref": prefix + "3.end"}, p1, None, role + " closing edge", "Closes the outline at the controlled start point.", layer, [
            {"kind": "start_coincident", "target": prefix + "3.end"}, {"kind": "vertical"}, {"kind": "length", "value": height}, {"kind": "end_coincident", "target": "origin" if p1 == (0, 0) else prefix + "1.start"}
        ]),
    ]
    return steps


def free_line(
    step_id: str,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    layer: str,
    purpose: str,
    role: str,
) -> dict[str, Any]:
    dx = end_xy[0] - start_xy[0]
    dy = end_xy[1] - start_xy[1]
    length = math.hypot(dx, dy)
    constraints: list[dict[str, Any]] = [
        {"kind": "start_offset", "target": "origin", "dx": start_xy[0], "dy": start_xy[1]},
        {"kind": "length", "value": length},
    ]
    if abs(dy) < 1e-9:
        constraints.append({"kind": "horizontal"})
    if abs(dx) < 1e-9:
        constraints.append({"kind": "vertical"})
    return line_step(
        step_id,
        {"point": [start_xy[0], start_xy[1]]},
        end_xy,
        None,
        purpose,
        "The explicit origin-relative start and exact endpoint make this " + role + " deterministic.",
        layer,
        constraints,
    )


def dimension_step(
    step_id: str,
    first_ref: str,
    second_ref: str,
    base_xy: tuple[float, float],
    measurement: float,
    orientation: float,
    purpose: str,
    dimension_kind: str,
    dimension_purpose: str = "general",
    first_xy: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "dimension",
        "purpose": purpose,
        "reasoning": "The dimension is bound to earlier physical geometry and carries an explicit measurement, orientation and base offset.",
        "first": {"ref": first_ref},
        "second": {"ref": second_ref},
        "base": {"point": [base_xy[0], base_xy[1]]},
        "dimension_kind": dimension_kind,
        "dimension_purpose": dimension_purpose,
        "style_name": "AICAD_MECH",
        "constraints": [
            {"kind": "dimension_measurement", "value": measurement},
            {"kind": "dimension_orientation", "value": orientation},
            {"kind": "base_offset", "target": first_ref, "dx": base_xy[0] - first_xy[0], "dy": base_xy[1] - first_xy[1]},
        ],
        "layer": "DIMENSION",
        "role": "interface",
    }


def circle_step(step_id: str, center: tuple[float, float], diameter: float, layer: str, purpose: str, role: str = "outline") -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "circle",
        "purpose": purpose,
        "reasoning": "The end-view circle is tied to an explicit origin-relative center and exact diameter.",
        "center": {"point": [center[0], center[1]]},
        "radius": diameter / 2,
        "constraints": [
            {"kind": "center_offset", "target": "origin", "dx": center[0], "dy": center[1]},
            {"kind": "diameter", "value": diameter},
        ],
        "layer": layer,
        "role": role,
    }


def note_frame_steps(prefix: str, x: float, y: float, width: float, note: str) -> list[dict[str, Any]]:
    steps = rectangle_steps(prefix, x, y, width, 12.0, "NOTE_FRAME", "bounded note frame")
    steps.append({
        "id": prefix + "T",
        "type": "text",
        "purpose": "Place the review limitation inside its note frame.",
        "reasoning": "Middle-center alignment and the frame dimensions keep the complete text inside the declared card.",
        "insert": {"point": [x + width / 2, y + 6.0]},
        "value": note,
        "height": 2.5,
        "rotation_deg": 0,
        "constraints": [
            {"kind": "position_offset", "target": "origin", "dx": x + width / 2, "dy": y + 6.0},
            {"kind": "text_height", "value": 2.5},
            {"kind": "rotation", "value": 0},
        ],
        "layer": "NOTES",
        "role": "interface",
    })
    return steps


def drawing_plan(name: str, drawing_id: str, preflight: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "drawing": {
            "name": name,
            "id": drawing_id,
            "units": "mm",
            "origin": [0, 0],
            "tolerance": 0.001,
            "domain": "mechanical",
            "locks": ["review_only_prototype", "critical_dimensions_require_inspection"],
            "review_policy": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "domainGated": True},
        },
        "engineering_normative_preflight": copy.deepcopy(preflight),
        "steps": steps,
    }


def simple_tube_drawing(
    name: str,
    drawing_id: str,
    length: float,
    outer: float,
    inner: float,
    preflight: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    steps = rectangle_steps("O", 0, 0, length, outer, "OUTLINE", "axial outer profile")
    wall = (outer - inner) / 2
    steps.extend([
        free_line("H1", (0, wall), (length, wall), "HIDDEN", "Show the lower internal cavity boundary.", "hidden cavity line"),
        free_line("H2", (0, outer - wall), (length, outer - wall), "HIDDEN", "Show the upper internal cavity boundary.", "hidden cavity line"),
        free_line("C1", (0, outer / 2), (length, outer / 2), "CENTER", "Show the common part axis.", "centerline"),
        circle_step("E1", (length + outer, outer / 2), outer, "OUTLINE", "Show the outside diameter in the end view.", "shaft"),
        circle_step("E2", (length + outer, outer / 2), inner, "HOLE", "Show the cavity diameter in the end view.", "hole"),
        dimension_step("D1", "O1.start", "O1.end", (0, -8), length, 0, "Control the axial part length.", "horizontal", "overall"),
        dimension_step("D2", "O1.end", "O2.end", (length + 8, 0), outer, 90, "Control the outside diameter envelope.", "vertical", first_xy=(length, 0)),
    ])
    steps.extend(note_frame_steps("N", 0, outer + 14, max(length, 120), note))
    return drawing_plan(name, drawing_id, preflight, steps)


def rectangular_tube_drawing(
    name: str,
    drawing_id: str,
    length: float,
    outer_width: float,
    outer_height: float,
    inner_width: float,
    inner_height: float,
    preflight: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    steps = rectangle_steps("O", 0, 0, length, outer_height, "OUTLINE", "carrier axial outer profile")
    wall_height = (outer_height - inner_height) / 2
    wall_width = (outer_width - inner_width) / 2
    end_x = length + 10
    steps.extend([
        free_line("H1", (0, wall_height), (length, wall_height), "HIDDEN", "Show the lower rectangular tunnel boundary.", "hidden cavity line"),
        free_line("H2", (0, outer_height - wall_height), (length, outer_height - wall_height), "HIDDEN", "Show the upper rectangular tunnel boundary.", "hidden cavity line"),
        free_line("C1", (0, outer_height / 2), (length, outer_height / 2), "CENTER", "Show the carrier center plane.", "centerline"),
    ])
    steps.extend(rectangle_steps("EO", end_x, 0, outer_width, outer_height, "OUTLINE", "carrier outer end view"))
    steps.extend(rectangle_steps("EI", end_x + wall_width, wall_height, inner_width, inner_height, "HIDDEN", "carrier inner end view"))
    steps.extend([
        dimension_step("D1", "O1.start", "O1.end", (0, -8), length, 0, "Control the carrier axial length.", "horizontal", "overall"),
        dimension_step("D2", "O1.end", "O2.end", (length + 8, 0), outer_height, 90, "Control the carrier outside height.", "vertical", first_xy=(length, 0)),
        dimension_step("D3", "EO1.start", "EO1.end", (end_x, -8), outer_width, 0, "Control the carrier outside width.", "horizontal", first_xy=(end_x, 0)),
        dimension_step("D4", "EI1.start", "EI1.end", (end_x + wall_width, -14), inner_width, 0, "Control the carrier tunnel width.", "horizontal", first_xy=(end_x + wall_width, wall_height)),
    ])
    steps.extend(note_frame_steps("N", 0, outer_height + 20, max(length + outer_width + 10, 140), note))
    return drawing_plan(name, drawing_id, preflight, steps)


def stepped_axial_drawing(
    name: str,
    drawing_id: str,
    first_length: float,
    first_diameter: float,
    second_length: float,
    second_diameter: float,
    preflight: dict[str, Any],
    note: str,
    bore_diameter: float | None = None,
) -> dict[str, Any]:
    total = first_length + second_length
    offset = (first_diameter - second_diameter) / 2
    points = [
        (0, 0), (first_length, 0), (first_length, offset), (total, offset),
        (total, offset + second_diameter), (first_length, offset + second_diameter),
        (first_length, first_diameter), (0, first_diameter), (0, 0),
    ]
    steps: list[dict[str, Any]] = []
    for index in range(len(points) - 1):
        step_id = f"P{index + 1}"
        start = {"ref": "origin"} if index == 0 else {"ref": f"P{index}.end"}
        end = points[index + 1]
        dx = end[0] - points[index][0]
        dy = end[1] - points[index][1]
        constraints: list[dict[str, Any]] = [{"kind": "length", "value": math.hypot(dx, dy)}]
        if index > 0:
            constraints.append({"kind": "start_coincident", "target": f"P{index}.end"})
        if abs(dy) < 1e-9:
            constraints.append({"kind": "horizontal"})
        if abs(dx) < 1e-9:
            constraints.append({"kind": "vertical"})
        if index == len(points) - 2:
            constraints.append({"kind": "end_coincident", "target": "origin"})
        steps.append(line_step(step_id, start, end, None, "Define the stepped axial visible profile.", "Each segment continues the exact local part section without a gap.", "OUTLINE", constraints))
    steps.append(free_line("C1", (0, first_diameter / 2), (total, first_diameter / 2), "CENTER", "Show the common part axis.", "centerline"))
    if bore_diameter is not None:
        lower = (first_diameter - bore_diameter) / 2
        upper = lower + bore_diameter
        steps.extend([
            free_line("H1", (0, lower), (total, lower), "HIDDEN", "Show the lower spine-bore boundary.", "hidden bore line"),
            free_line("H2", (0, upper), (total, upper), "HIDDEN", "Show the upper spine-bore boundary.", "hidden bore line"),
        ])
    steps.extend([
        dimension_step("D1", "P1.start", "P4.end", (0, -8), total, 0, "Control the total part length.", "horizontal", "overall"),
        dimension_step("D2", "P1.start", "P1.end", (0, -14), first_length, 0, "Control the first axial segment.", "horizontal"),
        dimension_step("D3", "P1.start", "P8.start", (total + 8, 0), first_diameter, 90, "Control the maximum diameter.", "vertical"),
    ])
    steps.extend(note_frame_steps("N", 0, first_diameter + 14, max(total, 120), note))
    return drawing_plan(name, drawing_id, preflight, steps)


def build_2d_plans(params: dict[str, Any], preflight: dict[str, Any]) -> dict[str, dict[str, Any]]:
    shell = params["handle_shell"]
    carrier = params["internal_carrier"]
    cap = params["rear_end_cap"]
    connector = params["rod_connector"]
    envelope = params["envelope"]
    plans: dict[str, dict[str, Any]] = {
        "handle_shell.drawing.plan.json": simple_tube_drawing(
            "MW-M-001 handle shell review drawing", "MW_DWG_M001_A", shell["length"], shell["outer_diameter"], shell["inner_diameter"], preflight,
            "SIDE APERTURE IS DATUM ONLY; ADD NATIVE SIDE-PLANE CUT BEFORE FABRICATION",
        ),
        "internal_carrier.drawing.plan.json": rectangular_tube_drawing(
            "MW-M-002 carrier review drawing", "MW_DWG_M002_A", carrier["length"], carrier["outer_width"], carrier["outer_height"],
            carrier["inner_width"], carrier["inner_height"], preflight,
            "RECTANGULAR CAGE WIDTHS ARE CONTROLLED BY THE PARAMETER SOURCE",
        ),
        "rear_end_cap.drawing.plan.json": stepped_axial_drawing(
            "MW-M-003 rear end cap review drawing", "MW_DWG_M003_A", cap["exposed_length"], cap["flange_diameter"], cap["plug_insertion_length"], cap["plug_diameter"], preflight,
            "KEEP REAR CAP NONCONDUCTIVE; ANTENNA INTEGRATION REVIEW REQUIRED",
        ),
        "rod_connector.drawing.plan.json": stepped_axial_drawing(
            "MW-M-004 rod connector review drawing", "MW_DWG_M004_A", connector["exposed_length"], connector["collar_diameter"], connector["plug_insertion_length"], connector["plug_diameter"], preflight,
            "ADHESIVE BORE IS PROTOTYPE ONLY; COUPON VALIDATION REQUIRED", connector["spine_bore_diameter"],
        ),
    }
    total = envelope["overall_length"]
    grip = envelope["grip_segment_length"]
    transition = envelope["transition_exposed_length"]
    rod_end = total
    handle_height = shell["outer_diameter"]
    rod_low = (handle_height - params["gfrp_spine"]["nominal_diameter"]) / 2
    rod_high = rod_low + params["gfrp_spine"]["nominal_diameter"]
    steps = rectangle_steps("G", 0, 0, grip, handle_height, "OUTLINE", "grip envelope")
    steps.extend([
        free_line("T1", (grip, 0), (grip + transition, 0), "SHAFT", "Show the transition lower edge.", "connector edge"),
        free_line("T2", (grip + transition, 0), (grip + transition, handle_height), "SHAFT", "Show the transition far edge.", "connector edge"),
        free_line("T3", (grip + transition, handle_height), (grip, handle_height), "SHAFT", "Show the transition upper edge.", "connector edge"),
    ])
    steps.extend([
        free_line("R1", (grip + transition, rod_low), (rod_end, rod_low), "SHAFT", "Show the lower exposed GFRP rod edge.", "rod edge"),
        free_line("R2", (rod_end, rod_low), (rod_end, rod_high), "SHAFT", "Close the rod tip envelope.", "rod tip"),
        free_line("R3", (rod_end, rod_high), (grip + transition, rod_high), "SHAFT", "Show the upper exposed GFRP rod edge.", "rod edge"),
        free_line("C1", (0, handle_height / 2), (rod_end, handle_height / 2), "CENTER", "Show the full wand reference axis.", "assembly centerline"),
        free_line("K1", (params["antenna_keepout"]["axial_start_z"], 2), (params["antenna_keepout"]["axial_end_z"], 2), "KEEP_OUT", "Mark the axial RF keepout start and end.", "keepout boundary"),
        dimension_step("D1", "G1.start", "R2.end", (0, -12), total, 0, "Control the total assembled length.", "horizontal", "overall"),
        dimension_step("D2", "G1.start", "G1.end", (0, -19), grip, 0, "Control the grip segment length.", "horizontal"),
        dimension_step("D3", "T1.start", "T1.end", (grip, -26), transition, 0, "Control the exposed transition length.", "horizontal", first_xy=(grip, 0)),
        dimension_step("D4", "R1.start", "R1.end", (grip + transition, -33), envelope["rod_exposed_length"], 0, "Control the exposed rod length.", "horizontal", first_xy=(grip + transition, rod_low)),
    ])
    steps.extend(note_frame_steps("N", 0, handle_height + 16, total, "REVIEW PROTOTYPE - PRESS TO ARM AT Z72 - RF KEEP OUT Z5 TO Z30"))
    plans["wand_general_arrangement.drawing.plan.json"] = drawing_plan(
        "Magic wand mechanical general arrangement review drawing", "MW_DWG_GA001_A", preflight, steps
    )
    return plans


def build_assembly_layout(params: dict[str, Any]) -> dict[str, Any]:
    cap = params["rear_end_cap"]
    shell = params["handle_shell"]
    connector = params["rod_connector"]
    spine = params["gfrp_spine"]
    keepout = params["antenna_keepout"]
    return {
        "schema": "aicad_magic_wand_mechanical_assembly_layout_v1",
        "revision": params["revision"],
        "units": params["units"],
        "datum": "A rear cap outer plane at global Z=0; B common wand axis",
        "placements": [
            {"part_number": cap["part_number"], "role": "rear cap", "global_z_min": 0.0, "global_z_max": cap["exposed_length"] + cap["plug_insertion_length"], "intended_overlap": "plug overlaps shell from Z5 to Z9"},
            {"part_number": shell["part_number"], "role": "handle shell", "global_z_min": cap["exposed_length"], "global_z_max": params["envelope"]["grip_segment_length"], "intended_overlap": "end cap and connector plugs occupy portions of shell bore"},
            {"part_number": params["internal_carrier"]["part_number"], "role": "electronics carrier", "global_z_min": 8.0, "global_z_max": 100.0, "intended_overlap": "inside nonconductive shell bore"},
            {"part_number": connector["part_number"], "role": "rod connector", "global_z_min": 100.0, "global_z_max": 125.0, "intended_overlap": "plug overlaps shell from Z100 to Z115"},
            {"part_number": spine["part_number"], "role": "GFRP spine", "global_z_min": 95.0, "global_z_max": params["envelope"]["overall_length"], "intended_overlap": "30 mm insertion from Z95 to Z125"}
        ],
        "functional_datums": {
            "press_to_arm_center_z": params["press_to_arm"]["center_z_from_rear_outer_datum"],
            "antenna_keepout": {"global_z_min": keepout["axial_start_z"], "global_z_max": keepout["axial_end_z"], "radial_radius": keepout["radial_radius"]},
            "provisional_module_body_z": [10.0, 25.0],
            "provisional_battery_z": [40.0, 80.0]
        },
        "derived_checks": {
            "overall_stack_mm": cap["exposed_length"] + shell["length"] + connector["exposed_length"] + spine["exposed_length"],
            "carrier_corner_diagonal_mm": round(math.hypot(params["internal_carrier"]["outer_width"], params["internal_carrier"]["outer_height"]), 6),
            "carrier_minimum_radial_corner_clearance_mm": round((shell["inner_diameter"] - math.hypot(params["internal_carrier"]["outer_width"], params["internal_carrier"]["outer_height"])) / 2, 6),
            "battery_axial_clearance_from_keepout_mm": 40.0 - keepout["axial_end_z"],
            "spine_axial_clearance_from_keepout_mm": 95.0 - keepout["axial_end_z"]
        },
        "assembly_authority": False,
        "reason": "AICAD 3D schema 1.0 has no native assembly mates or interference solver; placements are review datums only."
    }


def build_bom(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "aicad_magic_wand_mechanical_bom_v1",
        "project_id": params["project_id"],
        "revision": params["revision"],
        "status": "prototype_quote_only_not_release",
        "source": "design-parameters.json",
        "rows": [
            {"item": 1, "part_number": params["handle_shell"]["part_number"], "description": "Grip shell, axial tube prototype", "quantity": 1, "make_buy": "make", "material": params["handle_shell"]["prototype_material"], "process": params["handle_shell"]["prototype_process"]},
            {"item": 2, "part_number": params["internal_carrier"]["part_number"], "description": "Internal electronics carrier cage", "quantity": 1, "make_buy": "make", "material": params["internal_carrier"]["prototype_material"], "process": params["internal_carrier"]["prototype_process"]},
            {"item": 3, "part_number": params["rear_end_cap"]["part_number"], "description": "Rear nonconductive antenna-end cap", "quantity": 1, "make_buy": "make", "material": params["rear_end_cap"]["prototype_material"], "process": params["rear_end_cap"]["prototype_process"]},
            {"item": 4, "part_number": params["rod_connector"]["part_number"], "description": "Handle-to-spine connector", "quantity": 1, "make_buy": "make", "material": params["rod_connector"]["prototype_material"], "process": params["rod_connector"]["prototype_process"]},
            {"item": 5, "part_number": params["gfrp_spine"]["part_number"], "description": "Pultruded GFRP spine blank", "quantity": 1, "make_buy": "buy", "material": params["gfrp_spine"]["material"], "process": "supplier cut and deburr after incoming inspection"},
            {"item": 6, "part_number": "MW-C-001", "description": "Two-part structural adhesive trial kit", "quantity": 1, "make_buy": "buy", "material": "selection gated by coupon results", "process": "controlled mix, surface preparation and cure trial"}
        ],
        "excluded_from_this_bom": ["PCB assembly", "battery", "button", "haptic motor", "wiring"],
        "release_locks": copy.deepcopy(params["safety_locks"])
    }


def build_review_svg(params: dict[str, Any]) -> str:
    keepout = params["antenna_keepout"]
    shell = params["handle_shell"]
    scale = 3.0
    x0 = 80.0
    axis_y = 210.0
    rear = x0
    grip_end = x0 + params["envelope"]["grip_segment_length"] * scale
    connector_end = grip_end + params["envelope"]["transition_exposed_length"] * scale
    tip = x0 + params["envelope"]["overall_length"] * scale
    handle_h = shell["outer_diameter"] * scale
    rod_h = params["gfrp_spine"]["nominal_diameter"] * scale
    keepout_x = x0 + keepout["axial_start_z"] * scale
    keepout_w = (keepout["axial_end_z"] - keepout["axial_start_z"]) * scale
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520" role="img" aria-labelledby="title desc">
  <title id="title">Magic wand mechanical prototype isometric review</title>
  <desc id="desc">Review-only axial assembly visualization generated from design-parameters.json; it is not native BREP assembly evidence.</desc>
  <rect width="1200" height="520" fill="#f5f7fa"/>
  <style>
    .outline{{stroke:#10243e;stroke-width:3;fill:none}} .detail{{stroke:#245d8a;stroke-width:1.5;fill:none}}
    .hidden{{stroke:#66788a;stroke-width:1.2;stroke-dasharray:8 6;fill:none}} .center{{stroke:#b34d2e;stroke-width:1;stroke-dasharray:16 4 3 4}}
    .dim{{stroke:#505b66;stroke-width:1;fill:none}} .card{{fill:#fff;stroke:#24374a;stroke-width:1.5}}
    .label{{font:14px 'Segoe UI',sans-serif;fill:#172b3d}} .small{{font:12px 'Segoe UI',sans-serif;fill:#344a5e}}
    .head{{font:bold 22px 'Segoe UI',sans-serif;fill:#10243e}} .warn{{font:bold 13px 'Segoe UI',sans-serif;fill:#8a351f}}
  </style>
  <text class="head" x="42" y="42">MW-PROTOTYPE-001 / Mechanical review view / Rev A</text>
  <rect class="card" x="42" y="58" width="1116" height="48" rx="4"/>
  <text class="warn" x="58" y="79">REVIEW ONLY - no native assembly mates, material readback, structural approval or manufacturing authorization</text>
  <text class="small" x="58" y="97">Axial parts are dimension-driven; press-to-arm side aperture remains a declared side-plane modeling blocker.</text>
  <line class="center" x1="{rear - 20}" y1="{axis_y}" x2="{tip + 20}" y2="{axis_y}"/>
  <path d="M {rear} {axis_y-handle_h/2} L {grip_end} {axis_y-handle_h/2-12} L {grip_end} {axis_y+handle_h/2-12} L {rear} {axis_y+handle_h/2} Z" fill="#dce8f2" stroke="#10243e" stroke-width="3"/>
  <ellipse cx="{rear}" cy="{axis_y}" rx="10" ry="{handle_h/2}" fill="#f0f5f9" stroke="#10243e" stroke-width="3"/>
  <path d="M {grip_end} {axis_y-handle_h/2-12} L {connector_end} {axis_y-handle_h/2-15} L {connector_end} {axis_y+handle_h/2-15} L {grip_end} {axis_y+handle_h/2-12} Z" fill="#c4d7e8" stroke="#10243e" stroke-width="3"/>
  <path d="M {connector_end} {axis_y-rod_h/2-15} L {tip} {axis_y-rod_h/2-33} L {tip} {axis_y+rod_h/2-33} L {connector_end} {axis_y+rod_h/2-15} Z" fill="#dfebe0" stroke="#10243e" stroke-width="2.2"/>
  <rect x="{keepout_x}" y="{axis_y-handle_h/2-4}" width="{keepout_w}" height="{handle_h}" fill="#f2c36b" fill-opacity="0.4" stroke="#a86500" stroke-width="1.5" stroke-dasharray="7 5"/>
  <rect x="{x0+8*scale}" y="{axis_y-17}" width="{92*scale}" height="34" fill="none" stroke="#245d8a" stroke-width="1.5" stroke-dasharray="8 6"/>
  <circle cx="{x0+72*scale}" cy="{axis_y-handle_h/2-8}" r="8" fill="#d9513c" stroke="#7d2317" stroke-width="2"/>
  <line class="detail" x1="{x0+72*scale}" y1="{axis_y-handle_h/2-16}" x2="{x0+72*scale}" y2="132"/>
  <rect class="card" x="238" y="112" width="220" height="44" rx="4"/><text class="label" x="250" y="131">Press-to-arm datum Z=72</text><text class="small" x="250" y="148">side aperture not in axial BREP</text>
  <rect class="card" x="42" y="302" width="248" height="64" rx="4"/><text class="label" x="54" y="323">RF keepout Z=5..30</text><text class="small" x="54" y="342">nonconductive rear end</text><text class="small" x="54" y="359">battery starts at Z=40</text>
  <rect class="card" x="330" y="302" width="248" height="64" rx="4"/><text class="label" x="342" y="323">Grip segment 115 mm</text><text class="small" x="342" y="342">5 cap + 110 shell</text><text class="small" x="342" y="359">target OD 27 mm</text>
  <rect class="card" x="618" y="302" width="248" height="64" rx="4"/><text class="label" x="630" y="323">Transition 10 mm</text><text class="small" x="630" y="342">25 mm connector total</text><text class="small" x="630" y="359">15 mm shell insertion</text>
  <rect class="card" x="906" y="302" width="248" height="64" rx="4"/><text class="label" x="918" y="323">Exposed GFRP 190 mm</text><text class="small" x="918" y="342">diameter 7 mm</text><text class="small" x="918" y="359">30 mm insertion</text>
  <line class="dim" x1="{rear}" y1="404" x2="{tip}" y2="404"/><line class="dim" x1="{rear}" y1="396" x2="{rear}" y2="412"/><line class="dim" x1="{tip}" y1="396" x2="{tip}" y2="412"/>
  <rect class="card" x="455" y="386" width="270" height="36" rx="4"/><text class="label" x="504" y="409">OVERALL = 315 +/- 2 mm</text>
  <rect class="card" x="42" y="446" width="1116" height="44" rx="4"/>
  <text class="small" x="58" y="466">Solid = visible outline | thin blue = internal carrier | dashed amber = antenna exclusion | chain centerline = MODEL +Z axis</text>
  <text class="small" x="58" y="483">Source: design-parameters.json SHA-256 {sha256_file(PARAMETERS_PATH)[:16]}... | visualization has no topology authority</text>
</svg>'''


def write_text(path: Path, text: str, check: bool) -> None:
    normalized = text if text.endswith("\n") else text + "\n"
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != normalized:
            raise RuntimeError(f"generated file is stale or missing: {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8")


def write_json(path: Path, value: object, check: bool) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", check)


def generate(check: bool = False) -> list[Path]:
    params = load_json(PARAMETERS_PATH)
    preflight = build_preflight()
    outputs: dict[Path, object | str] = {
        ROOT / "preflight" / "engineering-preflight.json": preflight,
        ROOT / "assembly-layout.json": build_assembly_layout(params),
        ROOT / "bom.json": build_bom(params),
        ROOT / "review" / "wand-mechanical-isometric.svg": build_review_svg(params),
    }
    for filename, plan in build_3d_plans(params, preflight).items():
        outputs[ROOT / "plans3d" / filename] = plan
    for filename, plan in build_2d_plans(params, preflight).items():
        outputs[ROOT / "drawings2d" / filename] = plan
    for path, value in outputs.items():
        if isinstance(value, str):
            write_text(path, value, check)
        else:
            write_json(path, value, check)

    generated_paths = sorted(outputs)
    manifest = {
        "schema": "aicad_magic_wand_generated_source_manifest_v1",
        "revision": params["revision"],
        "parameterSource": {
            "path": "design-parameters.json",
            "size": PARAMETERS_PATH.stat().st_size,
            "sha256": sha256_file(PARAMETERS_PATH),
        },
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in generated_paths
        ],
        "locks": copy.deepcopy(params["safety_locks"]),
    }
    manifest_path = ROOT / "generated-source-manifest.json"
    write_json(manifest_path, manifest, check)
    return generated_paths + [manifest_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the review-only magic wand mechanical package from one parameter source")
    parser.add_argument("--check", action="store_true", help="fail if committed generated files differ from deterministic output")
    args = parser.parse_args()
    files = generate(check=args.check)
    print(json.dumps({
        "ok": True,
        "mode": "check" if args.check else "generate",
        "files": [path.relative_to(ROOT).as_posix() for path in files],
        "reviewOnly": True,
        "manufacturingAuthorized": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
