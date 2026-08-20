from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aicad import provider


def draft() -> dict:
    return {
        "name": "adapter-smoke",
        "units": "mm",
        "entities": [{
            "type": "line", "purpose": "baseline", "reasoning": "origin anchor",
            "x1": 0, "y1": 0, "x2": 10, "y2": 0,
            "cx": None, "cy": None, "radius": None,
            "start_angle_deg": None, "end_angle_deg": None,
        }],
    }


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class ProviderAdapterTests(unittest.TestCase):
    def test_openai_response_usage_is_retained_without_prompt(self) -> None:
        payload = {
            "id": "resp_test",
            "output_text": json.dumps(draft()),
            "usage": {
                "input_tokens": 100, "input_tokens_details": {"cached_tokens": 20},
                "output_tokens": 50, "total_tokens": 150,
            },
        }
        with patch.object(provider, "load_config", return_value={
            "provider": "openai", "model": "gpt-5.4-mini",
            "base_url": "https://api.openai.com/v1", "timeout_seconds": 10,
        }), patch.object(provider, "get_api_key", return_value="secret"), patch.object(
            provider.urllib.request, "urlopen", return_value=FakeResponse(payload)
        ):
            result = provider.generate_plan_with_usage("draw baseline", "openai")
        ledger = result["runLedger"]
        self.assertEqual(ledger["responseId"], "resp_test")
        self.assertEqual(ledger["usage"]["cacheMissInputTokens"], 80)
        self.assertNotIn("draw baseline", json.dumps(ledger))
        self.assertFalse(ledger["promptStored"])

    def test_deepseek_uses_official_chat_endpoint_and_cache_usage(self) -> None:
        payload = {
            "id": "ds_test",
            "choices": [{"message": {"content": json.dumps(draft())}}],
            "usage": {
                "prompt_tokens": 100, "prompt_cache_hit_tokens": 70,
                "prompt_cache_miss_tokens": 30, "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        captured: dict[str, object] = {}

        def urlopen(request: object, timeout: float) -> FakeResponse:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse(payload)

        with patch.object(provider, "load_config", return_value={
            "provider": "deepseek", "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com", "timeout_seconds": 10,
        }), patch.object(provider, "get_api_key", return_value="secret"), patch.object(
            provider.urllib.request, "urlopen", side_effect=urlopen
        ):
            result = provider.generate_plan_with_usage("draw baseline", "deepseek")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(result["runLedger"]["usage"]["cachedInputTokens"], 70)
        self.assertEqual(result["provider"], "deepseek")

    def test_explicit_deepseek_uses_safe_defaults_when_not_selected_in_config(self) -> None:
        payload = {
            "choices": [{"message": {"content": json.dumps(draft())}}],
            "usage": {
                "prompt_tokens": 2, "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 2, "completion_tokens": 1,
            },
        }
        captured: dict[str, str] = {}

        def urlopen(request: object, timeout: float) -> FakeResponse:
            captured["url"] = request.full_url
            captured["model"] = json.loads(request.data.decode("utf-8"))["model"]
            return FakeResponse(payload)

        with patch.object(provider, "load_config", return_value={
            "provider": "offline", "model": "gpt-5.4-mini",
            "base_url": "https://api.openai.com/v1", "timeout_seconds": 10,
        }), patch.object(provider, "get_api_key", return_value="secret"), patch.object(
            provider.urllib.request, "urlopen", side_effect=urlopen
        ):
            provider.generate_plan_with_usage("draw baseline", "deepseek")
        self.assertEqual(captured, {
            "url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-v4-flash",
        })


if __name__ == "__main__":
    unittest.main()
