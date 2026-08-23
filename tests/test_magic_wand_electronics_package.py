import csv
import json
import hashlib
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "magic-wand"
ELECTRONICS = PROJECT / "electronics"
FIRMWARE = PROJECT / "firmware"
HOST_EVIDENCE_GENERATOR_PATH = FIRMWARE / "scripts" / "generate_host_review_evidence.py"
HOST_EVIDENCE_GENERATOR = runpy.run_path(str(HOST_EVIDENCE_GENERATOR_PATH))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path):
    return json.loads(read_text(path))


def read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, f"empty CSV: {path}"
    assert all(None not in row for row in rows), f"ragged CSV: {path}"
    return rows


def test_review_package_has_required_source_of_truth_files():
    required = {
        ELECTRONICS / "README.md",
        ELECTRONICS / "review-report.md",
        ELECTRONICS / "native-validation.md",
        ELECTRONICS / "system-architecture.md",
        ELECTRONICS / "interface-control.md",
        ELECTRONICS / "design-calculations.md",
        ELECTRONICS / "evidence-manifest.json",
        ELECTRONICS / "verification-manifest.json",
        ELECTRONICS / "bom.csv",
        ELECTRONICS / "pcb-constraints.json",
        ELECTRONICS / "test-points.csv",
        ELECTRONICS / "fmea.csv",
        ELECTRONICS / "requirements-traceability.csv",
        ELECTRONICS / "bring-up-and-production-test.md",
        FIRMWARE / "host-review-evidence.json",
        HOST_EVIDENCE_GENERATOR_PATH,
        ELECTRONICS / "wand" / "connectivity.csv",
        ELECTRONICS / "receiver" / "connectivity.csv",
        FIRMWARE / "README.md",
        FIRMWARE / "CMakeLists.txt",
        FIRMWARE / "protocol.md",
        FIRMWARE / "state-machine.md",
        FIRMWARE / "gesture-dictionary.yaml",
        FIRMWARE / "include" / "mw_protocol.h",
        FIRMWARE / "include" / "mw_state_machine.h",
        FIRMWARE / "include" / "mw_gesture.h",
        FIRMWARE / "src" / "mw_protocol.c",
        FIRMWARE / "src" / "mw_state_machine.c",
        FIRMWARE / "src" / "mw_gesture.c",
        FIRMWARE / "src" / "main.c",
    }
    missing = sorted(str(path.relative_to(ROOT)) for path in required if not path.is_file())
    assert not missing, f"missing package files: {missing}"


def test_native_tool_blockers_and_no_fabrication_claim():
    report = read_text(ELECTRONICS / "review-report.md")
    verification = read_json(ELECTRONICS / "verification-manifest.json")
    required_blockers = {
        "BLK-EDA-001",
        "BLK-SIM-001",
        "BLK-FW-001",
        "BLK-MECH-001",
        "BLK-SAFE-001",
    }
    assert required_blockers <= set(verification["blockers"])
    assert required_blockers <= {item for item in required_blockers if item in report}
    assert "ENV-KICAD-001" in report
    assert verification["environment"]["kicad_cli"] != "NOT_FOUND"
    assert verification["environment"]["ngspice"] == "NOT_FOUND"
    assert verification["environment"]["arm_none_eabi_gcc"] == "NOT_FOUND"
    assert verification["environment"]["winget"] == "NOT_FOUND"
    assert verification["native_outputs_present"] is True
    assert verification["manufacturing_authorized"] is False
    assert verification["fabrication_authorized"] is False
    assert verification["production_release_eligible"] is False
    assert verification["analyses"]["kicad_erc"] != "NOT_RUN"
    assert verification["analyses"]["kicad_drc"] != "NOT_RUN"
    assert verification["analyses"]["gerber_drill_bom_cpl_native_export"] != "NOT_RUN"

    prohibited_native_suffixes = {
        ".kicad_sch",
        ".kicad_pcb",
        ".gbr",
        ".drl",
        ".pos",
    }
    native_files = [
        path
        for path in ELECTRONICS.rglob("*")
        if path.is_file() and path.suffix.lower() in prohibited_native_suffixes
    ]
    assert len(native_files) > 0  # native KiCad outputs now exist (A1 board + JLC package)
    lowered = report.lower()
    assert "erc passed" not in lowered
    assert "drc passed" not in lowered
    assert "production ready" not in lowered


