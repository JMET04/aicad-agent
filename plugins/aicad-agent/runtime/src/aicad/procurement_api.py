"""Object/path wrapper shared by the CLI and the packaged MCP server."""
from pathlib import Path
from typing import Any

from .manufacturing_api import _load_value
from .procurement import validate_procurement_preflight


def validate_procurement_value(value: Any, evidence_root: str | Path | None = None) -> dict[str, Any]:
    document, source = _load_value(value)
    root = evidence_root or (source.parent if source else None)
    return validate_procurement_preflight(document, root)
