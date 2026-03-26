"""Model pricing constants and cost calculation."""

from __future__ import annotations

from .models import TokenUsage

# Prices per 1M tokens (USD)
PRICING: dict[str, dict[str, float]] = {
    "opus": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_create": 18.75,
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


def calculate_cost(model_short: str, usage: TokenUsage) -> dict[str, float]:
    """Calculate costs for given usage. Returns dict with input_cost, output_cost, cache_savings, total."""
    family = get_pricing_family(model_short)
    prices = PRICING.get(family, PRICING["sonnet"])

    input_cost = usage.input_tokens * prices["input"] / 1_000_000
    output_cost = usage.output_tokens * prices["output"] / 1_000_000
    cache_read_cost = usage.cache_read_tokens * prices["cache_read"] / 1_000_000
    cache_create_cost = usage.cache_creation_tokens * prices["cache_create"] / 1_000_000

    # Cache savings = what it would have cost at full input price minus actual cache cost
    cache_savings = (
        (usage.cache_read_tokens + usage.cache_creation_tokens) * prices["input"] / 1_000_000
        - cache_read_cost - cache_create_cost
    )

    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "cache_read_cost": cache_read_cost,
        "cache_create_cost": cache_create_cost,
        "cache_savings": cache_savings,
        "total": input_cost + output_cost + cache_read_cost + cache_create_cost,
    }
