#!/usr/bin/env python3
"""Reproduce and verify the Magic Wand host-review evidence record.

The ``record`` mode is the only mode that replaces host-review-evidence.json.
``replay`` runs the same gates without touching that file, while ``check`` only
validates the committed record against the current source tree.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterator, Sequence
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve()
FIRMWARE = SCRIPT.parents[1]
PROJECT = FIRMWARE.parent
DEFAULT_EVIDENCE = FIRMWARE / "host-review-evidence.json"

SCHEMA = "magic_wand_firmware_host_review_evidence_v3"
SOURCE_MANIFEST_POLICY = "explicit_host_build_ctest_and_claim_inputs_v1"
EXPECTED_BUILD_STEPS = 34
EXPECTED_CTEST_TESTS = (
    "mw_host_review",
    "mw_gesture_vectors",
    "mw_target_math",
    "mw_gesture_event_v2_vectors",
    "mw_receiver_runtime_vectors",
    "mw_receiver_multichannel_vectors",
    "mw_pattern_effect_vectors",
    "mw_epoch_record_vectors",
    "mw_epoch_store_vectors",
    "mw_target_contract",
)
EXPECTED_BUILD_RESULT = "PASSED_34_OF_34_BUILD_STEPS"
EXPECTED_CTEST_RESULT = "PASSED_10_OF_10"
EXPECTED_CPPCHECK_RESULT = "PASSED_9_OF_9_SELECTED_RECEIVER_FILES_NO_FINDINGS"
TARGET_COMPILE_RESULT = (
    "NOT_RUN_NO_PINNED_NRF_CONNECT_SDK_ZEPHYR_WEST_OR_NINA_BOARD_BUILD"
)

# This is deliberately explicit. It binds every host compile input, every
# transitive input read by mw_target_contract, and the documents cited by the
# evidence claims. Paths are relative to FIRMWARE; the one ``..`` entry remains
# inside the Magic Wand project and is read by verify_target_contract.py.
SOURCE_PATHS = tuple(
    sorted(
        {
            "../electronics/wand/wand-factory-design.json",
            "CMakeLists.txt",
            "README.md",
            "RECEIVER_RUNTIME_HIL.md",
            "include/mw_board_pins.h",
            "include/mw_effect_audio.h",
            "include/mw_effect_scheduler.h",
            "include/mw_gesture.h",
            "include/mw_gesture_event_v2.h",
            "include/mw_pattern_renderer.h",
            "include/mw_protocol.h",
            "include/mw_receiver_board_pins.h",
            "include/mw_receiver_multichannel.h",
            "include/mw_receiver_rev_b_pins.h",
            "include/mw_receiver_runtime.h",
            "include/mw_state_machine.h",
            "include/mw_target_math.h",
            "protocol.md",
            "src/main.c",
            "src/mw_effect_audio.c",
            "src/mw_effect_scheduler.c",
            "src/mw_gesture.c",
            "src/mw_gesture_event_v2.c",
            "src/mw_pattern_renderer.c",
            "src/mw_protocol.c",
            "src/mw_receiver_multichannel.c",
            "src/mw_receiver_runtime.c",
            "src/mw_state_machine.c",
            "src/mw_target_math.c",
            "target/receiver-effects/TARGET_INTEGRATION.md",
            "target/receiver-effects/receiver-effects-overlay-contract.yaml",
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
            "tests/gesture_event_v2_vectors.c",
            "tests/gesture_vectors.c",
            "tests/pattern_effect_vectors.c",
            "tests/receiver_multichannel_vectors.c",
            "tests/receiver_runtime_vectors.c",
            "tests/target_math.c",
            "tools/export_effect_previews.c",
        }
    )
)
if len(SOURCE_PATHS) != 52:
    raise RuntimeError(
        f"host-review source manifest must contain 52 paths, got {len(SOURCE_PATHS)}"
    )

# Preserve the historical nine-file receiver static-analysis gate, but make its
# selection explicit for the first time so that 9/9 is independently replayable.
CPPCHECK_PATHS = (
    "src/mw_protocol.c",
    "src/mw_state_machine.c",
    "src/mw_receiver_runtime.c",
    "src/mw_receiver_multichannel.c",
    "src/mw_pattern_renderer.c",
    "src/mw_effect_audio.c",
    "src/mw_effect_scheduler.c",
    "tests/receiver_runtime_vectors.c",
    "tests/receiver_multichannel_vectors.c",
)

CLAIM_LIMITS = (
    "Not an nRF52840 or NINA-B302 target build.",
    "Not a BLE stack, production cryptographic implementation, target timing, "
    "watchdog, GPIO, flash-endurance or power-cut test.",
    "Host copy-decrypt callbacks test transaction plumbing only and are not "
    "cryptography or a security proof.",
    "Host RGB565, preview exports and PCM vectors do not prove GC9A01A SPI "
    "color/order, MAX98357A I2S timing, acoustic volume, EMC, thermal or power behavior.",
    "No receiver-effects KiCad source, ERC/DRC, Gerber, drill, BOM or placement "
    "package is authorized by this evidence.",
    "No wand electronics, mechanical source or fabrication package is in scope.",
)

PINNED_TOOL_PATHS = {
    "cmake": Path("D:/mingw64/mingw64/bin/cmake.exe"),
    "ctest": Path("D:/mingw64/mingw64/bin/ctest.exe"),
    "ninja": Path("D:/mingw64/mingw64/bin/ninja.exe"),
    "compiler": Path("D:/mingw64/bin/gcc.exe"),
    "cppcheck": Path("D:/mingw64/mingw64/bin/cppcheck.exe"),
}


class EvidenceError(RuntimeError):
    """Raised when a replay gate cannot produce trustworthy evidence."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def manifest_path(relative_path: str) -> Path:
    candidate = (FIRMWARE / relative_path).resolve()
    try:
        candidate.relative_to(PROJECT.resolve())
    except ValueError as exc:
        raise EvidenceError(
            f"manifest path escapes the Magic Wand project: {relative_path}"
        ) from exc
    return candidate


