"""Model pricing constants and cost calculation.

Dynamic pricing is fetched from LiteLLM's model price database (24h TTL).
Falls back to hardcoded table on network failure or cache miss.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from .models import TokenUsage

# ── LiteLLM price DB ─────────────────────────────────────────────────────────
_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_CACHE_PATH = Path.home() / ".cache" / "claude-usage" / "model_prices.json"
_CACHE_TTL = 86_400  # 24 hours

# Web search pricing (per 1000 requests, USD)
WEB_SEARCH_COST_PER_1K = 10.0

# ── Fallback hardcoded prices ($/M tokens) ───────────────────────────────────
_FALLBACK_PRICING: dict[str, dict[str, float]] = {
    "opus": {
        "input": 5.00,
        "output": 25.00,
        "cache_read": 0.50,
        "cache_create": 6.25,
    },
    "sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_create": 3.75,
    },
    "haiku": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_create": 1.25,
    },
}

# Model name normalization: raw API model ID -> short name
MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4-6": "opus-4.6",
    "claude-sonnet-4-6": "sonnet-4.6",
    "claude-sonnet-4-5-20250929": "sonnet-4.5",
    "claude-haiku-4-5-20251001": "haiku-4.5",
}

# Short name -> pricing family
MODEL_FAMILY: dict[str, str] = {
    "opus-4.6": "opus",
    "sonnet-4.6": "sonnet",
    "sonnet-4.5": "sonnet",
    "haiku-4.5": "haiku",
}

# ── LiteLLM key fragments for each family (family-level fallback) ────────────
_FAMILY_FRAGMENTS: dict[str, list[str]] = {
    "opus": ["claude-opus-4"],
    "sonnet": ["claude-sonnet-4"],
    "haiku": ["claude-haiku-4"],
}


def _short_to_litellm_fragment(model_short: str) -> str:
    """Convert short name like 'opus-4.6' to LiteLLM key fragment 'claude-opus-4-6'."""
    return "claude-" + model_short.replace(".", "-")


def normalize_model(raw: str) -> str:
    """Normalize raw model ID to short display name."""
    if raw in MODEL_ALIASES:
        return MODEL_ALIASES[raw]
    # Fallback: strip 'claude-' prefix and date suffix
    name = raw.removeprefix("claude-")
    parts = name.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        name = parts[0]
    return name


def get_pricing_family(model_short: str) -> str:
    """Get pricing family for a short model name."""
    if model_short in MODEL_FAMILY:
        return MODEL_FAMILY[model_short]
    low = model_short.lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in low:
            return family
    return "sonnet"  # fallback


# ── LiteLLM price loading ─────────────────────────────────────────────────────

def _load_litellm_cache() -> dict | None:
    """Load cached LiteLLM price DB if fresh (within TTL)."""
    try:
        if not _CACHE_PATH.exists():
            return None
        age = time.time() - _CACHE_PATH.stat().st_mtime
        if age > _CACHE_TTL:
            return None
        with _CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _fetch_litellm_prices() -> dict | None:
    """Download LiteLLM price DB and save to cache. Returns parsed dict or None."""
    try:
        with urllib.request.urlopen(_LITELLM_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        return data
    except Exception:
        return None


def _get_litellm_db() -> dict | None:
    """Return LiteLLM price DB (from cache or network). None if unavailable."""
    cached = _load_litellm_cache()
    if cached is not None:
        return cached
    return _fetch_litellm_prices()


def _entry_to_prices(entry: dict) -> dict[str, float] | None:
    """Convert a LiteLLM entry ($/token) to $/M prices dict."""
    try:
        input_per_token = entry.get("input_cost_per_token", 0) or 0
        output_per_token = entry.get("output_cost_per_token", 0) or 0
        cache_read_per_token = entry.get("cache_read_input_token_cost", 0) or 0
        cache_create_per_token = entry.get("cache_creation_input_token_cost", 0) or 0
        if input_per_token <= 0:
            return None
        return {
            "input": input_per_token * 1_000_000,
            "output": output_per_token * 1_000_000,
            "cache_read": cache_read_per_token * 1_000_000,
            "cache_create": cache_create_per_token * 1_000_000,
        }
    except (TypeError, ValueError):
        return None


def _find_prices_in_litellm(fragment: str, db: dict) -> dict[str, float] | None:
    """Find prices for keys matching a fragment. Prefers vanilla 'anthropic.<frag>' over region-prefixed variants."""
    candidates: list[tuple[str, dict]] = []
    for key, val in db.items():
        if not isinstance(val, dict):
            continue
        if fragment in key.lower():
            candidates.append((key, val))
    if not candidates:
        return None

    def rank(key: str) -> tuple[int, str]:
        # Prefer base "anthropic.X" over "region.anthropic.X" or "vendor_ai/X"
        low = key.lower()
        if low.startswith("anthropic."):
            return (0, key)
        if "/" in low:  # azure_ai/, vertex_ai/, bedrock/
            return (2, key)
        return (1, key)  # region-prefixed (us., eu., global., ...)

    candidates.sort(key=lambda x: rank(x[0]))
    return _entry_to_prices(candidates[0][1])


def _extract_family_prices_from_litellm(
    family: str, db: dict
) -> dict[str, float] | None:
    """Family-level fallback: pick the newest (highest date) model in the family."""
    fragments = _FAMILY_FRAGMENTS.get(family, [])
    candidates: list[tuple[str, dict]] = []
    for key, val in db.items():
        if not isinstance(val, dict):
            continue
        key_lower = key.lower()
        if not key_lower.startswith("anthropic."):
            continue
        if any(frag in key_lower for frag in fragments):
            candidates.append((key, val))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return _entry_to_prices(candidates[0][1])


# Module-level cache for resolved prices (keyed by short model name)
_resolved_prices: dict[str, dict[str, float]] = {}
_db_loaded = False
_db: dict | None = None


def _ensure_db() -> dict | None:
    global _db_loaded, _db
    if not _db_loaded:
        _db = _get_litellm_db()
        _db_loaded = True
    return _db


def _get_prices(model_short: str) -> dict[str, float]:
    """Return $/M prices for a specific short model name.

    Resolution order:
      1. Exact model match in LiteLLM (e.g. 'opus-4.6' → 'claude-opus-4-6')
      2. Family-level newest in LiteLLM (e.g. opus → latest opus-*)
      3. Hardcoded fallback table
    """
    if model_short in _resolved_prices:
        return _resolved_prices[model_short]

    family = get_pricing_family(model_short)
    db = _ensure_db()
    prices: dict[str, float] | None = None

    if db is not None:
        fragment = _short_to_litellm_fragment(model_short)
        prices = _find_prices_in_litellm(fragment, db)
        if prices is None:
            prices = _extract_family_prices_from_litellm(family, db)

    if prices is None:
        prices = _fallback_prices(family)

    _resolved_prices[model_short] = prices
    return prices


def _fallback_prices(family: str) -> dict[str, float]:
    """Return fallback hardcoded prices for a family."""
    return _FALLBACK_PRICING.get(family, _FALLBACK_PRICING["sonnet"])


def calculate_cost(model_short: str, usage: TokenUsage) -> dict[str, float]:
    """Calculate costs for given usage.

    Returns dict with:
      input_cost, output_cost, cache_read_cost, cache_create_cost,
      cache_savings, web_search_cost, total
    """
    prices = _get_prices(model_short)

    input_cost = usage.input_tokens * prices["input"] / 1_000_000
    output_cost = usage.output_tokens * prices["output"] / 1_000_000
    cache_read_cost = usage.cache_read_tokens * prices["cache_read"] / 1_000_000
    cache_create_cost = usage.cache_creation_tokens * prices["cache_create"] / 1_000_000

    # Cache savings = what it would have cost at full input price minus actual cache cost
    cache_savings = (
        (usage.cache_read_tokens + usage.cache_creation_tokens) * prices["input"] / 1_000_000
        - cache_read_cost - cache_create_cost
    )

    web_search_cost = usage.web_search_requests * WEB_SEARCH_COST_PER_1K / 1_000

    token_total = input_cost + output_cost + cache_read_cost + cache_create_cost
    total = token_total + web_search_cost

    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "cache_read_cost": cache_read_cost,
        "cache_create_cost": cache_create_cost,
        "cache_savings": cache_savings,
        "web_search_cost": web_search_cost,
        "total": total,
    }


def reset_price_cache() -> None:
    """Reset module-level price cache (useful for testing)."""
    global _db_loaded, _db
    _resolved_prices.clear()
    _db_loaded = False
    _db = None
