"""Fetch real usage limits from Anthropic's /api/oauth/usage — called ONCE at startup."""

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
    utilization: float | None = None  # 0–100 (percent used at fetch time)
    resets_at: str | None = None      # ISO datetime string e.g. "2026-03-26T12:00:01+00:00"


@dataclass
class OAuthUsage:
    five_hour: LimitInfo = field(default_factory=LimitInfo)
    seven_day: LimitInfo = field(default_factory=LimitInfo)
    seven_day_sonnet: LimitInfo = field(default_factory=LimitInfo)


# Module-level singleton: fetched once, never refetched automatically
_cache: OAuthUsage | None = None
_fetched: bool = False


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
    """Fetch usage data from API exactly once per process. Subsequent calls return cached result."""
    global _cache, _fetched

    if _fetched:
        return _cache

    _fetched = True  # mark even on failure so we don't retry on every refresh

    token = _get_token()
    if not token:
        log.debug("No OAuth token found")
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
            raw = json.loads(r.read())
            _cache = OAuthUsage(
                five_hour=_parse_limit(raw, "five_hour"),
                seven_day=_parse_limit(raw, "seven_day"),
                seven_day_sonnet=_parse_limit(raw, "seven_day_sonnet"),
            )
            log.debug("oauth/usage fetched: %s", _cache)
            return _cache
    except urllib.error.HTTPError as e:
        log.debug("oauth/usage HTTP %d", e.code)
    except Exception as e:
        log.debug("oauth/usage error: %s", e)

    return None
