from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable


PACKAGE = Path(__file__).resolve().parent
MAGIC_WAND = PACKAGE.parent
REPO_ROOT = PACKAGE.parents[2]

RELEASE_LOCKS = {
    "reviewOnly": True,
    "accepted": False,
    "technicalPackageReady": False,
    "manufacturingAuthorized": False,
    "fabricationAuthorized": False,
    "productionReleaseEligible": False,
    "humanEngineeringReviewRequired": True,
}

SOURCE_FILES = (
    MAGIC_WAND / "system-requirements.json",
    MAGIC_WAND / "mechanical" / "design-parameters.json",
    MAGIC_WAND / "mechanical" / "assembly-layout.json",
    MAGIC_WAND / "mechanical" / "bom.json",
    MAGIC_WAND / "mechanical" / "CAPABILITY_BLOCKERS.json",
    MAGIC_WAND / "mechanical" / "REQUIREMENTS_INTERFACES_TOLERANCES.md",
    MAGIC_WAND / "mechanical" / "generated-source-manifest.json",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def file_record(path: Path, kind: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": repo_path(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "kind": kind,
    }


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def authored_files(root: Path) -> list[Path]:
    ignored_parts = {".git", ".pytest_cache", "__pycache__", "build", "build-host", "cmakefiles", "testing"}
    allowed = {".c", ".csv", ".h", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in allowed
        and not any(
            part.casefold() in ignored_parts
            or part.casefold().startswith(("build-", "build_", "cmake-build"))
            for part in path.parts
        )
    )


def extract_markdown_blockers(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.fullmatch(r"(?:BLK|FW-BLK|ENV)-[A-Z0-9-]+", cells[0]):
            continue
        seen.add(cells[0])
        rows.append({
            "id": cells[0],
            "severity": cells[1].casefold() if len(cells) > 1 else "blocker",
            "finding": cells[2],
            "requiredClosure": cells[3] if len(cells) > 3 else "Independent evidence required.",
            "sourcePaths": [repo_path(path)],
            "status": "open",
            "closed": False,
        })
    for blocker_id in sorted(set(re.findall(r"\b(?:BLK|FW-BLK|ENV)-[A-Z0-9-]+\b", text)) - seen):
        rows.append({
            "id": blocker_id,
            "severity": "blocker",
            "finding": "Blocker referenced by the source package; read the bound source path for full context.",
            "requiredClosure": "Close the source-package evidence requirement and retain its exact identifier in the system audit.",
            "sourcePaths": [repo_path(path)],
            "status": "open",
            "closed": False,
        })
    return rows


def extract_json_blockers(path: Path) -> list[dict[str, Any]]:
    try:
        value = load_json(path)
    except (ValueError, json.JSONDecodeError):
        return []
    candidates = value.get("blockers")
    if not isinstance(candidates, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        rows.append({
            "id": item["id"],
            "severity": str(item.get("severity", "blocker")).casefold(),
            "finding": str(item.get("finding", item.get("reason", "Source package blocker."))),
            "requiredClosure": str(item.get("requiredClosure", item.get("required_closure", "Independent evidence required."))),
            "sourcePaths": [repo_path(path)],
            "status": "open",
            "closed": False,
        })
    return rows


def merge_blockers(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        blocker_id = row["id"]
        if blocker_id not in merged:
            merged[blocker_id] = row
            continue
        current = merged[blocker_id]
        current["sourcePaths"] = sorted(set(current["sourcePaths"] + row["sourcePaths"]))
    return [merged[key] for key in sorted(merged)]


def build_blockers(firmware_files: list[Path]) -> dict[str, Any]:
    mechanical = load_json(MAGIC_WAND / "mechanical" / "CAPABILITY_BLOCKERS.json")
    rows = [
        {
            "id": row["id"],
            "severity": row["severity"],
            "finding": row["reason"],
            "requiredClosure": row["required_closure"],
            "sourcePaths": [repo_path(MAGIC_WAND / "mechanical" / "CAPABILITY_BLOCKERS.json")],
            "status": "open",
            "closed": False,
        }
        for row in mechanical["blockers"]
    ]
    for path in authored_files(MAGIC_WAND / "electronics"):
        if path.suffix.casefold() == ".json":
            rows.extend(extract_json_blockers(path))
        elif path.suffix.casefold() == ".md":
            rows.extend(extract_markdown_blockers(path))
    for path in firmware_files:
        if path.suffix.casefold() == ".json":
            rows.extend(extract_json_blockers(path))
        elif path.suffix.casefold() == ".md":
            rows.extend(extract_markdown_blockers(path))
    rows.extend([
        {
            "id": "INT-BLK-001",
            "severity": "blocker",
            "finding": "Exact PCB outlines, battery, actuator and harness have not been proven against a native assembly interference model.",
            "requiredClosure": "Freeze exact ordered parts and board outlines; build the native assembly; prove fits, clearances, button alignment and serviceability after reopen.",
            "sourcePaths": [repo_path(MAGIC_WAND / "mechanical" / "assembly-layout.json"), repo_path(MAGIC_WAND / "electronics" / "interface-control.md")],
            "status": "open",
            "closed": False,
        },
        {
            "id": "INT-BLK-002",
            "severity": "blocker",
            "finding": "Press-to-arm release, reset, brownout, watchdog and link-loss safe timing have no target-hardware HIL or oscilloscope evidence.",
            "requiredClosure": "Run timestamped HIL fault injection and archive output waveforms proving the 100 ms release target and 250 ms link-loss target.",
            "sourcePaths": [repo_path(MAGIC_WAND / "system-requirements.json")],
            "status": "open",
            "closed": False,
        },
        {
            "id": "INT-BLK-003",
            "severity": "blocker",
            "finding": "Authenticated command protocol, monotonic persistence and gesture rejection have not been target-compiled, packet-captured or security-reviewed.",
            "requiredClosure": "Target-build and flash pinned firmware; run replay, nonce, stale-session, cross-device, fuzz and power-loss persistence tests with an independent security review.",
            "sourcePaths": [repo_path(MAGIC_WAND / "system-requirements.json")],
            "status": "open",
            "closed": False,
        },
        {
            "id": "INT-BLK-004",
            "severity": "blocker",
            "finding": "Antenna keepout is not backed by final PCB/enclosure/hand-effect RF evidence.",
            "requiredClosure": "Bind the current u-blox integration authority to the final stack and complete representative radiated or conducted comparison tests.",
            "sourcePaths": [repo_path(MAGIC_WAND / "mechanical" / "REQUIREMENTS_INTERFACES_TOLERANCES.md"), repo_path(MAGIC_WAND / "electronics" / "system-architecture.md")],
            "status": "open",
            "closed": False,
        },
        {
            "id": "INT-BLK-005",
            "severity": "blocker",
            "finding": "External mains relay and drone AUX integrations have no qualified installer/integrator evidence; applicable radio, EMC, battery and regional obligations are not closed.",
            "requiredClosure": "Obtain qualified electrical and flight-system reviews and complete the applicable compliance plan and staged tests.",
            "sourcePaths": [repo_path(MAGIC_WAND / "system-requirements.json")],
            "status": "open",
            "closed": False,
        },
        {
            "id": "INT-BLK-006",
            "severity": "blocker",
            "finding": "Factory release evidence is incomplete across native drawings, KiCad/CAM, target firmware, materials, process capability and physical validation.",
            "requiredClosure": "Complete every EVT/DVT/PVT exit criterion and independent approval; regenerate this manifest from the frozen revisions before release consideration.",
            "sourcePaths": [repo_path(MAGIC_WAND / "system-requirements.json")],
            "status": "open",
            "closed": False,
        },
    ])
    return {
        "schema": "aicad_magic_wand_system_blockers_v1",
        "projectId": "MW-PROTOTYPE-001",
        "revision": "A",
        "status": "open_blockers_release_prohibited",
        "blockers": merge_blockers(rows),
        "releaseLocks": RELEASE_LOCKS,
    }


def build_trace(blocker_ids: set[str], firmware_paths: list[str]) -> dict[str, Any]:
    system = load_json(MAGIC_WAND / "system-requirements.json")
    fixed: dict[str, dict[str, Any]] = {
        "SYS-001": {"evidencePaths": ["projects/magic-wand/mechanical/design-parameters.json", "projects/magic-wand/mechanical/assembly-layout.json"], "openBlockerIds": ["MW-BLK-002", "MW-BLK-003", "MW-BLK-005", "INT-BLK-001"]},
        "SYS-002": {"evidencePaths": ["projects/magic-wand/mechanical/REQUIREMENTS_INTERFACES_TOLERANCES.md", "projects/magic-wand/electronics/interface-control.md", *firmware_paths], "openBlockerIds": ["BLK-FW-001", "INT-BLK-002"]},
        "SYS-003": {"evidencePaths": ["projects/magic-wand/electronics/system-architecture.md", *firmware_paths], "openBlockerIds": ["BLK-FW-001", "INT-BLK-002"]},
        "SYS-004": {"evidencePaths": ["projects/magic-wand/electronics/system-architecture.md", *firmware_paths], "openBlockerIds": ["BLK-FW-001", "INT-BLK-003"]},
        "SYS-005": {"evidencePaths": ["projects/magic-wand/electronics/system-architecture.md", *firmware_paths], "openBlockerIds": ["BLK-FW-001", "INT-BLK-003"]},
        "SYS-006": {"evidencePaths": ["projects/magic-wand/electronics/interface-control.md", "projects/magic-wand/electronics/design-calculations.md", "projects/magic-wand/electronics/bom.csv"], "openBlockerIds": ["BLK-EDA-001", "BLK-SIM-001", "BLK-MECH-001"]},
        "SYS-007": {"evidencePaths": ["projects/magic-wand/mechanical/assembly-layout.json", "projects/magic-wand/mechanical/REQUIREMENTS_INTERFACES_TOLERANCES.md", "projects/magic-wand/electronics/system-architecture.md"], "openBlockerIds": ["MW-BLK-004", "INT-BLK-004"]},
        "SYS-008": {"evidencePaths": ["projects/magic-wand/electronics/interface-control.md", "projects/magic-wand/electronics/receiver/connectivity.csv"], "openBlockerIds": ["BLK-EDA-001", "INT-BLK-002"]},
        "SYS-009": {"evidencePaths": ["projects/magic-wand/electronics/interface-control.md"], "openBlockerIds": ["BLK-SAFE-001", "INT-BLK-005"]},
        "SYS-010": {"evidencePaths": ["projects/magic-wand/electronics/interface-control.md"], "openBlockerIds": ["BLK-SAFE-001", "INT-BLK-005"]},
        "SYS-011": {"evidencePaths": ["projects/magic-wand/electronics/system-architecture.md", *firmware_paths], "openBlockerIds": ["BLK-FW-001", "INT-BLK-002"]},
        "SYS-012": {"evidencePaths": ["projects/magic-wand/system-requirements.json", "projects/magic-wand/mechanical/CAPABILITY_BLOCKERS.json", "projects/magic-wand/electronics/review-report.md", "projects/magic-wand/integration/system-blockers.json"], "openBlockerIds": ["INT-BLK-006"]},
    }
    rows = []
    for requirement in system["requirements"]:
        link = fixed[requirement["id"]]
        rows.append({
            "id": requirement["id"],
            "category": requirement["category"],
            "requirement": requirement["requirement"],
            "acceptance": requirement["acceptance"],
            "verification": requirement["verification"],
            "sourceStatus": requirement["status"],
            "evidencePaths": sorted(set(link["evidencePaths"])),
            "openBlockerIds": [item for item in link["openBlockerIds"] if item in blocker_ids],
            "verificationState": "release_lock_control_enforced" if requirement["id"] == "SYS-012" else "evidence_pending",
            "verificationClosed": False,
        })
    return {
        "schema": "aicad_magic_wand_system_traceability_v1",
        "projectId": system["projectId"],
        "revision": system["revision"],
        "sourcePath": repo_path(MAGIC_WAND / "system-requirements.json"),
        "requirements": rows,
        "coverage": {"required": 12, "traced": len(rows), "missing": []},
        "releaseLocks": RELEASE_LOCKS,
    }


def build_interfaces(firmware_paths: list[str]) -> dict[str, Any]:
    evidence_fw = firmware_paths or ["projects/magic-wand/electronics/review-report.md"]
    rows = [
        ("IF-MECH-PCB-001", "mechanical", "wand PCB/carrier", "Carrier outer 17.8 x 12.8 mm, inner channel 15.4 x 10.4 mm, inside nominal shell ID 23.0 mm; exact PCB outline and keepouts remain unfrozen.", "No forced assembly; quote-only until native fit/interference proof.", ["projects/magic-wand/mechanical/assembly-layout.json", "projects/magic-wand/mechanical/REQUIREMENTS_INTERFACES_TOLERANCES.md"], "blocked"),
        ("IF-ARM-001", "press-to-arm switch", "wand MCU ARM_N", "Momentary normally-open switch at global Z=72 +/-0.5 mm; recessed at least 0.6 mm; grounds dedicated ARM_N through 1 kOhm with 100 kOhm pull-up.", "Stuck-low is a fault; release requests disarm; no command enable without continuous hold.", ["projects/magic-wand/mechanical/REQUIREMENTS_INTERFACES_TOLERANCES.md", "projects/magic-wand/electronics/interface-control.md", *evidence_fw], "blocked_hil_pending"),
        ("IF-RF-001", "NINA-B302 internal PIFA", "enclosure/host PCB", "Antenna end faces nonconductive rear region; mechanical keepout global Z=5..30 mm, radius 11.5 mm; no metal, battery, GFRP, shielding or harness in the conservative envelope.", "No RF pass claim; final vendor-rule overlay and representative hand/enclosure test required.", ["projects/magic-wand/mechanical/assembly-layout.json", "projects/magic-wand/electronics/system-architecture.md"], "blocked_rf_test_pending"),
        ("IF-PWR-WAND-001", "USB-C / protected 1S LiPo", "wand power tree", "5 V sink-only USB-C feeds BQ25185; protected 1S LiPo with 10 kOhm NTC; TPS63900 creates 3.3 V logic rail.", "Charge prohibited until exact cell/protection/NTC limits and thermal behavior are verified.", ["projects/magic-wand/electronics/interface-control.md", "projects/magic-wand/electronics/design-calculations.md"], "blocked_eda_bench_pending"),
        ("IF-BLE-001", "wand NINA-B302", "receiver NINA-B302", "BLE 1M, LE Secure Connections plus application AES-CCM, direction/device/session binding and monotonic anti-replay sequence.", "Invalid, stale, duplicate or unauthenticated packets cause no output and do not renew arm lease.", ["projects/magic-wand/electronics/system-architecture.md", *evidence_fw], "blocked_target_security_test_pending"),
        ("IF-RX-LOGIC-001", "receiver", "external controller", "J2 exposes GND, external VREF_IO 3.3/5 V, UART TX/RX and PWM/AUX. It is signal-only; SBUS requires an externally reviewed inverter.", "Outputs default inactive; no propulsion energy or arming/primary flight control.", ["projects/magic-wand/electronics/interface-control.md", "projects/magic-wand/electronics/receiver/connectivity.csv"], "blocked_eda_bench_pending"),
        ("IF-RX-ISO-001", "receiver optocoupler", "external low-voltage input", "J3 is floating collector/emitter, external pull-up, target 3.3..24 V and <=10 mA subject to exact CTR validation.", "Signal isolation only; no mains conductor on PCB or inside enclosure.", ["projects/magic-wand/electronics/interface-control.md"], "blocked_eda_bench_pending"),
        ("IF-RX-LOAD-001", "receiver MOSFET", "external SELV load", "J4 common-ground 5..12 V low-side channel, provisional 1 A continuous / 2 A 100 ms; external supply protection and inductive flyback required.", "No mains and no flight propulsion; hardware pulldown holds gate inactive on reset.", ["projects/magic-wand/electronics/interface-control.md", "projects/magic-wand/electronics/receiver/connectivity.csv"], "blocked_drc_thermal_load_test_pending"),
        ("IF-MAINS-001", "receiver SELV output", "external certified relay/contactor", "Only the certified product's low-voltage control input may connect; all mains wiring, enclosure, creepage and installation are external.", "Qualified electrical professional review mandatory; no mains enters AICAD PCB/enclosure.", ["projects/magic-wand/system-requirements.json", "projects/magic-wand/electronics/interface-control.md"], "external_specialist_required"),
        ("IF-DRONE-001", "receiver signal", "autopilot AUX/telemetry", "Only non-flight-critical AUX or telemetry signal; no motor, ESC power, arming or primary flight controls.", "Integrator-configured failsafe; ground and restrained-prop test before any flight.", ["projects/magic-wand/system-requirements.json", "projects/magic-wand/electronics/interface-control.md"], "external_specialist_required"),
    ]
    return {
        "schema": "aicad_magic_wand_interface_control_v1",
        "projectId": "MW-PROTOTYPE-001",
        "revision": "A",
        "coordinateAuthority": "Mechanical datum A at rear cap outer plane Z=0, datum B common axis, millimetres.",
        "interfaces": [
            {
                "id": item[0], "producer": item[1], "consumer": item[2], "contract": item[3],
                "safeState": item[4], "evidencePaths": sorted(set(item[5])), "status": item[6],
            }
            for item in rows
        ],
        "releaseLocks": RELEASE_LOCKS,
    }


def build_bom() -> tuple[dict[str, Any], str]:
    mechanical = load_json(MAGIC_WAND / "mechanical" / "bom.json")
    rows: list[dict[str, Any]] = []
    for row in mechanical["rows"]:
        rows.append({
            "uid": f"MECH:{row['part_number']}", "domain": "mechanical", "assembly": "wand",
            "sourceIdentifier": row["part_number"], "refs": None, "quantity": row["quantity"],
            "manufacturer": None, "manufacturerPartNumber": row["part_number"],
            "description": row["description"], "specification": row["material"],
            "processOrPackage": row["process"], "makeBuy": row["make_buy"],
            "unitPriceCny": None, "extendedPriceCny": None, "priceStatus": "unknown_not_quoted",
            "sourcePath": repo_path(MAGIC_WAND / "mechanical" / "bom.json"),
        })
    with (MAGIC_WAND / "electronics" / "bom.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=1):
            uid = f"ELEC:{row['board']}:{row['refs']}"
            rows.append({
                "uid": uid, "domain": "electronics", "assembly": row["board"],
                "sourceIdentifier": f"E{index:03d}", "refs": row["refs"], "quantity": int(row["qty"]),
                "manufacturer": row["manufacturer"], "manufacturerPartNumber": row["mpn"],
                "description": row["description"], "specification": row["key_requirement"],
                "processOrPackage": row["package_or_value"], "makeBuy": "buy",
                "unitPriceCny": None, "extendedPriceCny": None, "priceStatus": "unknown_not_quoted_order_time_recheck",
                "sourcePath": repo_path(MAGIC_WAND / "electronics" / "bom.csv"),
            })
    uids = [row["uid"].casefold() for row in rows]
    if len(uids) != len(set(uids)):
        raise ValueError("combined BOM UID collision")
    bom = {
        "schema": "aicad_magic_wand_combined_bom_v1",
        "projectId": "MW-PROTOTYPE-001", "revision": "A",
        "status": "review_only_prices_unknown_not_procurement_release",
        "currency": "CNY", "rows": rows,
        "notes": [
            "Null prices are intentional: no timestamped supplier or factory quotation was provided.",
            "Grouped electronics references remain one source BOM line and must be exploded by the EDA BOM before procurement.",
            "Firmware has no physical BOM row; programming fixtures and licenses are excluded pending process design.",
        ],
        "releaseLocks": RELEASE_LOCKS,
    }
    out = io.StringIO(newline="")
    fields = ["uid", "domain", "assembly", "source_identifier", "refs", "quantity", "manufacturer", "manufacturer_part_number", "description", "specification", "process_or_package", "make_buy", "unit_price_cny", "extended_price_cny", "price_status", "source_path"]
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "uid": row["uid"], "domain": row["domain"], "assembly": row["assembly"],
            "source_identifier": row["sourceIdentifier"], "refs": row["refs"] or "",
            "quantity": row["quantity"], "manufacturer": row["manufacturer"] or "",
            "manufacturer_part_number": row["manufacturerPartNumber"], "description": row["description"],
            "specification": row["specification"], "process_or_package": row["processOrPackage"],
            "make_buy": row["makeBuy"], "unit_price_cny": "", "extended_price_cny": "",
            "price_status": row["priceStatus"], "source_path": row["sourcePath"],
        })
    return bom, out.getvalue()


def build_fmea() -> dict[str, Any]:
    raw = [
        ("FMEA-001", ["SYS-002"], "Press-to-arm switch stuck low or mechanically jammed", "Unexpected armed request", 5, 3, 3, "Recessed momentary switch; stuck-low fault; continuous-hold lease", "Switch fault injection and release timing HIL"),
        ("FMEA-002", ["SYS-002", "SYS-003"], "Firmware fails to disarm on release/reset/watchdog", "Receiver output remains active", 5, 2, 4, "Independent raw input; bounded lease; watchdog; safe defaults", "Oscilloscope capture over release/reset/brownout/watchdog"),
        ("FMEA-003", ["SYS-003"], "Receiver output glitches during boot or brownout", "Uncommanded load pulse", 5, 3, 4, "Gate pulldown; inactive GPIO initialization; power-good monitor", "Repeated power ramp and reset fault injection at all outputs"),
        ("FMEA-004", ["SYS-003"], "BLE link loss is not detected in budget", "Stale command persists", 5, 2, 4, "Freshness window, arm lease and link watchdog", "RF attenuation/disconnect HIL with output waveform"),
        ("FMEA-005", ["SYS-005"], "Replay, cross-device or stale-session packet accepted", "Unauthorized output activation", 5, 2, 5, "LE Secure Connections plus AES-CCM/session/direction/sequence binding", "Negative vectors, packet capture, reboot/power-loss sequence tests"),
        ("FMEA-006", ["SYS-005"], "Nonce or monotonic counter reused after power loss", "Authentication confidentiality/integrity weakened", 5, 2, 5, "Persistent sequence epoch and fail-closed recovery", "Power-cut campaign and storage wear/corruption tests"),
        ("FMEA-007", ["SYS-004"], "False gesture classification", "Wrong but authenticated command", 4, 4, 3, "Confidence threshold, rejection class, press-to-arm gating", "Representative-user confusion matrix and false-activation study"),
        ("FMEA-008", ["SYS-004"], "Relative IMU estimate represented as exact 3D path", "Unsafe or misleading application behavior", 4, 3, 2, "Explicit no-absolute-position contract", "Requirements/UI/content audit and algorithm review"),
        ("FMEA-009", ["SYS-006"], "Wrong cell, NTC or charger setting", "Cell overheating, swelling or fire", 5, 3, 4, "Protected keyed pack; NTC supervision; current/thermal limits", "Ordered-part audit, abuse-aware bench charge and thermal test"),
        ("FMEA-010", ["SYS-006"], "Haptic/BLE transient collapses 3.3 V rail", "Reset, lost safety state or erratic feedback", 4, 3, 4, "Buck-boost margin and decoupling; brownout-safe logic", "Worst-state transient waveform and hot/cold battery test"),
        ("FMEA-011", ["SYS-007"], "Antenna detuned by ground, battery, GFRP, hand or enclosure", "Intermittent link and delayed safe-state detection", 4, 4, 4, "Nonconductive end and conservative mechanical keepout", "Final layout overlay and representative RF comparison/pre-scan"),
        ("FMEA-012", ["SYS-008"], "VREF_IO or connector is miswired", "Damage or unexpected logic state", 4, 3, 3, "Keyed labels, voltage-domain contract and translator direction", "Connector fault injection and voltage sweep"),
        ("FMEA-013", ["SYS-008"], "Optocoupler CTR insufficient or isolation pins grounded", "Output fails or isolation boundary is lost", 4, 3, 4, "Floating collector/emitter and conservative current target", "Exact-bin review, DRC and min/max temperature load test"),
        ("FMEA-014", ["SYS-008"], "MOSFET short, copper overheats or flyback omitted", "Load remains active or board overheats", 5, 3, 4, "Gate pulldown, provisional current limit and external flyback", "DRC/current-density review, thermal test and inductive fault test"),
        ("FMEA-015", ["SYS-009"], "Mains conductor or uncertified relay is brought inside product", "Shock, fire or regulatory breach", 5, 2, 3, "Hard SELV boundary and external certified enclosed relay only", "Qualified installer design/installation inspection"),
        ("FMEA-016", ["SYS-010"], "Receiver assigned to arming, propulsion or primary flight control", "Loss of vehicle control or injury", 5, 2, 4, "AUX/telemetry-only contract; no propulsion wiring", "Integrator config audit, ground and restrained-prop failsafe test"),
        ("FMEA-017", ["SYS-001", "SYS-007"], "Shell, rod or adhesive interface fails", "Parts detach; antenna stack shifts; impact hazard", 4, 3, 4, "GFRP insertion and prototype fit definitions", "Material freeze, coupon/pull test, drop/fatigue and first-article inspection"),
        ("FMEA-018", ["SYS-011"], "Feedback pattern is ambiguous or indicates success on fault", "User repeats or misinterprets command", 3, 4, 3, "Distinct paired/armed/accepted/rejected/fault patterns", "Blinded usability and state-machine fault tests"),
        ("FMEA-019", ["SYS-012"], "Stale drawing/BOM/firmware revision reaches factory", "Wrong product or latent safety defect", 5, 3, 3, "Hash manifest, revision parity and release locks", "Independent manifest/revision audit at every handoff"),
        ("FMEA-020", ["SYS-012"], "Unqualified substitute or malformed MPN ordered", "Assembly, safety or lifecycle failure", 4, 4, 3, "Exact MPN/footprint review and order-time lifecycle recheck", "Procurement AVL review and incoming inspection"),
    ]
    return {
        "schema": "aicad_magic_wand_system_fmea_v1", "projectId": "MW-PROTOTYPE-001", "revision": "A",
        "scale": "1 low to 5 high; RPN is triage only and never overrides a severity-5 hazard gate",
        "rows": [
            {"id": row[0], "linkedRequirements": row[1], "failureMode": row[2], "effect": row[3],
             "severity": row[4], "occurrence": row[5], "detectability": row[6],
             "rpn": row[4] * row[5] * row[6], "currentControls": row[7], "requiredVerification": row[8],
             "status": "open", "closed": False}
            for row in raw
        ],
        "releaseLocks": RELEASE_LOCKS,
    }


def build_factory_plan() -> dict[str, Any]:
    stages = [
        ("EVT", [
            ("EVT-001", "Freeze exact battery, haptic, switch, connectors, PCB outlines and controlled datasheet revisions", "open"),
            ("EVT-002", "Add missing native press-to-arm side cut and prove native assembly fit/interference/reopen", "blocked"),
            ("EVT-003", "Capture wand and receiver in KiCad; peer-check symbols/footprints/pins; run zero-unresolved ERC/DRC", "blocked"),
            ("EVT-004", "Export revision-bound schematic PDF, PCB, BOM, CPL, assembly/fab drawings, Gerbers and PTH/NPTH drills", "blocked"),
            ("EVT-005", "Target-build/flash pinned firmware and run host unit tests plus target HIL fault/security tests", "blocked"),
            ("EVT-006", "Build supervised mechanical samples and PCBA engineering samples with incoming inspection", "blocked"),
            ("EVT-007", "Measure charge/thermal, rail transient, RF, I/O loads, arm/link-loss timing and gesture confusion matrix", "blocked"),
            ("EVT-008", "Independent EVT hazard review; document every failure and controlled ECO", "blocked"),
        ]),
        ("DVT", [
            ("DVT-001", "Freeze design inputs, material/process specifications, tolerances, firmware protocol and threat model", "blocked"),
            ("DVT-002", "Complete structural/drop/fatigue/adhesive, environmental and battery/charging validation", "blocked"),
            ("DVT-003", "Complete RF/EMC pre-scan and applicable radio, USB, battery and regional compliance plan/tests", "blocked"),
            ("DVT-004", "Validate misuse, fault injection, security, usability and all receiver interface limits on representative units", "blocked"),
            ("DVT-005", "Release native manufacturing drawings, DFM feedback, test fixtures and service/recovery instructions for review", "blocked"),
        ]),
        ("PVT", [
            ("PVT-001", "Approve supplier AVL, incoming controls, golden samples and revision-locked factory package", "blocked"),
            ("PVT-002", "Run pilot build with calibrated fixtures, programming/key injection, serialization and end-of-line tests", "blocked"),
            ("PVT-003", "Demonstrate yield, process capability, traceability, rework controls and failure containment", "blocked"),
            ("PVT-004", "Close independent engineering, regulatory, quality and release approvals before any production authorization", "blocked"),
        ]),
    ]
    return {
        "schema": "aicad_magic_wand_evt_dvt_pvt_plan_v1", "projectId": "MW-PROTOTYPE-001", "revision": "A",
        "currentGate": "pre_EVT_definition_blocked_from_pcb_fabrication_and_production",
        "stages": [{"stage": stage, "items": [{"id": i, "requiredEvidence": text, "status": status, "closed": False} for i, text, status in items]} for stage, items in stages],
        "factoryQuotation": {
            "mechanicalQuoteOnly": True,
            "mechanicalReferencePaths": [
                "projects/magic-wand/mechanical/artifacts/3d/handle_shell/handle_shell.step",
                "projects/magic-wand/mechanical/artifacts/3d/internal_carrier/internal_carrier.step",
                "projects/magic-wand/mechanical/artifacts/3d/rear_end_cap/rear_end_cap.step",
                "projects/magic-wand/mechanical/artifacts/3d/rod_connector/rod_connector.step",
                "projects/magic-wand/mechanical/artifacts/2d/wand_general_arrangement/wand_general_arrangement.dxf",
            ],
            "conditions": ["REVIEW ONLY / NOT FOR PRODUCTION must remain visible", "Quote and DFM feedback only; no fabrication authorization", "Supplier must state assumed process/material/tolerance and return deviations"],
            "electronicsFabricationAllowed": False,
            "reason": "No native KiCad, ERC/DRC, CAM or target-firmware evidence exists.",
        },
        "releaseLocks": RELEASE_LOCKS,
    }


def build_cost() -> dict[str, Any]:
    providers = {
        "openai": {"model": "gpt-5.6-terra", "inputUsdPerMillion": 2.0, "cachedInputUsdPerMillion": 0.2, "outputUsdPerMillion": 12.0, "pricingUrl": "https://developers.openai.com/api/docs/models/gpt-5.6-terra"},
        "deepseek": {"model": "deepseek-v4-pro", "inputUsdPerMillion": 0.435, "cachedInputUsdPerMillion": 0.003625, "outputUsdPerMillion": 0.87, "pricingUrl": "https://api-docs.deepseek.com/quick_start/pricing/"},
    }
    phases = [
        ("mechanical_drawings", 160_000, 65_000, 40, 70, 220, 18, 32),
        ("electronics_and_firmware", 210_000, 90_000, 55, 95, 260, 30, 52),
        ("system_integration", 95_000, 42_000, 24, 40, 240, 12, 22),
    ]
    exchange = 7.20
    rows = []
    for phase, input_tokens, output_tokens, human_low, human_high, hourly, review_low, review_high in phases:
        api: dict[str, Any] = {}
        for provider, pricing in providers.items():
            usd = input_tokens / 1_000_000 * pricing["inputUsdPerMillion"] + output_tokens / 1_000_000 * pricing["outputUsdPerMillion"]
            api[provider] = {"usd": round(usd, 6), "cny": round(usd * exchange, 2)}
        rows.append({
            "phase": phase, "estimatedInputTokens": input_tokens, "estimatedOutputTokens": output_tokens,
            "humanOnlyHours": {"low": human_low, "high": human_high},
            "humanHourlyRateCny": hourly,
            "humanOnlyCostCny": {"low": human_low * hourly, "high": human_high * hourly},
            "requiredHumanReviewAfterAiHours": {"low": review_low, "high": review_high},
            "requiredHumanReviewAfterAiCostCny": {"low": review_low * hourly, "high": review_high * hourly},
            "apiTokenOnlyCost": api,
        })
    totals: dict[str, Any] = {
        "estimatedInputTokens": sum(row["estimatedInputTokens"] for row in rows),
        "estimatedOutputTokens": sum(row["estimatedOutputTokens"] for row in rows),
        "humanOnlyCostCny": {"low": sum(row["humanOnlyCostCny"]["low"] for row in rows), "high": sum(row["humanOnlyCostCny"]["high"] for row in rows)},
        "requiredHumanReviewAfterAiCostCny": {"low": sum(row["requiredHumanReviewAfterAiCostCny"]["low"] for row in rows), "high": sum(row["requiredHumanReviewAfterAiCostCny"]["high"] for row in rows)},
        "apiTokenOnlyCostCny": {provider: round(sum(row["apiTokenOnlyCost"][provider]["cny"] for row in rows), 2) for provider in providers},
    }
    return {
        "schema": "aicad_magic_wand_rough_cost_estimate_v1", "projectId": "MW-PROTOTYPE-001", "revision": "A",
        "snapshotDate": "2026-08-21", "currency": "CNY", "usdToCnyPlanningRate": exchange,
        "estimateType": "API-equivalent planning estimate, not actual platform usage or invoice",
        "providers": providers, "phases": rows, "totals": totals,
        "assumptions": [
            "All API input is priced as cache-miss standard processing; no batch, cache, long-context, regional or priority adjustment is assumed.",
            "Token volumes are engineering planning estimates for equivalent prompt/tool/report work; tokenizer and retry differences can materially change usage.",
            "Model output quality and tool reliability are not assumed equivalent. Both workflows still require qualified human review and physical/native-tool evidence.",
            "The exchange rate is a round budgeting assumption, not a live foreign-exchange quote.",
        ],
        "excluded": ["CAD/EDA licenses and workstation", "web search, image or other tool fees", "prototype parts, PCB/PCBA, freight, fixtures and rework", "RF/EMC/battery/regulatory laboratories", "qualified sign-off, installer and flight-integrator fees", "taxes and supplier margins"],
        "releaseLocks": RELEASE_LOCKS,
    }


def build_status(blockers: dict[str, Any], firmware_files: list[Path]) -> dict[str, Any]:
    host_path = MAGIC_WAND / "firmware" / "host-review-evidence.json"
    host = load_json(host_path) if host_path.is_file() else None
    host_summary = None
    firmware_status = "source_contract_package_present_but_no_host_or_target_build_evidence"
    if host is not None:
        results = host["results"]
        host_summary = {
            "path": repo_path(host_path),
            "compileAndLink": results["compile_and_link"],
            "ctest": results["ctest"],
            "targetCompile": results["target_compile"],
            "claimLimits": host["claim_limits"],
        }
        firmware_status = "host_c11_compile_and_contract_smoke_passed_but_no_target_build_flash_hil_or_security_review"
    return {
        "schema": "aicad_magic_wand_integration_status_v1", "projectId": "MW-PROTOTYPE-001", "revision": "A",
        "overallStatus": "review_only_pre_evt_open_blockers",
        "openBlockerCount": len(blockers["blockers"]),
        "domainStatus": {
            "mechanical": "native_parts_and_portable_drawings_reviewed_but_assembly_material_and_manufacturing_gates_open",
            "electronics": "logical_connectivity_only_no_native_kicad_erc_drc_cam_or_bench_evidence",
            "firmware": firmware_status,
            "system": "traceable_review_package_complete_but_evt_dvt_pvt_and_independent_release_gates_open",
        },
        "firmwareEvidenceFiles": [repo_path(path) for path in firmware_files],
        "firmwareHostReview": host_summary,
        "canDo": ["requirements and interface review", "mechanical STEP/DXF quote-only DFM discussion", "KiCad capture planning from connectivity tables", "host-side firmware contract review", "EVT/DVT/PVT planning and rough budgeting"],
        "cannotDo": ["claim factory or production readiness", "fabricate PCBs from this package", "claim ERC/DRC, target firmware, HIL, RF, structural, battery or regulatory pass", "switch mains directly", "control drone arming, propulsion or primary flight functions"],
        "releaseLocks": RELEASE_LOCKS,
    }


def markdown_outputs(status: dict[str, Any], trace: dict[str, Any], interfaces: dict[str, Any], factory: dict[str, Any], cost: dict[str, Any]) -> dict[str, str]:
    trace_rows = "\n".join(f"| {row['id']} | {row['category']} | {row['sourceStatus']} | {row['verificationState']} | {', '.join(row['openBlockerIds'])} |" for row in trace["requirements"])
    interface_rows = "\n".join(f"| {row['id']} | {row['producer']} → {row['consumer']} | {row['safeState']} | {row['status']} |" for row in interfaces["interfaces"])
    stage_rows = "\n".join(f"| {stage['stage']} | {item['id']} | {item['requiredEvidence']} | {item['status']} |" for stage in factory["stages"] for item in stage["items"])
    cost_rows = "\n".join(
        f"| {row['phase']} | {row['estimatedInputTokens']:,} | {row['estimatedOutputTokens']:,} | ¥{row['humanOnlyCostCny']['low']:,}–¥{row['humanOnlyCostCny']['high']:,} | ¥{row['apiTokenOnlyCost']['openai']['cny']:.2f} | ¥{row['apiTokenOnlyCost']['deepseek']['cny']:.2f} | ¥{row['requiredHumanReviewAfterAiCostCny']['low']:,}–¥{row['requiredHumanReviewAfterAiCostCny']['high']:,} |"
        for row in cost["phases"]
    )
    readme = f"""# 魔法棒系统整合审查包（Rev A）

状态：**{status['overallStatus']}**。本目录把机械、电子、固件和系统需求串成一份可审计的 EVT 前审查包；它不是工厂生产放行包。

## 一眼结论

- 可做：需求/接口审查、机械 STEP/DXF 询价与 DFM 讨论、KiCad 录入准备、主机侧固件契约审查、EVT→DVT→PVT 规划和粗算。
- 不可做：PCB 投板、生产放行、直接市电控制、无人机武装/动力/主飞控，或宣称 ERC/DRC、目标固件、HIL、RF、结构、锂电和法规已经通过。
- 当前开放阻塞项：{status['openBlockerCount']} 个；所有授权锁保持关闭，`reviewOnly=true`。
- 浏览器总览：`system-review-overview.svg`。所有注释位于边框内，电源/RF/安全/普通信号采用不同线宽和线型。

## 交付索引

- `integration-status.json`：可做/不可做和各域状态；
- `system-interface-control.json` / `.md`：wand↔receiver、机械↔PCB、电源、RF、press-to-arm、安全输出边界；
- `system-traceability.json`：SYS-001..012 原文级追溯；
- `combined-bom.json` / `.csv`：机械+电子合并 BOM，未询价单价保持 `null`/空白；
- `system-fmea.json`：系统 FMEA；
- `evt-dvt-pvt-plan.json` / `.md`：阶段门和工厂打样/询价边界；
- `rough-cost-estimate.json` / `.md`：人工、OpenAI API、DeepSeek API 粗算；
- `system-blockers.json`：源域阻塞项与系统级阻塞项；
- `delivery-manifest.json`：真实 path/size/SHA-256 清单。

## SYS-001..012 总览

| ID | 类别 | 源状态 | 当前验证状态 | 开放阻塞 |
|---|---|---|---|---|
{trace_rows}

## 放行声明

机械包虽有实际 SolidWorks 零件重开证据，仍缺侧孔、原生装配干涉、材料/结构和制造图闭环；电子包只有逻辑连接意图，没有原生 KiCad、ERC/DRC、CAM 或板级实测；固件没有目标构建、烧录、HIL 或独立安全审查。因此整机只能作为 review-only 的 EVT 输入。

## 复现

在仓库根目录执行：

```powershell
python projects/magic-wand/integration/build_package.py --check
python tests/test_magic_wand_integration_package.py
```
"""
    interface_md = f"""# 系统方框与接口控制

权威坐标：机械 A 基准为后端盖外平面 Z=0，B 为整机轴线，单位 mm。SVG 为审查视图，不是原理图、PCB 或装配 BREP。

```mermaid
flowchart LR
  ARM[recessed press-to-arm] --> WMCU[wand NINA-B302]
  IMU[LSM6DSV16X] --> WMCU
  PWR[USB-C + protected 1S LiPo\nBQ25185 + TPS63900] --> WMCU
  WMCU -. authenticated BLE .-> RMCU[receiver NINA-B302]
  RMCU --> LOGIC[UART / PWM AUX]
  RMCU --> ISO[isolated open collector]
  RMCU --> LOAD[5-12 V low-side SELV]
  ISO -. SELV control only .-> RELAY[external certified relay]
  LOGIC -. non-flight-critical .-> FC[autopilot AUX/telemetry]
```

| 接口 | 方向 | 安全状态/边界 | 当前状态 |
|---|---|---|---|
{interface_rows}

所有接口的完整约束和证据路径见 `system-interface-control.json`。任何表中“blocked/pending/external specialist”都不能被下游测试或视觉审查补偿。
"""
    factory_md = f"""# EVT → DVT → PVT 与工厂打样清单

当前门：**{factory['currentGate']}**。机械文件仅可用于带 REVIEW ONLY 标识的询价/DFM 讨论；电子文件禁止投板。

| 阶段 | ID | 必需证据 | 状态 |
|---|---|---|---|
{stage_rows}

## 工厂询价边界

- 可发：`evt-dvt-pvt-plan.json` 列出的五个机械参考文件，且只用于报价与 DFM 意见；
- 不可发作生产依据：任何电子 CSV、概念方框、未绑定原生特征的便携图或固件骨架；
- 必须回填：假定材料/工艺/公差、最小批量、单价阶梯、模具/治具、检测能力、交期和偏差；
- 投板前硬门：原生 KiCad、同行 pin/footprint 审查、零未解决 ERC/DRC、完整 CAM/PTH/NPTH 和同版 BOM/CPL；
- 每个阶段只凭实际证据关闭，不得用“计划完成”代替测试结果。
"""
    cost_md = f"""# 粗略成本对比（API 等价估算）

价目快照：2026-08-21；币种人民币；预算汇率 1 USD = ¥{cost['usdToCnyPlanningRate']:.2f}。这不是桌面会话账单，也不代表不同模型能力等价。

| 工作段 | 输入 token | 输出 token | 纯人工 | OpenAI gpt-5.6-terra API | DeepSeek v4-pro API | AI 后仍需人工复核 |
|---|---:|---:|---:|---:|---:|---:|
{cost_rows}
| **合计** | **{cost['totals']['estimatedInputTokens']:,}** | **{cost['totals']['estimatedOutputTokens']:,}** | **¥{cost['totals']['humanOnlyCostCny']['low']:,}–¥{cost['totals']['humanOnlyCostCny']['high']:,}** | **¥{cost['totals']['apiTokenOnlyCostCny']['openai']:.2f}** | **¥{cost['totals']['apiTokenOnlyCostCny']['deepseek']:.2f}** | **¥{cost['totals']['requiredHumanReviewAfterAiCostCny']['low']:,}–¥{cost['totals']['requiredHumanReviewAfterAiCostCny']['high']:,}** |

OpenAI 采用标准处理输入 $2.00/M、输出 $12.00/M；DeepSeek 采用 cache-miss 输入 $0.435/M、输出 $0.87/M。来源 URL 与全部假设/不含项见 `rough-cost-estimate.json`。API token 很便宜，但原生工具、工程复核、样机、实验室和合规成本才是主要成本，不能删掉。
"""
    return {"README.md": readme, "system-interface-control.md": interface_md, "evt-dvt-pvt-plan.md": factory_md, "rough-cost-estimate.md": cost_md}


def svg_text() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xhtml="http://www.w3.org/1999/xhtml" viewBox="0 0 1600 1000" role="img" aria-labelledby="svg-title svg-desc">
  <title id="svg-title">Magic wand system and release review overview</title>
  <desc id="svg-desc">Review-only system interface diagram. Power, RF, safety and signal paths use different line weights and dash patterns.</desc>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker>
    <style>
      :root { color-scheme: light; }
      .canvas { fill:#f5f7fb; }
      .panel { fill:#ffffff; stroke:#26364d; stroke-width:3; }
      .node.titlebox rect { fill:#13243a; stroke:#13243a; stroke-width:3; }
      .node rect { fill:#ffffff; stroke:#26364d; stroke-width:3; rx:14; }
      .node.mechanical rect { fill:#eef4ff; stroke:#245ea8; stroke-width:4; }
      .node.electronics rect { fill:#effbf5; stroke:#217a4b; stroke-width:4; }
      .node.external rect { fill:#fff8e8; stroke:#9a6712; stroke-width:4; stroke-dasharray:12 7; }
      .node.blocker rect { fill:#fff0f1; stroke:#ad2532; stroke-width:5; }
      .boxtext { font: 18px/1.18 "Segoe UI", "Microsoft YaHei", sans-serif; color:#15243a; box-sizing:border-box; padding:4px 8px; overflow:hidden; }
      .boxtext strong { font-size:20px; }
      .small { font-size:15px; line-height:1.18; }
      .titlebox .boxtext { padding:3px 8px; }
      .white { color:#ffffff; }
      .path { fill:none; marker-end:url(#arrow); }
      .power { stroke:#d47b00; stroke-width:7; }
      .rf { stroke:#6b42c1; stroke-width:5; stroke-dasharray:16 9; }
      .safety { stroke:#c12f3c; stroke-width:6; stroke-dasharray:14 6 3 6; }
      .signal { stroke:#2a6f98; stroke-width:3; }
      .mechanical-link { stroke:#526579; stroke-width:4; stroke-dasharray:3 7; }
    </style>
  </defs>
  <rect class="canvas" x="0" y="0" width="1600" height="1000"/>
  <g class="node titlebox" data-node-id="TITLE"><rect x="40" y="28" width="1520" height="86"/><foreignObject x="58" y="38" width="1484" height="66"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext white"><strong>魔法棒系统 / 整机审查总览 · Rev A</strong><br/><span class="small">REVIEW ONLY · PRE-EVT · 所有制造/投板/生产授权锁关闭</span></xhtml:div></foreignObject></g>

  <path class="path safety" d="M 350 296 L 455 296"/>
  <path class="path signal" d="M 350 425 L 455 425"/>
  <path class="path power" d="M 350 580 L 455 580"/>
  <path class="path mechanical-link" d="M 350 725 L 455 725"/>
  <path class="path rf" d="M 785 385 L 900 385"/>
  <path class="path signal" d="M 1230 286 L 1320 286"/>
  <path class="path signal" d="M 1230 385 L 1320 385"/>
  <path class="path power" d="M 1230 494 L 1320 494"/>
  <path class="path safety" d="M 1480 385 L 1510 385 L 1510 760 L 1230 760"/>

  <g class="node mechanical" data-node-id="MECH"><rect x="55" y="150" width="295" height="118"/><foreignObject x="70" y="165" width="265" height="88"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>机械包</strong><br/><span class="small">315 mm · Ø27 grip · 190 mm GFRP<br/>4 个原生零件；无 SLDASM/干涉结论</span></xhtml:div></foreignObject></g>
  <g class="node mechanical" data-node-id="ARM"><rect x="55" y="285" width="295" height="118"/><foreignObject x="70" y="300" width="265" height="88"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>Press-to-arm</strong><br/><span class="small">Z=72 ±0.5 mm · recessed ≥0.6 mm<br/>侧孔 BREP 尚缺；连续按住才允许</span></xhtml:div></foreignObject></g>
  <g class="node electronics" data-node-id="IMU"><rect x="55" y="420" width="295" height="108"/><foreignObject x="70" y="435" width="265" height="78"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>LSM6DSV16X</strong><br/><span class="small">相对姿态/短窗手势<br/>不声称绝对位置或精确 3D 轨迹</span></xhtml:div></foreignObject></g>
  <g class="node electronics" data-node-id="POWER"><rect x="55" y="545" width="295" height="128"/><foreignObject x="70" y="560" width="265" height="98"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>Wand 电源</strong><br/><span class="small">USB-C 5 V sink → BQ25185<br/>protected 1S LiPo + NTC<br/>TPS63900 → 3.3 V</span></xhtml:div></foreignObject></g>
  <g class="node mechanical" data-node-id="RFMECH"><rect x="55" y="690" width="295" height="118"/><foreignObject x="70" y="705" width="265" height="88"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>RF 机械边界</strong><br/><span class="small">非导电后端 · Z=5..30 keepout<br/>最终 PCB/手握/壳体 RF 实测未做</span></xhtml:div></foreignObject></g>

  <g class="node electronics" data-node-id="WANDMCU"><rect x="455" y="225" width="330" height="510"/><foreignObject x="475" y="245" width="290" height="470"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>Wand NINA-B302 / nRF52840</strong><br/><br/><span class="small">输入：专用 ARM_N、IMU I²C/INT、充电状态<br/><br/>输出：DRV2605L haptic、状态反馈、BLE 命令<br/><br/>安全契约：低置信度无动作；松手撤销；stuck-low 报错；会话/方向/设备/序列绑定<br/><br/><b>未闭环：</b>目标编译、烧录、HIL、packet capture、安全评审</span></xhtml:div></foreignObject></g>

  <g class="node electronics" data-node-id="RXMCU"><rect x="900" y="225" width="330" height="510"/><foreignObject x="920" y="245" width="290" height="470"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>Receiver NINA-B302 / nRF52840</strong><br/><br/><span class="small">BLE 1M + LE Secure Connections<br/>应用层 AES-CCM + monotonic anti-replay<br/><br/>仅在 ARM lease、fresh command、allow-list 和认证全部成立时输出<br/><br/>boot/reset/brownout/watchdog/link loss → 全输出 inactive / high-Z<br/><br/><b>未闭环：</b>KiCad、ERC/DRC、CAM、板测与 HIL</span></xhtml:div></foreignObject></g>

  <g class="node external" data-node-id="LOGIC"><rect x="1320" y="225" width="230" height="105"/><foreignObject x="1333" y="238" width="204" height="79"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext small"><strong>UART / PWM AUX</strong><br/>3.3/5 V VREF · signal only</xhtml:div></foreignObject></g>
  <g class="node external" data-node-id="ISO"><rect x="1320" y="345" width="230" height="105"/><foreignObject x="1333" y="358" width="204" height="79"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext small"><strong>Isolated OC</strong><br/>floating C/E · ≤10 mA target</xhtml:div></foreignObject></g>
  <g class="node external" data-node-id="LOAD"><rect x="1320" y="465" width="230" height="105"/><foreignObject x="1333" y="478" width="204" height="79"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext small"><strong>SELV low-side</strong><br/>5–12 V · 1 A provisional</xhtml:div></foreignObject></g>
  <g class="node external" data-node-id="MAINS"><rect x="1320" y="595" width="230" height="120"/><foreignObject x="1333" y="608" width="204" height="94"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext small"><strong>外部 certified relay</strong><br/>只接低压控制；市电完全在产品外</xhtml:div></foreignObject></g>
  <g class="node external" data-node-id="DRONE"><rect x="1320" y="720" width="230" height="120"/><foreignObject x="1333" y="733" width="204" height="94"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext small"><strong>Autopilot AUX</strong><br/>非飞行关键；禁止武装/动力/主飞控</xhtml:div></foreignObject></g>

  <g class="node blocker" data-node-id="BLOCKERS"><rect x="455" y="770" width="775" height="150"/><foreignObject x="475" y="790" width="735" height="110"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext"><strong>系统级硬阻塞</strong><br/><span class="small">无原生装配干涉 · 无最终材料/结构 · 无 KiCad/ERC/DRC/CAM · 无目标固件/HIL/security · 无最终 RF/热/电池/法规 · 无独立放行</span></xhtml:div></foreignObject></g>
  <g class="node" data-node-id="LEGEND"><rect x="55" y="835" width="295" height="150"/><foreignObject x="70" y="850" width="265" height="120"><xhtml:div xmlns="http://www.w3.org/1999/xhtml" class="boxtext small"><strong>线型图例</strong><br/>粗橙实线 = power<br/>紫虚线 = authenticated RF<br/>红点划粗线 = safety<br/>蓝细实线 = ordinary signal</xhtml:div></foreignObject></g>
</svg>
"""


def generate(check: bool = False) -> list[str]:
    for path in SOURCE_FILES:
        if not path.is_file():
            raise FileNotFoundError(path)
    electronics_files = authored_files(MAGIC_WAND / "electronics")
    firmware_files = authored_files(MAGIC_WAND / "firmware")
    if not electronics_files:
        raise FileNotFoundError("electronics source package is absent")
    if not firmware_files:
        raise FileNotFoundError("firmware source package is absent")

    blockers = build_blockers(firmware_files)
    firmware_paths = [repo_path(path) for path in firmware_files]
    trace = build_trace({row["id"] for row in blockers["blockers"]}, firmware_paths)
    interfaces = build_interfaces(firmware_paths)
    bom, bom_csv = build_bom()
    fmea = build_fmea()
    factory = build_factory_plan()
    cost = build_cost()
    status = build_status(blockers, firmware_files)

    content: dict[str, str] = {
        "integration-status.json": json_text(status),
        "system-blockers.json": json_text(blockers),
        "system-traceability.json": json_text(trace),
        "system-interface-control.json": json_text(interfaces),
        "combined-bom.json": json_text(bom),
        "combined-bom.csv": bom_csv,
        "system-fmea.json": json_text(fmea),
        "evt-dvt-pvt-plan.json": json_text(factory),
        "rough-cost-estimate.json": json_text(cost),
        "system-review-overview.svg": svg_text(),
    }
    content.update(markdown_outputs(status, trace, interfaces, factory, cost))

    changed: list[str] = []
    for name, text in content.items():
        path = PACKAGE / name
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != text:
            if check:
                raise RuntimeError(f"stale generated integration artifact: {path}")
            path.write_text(text, encoding="utf-8", newline="")
            changed.append(name)

    source_inputs = [*SOURCE_FILES, *electronics_files, *firmware_files]
    deliverables = [PACKAGE / "build_package.py", *(PACKAGE / name for name in sorted(content))]
    manifest = {
        "schema": "aicad_magic_wand_integration_delivery_manifest_v1", "projectId": "MW-PROTOTYPE-001", "revision": "A",
        "status": "review_only_hash_closure_not_release",
        "root": repo_path(REPO_ROOT),
        "sourceInputs": [file_record(path, "source_evidence") for path in sorted(set(source_inputs))],
        "deliverables": [file_record(path, "integration_deliverable") for path in deliverables],
        "selfHashPolicy": {"deliveryManifestExcluded": True, "reason": "A file cannot contain a stable SHA-256 of itself; every other integration deliverable is bound."},
        "releaseLocks": RELEASE_LOCKS,
    }
    manifest_text = json_text(manifest)
    manifest_path = PACKAGE / "delivery-manifest.json"
    current_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
    if current_manifest != manifest_text:
        if check:
            raise RuntimeError(f"stale generated integration artifact: {manifest_path}")
        manifest_path.write_text(manifest_text, encoding="utf-8", newline="")
        changed.append("delivery-manifest.json")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check the magic-wand integration review package")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = generate(check=args.check)
    print(json.dumps({"ok": True, "check": args.check, "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
