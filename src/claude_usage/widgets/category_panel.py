"""Category usage bar chart panel."""

from __future__ import annotations

from textual.widgets import Static

from ..models import AggregatedUsage, CategoryStats
from ..theme import COLORS
from ._helpers import format_tokens, make_bar


# Display order + color hints for the 13 categories
CATEGORY_ORDER = [
    "Coding",
    "Debugging",
    "Feature",
    "Refactoring",
    "Testing",
    "Git",
    "Build-Deploy",
    "Exploration",
    "Planning",
    "Delegation",
    "Brainstorming",
    "Conversation",
    "General",
]

# Cycle through a small palette for category bars
_BAR_COLORS = [
    "#e8725c",  # coral
    "#f0a500",  # amber
    "#48c9b0",  # teal
    "#e94560",  # accent
    "#a78bfa",  # purple
    "#34d399",  # green
    "#60a5fa",  # blue
    "#f472b6",  # pink
]


def _bar_color(idx: int) -> str:
    return _BAR_COLORS[idx % len(_BAR_COLORS)]


class CategoryPanelWidget(Static):
    """Horizontal bar chart of category token usage + top tools."""

    def update_categories(self, data: AggregatedUsage) -> None:
        lines: list[str] = ["[bold]CATEGORY USAGE[/bold]", ""]

        categories = data.categories

        if not categories:
            lines.append("[dim]No activity yet[/]")
            self.update("\n".join(lines))
            return

        # Build sorted list: use CATEGORY_ORDER first, then any extras
        ordered: list[CategoryStats] = []
        seen: set[str] = set()
        for cat_name in CATEGORY_ORDER:
            if cat_name in categories:
                ordered.append(categories[cat_name])
                seen.add(cat_name)
        for cat_name, stat in categories.items():
            if cat_name not in seen:
                ordered.append(stat)

        # Filter to non-zero only
        ordered = [s for s in ordered if s.tokens.billable_total > 0 or s.turn_count > 0]

        if not ordered:
            lines.append("[dim]No activity yet[/]")
            self.update("\n".join(lines))
            return

        max_tokens = max((s.tokens.billable_total for s in ordered), default=1) or 1

        for idx, stat in enumerate(ordered):
            tokens = stat.tokens.billable_total
            ratio = tokens / max_tokens if max_tokens > 0 else 0
            bar = make_bar(ratio, width=22)
            color = _bar_color(idx)
            name = stat.category[:14]
            tokens_str = format_tokens(tokens)
            turn_str = f"{stat.turn_count}t" if stat.turn_count else ""

            lines.append(
                f"  {name:<14} [{color}]{bar}[/] {tokens_str:>6}"
                + (f"  [dim]{turn_str}[/]" if turn_str else "")
            )

        # ── Top tools section ─────────────────────────
        by_tool = data.activity.by_tool
        if by_tool:
            lines.append("")
            lines.append("[bold]TOP TOOLS[/bold]")
            top_tools = sorted(by_tool.items(), key=lambda x: x[1], reverse=True)[:5]
            max_tool_tokens = top_tools[0][1] if top_tools else 1
            for tidx, (tool_name, tok) in enumerate(top_tools):
                ratio = tok / max_tool_tokens if max_tool_tokens > 0 else 0
                bar = make_bar(ratio, width=18)
                color = _bar_color(tidx + 3)
                name_str = tool_name[:14]
                lines.append(
                    f"  {name_str:<14} [{color}]{bar}[/] {format_tokens(tok):>6}"
                )

        self.update("\n".join(lines))
