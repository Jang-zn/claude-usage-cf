"""
OAuth usage: API 1회 호출로 limit 역산, 이후 로컬 토큰으로 계산.

flow:
  1. fetch_once() → API 호출, utilization% + resets_at 취득
  2. store_limits() → utilization% / local_tokens 으로 절대 limit 역산 + 저장
  3. compute_current() → 매 refresh마다 local_tokens / stored_limit 으로 % 계산
"""

from __future__ import annotations

import json
import logging
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
_BETA = "oauth-2025-04-20"
_UA = "claude-code/2.1.76"


@dataclass
class LimitInfo:
    utilization: float | None = None  # 0–100 (%)
    resets_at: str | None = None      # ISO datetime string


@dataclass
class OAuthUsage:
    five_hour: LimitInfo = field(default_factory=LimitInfo)
    seven_day: LimitInfo = field(default_factory=LimitInfo)
    seven_day_sonnet: LimitInfo = field(default_factory=LimitInfo)


# API에서 1회 가져온 raw snapshot
_raw: OAuthUsage | None = None
_fetched: bool = False

# 역산된 절대 limit 값 (tokens)
_limit_five_hour: float | None = None
_limit_seven_day: float | None = None
_limit_seven_day_sonnet: float | None = None


def _get_token() -> str | None:
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode().strip()
        return json.loads(raw)["claudeAiOauth"]["accessToken"]
    except Exception:
        return None


def _parse_limit(raw: dict, key: str) -> LimitInfo:
    item = raw.get(key)
    if not isinstance(item, dict):
        return LimitInfo()
    return LimitInfo(
        utilization=item.get("utilization"),
        resets_at=item.get("resets_at"),
    )


def fetch_once() -> OAuthUsage | None:
    """API를 1회만 호출해 raw utilization%와 resets_at을 가져옴."""
    global _raw, _fetched

    if _fetched:
        return _raw

    _fetched = True
    token = _get_token()
    if not token:
        return None

    req = urllib.request.Request(
        _ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
            "anthropic-beta": _BETA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            _raw = OAuthUsage(
                five_hour=_parse_limit(data, "five_hour"),
                seven_day=_parse_limit(data, "seven_day"),
                seven_day_sonnet=_parse_limit(data, "seven_day_sonnet"),
            )
            log.debug("oauth/usage fetched: %s", _raw)
    except urllib.error.HTTPError as e:
        log.debug("oauth/usage HTTP %d", e.code)
    except Exception as e:
        log.debug("oauth/usage error: %s", e)

    return _raw


def store_limits(
    win_tokens: int,
    week_all_tokens: int,
    week_sonnet_tokens: int,
) -> None:
    """
    API utilization%와 현재 로컬 토큰 수로 절대 limit을 역산해 저장.
    limit = local_tokens / (utilization / 100)
    이미 저장된 경우 스킵.
    """
    global _limit_five_hour, _limit_seven_day, _limit_seven_day_sonnet

    if _raw is None:
        return

    if _limit_five_hour is None and _raw.five_hour.utilization and win_tokens > 0:
        _limit_five_hour = win_tokens / (_raw.five_hour.utilization / 100)
        log.debug("five_hour limit derived: %.0f tokens", _limit_five_hour)

    if _limit_seven_day is None and _raw.seven_day.utilization and week_all_tokens > 0:
        _limit_seven_day = week_all_tokens / (_raw.seven_day.utilization / 100)
        log.debug("seven_day limit derived: %.0f tokens", _limit_seven_day)

    if _limit_seven_day_sonnet is None and _raw.seven_day_sonnet.utilization and week_sonnet_tokens > 0:
        _limit_seven_day_sonnet = week_sonnet_tokens / (_raw.seven_day_sonnet.utilization / 100)
        log.debug("seven_day_sonnet limit derived: %.0f tokens", _limit_seven_day_sonnet)


def compute_current(
    win_tokens: int,
    week_all_tokens: int,
    week_sonnet_tokens: int,
) -> OAuthUsage | None:
    """저장된 limit으로 현재 로컬 토큰을 % 로 변환해 반환."""
    if _raw is None:
        return None

    def pct(tokens: int, limit: float | None) -> float | None:
        if limit and limit > 0:
            return min(tokens / limit * 100, 100.0)
        return None

    return OAuthUsage(
        five_hour=LimitInfo(
            utilization=pct(win_tokens, _limit_five_hour),
            resets_at=_raw.five_hour.resets_at,
        ),
        seven_day=LimitInfo(
            utilization=pct(week_all_tokens, _limit_seven_day),
            resets_at=_raw.seven_day.resets_at,
        ),
        seven_day_sonnet=LimitInfo(
            utilization=pct(week_sonnet_tokens, _limit_seven_day_sonnet),
            resets_at=_raw.seven_day_sonnet.resets_at,
        ),
    )
