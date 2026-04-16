"""Data models for Claude Usage Tracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


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
    web_search_requests: int = 0

    @property
    def itpm_total(self) -> int:
        """ITPM 산정 기준: input + output + cache_creation (cache_read 제외).
        Used for quota/window/gauge calculations where cache_read is excluded."""
        return self.input_tokens + self.output_tokens + self.cache_creation_tokens

    @property
    def billable_total(self) -> int:
        """전체 청구 토큰: input + output + cache_read + cache_creation.
        Used for cost calculations and export where all billed tokens must be counted."""
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.web_search_requests += other.web_search_requests
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
    category: str = "General"
    tools_used: list[str] = field(default_factory=list)
    bash_commands: list[str] = field(default_factory=list)


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
        return Path(self.cwd).name if self.cwd else ""


@dataclass
class ModelUsage:
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    weekly_limit: int = 45_000_000
    request_count: int = 0   # 개별 API 호출 수
    turn_count: int = 0      # 질문 턴 수 (세션 내 30초 간격으로 구분)


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
    by_model: dict[str, int] = field(default_factory=dict)  # model -> ITPM tokens
    reset_at: datetime | None = None  # oldest_record.timestamp + 5h


@dataclass
class CategoryStats:
    category: str
    tokens: TokenUsage = field(default_factory=TokenUsage)
    turn_count: int = 0
    cost_usd: float = 0.0


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
    categories: dict[str, CategoryStats] = field(default_factory=dict)
    one_shot_rate: float | None = None
