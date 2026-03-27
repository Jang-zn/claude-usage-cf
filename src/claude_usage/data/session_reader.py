"""Read session files from ~/.claude/sessions/*.json."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..models import SessionInfo


if sys.platform == "win32":
    import ctypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259  # Win32 sentinel; a process that legitimately exits with 259 is a false positive

    def _is_pid_alive(pid: int) -> bool:
        # os.kill(pid, 0) sends CTRL_C_EVENT on Windows; use Win32 API instead
        handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == _STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
else:
    def _is_pid_alive(pid: int) -> bool:
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
