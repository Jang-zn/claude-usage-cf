"""Tests for pricing module."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_usage.pricing import (
    normalize_model,
    get_pricing_family,
    calculate_cost,
    reset_price_cache,
    _FALLBACK_PRICING,
    _CACHE_PATH,
    _CACHE_TTL,
)
from claude_usage.models import TokenUsage


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset module-level price cache before each test."""
    reset_price_cache()
    yield
    reset_price_cache()


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


class TestCalculateCostFallback:
    """Tests using fallback pricing (LiteLLM DB disabled via mock)."""

    @pytest.fixture(autouse=True)
    def _disable_litellm(self):
        """Force fallback by making _get_litellm_db return None."""
        import claude_usage.pricing as pricing_module
        with patch.object(pricing_module, "_get_litellm_db", return_value=None):
            reset_price_cache()
            yield
            reset_price_cache()

    def test_opus_46_input_1m(self):
        """Opus 4.6: 1M input tokens -> $5.00 (fallback price)."""
        usage = TokenUsage(input_tokens=1_000_000)
        result = calculate_cost("opus-4.6", usage)
        assert result["input_cost"] == pytest.approx(5.00, abs=0.01)

    def test_opus_46_output_1m(self):
        """Opus 4.6: 1M output tokens -> $25.00 (fallback price)."""
        usage = TokenUsage(output_tokens=1_000_000)
        result = calculate_cost("opus-4.6", usage)
        assert result["output_cost"] == pytest.approx(25.00, abs=0.01)

    def test_opus_46_combined(self):
        """Opus 4.6: 1M input + 1M output -> $30.00."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        result = calculate_cost("opus-4.6", usage)
        assert result["input_cost"] == pytest.approx(5.0, abs=0.01)
        assert result["output_cost"] == pytest.approx(25.0, abs=0.01)
        assert result["total"] == pytest.approx(30.0, abs=0.01)

    def test_cache_savings(self):
        usage = TokenUsage(
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=0,
        )
        result = calculate_cost("opus-4.6", usage)
        # Cache read at $0.50/M vs full input at $5.00/M -> savings of $4.50
        assert result["cache_savings"] == pytest.approx(4.50, abs=0.01)

    def test_zero_usage(self):
        usage = TokenUsage()
        result = calculate_cost("sonnet-4.6", usage)
        assert result["total"] == 0.0
        assert result["cache_savings"] == 0.0

    def test_sonnet_pricing(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        result = calculate_cost("sonnet-4.6", usage)
        assert result["input_cost"] == pytest.approx(3.0, abs=0.01)
        assert result["output_cost"] == pytest.approx(15.0, abs=0.01)

    def test_web_search_cost_included(self):
        """web_search_requests billing: $10/1000 requests."""
        usage = TokenUsage(web_search_requests=1000)
        result = calculate_cost("sonnet-4.6", usage)
        assert result["web_search_cost"] == pytest.approx(10.0, abs=0.01)
        assert result["total"] == pytest.approx(10.0, abs=0.01)

    def test_web_search_partial_requests(self):
        """500 web search requests -> $5.00."""
        usage = TokenUsage(web_search_requests=500)
        result = calculate_cost("opus-4.6", usage)
        assert result["web_search_cost"] == pytest.approx(5.0, abs=0.01)

    def test_web_search_zero(self):
        """No web searches -> zero web_search_cost, key still present."""
        usage = TokenUsage(input_tokens=1_000_000)
        result = calculate_cost("sonnet-4.6", usage)
        assert "web_search_cost" in result
        assert result["web_search_cost"] == 0.0

    def test_total_includes_web_search(self):
        """total = token costs + web_search_cost."""
        usage = TokenUsage(input_tokens=1_000_000, web_search_requests=1000)
        result = calculate_cost("sonnet-4.6", usage)
        expected_total = result["input_cost"] + result["web_search_cost"]
        assert result["total"] == pytest.approx(expected_total, abs=0.01)


class TestLiteLLMFallback:
    """Tests that verify network failure falls back to hardcoded prices."""

    def test_network_failure_uses_fallback(self):
        """When urllib.request.urlopen raises, fallback table is used."""
        import urllib.request
        with patch("urllib.request.urlopen", side_effect=OSError("network unreachable")):
            with patch.object(Path, "exists", return_value=False):
                reset_price_cache()
                usage = TokenUsage(input_tokens=1_000_000)
                result = calculate_cost("opus-4.6", usage)
                # Should use fallback: $5.00/M for opus input
                assert result["input_cost"] == pytest.approx(5.00, abs=0.01)

    def test_fallback_prices_sanity(self):
        """Fallback table has expected Opus 4.6 prices."""
        assert _FALLBACK_PRICING["opus"]["input"] == pytest.approx(5.00)
        assert _FALLBACK_PRICING["opus"]["output"] == pytest.approx(25.00)
        assert _FALLBACK_PRICING["opus"]["cache_read"] == pytest.approx(0.50)
        assert _FALLBACK_PRICING["opus"]["cache_create"] == pytest.approx(6.25)


class TestLiteLLMCache:
    """Tests for the 24h cache mechanism."""

    def _make_litellm_db(self) -> dict:
        """Minimal LiteLLM DB fixture with claude-opus-4-6 entry."""
        return {
            "claude-opus-4-6": {
                "input_cost_per_token": 5e-6,   # $5/M
                "output_cost_per_token": 25e-6,  # $25/M
                "cache_read_input_token_cost": 0.5e-6,
                "cache_creation_input_token_cost": 6.25e-6,
            },
            "claude-sonnet-4-6": {
                "input_cost_per_token": 3e-6,
                "output_cost_per_token": 15e-6,
                "cache_read_input_token_cost": 0.3e-6,
                "cache_creation_input_token_cost": 3.75e-6,
            },
            "claude-haiku-4-5-20251001": {
                "input_cost_per_token": 1e-6,
                "output_cost_per_token": 5e-6,
                "cache_read_input_token_cost": 0.1e-6,
                "cache_creation_input_token_cost": 1.25e-6,
            },
        }

    def test_fresh_cache_skips_network(self, tmp_path):
        """Cache file within TTL → network not called."""
        import claude_usage.pricing as pricing_module

        cache_file = tmp_path / "model_prices.json"
        cache_file.write_text(json.dumps(self._make_litellm_db()))
        # Set mtime to now (fresh)
        cache_file.touch()

        with patch.object(pricing_module, "_CACHE_PATH", cache_file):
            with patch("urllib.request.urlopen") as mock_urlopen:
                reset_price_cache()
                usage = TokenUsage(input_tokens=1_000_000)
                result = calculate_cost("opus-4.6", usage)
                # Network should NOT have been called
                mock_urlopen.assert_not_called()
                # Price should match the DB
                assert result["input_cost"] == pytest.approx(5.00, abs=0.01)

    def test_stale_cache_triggers_network(self, tmp_path):
        """Cache file older than 24h → network fetch attempted."""
        import claude_usage.pricing as pricing_module

        cache_file = tmp_path / "model_prices.json"
        cache_file.write_text(json.dumps(self._make_litellm_db()))
        # Set mtime to 25 hours ago
        old_mtime = time.time() - (_CACHE_TTL + 3600)
        import os
        os.utime(cache_file, (old_mtime, old_mtime))

        with patch.object(pricing_module, "_CACHE_PATH", cache_file):
            # Mock urlopen to return our DB
            db_bytes = json.dumps(self._make_litellm_db()).encode()
            mock_response = MagicMock()
            mock_response.read.return_value = db_bytes
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
                reset_price_cache()
                usage = TokenUsage(input_tokens=1_000_000)
                calculate_cost("opus-4.6", usage)
                mock_urlopen.assert_called_once()

    def test_litellm_prices_applied(self, tmp_path):
        """Prices from LiteLLM DB are used when cache is fresh."""
        import claude_usage.pricing as pricing_module

        # Use custom prices different from fallback
        custom_db = {
            "claude-opus-4-6": {
                "input_cost_per_token": 10e-6,   # $10/M (custom)
                "output_cost_per_token": 50e-6,
                "cache_read_input_token_cost": 1e-6,
                "cache_creation_input_token_cost": 12.5e-6,
            }
        }
        cache_file = tmp_path / "model_prices.json"
        cache_file.write_text(json.dumps(custom_db))
        cache_file.touch()

        with patch.object(pricing_module, "_CACHE_PATH", cache_file):
            reset_price_cache()
            usage = TokenUsage(input_tokens=1_000_000)
            result = calculate_cost("opus-4.6", usage)
            # Should use custom $10/M, not fallback $5/M
            assert result["input_cost"] == pytest.approx(10.00, abs=0.01)
