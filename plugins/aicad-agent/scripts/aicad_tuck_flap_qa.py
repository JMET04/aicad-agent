from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CANDIDATES = [
    PLUGIN_ROOT / "runtime" / "src",
    PLUGIN_ROOT.parents[1] / "src",
]
for runtime_src in RUNTIME_CANDIDATES:
    if (runtime_src / "aicad" / "engine.py").is_file():
        sys.path.insert(0, str(runtime_src))
        break

from aicad.engine import CompiledPlan, ResolvedLine, compile_plan, load_and_compile  # noqa: E402


TOL = 1e-6


def _point(value: tuple[float, float]) -> tuple[float, float]:
    return float(value[0]), float(value[1])


def _same(left: tuple[float, float], right: tuple[float, float], tolerance: float) -> bool:
    return math.dist(left, right) <= tolerance


def _line(plan: CompiledPlan, entity_id: str) -> ResolvedLine:
    matches = [entity for entity in plan.entities if entity.id == entity_id]
    if len(matches) != 1 or not isinstance(matches[0], ResolvedLine):
        raise ValueError(f"{entity_id} must resolve to exactly one line")
    return matches[0]


def _ordered_x(line: ResolvedLine) -> tuple[tuple[float, float], tuple[float, float]]:
    points = sorted((_point(line.start), _point(line.end)), key=lambda item: (item[0], item[1]))
    return points[0], points[1]


def _connects(
    line: ResolvedLine,
    first: tuple[float, float],
    second: tuple[float, float],
    tolerance: float,
) -> bool:
    start, end = _point(line.start), _point(line.end)
    return (_same(start, first, tolerance) and _same(end, second, tolerance)) or (
        _same(start, second, tolerance) and _same(end, first, tolerance)
    )


def _convex(points: list[tuple[float, float]], tolerance: float) -> tuple[bool, list[float]]:
    crosses: list[float] = []
    for index in range(len(points)):
        a = points[index]
        b = points[(index + 1) % len(points)]
        c = points[(index + 2) % len(points)]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > tolerance:
            crosses.append(cross)
    return bool(crosses) and (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)), crosses


