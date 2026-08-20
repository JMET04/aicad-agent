from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .engine import PlanError
from .costing import estimate_cost, normalize_deepseek_usage, normalize_openai_usage, offline_usage
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


def _openai_plan_with_run(request: str) -> dict[str, Any]:
    config = load_config()
    api_key = get_api_key("openai")
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
    model = str(config["model"])
    usage = normalize_openai_usage(payload)
    return {
        "plan": draft_to_plan(draft),
        "provider": "openai",
        "model": model,
        "runLedger": {
            "schema": "aicad_provider_run_v1",
            "status": "success",
            "provider": "openai",
            "model": model,
            "requestSha256": hashlib.sha256(request.encode("utf-8")).hexdigest(),
            "responseId": payload.get("id") if isinstance(payload.get("id"), str) else None,
            "recordedAt": datetime.now(timezone.utc).isoformat(),
            "usage": usage,
            "cost": estimate_cost("openai", model, usage),
            "promptStored": False,
            "invoiceIsSourceOfTruth": True,
        },
    }


def _openai_plan(request: str) -> dict[str, Any]:
    """Compatibility wrapper for callers that only need the constrained plan."""
    return _openai_plan_with_run(request)["plan"]


def _extract_deepseek_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError("DeepSeek response did not contain a completion choice")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("DeepSeek response did not contain JSON output text")
    return content


def _deepseek_plan_with_run(request: str) -> dict[str, Any]:
    config = load_config()
    api_key = get_api_key("deepseek")
    if not api_key:
        raise ProviderError("DeepSeek API key is not configured; use DEEPSEEK_API_KEY or provider setup")
    selected = config.get("provider") == "deepseek"
    base_url = str(config["base_url"]) if selected else "https://api.deepseek.com"
    model = str(config["model"]) if selected else "deepseek-v4-flash"
    endpoint = base_url.rstrip("/") + "/chat/completions"
    parsed_endpoint = urllib.parse.urlparse(endpoint)
    if parsed_endpoint.scheme != "https" and parsed_endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProviderError("DeepSeek base URL must use HTTPS unless it targets localhost")
    schema_text = json.dumps(AI_DRAFT_SCHEMA, ensure_ascii=False, separators=(",", ":"))
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS + "\nReturn one JSON object matching this JSON Schema: " + schema_text},
            {"role": "user", "content": request},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "max_tokens": 12000,
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
        raise ProviderError(f"DeepSeek request failed with HTTP {exc.code}{suffix}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"DeepSeek connection failed: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError("DeepSeek returned an unreadable response") from exc
    if not isinstance(payload, dict):
        raise ProviderError("DeepSeek returned an invalid response object")
    try:
        draft = json.loads(_extract_deepseek_text(payload))
    except json.JSONDecodeError as exc:
        raise ProviderError("DeepSeek JSON output was not valid JSON") from exc
    usage = normalize_deepseek_usage(payload)
    return {
        "plan": draft_to_plan(draft),
        "provider": "deepseek",
        "model": model,
        "runLedger": {
            "schema": "aicad_provider_run_v1",
            "status": "success",
            "provider": "deepseek",
            "model": model,
            "requestSha256": hashlib.sha256(request.encode("utf-8")).hexdigest(),
            "responseId": payload.get("id") if isinstance(payload.get("id"), str) else None,
            "recordedAt": datetime.now(timezone.utc).isoformat(),
            "usage": usage,
            "cost": estimate_cost("deepseek", model, usage),
            "promptStored": False,
            "invoiceIsSourceOfTruth": True,
        },
    }


def _deepseek_plan(request: str) -> dict[str, Any]:
    return _deepseek_plan_with_run(request)["plan"]


def generate_plan_with_usage(request: str, provider: str = "offline") -> dict[str, Any]:
    if provider not in {"auto", "offline", "openai", "deepseek"}:
        raise ProviderError("provider must be auto, offline, openai, or deepseek")
    if provider in {"auto", "offline"}:
        try:
            plan = offline_plan(request)
            usage = offline_usage()
            return {
                "plan": plan,
                "provider": "offline",
                "model": None,
                "runLedger": {
                    "schema": "aicad_provider_run_v1",
                    "status": "success",
                    "provider": "offline",
                    "model": None,
                    "requestSha256": hashlib.sha256(request.encode("utf-8")).hexdigest(),
                    "responseId": None,
                    "recordedAt": datetime.now(timezone.utc).isoformat(),
                    "usage": usage,
                    "cost": estimate_cost("offline", "", usage),
                    "promptStored": False,
                    "invoiceIsSourceOfTruth": False,
                },
            }
        except UnsupportedRequest:
            if provider == "offline":
                raise
            configured = str(load_config().get("provider", "openai"))
            provider = configured if configured in {"openai", "deepseek"} else "openai"
    if provider == "deepseek":
        return _deepseek_plan_with_run(request)
    return _openai_plan_with_run(request)


def generate_plan(request: str, provider: str = "offline") -> tuple[dict[str, Any], str]:
    result = generate_plan_with_usage(request, provider)
    return result["plan"], str(result["provider"])
