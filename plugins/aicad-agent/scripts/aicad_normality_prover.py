from __future__ import annotations

import argparse
import ast
import json
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CANDIDATES = [
    PLUGIN_ROOT / "runtime" / "src",
    PLUGIN_ROOT.parents[1] / "src",
]
for runtime_src in RUNTIME_CANDIDATES:
    if (runtime_src / "aicad" / "engine.py").is_file():
        sys.path.insert(0, str(runtime_src))
        break

from aicad.engine import CompiledPlan, ResolvedLine, load_and_compile  # noqa: E402


Point = tuple[float, float]
TOL = 1e-6
ALLOWED_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
ALLOWED_UNARY = {ast.UAdd: lambda value: value, ast.USub: lambda value: -value}
ROOT_CAUSES = {
    "contract": (
        "结构族合同不完整或含有不可计算字段，验证器无法建立封闭的数学问题。",
        "模板必须通过 schema、变量依赖和端点覆盖门禁；缺项时禁止生成。",
    ),
    "locks": (
        "审阅安全锁被打开或候选数据与合同的安全边界不一致。",
        "所有证明与输出都必须保持 reviewOnly=true、accepted=false、ruleEnabled=false、packagingGated=true。",
    ),
    "plan_geometry": (
        "逐线计划、逻辑几何目录或结构族模板发生漂移，实体不再一一对应。",
        "每次生成后按 ID、端点、图层、用途和依赖逐项与固定结构族合同复核。",
    ),
    "vertex_coverage": (
        "存在未归入命名顶点的线端点，或一个端点被重复归类，拓扑关系不完整。",
        "每个生产端点必须恰好属于一个命名顶点，命名顶点内的全部引用必须重合。",
    ),
    "constraint_rank": (
        "独立方程数量不足或相互重复，几何仍有未声明自由度；单看约束总条数产生了虚假安全感。",
        "按雅可比矩阵秩计算有效约束；参数族零空间必须等于声明的独立参数数，实例代入后零空间必须为零。",
    ),
    "topology": (
        "外轮廓出现断裂、重复、退化或自交，逐线局部检查没有覆盖全局拓扑。",
        "输出前重建有向外轮廓并验证单闭环、简单多边形、非零面积和端点连续性。",
    ),
    "feature": (
        "线段各自看似合理，但组合后的功能面凹陷、退化、互相穿插或工艺区越界。",
        "每条生产线必须归属命名功能特征；每个特征必须有完整面边界、凸性/简单性/面积/包含关系合同。",
    ),
    "functional": (
        "几何被完全约束，但约束的是错误产品；缺少闭合、插入、避让、对称或工艺公式。",
        "把结构规范写成独立的测量断言，且任何硬断言失败都不得由其他分数抵消。",
    ),
    "parameter_domain": (
        "默认值可用，但边界或组合参数产生退化、反向锥度、负间隙或面相交。",
        "结构族发布前必须运行默认、边界和确定性随机参数扫描；每次实例还要重新校验实际参数。",
    ),
}


@dataclass(frozen=True)
class ParameterState:
    values: dict[str, float]
    independent_ids: tuple[str, ...]
    derived_ids: tuple[str, ...]


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _expression_names(expression: str) -> set[str]:
    tree = ast.parse(expression, mode="eval")
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Expression, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp)):
            continue
        elif isinstance(node, tuple(ALLOWED_BINARY) + tuple(ALLOWED_UNARY)):
            continue
        else:
            raise ValueError(f"unsupported expression node {type(node).__name__} in {expression!r}")
    return names


