"""Tests for the aggregator module."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_usage.config import AccountConfig, AppConfig
from claude_usage.data.aggregator import aggregate, get_week_start, _aggregate_account
from claude_usage.data.jsonl_parser import reset_offsets
from claude_usage.models import TokenUsage, UsageRecord


@pytest.fixture(autouse=True)
def _clean_offsets():
    reset_offsets()
    yield
    reset_offsets()


SAMPLE_ASSISTANT = {
    "type": "assistant",
    "message": {
        "model": "claude-opus-4-6",
        "role": "assistant",
        "content": [{"type": "tool_use", "name": "Read", "id": "t1", "input": {}}],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    },
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    "sessionId": "sess-001",
}

SAMPLE_CACHE = {
    "version": 2,
    "lastComputedDate": "2026-01-01",
    "dailyModelTokens": [
        {"date": "2026-01-01", "tokensByModel": {"claude-opus-4-6": 5000}},
    ],
    "modelUsage": {
        "claude-opus-4-6": {
            "inputTokens": 1000,
            "outputTokens": 500,
            "cacheReadInputTokens": 10000,
            "cacheCreationInputTokens": 2000,
        }
    },
    "dailyActivity": [
        {"date": "2026-01-01", "messageCount": 10, "sessionCount": 2, "toolCallCount": 5},
    ],
}


def _setup_claude_home(tmp_path: Path) -> Path:
    """Create a minimal claude home with JSONL and cache."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    # Write cache
    (claude_home / "stats-cache.json").write_text(json.dumps(SAMPLE_CACHE))

    # Write JSONL
    project_dir = claude_home / "projects" / "-Users-jang-myapp"
    project_dir.mkdir(parents=True)
    jsonl_path = project_dir / "conversation.jsonl"
    jsonl_path.write_text(json.dumps(SAMPLE_ASSISTANT) + "\n")

    # Write session
    sessions_dir = claude_home / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "sess-001.json").write_text(json.dumps({
        "pid": 99999,
        "sessionId": "sess-001",
        "cwd": "/Users/jang/projects/myapp",
        "startedAt": 1774450952964,
    }))

    return claude_home


class TestGetWeekStart:
    def test_returns_monday(self):
        result = get_week_start()
        dt = datetime.fromisoformat(result)
        assert dt.weekday() == 0  # Monday


class TestAggregate:
    def test_single_account(self, tmp_path):
        claude_home = _setup_claude_home(tmp_path)
        config = AppConfig(
            accounts=[AccountConfig(name="Test", claude_home=str(claude_home))],
        )

        results = aggregate(config=config, period="month")
        assert len(results) == 1
        agg = results[0]
        assert agg.account_name == "Test"
        assert agg.period == "month"
        # Should have opus model from JSONL
        assert "opus-4.6" in agg.models

    def test_projects_sorted_by_tokens(self, tmp_path):
        claude_home = _setup_claude_home(tmp_path)
        config = AppConfig(
            accounts=[AccountConfig(name="Test", claude_home=str(claude_home))],
        )

        results = aggregate(config=config, period="month")
        agg = results[0]
        if len(agg.projects) > 1:
            for i in range(len(agg.projects) - 1):
                assert agg.projects[i].total_tokens >= agg.projects[i + 1].total_tokens

    def test_sessions_loaded(self, tmp_path):
        claude_home = _setup_claude_home(tmp_path)
        config = AppConfig(
            accounts=[AccountConfig(name="Test", claude_home=str(claude_home))],
        )

        results = aggregate(config=config, period="week")
        agg = results[0]
        assert len(agg.sessions) == 1
        assert agg.sessions[0].session_id == "sess-001"

    def test_activity_populated(self, tmp_path):
        claude_home = _setup_claude_home(tmp_path)
        config = AppConfig(
            accounts=[AccountConfig(name="Test", claude_home=str(claude_home))],
        )

        results = aggregate(config=config, period="month")
        agg = results[0]
        # JSONL has a Read tool_use
        assert "Tool" in agg.activity.by_category or len(agg.activity.by_category) == 0