def test_kicad_1005_recipe_has_exact_gated_exports():
    recipe = read_text(ELECTRONICS / "native-validation.md")
    for token in (
        "10.0.5",
        "--severity-all --exit-code-violations",
        "--schematic-parity",
        "pcb export gerbers",
        "--check-zones",
        "pcb export drill --format excellon",
        "--excellon-separate-th",
        "pcb export pos --format csv --units mm --side both",
        "sch export bom --exclude-dnp",
        "pcb render --width 1600 --height 1200",
        "zero non-excluded errors and zero non-excluded warnings",
        "independent CAM viewer",
    ):
        assert token in recipe


def test_official_evidence_covers_core_parts_and_boundaries():
    manifest = read_json(ELECTRONICS / "evidence-manifest.json")
    ids = {entry["id"] for entry in manifest["evidence"]}
    required_ids = {
        "UBX-NINA-B3-DS-R15",
        "UBX-NINA-B3-SIM-R15",
        "ST-LSM6DSV16X-DS13510-R4",
        "TI-BQ25185-SLUSF65A",
        "TI-TPS63900-SLVSFJ2D",
        "TI-DRV2605L-SLOS854D",
        "TI-TPS62162-SLVSAJ1E",
        "TI-SN74LVC2T45-SCES516N",
        "TOSHIBA-TLP291-SE-DS",
        "TI-CSD17313Q2-SLPS260E",
        "ST-USBLC6-2-DS4260-R7",
        "NORDIC-NRF52840-PS",
        "USBIF-TYPEC-R2-5",
    }
    assert required_ids <= ids
    for entry in manifest["evidence"]:
        assert entry["url"].startswith("https://")
        assert entry["status"] in {"datasheet-checked", "standards-owner-checked"}
        assert entry["claims_checked"]


def test_bom_is_structured_and_contains_required_architecture():
    rows = read_csv(ELECTRONICS / "bom.csv")
    required_columns = {
        "board",
        "refs",
        "qty",
        "manufacturer",
        "mpn",
        "alternate",
        "alternate_qualification",
        "lifecycle_risk",
        "status_source",
    }
    assert required_columns <= set(rows[0])
    assert all(row["manufacturer"] and row["mpn"] for row in rows)
    joined = "\n".join(row["mpn"] for row in rows)
    for mpn in (
        "NINA-B302-00B-00",
        "LSM6DSV16XTR",
        "BQ25185DLHR",
        "TPS63900DSKR",
        "DRV2605LDGSR",
        "TPS62162DSGR",
        "SN74LVC2T45DCUR",
        "CSD17313Q2",
        "TLP291(GB-TP,SE",
    ):
        assert mpn in joined
    nina_rows = [row for row in rows if row["mpn"] == "NINA-B302-00B-00"]
    assert {row["board"] for row in nina_rows} == {"wand", "receiver"}


def test_connectivity_tables_encode_pin_power_and_interface_safety():
    wand_rows = read_csv(ELECTRONICS / "wand" / "connectivity.csv")
    receiver_rows = read_csv(ELECTRONICS / "receiver" / "connectivity.csv")
    wand_text = "\n".join(",".join(row.values()) for row in wand_rows)
    receiver_text = "\n".join(",".join(row.values()) for row in receiver_rows)

    for token in (
        "NINA-B302 internal PIFA",
        "VCC_IO",
        "LSM6DSV16X",
        "BAT_NTC",
        "ARM_N",
        "HAPTIC_P",
        "HAPTIC_N",
        "USB_CC1",
        "USB_CC2",
    ):
        assert token in wand_text
    for token in (
        "VREF_IO",
        "3V3_or_5V",
        "ISO_OC_COL",
        "ISO_OC_EMIT",
        "LOAD_SUPPLY_5_12V",
        "LOAD_DRAIN",
        "Common-ground",
        "selected B302 internal PIFA",
    ):
        assert token in receiver_text
    assert "IO_OE_N" not in receiver_text
    assert "bUSB" not in wand_text + receiver_text
    for forbidden in ("LINE_VAC", "NEUTRAL", "ESC_POWER", "MOTOR_POWER"):
        assert forbidden not in receiver_text


