"""Combine all data sources into AggregatedUsage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import defaultdict

from ..config import AppConfig, AccountConfig
from ..models import (
    AggregatedUsage,
    ActivitySummary,
    DailyUsage,
    ModelUsage,
    ProjectUsage,
    TokenUsage,
    UsageRecord,
    WindowUsage,
)
from ..pricing import normalize_model, get_pricing_family
from .cache_reader import read_stats_cache
from .jsonl_parser import parse_all_jsonl
from .session_reader import read_sessions

PERIOD_DAYS = {
    "day": 1,
    "week": 7,
    "month": 30,
}

# Accumulated JSONL records per account (survives across refreshes)
_record_cache: dict[str, list[UsageRecord]] = {}


def get_week_start() -> str:
    """Return Monday of the current week as YYYY-MM-DD."""
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _is_valid_model(model: str) -> bool:
    """Filter out synthetic/internal model names."""
    return bool(model) and not model.startswith("<")


def _aggregate_account(
    account: AccountConfig,
    period: str,
    config: AppConfig,
) -> AggregatedUsage:
    """Aggregate data for a single account."""
    claude_home = account.claude_home_path
    lookback_days = PERIOD_DAYS.get(period, 7)
    cache_key = str(claude_home)

    # Read cache for historical data
    cache = read_stats_cache(claude_home)

    # Read JSONL incrementally — new records only
    new_records = parse_all_jsonl(
        claude_home,
        lookback_days=max(lookback_days, 30),  # always parse 30 days for cache
        incremental=True,
    )

    # Accumulate records
    if cache_key not in _record_cache:
        _record_cache[cache_key] = []
    _record_cache[cache_key].extend(new_records)
    all_jsonl_records = _record_cache[cache_key]

    # Read sessions
    sessions = read_sessions(claude_home)

    # Determine date range for the requested period
    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=lookback_days - 1)).isoformat()

    # Filter records to period
    jsonl_records = [
        rec for rec in all_jsonl_records
        if rec.timestamp.strftime("%Y-%m-%d") >= start_date
    ]

    # Build models dict — only include data within the requested period
    models: dict[str, ModelUsage] = {}
    last_computed = cache.last_computed_date

    # From cache daily tokens (within period, before lastComputedDate)
    for du in cache.daily_tokens:
        if du.date < start_date:
            continue
        for model_short, count in du.by_model.items():
            if not _is_valid_model(model_short):
                continue
            if model_short not in models:
                family = get_pricing_family(model_short)
                limit = config.get_limit(family)
                models[model_short] = ModelUsage(model=model_short, weekly_limit=limit)
            models[model_short].usage.output_tokens += count

    # From JSONL records (data after lastComputedDate, within period)
    for rec in jsonl_records:
        if not _is_valid_model(rec.model):
            continue
        date_str = rec.timestamp.strftime("%Y-%m-%d")
        if last_computed and date_str <= last_computed:
            continue

        if rec.model not in models:
            family = get_pricing_family(rec.model)
            limit = config.get_limit(family)
            models[rec.model] = ModelUsage(model=rec.model, weekly_limit=limit)
        models[rec.model].usage += rec.usage

    # Build daily usage
    daily_map: dict[str, DailyUsage] = {}

    # From cache daily tokens
    for du in cache.daily_tokens:
        if du.date >= start_date:
            daily_map[du.date] = du

    # From JSONL records
    for rec in jsonl_records:
        if not _is_valid_model(rec.model):
            continue
        date_str = rec.timestamp.strftime("%Y-%m-%d")
        if last_computed and date_str <= last_computed:
            continue

        if date_str not in daily_map:
            daily_map[date_str] = DailyUsage(date=date_str)
        day = daily_map[date_str]
        tokens = rec.usage.total
        day.total_tokens += tokens
        day.by_model[rec.model] = day.by_model.get(rec.model, 0) + tokens

    daily = sorted(daily_map.values(), key=lambda d: d.date)

    # Build project usage
    project_map: defaultdict[str, int] = defaultdict(int)
    for rec in jsonl_records:
        if rec.project:
            project_map[rec.project] += rec.usage.total

    projects = sorted(
        [ProjectUsage(project=p, total_tokens=t) for p, t in project_map.items()],
        key=lambda x: x.total_tokens,
        reverse=True,
    )

    # Build activity summary
    cat_tokens: defaultdict[str, int] = defaultdict(int)
    tool_tokens: defaultdict[str, int] = defaultdict(int)

    for rec in jsonl_records:
        for act in rec.activities:
            t = act.tokens.total
            cat_tokens[act.category.value] += t
            tool_tokens[act.name] += t

    activity = ActivitySummary(
        by_category=dict(cat_tokens),
        by_tool=dict(tool_tokens),
    )

    # Build 5-hour rolling window usage
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=5)
    win_by_model: defaultdict[str, int] = defaultdict(int)
    oldest_ts = None
    for rec in all_jsonl_records:
        if rec.timestamp >= window_start and _is_valid_model(rec.model):
            win_by_model[rec.model] += rec.usage.total
            if oldest_ts is None or rec.timestamp < oldest_ts:
                oldest_ts = rec.timestamp
    reset_at = (oldest_ts + timedelta(hours=5)) if oldest_ts else None
    window = WindowUsage(by_model=dict(win_by_model), reset_at=reset_at)

    # OAuth usage: 1회 API 호출 → limit 역산 → 매 refresh마다 로컬 토큰으로 계산
    from .oauth_usage import fetch_once, store_limits, compute_current

    win_tokens = sum(win_by_model.values())
    week_all_tokens = sum(mu.usage.total for mu in models.values())
    week_sonnet_tokens = models.get("sonnet-4.6", ModelUsage(model="sonnet-4.6")).usage.total

    fetch_once()  # 최초 1회만 실제 호출, 이후 no-op
    store_limits(win_tokens, week_all_tokens, week_sonnet_tokens)  # limit 역산 (1회만)
    oauth_usage = compute_current(win_tokens, week_all_tokens, week_sonnet_tokens)

    return AggregatedUsage(
        models=models,
        daily=daily,
        projects=projects,
        sessions=sessions,
        activity=activity,
        window=window,
        oauth_usage=oauth_usage,
        period=period,
        account_name=account.name,
    )


def aggregate_usage(
    account: AccountConfig,
    period: str,
    config: AppConfig,
) -> AggregatedUsage:
    """Aggregate usage for a single account (public API)."""
    return _aggregate_account(account, period, config)


def aggregate(
    config: AppConfig | None = None,
    period: str = "week",
) -> list[AggregatedUsage]:
    """Aggregate usage for all configured accounts."""
    if config is None:
        from ..config import load_config
        config = load_config()

    results: list[AggregatedUsage] = []
    for account in config.accounts:
        results.append(_aggregate_account(account, period, config))

    return results
