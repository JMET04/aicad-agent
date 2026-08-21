import copy
import hashlib
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ELECTRONICS_SOURCE = REPO / "projects" / "magic-wand" / "electronics"
sys.path.insert(0, str(ELECTRONICS_SOURCE))

import factory_emit  # noqa: E402
from build_factory_package import BOARDS, absolute_pads  # noqa: E402


def artifact(path: Path, relative: str) -> dict:
    payload = path.read_bytes()
    return {
        "path": relative,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
    }


def write_fixture(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@contextmanager
def raises(error_type, match: str):
    try:
        yield
    except error_type as exc:
        assert re.search(match, str(exc)), str(exc)
    else:
        raise AssertionError(f"expected {error_type.__name__}: {match}")


def test_frozen_routes_require_canonical_regular_files_and_exact_hashes(tmp_path, monkeypatch):
    project = tmp_path / "magic-wand"
    electronics = project / "electronics"
    receiver_dir = electronics / "receiver"
    receiver_dir.mkdir(parents=True)
    monkeypatch.setattr(factory_emit, "ROOT", electronics)

    board = next(item for item in BOARDS if item.name == "receiver")
    pads = absolute_pads(board)
    board_path = receiver_dir / "receiver.kicad_pcb"
    report_path = receiver_dir / "receiver-native-drc.rpt"
    fixture_path = receiver_dir / "receiver-frozen-routes.json"
    board_path.write_bytes(b"canonical receiver board\n")
    report_path.write_bytes(b"Found 0 DRC violations\nFound 0 unconnected pads\nFound 0 Footprint errors\n")

    value = {
        "schema": "aicad.frozen-pcb-routes.v1",
        "status": "DRC_FROZEN",
        "revision": "TEST",
        "board": "receiver",
        "boardDimensionsMm": [50, 42, 1.6],
        "sourceDesign": factory_emit.route_source_design(board, pads),
        "sourceBoard": artifact(
            board_path, "electronics/receiver/receiver.kicad_pcb"
        ),
        "nativeDrc": {
            **artifact(
                report_path, "electronics/receiver/receiver-native-drc.rpt"
            ),
            "violations": 0,
            "unconnected": 0,
            "footprintErrors": 0,
            "exclusions": 0,
            "suppressions": 0,
        },
        "routes": [{"net": "GND", "layer": "F.Cu", "width": 0.2, "points": [[1, 1], [2, 2]]}],
        "vias": [],
    }
    write_fixture(fixture_path, value)
    routes, vias, failures, source = factory_emit.resolved_routes(board, pads)
    assert routes == value["routes"]
    assert vias == []
    assert failures == []
    assert source["nativeDrc"] == value["nativeDrc"]

    pending = copy.deepcopy(value)
    pending["status"] = "VALIDATED_ROUTE_PENDING_CANONICAL_NATIVE_DRC"
    write_fixture(fixture_path, pending)
    with raises(ValueError, match="unfrozen"):
        factory_emit.resolved_routes(board, pads)

    backslash = copy.deepcopy(value)
    backslash["sourceBoard"]["path"] = r"electronics\receiver\receiver.kicad_pcb"
    write_fixture(fixture_path, backslash)
    with raises(ValueError, match="non-canonical"):
        factory_emit.resolved_routes(board, pads)

    wrong_binding_path = receiver_dir / "other.kicad_pcb"
    wrong_binding_path.write_bytes(board_path.read_bytes())
    wrong_binding = copy.deepcopy(value)
    wrong_binding["sourceBoard"] = artifact(
        wrong_binding_path, "electronics/receiver/other.kicad_pcb"
    )
    write_fixture(fixture_path, wrong_binding)
    with raises(ValueError, match="canonical board"):
        factory_emit.resolved_routes(board, pads)

    absolute = copy.deepcopy(value)
    absolute["sourceBoard"]["path"] = board_path.as_posix()
    write_fixture(fixture_path, absolute)
    with raises(ValueError, match="controlled relative|non-canonical"):
        factory_emit.resolved_routes(board, pads)

    tampered = copy.deepcopy(value)
    write_fixture(fixture_path, tampered)
    board_path.write_bytes(b"tampered receiver board\n")
    with raises(ValueError, match="size/SHA"):
        factory_emit.resolved_routes(board, pads)
