"""Provider usage normalization and auditable per-drawing cost estimates.

The catalog is intentionally small and date-stamped. Unknown models or
missing API usage remain unknown instead of being reported as zero. Invoice
data remains the financial source of truth.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping


PRICE_CATALOG_VERSION = "2026-08-21"
PRICE_CATALOG: dict[tuple[str, str], dict[str, Any]] = {
    ("deepseek", "deepseek-v4-flash"): {
        "inputCacheHitUsdPerMillion": "0.0028",
        "inputCacheMissUsdPerMillion": "0.14",
        "outputUsdPerMillion": "0.28",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "effectiveOn": "2026-08-20",
    },
    ("deepseek", "deepseek-v4-pro"): {
        "inputCacheHitUsdPerMillion": "0.003625",
        "inputCacheMissUsdPerMillion": "0.435",
        "outputUsdPerMillion": "0.87",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "effectiveOn": "2026-08-20",
    },
    ("openai", "gpt-5.4-mini"): {
        "inputCacheHitUsdPerMillion": "0.075",
        "inputCacheMissUsdPerMillion": "0.75",
        "outputUsdPerMillion": "4.50",
        "source": "https://platform.openai.com/pricing",
        "effectiveOn": "2026-08-20",
    },
    ("openai", "gpt-5.4"): {
        "inputCacheHitUsdPerMillion": "0.25",
        "inputCacheMissUsdPerMillion": "2.50",
        "outputUsdPerMillion": "15.00",
        "source": "https://platform.openai.com/pricing",
        "effectiveOn": "2026-08-20",
    },
    ("openai", "gpt-5.6-luna"): {
        "inputCacheHitUsdPerMillion": "0.02",
        "inputCacheMissUsdPerMillion": "0.20",
        "outputUsdPerMillion": "1.20",
        "source": "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        "effectiveOn": "2026-08-21",
        "cacheWriteInputMultiplier": "1.25",
        "longContextThresholdInputTokens": 272000,
        "longContextInputMultiplier": "2.0",
        "longContextOutputMultiplier": "1.5",
    },
    ("openai", "gpt-5.6-terra"): {
        "inputCacheHitUsdPerMillion": "0.20",
        "inputCacheMissUsdPerMillion": "2.00",
        "outputUsdPerMillion": "12.00",
        "source": "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        "effectiveOn": "2026-08-21",
        "cacheWriteInputMultiplier": "1.25",
        "longContextThresholdInputTokens": 272000,
        "longContextInputMultiplier": "2.0",
        "longContextOutputMultiplier": "1.5",
    },
    ("openai", "gpt-5.6-sol"): {
        "inputCacheHitUsdPerMillion": "0.50",
        "inputCacheMissUsdPerMillion": "5.00",
        "outputUsdPerMillion": "30.00",
        "source": "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        "effectiveOn": "2026-08-21",
        "cacheWriteInputMultiplier": "1.25",
        "longContextThresholdInputTokens": 272000,
        "longContextInputMultiplier": "2.0",
        "longContextOutputMultiplier": "1.5",
    },
}


def unavailable_usage(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "source": "api_response_unavailable",
        "inputTokens": None,
        "cachedInputTokens": None,
        "cacheWriteInputTokens": None,
        "cacheMissInputTokens": None,
        "outputTokens": None,
        "reasoningTokens": None,
        "totalTokens": None,
        "reason": reason,
    }


def offline_usage() -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "source": "offline_deterministic_generator",
        "inputTokens": None,
        "cachedInputTokens": None,
        "cacheWriteInputTokens": None,
        "cacheMissInputTokens": None,
        "outputTokens": None,
        "reasoningTokens": None,
        "totalTokens": None,
        "reason": "no_remote_model_call",
    }


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def normalize_openai_usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("usage")
    if not isinstance(raw, Mapping):
        return unavailable_usage("response_missing_usage")
    input_tokens = _nonnegative_int(raw.get("input_tokens"))
    output_tokens = _nonnegative_int(raw.get("output_tokens"))
    total_tokens = _nonnegative_int(raw.get("total_tokens"))
    input_details = raw.get("input_tokens_details")
    output_details = raw.get("output_tokens_details")
    cached = (
        _nonnegative_int(input_details.get("cached_tokens"))
        if isinstance(input_details, Mapping)
        else None
    )
    cache_write = (
        _nonnegative_int(input_details.get("cache_write_tokens"))
        if isinstance(input_details, Mapping)
        else None
    )
    reasoning = (
        _nonnegative_int(output_details.get("reasoning_tokens"))
        if isinstance(output_details, Mapping)
        else None
    )
    if input_tokens is None or output_tokens is None:
        return unavailable_usage("response_usage_missing_input_or_output_tokens")

    cached_detail_present = cached is not None
    cache_write_detail_present = cache_write is not None
    if cached is None:
        cached = 0
    if cache_write is None:
        cache_write = 0
    if cached + cache_write > input_tokens:
        return unavailable_usage(
            "cached_or_cache_write_input_exceeds_input_tokens"
        )
    if cached_detail_present and cache_write_detail_present:
        precision = "exact_from_response"
        note = ""
    else:
        precision = "estimated"
        assumptions = []
        if not cached_detail_present:
            assumptions.append("zero cached input")
        if not cache_write_detail_present:
            assumptions.append("zero cache writes")
        note = (
            "input token detail absent; estimate assumes "
            + " and ".join(assumptions)
        )
    return {
        "status": precision,
        "source": "api_response",
        "inputTokens": input_tokens,
        "cachedInputTokens": cached,
        "cacheWriteInputTokens": cache_write,
        "cacheMissInputTokens": input_tokens - cached - cache_write,
        "outputTokens": output_tokens,
        "reasoningTokens": reasoning,
        "totalTokens": (
            total_tokens
            if total_tokens is not None
            else input_tokens + output_tokens
        ),
        "reason": note,
    }


def normalize_deepseek_usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("usage")
    if not isinstance(raw, Mapping):
        return unavailable_usage("response_missing_usage")
    prompt = _nonnegative_int(raw.get("prompt_tokens"))
    output = _nonnegative_int(raw.get("completion_tokens"))
    hit = _nonnegative_int(raw.get("prompt_cache_hit_tokens"))
    miss = _nonnegative_int(raw.get("prompt_cache_miss_tokens"))
    total = _nonnegative_int(raw.get("total_tokens"))
    completion_details = raw.get("completion_tokens_details")
    reasoning = (
        _nonnegative_int(completion_details.get("reasoning_tokens"))
        if isinstance(completion_details, Mapping)
        else None
    )
    if prompt is None or output is None:
        return unavailable_usage(
            "response_usage_missing_prompt_or_completion_tokens"
        )
    if hit is None or miss is None:
        return {
            **unavailable_usage(
                "response_usage_missing_cache_hit_or_miss_tokens"
            ),
            "inputTokens": prompt,
            "outputTokens": output,
            "reasoningTokens": reasoning,
            "totalTokens": total if total is not None else prompt + output,
        }
    if hit + miss != prompt:
        return unavailable_usage(
            "cache_hit_plus_miss_does_not_equal_prompt_tokens"
        )
    return {
        "status": "exact_from_response",
        "source": "api_response",
        "inputTokens": prompt,
        "cachedInputTokens": hit,
        "cacheWriteInputTokens": 0,
        "cacheMissInputTokens": miss,
        "outputTokens": output,
        "reasoningTokens": reasoning,
        "totalTokens": total if total is not None else prompt + output,
        "reason": "",
    }


def estimate_cost(
    provider: str, model: str, usage: Mapping[str, Any]
) -> dict[str, Any]:
    if provider == "offline":
        return {
            "status": "exact",
            "currency": "USD",
            "amount": "0.00000000",
            "catalogVersion": PRICE_CATALOG_VERSION,
            "priceSource": None,
            "reason": "no_remote_model_call",
            "invoiceReconciliationRequired": False,
        }
    price = PRICE_CATALOG.get((provider, model))
    if price is None:
        return {
            "status": "unknown",
            "currency": "USD",
            "amount": None,
            "catalogVersion": PRICE_CATALOG_VERSION,
            "priceSource": None,
            "reason": f"no_price_snapshot_for_{provider}:{model}",
            "invoiceReconciliationRequired": True,
        }
    hit = _nonnegative_int(usage.get("cachedInputTokens"))
    miss = _nonnegative_int(usage.get("cacheMissInputTokens"))
    cache_write = _nonnegative_int(usage.get("cacheWriteInputTokens", 0))
    output = _nonnegative_int(usage.get("outputTokens"))
    if hit is None or miss is None or cache_write is None or output is None:
        return {
            "status": "unknown",
            "currency": "USD",
            "amount": None,
            "catalogVersion": PRICE_CATALOG_VERSION,
            "priceSource": price["source"],
            "reason": "usage_breakdown_incomplete",
            "invoiceReconciliationRequired": True,
        }

    input_total = hit + miss + cache_write
    reported_input = _nonnegative_int(usage.get("inputTokens"))
    if reported_input is not None and reported_input != input_total:
        return {
            "status": "unknown",
            "currency": "USD",
            "amount": None,
            "catalogVersion": PRICE_CATALOG_VERSION,
            "priceSource": price["source"],
            "reason": "input_usage_breakdown_does_not_equal_input_tokens",
            "invoiceReconciliationRequired": True,
        }

    input_multiplier = Decimal("1")
    output_multiplier = Decimal("1")
    threshold = price.get("longContextThresholdInputTokens")
    if isinstance(threshold, int) and input_total > threshold:
        input_multiplier = Decimal(price["longContextInputMultiplier"])
        output_multiplier = Decimal(price["longContextOutputMultiplier"])
    cache_write_multiplier = Decimal(
        price.get("cacheWriteInputMultiplier", "1")
    )
    million = Decimal(1_000_000)
    input_amount = (
        Decimal(hit) * Decimal(price["inputCacheHitUsdPerMillion"])
        + Decimal(miss) * Decimal(price["inputCacheMissUsdPerMillion"])
        + Decimal(cache_write)
        * Decimal(price["inputCacheMissUsdPerMillion"])
        * cache_write_multiplier
    ) / million
    output_amount = (
        Decimal(output) * Decimal(price["outputUsdPerMillion"])
    ) / million
    amount = input_multiplier * input_amount + output_multiplier * output_amount
    status = (
        "exact_from_response_and_snapshot"
        if usage.get("status") == "exact_from_response"
        else "estimated"
    )
    return {
        "status": status,
        "currency": "USD",
        "amount": str(
            amount.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        ),
        "catalogVersion": PRICE_CATALOG_VERSION,
        "priceSource": price["source"],
        "priceEffectiveOn": price["effectiveOn"],
        "pricingAdjustments": {
            "cacheWriteInputMultiplier": str(cache_write_multiplier),
            "longContextThresholdInputTokens": threshold,
            "longContextApplied": input_multiplier != Decimal("1"),
            "inputMultiplier": str(input_multiplier),
            "outputMultiplier": str(output_multiplier),
        },
        "reason": "reconcile_with_provider_invoice",
        "invoiceReconciliationRequired": True,
    }


def price_catalog_is_current(as_of: date | None = None) -> bool:
    """A small guard that forces an explicit refresh after 90 days."""
    target = as_of or date.today()
    snapshot = date.fromisoformat(PRICE_CATALOG_VERSION)
    return 0 <= (target - snapshot).days <= 90