def test_host_review_evidence_generator_manifest_is_complete():
    source_paths = set(HOST_EVIDENCE_GENERATOR["SOURCE_PATHS"])
    expected_ctest_tests = HOST_EVIDENCE_GENERATOR["EXPECTED_CTEST_TESTS"]

    assert HOST_EVIDENCE_GENERATOR["EXPECTED_BUILD_RESULT"] == (
        "PASSED_34_OF_34_BUILD_STEPS"
    )
    assert len(expected_ctest_tests) == 10
    assert expected_ctest_tests[-3:] == (
        "mw_epoch_record_vectors",
        "mw_epoch_store_vectors",
        "mw_target_contract",
    )
    assert len(source_paths) == 52
    assert {
        "../electronics/wand/wand-factory-design.json",
        "target/receiver-effects/src/mw_epoch_record.c",
        "target/receiver-effects/src/mw_epoch_record.h",
        "target/receiver-effects/src/mw_epoch_store.c",
        "target/receiver-effects/src/mw_epoch_store.h",
        "target/receiver-effects/tests/epoch_record_vectors.c",
        "target/receiver-effects/tests/epoch_store_vectors.c",
        "target/zephyr/CMakeLists.txt",
        "target/zephyr/Kconfig",
        "target/zephyr/boards/c08-005.conf",
        "target/zephyr/boards/c08-005.overlay",
        "target/zephyr/boards/ubx_evkninab3_nrf52840.overlay",
        "target/zephyr/prj.conf",
        "target/zephyr/src/main.c",
        "target/zephyr/verify_target_contract.py",
        "tools/export_effect_previews.c",
    } <= source_paths


def test_firmware_security_replay_and_output_ranges_are_fail_closed():
    protocol_h = read_text(FIRMWARE / "include" / "mw_protocol.h")
    protocol_c = read_text(FIRMWARE / "src" / "mw_protocol.c")
    state_h = read_text(FIRMWARE / "include" / "mw_state_machine.h")
    state_c = read_text(FIRMWARE / "src" / "mw_state_machine.c")
    host_test = read_text(FIRMWARE / "src" / "main.c")
    protocol_doc = read_text(FIRMWARE / "protocol.md")

    assert "MW_NONCE_BYTES ((size_t)13)" in protocol_h
    assert "MW_TAG_BYTES ((size_t)16)" in protocol_h
    assert "mw_commit_high_water_fn" in protocol_h
    assert protocol_c.index("commit_high_water(persistence_context") < protocol_c.index(
        "guard->receive_high_water = frame->header.sequence"
    )
    assert "!guard->persistence_ready" in protocol_c
    assert "frame->header.flags != 0U" in protocol_c
    assert "payload_length_is_valid" in protocol_c
    assert "MW_GESTURE_PAYLOAD_PROFILE_MULTICHANNEL_V2" in protocol_h
    assert "mw_replay_guard_set_gesture_profile" in protocol_h
    assert "frame->header.sequence <= guard->receive_high_water" in protocol_c
    assert "LE Secure Connections" in protocol_doc
    assert "out-of-band" in protocol_doc
    assert "AES-128-CCM" in protocol_doc
    assert "Just Works" in protocol_doc

    assert "MW_ARM_LEASE_MS UINT32_C(100)" in state_h
    assert "MW_ARM_LEASE_REFRESH_MS UINT32_C(25)" in state_h
    assert "MW_LINK_LOSS_MS UINT32_C(250)" in state_h
    assert "MW_MAX_OUTPUT_PULSE_MS UINT32_C(500)" in state_h
    assert "argument > 1U" in state_c
    assert "argument == 0U" in state_c
    assert "argument > MW_MAX_OUTPUT_PULSE_MS" in state_c
    assert "MW_CMD_SET_AUX, 2U" in host_test
    assert "MW_CMD_PULSE_LOW_SIDE, 0U" in host_test
    assert "MW_CMD_PULSE_LOW_SIDE, 501U" in host_test
    assert "frame.header.payload_length = 2U" in host_test
    assert "frame.header.flags = 1U" in host_test


    host_evidence = read_json(FIRMWARE / "host-review-evidence.json")
    results = host_evidence["results"]
    expected_sources = set(HOST_EVIDENCE_GENERATOR["SOURCE_PATHS"])
    assert results["compile_and_link"] == HOST_EVIDENCE_GENERATOR["EXPECTED_BUILD_RESULT"]
    assert results["ctest"] == HOST_EVIDENCE_GENERATOR["EXPECTED_CTEST_RESULT"]
    assert results["tests"] == list(HOST_EVIDENCE_GENERATOR["EXPECTED_CTEST_TESTS"])
    assert results["cppcheck"] == HOST_EVIDENCE_GENERATOR["EXPECTED_CPPCHECK_RESULT"]
    assert results["cppcheck_files"] == list(HOST_EVIDENCE_GENERATOR["CPPCHECK_PATHS"])
    assert results["target_compile"].startswith("NOT_RUN")
    assert host_evidence["source_manifest"] == {
        "policy": HOST_EVIDENCE_GENERATOR["SOURCE_MANIFEST_POLICY"],
        "count": len(expected_sources),
        "includes_transitive_ctest_inputs": True,
    }
    assert set(host_evidence["source_sha256"]) == expected_sources
    for relative_path, expected_hash in host_evidence["source_sha256"].items():
        actual_hash = hashlib.sha256((FIRMWARE / relative_path).read_bytes()).hexdigest().upper()
        assert actual_hash == expected_hash
    assert host_evidence["generator"]["script"] == (
        "scripts/generate_host_review_evidence.py"
    )
    assert host_evidence["generator"]["script_sha256"] == hashlib.sha256(
        HOST_EVIDENCE_GENERATOR_PATH.read_bytes()
    ).hexdigest().upper()
    assert any("not cryptography" in item.lower() for item in host_evidence["claim_limits"])

