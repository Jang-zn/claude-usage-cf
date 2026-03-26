"""Fetch real usage data from Anthropic's /api/oauth/usage — refreshed every 5 minutes."""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
_BETA = "oauth-2025-04-20"
_UA = "claude-code/2.1.76"
_REFRESH_INTERVAL = 300  # 5분


@dataclass
class LimitInfo:
    utilization: float | None = None  # 0–100 (percent used)
    resets_at: str | None = None      # ISO datetime string


@dataclass
class OAuthUsage:
    five_hour: LimitInfo = field(default_factory=LimitInfo)
    seven_day: LimitInfo = field(default_factory=LimitInfo)
    seven_day_sonnet: LimitInfo = field(default_factory=LimitInfo)


_cache: OAuthUsage | None = None
_last_fetch: float = 0.0


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
    """5분 간격으로 갱신. 실패 시 마지막 성공 결과 반환."""
    global _cache, _last_fetch

    now = time.time()
    if _cache is not None and (now - _last_fetch) < _REFRESH_INTERVAL:
        return _cache

    token = _get_token()
    if not token:
        log.debug("No OAuth token found")
        return _cache

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
            raw = json.loads(r.read())
            _cache = OAuthUsage(
                five_hour=_parse_limit(raw, "five_hour"),
                seven_day=_parse_limit(raw, "seven_day"),
                seven_day_sonnet=_parse_limit(raw, "seven_day_sonnet"),
            )
            _last_fetch = now
            log.debug("oauth/usage refreshed: %s", _cache)
    except urllib.error.HTTPError as e:
        log.debug("oauth/usage HTTP %d", e.code)
        if _cache is None:
            # 첫 호출 실패 시 다음 refresh에서 재시도하도록 타임스탬프 갱신 안 함
            pass
        else:
            _last_fetch = now  # 실패해도 5분 뒤 재시도
    except Exception as e:
        log.debug("oauth/usage error: %s", e)

    return _cache
