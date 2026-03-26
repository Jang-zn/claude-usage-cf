"""
OAuth usage: API 호출 조건
  - 최초 실행 시
  - 30분 주기 싱크
  - reset 시간 도달 시 (윈도우 전환)
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
_BETA = "oauth-2025-04-20"
_UA = "claude-code/2.1.76"
_SYNC_INTERVAL = 1800  # 30분


@dataclass
class LimitInfo:
    utilization: float | None = None
    resets_at: str | None = None  # ISO datetime string


@dataclass
class OAuthUsage:
    five_hour: LimitInfo = field(default_factory=LimitInfo)
    seven_day: LimitInfo = field(default_factory=LimitInfo)
    seven_day_sonnet: LimitInfo = field(default_factory=LimitInfo)


_raw: OAuthUsage | None = None
_last_fetch: float = 0.0

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


def _resets_at_ts(info: LimitInfo) -> float | None:
    """resets_at ISO string → unix timestamp. None이면 None."""
    if not info.resets_at:
        return None
    try:
        return datetime.fromisoformat(info.resets_at).timestamp()
    except Exception:
        return None


def _should_refetch(now: float) -> bool:
    """재호출 필요 여부: 미호출 / 30분 경과 / 어떤 reset 시간이라도 지남."""
    if _raw is None:
        return True
    if now - _last_fetch >= _SYNC_INTERVAL:
        return True
    for info in (_raw.five_hour, _raw.seven_day, _raw.seven_day_sonnet):
        ts = _resets_at_ts(info)
        if ts and _last_fetch < ts <= now:
            log.debug("reset time passed (%s), triggering refetch", info.resets_at)
            return True
    return False


def _do_fetch() -> bool:
    """API 호출. 성공 시 _raw / _last_fetch 업데이트, 실패 시 False 반환."""
    global _raw, _last_fetch, _limit_five_hour, _limit_seven_day, _limit_seven_day_sonnet

    token = _get_token()
    if not token:
        return False

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
            _last_fetch = time.time()
            # reset 발생 시 limit 재역산을 위해 초기화
            _limit_five_hour = None
            _limit_seven_day = None
            _limit_seven_day_sonnet = None
            log.debug("oauth/usage fetched: %s", _raw)
            return True
    except urllib.error.HTTPError as e:
        log.debug("oauth/usage HTTP %d", e.code)
    except Exception as e:
        log.debug("oauth/usage error: %s", e)
    return False


def fetch_once() -> OAuthUsage | None:
    """조건 충족 시 API 호출 (최초 / 30분 / reset 도달). 아니면 no-op."""
    if _should_refetch(time.time()):
        _do_fetch()
    return _raw


def store_limits(
    win_tokens: int,
    week_all_tokens: int,
    week_sonnet_tokens: int,
) -> None:
    """utilization% + 로컬 토큰으로 절대 limit 역산. None인 항목만 계산."""
    global _limit_five_hour, _limit_seven_day, _limit_seven_day_sonnet

    if _raw is None:
        return

    if _limit_five_hour is None and _raw.five_hour.utilization and win_tokens > 0:
        _limit_five_hour = win_tokens / (_raw.five_hour.utilization / 100)
        log.debug("five_hour limit derived: %.0f", _limit_five_hour)

    if _limit_seven_day is None and _raw.seven_day.utilization and week_all_tokens > 0:
        _limit_seven_day = week_all_tokens / (_raw.seven_day.utilization / 100)
        log.debug("seven_day limit derived: %.0f", _limit_seven_day)

    if _limit_seven_day_sonnet is None and _raw.seven_day_sonnet.utilization and week_sonnet_tokens > 0:
        _limit_seven_day_sonnet = week_sonnet_tokens / (_raw.seven_day_sonnet.utilization / 100)
        log.debug("seven_day_sonnet limit derived: %.0f", _limit_seven_day_sonnet)


def compute_current(
    win_tokens: int,
    week_all_tokens: int,
    week_sonnet_tokens: int,
) -> OAuthUsage | None:
    """저장된 limit으로 현재 토큰 → % 계산."""
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
