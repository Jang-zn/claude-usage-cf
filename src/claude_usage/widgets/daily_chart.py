"""Daily usage horizontal bar chart."""

from __future__ import annotations

from datetime import datetime

from textual.widgets import Static

from ..models import DailyUsage
from ..theme import COLORS
from ._helpers import format_tokens, make_bar


class DailyChartWidget(Static):
    """Horizontal bar chart of daily token usage."""

    def update_daily(self, daily: list[DailyUsage]) -> None:
        lines: list[str] = ["[bold]DAILY USAGE[/bold]", ""]

        if not daily:
            lines.append("[dim]No data[/]")
            self.update("\n".join(lines))
            return

        max_tokens = max((d.total_tokens for d in daily), default=1) or 1

        for d in daily:
            # Parse date to get day abbreviation
            try:
                dt = datetime.strptime(d.date, "%Y-%m-%d")
                day_abbr = dt.strftime("%a")
                date_str = dt.strftime("%m/%d")
            except ValueError:
                day_abbr = d.date[:3]
                date_str = d.date

            ratio = d.total_tokens / max_tokens
            bar = make_bar(ratio, width=24)
            tokens_str = format_tokens(d.total_tokens)

            lines.append(
                f"  {day_abbr} {date_str} │ [#f0a500]{bar}[/] {tokens_str:>6}"
            )

        self.update("\n".join(lines))
