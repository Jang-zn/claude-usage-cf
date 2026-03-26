"""Read session files from ~/.claude/sessions/*.json."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..models import SessionInfo


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def read_sessions(claude_home: Path) -> list[SessionInfo]:
    """Read all session files and return SessionInfo list."""
    sessions_dir = claude_home / "sessions"
    if not sessions_dir.exists():
        return []

    sessions: list[SessionInfo] = []
    for session_file in sessions_dir.glob("*.json"):
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        pid = data.get("pid", 0)
        session_id = data.get("sessionId", "")
        cwd = data.get("cwd", "")
        started_at_ms = data.get("startedAt", 0)

        started_at = datetime.fromtimestamp(started_at_ms / 1000, tz=timezone.utc)
        is_alive = _is_pid_alive(pid) if pid else False

        sessions.append(SessionInfo(
            pid=pid,
            session_id=session_id,
            cwd=cwd,
            started_at=started_at,
            is_alive=is_alive,
        ))

    return sessions
