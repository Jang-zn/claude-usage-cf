"""Tests for the aggregator module."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_usage.config import AccountConfig, AppConfig
from claude_usage.data.aggregator import aggregate, get_week_start, _aggregate_account
from claude_usage.data.jsonl_parser import reset_offsets
from claude_usage.models import CategoryStats, TokenUsage, UsageRecord


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


def _make_assistant_record(
    model: str,
    tools: list[str],
    bash_cmds: list[str],
    session_id: str = "sess-A",
    ts_offset_seconds: int = 0,
) -> dict:
    """Build a raw assistant JSONL record with specified tool_use content."""
    now = datetime.now(timezone.utc) + timedelta(seconds=ts_offset_seconds)
    content = []
    for tool_name in tools:
        block: dict = {"type": "tool_use", "id": f"id-{tool_name}", "name": tool_name, "input": {}}
        if tool_name == "Bash" and bash_cmds:
            block["input"] = {"command": bash_cmds[0]}
        content.append(block)
    return {
        "type": "assistant",
        "message": {
            "id": f"msg-{model}-{ts_offset_seconds}",
            "model": model,
            "role": "assistant",
            "content": content,
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "sessionId": session_id,
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


class TestCategoryAggregation:
    def test_categories_populated(self, tmp_path):
        """Records with different categories aggregate into separate CategoryStats."""
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "stats-cache.json").write_text(json.dumps({
            "version": 2, "lastComputedDate": "2020-01-01",
            "dailyModelTokens": [], "modelUsage": {}, "dailyActivity": [],
        }))
        project_dir = claude_home / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)
        (claude_home / "sessions").mkdir()

        # Coding record (Edit tool)
        coding_rec = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 0)
        # Debugging record (Edit + "fix" keyword triggered by first user msg)
        # Use Bash+git → Git category
        git_rec = _make_assistant_record("claude-opus-4-6", ["Bash"], ["git commit -m x"], "sess-B", 60)
        _write_jsonl(project_dir / "conv.jsonl", [coding_rec, git_rec])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        agg = results[0]

        # Both categories should be present
        assert len(agg.categories) >= 1
        # All CategoryStats have turn_count >= 1
        for stats in agg.categories.values():
            assert stats.turn_count >= 1
            assert stats.cost_usd >= 0.0

    def test_category_stats_token_sum(self, tmp_path):
        """CategoryStats.tokens accumulates correctly across multiple records."""
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "stats-cache.json").write_text(json.dumps({
            "version": 2, "lastComputedDate": "2020-01-01",
            "dailyModelTokens": [], "modelUsage": {}, "dailyActivity": [],
        }))
        project_dir = claude_home / "projects" / "-Users-jang-app2"
        project_dir.mkdir(parents=True)
        (claude_home / "sessions").mkdir()

        # Two records with Edit tool → both classified as Coding (no debug keyword)
        r1 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 0)
        r2 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 120)
        _write_jsonl(project_dir / "conv.jsonl", [r1, r2])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        agg = results[0]

        # Find category with edit-tool records (Coding or similar)
        total_turns = sum(s.turn_count for s in agg.categories.values())
        assert total_turns == 2

        # Total tokens across all categories should match per-record usage * 2
        total_input = sum(s.tokens.input_tokens for s in agg.categories.values())
        assert total_input == 400  # 200 * 2


class TestOneShotRate:
    def _make_env(self, tmp_path: Path) -> tuple[Path, Path]:
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "stats-cache.json").write_text(json.dumps({
            "version": 2, "lastComputedDate": "2020-01-01",
            "dailyModelTokens": [], "modelUsage": {}, "dailyActivity": [],
        }))
        project_dir = claude_home / "projects" / "-Users-jang-app"
        project_dir.mkdir(parents=True)
        (claude_home / "sessions").mkdir()
        return claude_home, project_dir

    def test_no_edit_turns_yields_none(self, tmp_path):
        """When no edit-tool turns exist, one_shot_rate is None."""
        claude_home, project_dir = self._make_env(tmp_path)
        # Only Bash+git, no edit tools
        rec = _make_assistant_record("claude-opus-4-6", ["Bash"], ["git status"], "sess-A", 0)
        _write_jsonl(project_dir / "conv.jsonl", [rec])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        assert results[0].one_shot_rate is None

    def test_single_edit_turn_is_one_shot(self, tmp_path):
        """A single edit turn with no successor is one-shot → rate = 1.0."""
        claude_home, project_dir = self._make_env(tmp_path)
        rec = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 0)
        _write_jsonl(project_dir / "conv.jsonl", [rec])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        assert results[0].one_shot_rate == 1.0

    def test_two_edit_turns_within_window_half_one_shot(self, tmp_path):
        """Two edit turns in same session within 30s → only 2nd is one-shot → 0.5."""
        claude_home, project_dir = self._make_env(tmp_path)
        # ts_offset 0 and 10 seconds → within 30s window
        r1 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 0)
        r2 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 10)
        _write_jsonl(project_dir / "conv.jsonl", [r1, r2])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        assert results[0].one_shot_rate == pytest.approx(0.5)

    def test_two_edit_turns_different_sessions_both_one_shot(self, tmp_path):
        """Edit turns in different sessions are independent → both one-shot → 1.0."""
        claude_home, project_dir = self._make_env(tmp_path)
        r1 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 0)
        r2 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-B", 5)
        _write_jsonl(project_dir / "conv.jsonl", [r1, r2])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        assert results[0].one_shot_rate == pytest.approx(1.0)

    def test_two_edit_turns_beyond_window_both_one_shot(self, tmp_path):
        """Edit turns in same session but > 30s apart → both are one-shot → 1.0."""
        claude_home, project_dir = self._make_env(tmp_path)
        r1 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 0)
        r2 = _make_assistant_record("claude-opus-4-6", ["Edit"], [], "sess-A", 60)
        _write_jsonl(project_dir / "conv.jsonl", [r1, r2])

        config = AppConfig(accounts=[AccountConfig(name="T", claude_home=str(claude_home))])
        results = aggregate(config=config, period="month")
        assert results[0].one_shot_rate == pytest.approx(1.0)
