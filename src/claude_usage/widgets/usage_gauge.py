"""Token usage gauge bars per model."""

from __future__ import annotations

from textual.widgets import Static

from ..models import AggregatedUsage, ModelUsage, TokenUsage
from ..theme import get_model_color
from ._helpers import format_tokens, make_bar

# Models to always show in the gauge (even if 0 usage)
DEFAULT_MODELS = ["opus-4.6", "sonnet-4.6", "haiku-4.5"]


class UsageGaugePanel(Static):
    """Gauge bars showing token usage per model."""

    _period: str = "week"

    def update_usage(
        self,
        models: dict[str, ModelUsage],
        period: str = "",
        one_shot_rate: float | None = None,
    ) -> None:
        if period:
            self._period = period

        period_label = {
            "day": "Today",
            "session": "This Session (5h)",
            "week": "This Week",
            "month": "This Month",
        }.get(self._period, self._period)
        lines: list[str] = [f"[bold]TOKEN USAGE ({period_label})[/bold]", ""]

        # Ensure all default models are shown
        shown = set()
        all_models = dict(models)
        for default_model in DEFAULT_MODELS:
            if default_model not in all_models:
                all_models[default_model] = ModelUsage(model=default_model)

        # Display in order: defaults first, then any extras
        ordered = []
        for dm in DEFAULT_MODELS:
            if dm in all_models:
                ordered.append((dm, all_models[dm]))
                shown.add(dm)
        for name, mu in all_models.items():
            if name not in shown:
                ordered.append((name, mu))

        # Scale bars relative to the model with most usage
        max_total = max((mu.usage.itpm_total for _, mu in ordered), default=1) or 1

        for name, mu in ordered:
            total = mu.usage.itpm_total
            ratio = total / max_total
            color = get_model_color(name)
            bar = make_bar(ratio, width=28)
            label = f"{name:<14}"
            tokens_str = format_tokens(total) if total > 0 else "—"

            if mu.turn_count > 0:
                avg = total // mu.turn_count
                avg_str = f"  [dim]~{format_tokens(avg)}/turn[/]"
            else:
                avg_str = ""

            lines.append(
                f"[{color}]{label} {bar}  {tokens_str:>7}[/]{avg_str}"
            )

        # ── One-shot rate ───────────────────────────────
        if one_shot_rate is None:
            lines.append("  [dim]One-shot: n/a[/]")
        else:
            pct = round(one_shot_rate * 100)
            lines.append(f"  [dim]One-shot:[/] [bold]{pct}%[/]")

        self.update("\n".join(lines))
