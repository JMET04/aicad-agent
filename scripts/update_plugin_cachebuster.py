from __future__ import annotations

"""Update a local Codex plugin build suffix without touching marketplace.json."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


VERSION_RE = re.compile(
    r"^(?P<base>\d+\.\d+\.\d+)\+codex\.(?P<stamp>\d{14})$"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument(
        "--mirror-manifest", action="append", default=[], type=Path
    )
    parser.add_argument("--timestamp", default="")
    args = parser.parse_args()

    source = args.source_manifest.resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    previous = str(value.get("version", ""))
    match = VERSION_RE.fullmatch(previous)
    if not match:
        raise SystemExit(
            f"unsupported plugin version; expected X.Y.Z+codex.YYYYMMDDHHMMSS: {previous}"
        )
    timestamp = args.timestamp or datetime.now(timezone.utc).strftime(
        "%Y%m%d%H%M%S"
    )
    if not re.fullmatch(r"\d{14}", timestamp):
        raise SystemExit("--timestamp must contain exactly 14 digits")
    if timestamp <= match.group("stamp"):
        raise SystemExit(
            f"cachebuster must increase monotonically: {timestamp} <= {match.group('stamp')}"
        )
    value["version"] = f"{match.group('base')}+codex.{timestamp}"
    destinations = [source, *(path.resolve() for path in args.mirror_manifest)]
    if len(set(destinations)) != len(destinations):
        raise SystemExit("source and mirror manifest paths must be unique")
    for destination in destinations:
        write_json(destination, value)
    hashes = {str(path): sha256(path) for path in destinations}
    if len(set(hashes.values())) != 1:
        raise SystemExit("written plugin manifests are not byte-identical")
    print(
        json.dumps(
            {
                "status": "pass",
                "previousVersion": previous,
                "version": value["version"],
                "marketplaceModified": False,
                "manifests": hashes,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
