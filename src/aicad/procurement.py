"""Read-only whole-deliverable cost and functional-evidence preflight.

This checks recorded evidence, not supplier truth, human identity, or hardware.
It has no ordering/payment/browser API and never grants purchase authorization.
"""
from __future__ import annotations

import hashlib
import json
import stat
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "aicad_procurement_preflight_v1"
FUNCTION_LEVELS = {"host_logic", "analog_simulation", "fit_analysis", "hardware_measurement"}
FULL_CATEGORIES = {"pcb", "components", "accessories", "mechanical", "assembly", "shipping", "tax", "tools"}
ACTIONS = {"submit_order", "buy_components", "pay", "consume_coupon"}


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _positive_integer(value: Any, label: str, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"{label}: expected {'nonnegative' if zero else 'positive'} integer")
    return value


def _money(value: Any, label: str) -> Decimal:
    if not isinstance(value, str) or not value.strip() or len(value) > 40:
        raise ValueError(f"{label}: explicit decimal string required; unknown is not zero")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label}: invalid decimal") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1e12") or result.as_tuple().exponent < -12:
        raise ValueError(f"{label}: invalid, negative or unreasonable amount")
    return result


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string with timezone")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timestamp timezone is required")
    return stamp.astimezone(timezone.utc)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty text required")
    return value


def _artifact(root: Path, entry: Any, *, json_object: bool = True) -> Any:
    if not isinstance(entry, dict):
        raise ValueError("size/hash-bound evidence entry required")
    relative = entry.get("path")
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise ValueError("evidence path must be portable and relative")
    parts = PurePosixPath(relative)
    if not relative or parts.is_absolute() or any(part in {".", ".."} for part in relative.split("/")):
        raise ValueError("unsafe evidence path")
    target = root
    for part in parts.parts:
        target = target / part
        metadata = target.lstat()
        if target.is_symlink() or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("linked evidence is forbidden")
    target.resolve(strict=True).relative_to(root)
    if not target.is_file():
        raise ValueError("evidence must be a regular file")
    raw = target.read_bytes()
    _positive_integer(entry.get("size"), "evidence size", zero=True)
    if len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        raise ValueError("stale evidence size or SHA-256")
    if not json_object:
        return raw
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("evidence JSON root must be an object")
    return document