def test_gesture_scope_is_relative_and_low_confidence_rejects():
    architecture = read_text(ELECTRONICS / "system-architecture.md").lower()
    gesture_yaml = read_text(FIRMWARE / "gesture-dictionary.yaml")
    gesture_c = read_text(FIRMWARE / "src" / "mw_gesture.c")
    assert "precise absolute 3d position or trajectory claims out of scope" in architecture
    assert "absolute_position" in gesture_yaml
    assert "exact_free_space_3d_path" in gesture_yaml
    assert "low_confidence_behavior: GESTURE_NONE" in gesture_yaml
    assert "held_out_users_not_random_windows" in gesture_yaml
    assert "A circle is a closed, high-area path in integrated Y/Z angular space" in gesture_c


def test_sys_002_through_sys_012_trace_to_safe_artifacts():
    system = read_json(PROJECT / "system-requirements.json")
    requirements = {item["id"]: item for item in system["requirements"]}
    expected_ids = {f"SYS-{number:03d}" for number in range(2, 13)}
    assert expected_ids <= requirements.keys()
    assert system["status"] == "owner_authorized_prototype_fabrication_physical_and_target_validation_pending"
    locks = system["releaseLocks"]
    assert locks["prototypeOnly"] is True
    assert locks["wandBarePcbTechnicalPackageReady"] is True
    assert locks["printableEnclosureTechnicalPackageReady"] is True
    assert locks["prototypeBarePcbFabricationAuthorized"] is True
    assert locks["prototype3dPrintingAuthorized"] is True
    for key in (
        "systemAccepted",
        "pcbaOrderAuthorized",
        "targetFirmwareReleaseEligible",
        "productionReleaseEligible",
    ):
        assert locks[key] is False

    trace_rows = read_csv(ELECTRONICS / "requirements-traceability.csv")
    trace_ids = {row["requirement_id"] for row in trace_rows}
    assert expected_ids == trace_ids
    trace_text = "\n".join(",".join(row.values()) for row in trace_rows).lower()
    assert "<=100 ms" in trace_text
    assert "<=250 ms" in trace_text
    assert "gesture-dictionary" in trace_text
    assert "absolute position" in requirements["SYS-004"]["requirement"].lower()
    assert "mains conductor" in requirements["SYS-009"]["acceptance"].lower()
    assert "no primary control" in trace_text
    assert "review-only" in trace_text

    interface = read_text(ELECTRONICS / "interface-control.md").lower()
    assert "no mains conductor" in interface
    assert "no esc, battery or motor power" in interface
    assert "non-inverted uart" in interface
    assert "external" in interface and "sbus" in interface


def test_fmea_and_bringup_cover_high_consequence_faults():
    rows = read_csv(ELECTRONICS / "fmea.csv")
    assert len(rows) >= 20
    ids = {row["id"] for row in rows}
    assert {f"FMEA-{number:03d}" for number in range(1, 22)} <= ids
    for row in rows:
        expected_rpn = (
            int(row["severity_1_10"])
            * int(row["occurrence_1_10"])
            * int(row["detection_1_10"])
        )
        assert int(row["initial_rpn"]) == expected_rpn
        assert row["controls_or_design_action"]
        assert row["verification"]
    bringup = read_text(ELECTRONICS / "bring-up-and-production-test.md")
    for token in (
        "battery simulator first",
        "No mains conductor",
        "Temperature faults",
        "when either side is absent",
        "interrupted flash write",
        "Proposed manufacturing tests (not yet implemented)",
    ):
        assert token in bringup


if __name__ == "__main__":
    discovered = sorted(
        (name, function)
        for name, function in globals().items()
        if name.startswith("test_") and callable(function)
    )
    for test_name, test_function in discovered:
        test_function()
        print(f"PASS {test_name}")
    print(f"{len(discovered)} contract tests passed")
