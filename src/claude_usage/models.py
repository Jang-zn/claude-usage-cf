"""Data models for Claude Usage Tracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ActivityCategory(Enum):
    TOOL = "Tool"
    MCP = "MCP"
    AGENT = "Agent"
    TEAM = "Team"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def total_with_cache(self) -> int:
        return self.total + self.cache_read_tokens + self.cache_creation_tokens

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        return self


@dataclass
class ActivityRecord:
    category: ActivityCategory
    name: str  # tool name or MCP server name
    detail: str = ""  # subtool or subagent type
    tokens: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class UsageRecord:
    timestamp: datetime
    model: str
    usage: TokenUsage
    project: str = ""
    session_id: str = ""
    activities: list[ActivityRecord] = field(default_factory=list)


@dataclass
class SessionInfo:
    pid: int
    session_id: str
    cwd: str
    started_at: datetime
    model: str = ""
    is_alive: bool = False

    @property
    def project_name(self) -> str:
        return self.cwd.rstrip("/").rsplit("/", 1)[-1] if self.cwd else ""


@dataclass
class ModelUsage:
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    weekly_limit: int = 45_000_000
    request_count: int = 0


@dataclass
class DailyUsage:
    date: str
    total_tokens: int = 0
    by_model: dict[str, int] = field(default_factory=dict)


@dataclass
class ProjectUsage:
    project: str
    total_tokens: int = 0


@dataclass
class ActivitySummary:
    by_category: dict[str, int] = field(default_factory=dict)  # category -> tokens
    by_tool: dict[str, int] = field(default_factory=dict)  # tool_name -> tokens


@dataclass
class WindowUsage:
    """5-hour rolling window usage per model."""
    by_model: dict[str, int] = field(default_factory=dict)  # model -> total tokens (input+output)
    reset_at: datetime | None = None  # oldest_record.timestamp + 5h


@dataclass
class AggregatedUsage:
    models: dict[str, ModelUsage] = field(default_factory=dict)
    daily: list[DailyUsage] = field(default_factory=list)
    projects: list[ProjectUsage] = field(default_factory=list)
    sessions: list[SessionInfo] = field(default_factory=list)
    activity: ActivitySummary = field(default_factory=ActivitySummary)
    window: WindowUsage = field(default_factory=WindowUsage)
    oauth_usage: object | None = None  # OAuthUsage | None (avoid circular import)
    period: str = "week"
    account_name: str = "Personal"