def _unique_rows(value: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("explicit inventory list required")
    rows: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("inventory row must be an object")
        identifier = _text(row.get(key), key)
        if identifier in rows:
            raise ValueError(f"duplicate {key}: {identifier}")
        rows[identifier] = row
    return rows


def _check_measurement(actual: Any, check: dict[str, Any]) -> bool:
    expected = check.get("expected")
    operator = check.get("operator")
    if operator == "eq":
        return type(actual) is type(expected) and actual == expected
    if operator not in {"lte", "gte"}:
        raise ValueError("unsupported measurement operator")
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        observed, limit = Decimal(str(actual)), Decimal(str(expected))
        if not observed.is_finite() or not limit.is_finite():
            return False
        return observed <= limit if operator == "lte" else observed >= limit
    except InvalidOperation:
        return False


def validate_procurement_preflight(
    contract: Any, evidence_root: str | Path | None, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Recompute costs and bind pre-order tests/approval to one exact design.

    A passing report is a *record-consistency* candidate for a human's final
    order-time review. No boolean here authenticates approval or supplier data.
    """
    blockers: list[dict[str, str]] = []
    report: dict[str, Any] = {
        "schema": "aicad_procurement_preflight_report_v1", "ok": False,
        "orderPreflightPassed": False, "budgetCoverageReady": False,
        "functionalPreOrderEvidenceReady": False, "quotedTotalCny": None,
        "knownSubtotalCny": None, "blockers": blockers, "physicalValidationPending": [],
        "purchaseAuthorized": False, "paymentAuthorized": False, "couponConsumptionAuthorized": False,
        "realHardwareFunctionProven": False, "productionReady": False,
        "externalEvidenceAuthenticityRequired": True, "orderTimeSupplierRecheckRequired": True,
        "reviewOnly": True,
    }

    def fail(code: str, detail: str) -> None:
        blockers.append({"code": code, "detail": detail})

    try:
        if not isinstance(contract, dict) or contract.get("schema") != SCHEMA:
            raise ValueError(f"expected {SCHEMA}")
        root = Path(evidence_root).expanduser().resolve(strict=True) if evidence_root else None
        if root is None or not root.is_dir():
            raise ValueError("explicit controlled evidence root required")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("evaluation time requires timezone")
        project_id = _text(contract.get("projectId"), "projectId")
        action = contract.get("action")
        if action not in ACTIONS:
            raise ValueError("unsupported irreversible action")
        if contract.get("projectState") != "active":
            fail("PROJECT_STOPPED", "Paused, terminated or undeclared project cannot order, pay or use a coupon.")
        report.update(projectId=project_id, action=action, evaluatedAt=current.isoformat())
    except (ValueError, OSError, TypeError) as exc:
        fail("CONTRACT_INVALID", str(exc))
        return report

    design = contract.get("design")
    design_bytes: dict[str, bytes] = {}
    try:
        sources = _unique_rows(design, "id")
        if not sources:
            raise ValueError("at least one frozen native design/firmware source required")
        for identifier, entry in sources.items():
            design_bytes[identifier] = _artifact(root, entry, json_object=False)
        design_sha = canonical_sha256(design)
        report["designSha256"] = design_sha
    except (ValueError, OSError, TypeError) as exc:
        fail("DESIGN_EVIDENCE", str(exc))
        design_sha = None

    try:
        inventory = _artifact(root, contract.get("inventory"))
        if inventory.get("schema") != "aicad_procurement_inventory_v1" or inventory.get("projectId") != project_id:
            raise ValueError("inventory identity/schema mismatch")
        inventory_sha = contract["inventory"]["sha256"]
        report["inventorySha256"] = inventory_sha
    except (ValueError, OSError, TypeError, KeyError) as exc:
        fail("INVENTORY_EVIDENCE", str(exc))
        return report

    try:
        _positive_integer(inventory.get("quantity"), "system quantity")
        items = _unique_rows(inventory.get("items"), "id")
        if not items:
            raise ValueError("empty cost inventory")
        categories: set[str] = set()
        for item in items.values():
            categories.add(_text(item.get("category"), "category"))
            _positive_integer(item.get("need"), "required quantity")
            if not isinstance(item.get("mpn"), str) or (item["category"] == "components" and not item["mpn"].strip()):
                raise ValueError("component inventory requires frozen selected MPN")
        deliverable = inventory.get("deliverable")
        if deliverable == "complete_system":
            if not FULL_CATEGORIES.issubset(categories):
                raise ValueError("whole-deliverable cost categories missing: " + ", ".join(sorted(FULL_CATEGORIES - categories)))
        elif deliverable == "bare_pcb":
            if categories != {"pcb", "shipping", "tax"}:
                raise ValueError("explicit bare-board scope must contain PCB, shipping and tax only")
        else:
            raise ValueError("deliverable must be complete_system or explicitly approved bare_pcb")
        scenarios = _unique_rows(inventory.get("scenarios"), "id")
        if deliverable == "complete_system" and not scenarios:
            raise ValueError("complete system requires measurable pre-order function scenarios")
        for scenario in scenarios.values():
            if scenario.get("level") not in FUNCTION_LEVELS:
                raise ValueError("DRC, file parsing and compilation are not functional test methods")
            _text(scenario.get("criterion"), "scenario criterion")
            checks = _unique_rows(scenario.get("checks"), "id")
            if not checks or any(row.get("operator") not in {"eq", "lte", "gte"} or "expected" not in row for row in checks.values()):
                raise ValueError("scenario requires typed measurable acceptance checks")
            if type(scenario.get("physicalValidationRequired")) is not bool:
                raise ValueError("declare remaining physical-validation obligation")
        report["deliverable"] = deliverable
        report["physicalValidationPending"] = sorted(s["id"] for s in scenarios.values() if s["physicalValidationRequired"])
    except (ValueError, TypeError, KeyError) as exc:
        fail("INVENTORY_SCOPE", str(exc))
        return report

    # Inspect the frozen configuration, not a test author's copied assertion.
    # Native DRC and isolated host tests cannot turn CONFIG_BT=n into working BLE.
    for scenario in scenarios.values():
        try:
            source_checks = scenario.get("sourceChecks", [])
            if not isinstance(source_checks, list):
                raise ValueError("sourceChecks must be a list")
            for check in source_checks:
                if not isinstance(check, dict) or check.get("format") != "kconfig":
                    raise ValueError("source check requires explicit kconfig format")
                key = _text(check.get("setting"), "configuration setting")
                expected = _text(check.get("expected"), "expected configuration value")
                if not key.startswith("CONFIG_") or any(not (c.isupper() or c.isdigit() or c == "_") for c in key):
                    raise ValueError("invalid Kconfig setting")
                source = design_bytes[check["designId"]].decode("utf-8")
                values = []
                for line in source.splitlines():
                    stripped = line.strip()
                    if stripped.startswith(key + "="):
                        values.append(stripped.split("=", 1)[1].strip())
                    elif stripped == "# " + key + " is not set":
                        values.append("n")
                if values != [expected]:
                    raise ValueError(f"{key}: frozen configuration does not unambiguously equal {expected}")
        except (ValueError, KeyError, UnicodeError, TypeError) as exc:
            fail("FUNCTION_CONFIGURATION", scenario["id"] + ": " + str(exc))

    try:
        quotes = _unique_rows(contract.get("quotes"), "itemId")
        if set(quotes) != set(items):
            fail("COST_COVERAGE", "Quotes must exactly cover the frozen inventory; missing, extra or optional substitutes cannot count as a complete price.")
    except (ValueError, TypeError) as exc:
        fail("COST_COVERAGE", str(exc))
        quotes = {}
    subtotal = Decimal(0)
    quote_error = False
    for identifier, quote in quotes.items():
        try:
            if identifier not in items:
                raise ValueError("quote item outside frozen inventory")
            snapshot = _artifact(root, quote.get("evidence"))
            if snapshot != {key: value for key, value in quote.items() if key != "evidence"}:
                raise ValueError("quote does not match its actual recorded snapshot")
            unit = _money(quote.get("unitCny"), "unitCny")
            count = _positive_integer(quote.get("purchaseQty"), "purchaseQty")
            moq = _positive_integer(quote.get("moq"), "moq")
            multiple = _positive_integer(quote.get("multiple"), "multiple")
            stock = _positive_integer(quote.get("stock"), "stock", zero=True)
            if count < items[identifier]["need"] or count < moq or count % multiple or stock < count:
                raise ValueError("quantity/MOQ/multiple/available-stock mismatch")
            if quote.get("status") not in {"in_stock", "owned"} or quote.get("taxIncluded") is not True:
                raise ValueError("quote must be available and explicitly tax-inclusive")
            if not _instant(quote.get("quotedAt")) <= current <= _instant(quote.get("validUntil")):
                raise ValueError("stale, future or expired quotation")
            _text(quote.get("source"), "quote source")
            if quote.get("mpn") != items[identifier]["mpn"]:
                try:
                    qualification = _artifact(root, quote.get("qualification"))
                    if (qualification.get("schema") != "aicad_substitution_qualification_v1"
                        or qualification.get("itemId") != identifier
                        or qualification.get("originalMpn") != items[identifier]["mpn"]
                        or qualification.get("replacementMpn") != quote.get("mpn")
                        or qualification.get("designSha256") != design_sha
                        or qualification.get("approved") is not True
                        or any(qualification.get(key) is not True for key in ("footprint", "pinout", "ratings", "firmware", "mechanical"))):
                        raise ValueError("substitution needs source-bound full compatibility qualification")
                except (ValueError, OSError, TypeError) as exc:
                    fail("SUBSTITUTION_UNQUALIFIED", identifier + ": " + str(exc))
                    quote_error = True
            subtotal += (unit * count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (ValueError, OSError, TypeError, InvalidOperation) as exc:
            quote_error = True
            fail("QUOTE_INVALID", identifier + ": " + str(exc))
    report["knownSubtotalCny"] = format(subtotal, ".2f") if quotes else None
    costs_ready = not quote_error and set(quotes) == set(items) and not any(b["code"] == "COST_COVERAGE" for b in blockers)
    report["budgetCoverageReady"] = costs_ready
    report["quotedTotalCny"] = format(subtotal, ".2f") if costs_ready else None

    try:
        test_rows = _unique_rows(contract.get("tests"), "scenarioId")
        if set(test_rows) != set(scenarios):
            fail("FUNCTION_COVERAGE", "Every required effect/fault scenario needs its own actual bound test evidence.")
    except (ValueError, TypeError) as exc:
        fail("FUNCTION_COVERAGE", str(exc))
        test_rows = {}
    for identifier, row in test_rows.items():
        try:
            if identifier not in scenarios:
                raise ValueError("unexpected test scenario")
            result = _artifact(root, row.get("evidence"))
            scenario = scenarios[identifier]
            if (result.get("schema") != "aicad_functional_evidence_v1" or result.get("scenarioId") != identifier
                or result.get("designSha256") != design_sha or result.get("inventorySha256") != inventory_sha
                or result.get("level") != scenario["level"] or result.get("outcome") != "pass"):
                raise ValueError("test identity, source, method or outcome mismatch")
            _text(result.get("limitations"), "test-model limitations")
            measurements = result.get("measurements")
            checks = _unique_rows(scenario["checks"], "id")
            if not isinstance(measurements, dict) or set(measurements) != set(checks):
                raise ValueError("test measurement coverage mismatch")
            if not all(_check_measurement(measurements[key], check) for key, check in checks.items()):
                raise ValueError("measured behavior does not meet declared acceptance criteria")
        except (ValueError, OSError, TypeError, KeyError) as exc:
            fail("FUNCTION_EVIDENCE", identifier + ": " + str(exc))
    report["functionalPreOrderEvidenceReady"] = not any(b["code"].startswith("FUNCTION_") for b in blockers)

    try:
        approval = _artifact(root, contract.get("approval"))
        budget = _money(approval.get("budgetCny"), "budgetCny")
        if (approval.get("schema") != "aicad_budget_acceptance_v1" or approval.get("actor") != "human"
            or approval.get("confirmed") is not True or approval.get("projectId") != project_id
            or approval.get("action") != action or approval.get("designSha256") != design_sha
            or approval.get("inventorySha256") != inventory_sha
            or approval.get("quoteSetSha256") != canonical_sha256(contract.get("quotes"))
            or _instant(approval.get("validUntil")) < current):
            raise ValueError("budget acceptance must bind exact project/action/design/inventory/quotes and remain current")
        report["budgetCny"] = format(budget, "f")
        if costs_ready and subtotal > budget:
            fail("BUDGET_OVERRUN", f"Whole-deliverable total {subtotal:.2f} exceeds accepted budget {budget}.")
    except (ValueError, OSError, TypeError, KeyError) as exc:
        fail("BUDGET_APPROVAL", str(exc))

    report["orderPreflightPassed"] = not blockers
    report["ok"] = not blockers
    return report
