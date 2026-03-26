"""Token usage gauge bars per model."""

from __future__ import annotations

from textual.widgets import Static

from ..models import ModelUsage, TokenUsage
from ..theme import get_model_color
from ._helpers import format_tokens, make_bar

# Models to always show in the gauge (even if 0 usage)
DEFAULT_MODELS = ["opus-4.6", "sonnet-4.6", "haiku-4.5"]


class UsageGaugePanel(Static):
    """Gauge bars showing token usage per model."""

    _period: str = "week"

    def update_usage(self, models: dict[str, ModelUsage], period: str = "") -> None:
        if period:
            self._period = period

        period_label = {"day": "Today", "week": "This Week", "month": "This Month"}.get(
            self._period, self._period
        )
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
        max_total = max((mu.usage.total for _, mu in ordered), default=1) or 1

        for name, mu in ordered:
            total = mu.usage.total
            ratio = total / max_total
            color = get_model_color(name)
            bar = make_bar(ratio, width=28)
            label = f"{name:<14}"
            tokens_str = format_tokens(total) if total > 0 else "—"

            lines.append(
                f"[{color}]{label} {bar}  {tokens_str:>7}[/]"
            )

        self.update("\n".join(lines))