def _evaluate_expression(expression: str, variables: dict[str, float]) -> float:
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return _number(node.value, f"constant in {expression!r}")
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"unknown variable {node.id!r} in {expression!r}")
            return _number(variables[node.id], node.id)
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY:
            return ALLOWED_BINARY[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY:
            return ALLOWED_UNARY[type(node.op)](visit(node.operand))
        raise ValueError(f"unsupported expression in {expression!r}")

    value = visit(tree)
    if not math.isfinite(value):
        raise ValueError(f"expression {expression!r} did not produce a finite value")
    return value


def _resolve_parameters(template: dict[str, Any], supplied: dict[str, Any]) -> ParameterState:
    values: dict[str, float] = {}
    independent: list[str] = []
    derived: list[str] = []
    definitions = template["parameters"]
    ids = [str(item["id"]) for item in definitions]
    if len(ids) != len(set(ids)):
        raise ValueError("parameter IDs must be unique")
    independent_set = {str(item["id"]) for item in definitions if item["role"] == "independent"}
    extra = set(supplied) - independent_set
    missing = independent_set - set(supplied)
    if extra or missing:
        raise ValueError(f"independent parameter mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    for item in definitions:
        parameter_id = str(item["id"])
        if item["role"] == "independent":
            value = _number(supplied[parameter_id], parameter_id)
            minimum = _number(item["min"], f"{parameter_id}.min")
            maximum = _number(item["max"], f"{parameter_id}.max")
            if value < minimum or value > maximum:
                raise ValueError(f"{parameter_id}={value:g} is outside [{minimum:g}, {maximum:g}]")
            values[parameter_id] = value
            independent.append(parameter_id)
        elif item["role"] == "derived":
            expression = str(item["formula"])
            unavailable = _expression_names(expression) - set(values)
            if unavailable:
                raise ValueError(
                    f"derived parameter {parameter_id} has forward/cyclic dependencies {sorted(unavailable)}"
                )
            values[parameter_id] = _evaluate_expression(expression, values)
            derived.append(parameter_id)
        else:
            raise ValueError(f"unsupported role for {parameter_id}")
    return ParameterState(values, tuple(independent), tuple(derived))


def _point(value: Any, label: str) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must be [x, y]")
    return _number(value[0], f"{label}[0]"), _number(value[1], f"{label}[1]")


def _same(left: Point, right: Point, tolerance: float) -> bool:
    return math.dist(left, right) <= tolerance


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(point: Point, a: Point, b: Point, tolerance: float) -> bool:
    return (
        abs(_cross(a, b, point)) <= tolerance
        and min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point, tolerance: float) -> bool:
    values = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    if values[0] * values[1] < -(tolerance**2) and values[2] * values[3] < -(tolerance**2):
        return True
    return (
        (abs(values[0]) <= tolerance and _on_segment(c, a, b, tolerance))
        or (abs(values[1]) <= tolerance and _on_segment(d, a, b, tolerance))
        or (abs(values[2]) <= tolerance and _on_segment(a, c, d, tolerance))
        or (abs(values[3]) <= tolerance and _on_segment(b, c, d, tolerance))
    )


def _proper_intersection(a: Point, b: Point, c: Point, d: Point, tolerance: float) -> bool:
    return (
        _cross(a, b, c) * _cross(a, b, d) < -(tolerance**2)
        and _cross(c, d, a) * _cross(c, d, b) < -(tolerance**2)
    )


def _polygon_area(points: list[Point]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _polygon_simple(points: list[Point], tolerance: float) -> bool:
    if len(points) < 3:
        return False
    edges = [(points[index], points[(index + 1) % len(points)]) for index in range(len(points))]
    if any(math.dist(a, b) <= tolerance for a, b in edges):
        return False
    for left_index, (a, b) in enumerate(edges):
        for right_index, (c, d) in enumerate(edges):
            if right_index <= left_index:
                continue
            if right_index in {left_index, (left_index + 1) % len(edges)}:
                continue
            if left_index == 0 and right_index == len(edges) - 1:
                continue
            if _segments_intersect(a, b, c, d, tolerance):
                return False
    return True


def _polygon_convex(points: list[Point], tolerance: float) -> bool:
    signs = []
    for index in range(len(points)):
        value = _cross(points[index], points[(index + 1) % len(points)], points[(index + 2) % len(points)])
        if abs(value) > tolerance:
            signs.append(1 if value > 0 else -1)
    return bool(signs) and len(set(signs)) == 1


def _point_in_polygon_strict(point: Point, polygon: list[Point], tolerance: float) -> bool:
    for index, start in enumerate(polygon):
        if _on_segment(point, start, polygon[(index + 1) % len(polygon)], tolerance):
            return False
    inside = False
    x, y = point
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
            if crossing_x > x:
                inside = not inside
    return inside


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    squared = dx * dx + dy * dy
    if squared == 0:
        return math.dist(point, start)
    ratio = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / squared))
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point, projection)


def _polygon_clearance(inner: list[Point], outer: list[Point]) -> float:
    return min(
        _point_segment_distance(point, outer[index], outer[(index + 1) % len(outer)])
        for point in inner
        for index in range(len(outer))
    )


def _polygons_overlap(left: list[Point], right: list[Point], tolerance: float) -> bool:
    for left_index, a in enumerate(left):
        b = left[(left_index + 1) % len(left)]
        for right_index, c in enumerate(right):
            d = right[(right_index + 1) % len(right)]
            if _proper_intersection(a, b, c, d, tolerance):
                return True
    if any(_point_in_polygon_strict(point, right, tolerance) for point in left):
        return True
    if any(_point_in_polygon_strict(point, left, tolerance) for point in right):
        return True
    left_center = (sum(point[0] for point in left) / len(left), sum(point[1] for point in left) / len(left))
    right_center = (sum(point[0] for point in right) / len(right), sum(point[1] for point in right) / len(right))
    return _point_in_polygon_strict(left_center, right, tolerance) or _point_in_polygon_strict(
        right_center, left, tolerance
    )


def _matrix_rank(matrix: list[list[float]], tolerance: float = 1e-7) -> int:
    if not matrix:
        return 0
    work = [row[:] for row in matrix]
    rows, columns = len(work), len(work[0])
    scale = max((abs(value) for row in work for value in row), default=1.0)
    cutoff = tolerance * max(1.0, scale)
    rank = 0
    for column in range(columns):
        pivot = max(range(rank, rows), key=lambda row: abs(work[row][column]), default=rank)
        if pivot >= rows or abs(work[pivot][column]) <= cutoff:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        divisor = work[rank][column]
        work[rank] = [value / divisor for value in work[rank]]
        for row in range(rows):
            if row == rank:
                continue
            factor = work[row][column]
            if abs(factor) <= cutoff:
                continue
            work[row] = [work[row][item] - factor * work[rank][item] for item in range(columns)]
        rank += 1
        if rank == rows:
            break
    return rank


def _jacobian_rank(function: Callable[[dict[str, float]], list[float]], state: dict[str, float]) -> tuple[int, int, int]:
    names = list(state)
    baseline = function(state)
    matrix = [[0.0 for _ in names] for _ in baseline]
    for column, name in enumerate(names):
        step = 1e-5 * max(1.0, abs(state[name]))
        plus = dict(state)
        minus = dict(state)
        plus[name] += step
        minus[name] -= step
        plus_values = function(plus)
        minus_values = function(minus)
        for row in range(len(baseline)):
            matrix[row][column] = (plus_values[row] - minus_values[row]) / (2 * step)
    return _matrix_rank(matrix), len(baseline), len(names)


