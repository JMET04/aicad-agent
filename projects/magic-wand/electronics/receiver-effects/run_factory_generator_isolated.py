#!/usr/bin/env python3
"""Run the reviewed receiver-effects generator into an isolated directory."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generator", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    generator = args.generator.resolve(strict=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("receiver_effects_isolated", generator)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load generator: {generator}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = args.output_dir.resolve()
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
