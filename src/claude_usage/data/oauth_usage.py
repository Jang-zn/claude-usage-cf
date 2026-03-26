"""
OAuth usage: API 호출 조건
  - 최초 실행 시
  - 30분 주기 싱크
  - reset 시간 도달 시 (윈도우 전환)

공개 API: get_oauth_usage(win_tokens, week_all_tokens, week_sonnet_tokens) → OAuthUsage | None
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
_BETA = "oauth-2025-04-20"
_UA = "claude-code/2.1.76"
_SYNC_INTERVAL = 1800  # 30분

_lock = threading.Lock()


@dataclass
class LimitInfo:
    utilization: float | None = None
    resets_at: str | None = None  # ISO datetime string


@dataclass
class OAuthUsage:
    five_hour: LimitInfo = field(default_factory=LimitInfo)
    seven_day: LimitInfo = field(default_factory=LimitInfo)
    seven_day_sonnet: LimitInfo = field(default_factory=LimitInfo)


# 모듈 상태 (Lock으로 보호)
_raw: OAuthUsage | None = None
_last_fetch: float = 0.0
_limit_five_hour: float | None = None
_limit_seven_day: float | None = None
_limit_seven_day_sonnet: float | None = None


def _get_token() -> str | None:
    # macOS: Keychain
    if sys.platform == "darwin":
        try:
            raw = subprocess.check_output(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).decode().strip()
            return json.loads(raw)["claudeAiOauth"]["accessToken"]
        except Exception:
            pass

    # Windows / Linux: ~/.claude/.credentials.json
    try:
        creds_path = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / ".credentials.json"
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        return data["claudeAiOauth"]["accessToken"]
    except Exception:
        return None


def _parse_limit(data: dict, key: str) -> LimitInfo:
    item = data.get(key)
    if not isinstance(item, dict):
        return LimitInfo()
    return LimitInfo(utilization=item.get("utilization"), resets_at=item.get("resets_at"))


def _resets_at_ts(info: LimitInfo) -> float | None:
    if not info.resets_at:
        return None
    try:
        return datetime.fromisoformat(info.resets_at).timestamp()
    except Exception:
        return None


def _should_refetch(now: float) -> bool:
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


def _do_fetch() -> None:
    """API 호출 및 상태 갱신. _lock 보유 상태에서 호출."""
    global _raw, _last_fetch, _limit_five_hour, _limit_seven_day, _limit_seven_day_sonnet

    token = _get_token()
    if not token:
        return

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
            # reset 발생 시 limit 재역산
            _limit_five_hour = None
            _limit_seven_day = None
            _limit_seven_day_sonnet = None
            log.debug("oauth/usage fetched: %s", _raw)
    except urllib.error.HTTPError as e:
        log.debug("oauth/usage HTTP %d", e.code)
    except Exception as e:
        log.debug("oauth/usage error: %s", e)


def get_oauth_usage(
    win_tokens: int,
    week_all_tokens: int,
    week_sonnet_tokens: int,
) -> OAuthUsage | None:
    """
    필요 시 API를 호출하고, 저장된 limit으로 현재 토큰 → % 를 계산해 반환.
    실패 시 None 반환.
    """
    global _limit_five_hour, _limit_seven_day, _limit_seven_day_sonnet

    with _lock:
        now = time.time()
        if _should_refetch(now):
            _do_fetch()

        if _raw is None:
            return None

        # limit 역산 (None인 항목만)
        if _limit_five_hour is None and _raw.five_hour.utilization and win_tokens > 0:
            _limit_five_hour = win_tokens / (_raw.five_hour.utilization / 100)

        if _limit_seven_day is None and _raw.seven_day.utilization and week_all_tokens > 0:
            _limit_seven_day = week_all_tokens / (_raw.seven_day.utilization / 100)

        if _limit_seven_day_sonnet is None and _raw.seven_day_sonnet.utilization and week_sonnet_tokens > 0:
            _limit_seven_day_sonnet = week_sonnet_tokens / (_raw.seven_day_sonnet.utilization / 100)

        def pct(tokens: int, limit: float | None) -> float | None:
            return min(tokens / limit * 100, 100.0) if limit else None

        return OAuthUsage(
            five_hour=LimitInfo(pct(win_tokens, _limit_five_hour), _raw.five_hour.resets_at),
            seven_day=LimitInfo(pct(week_all_tokens, _limit_seven_day), _raw.seven_day.resets_at),
            seven_day_sonnet=LimitInfo(pct(week_sonnet_tokens, _limit_seven_day_sonnet), _raw.seven_day_sonnet.resets_at),
        )
