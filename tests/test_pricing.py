"""Tests for pricing module."""

import pytest

from claude_usage.pricing import (
    normalize_model,
    get_pricing_family,
    calculate_cost,
)
from claude_usage.models import TokenUsage


class TestNormalizeModel:
    def test_known_models(self):
        assert normalize_model("claude-opus-4-6") == "opus-4.6"
        assert normalize_model("claude-sonnet-4-6") == "sonnet-4.6"
        assert normalize_model("claude-sonnet-4-5-20250929") == "sonnet-4.5"
        assert normalize_model("claude-haiku-4-5-20251001") == "haiku-4.5"

    def test_unknown_model_strips_prefix(self):
        result = normalize_model("claude-new-model")
        assert result == "new-model"

    def test_unknown_model_with_date_suffix(self):
        result = normalize_model("claude-test-20260101")
        assert result == "test"

    def test_passthrough(self):
        assert normalize_model("custom-model") == "custom-model"


class TestGetPricingFamily:
    def test_known_families(self):
        assert get_pricing_family("opus-4.6") == "opus"
        assert get_pricing_family("sonnet-4.6") == "sonnet"
        assert get_pricing_family("sonnet-4.5") == "sonnet"
        assert get_pricing_family("haiku-4.5") == "haiku"

    def test_fallback_from_name(self):
        assert get_pricing_family("opus-99") == "opus"
        assert get_pricing_family("sonnet-future") == "sonnet"

    def test_unknown_defaults_to_sonnet(self):
        assert get_pricing_family("unknown-model") == "sonnet"


class TestCalculateCost:
    def test_opus_cost(self):
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        result = calculate_cost("opus-4.6", usage)
        assert result["input_cost"] == pytest.approx(15.0)
        assert result["output_cost"] == pytest.approx(75.0)
        assert result["total"] == pytest.approx(90.0)

    def test_cache_savings(self):
        usage = TokenUsage(
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=0,
        )
        result = calculate_cost("opus-4.6", usage)
        # Cache read at 1.50/M vs full input at 15.00/M -> savings of 13.50
        assert result["cache_savings"] == pytest.approx(13.50)

    def test_zero_usage(self):
        usage = TokenUsage()
        result = calculate_cost("sonnet-4.6", usage)
        assert result["total"] == 0.0
        assert result["cache_savings"] == 0.0

    def test_sonnet_pricing(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        result = calculate_cost("sonnet-4.6", usage)
        assert result["input_cost"] == pytest.approx(3.0)
        assert result["output_cost"] == pytest.approx(15.0)
