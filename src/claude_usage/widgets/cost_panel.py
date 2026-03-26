"""Cost estimate panel widget."""

from __future__ import annotations

from textual.widgets import Static

from ..models import ModelUsage
from ..pricing import calculate_cost
from ..theme import get_model_color


class CostPanelWidget(Static):
    """Shows cost breakdown by model."""

    def update_costs(self, models: dict[str, ModelUsage]) -> None:
        lines: list[str] = [
            "[bold]COST ESTIMATE[/bold]",
            "",
            f"  {'Model':<14} {'Input':>8} {'Output':>8} {'Total':>8}",
            f"  {'─' * 14} {'─' * 8} {'─' * 8} {'─' * 8}",
        ]

        grand_total = 0.0
        total_savings = 0.0

        for name, mu in models.items():
            costs = calculate_cost(name, mu.usage)
            color = get_model_color(name)
            input_c = costs["input_cost"] + costs["cache_read_cost"] + costs["cache_create_cost"]
            output_c = costs["output_cost"]
            total_c = costs["total"]
            grand_total += total_c
            total_savings += costs["cache_savings"]

            lines.append(
                f"  [{color}]{name:<14}[/] ${input_c:>7.2f} ${output_c:>7.2f} ${total_c:>7.2f}"
            )

        lines.append(f"  {'─' * 14} {'─' * 8} {'─' * 8} {'─' * 8}")

        if total_savings > 0:
            lines.append(f"  [#48c9b0]Cache savings:{'':>18} -${total_savings:>6.2f}[/]")

        lines.append(f"  [bold]{'TOTAL':<14}{'':>18} ${grand_total:>7.2f}[/]")

        self.update("\n".join(lines))
