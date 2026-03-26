"""Configuration loading with defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AccountConfig:
    name: str = "Personal"
    claude_home: str = "~/.claude"

    @property
    def claude_home_path(self) -> Path:
        return Path(self.claude_home).expanduser()


@dataclass
class LimitConfig:
    model: str = "opus"
    weekly_tokens: int = 45_000_000


@dataclass
class DisplayConfig:
    refresh_interval: int = 5
    default_period: str = "day"
    show_cost: bool = True


@dataclass
class AppConfig:
    accounts: list[AccountConfig] = field(default_factory=lambda: [AccountConfig()])
    limits: list[LimitConfig] = field(default_factory=lambda: [
        LimitConfig("opus", 45_000_000),
        LimitConfig("sonnet", 45_000_000),
        LimitConfig("haiku", 45_000_000),
    ])
    display: DisplayConfig = field(default_factory=DisplayConfig)

    def get_limit(self, model_family: str) -> int:
        for lim in self.limits:
            if lim.model in model_family or model_family in lim.model:
                return lim.weekly_tokens
        return 45_000_000


CONFIG_PATHS = [
    Path("~/.config/claude-usage/config.yaml").expanduser(),
    Path("~/.config/claude-usage/config.yml").expanduser(),
]


def load_config() -> AppConfig:
    """Load config from YAML file or return defaults."""
    for path in CONFIG_PATHS:
        if path.exists():
            try:
                raw = yaml.safe_load(path.read_text())
                if not raw:
                    return AppConfig()
                return _parse_config(raw)
            except Exception:
                return AppConfig()
    return AppConfig()


def _parse_config(raw: dict) -> AppConfig:
    accounts = []
    for a in raw.get("accounts", []):
        accounts.append(AccountConfig(
            name=a.get("name", "Personal"),
            claude_home=a.get("claude_home", "~/.claude"),
        ))

    limits = []
    for lim in raw.get("limits", []):
        limits.append(LimitConfig(
            model=lim.get("model", "opus"),
            weekly_tokens=lim.get("weekly_tokens", 45_000_000),
        ))

    disp_raw = raw.get("display", {})
    display = DisplayConfig(
        refresh_interval=disp_raw.get("refresh_interval", 5),
        default_period=disp_raw.get("default_period", "week"),
        show_cost=disp_raw.get("show_cost", True),
    )

    return AppConfig(
        accounts=accounts or [AccountConfig()],
        limits=limits or [
            LimitConfig("opus", 45_000_000),
            LimitConfig("sonnet", 45_000_000),
            LimitConfig("haiku", 45_000_000),
        ],
        display=display,
    )
