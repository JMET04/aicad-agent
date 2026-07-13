from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .engine import PlanError
from .natural import UnsupportedRequest, draft_to_plan, offline_plan
from .settings import get_api_key, load_config


class ProviderError(PlanError):
    """Raised when a natural-language provider cannot produce a safe plan."""


AI_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "units", "entities"],
    "properties": {
        "name": {"type": "string"},
        "units": {"type": "string", "enum": ["mm", "inch"]},
        "entities": {
            "type": "array", "minItems": 1, "maxItems": 500,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["type", "purpose", "reasoning", "x1", "y1", "x2", "y2", "cx", "cy", "radius", "start_angle_deg", "end_angle_deg"],
                "properties": {
                    "type": {"type": "string", "enum": ["line", "circle", "arc"]},
                    "purpose": {"type": "string"}, "reasoning": {"type": "string"},
                    "x1": {"type": ["number", "null"]}, "y1": {"type": ["number", "null"]},
                    "x2": {"type": ["number", "null"]}, "y2": {"type": ["number", "null"]},
                    "cx": {"type": ["number", "null"]}, "cy": {"type": ["number", "null"]},
                    "radius": {"type": ["number", "null"]},
                    "start_angle_deg": {"type": ["number", "null"]}, "end_angle_deg": {"type": ["number", "null"]},
                },
            },
        },
    },
}


SYSTEM_INSTRUCTIONS = """You convert a Chinese or English 2D CAD request into ordered primitive geometry.
Safety and geometry rules:
- Output only LINE, CIRCLE, and counter-clockwise ARC entities using the supplied schema.
- Use the drawing origin (0,0). The first LINE must start at (0,0); if the drawing is only radial geometry, the first center must be (0,0).
- Draw each boundary in connected order whenever possible. For every entity, explain its purpose and its mathematical relationship to earlier geometry.
- Resolve all coordinates numerically. Never emit text, dimensions, blocks, hatches, splines, 3D entities, commands, code, or file operations.
- For LINE fill x1,y1,x2,y2 and set radial fields null. For CIRCLE fill cx,cy,radius and set other numeric fields null. For ARC also fill start_angle_deg and end_angle_deg.
- Use positive radii, finite coordinates, no duplicate or zero-length entities, and at most 500 entities.
- If units are not stated, use mm. Interpret a diameter as twice the radius.
The result is an untrusted draft and will be independently constrained and validated before CAD execution."""


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for output in payload.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise ProviderError("OpenAI response did not contain structured output text")


def _openai_plan(request: str) -> dict[str, Any]:
    config = load_config()
    api_key = get_api_key()
    if not api_key:
        raise ProviderError("OpenAI API key is not configured; run AICAD_SETUP or use an offline-supported shape")
    endpoint = str(config["base_url"]).rstrip("/") + "/responses"
    parsed_endpoint = urllib.parse.urlparse(endpoint)
    if parsed_endpoint.scheme != "https" and parsed_endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProviderError("OpenAI base URL must use HTTPS unless it targets localhost")
    body = {
        "model": str(config["model"]),
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": request,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 12000,
        "text": {"format": {"type": "json_schema", "name": "aicad_draft", "strict": True, "schema": AI_DRAFT_SCHEMA}},
    }
    http_request = urllib.request.Request(
        endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "AiCadConstraint/1.0"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=float(config["timeout_seconds"])) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        suffix = f": {detail[:300]}" if detail else ""
        raise ProviderError(f"OpenAI request failed with HTTP {exc.code}{suffix}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"OpenAI connection failed: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError("OpenAI returned an unreadable response") from exc
    if not isinstance(payload, dict):
        raise ProviderError("OpenAI returned an invalid response object")
    try:
        draft = json.loads(_extract_output_text(payload))
    except json.JSONDecodeError as exc:
        raise ProviderError("OpenAI structured output was not valid JSON") from exc
    return draft_to_plan(draft)


def generate_plan(request: str, provider: str = "offline") -> tuple[dict[str, Any], str]:
    if provider not in {"auto", "offline", "openai"}:
        raise ProviderError("provider must be auto, offline, or openai")
    if provider in {"auto", "offline"}:
        try:
            return offline_plan(request), "offline"
        except UnsupportedRequest:
            if provider == "offline":
                raise
    return _openai_plan(request), "openai"
