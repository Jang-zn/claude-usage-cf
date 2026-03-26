"""Active sessions list widget."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import Static

from ..models import SessionInfo


class SessionListWidget(Static):
    """Table of active sessions."""

    def update_sessions(self, sessions: list[SessionInfo]) -> None:
        lines: list[str] = ["[bold]ACTIVE SESSIONS[/bold]", ""]

        if not sessions:
            lines.append("[dim]No active sessions[/]")
            self.update("\n".join(lines))
            return

        # Header
        lines.append(
            f"  {'PID':<8} {'Project':<20} {'Started':<10} {'Duration':<10} {'Model':<12}"
        )
        lines.append(f"  {'─' * 8} {'─' * 20} {'─' * 10} {'─' * 10} {'─' * 12}")

        now = datetime.now(timezone.utc)

        for s in sessions:
            project = s.project_name[:20] if s.project_name else "(unknown)"
            # Ensure started_at is tz-aware for subtraction
            started_at = s.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            started = started_at.astimezone().strftime("%H:%M")
            duration = self._format_duration(now, started_at)
            model = s.model[:12] if s.model else ""

            alive_indicator = "[green]●[/]" if s.is_alive else "[dim]○[/]"

            lines.append(
                f"  {alive_indicator} {s.pid:<6} {project:<20} {started:<10} {duration:<10} {model:<12}"
            )

        self.update("\n".join(lines))

    @staticmethod
    def _format_duration(now: datetime, started: datetime) -> str:
        delta = now - started
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "0m"
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 23:
            days = hours // 24
            hours = hours % 24
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
