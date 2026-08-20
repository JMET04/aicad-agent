from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aicad.costing import (
    estimate_cost,
    PRICE_CATALOG_VERSION,
    normalize_deepseek_usage,
    normalize_openai_usage,
    offline_usage,
)


class ProviderCostingTests(unittest.TestCase):
    def test_offline_cost_is_exact_zero_but_tokens_are_not_fake_zero(self) -> None:
        usage = offline_usage()
        self.assertIsNone(usage["inputTokens"])
        self.assertEqual(estimate_cost("offline", "", usage)["amount"], "0.00000000")

    def test_openai_usage_separates_cached_and_uncached_tokens(self) -> None:
        usage = normalize_openai_usage({"usage": {
            "input_tokens": 10_000,
            "input_tokens_details": {"cached_tokens": 8_000, "cache_write_tokens": 0},
            "output_tokens": 2_000,
            "output_tokens_details": {"reasoning_tokens": 700},
            "total_tokens": 12_000,
        }})
        self.assertEqual(usage["cacheMissInputTokens"], 2_000)
        self.assertEqual(usage["reasoningTokens"], 700)
        cost = estimate_cost("openai", "gpt-5.4-mini", usage)
        self.assertEqual(cost["status"], "exact_from_response_and_snapshot")
        self.assertEqual(cost["amount"], "0.01110000")

    def test_current_gpt_5_6_terra_snapshot_uses_reduced_price(self) -> None:

        usage = normalize_openai_usage({"usage": {
            "input_tokens": 10_000,
            "input_tokens_details": {"cached_tokens": 8_000},
            "output_tokens": 2_000,
        }})
        cost = estimate_cost("openai", "gpt-5.6-terra", usage)
        self.assertEqual(PRICE_CATALOG_VERSION, "2026-08-21")
        self.assertEqual(cost["amount"], "0.02960000")
        self.assertIn("gpt-5.6-terra", cost["priceSource"])

    def test_gpt_5_6_cache_writes_are_separated_and_billed(self) -> None:
        usage = normalize_openai_usage({"usage": {
            "input_tokens": 10_000,
            "input_tokens_details": {
                "cached_tokens": 4_000,
                "cache_write_tokens": 3_000,
            },
            "output_tokens": 2_000,
        }})
        self.assertEqual(usage["cachedInputTokens"], 4_000)
        self.assertEqual(usage["cacheWriteInputTokens"], 3_000)
        self.assertEqual(usage["cacheMissInputTokens"], 3_000)
        cost = estimate_cost("openai", "gpt-5.6-terra", usage)
        self.assertEqual(cost["amount"], "0.03830000")
        self.assertEqual(
            cost["pricingAdjustments"]["cacheWriteInputMultiplier"], "1.25"
        )

    def test_gpt_5_6_long_context_multiplier_is_applied(self) -> None:
        usage = normalize_openai_usage({"usage": {
            "input_tokens": 300_000,
            "input_tokens_details": {
                "cached_tokens": 0,
                "cache_write_tokens": 0,
            },
            "output_tokens": 100_000,
        }})
        cost = estimate_cost("openai", "gpt-5.6-terra", usage)
        self.assertEqual(cost["amount"], "3.00000000")
        self.assertTrue(cost["pricingAdjustments"]["longContextApplied"])

    def test_deepseek_v4_flash_uses_distinct_cache_prices(self) -> None:
        usage = normalize_deepseek_usage({"usage": {
            "prompt_tokens": 10_000,
            "prompt_cache_hit_tokens": 8_000,
            "prompt_cache_miss_tokens": 2_000,
            "completion_tokens": 2_000,
            "total_tokens": 12_000,
        }})
        cost = estimate_cost("deepseek", "deepseek-v4-flash", usage)
        self.assertEqual(cost["amount"], "0.00086240")
        self.assertIn("deepseek.com", cost["priceSource"])

    def test_missing_usage_or_unknown_price_stays_unknown(self) -> None:
        usage = normalize_deepseek_usage({})
        self.assertEqual(usage["status"], "unknown")
        self.assertIsNone(estimate_cost("deepseek", "deepseek-v4-flash", usage)["amount"])
        known_usage = normalize_openai_usage({"usage": {"input_tokens": 1, "output_tokens": 1}})
        self.assertIsNone(estimate_cost("openai", "future-model", known_usage)["amount"])

    def test_deepseek_inconsistent_cache_totals_are_rejected(self) -> None:
        usage = normalize_deepseek_usage({"usage": {
            "prompt_tokens": 10,
            "prompt_cache_hit_tokens": 8,
            "prompt_cache_miss_tokens": 3,
            "completion_tokens": 2,
        }})
        self.assertEqual(usage["status"], "unknown")
        self.assertIn("does_not_equal", usage["reason"])


if __name__ == "__main__":
    unittest.main()
