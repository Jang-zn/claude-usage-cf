"""Compact header widget."""

from __future__ import annotations

from datetime import datetime

from textual.widgets import Static


class HeaderWidget(Static):
    """Compact single-bar header."""

    _account: str = "Personal"
    _period: str = "day"

    def on_mount(self) -> None:
        self._render_header()
        self.set_interval(1.0, self._refresh_time)

    def _refresh_time(self) -> None:
        self._render_header()

    def update_info(self, account: str, period: str) -> None:
        self._account = account
        self._period = period
        self._render_header()

    def _render_header(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        period_label = {
            "day": "Today",
            "week": "This Week",
            "month": "This Month",
        }.get(self._period, self._period)

        account = self._account or "Personal"
        self.update(
            f"\u25c6 [bold]Claude Usage Tracker[/bold]"
            f"  [dim]\u2500\u2500[/dim]  "
            f"{account}"
            f"  [dim]\u00b7[/dim]  "
            f"[yellow]{period_label}[/yellow]"
            f"  [dim]\u00b7  {now}[/dim]"
        )