def _line_map(plan: CompiledPlan) -> dict[str, ResolvedLine]:
    result: dict[str, ResolvedLine] = {}
    for entity in plan.entities:
        if not isinstance(entity, ResolvedLine):
            raise ValueError("normality prover currently requires a line-only 2D production profile")
        result[entity.id] = entity
    return result


def _geometry_map(geometry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entities = geometry.get("entities")
    if not isinstance(entities, list) or not entities:
        raise ValueError("geometry.entities must be a non-empty array")
    result = {str(item.get("id")): item for item in entities if isinstance(item, dict)}
    if len(result) != len(entities):
        raise ValueError("geometry entity IDs must be unique")
    return result


def _endpoint(entity: ResolvedLine | dict[str, Any], side: str) -> Point:
    if side not in {"start", "end"}:
        raise ValueError(f"unsupported endpoint side {side!r}")
    value = getattr(entity, side) if isinstance(entity, ResolvedLine) else entity[side]
    return _point(value, f"endpoint.{side}")


def _vertex_actuals(
    template: dict[str, Any],
    plan_by_id: dict[str, ResolvedLine],
    production_ids: set[str],
    tolerance: float,
) -> tuple[dict[str, Point], dict[str, str], dict[str, Any]]:
    vertices: dict[str, Point] = {}
    endpoint_owner: dict[str, str] = {}
    coincidence_errors: list[dict[str, Any]] = []
    for vertex in template["vertices"]:
        vertex_id = str(vertex["id"])
        if vertex_id in vertices:
            raise ValueError(f"duplicate vertex ID {vertex_id}")
        points: list[Point] = []
        for reference in vertex["refs"]:
            entity_id, separator, side = str(reference).rpartition(".")
            if not separator or entity_id not in production_ids or entity_id not in plan_by_id:
                raise ValueError(f"{vertex_id} has unknown production endpoint reference {reference!r}")
            if reference in endpoint_owner:
                raise ValueError(f"endpoint {reference} belongs to both {endpoint_owner[reference]} and {vertex_id}")
            endpoint_owner[reference] = vertex_id
            points.append(_endpoint(plan_by_id[entity_id], side))
        if not points:
            raise ValueError(f"{vertex_id} must reference at least one endpoint")
        anchor = points[0]
        error = max(math.dist(anchor, point) for point in points)
        if error > tolerance:
            coincidence_errors.append({"vertexId": vertex_id, "maxCoincidenceErrorMm": error})
        vertices[vertex_id] = anchor
    expected_refs = {f"{entity_id}.{side}" for entity_id in production_ids for side in ("start", "end")}
    missing = sorted(expected_refs - set(endpoint_owner))
    extra = sorted(set(endpoint_owner) - expected_refs)
    duplicate_positions = []
    rows = list(vertices.items())
    for index, (left_id, left) in enumerate(rows):
        for right_id, right in rows[index + 1 :]:
            if _same(left, right, tolerance):
                duplicate_positions.append([left_id, right_id])
    evidence = {
        "endpointReferenceCount": len(endpoint_owner),
        "expectedEndpointReferenceCount": len(expected_refs),
        "missingEndpointReferences": missing,
        "extraEndpointReferences": extra,
        "coincidenceErrors": coincidence_errors,
        "duplicateNamedVertexPositions": duplicate_positions,
    }
    return vertices, endpoint_owner, evidence


def _formula_vertices(template: dict[str, Any], parameters: dict[str, float]) -> dict[str, Point]:
    return {
        str(vertex["id"]): (
            _evaluate_expression(str(vertex["x"]), parameters),
            _evaluate_expression(str(vertex["y"]), parameters),
        )
        for vertex in template["vertices"]
    }


def _feature_results(template: dict[str, Any], vertices: dict[str, Point], tolerance: float) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    polygons: dict[str, list[Point]] = {}
    by_id = {str(feature["id"]): feature for feature in template["features"]}
    for feature in template["features"]:
        feature_id = str(feature["id"])
        polygon = [vertices[str(vertex_id)] for vertex_id in feature["polygonVertexIds"]]
        polygons[feature_id] = polygon
        signed_area = _polygon_area(polygon)
        simple = _polygon_simple(polygon, tolerance)
        convex = _polygon_convex(polygon, tolerance)
        rules = feature.get("rules", {})
        checks = {
            "nonzero_area": abs(signed_area) > tolerance,
            "minimum_area": abs(signed_area) + tolerance >= float(rules.get("minAreaMm2", 0.0)),
            "simple": not rules.get("simple", True) or simple,
            "convex": not rules.get("convex", False) or convex,
        }
        results.append(
            {
                "id": feature_id,
                "kind": feature["kind"],
                "countsAsFace": bool(feature.get("countsAsFace", feature["kind"] == "face")),
                "pass": all(checks.values()),
                "checks": checks,
                "signedAreaMm2": signed_area,
                "areaMm2": abs(signed_area),
                "vertexIds": feature["polygonVertexIds"],
                "entityIds": feature["entityIds"],
            }
        )
    result_by_id = {row["id"]: row for row in results}
    containment_rows: list[dict[str, Any]] = []
    for feature_id, feature in by_id.items():
        outer_id = feature.get("containedIn")
        if not outer_id:
            continue
        if outer_id not in polygons:
            raise ValueError(f"{feature_id}.containedIn references unknown feature {outer_id}")
        inner, outer = polygons[feature_id], polygons[outer_id]
        inside = all(_point_in_polygon_strict(point, outer, tolerance) for point in inner)
        clearance = _polygon_clearance(inner, outer)
        minimum = float(feature.get("minBoundaryClearanceMm", 0.0))
        passed = inside and clearance + tolerance >= minimum
        result_by_id[feature_id]["checks"]["contained_in_parent"] = inside
        result_by_id[feature_id]["checks"]["minimum_boundary_clearance"] = passed
        result_by_id[feature_id]["pass"] = result_by_id[feature_id]["pass"] and passed
        containment_rows.append(
            {"featureId": feature_id, "parentId": outer_id, "clearanceMm": clearance, "requiredMm": minimum, "pass": passed}
        )
    faces = [row for row in results if row["countsAsFace"]]
    overlap_rows: list[dict[str, Any]] = []
    for index, left in enumerate(faces):
        for right in faces[index + 1 :]:
            overlap = _polygons_overlap(polygons[left["id"]], polygons[right["id"]], tolerance)
            overlap_rows.append({"left": left["id"], "right": right["id"], "overlap": overlap, "pass": not overlap})
    global_pass = all(row["pass"] for row in results) and all(row["pass"] for row in overlap_rows)
    results.append(
        {
            "id": "STRUCTURAL_FACE_INTERIOR_OVERLAP",
            "kind": "global",
            "countsAsFace": False,
            "pass": all(row["pass"] for row in overlap_rows),
            "pairs": overlap_rows,
            "containment": containment_rows,
        }
    )
    return results, global_pass


def _measurement_values(
    template: dict[str, Any], vertices: dict[str, Point], feature_rows: list[dict[str, Any]]
) -> dict[str, float]:
    feature_areas = {row["id"]: float(row["areaMm2"]) for row in feature_rows if "areaMm2" in row}
    all_points = list(vertices.values())
    values: dict[str, float] = {
        "ACTUAL_BBOX_WIDTH": max(point[0] for point in all_points) - min(point[0] for point in all_points),
        "ACTUAL_BBOX_HEIGHT": max(point[1] for point in all_points) - min(point[1] for point in all_points),
    }
    for measurement in template.get("measurements", []):
        measurement_id = str(measurement["id"])
        kind = measurement["kind"]
        if kind == "feature_area":
            values[measurement_id] = feature_areas[str(measurement["featureId"])]
            continue
        left = vertices[str(measurement["a"])]
        right = vertices[str(measurement["b"])]
        if kind == "distance":
            value = math.dist(left, right)
        elif kind == "signed_dx":
            value = right[0] - left[0]
        elif kind == "signed_dy":
            value = right[1] - left[1]
        elif kind == "abs_dx":
            value = abs(right[0] - left[0])
        elif kind == "abs_dy":
            value = abs(right[1] - left[1])
        else:
            raise ValueError(f"unsupported measurement kind {kind!r}")
        values[measurement_id] = value
    return values


def _assertion_results(assertions: list[dict[str, Any]], environment: dict[str, float], tolerance: float) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    for assertion in assertions:
        left = _evaluate_expression(str(assertion["lhs"]), environment)
        right = _evaluate_expression(str(assertion["rhs"]), environment)
        operator = assertion["operator"]
        if operator == "==":
            passed = abs(left - right) <= tolerance
        elif operator == ">=":
            passed = left + tolerance >= right
        elif operator == "<=":
            passed = left - tolerance <= right
        elif operator == ">":
            passed = left > right + tolerance
        elif operator == "<":
            passed = left < right - tolerance
        else:
            raise ValueError(f"unsupported assertion operator {operator!r}")
        rows.append(
            {
                "id": assertion["id"],
                "pass": passed,
                "purpose": assertion["purpose"],
                "lhs": left,
                "operator": operator,
                "rhs": right,
                "residual": left - right,
            }
        )
    return rows, all(row["pass"] for row in rows)


def _outer_contour_result(
    template: dict[str, Any], vertices: dict[str, Point], endpoint_owner: dict[str, str], tolerance: float
) -> dict[str, Any]:
    points: list[Point] = []
    joins: list[dict[str, Any]] = []
    contour = template["outerContour"]
    directed: list[tuple[str, Point, Point]] = []
    missing_endpoint_references: list[str] = []
    for item in contour:
        if isinstance(item, str):
            entity_id, direction = item, "forward"
        else:
            entity_id, direction = str(item["entityId"]), item.get("direction", "forward")
        start_side, end_side = ("start", "end") if direction == "forward" else ("end", "start")
        start_ref, end_ref = f"{entity_id}.{start_side}", f"{entity_id}.{end_side}"
        missing_endpoint_references.extend(
            reference for reference in (start_ref, end_ref) if reference not in endpoint_owner
        )
        if missing_endpoint_references:
            continue
        directed.append((entity_id, vertices[endpoint_owner[start_ref]], vertices[endpoint_owner[end_ref]]))
    if missing_endpoint_references:
        return {
            "pass": False,
            "entityCount": len(contour),
            "joins": [],
            "simple": False,
            "areaMm2": 0.0,
            "missingEndpointReferences": sorted(set(missing_endpoint_references)),
        }
    for index, (entity_id, start, end) in enumerate(directed):
        next_id, next_start, _ = directed[(index + 1) % len(directed)]
        error = math.dist(end, next_start)
        joins.append({"from": entity_id, "to": next_id, "errorMm": error, "pass": error <= tolerance})
        points.append(start)
    area = abs(_polygon_area(points))
    return {
        "pass": all(row["pass"] for row in joins) and _polygon_simple(points, tolerance) and area > tolerance,
        "entityCount": len(directed),
        "joins": joins,
        "simple": _polygon_simple(points, tolerance),
        "areaMm2": area,
    }


def _rank_result(
    template: dict[str, Any], parameters: ParameterState, vertices: dict[str, Point]
) -> dict[str, Any]:
    state: dict[str, float] = {}
    for vertex_id, point in vertices.items():
        state[f"{vertex_id}_x"] = point[0]
        state[f"{vertex_id}_y"] = point[1]
    state.update(parameters.values)
    definitions = {str(item["id"]): item for item in template["parameters"]}

    def family_residuals(candidate: dict[str, float]) -> list[float]:
        residuals: list[float] = []
        for vertex in template["vertices"]:
            vertex_id = str(vertex["id"])
            residuals.append(candidate[f"{vertex_id}_x"] - _evaluate_expression(str(vertex["x"]), candidate))
            residuals.append(candidate[f"{vertex_id}_y"] - _evaluate_expression(str(vertex["y"]), candidate))
        for parameter_id in parameters.derived_ids:
            residuals.append(
                candidate[parameter_id]
                - _evaluate_expression(str(definitions[parameter_id]["formula"]), candidate)
            )
        return residuals

    def instance_residuals(candidate: dict[str, float]) -> list[float]:
        residuals = family_residuals(candidate)
        residuals.extend(candidate[parameter_id] - parameters.values[parameter_id] for parameter_id in parameters.independent_ids)
        return residuals

    family_rank, family_equations, variable_count = _jacobian_rank(family_residuals, state)
    instance_rank, instance_equations, _ = _jacobian_rank(instance_residuals, state)
    family_nullity = variable_count - family_rank
    instance_nullity = variable_count - instance_rank
    expected_family_nullity = len(parameters.independent_ids)
    passed = (
        family_rank == family_equations
        and family_nullity == expected_family_nullity
        and instance_rank == variable_count
        and instance_nullity == 0
    )
    return {
        "pass": passed,
        "coordinateDegreesOfFreedom": 2 * len(vertices),
        "parameterVariableCount": len(parameters.values),
        "independentDesignParameterCount": len(parameters.independent_ids),
        "derivedParameterCount": len(parameters.derived_ids),
        "totalVariableCount": variable_count,
        "familyEquationCount": family_equations,
        "familyIndependentRank": family_rank,
        "familyNullity": family_nullity,
        "expectedFamilyNullity": expected_family_nullity,
        "instanceEquationCount": instance_equations,
        "instanceIndependentRank": instance_rank,
        "instanceNullity": instance_nullity,
        "redundantFamilyEquationCount": family_equations - family_rank,
        "redundantInstanceEquationCount": instance_equations - instance_rank,
        "interpretation": "The family may move only through declared independent parameters; binding one job instance leaves zero geometric freedom.",
    }


def _bbox_result(template: dict[str, Any], vertices: dict[str, Point], parameters: dict[str, float], tolerance: float) -> dict[str, Any]:
    points = list(vertices.values())
    actual = [
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    ]
    expected = [
        _evaluate_expression(str(template["expectedBBox"][name]), parameters)
        for name in ("minX", "minY", "maxX", "maxY")
    ]
    errors = [abs(left - right) for left, right in zip(actual, expected)]
    return {"pass": max(errors) <= tolerance, "actualMm": actual, "expectedMm": expected, "errorsMm": errors}


def _domain_sweep(template: dict[str, Any], default_values: dict[str, Any], tolerance: float) -> dict[str, Any]:
    sampling = template.get("sampling", {})
    cases: list[tuple[str, dict[str, Any]]] = [("default", dict(default_values))]
    for item in sampling.get("explicitCases", []):
        values = dict(default_values)
        values.update(item["values"])
        cases.append((str(item["id"]), values))
    random_seed = int(sampling.get("randomSeed", 0))
    generator = random.Random(random_seed)
    definitions = [item for item in template["parameters"] if item["role"] == "independent"]
    requested_random = int(sampling.get("randomCases", 0))
    accepted_random = 0
    attempts = 0
    while accepted_random < requested_random and attempts < max(100, requested_random * 100):
        attempts += 1
        values = {
            str(item["id"]): generator.uniform(float(item["min"]), float(item["max"]))
            for item in definitions
        }
        try:
            candidate_parameters = _resolve_parameters(template, values)
            _, domain_ok = _assertion_results(
                template.get("domainAssertions", []), candidate_parameters.values, tolerance
            )
        except Exception:
            domain_ok = False
        if not domain_ok:
            continue
        accepted_random += 1
        cases.append((f"random_{accepted_random:04d}", values))

    failures: list[dict[str, Any]] = []
    for case_id, values in cases:
        try:
            parameters = _resolve_parameters(template, values)
            domain_rows, domain_pass = _assertion_results(
                template.get("domainAssertions", []), parameters.values, tolerance
            )
            vertices = _formula_vertices(template, parameters.values)
            feature_rows, feature_pass = _feature_results(template, vertices, tolerance)
            measurements = _measurement_values(template, vertices, feature_rows)
            assertion_rows, assertion_pass = _assertion_results(
                template.get("assertions", []), {**parameters.values, **measurements}, tolerance
            )
            bbox = _bbox_result(template, vertices, parameters.values, tolerance)
            case_pass = domain_pass and feature_pass and assertion_pass and bbox["pass"]
            if not case_pass:
                failures.append(
                    {
                        "id": case_id,
                        "parameterValues": values,
                        "failedDomainAssertions": [row["id"] for row in domain_rows if not row["pass"]],
                        "failedFeatures": [row["id"] for row in feature_rows if not row["pass"]],
                        "failedAssertions": [row["id"] for row in assertion_rows if not row["pass"]],
                        "bbox": bbox,
                    }
                )
        except Exception as exc:  # fail closed and retain the first actionable reason
            failures.append({"id": case_id, "parameterValues": values, "error": str(exc)})
        if len(failures) >= 20:
            break
    return {
        "pass": not failures,
        "caseCount": len(cases),
        "explicitCaseCount": 1 + len(sampling.get("explicitCases", [])),
        "randomCaseCount": accepted_random,
        "randomSamplingAttempts": attempts,
        "randomAcceptanceRate": accepted_random / attempts if attempts else 1.0,
        "randomSeed": random_seed,
        "failures": failures,
        "scope": "Template-domain geometry and functional assertions; each emitted CAD instance must still pass the full plan comparison.",
    }


def _failure(gate: str, evidence: Any) -> dict[str, Any]:
    cause, prevention = ROOT_CAUSES[gate]
    return {
        "gate": gate,
        "rootCause": cause,
        "preventionRule": prevention,
        "persistentRuleId": "PKG-G023",
        "evidence": evidence,
    }


def evaluate(
    plan: CompiledPlan,
    geometry: dict[str, Any],
    template: dict[str, Any],
    instance: dict[str, Any],
) -> dict[str, Any]:
    tolerance = float(template.get("toleranceMm", TOL))
    failures: list[dict[str, Any]] = []
    if template.get("schema") != "aicad_normality_template_v1" or instance.get("schema") != "aicad_normality_instance_v1":
        raise ValueError("unsupported normality template or instance schema")
    if instance.get("profileId") != template.get("profileId") or instance.get("profileVersion") != template.get("profileVersion"):
        raise ValueError("normality instance does not bind the exact template profile/version")

    closure_system = template.get("closureSystem", {})
    closure_pass = (
        isinstance(closure_system.get("top"), str)
        and isinstance(closure_system.get("bottom"), str)
        and bool(closure_system.get("asymmetric"))
        == (closure_system.get("top") != closure_system.get("bottom"))
        and bool(closure_system.get("standard"))
    )

    parameters = _resolve_parameters(template, instance["values"])
    domain_assertion_rows, actual_domain_pass = _assertion_results(
        template.get("domainAssertions", []), parameters.values, tolerance
    )
    expected_locks = {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True}
    geometry_locks = geometry.get("design", geometry).get("locks", geometry.get("design", geometry))
    locks_pass = all(template.get("locks", {}).get(key) == value for key, value in expected_locks.items())
    locks_pass = locks_pass and all(instance.get("locks", {}).get(key) == value for key, value in expected_locks.items())
    locks_pass = locks_pass and all(geometry_locks.get(key) == value for key, value in expected_locks.items())
    if not locks_pass:
        failures.append(_failure("locks", {"template": template.get("locks"), "instance": instance.get("locks"), "geometry": geometry_locks}))

    plan_by_id = _line_map(plan)
    geometry_by_id = _geometry_map(geometry)
    excluded = set(map(str, template.get("excludedEntityIds", [])))
    production_plan_ids = set(plan_by_id) - excluded
    geometry_ids = set(geometry_by_id)
    expected_ids = set(map(str, template["productionEntityIds"]))
    mapping_errors: list[dict[str, Any]] = []
    if production_plan_ids != geometry_ids or geometry_ids != expected_ids:
        mapping_errors.append(
            {
                "planOnly": sorted(production_plan_ids - geometry_ids),
                "geometryOnly": sorted(geometry_ids - production_plan_ids),
                "templateOnly": sorted(expected_ids - geometry_ids),
                "unexpectedGeometry": sorted(geometry_ids - expected_ids),
            }
        )
    layer_counts = Counter(str(item.get("layer")) for item in geometry_by_id.values())
    expected_layer_counts = {str(key): int(value) for key, value in template["expectedLayerCounts"].items()}
    constraint_coverage: list[dict[str, Any]] = []
    for entity_id in sorted(production_plan_ids & geometry_ids & expected_ids):
        line = plan_by_id[entity_id]
        item = geometry_by_id[entity_id]
        start_error = math.dist(_point(item["start"], f"{entity_id}.start"), line.start)
        end_error = math.dist(_point(item["end"], f"{entity_id}.end"), line.end)
        metadata_ok = bool(line.purpose and line.reasoning and item.get("purpose") and item.get("reasoning") and item.get("dependencies"))
        anchor_relation = any(row.get("kind") in {"start_coincident", "start_offset"} for row in line.constraints)
        shape_relation = any(row.get("kind") in {"horizontal", "vertical", "length", "parallel", "perpendicular"} for row in line.constraints)
        row_pass = start_error <= tolerance and end_error <= tolerance and metadata_ok and anchor_relation and shape_relation
        constraint_coverage.append(
            {
                "entityId": entity_id,
                "pass": row_pass,
                "startErrorMm": start_error,
                "endErrorMm": end_error,
                "metadataComplete": metadata_ok,
                "anchorRelation": anchor_relation,
                "shapeOrDimensionRelation": shape_relation,
            }
        )
    plan_geometry_pass = (
        not mapping_errors
        and dict(layer_counts) == expected_layer_counts
        and all(row["pass"] for row in constraint_coverage)
        and bool(plan.entities)
        and plan.entities[0].id in excluded
        and _same(plan.entities[0].anchor, (0.0, 0.0), tolerance)
    )
    if not plan_geometry_pass:
        failures.append(
            _failure(
                "plan_geometry",
                {
                    "mappingErrors": mapping_errors,
                    "actualLayerCounts": dict(layer_counts),
                    "expectedLayerCounts": expected_layer_counts,
                    "failedEntities": [row for row in constraint_coverage if not row["pass"]],
                },
            )
        )

    vertices, endpoint_owner, vertex_evidence = _vertex_actuals(
        template, plan_by_id, expected_ids, tolerance
    )
    vertex_coverage_pass = not any(
        vertex_evidence[key]
        for key in (
            "missingEndpointReferences",
            "extraEndpointReferences",
            "coincidenceErrors",
            "duplicateNamedVertexPositions",
        )
    )
    formula_vertices = _formula_vertices(template, parameters.values)
    formula_errors = {
        vertex_id: math.dist(vertices[vertex_id], formula_vertices[vertex_id])
        for vertex_id in vertices
        if math.dist(vertices[vertex_id], formula_vertices[vertex_id]) > tolerance
    }
    vertex_coverage_pass = vertex_coverage_pass and not formula_errors
    vertex_evidence["formulaMismatchMm"] = formula_errors
    if not vertex_coverage_pass:
        failures.append(_failure("vertex_coverage", vertex_evidence))

    rank = _rank_result(template, parameters, vertices)
    if not rank["pass"]:
        failures.append(_failure("constraint_rank", rank))

    outer = _outer_contour_result(template, vertices, endpoint_owner, tolerance)
    if not outer["pass"]:
        failures.append(_failure("topology", outer))

    feature_rows, feature_pass = _feature_results(template, vertices, tolerance)
    feature_entity_ids = Counter(
        str(entity_id) for feature in template["features"] for entity_id in feature["entityIds"]
    )
    unassigned_entities = sorted(expected_ids - set(feature_entity_ids))
    unknown_feature_entities = sorted(set(feature_entity_ids) - expected_ids)
    feature_pass = feature_pass and not unassigned_entities and not unknown_feature_entities
    feature_evidence = {
        "faceCount": sum(1 for row in feature_rows if row.get("countsAsFace")),
        "featureCount": len(template["features"]),
        "unassignedProductionEntities": unassigned_entities,
        "unknownFeatureEntities": unknown_feature_entities,
        "results": feature_rows,
    }
    if not feature_pass:
        failures.append(_failure("feature", feature_evidence))

    measurements = _measurement_values(template, vertices, feature_rows)
    assertion_rows, assertions_pass = _assertion_results(
        template.get("assertions", []), {**parameters.values, **measurements}, tolerance
    )
    bbox = _bbox_result(template, vertices, parameters.values, tolerance)
    assertions_pass = assertions_pass and bbox["pass"]
    assertions_pass = assertions_pass and closure_pass
    if not assertions_pass:
        failures.append(
            _failure(
                "functional",
                {"failedAssertions": [row for row in assertion_rows if not row["pass"]], "bbox": bbox, "closureSystem": closure_system, "closureContractPass": closure_pass},
            )
        )

    domain = _domain_sweep(template, instance["values"], tolerance)
    domain["actualInstanceAssertions"] = domain_assertion_rows
    domain["actualInstancePass"] = actual_domain_pass
    domain["pass"] = domain["pass"] and actual_domain_pass
    if not domain["pass"]:
        failures.append(_failure("parameter_domain", domain))

    atomic_assertions = (
        rank["instanceEquationCount"]
        + len(constraint_coverage) * 5
        + len(outer["joins"])
        + sum(len(row.get("checks", {})) for row in feature_rows)
        + len(assertion_rows)
        + 4
    )
    return {
        "schema": "aicad_normality_proof_v1",
        "status": "pass" if not failures else "failed",
        "profile": {"id": template["profileId"], "version": template["profileVersion"]},
        "drawing": plan.name,
        "sourcePlanSha256": plan.source_hash,
        "ruleIds": ["PKG-G018", "PKG-G022", "PKG-G023"],
        "checks": {
            "locksClosed": locks_pass,
            "planGeometryBijection": plan_geometry_pass,
            "everyEndpointExactlyOneNamedVertex": vertex_coverage_pass,
            "constraintRankComplete": rank["pass"],
            "outerContourSingleSimpleClosedRing": outer["pass"],
            "allFeatureContractsPass": feature_pass,
            "allFunctionalAssertionsAndBBoxPass": assertions_pass,
            "parameterDomainSweepPass": domain["pass"],
        },
        "counts": {
            "productionEntities": len(expected_ids),
            "namedVertices": len(vertices),
            "structuralFaces": feature_evidence["faceCount"],
            "featureContracts": feature_evidence["featureCount"],
            "lineConstraintRows": sum(len(plan_by_id[entity_id].constraints) for entity_id in expected_ids),
            "namedFunctionalAssertions": len(assertion_rows),
            "effectiveInstanceEqualityRank": rank["instanceIndependentRank"],
            "estimatedAtomicHardChecks": atomic_assertions,
        },
        "mathematicalProof": rank,
        "planGeometry": {
            "actualLayerCounts": dict(layer_counts),
            "expectedLayerCounts": expected_layer_counts,
            "entityChecks": constraint_coverage,
        },
        "vertices": vertex_evidence,
        "outerContour": outer,
        "features": feature_evidence,
        "measurements": measurements,
        "functionalAssertions": assertion_rows,
        "closureSystem": {**closure_system, "pass": closure_pass},
        "boundingBox": bbox,
        "parameterDomainSweep": domain,
        "failures": failures,
        "closedLoop": "detect -> locate failed gate -> explain root cause -> add persistent rule -> add red fixture -> repair -> full regression",
        "guaranteeBoundary": {
            "boundedGuarantee": "A pass proves this drawing is normal only inside the named structure template, declared parameter domain and implemented hard gates.",
            "notClaimed": [
                "material strength certification",
                "machine/tooling tolerance certification",
                "mass-production acceptance",
                "unmodeled product families",
            ],
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
        },
    }


def _write_markdown(report: dict[str, Any], target: Path) -> None:
    proof = report["mathematicalProof"]
    lines = [
        "# AICAD CAD 正常性证明报告",
        "",
        f"- 总状态：**{report['status'].upper()}**",
        f"- 结构族：`{report['profile']['id']}` / `{report['profile']['version']}`",
        f"- 生产实体：{report['counts']['productionEntities']} 条；命名顶点：{report['counts']['namedVertices']} 个；结构面：{report['counts']['structuralFaces']} 个。",
        f"- 坐标自由度：{proof['coordinateDegreesOfFreedom']}；独立设计参数：{proof['independentDesignParameterCount']}；派生参数：{proof['derivedParameterCount']}。",
        f"- 参数族独立约束秩：{proof['familyIndependentRank']}/{proof['familyEquationCount']}，剩余自由度：{proof['familyNullity']}（必须恰好等于独立设计参数数）。",
        f"- 本次尺寸代入后独立约束秩：{proof['instanceIndependentRank']}/{proof['totalVariableCount']}，剩余自由度：{proof['instanceNullity']}（必须为 0）。",
        f"- 命名功能断言：{report['counts']['namedFunctionalAssertions']} 条；估算原子硬检查：{report['counts']['estimatedAtomicHardChecks']} 项。",
        "",
        "## 八层硬门禁",
        "",
    ]
    labels = {
        "locksClosed": "审阅安全锁",
        "planGeometryBijection": "计划/逻辑几何一一对应",
        "everyEndpointExactlyOneNamedVertex": "端点与命名顶点完备覆盖",
        "constraintRankComplete": "独立约束秩完备",
        "outerContourSingleSimpleClosedRing": "外轮廓单闭环且不自交",
        "allFeatureContractsPass": "全部功能面合同",
        "allFunctionalAssertionsAndBBoxPass": "结构功能公式与外包尺寸",
        "parameterDomainSweepPass": "参数边界与随机扫描",
    }
    for key, passed in report["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {labels[key]}")
    lines.extend(["", "## 错误根因与下次预防规则", ""])
    if not report["failures"]:
        lines.append("本次没有失败项；历史反例仍保留在回归测试中，后续修改不得删除门禁。")
    for failure in report["failures"]:
        lines.extend(
            [
                f"### {failure['gate']}",
                "",
                f"- 为什么出现：{failure['rootCause']}",
                f"- 下次新增/保持的规则：{failure['preventionRule']}",
                f"- 永久规则编号：`{failure['persistentRuleId']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## 结论边界",
            "",
            "通过代表：在已命名结构族、声明参数域和现有硬门禁范围内，候选几何被数学关系唯一确定且所有已建模功能检查通过。",
            "",
            "不代表：材料强度、刀模/设备公差、量产可制造性或未建模结构族已获认证。当前仍为审阅候选，安全锁保持关闭。",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prove bounded CAD normality using a versioned structure-family contract, independent rank and hard feature gates"
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-md", required=True, type=Path)
    args = parser.parse_args()
    try:
        plan = load_and_compile(args.plan)
        geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
        template = json.loads(args.template.read_text(encoding="utf-8"))
        instance = json.loads(args.instance.read_text(encoding="utf-8"))
        report = evaluate(plan, geometry, template, instance)
    except Exception as exc:
        report = {
            "schema": "aicad_normality_proof_v1",
            "status": "failed",
            "checks": {"contractReadableAndComputable": False},
            "failures": [_failure("contract", {"error": str(exc)})],
            "guaranteeBoundary": {
                "boundedGuarantee": "No guarantee is emitted because the contract could not be evaluated.",
                "reviewOnly": True,
                "accepted": False,
                "ruleEnabled": False,
                "packagingGated": True,
            },
        }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if "mathematicalProof" in report:
        _write_markdown(report, args.out_md)
    else:
        args.out_md.write_text(
            "# AICAD CAD 正常性证明报告\n\n- 总状态：**FAILED**\n- 合同无法计算；未输出任何正常性保证。\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "failedGates": [item["gate"] for item in report.get("failures", [])],
                "outJson": str(args.out_json.resolve()),
                "outMarkdown": str(args.out_md.resolve()),
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
