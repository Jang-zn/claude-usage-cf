"""CSV/JSON export for AggregatedUsage."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from .models import AggregatedUsage, UsageRecord
from .pricing import calculate_cost


def _default_export_path(fmt: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path.home() / ".claude-usage" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{timestamp}.{fmt}"


def export_usage(
    agg: AggregatedUsage,
    fmt: Literal["csv", "json"],
    out: Path | None = None,
) -> Path:
    """Export aggregated usage summary to CSV or JSON.

    Args:
        agg: Aggregated usage data to export.
        fmt: Output format — "csv" or "json".
        out: Output file path. If None, defaults to
             ~/.claude-usage/exports/{YYYYMMDD-HHMMSS}.{fmt}.

    Returns:
        Path to the written file.
    """
    if out is None:
        out = _default_export_path(fmt)
    else:
        out = Path(out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        _write_json(agg, out)
    else:
        _write_csv(agg, out)

    return out


def _write_json(agg: AggregatedUsage, out: Path) -> None:
    """Write JSON export."""
    models_list = []
    for model_name, mu in agg.models.items():
        cost_info = calculate_cost(model_name, mu.usage)
        models_list.append({
            "model": model_name,
            "input_tokens": mu.usage.input_tokens,
            "output_tokens": mu.usage.output_tokens,
            "cache_read_tokens": mu.usage.cache_read_tokens,
            "cache_creation_tokens": mu.usage.cache_creation_tokens,
            "web_search_requests": mu.usage.web_search_requests,
            "request_count": mu.request_count,
            "turn_count": mu.turn_count,
            "cost_usd": round(cost_info["total"], 6),
        })

    daily_list = [
        {
            "date": du.date,
            "total_tokens": du.total_tokens,
            "by_model": du.by_model,
        }
        for du in agg.daily
    ]

    projects_list = [
        {
            "project": pu.project,
            "total_tokens": pu.total_tokens,
        }
        for pu in agg.projects
    ]

    categories_list = []
    for cat_name, cs in agg.categories.items():
        categories_list.append({
            "category": cat_name,
            "input_tokens": cs.tokens.input_tokens,
            "output_tokens": cs.tokens.output_tokens,
            "cache_read_tokens": cs.tokens.cache_read_tokens,
            "cache_creation_tokens": cs.tokens.cache_creation_tokens,
            "web_search_requests": cs.tokens.web_search_requests,
            "turn_count": cs.turn_count,
            "cost_usd": round(cs.cost_usd, 6),
        })

    payload = {
        "generated_at": datetime.now().isoformat(),
        "account": agg.account_name,
        "period": agg.period,
        "models": models_list,
        "daily": daily_list,
        "projects": projects_list,
        "categories": categories_list,
        "one_shot_rate": agg.one_shot_rate,
    }

    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(agg: AggregatedUsage, out: Path) -> None:
    """Write CSV export with a 'section' column to distinguish rows."""
    fieldnames = [
        "section",
        "date",
        "account",
        "model",
        "project",
        "category",
        "input",
        "output",
        "cache_read",
        "cache_create",
        "web_search_requests",
        "cost_usd",
    ]

    rows: list[dict] = []

    # Section: model — per-model totals
    for model_name, mu in agg.models.items():
        cost_info = calculate_cost(model_name, mu.usage)
        rows.append({
            "section": "model",
            "date": "",
            "account": agg.account_name,
            "model": model_name,
            "project": "",
            "category": "",
            "input": mu.usage.input_tokens,
            "output": mu.usage.output_tokens,
            "cache_read": mu.usage.cache_read_tokens,
            "cache_create": mu.usage.cache_creation_tokens,
            "web_search_requests": mu.usage.web_search_requests,
            "cost_usd": round(cost_info["total"], 6),
        })

    # Section: daily
    for du in agg.daily:
        rows.append({
            "section": "daily",
            "date": du.date,
            "account": agg.account_name,
            "model": "",
            "project": "",
            "category": "",
            "input": du.total_tokens,
            "output": "",
            "cache_read": "",
            "cache_create": "",
            "web_search_requests": "",
            "cost_usd": "",
        })

    # Section: project
    for pu in agg.projects:
        rows.append({
            "section": "project",
            "date": "",
            "account": agg.account_name,
            "model": "",
            "project": pu.project,
            "category": "",
            "input": pu.total_tokens,
            "output": "",
            "cache_read": "",
            "cache_create": "",
            "web_search_requests": "",
            "cost_usd": "",
        })

    # Section: category
    for cat_name, cs in agg.categories.items():
        rows.append({
            "section": "category",
            "date": "",
            "account": agg.account_name,
            "model": "",
            "project": "",
            "category": cat_name,
            "input": cs.tokens.input_tokens,
            "output": cs.tokens.output_tokens,
            "cache_read": cs.tokens.cache_read_tokens,
            "cache_create": cs.tokens.cache_creation_tokens,
            "web_search_requests": cs.tokens.web_search_requests,
            "cost_usd": round(cs.cost_usd, 6),
        })

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    out.write_text(buf.getvalue(), encoding="utf-8")


def export_records(
    records: list[UsageRecord],
    account: str = "",
    fmt: Literal["csv", "json"] = "csv",
    out: Path | None = None,
) -> Path:
    """Export raw UsageRecord list to CSV or JSON.

    Useful when you need per-record detail rather than aggregated summaries.

    Args:
        records: List of UsageRecord instances.
        account: Account name label to include in output.
        fmt: Output format — "csv" or "json".
        out: Output file path. Defaults to ~/.claude-usage/exports/{timestamp}.{fmt}.

    Returns:
        Path to the written file.
    """
    if out is None:
        out = _default_export_path(fmt)
    else:
        out = Path(out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        payload = {
            "generated_at": datetime.now().isoformat(),
            "account": account,
            "records": [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "model": r.model,
                    "project": r.project,
                    "session_id": r.session_id,
                    "category": r.category,
                    "input": r.usage.input_tokens,
                    "output": r.usage.output_tokens,
                    "cache_read": r.usage.cache_read_tokens,
                    "cache_create": r.usage.cache_creation_tokens,
                    "web_search_requests": r.usage.web_search_requests,
                    "cost_usd": round(calculate_cost(r.model, r.usage)["total"], 6),
                }
                for r in records
            ],
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        fieldnames = [
            "date", "account", "model", "project", "category",
            "input", "output", "cache_read", "cache_create",
            "web_search_requests", "cost_usd",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            cost_info = calculate_cost(r.model, r.usage)
            writer.writerow({
                "date": r.timestamp.astimezone().strftime("%Y-%m-%d"),
                "account": account,
                "model": r.model,
                "project": r.project,
                "category": r.category,
                "input": r.usage.input_tokens,
                "output": r.usage.output_tokens,
                "cache_read": r.usage.cache_read_tokens,
                "cache_create": r.usage.cache_creation_tokens,
                "web_search_requests": r.usage.web_search_requests,
                "cost_usd": round(cost_info["total"], 6),
            })
        out.write_text(buf.getvalue(), encoding="utf-8")

    return out
