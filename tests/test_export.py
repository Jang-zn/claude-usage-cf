"""Tests for src/claude_usage/export.py."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_usage.export import export_usage, export_records
from claude_usage.models import (
    AggregatedUsage,
    CategoryStats,
    DailyUsage,
    ModelUsage,
    ProjectUsage,
    TokenUsage,
    UsageRecord,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_agg() -> AggregatedUsage:
    """Build a minimal AggregatedUsage for testing."""
    usage = TokenUsage(
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=200,
        cache_creation_tokens=100,
        web_search_requests=3,
    )
    models = {
        "sonnet-4.6": ModelUsage(
            model="sonnet-4.6",
            usage=usage,
            request_count=5,
            turn_count=3,
        )
    }
    daily = [DailyUsage(date="2026-04-16", total_tokens=1500)]
    projects = [ProjectUsage(project="my-project", total_tokens=800)]
    categories = {
        "Coding": CategoryStats(
            category="Coding",
            tokens=usage,
            turn_count=2,
            cost_usd=0.005,
        )
    }
    return AggregatedUsage(
        models=models,
        daily=daily,
        projects=projects,
        categories=categories,
        account_name="Personal",
        period="week",
        one_shot_rate=0.75,
    )


def _make_records() -> list[UsageRecord]:
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    return [
        UsageRecord(
            timestamp=ts,
            model="haiku",
            usage=usage,
            project="proj-a",
            session_id="sess-1",
            category="Coding",
        ),
        UsageRecord(
            timestamp=ts,
            model="sonnet-4.6",
            usage=usage,
            project="proj-b",
            session_id="sess-2",
            category="Debugging",
        ),
    ]


# ── export_usage (CSV) ────────────────────────────────────────────────────────

class TestExportUsageCsv:
    def test_file_created(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.csv"
        result = export_usage(agg, fmt="csv", out=out)
        assert result == out
        assert out.exists()

    def test_csv_header(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.csv"
        export_usage(agg, fmt="csv", out=out)
        with out.open() as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames is not None
            expected_fields = {
                "section", "date", "account", "model", "project",
                "category", "input", "output", "cache_read", "cache_create",
                "web_search_requests", "cost_usd",
            }
            assert expected_fields <= set(reader.fieldnames)

    def test_csv_sections_present(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.csv"
        export_usage(agg, fmt="csv", out=out)
        with out.open() as f:
            reader = csv.DictReader(f)
            sections = {row["section"] for row in reader}
        assert "model" in sections
        assert "daily" in sections
        assert "project" in sections
        assert "category" in sections

    def test_csv_model_row_values(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.csv"
        export_usage(agg, fmt="csv", out=out)
        with out.open() as f:
            reader = csv.DictReader(f)
            model_rows = [r for r in reader if r["section"] == "model"]
        assert len(model_rows) == 1
        row = model_rows[0]
        assert row["model"] == "sonnet-4.6"
        assert row["account"] == "Personal"
        assert int(row["input"]) == 1000
        assert int(row["output"]) == 500

    def test_csv_parent_dir_created(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "sub" / "dir" / "out.csv"
        result = export_usage(agg, fmt="csv", out=out)
        assert result.exists()


# ── export_usage (JSON) ───────────────────────────────────────────────────────

class TestExportUsageJson:
    def test_file_created(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.json"
        result = export_usage(agg, fmt="json", out=out)
        assert result == out
        assert out.exists()

    def test_json_round_trip(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.json"
        export_usage(agg, fmt="json", out=out)
        data = json.loads(out.read_text())

        assert data["account"] == "Personal"
        assert data["period"] == "week"
        assert data["one_shot_rate"] == pytest.approx(0.75)
        assert "generated_at" in data

    def test_json_models_section(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.json"
        export_usage(agg, fmt="json", out=out)
        data = json.loads(out.read_text())

        assert len(data["models"]) == 1
        m = data["models"][0]
        assert m["model"] == "sonnet-4.6"
        assert m["input_tokens"] == 1000
        assert m["output_tokens"] == 500
        assert m["web_search_requests"] == 3
        assert isinstance(m["cost_usd"], float)

    def test_json_daily_section(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.json"
        export_usage(agg, fmt="json", out=out)
        data = json.loads(out.read_text())

        assert len(data["daily"]) == 1
        assert data["daily"][0]["date"] == "2026-04-16"

    def test_json_projects_section(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.json"
        export_usage(agg, fmt="json", out=out)
        data = json.loads(out.read_text())

        assert len(data["projects"]) == 1
        assert data["projects"][0]["project"] == "my-project"

    def test_json_categories_section(self, tmp_path):
        agg = _make_agg()
        out = tmp_path / "out.json"
        export_usage(agg, fmt="json", out=out)
        data = json.loads(out.read_text())

        assert len(data["categories"]) == 1
        cat = data["categories"][0]
        assert cat["category"] == "Coding"
        assert cat["turn_count"] == 2


# ── default path (HOME monkeypatch) ───────────────────────────────────────────

class TestDefaultExportPath:
    def test_default_csv_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # Reset Path.home() cache (Python uses os.environ["HOME"])
        import pathlib
        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))

        agg = _make_agg()
        result = export_usage(agg, fmt="csv")
        assert result.exists()
        assert result.suffix == ".csv"
        assert ".claude-usage" in str(result)

    def test_default_json_path(self, tmp_path, monkeypatch):
        import pathlib
        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))

        agg = _make_agg()
        result = export_usage(agg, fmt="json")
        assert result.exists()
        assert result.suffix == ".json"


# ── export_records ────────────────────────────────────────────────────────────

class TestExportRecords:
    def test_records_csv(self, tmp_path):
        records = _make_records()
        out = tmp_path / "records.csv"
        result = export_records(records, account="Personal", fmt="csv", out=out)
        assert result.exists()
        with out.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["model"] == "haiku"
        assert rows[1]["model"] == "sonnet-4.6"

    def test_records_json(self, tmp_path):
        records = _make_records()
        out = tmp_path / "records.json"
        result = export_records(records, account="Work", fmt="json", out=out)
        assert result.exists()
        data = json.loads(out.read_text())
        assert data["account"] == "Work"
        assert len(data["records"]) == 2
        assert data["records"][0]["category"] == "Coding"
        assert data["records"][1]["project"] == "proj-b"

    def test_records_csv_header(self, tmp_path):
        records = _make_records()
        out = tmp_path / "records.csv"
        export_records(records, fmt="csv", out=out)
        with out.open() as f:
            reader = csv.DictReader(f)
            assert "date" in reader.fieldnames
            assert "model" in reader.fieldnames
            assert "cost_usd" in reader.fieldnames
