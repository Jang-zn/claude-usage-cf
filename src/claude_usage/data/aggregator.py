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
from .oauth_usage import get_oauth_usage
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
    force_oauth: bool = False,
) -> AggregatedUsage:
    """Aggregate data for a single account."""
    claude_home = account.claude_home_path
    cache_key = str(claude_home)

    # Determine parse lookback
    if period == "session":
        parse_lookback = 30  # always keep 30 days in cache for OAuth calc
    else:
        lookback_days = PERIOD_DAYS.get(period, 7)
        parse_lookback = max(lookback_days, 30)

    # Read cache for historical data
    cache = read_stats_cache(claude_home)

    # Read JSONL incrementally — new records only
    new_records = parse_all_jsonl(
        claude_home,
        lookback_days=parse_lookback,
        incremental=True,
    )

    # Accumulate records
    if cache_key not in _record_cache:
        _record_cache[cache_key] = []
    if new_records:
        _record_cache[cache_key].extend(new_records)
        # Trim records older than lookback window to bound memory
        cutoff = datetime.now(timezone.utc) - timedelta(days=parse_lookback)
        _record_cache[cache_key] = [r for r in _record_cache[cache_key] if r.timestamp >= cutoff]
    all_jsonl_records = _record_cache[cache_key]

    # Read sessions
    sessions = read_sessions(claude_home)

    # ── Determine period-filtered records ─────────────────────────────────────
    if period == "session":
        now_utc = datetime.now(timezone.utc)
        window_start = now_utc - timedelta(hours=5)
        jsonl_records = [
            rec for rec in all_jsonl_records
            if rec.timestamp >= window_start
        ]
        start_date = None  # not used for session
    else:
        lookback_days = PERIOD_DAYS.get(period, 7)
        # Use local timezone so "day" = calendar today in user's locale
        today_local = datetime.now().date()
        start_date = (today_local - timedelta(days=lookback_days - 1)).isoformat()
        jsonl_records = [
            rec for rec in all_jsonl_records
            if rec.timestamp.astimezone().strftime("%Y-%m-%d") >= start_date
        ]

    # ── Build models dict ─────────────────────────────────────────────────────
    models: dict[str, ModelUsage] = {}
    last_computed = cache.last_computed_date

    if period != "session" and start_date is not None:
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
        if period != "session" and last_computed:
            date_str = rec.timestamp.astimezone().strftime("%Y-%m-%d")
            if date_str <= last_computed:
                continue

        if rec.model not in models:
            family = get_pricing_family(rec.model)
            limit = config.get_limit(family)
            models[rec.model] = ModelUsage(model=rec.model, weekly_limit=limit)
        models[rec.model].usage += rec.usage
        models[rec.model].request_count += 1

    # ── Build daily usage ─────────────────────────────────────────────────────
    daily_map: dict[str, DailyUsage] = {}

    if period != "session" and start_date is not None:
        for du in cache.daily_tokens:
            if du.date >= start_date:
                daily_map[du.date] = du

    for rec in jsonl_records:
        if not _is_valid_model(rec.model):
            continue
        date_str = rec.timestamp.astimezone().strftime("%Y-%m-%d")
        if period != "session" and last_computed and date_str <= last_computed:
            continue

        if date_str not in daily_map:
            daily_map[date_str] = DailyUsage(date=date_str)
        day = daily_map[date_str]
        tokens = rec.usage.total
        day.total_tokens += tokens
        day.by_model[rec.model] = day.by_model.get(rec.model, 0) + tokens

    daily = sorted(daily_map.values(), key=lambda d: d.date)

    # ── Build project usage ───────────────────────────────────────────────────
    project_map: defaultdict[str, int] = defaultdict(int)
    for rec in jsonl_records:
        if rec.project:
            project_map[rec.project] += rec.usage.total

    projects = sorted(
        [ProjectUsage(project=p, total_tokens=t) for p, t in project_map.items()],
        key=lambda x: x.total_tokens,
        reverse=True,
    )

    # ── Count question turns per model (30s gap within session = new turn) ───
    _TURN_GAP = 30  # seconds
    _session_last: dict[str, datetime] = {}
    for rec in sorted(jsonl_records, key=lambda r: r.timestamp):
        if not _is_valid_model(rec.model) or rec.model not in models:
            continue
        sid = rec.session_id or "__no_session__"
        last_ts = _session_last.get(sid)
        if last_ts is None or (rec.timestamp - last_ts).total_seconds() > _TURN_GAP:
            models[rec.model].turn_count += 1
        _session_last[sid] = rec.timestamp

    # ── Build activity summary ────────────────────────────────────────────────
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

    # ── Build 5-hour rolling window usage ────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    window_start_5h = now_utc - timedelta(hours=5)
    win_by_model: defaultdict[str, int] = defaultdict(int)
    oldest_ts = None
    for rec in all_jsonl_records:
        if rec.timestamp >= window_start_5h and _is_valid_model(rec.model):
            win_by_model[rec.model] += rec.usage.total
            if oldest_ts is None or rec.timestamp < oldest_ts:
                oldest_ts = rec.timestamp
    reset_at = (oldest_ts + timedelta(hours=5)) if oldest_ts else None
    window = WindowUsage(by_model=dict(win_by_model), reset_at=reset_at)

    # ── OAuth quota: always based on 7-day data ───────────────────────────────
    today_local = datetime.now().date()
    week_start_str = (today_local - timedelta(days=6)).isoformat()
    week_records = [
        rec for rec in all_jsonl_records
        if rec.timestamp.astimezone().strftime("%Y-%m-%d") >= week_start_str
        and _is_valid_model(rec.model)
    ]
    week_all_tokens = sum(rec.usage.total for rec in week_records)
    week_sonnet_tokens = sum(
        rec.usage.total for rec in week_records if rec.model == "sonnet-4.6"
    )

    oauth_usage = get_oauth_usage(
        win_tokens=sum(window.by_model.values()),
        week_all_tokens=week_all_tokens,
        week_sonnet_tokens=week_sonnet_tokens,
        force=force_oauth,
    )

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
    force_oauth: bool = False,
) -> AggregatedUsage:
    """Aggregate usage for a single account (public API)."""
    return _aggregate_account(account, period, config, force_oauth=force_oauth)


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
