"""Incremental JSONL parser with byte offset tracking."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from ..models import (
    ActivityCategory,
    ActivityRecord,
    TokenUsage,
    UsageRecord,
)
from ..pricing import normalize_model

# Fast pre-filter before JSON parsing (check both with and without spaces)
# Also matches progress records containing nested "type":"assistant" — intentional
_ASSISTANT_MARKERS = ('"type":"assistant"', '"type": "assistant"')

# Byte offsets per file for incremental reads
_file_offsets: dict[str, int] = {}

# Compiled regex for project name extraction
_PROJECT_PATTERNS = [
    re.compile(r'-projects-(.+)'),
    re.compile(r'-workspace-(.+)'),
]
_HOME_FALLBACK = re.compile(r'^-(?:[A-Za-z]-)?[A-Z][a-z]+-[a-z]+-(.+)$')


def reset_offsets() -> None:
    """Reset all tracked byte offsets (useful for testing)."""
    _file_offsets.clear()


def _extract_project_name(filepath: str) -> str:
    """Extract project name from JSONL path.

    Path like ~/.claude/projects/-Users-jang-projects-app-in-toss-be/...
    The directory name encodes the full path with `-` replacing `/`.

    Strategy: split by known path segments like -projects- or -workspace-
    to extract the project suffix as-is (preserving hyphens in project names).
    """
    parts = Path(filepath).parts
    for part in parts:
        if not (part.startswith("-") and "-" in part[1:]):
            continue

        # Try known path patterns
        for pattern in _PROJECT_PATTERNS:
            m = pattern.search(part)
            if m:
                return m.group(1)

        # Fallback: extract after username segment
        m = _HOME_FALLBACK.match(part)
        if m:
            result = m.group(1)
            # If result looks like a bare home dir reference, use "home"
            if not result or result == part:
                return "home"
            return result

        return part
    return ""


def _parse_activities(content: list[dict], usage: TokenUsage) -> list[ActivityRecord]:
    """Extract activity records from message content blocks."""
    tool_uses = [block for block in content if block.get("type") == "tool_use"]
    if not tool_uses:
        return []

    count = len(tool_uses)

    # A5: Distribute tokens evenly with remainder attributed to the first block
    def _split(total: int) -> list[int]:
        base = total // count
        remainder = total - base * count
        return [base + remainder] + [base] * (count - 1)

    input_split = _split(usage.input_tokens)
    output_split = _split(usage.output_tokens)
    cache_read_split = _split(usage.cache_read_tokens)
    cache_creation_split = _split(usage.cache_creation_tokens)
    # web_search_requests: entire count attributed to first block only
    web_search_split = [usage.web_search_requests] + [0] * (count - 1)

    activities: list[ActivityRecord] = []
    for i, block in enumerate(tool_uses):
        name = block.get("name", "")
        input_data = block.get("input", {})
        if not isinstance(input_data, dict):
            input_data = {}

        block_tokens = TokenUsage(
            input_tokens=input_split[i],
            output_tokens=output_split[i],
            cache_read_tokens=cache_read_split[i],
            cache_creation_tokens=cache_creation_split[i],
            web_search_requests=web_search_split[i],
        )

        if name == "TeamCreate" or (isinstance(input_data.get("teamName"), str) and input_data["teamName"]):
            activities.append(ActivityRecord(
                category=ActivityCategory.TEAM,
                name=name,
                detail=input_data.get("teamName", ""),
                tokens=block_tokens,
            ))
        elif name == "Agent":
            subagent_type = input_data.get("subagent_type", "")
            activities.append(ActivityRecord(
                category=ActivityCategory.AGENT,
                name=name,
                detail=subagent_type if isinstance(subagent_type, str) else "",
                tokens=block_tokens,
            ))
        elif name.startswith("mcp__"):
            # mcp__<server>__<tool>
            parts = name.split("__", 2)
            server = parts[1] if len(parts) > 1 else ""
            tool = parts[2] if len(parts) > 2 else ""
            activities.append(ActivityRecord(
                category=ActivityCategory.MCP,
                name=server,
                detail=tool,
                tokens=block_tokens,
            ))
        else:
            activities.append(ActivityRecord(
                category=ActivityCategory.TOOL,
                name=name,
                tokens=block_tokens,
            ))

    return activities


def _extract_usage_and_model(raw_usage: dict, raw_model: str) -> tuple[TokenUsage, str] | None:
    """Extract TokenUsage and normalized model from raw dicts."""
    if not isinstance(raw_usage, dict) or not isinstance(raw_model, str):
        return None
    server_tool_use = raw_usage.get("server_tool_use", {})
    if not isinstance(server_tool_use, dict):
        server_tool_use = {}
    usage = TokenUsage(
        input_tokens=raw_usage.get("input_tokens", 0) or 0,
        output_tokens=raw_usage.get("output_tokens", 0) or 0,
        cache_read_tokens=raw_usage.get("cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=raw_usage.get("cache_creation_input_tokens", 0) or 0,
        web_search_requests=server_tool_use.get("web_search_requests", 0) or 0,
    )
    return usage, normalize_model(raw_model)


def _extract_timestamp(data: dict) -> datetime:
    """Extract timestamp from a JSONL record."""
    ts_str = data.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return datetime.now(timezone.utc)


def _parse_subagent_record(data: dict, project: str) -> UsageRecord | None:
    """Parse a subagent progress record into a UsageRecord."""
    inner = data.get("data")
    if not isinstance(inner, dict) or inner.get("type") != "agent_progress":
        return None

    # Navigate: data.message.message.{usage, model}
    wrapper = inner.get("message")
    if not isinstance(wrapper, dict):
        return None
    msg = wrapper.get("message")
    if not isinstance(msg, dict):
        return None

    result = _extract_usage_and_model(msg.get("usage"), msg.get("model", ""))
    if result is None:
        return None
    usage, model = result

    return UsageRecord(
        timestamp=_extract_timestamp(data),
        model=model,
        usage=usage,
        project=project,
        session_id=data.get("sessionId", ""),
        activities=[ActivityRecord(
            category=ActivityCategory.AGENT,
            name="Subagent",
            detail=inner.get("agentId", ""),
            tokens=TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
            ),
        )],
    )


def _make_dedup_key(msg_id: str | None, session_id: str, timestamp_iso: str) -> str:
    """Build a dedup key: prefer msg.id, fall back to session_id:timestamp."""
    if msg_id:
        return msg_id
    return f"{session_id}:{timestamp_iso}"


def parse_jsonl_file(
    filepath: str,
    incremental: bool = True,
    seen_ids: set[str] | None = None,
) -> list[UsageRecord]:
    """Parse a single JSONL file, optionally from last known offset.

    Args:
        filepath: Path to the JSONL file.
        incremental: If True, continue from the last byte offset.
        seen_ids: Optional shared set of message IDs for cross-file deduplication.
                  Records whose dedup key is already in this set are skipped,
                  and newly seen keys are added to it in-place.
    """
    records: list[UsageRecord] = []
    start_offset = _file_offsets.get(filepath, 0) if incremental else 0

    try:
        project = _extract_project_name(filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            if start_offset > 0:
                f.seek(start_offset)

            while True:
                line = f.readline()
                if not line:
                    break

                # Fast pre-filter
                if not any(m in line for m in _ASSISTANT_MARKERS):
                    continue

                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                record_type = data.get("type")
                session_id = data.get("sessionId", "")
                timestamp_iso = data.get("timestamp", "")

                if record_type == "assistant":
                    msg = data.get("message")
                    if not isinstance(msg, dict):
                        continue

                    # A2: dedup by msg.id or fallback key
                    msg_id = msg.get("id")
                    dedup_key = _make_dedup_key(msg_id, session_id, timestamp_iso)
                    if seen_ids is not None:
                        if dedup_key in seen_ids:
                            continue
                        seen_ids.add(dedup_key)

                    result = _extract_usage_and_model(msg.get("usage"), msg.get("model", ""))
                    if result is None:
                        continue
                    usage, model = result

                    content = msg.get("content", [])
                    activities = _parse_activities(content, usage) if isinstance(content, list) else []

                    records.append(UsageRecord(
                        timestamp=_extract_timestamp(data),
                        model=model,
                        usage=usage,
                        project=project,
                        session_id=session_id,
                        activities=activities,
                    ))

                elif record_type == "progress":
                    # A2: dedup progress records using inner msg.id if available
                    inner = data.get("data") or {}
                    wrapper = inner.get("message") or {} if isinstance(inner, dict) else {}
                    inner_msg = wrapper.get("message") or {} if isinstance(wrapper, dict) else {}
                    inner_msg_id = inner_msg.get("id") if isinstance(inner_msg, dict) else None
                    dedup_key = _make_dedup_key(inner_msg_id, session_id, timestamp_iso)
                    if seen_ids is not None:
                        if dedup_key in seen_ids:
                            continue
                        seen_ids.add(dedup_key)

                    rec = _parse_subagent_record(data, project)
                    if rec is not None:
                        records.append(rec)

            # Update offset to current position
            _file_offsets[filepath] = f.tell()

    except (OSError, IOError):
        pass

    return records


def parse_all_jsonl(
    claude_home: Path,
    lookback_days: int = 30,
    incremental: bool = True,
) -> list[UsageRecord]:
    """Parse all JSONL files under claude_home/projects/*/.

    Scans both top-level project JSONL files and subagents/**/*.jsonl.
    Uses a shared seen_ids set across all files for cross-file deduplication.
    Only processes files modified within lookback_days.
    """
    projects_dir = claude_home / "projects"
    if not projects_dir.exists():
        return []

    cutoff = time.time() - (lookback_days * 86400)
    records: list[UsageRecord] = []
    # A2: shared dedup set across all files in this scan
    seen_ids: set[str] = set()

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        # Collect JSONL files: top-level + subagents (max 2-depth)
        jsonl_files: list[tuple[Path, str | None]] = []

        for jsonl_file in project_dir.glob("*.jsonl"):
            jsonl_files.append((jsonl_file, None))

        # A3: subagents directory, up to 2 levels deep
        for jsonl_file in project_dir.glob("subagents/*.jsonl"):
            jsonl_files.append((jsonl_file, project_dir.name))
        for jsonl_file in project_dir.glob("subagents/*/*.jsonl"):
            jsonl_files.append((jsonl_file, project_dir.name))

        for jsonl_file, parent_dir_name in jsonl_files:
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue

            file_records = parse_jsonl_file(
                str(jsonl_file), incremental=incremental, seen_ids=seen_ids
            )

            # A3: if project name extraction returns empty, fall back to parent dir name
            if parent_dir_name is not None:
                for rec in file_records:
                    if not rec.project:
                        rec.project = _extract_project_name(
                            str(project_dir / "placeholder.jsonl")
                        ) or parent_dir_name

            records.extend(file_records)

    return records