def _close_value(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= tolerance


def _flap_metrics(
    plan: CompiledPlan,
    flap: dict[str, Any],
    parameters: dict[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    root_fold = _line(plan, flap["rootFoldId"])
    tongue_fold = _line(plan, flap["tongueFoldId"])
    free_edge = _line(plan, flap["tongueFreeEdgeId"])
    main_left = _line(plan, flap["mainLeftEdgeId"])
    main_right = _line(plan, flap["mainRightEdgeId"])
    tongue_left = _line(plan, flap["tongueLeftBevelId"])
    tongue_right = _line(plan, flap["tongueRightBevelId"])

    root_left, root_right = _ordered_x(root_fold)
    tongue_root_left, tongue_root_right = _ordered_x(tongue_fold)
    free_left, free_right = _ordered_x(free_edge)
    sign = float(flap["outwardSign"])

    main_depth = sign * (tongue_root_left[1] - root_left[1])
    tongue_depth = sign * (free_left[1] - tongue_root_left[1])
    root_width = root_right[0] - root_left[0]
    tongue_root_width = tongue_root_right[0] - tongue_root_left[0]
    free_width = free_right[0] - free_left[0]
    main_left_taper = tongue_root_left[0] - root_left[0]
    main_right_taper = root_right[0] - tongue_root_right[0]
    tongue_left_taper = free_left[0] - tongue_root_left[0]
    tongue_right_taper = tongue_root_right[0] - free_right[0]

    polygon = [
        root_left,
        root_right,
        tongue_root_right,
        free_right,
        free_left,
        tongue_root_left,
    ]
    convex, cross_products = _convex(polygon, tolerance)
    expected_main_taper = float(parameters["mainFlapTaperEachSideMm"])
    expected_tongue_taper = float(parameters["tongueTaperEachSideMm"])

    checks = {
        "root_fold_horizontal": _close_value(root_left[1], root_right[1], tolerance),
        "tongue_fold_horizontal": _close_value(tongue_root_left[1], tongue_root_right[1], tolerance),
        "tongue_free_edge_horizontal": _close_value(free_left[1], free_right[1], tolerance),
        "main_left_edge_connects_face": _connects(main_left, root_left, tongue_root_left, tolerance),
        "main_right_edge_connects_face": _connects(main_right, root_right, tongue_root_right, tolerance),
        "tongue_left_bevel_connects_face": _connects(tongue_left, tongue_root_left, free_left, tolerance),
        "tongue_right_bevel_connects_face": _connects(tongue_right, tongue_root_right, free_right, tolerance),
        "usable_root_width_matches_contract": _close_value(
            root_width, float(parameters["usableRootWidthMm"]), tolerance
        ),
        "tongue_root_width_matches_contract": _close_value(
            tongue_root_width, float(parameters["tongueRootWidthMm"]), tolerance
        ),
        "tongue_free_width_matches_contract": _close_value(
            free_width, float(parameters["tongueFreeWidthMm"]), tolerance
        ),
        "main_flap_depth_matches_contract": _close_value(
            main_depth, float(parameters["mainFlapDepthMm"]), tolerance
        ),
        "tongue_depth_matches_contract": _close_value(
            tongue_depth, float(parameters["tongueDepthMm"]), tolerance
        ),
        "main_left_taper_is_explicit": _close_value(main_left_taper, expected_main_taper, tolerance),
        "main_right_taper_is_explicit": _close_value(main_right_taper, expected_main_taper, tolerance),
        "tongue_left_taper_is_explicit": _close_value(tongue_left_taper, expected_tongue_taper, tolerance),
        "tongue_right_taper_is_explicit": _close_value(tongue_right_taper, expected_tongue_taper, tolerance),
        "tongue_narrows_toward_free_edge": free_width < tongue_root_width - tolerance,
        "combined_main_flap_and_tongue_is_convex": convex,
    }
    return {
        "id": flap["id"],
        "position": flap["position"],
        "pass": all(checks.values()),
        "checks": checks,
        "metricsMm": {
            "rootWidth": root_width,
            "tongueRootWidth": tongue_root_width,
            "tongueFreeWidth": free_width,
            "mainDepth": main_depth,
            "tongueDepth": tongue_depth,
            "mainLeftTaper": main_left_taper,
            "mainRightTaper": main_right_taper,
            "tongueLeftTaper": tongue_left_taper,
            "tongueRightTaper": tongue_right_taper,
        },
        "boundaryPointsMm": polygon,
        "convexityCrossProducts": cross_products,
        "entityIds": {
            "rootFold": flap["rootFoldId"],
            "mainLeft": flap["mainLeftEdgeId"],
            "mainRight": flap["mainRightEdgeId"],
            "tongueFold": flap["tongueFoldId"],
            "tongueLeft": flap["tongueLeftBevelId"],
            "tongueRight": flap["tongueRightBevelId"],
            "tongueFree": flap["tongueFreeEdgeId"],
        },
    }


def evaluate(
    plan: CompiledPlan,
    contract: dict[str, Any],
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tolerance = float(contract.get("toleranceMm", TOL))
    parameters = contract["parameters"]
    bootstrap = contract["originBootstrap"]
    bootstrap_matches = [
        entity
        for entity in plan.entities
        if entity.id == bootstrap["id"] and isinstance(entity, ResolvedLine)
    ]
    catalog_ids = {
        str(item.get("sourcePlanEntityId"))
        for item in (catalog or {}).get("objects", [])
        if isinstance(item, dict)
    }
    bootstrap_ok = (
        len(bootstrap_matches) == 1
        and bool(plan.entities)
        and plan.entities[0].id == bootstrap["id"]
        and _same(_point(bootstrap_matches[0].start), (0.0, 0.0), tolerance)
        and bootstrap.get("production") is False
        and (catalog is None or bootstrap["id"] not in catalog_ids)
    )
    locks = contract["locks"]
    locks_ok = (
        locks.get("reviewOnly") is True
        and locks.get("accepted") is False
        and locks.get("ruleEnabled") is False
        and locks.get("packagingGated") is True
    )
    if catalog is not None:
        catalog_locks = catalog.get("locks", {})
        locks_ok = locks_ok and all(catalog_locks.get(key) == value for key, value in locks.items())

    flap_results = [
        _flap_metrics(plan, flap, parameters, tolerance)
        for flap in contract["flaps"]
    ]
    metric_names = (
        "rootWidth",
        "tongueRootWidth",
        "tongueFreeWidth",
        "mainDepth",
        "tongueDepth",
        "mainLeftTaper",
        "mainRightTaper",
        "tongueLeftTaper",
        "tongueRightTaper",
    )
    paired_match = len(flap_results) == 2 and all(
        _close_value(
            float(flap_results[0]["metricsMm"][name]),
            float(flap_results[1]["metricsMm"][name]),
            tolerance,
        )
        for name in metric_names
    )
    checks = {
        "origin_bootstrap_is_nonproduction_and_catalog_excluded": bootstrap_ok,
        "review_locks_closed": locks_ok,
        "every_named_main_flap_face_passes": all(row["pass"] for row in flap_results),
        "top_and_bottom_flap_metrics_match": paired_match,
        "every_combined_main_flap_and_tongue_is_convex": all(
            row["checks"]["combined_main_flap_and_tongue_is_convex"] for row in flap_results
        ),
        "no_unparameterized_main_flap_waist": all(
            row["checks"]["main_left_taper_is_explicit"]
            and row["checks"]["main_right_taper_is_explicit"]
            for row in flap_results
        ),
        "tongue_tapers_inward_toward_free_edge": all(
            row["checks"]["tongue_narrows_toward_free_edge"]
            and row["checks"]["tongue_left_taper_is_explicit"]
            and row["checks"]["tongue_right_taper_is_explicit"]
            for row in flap_results
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    for row in flap_results:
        failures.extend(
            f"{row['id']}:{name}"
            for name, passed in row["checks"].items()
            if not passed
        )
    return {
        "schema": "aicad_tuck_flap_face_validation_v1",
        "status": "pass" if not failures else "failed",
        "ruleIds": ["PKG-G018", "PKG-G022"],
        "drawing": plan.name,
        "sourcePlanSha256": plan.source_hash,
        "checks": checks,
        "flaps": flap_results,
        "failureReasons": failures,
        "locks": locks,
        "boundary": {
            "reviewOnly": True,
            "productionAccepted": False,
            "manufacturingValidationClaimed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate complete straight-tuck main-flap faces instead of isolated line plausibility"
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    plan = load_and_compile(args.plan)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8")) if args.catalog else None
    report = evaluate(plan, contract, catalog)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "failed": report["failureReasons"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
