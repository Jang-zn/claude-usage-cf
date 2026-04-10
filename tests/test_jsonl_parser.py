"""Tests for JSONL parser."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from claude_usage.data.jsonl_parser import (
    _extract_project_name,
    _parse_activities,
    parse_jsonl_file,
    parse_all_jsonl,
    reset_offsets,
)
from claude_usage.models import ActivityCategory, TokenUsage


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
        "content": [
            {"type": "tool_use", "name": "Read", "id": "t1", "input": {"file_path": "/tmp/x"}},
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 2000,
        },
    },
    "timestamp": "2026-03-25T16:29:50.391Z",
    "sessionId": "sess-001",
}

SAMPLE_SUBAGENT = {
    "type": "progress",
    "data": {
        "type": "agent_progress",
        "agentId": "a08eb8cbd4fe53e03",
        "message": {
            "type": "assistant",
            "message": {
                "model": "claude-haiku-4-5-20251001",
                "usage": {
                    "input_tokens": 3000,
                    "output_tokens": 1000,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 200,
                },
            },
        },
    },
    "timestamp": "2026-03-25T16:30:00.000Z",
    "sessionId": "sess-001",
}

SAMPLE_USER = {"type": "user", "message": {"role": "user", "content": "hello"}}


def _write_jsonl(path: str, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestExtractProjectName:
    def test_standard_path(self):
        path = "/Users/jang/.claude/projects/-Users-jang-projects-app-in-toss-be/conversation.jsonl"
        assert _extract_project_name(path) == "app-in-toss-be"

    def test_simple_project(self):
        path = "/Users/jang/.claude/projects/-Users-jang-myproject/conv.jsonl"
        assert _extract_project_name(path) == "myproject"

    def test_no_project_dir(self):
        assert _extract_project_name("/tmp/somefile.jsonl") == ""


class TestParseActivities:
    def test_regular_tool(self):
        content = [{"type": "tool_use", "name": "Read", "input": {}}]
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        acts = _parse_activities(content, usage)
        assert len(acts) == 1
        assert acts[0].category == ActivityCategory.TOOL
        assert acts[0].name == "Read"

    def test_mcp_tool(self):
        content = [{"type": "tool_use", "name": "mcp__github__get_issues", "input": {}}]
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        acts = _parse_activities(content, usage)
        assert len(acts) == 1
        assert acts[0].category == ActivityCategory.MCP
        assert acts[0].name == "github"
        assert acts[0].detail == "get_issues"

    def test_agent_tool(self):
        content = [{"type": "tool_use", "name": "Agent", "input": {"subagent_type": "Explore"}}]
        usage = TokenUsage(input_tokens=200, output_tokens=100)
        acts = _parse_activities(content, usage)
        assert len(acts) == 1
        assert acts[0].category == ActivityCategory.AGENT
        assert acts[0].detail == "Explore"

    def test_team_tool(self):
        content = [{"type": "tool_use", "name": "TeamCreate", "input": {"teamName": "dev-team"}}]
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        acts = _parse_activities(content, usage)
        assert len(acts) == 1
        assert acts[0].category == ActivityCategory.TEAM

    def test_token_split_across_tools(self):
        content = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Write", "input": {}},
        ]
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        acts = _parse_activities(content, usage)
        assert len(acts) == 2
        assert acts[0].tokens.input_tokens == 50
        assert acts[1].tokens.input_tokens == 50

    def test_no_tool_use(self):
        content = [{"type": "text", "text": "hello"}]
        usage = TokenUsage(input_tokens=100)
        acts = _parse_activities(content, usage)
        assert acts == []


class TestParseJsonlFile:
    def test_basic_parse(self, tmp_path):
        filepath = str(tmp_path / "conv.jsonl")
        _write_jsonl(filepath, [SAMPLE_USER, SAMPLE_ASSISTANT])

        records = parse_jsonl_file(filepath, incremental=False)
        assert len(records) == 1
        rec = records[0]
        assert rec.model == "opus-4.6"
        assert rec.usage.input_tokens == 100
        assert rec.usage.output_tokens == 50
        assert rec.usage.cache_creation_tokens == 500
        assert rec.usage.cache_read_tokens == 2000
        assert rec.session_id == "sess-001"

    def test_incremental_read(self, tmp_path):
        filepath = str(tmp_path / "conv.jsonl")
        _write_jsonl(filepath, [SAMPLE_ASSISTANT])

        records1 = parse_jsonl_file(filepath, incremental=True)
        assert len(records1) == 1

        # Append another record
        with open(filepath, "a") as f:
            f.write(json.dumps(SAMPLE_ASSISTANT) + "\n")

        records2 = parse_jsonl_file(filepath, incremental=True)
        assert len(records2) == 1  # Only the new record

    def test_malformed_json_skipped(self, tmp_path):
        filepath = str(tmp_path / "conv.jsonl")
        with open(filepath, "w") as f:
            f.write('{"type":"assistant" broken json\n')
            f.write(json.dumps(SAMPLE_ASSISTANT) + "\n")

        records = parse_jsonl_file(filepath, incremental=False)
        assert len(records) == 1

    def test_missing_file(self):
        records = parse_jsonl_file("/nonexistent/file.jsonl", incremental=False)
        assert records == []

    def test_subagent_record_parsed(self, tmp_path):
        filepath = str(tmp_path / "conv.jsonl")
        _write_jsonl(filepath, [SAMPLE_USER, SAMPLE_ASSISTANT, SAMPLE_SUBAGENT])

        records = parse_jsonl_file(filepath, incremental=False)
        assert len(records) == 2

        # First record: parent assistant
        assert records[0].model == "opus-4.6"
        assert records[0].usage.input_tokens == 100

        # Second record: subagent
        sub = records[1]
        assert sub.model == "haiku-4.5"
        assert sub.usage.input_tokens == 3000
        assert sub.usage.output_tokens == 1000
        assert sub.usage.cache_creation_tokens == 500
        assert sub.usage.cache_read_tokens == 200
        assert sub.session_id == "sess-001"
        assert len(sub.activities) == 1
        assert sub.activities[0].category == ActivityCategory.AGENT
        assert sub.activities[0].name == "Subagent"
        assert sub.activities[0].detail == "a08eb8cbd4fe53e03"

    def test_subagent_missing_usage(self, tmp_path):
        """Malformed subagent record should be skipped."""
        bad_subagent = {
            "type": "progress",
            "data": {
                "type": "agent_progress",
                "agentId": "bad",
                "message": {"type": "assistant", "message": {}},
            },
            "timestamp": "2026-03-25T16:30:00.000Z",
            "sessionId": "sess-001",
        }
        filepath = str(tmp_path / "conv.jsonl")
        _write_jsonl(filepath, [bad_subagent, SAMPLE_ASSISTANT])

        records = parse_jsonl_file(filepath, incremental=False)
        assert len(records) == 1
        assert records[0].model == "opus-4.6"

    def test_subagent_incremental(self, tmp_path):
        """Incremental reads work with mixed assistant + subagent records."""
        filepath = str(tmp_path / "conv.jsonl")
        _write_jsonl(filepath, [SAMPLE_ASSISTANT])

        records1 = parse_jsonl_file(filepath, incremental=True)
        assert len(records1) == 1

        # Append a subagent record
        with open(filepath, "a") as f:
            f.write(json.dumps(SAMPLE_SUBAGENT) + "\n")

        records2 = parse_jsonl_file(filepath, incremental=True)
        assert len(records2) == 1
        assert records2[0].model == "haiku-4.5"


class TestParseAllJsonl:
    def test_finds_jsonl_files(self, tmp_path):
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)
        filepath = project_dir / "conversation.jsonl"
        _write_jsonl(str(filepath), [SAMPLE_ASSISTANT])

        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert len(records) == 1
        assert records[0].project == "myapp"

    def test_empty_projects_dir(self, tmp_path):
        (tmp_path / "projects").mkdir()
        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert records == []

    def test_no_projects_dir(self, tmp_path):
        records = parse_all_jsonl(tmp_path, lookback_days=30)
        assert records == []