def source_hashes() -> dict[str, str]:
    missing = [relative for relative in SOURCE_PATHS if not manifest_path(relative).is_file()]
    if missing:
        raise EvidenceError("missing source manifest files: " + ", ".join(missing))
    return {relative: sha256(manifest_path(relative)) for relative in SOURCE_PATHS}


def resolve_tool(explicit: str | None, name: str) -> Path:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    else:
        candidates.extend((str(PINNED_TOOL_PATHS[name]), name))
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
        discovered = shutil.which(candidate)
        if discovered:
            return Path(discovered).resolve()
    raise EvidenceError(f"required tool not found: {name}; tried {candidates}")


def run_checked(
    args: Sequence[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        rendered = subprocess.list2cmdline(list(args))
        detail = (completed.stdout + completed.stderr)[-6000:]
        raise EvidenceError(f"command failed ({completed.returncode}): {rendered}\n{detail}")
    return completed


def version_from(pattern: str, output: str, label: str) -> str:
    match = re.search(pattern, output, flags=re.IGNORECASE)
    if not match:
        raise EvidenceError(f"could not parse {label} version from: {output.strip()!r}")
    return match.group(1)


def toolchain_record(tools: dict[str, Path]) -> dict[str, object]:
    cmake_output = run_checked((str(tools["cmake"]), "--version")).stdout
    ninja_output = run_checked((str(tools["ninja"]), "--version")).stdout
    compiler_output = run_checked((str(tools["compiler"]), "--version")).stdout
    cppcheck_output = run_checked((str(tools["cppcheck"]), "--version")).stdout
    return {
        "cmake": tools["cmake"].as_posix(),
        "cmake_version": version_from(r"cmake version\s+([^\s]+)", cmake_output, "CMake"),
        "generator": "Ninja",
        "ninja": tools["ninja"].as_posix(),
        "ninja_version": ninja_output.strip(),
        "compiler": tools["compiler"].as_posix(),
        "compiler_id": "GNU",
        "compiler_version": version_from(r"\b(\d+\.\d+\.\d+)\b", compiler_output, "GCC"),
        "cppcheck": tools["cppcheck"].as_posix(),
        "cppcheck_version": version_from(r"Cppcheck\s+([^\s]+)", cppcheck_output, "Cppcheck"),
        "python": Path(sys.executable).resolve().as_posix(),
        "python_version": platform.python_version(),
        "language": "C11",
        "warnings_as_errors": True,
        "warning_flags": [
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wpedantic",
            "-Wconversion",
            "-Wshadow",
        ],
    }


def normalized_command(args: Sequence[str], build_dir: Path) -> str:
    normalized: list[str] = []
    replacements = (
        (str(build_dir.resolve()), "<BUILD_DIR>"),
        (str(FIRMWARE.resolve()), "<FIRMWARE_DIR>"),
    )
    for arg in args:
        value = str(arg)
        for concrete, placeholder in replacements:
            value = value.replace(concrete, placeholder)
            value = value.replace(concrete.replace("\\", "/"), placeholder)
        normalized.append(value.replace("\\", "/"))
    return subprocess.list2cmdline(normalized)


def parse_build_steps(output: str) -> tuple[int, int]:
    progress = [
        (int(match.group(1)), int(match.group(2)))
        for match in re.finditer(r"(?m)^\[(\d+)/(\d+)\]\s", output)
    ]
    if not progress:
        raise EvidenceError("Ninja build output did not contain [step/total] progress")
    return progress[-1]


def parse_ctest_inventory(output: str) -> tuple[str, ...]:
    try:
        document = json.loads(output)
        names = tuple(str(item["name"]) for item in document["tests"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise EvidenceError("could not parse ctest --show-only=json-v1 output") from exc
    return names


def parse_junit(path: Path) -> tuple[int, int, int, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag.endswith("testsuite") else [
        element for element in root if element.tag.endswith("testsuite")
    ]
    if not suites:
        raise EvidenceError("CTest JUnit output contains no testsuite")
    tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    return tests, failures, errors, skipped


def replay(build_dir: Path, tools: dict[str, Path]) -> dict[str, object]:
    hashes_before = source_hashes()
    configure = (
        str(tools["cmake"]),
        "-S",
        str(FIRMWARE),
        "-B",
        str(build_dir),
        "-G",
        "Ninja",
        f"-DCMAKE_C_COMPILER={tools['compiler']}",
        f"-DCMAKE_MAKE_PROGRAM={tools['ninja']}",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        "-DMW_HOST_REVIEW=ON",
    )
    build = (str(tools["cmake"]), "--build", str(build_dir), "--parallel", "1")
    show_tests = (
        str(tools["ctest"]),
        "--test-dir",
        str(build_dir),
        "--show-only=json-v1",
    )
    junit = build_dir / "ctest-junit.xml"
    run_tests = (
        str(tools["ctest"]),
        "--test-dir",
        str(build_dir),
        "--output-on-failure",
        "--output-junit",
        str(junit),
    )
    cppcheck = (
        str(tools["cppcheck"]),
        "--enable=warning,performance,portability",
        "--std=c11",
        "--error-exitcode=1",
        "--inline-suppr",
        "--suppress=missingIncludeSystem",
        "--quiet",
        "-Iinclude",
        "-Itarget/receiver-effects/src",
        *CPPCHECK_PATHS,
    )

    run_checked(configure)
    build_run = run_checked(build)
    completed_steps, total_steps = parse_build_steps(build_run.stdout + build_run.stderr)
    if (completed_steps, total_steps) != (EXPECTED_BUILD_STEPS, EXPECTED_BUILD_STEPS):
        raise EvidenceError(
            "clean host build step count changed: "
            f"expected {EXPECTED_BUILD_STEPS}/{EXPECTED_BUILD_STEPS}, "
            f"got {completed_steps}/{total_steps}"
        )

    inventory = parse_ctest_inventory(run_checked(show_tests).stdout)
    if inventory != EXPECTED_CTEST_TESTS:
        raise EvidenceError(
            "CTest inventory changed: expected "
            f"{EXPECTED_CTEST_TESTS}, got {inventory}"
        )
    ctest_started = time.monotonic()
    run_checked(run_tests)
    ctest_elapsed = round(time.monotonic() - ctest_started, 2)
    tests, failures, errors, skipped = parse_junit(junit)
    if (tests, failures, errors, skipped) != (len(EXPECTED_CTEST_TESTS), 0, 0, 0):
        raise EvidenceError(
            "CTest JUnit result changed: "
            f"tests={tests}, failures={failures}, errors={errors}, skipped={skipped}"
        )

    run_checked(cppcheck, cwd=FIRMWARE)
    toolchain = toolchain_record(tools)
    hashes_after = source_hashes()
    if hashes_after != hashes_before:
        changed = sorted(
            path
            for path in SOURCE_PATHS
            if hashes_after.get(path) != hashes_before.get(path)
        )
        raise EvidenceError("source changed during evidence replay: " + ", ".join(changed))

    return {
        "schema": SCHEMA,
        "artifact_status": "HOST_VERIFIED_TARGET_AND_HIL_BLOCKED",
        "observed_at": datetime.now(timezone.utc).date().isoformat(),
        "scope": (
            "Portable C11 protocol/profile gates, target math, eight gesture classes, "
            "fail-closed receiver runtime, eight isolated device/session/channel slots, "
            "persistent epoch record/store vectors, output-owner arbitration, 240x240 "
            "RGB565 renderer, deterministic volume-limited procedural audio and effect "
            "scheduler, plus the deterministic preview exporter build."
        ),
        "claim_limits": list(CLAIM_LIMITS),
        "generator": {
            "script": "scripts/generate_host_review_evidence.py",
            "script_sha256": sha256(SCRIPT),
            "source_manifest_policy": SOURCE_MANIFEST_POLICY,
        },
        "toolchain": toolchain,
        "commands": [
            normalized_command(configure, build_dir),
            normalized_command(build, build_dir),
            normalized_command(show_tests, build_dir),
            normalized_command(run_tests, build_dir),
            normalized_command(cppcheck, build_dir),
        ],
        "results": {
            "configure": "PASSED",
            "compile_and_link": EXPECTED_BUILD_RESULT,
            "ctest": EXPECTED_CTEST_RESULT,
            "ctest_elapsed_seconds": ctest_elapsed,
            "tests": list(EXPECTED_CTEST_TESTS),
            "cppcheck": EXPECTED_CPPCHECK_RESULT,
            "cppcheck_files": list(CPPCHECK_PATHS),
            "target_compile": TARGET_COMPILE_RESULT,
        },
        "source_manifest": {
            "policy": SOURCE_MANIFEST_POLICY,
            "count": len(SOURCE_PATHS),
            "includes_transitive_ctest_inputs": True,
        },
        "source_sha256": hashes_after,
        "receiver_handoff": "RECEIVER_RUNTIME_HIL.md",
        "receiver_effects_contract": (
            "../electronics/receiver-effects/receiver-effects-contract.json"
        ),
        "reproduction_note": (
            "Run this generator in record mode. It uses a fresh out-of-tree build, "
            "pinned tools, an explicit source manifest and atomic evidence replacement; "
            "the result remains host evidence, not a target image or fabrication artifact."
        ),
    }


def check_evidence(path: Path) -> list[str]:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read evidence: {exc}"]

    errors: list[str] = []

    def expect(label: str, actual: object, expected: object) -> None:
        if actual != expected:
            errors.append(f"{label}: expected {expected!r}, got {actual!r}")

    results = evidence.get("results", {})
    manifest = evidence.get("source_manifest", {})
    generator = evidence.get("generator", {})
    expect("schema", evidence.get("schema"), SCHEMA)
    expect("results.configure", results.get("configure"), "PASSED")
    expect("results.compile_and_link", results.get("compile_and_link"), EXPECTED_BUILD_RESULT)
    expect("results.ctest", results.get("ctest"), EXPECTED_CTEST_RESULT)
    expect("results.tests", results.get("tests"), list(EXPECTED_CTEST_TESTS))
    expect("results.cppcheck", results.get("cppcheck"), EXPECTED_CPPCHECK_RESULT)
    expect("results.cppcheck_files", results.get("cppcheck_files"), list(CPPCHECK_PATHS))
    target_compile = results.get("target_compile", "")
    if not isinstance(target_compile, str) or not target_compile.startswith("NOT_RUN"):
        errors.append("results.target_compile must start with NOT_RUN")
    expect("source_manifest.policy", manifest.get("policy"), SOURCE_MANIFEST_POLICY)
    expect("source_manifest.count", manifest.get("count"), len(SOURCE_PATHS))
    expect(
        "source_manifest.includes_transitive_ctest_inputs",
        manifest.get("includes_transitive_ctest_inputs"),
        True,
    )
    expect("generator.script", generator.get("script"), "scripts/generate_host_review_evidence.py")
    expect("generator.script_sha256", generator.get("script_sha256"), sha256(SCRIPT))
    expect(
        "generator.source_manifest_policy",
        generator.get("source_manifest_policy"),
        SOURCE_MANIFEST_POLICY,
    )

    declared_hashes = evidence.get("source_sha256", {})
    if not isinstance(declared_hashes, dict):
        errors.append("source_sha256 must be an object")
    else:
        declared = set(declared_hashes)
        expected = set(SOURCE_PATHS)
        if declared != expected:
            missing = sorted(expected - declared)
            extra = sorted(declared - expected)
            errors.append(f"source_sha256 set mismatch: missing={missing}, extra={extra}")
        try:
            current_hashes = source_hashes()
        except EvidenceError as exc:
            errors.append(str(exc))
        else:
            for relative_path in sorted(declared & expected):
                expect(
                    f"source_sha256[{relative_path}]",
                    declared_hashes[relative_path],
                    current_hashes[relative_path],
                )

    claim_limits = evidence.get("claim_limits", [])
    if not isinstance(claim_limits, list) or not any(
        isinstance(item, str) and "not cryptography" in item.lower()
        for item in claim_limits
    ):
        errors.append("claim_limits must contain a 'not cryptography' limitation")
    return errors


def atomic_write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def fresh_build_directory(requested: Path | None) -> Iterator[Path]:
    if requested is None:
        with tempfile.TemporaryDirectory(prefix="mw-host-review-") as temporary:
            yield Path(temporary).resolve()
        return

    build_dir = requested.expanduser().resolve()
    try:
        build_dir.relative_to(FIRMWARE.resolve())
    except ValueError:
        pass
    else:
        raise EvidenceError("build directory must be outside the firmware source tree")
    if build_dir.exists() and any(build_dir.iterdir()):
        raise EvidenceError(f"explicit build directory is not empty: {build_dir}")
    build_dir.mkdir(parents=True, exist_ok=True)
    yield build_dir


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("manifest", "check", "replay", "record"))
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--candidate-output", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--cmake")
    parser.add_argument("--ctest")
    parser.add_argument("--ninja")
    parser.add_argument("--compiler")
    parser.add_argument("--cppcheck")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.mode == "manifest":
            print(
                json.dumps(
                    {
                        "build_steps": EXPECTED_BUILD_STEPS,
                        "ctest_tests": list(EXPECTED_CTEST_TESTS),
                        "cppcheck_files": list(CPPCHECK_PATHS),
                        "source_count": len(SOURCE_PATHS),
                        "source_paths": list(SOURCE_PATHS),
                    },
                    indent=2,
                )
            )
            return 0

        evidence_path = args.evidence.expanduser().resolve()
        if args.mode == "check":
            errors = check_evidence(evidence_path)
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print(f"PASS: host-review evidence matches {len(SOURCE_PATHS)} source inputs")
            return 0

        if args.mode == "record" and args.candidate_output:
            raise EvidenceError("--candidate-output is only valid with replay")
        tools = {
            name: resolve_tool(getattr(args, name), name)
            for name in ("cmake", "ctest", "ninja", "compiler", "cppcheck")
        }
        with fresh_build_directory(args.build_dir) as build_dir:
            candidate = replay(build_dir, tools)

        if args.mode == "record":
            atomic_write_json(evidence_path, candidate)
            output_path = evidence_path
        else:
            output_path = None
            if args.candidate_output:
                output_path = args.candidate_output.expanduser().resolve()
                atomic_write_json(output_path, candidate)

        summary = {
            "status": "PASSED",
            "mode": args.mode,
            "compile_and_link": candidate["results"]["compile_and_link"],
            "ctest": candidate["results"]["ctest"],
            "cppcheck": candidate["results"]["cppcheck"],
            "source_count": len(candidate["source_sha256"]),
            "output": output_path.as_posix() if output_path else None,
        }
        print(json.dumps(summary, indent=2))
        return 0
    except (EvidenceError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
