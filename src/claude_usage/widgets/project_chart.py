"""Project usage horizontal bar chart."""

from __future__ import annotations

from textual.widgets import Static

from ..models import ProjectUsage
from ..theme import COLORS
from ._helpers import format_tokens, make_bar


class ProjectChartWidget(Static):
    """Horizontal bar chart of project token usage, top 5 + rest."""

    def update_projects(self, projects: list[ProjectUsage]) -> None:
        lines: list[str] = ["[bold]PROJECT USAGE[/bold]", ""]

        if not projects:
            lines.append("[dim]No data[/]")
            self.update("\n".join(lines))
            return

        # Sort descending
        sorted_projects = sorted(projects, key=lambda p: p.total_tokens, reverse=True)
        top = sorted_projects[:5]
        rest = sorted_projects[5:]

        max_tokens = top[0].total_tokens if top else 1

        for p in top:
            ratio = p.total_tokens / max_tokens if max_tokens > 0 else 0
            bar = make_bar(ratio, width=24)
            name = p.project[:16] if p.project else "(unknown)"
            tokens_str = format_tokens(p.total_tokens)

            lines.append(
                f"  {name:<16} [#e8725c]{bar}[/] {tokens_str:>6}"
            )

        if rest:
            rest_total = sum(r.total_tokens for r in rest)
            lines.append(
                f"  [dim]({len(rest)} more){'':<10} {format_tokens(rest_total):>6}[/]"
            )

        self.update("\n".join(lines))
