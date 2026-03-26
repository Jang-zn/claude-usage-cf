"""Read and parse ~/.claude/stats-cache.json for historical data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..models import DailyUsage, TokenUsage
from ..pricing import normalize_model


@dataclass
class CacheData:
    """Parsed stats-cache.json data."""

    last_computed_date: str = ""
    daily_tokens: list[DailyUsage] = field(default_factory=list)
    model_totals: dict[str, TokenUsage] = field(default_factory=dict)
    daily_activity: list[dict] = field(default_factory=list)


def read_stats_cache(claude_home: Path) -> CacheData:
    """Read and parse stats-cache.json. Returns empty CacheData on failure."""
    cache_path = claude_home / "stats-cache.json"
    if not cache_path.exists():
        return CacheData()

    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CacheData()

    if not isinstance(raw, dict):
        return CacheData()

    result = CacheData(last_computed_date=raw.get("lastComputedDate", ""))

    # Parse dailyModelTokens
    for entry in raw.get("dailyModelTokens", []):
        date = entry.get("date", "")
        tokens_by_model = entry.get("tokensByModel", {})
        by_model: dict[str, int] = {}
        total = 0
        for raw_model, count in tokens_by_model.items():
            short = normalize_model(raw_model)
            by_model[short] = by_model.get(short, 0) + count
            total += count
        result.daily_tokens.append(DailyUsage(
            date=date,
            total_tokens=total,
            by_model=by_model,
        ))

    # Parse modelUsage
    for raw_model, usage_data in raw.get("modelUsage", {}).items():
        short = normalize_model(raw_model)
        tu = TokenUsage(
            input_tokens=usage_data.get("inputTokens", 0),
            output_tokens=usage_data.get("outputTokens", 0),
            cache_read_tokens=usage_data.get("cacheReadInputTokens", 0),
            cache_creation_tokens=usage_data.get("cacheCreationInputTokens", 0),
        )
        if short in result.model_totals:
            result.model_totals[short] += tu
        else:
            result.model_totals[short] = tu

    # Parse dailyActivity
    result.daily_activity = raw.get("dailyActivity", [])

    return result
