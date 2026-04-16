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
from claude_usage.models import ActivityCategory, TokenUsage, UsageRecord


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


# ---------------------------------------------------------------------------
# New tests for A2 (dedup), A3 (subagents scan), A5 (token remainder)
# ---------------------------------------------------------------------------

# Assistant record WITH an explicit msg.id
SAMPLE_ASSISTANT_WITH_ID = {
    "type": "assistant",
    "message": {
        "id": "msg-abc123",
        "model": "claude-opus-4-6",
        "role": "assistant",
        "content": [],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    },
    "timestamp": "2026-04-01T10:00:00.000Z",
    "sessionId": "sess-dedup",
}

# Progress record whose inner msg.id matches the assistant above
SAMPLE_PROGRESS_SAME_ID = {
    "type": "progress",
    "data": {
        "type": "agent_progress",
        "agentId": "agent-xyz",
        "message": {
            "type": "assistant",
            "message": {
                "id": "msg-abc123",
                "model": "claude-haiku-4-5-20251001",
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 80,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
    },
    "timestamp": "2026-04-01T10:00:01.000Z",
    "sessionId": "sess-dedup",
}

# Record without msg.id (fallback key test)
SAMPLE_ASSISTANT_NO_ID = {
    "type": "assistant",
    "message": {
        "model": "claude-haiku-4-5-20251001",
        "role": "assistant",
        "content": [],
        "usage": {
            "input_tokens": 50,
            "output_tokens": 20,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    },
    "timestamp": "2026-04-01T11:00:00.000Z",
    "sessionId": "sess-fallback",
}


class TestDedupSeenIds:
    """A2: msg.id-based deduplication via seen_ids parameter."""

    def test_same_msg_id_across_two_files_counted_once(self, tmp_path):
        """Same msg.id in two different files → 1 record total when seen_ids is shared."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)

        file1 = str(project_dir / "conv1.jsonl")
        file2 = str(project_dir / "conv2.jsonl")
        _write_jsonl(file1, [SAMPLE_ASSISTANT_WITH_ID])
        _write_jsonl(file2, [SAMPLE_ASSISTANT_WITH_ID])

        seen: set[str] = set()
        r1 = parse_jsonl_file(file1, incremental=False, seen_ids=seen)
        r2 = parse_jsonl_file(file2, incremental=False, seen_ids=seen)
        assert len(r1) + len(r2) == 1

    def test_assistant_and_progress_same_id_counted_once(self, tmp_path):
        """assistant record + progress record sharing msg.id → 1 record total."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)
        filepath = str(project_dir / "conv.jsonl")
        _write_jsonl(filepath, [SAMPLE_ASSISTANT_WITH_ID, SAMPLE_PROGRESS_SAME_ID])

        seen: set[str] = set()
        records = parse_jsonl_file(filepath, incremental=False, seen_ids=seen)
        # The assistant record is parsed first; the progress record has the same inner
        # msg.id and should be skipped.
        assert len(records) == 1
        assert records[0].model == "opus-4.6"

    def test_no_seen_ids_no_dedup(self, tmp_path):
        """Without seen_ids, duplicate records in the same file are both collected."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)
        filepath = str(project_dir / "conv.jsonl")
        _write_jsonl(filepath, [SAMPLE_ASSISTANT_WITH_ID, SAMPLE_ASSISTANT_WITH_ID])

        records = parse_jsonl_file(filepath, incremental=False)
        # No dedup → both records returned
        assert len(records) == 2

    def test_fallback_key_dedup_no_msg_id(self, tmp_path):
        """Records without msg.id use session_id:timestamp as fallback dedup key."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)
        file1 = str(project_dir / "a.jsonl")
        file2 = str(project_dir / "b.jsonl")
        _write_jsonl(file1, [SAMPLE_ASSISTANT_NO_ID])
        _write_jsonl(file2, [SAMPLE_ASSISTANT_NO_ID])

        seen: set[str] = set()
        r1 = parse_jsonl_file(file1, incremental=False, seen_ids=seen)
        r2 = parse_jsonl_file(file2, incremental=False, seen_ids=seen)
        # Same session_id + timestamp → only counted once
        assert len(r1) + len(r2) == 1

    def test_parse_all_jsonl_uses_shared_dedup(self, tmp_path):
        """parse_all_jsonl internally shares seen_ids so duplicate records are deduplicated."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        project_dir.mkdir(parents=True)
        file1 = str(project_dir / "conv1.jsonl")
        file2 = str(project_dir / "conv2.jsonl")
        _write_jsonl(file1, [SAMPLE_ASSISTANT_WITH_ID])
        _write_jsonl(file2, [SAMPLE_ASSISTANT_WITH_ID])

        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert len(records) == 1


class TestSubagentsScan:
    """A3: subagents/*.jsonl and subagents/*/*.jsonl are scanned."""

    def test_subagents_dir_scanned(self, tmp_path):
        """JSONL files inside subagents/ are picked up by parse_all_jsonl."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        subagents_dir = project_dir / "subagents"
        subagents_dir.mkdir(parents=True)

        _write_jsonl(str(subagents_dir / "sub.jsonl"), [SAMPLE_ASSISTANT_WITH_ID])

        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert len(records) == 1

    def test_subagents_nested_dir_scanned(self, tmp_path):
        """JSONL files inside subagents/<id>/ (2-depth) are also picked up."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        nested_dir = project_dir / "subagents" / "agent-123"
        nested_dir.mkdir(parents=True)

        _write_jsonl(str(nested_dir / "sub.jsonl"), [SAMPLE_ASSISTANT_WITH_ID])

        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert len(records) == 1

    def test_subagents_project_name_fallback(self, tmp_path):
        """If _extract_project_name returns '' for a subagents file, fall back to parent."""
        project_dir = tmp_path / "projects" / "-Users-jang-projects-myapp"
        subagents_dir = project_dir / "subagents"
        subagents_dir.mkdir(parents=True)

        _write_jsonl(str(subagents_dir / "sub.jsonl"), [SAMPLE_ASSISTANT_WITH_ID])

        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert len(records) == 1
        # Project name should be non-empty (either extracted or fallback)
        assert records[0].project != ""

    def test_subagent_dedup_with_top_level(self, tmp_path):
        """Same msg.id in top-level and subagents/ file → counted only once."""
        project_dir = tmp_path / "projects" / "-Users-jang-myapp"
        subagents_dir = project_dir / "subagents"
        subagents_dir.mkdir(parents=True)

        _write_jsonl(str(project_dir / "conv.jsonl"), [SAMPLE_ASSISTANT_WITH_ID])
        _write_jsonl(str(subagents_dir / "sub.jsonl"), [SAMPLE_ASSISTANT_WITH_ID])

        records = parse_all_jsonl(tmp_path, lookback_days=30, incremental=False)
        assert len(records) == 1


class TestTokenRemainder:
    """A5: Remainder tokens are attributed to the first block, not lost."""

    def test_remainder_goes_to_first_block(self):
        """input_tokens=10 split across 3 tools → [4, 3, 3]."""
        content = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Write", "input": {}},
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]
        usage = TokenUsage(input_tokens=10, output_tokens=0)
        acts = _parse_activities(content, usage)
        assert len(acts) == 3
        assert acts[0].tokens.input_tokens == 4   # base(3) + remainder(1)
        assert acts[1].tokens.input_tokens == 3
        assert acts[2].tokens.input_tokens == 3

    def test_token_sum_preserved(self):
        """Total tokens across all blocks always equals original."""
        content = [
            {"type": "tool_use", "name": "A", "input": {}},
            {"type": "tool_use", "name": "B", "input": {}},
            {"type": "tool_use", "name": "C", "input": {}},
        ]
        usage = TokenUsage(
            input_tokens=10,
            output_tokens=7,
            cache_read_tokens=5,
            cache_creation_tokens=11,
        )
        acts = _parse_activities(content, usage)
        assert sum(a.tokens.input_tokens for a in acts) == 10
        assert sum(a.tokens.output_tokens for a in acts) == 7
        assert sum(a.tokens.cache_read_tokens for a in acts) == 5
        assert sum(a.tokens.cache_creation_tokens for a in acts) == 11

    def test_web_search_first_block_only(self):
        """web_search_requests attributed entirely to first block."""
        content = [
            {"type": "tool_use", "name": "Search", "input": {}},
            {"type": "tool_use", "name": "Read", "input": {}},
        ]
        usage = TokenUsage(input_tokens=4, output_tokens=0, web_search_requests=3)
        acts = _parse_activities(content, usage)
        assert acts[0].tokens.web_search_requests == 3
        assert acts[1].tokens.web_search_requests == 0

    def test_even_split_no_remainder(self):
        """Even split: input_tokens=6 across 3 tools → [2, 2, 2]."""
        content = [
            {"type": "tool_use", "name": "A", "input": {}},
            {"type": "tool_use", "name": "B", "input": {}},
            {"type": "tool_use", "name": "C", "input": {}},
        ]
        usage = TokenUsage(input_tokens=6, output_tokens=0)
        acts = _parse_activities(content, usage)
        assert all(a.tokens.input_tokens == 2 for a in acts)
