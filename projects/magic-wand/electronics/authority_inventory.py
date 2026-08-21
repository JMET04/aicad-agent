#!/usr/bin/env python3
"""Emit the fail-closed per-reference land-pattern authority baseline.

This inventory deliberately describes the current pre-correction design. It
does not authorize any footprint. Its purpose is to make the legacy
package-name based exact_land_pattern claims measurable before those claims
are removed and replaced with per-MPN controlled evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from build_factory_package import (
    BOARDS,
    ROOT,
    absolute_pads,
)
LEGACY_PACKAGE_NAME_WHITELIST = {
    "LGA-55", "LGA-14", "WSON-10-EP", "WSON-8-EP", "VSSOP-10", "VSSOP-8",
    "SO-4", "SON-2x2", "SOT-23-6", "USB-C-16P", "JST-SH-3", "JST-SH-2",
    "DF13A-5P-1.25H", "TB-2.54-2", "TB-2.54-3", "0402", "0603", "0805",
    "SOD-123", "L_4x4", "SKQG", "TESTPOINT", "NPTH",
}




SCHEMA = "aicad_land_pattern_authority_inventory_v1"
OUTPUT = ROOT / "evidence" / "authority" / "land-pattern-authority-inventory-baseline.json"
CRITICAL_PREFIXES = ("J", "U", "Q", "D", "L", "F", "SW")

KNOWN_BLOCKERS = {
    ("wand", "J1"): (
        "JAE SJ121837 requires 16 SMT contacts including A8/B8, four THT shell "
        "stakes, two NPTH locators and two unnumbered SMT hold-downs; current "
        "model has 14 contacts and two SMD shell pads."
    ),
    ("receiver", "J1"): (
        "JAE SJ121837 requires 16 SMT contacts including A8/B8, four THT shell "
        "stakes, two NPTH locators and two unnumbered SMT hold-downs; current "
        "model has 14 contacts and two SMD shell pads."
    ),
    ("wand", "J2"): "JST SM03B official pattern includes two MP anchor pads; current model omits them.",
    ("wand", "J3"): "JST SM02B official pattern includes two MP anchor pads; current model omits them.",
    ("wand", "SW1"): (
        "SKQGAFE010 is a four-terminal 5.2 x 5.2 x 1.5 mm switch; current model "
        "has two physical pads and a 4.0 x 3.5 mm body."
    ),
    ("wand", "F1"): (
        "MF-FSMF050X-2 requires its Bourns 0603 fuse land pattern; the legacy "
        "two-pin prefix mapping assigns an inductor footprint family."
    ),
    ("receiver", "F1"): "Fuse requires per-MPN manufacturer land-pattern authority.",
    ("wand", "L1"): "XFL4020-222MEC is not authorized by the generic L_4x4 geometry.",
    ("receiver", "L1"): "LQH32-series inductor is not authorized by the generic L_4x4 geometry.",
    ("receiver", "Q1"): (
        "CSD17313Q2 Texas_DQK has eight physical pads including exposed copper; "
        "current SON model has three pads."
    ),
    ("receiver", "D1"): "SS24-13-F is SMB/DO-214AA, not the current SOD-123 geometry.",
    ("receiver", "D2"): "SMBJ15A is DO-214AA/SMB, not the current SOD-123 geometry, even when DNP.",
    ("wand", "U2"): "LSM6DSV16X LGA-14 uses a four-side pad topology, not the current dual-row model.",
}


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _population(part) -> str:
    if part.dnp:
        return "DNP"
    if part.assembly == "NPTH":
        return "MECHANICAL_NPTH"
    if part.ref.startswith("TP"):
        return "BARE_PAD_POLICY_PENDING"
    return "FITTED"


def _severity(ref: str) -> str:
    return "P0" if ref.startswith(CRITICAL_PREFIXES) else "P1"


def _default_blocker(board_name: str, part) -> str:
    if part.ref.startswith("TP"):
        return "Testpoint population policy is unresolved: BOM says do-not-fit but current part is a fitted THT item."
    if part.assembly == "NPTH":
        return "Mechanical hole needs a board-interface authority record with finished-hole tolerance."
    if part.package in {"0402", "0603", "0805"}:
        return (
            "Passive needs a controlled manufacturer package plus component-class-specific "
            "KiCad/IPC footprint fingerprint; resistor, capacitor and fuse geometries may not be merged."
        )
    return (
        f"{board_name}.{part.ref} has no per-MPN controlled authority contract; "
        "a package-name whitelist cannot establish an exact land pattern."
    )


def _current_pads(part, pads_by_ref: dict[str, list[dict]]) -> list[dict]:
    result = []
    for index, pad in enumerate(pads_by_ref.get(part.ref, []), start=1):
        result.append(
            {
                "physicalPadId": f"{part.ref}:{index:03d}",
                "number": pad["number"],
                "net": pad.get("net", ""),
                "xMm": pad["x"],
                "yMm": pad["y"],
                "widthMm": pad["width"],
                "heightMm": pad["height"],
                "drillMm": pad["drill"],
                "kind": pad["kind"],
                "role": "locating" if pad["kind"] == "npth" else "electrical",
                "layers": (
                    ["*.Cu", "*.Mask"]
                    if pad["kind"] == "tht"
                    else ([] if pad["kind"] == "npth" else ["F.Cu", "F.Paste", "F.Mask"])
                ),
            }
        )
    return result


def build_inventory() -> dict:
    rows = []
    board_counts = {}
    for board in BOARDS:
        all_pads = absolute_pads(board, require_controlled=False)
        pads_by_ref: dict[str, list[dict]] = {}
        for pad in all_pads:
            pads_by_ref.setdefault(pad["ref"], []).append(pad)
        board_counts[board.name] = {
            "refs": len(board.parts),
            "currentExactClaims": sum(bool(part.exact_land_pattern) for part in board.parts),
        }
        for part in board.parts:
            pads = _current_pads(part, pads_by_ref)
            whitelist_claim = part.package in LEGACY_PACKAGE_NAME_WHITELIST
            blocker = KNOWN_BLOCKERS.get((board.name, part.ref), _default_blocker(board.name, part))
            rows.append(
                {
                    "board": board.name,
                    "ref": part.ref,
                    "value": part.value,
                    "manufacturer": part.manufacturer,
                    "mpn": part.mpn,
                    "population": _population(part),
                    "assembly": part.assembly,
                    "package": part.package,
                    "footprint": part.footprint,
                    "orientationDeg": part.rotation,
                    "bodyEnvelopeCurrentMm": [part.width, part.height],
                    "logicalPinCount": len(part.pins),
                    "physicalPadCountCurrent": len(pads),
                    "physicalPadsCurrent": pads,
                    "physicalPadFingerprintCurrent": _canonical_sha(pads),
                    "currentExactLandPatternClaim": bool(part.exact_land_pattern),
                    "currentClaimMechanism": (
                        "PACKAGE_NAME_WHITELIST"
                        if whitelist_claim
                        else "LEGACY_MANUAL_BOOLEAN_WITHOUT_CONTROLLED_EVIDENCE"
                    ),
                    "authorityStatus": "BLOCKED_NO_PER_REF_AUTHORITY",
                    "authorityId": None,
                    "authorityEvidence": None,
                    "severity": _severity(part.ref),
                    "releaseBlocker": blocker,
                }
            )
    rows.sort(key=lambda row: (row["board"], row["ref"]))
    exact_claims = sum(row["currentExactLandPatternClaim"] for row in rows)
    package_claims = sum(row["currentClaimMechanism"] == "PACKAGE_NAME_WHITELIST" for row in rows)
    p0_rows = [row for row in rows if row["severity"] == "P0"]
    population = Counter(row["population"] for row in rows)
    return {
        "schema": SCHEMA,
        "status": "BLOCKED_BASELINE",
        "kind": "land_pattern_authority_inventory",
        "scope": "magic-wand dual PCB factory package",
        "policy": {
            "exactClaimRule": "No per-reference controlled authority contract means exact_land_pattern=false.",
            "packageNameWhitelistAccepted": False,
            "physicalPadComparison": "ordered canonical physical-pad multiset; duplicate pad numbers are preserved",
            "routeReuse": "authority, every physical pad, body/datum, rules and layer stack are fingerprint inputs",
        },
        "summary": {
            "totalRefs": len(rows),
            "boards": board_counts,
            "currentExactClaims": exact_claims,
            "invalidPackageAutoExactClaims": package_claims,
            "releaseBlockedRefs": len(rows),
            "criticalP0Refs": len(p0_rows),
            "remainingP0": len(p0_rows),
            "population": dict(sorted(population.items())),
        },
        "gateAssertions": {
            "inventoryCompleteForCurrentSource": len(rows) == sum(len(board.parts) for board in BOARDS),
            "allCurrentExactClaimsFailClosed": exact_claims == len(rows),
            "allRefsHaveControlledAuthority": False,
            "placementRouteAllowed": False,
            "prototypeReleaseAllowed": False,
        },
        "rows": rows,
        "inventoryFingerprint": _canonical_sha(rows),
    }


def main() -> int:
    if OUTPUT.is_file():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
        summary = existing.get("summary", {})
        if (
            existing.get("schema") != SCHEMA
            or existing.get("status") != "BLOCKED_BASELINE"
            or summary.get("totalRefs") != 92
            or summary.get("currentExactClaims") != 92
            or summary.get("invalidPackageAutoExactClaims") != 92
        ):
            raise RuntimeError("existing historical baseline failed immutable 92/92 policy checks")
        print(f"{OUTPUT.relative_to(ROOT)}: immutable historical baseline verified; not overwritten")
        return 0

    inventory = build_inventory()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = inventory["summary"]
    print(
        f"{OUTPUT.relative_to(ROOT)}: refs={summary['totalRefs']} "
        f"exact={summary['currentExactClaims']} invalidAutoExact={summary['invalidPackageAutoExactClaims']} "
        f"P0={summary['remainingP0']} status={inventory['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
