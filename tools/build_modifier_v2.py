from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicad.viewmap import build_multiview_review


def main() -> int:
    plan = json.loads((ROOT / "examples" / "mounting_plate_3d.plan.json").read_text(encoding="utf-8"))
    output = ROOT / "build" / "modifier-ui-v2"
    result = build_multiview_review(plan, "3d", "mechanical", output, "mounting_plate_v2")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
