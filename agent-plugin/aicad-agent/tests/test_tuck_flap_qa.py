from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aicad_tuck_flap_qa.py"
SPEC = importlib.util.spec_from_file_location("aicad_tuck_flap_qa", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def line(entity_id, start, end, purpose):
    return {
        "id": entity_id,
        "type": "line",
        "purpose": purpose,
        "reasoning": f"{purpose} is fixed by the face contract.",
        "start": {"point": list(start)},
        "construction": {"kind": "to_point", "target": {"point": list(end)}},
        "constraints": [
            {"kind": "start_offset", "target": "origin", "dx": start[0], "dy": start[1]},
            {"kind": "length", "value": ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5},
        ],
    }


def plan_payload(bad_profile=False):
    if bad_profile:
        bottom = {"free_l": (0, 0), "free_r": (200, 0), "root_l": (5, 15), "root_r": (195, 15)}
        top = {"free_l": (0, 330), "free_r": (200, 330), "root_l": (5, 315), "root_r": (195, 315)}
    else:
        bottom = {"free_l": (5, 0), "free_r": (193.5, 0), "root_l": (0, 15), "root_r": (198.5, 15)}
        top = {"free_l": (5, 330), "free_r": (193.5, 330), "root_l": (0, 315), "root_r": (198.5, 315)}
    steps = [line("ORIGIN_BOOTSTRAP", (0, 0), (5, 0), "temporary origin protocol line")]
    steps.extend([
        line("CUT_BOTTOM_TONGUE_FREE", bottom["free_l"], bottom["free_r"], "bottom tongue free edge"),
        line("CUT_BOTTOM_TONGUE_RIGHT", bottom["free_r"], bottom["root_r"], "bottom tongue right bevel"),
        line("SLOT_BOTTOM_MAIN_RIGHT", bottom["root_r"], (198.5, 135), "bottom main right edge"),
        line("CUT_BOTTOM_MAIN_LEFT", (0, 135), bottom["root_l"], "bottom main left edge"),
        line("CUT_BOTTOM_TONGUE_LEFT", bottom["root_l"], bottom["free_l"], "bottom tongue left bevel"),
        line("CREASE_BOTTOM_MAIN_ROOT", (0, 135), (198.5, 135), "bottom main root fold"),
        line("CREASE_BOTTOM_TONGUE", bottom["root_l"], bottom["root_r"], "bottom tongue fold"),
        line("SLOT_TOP_MAIN_RIGHT", (198.5, 195), top["root_r"], "top main right edge"),
        line("CUT_TOP_TONGUE_RIGHT", top["root_r"], top["free_r"], "top tongue right bevel"),
        line("CUT_TOP_TONGUE_FREE", top["free_r"], top["free_l"], "top tongue free edge"),
        line("CUT_TOP_TONGUE_LEFT", top["free_l"], top["root_l"], "top tongue left bevel"),
        line("CUT_TOP_MAIN_LEFT", top["root_l"], (0, 195), "top main left edge"),
        line("CREASE_TOP_MAIN_ROOT", (0, 195), (198.5, 195), "top main root fold"),
        line("CREASE_TOP_TONGUE", top["root_l"], top["root_r"], "top tongue fold"),
    ])
    return {
        "schema_version": "2.0",
        "drawing": {"name": "test_straight_tuck", "units": "mm", "origin": [0, 0], "tolerance": 1e-6},
        "steps": steps,
    }


def contract():
    common = {
        "rootFoldId": "CREASE_{position}_MAIN_ROOT",
        "mainLeftEdgeId": "CUT_{position}_MAIN_LEFT",
        "mainRightEdgeId": "SLOT_{position}_MAIN_RIGHT",
        "tongueFoldId": "CREASE_{position}_TONGUE",
        "tongueLeftBevelId": "CUT_{position}_TONGUE_LEFT",
        "tongueRightBevelId": "CUT_{position}_TONGUE_RIGHT",
        "tongueFreeEdgeId": "CUT_{position}_TONGUE_FREE",
    }
    flaps = []
    for position, sign in (("BOTTOM", -1), ("TOP", 1)):
        flaps.append({
            "id": f"{position}_MAIN_FLAP",
            "position": position.lower(),
            "outwardSign": sign,
            **{key: value.format(position=position) for key, value in common.items()},
        })
    return {
        "schema": "aicad_tuck_flap_face_contract_v1",
        "style": "straight_tuck_end",
        "toleranceMm": 1e-6,
        "originBootstrap": {"id": "ORIGIN_BOOTSTRAP", "production": False},
        "parameters": {
            "panelLengthMm": 200,
            "panelWidthMm": 120,
            "rootReliefWidthMm": 3,
            "usableRootWidthMm": 198.5,
            "mainFlapDepthMm": 120,
            "mainFlapTaperEachSideMm": 0,
            "tongueDepthMm": 15,
            "tongueTaperEachSideMm": 5,
            "tongueRootWidthMm": 198.5,
            "tongueFreeWidthMm": 188.5,
        },
        "flaps": flaps,
        "locks": {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True},
    }


class TuckFlapQaTests(unittest.TestCase):
    def test_rejects_inward_waist_and_outward_flared_tongue(self):
        compiled = MODULE.compile_plan(plan_payload(bad_profile=True))
        report = MODULE.evaluate(compiled, contract())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["no_unparameterized_main_flap_waist"])
        self.assertFalse(report["checks"]["tongue_tapers_inward_toward_free_edge"])
        self.assertFalse(report["checks"]["every_combined_main_flap_and_tongue_is_convex"])

    def test_accepts_untapered_main_flap_and_inward_tapered_tongue(self):
        compiled = MODULE.compile_plan(plan_payload(bad_profile=False))
        report = MODULE.evaluate(compiled, contract())
        self.assertEqual(report["status"], "pass", report["failureReasons"])
        for flap in report["flaps"]:
            self.assertEqual(flap["metricsMm"]["mainLeftTaper"], 0)
            self.assertEqual(flap["metricsMm"]["mainRightTaper"], 0)
            self.assertEqual(flap["metricsMm"]["tongueLeftTaper"], 5)
            self.assertEqual(flap["metricsMm"]["tongueRightTaper"], 5)


if __name__ == "__main__":
    unittest.main()
