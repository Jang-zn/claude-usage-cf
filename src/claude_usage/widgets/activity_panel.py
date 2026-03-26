"""Quota status panel — session window + weekly usage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from textual.widgets import Static

from ..models import AggregatedUsage
from ..theme import get_model_color
from ._helpers import format_tokens, make_bar

if TYPE_CHECKING:
    from ..data.oauth_usage import OAuthUsage

DEFAULT_MODELS = ["opus-4.6", "sonnet-4.6", "haiku-4.5"]


def _fmt_reset(ts: int | str | None) -> str:
    if ts is None:
        return ""
    if isinstance(ts, str):
        from datetime import datetime as _dt
        dt = _dt.fromisoformat(ts).astimezone()
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    now = datetime.now(timezone.utc)
    secs = max(int((dt - now).total_seconds()), 0)
    h, rem = divmod(secs // 60, 60)
    clock = dt.strftime("%H:%M")
    if secs < 60:
        return f"[#f0a500]< 1m[/] (resets {clock})"
    return f"[#f0a500]{h}h {rem:02d}m[/] (resets {clock})"


class ActivityPanelWidget(Static):
    """Shows session window + weekly quota status."""

    _data: AggregatedUsage | None = None

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh_render)

    def _refresh_render(self) -> None:
        if self._data is not None:
            self._draw(self._data)

    def update_activity(self, data: AggregatedUsage) -> None:
        self._data = data
        self._draw(data)

    def _draw(self, data: AggregatedUsage) -> None:
        lines: list[str] = ["[bold]QUOTA STATUS[/bold]"]
        oauth = data.oauth_usage  # OAuthUsage | None

        # ── Session (5-hour window) ────────────────────
        lines.append("")

        if oauth is not None:
            self._draw_oauth_section(lines, oauth)
        else:
            self._draw_local_window(lines, data)

        # ── Weekly Usage ───────────────────────────────
        lines.append("")

        if oauth is not None and oauth.seven_day.utilization is not None:
            # Real data from API
            pct = oauth.seven_day.utilization
            ratio = pct / 100
            bar = make_bar(ratio, width=20)
            color = "bold red" if pct > 90 else ("bold yellow" if pct > 70 else "#e8725c")
            lines.append(f"  [bold]Weekly[/bold]  [dim](all models)[/dim]")
            lines.append(f"  [{color}]{bar}  {pct:.0f}% used[/]")
            reset_str = _fmt_reset(oauth.seven_day.resets_at)
            if reset_str:
                lines.append(f"  [dim]  {reset_str}[/dim]".replace("[/dim][dim]", ""))

            if oauth.seven_day_sonnet.utilization is not None:
                pct_s = oauth.seven_day_sonnet.utilization
                ratio_s = pct_s / 100
                bar_s = make_bar(ratio_s, width=20)
                color_s = "bold red" if pct_s > 90 else ("bold yellow" if pct_s > 70 else "#f0a500")
                lines.append(f"  [bold]Weekly Sonnet[/bold]")
                lines.append(f"  [{color_s}]{bar_s}  {pct_s:.0f}% used[/]")
                reset_s = _fmt_reset(oauth.seven_day_sonnet.resets_at)
                if reset_s:
                    lines.append(f"  [dim]  {reset_s}[/dim]".replace("[/dim][dim]", ""))
        else:
            # Fallback: local estimate
            lines.append("  [bold]Weekly Usage[/bold]  [dim](est. 45M limit)[/dim]")
            for model in DEFAULT_MODELS:
                mu = data.models.get(model)
                limit = mu.weekly_limit if mu else 45_000_000
                used = mu.usage.total if mu else 0
                left = max(limit - used, 0)
                pct_used = used / limit * 100 if limit > 0 else 0.0
                ratio_used = min(used / limit, 1.0) if limit > 0 else 0.0
                color = get_model_color(model)
                if pct_used > 90:
                    style = "bold red"
                elif pct_used > 70:
                    style = "bold yellow"
                else:
                    style = color
                bar = make_bar(ratio_used, width=14)
                lines.append(
                    f"  [{style}]{model:<12} {bar}  {format_tokens(left):>7} left[/]"
                )

        self.update("\n".join(lines))

    def _draw_oauth_section(self, lines: list[str], oauth: "OAuthUsage") -> None:
        fh = oauth.five_hour
        if fh.utilization is not None:
            pct = fh.utilization
            ratio = pct / 100
            bar = make_bar(ratio, width=20)
            color = "bold red" if pct > 90 else ("bold yellow" if pct > 70 else "#e8725c")
            lines.append(f"  [bold]Session[/bold]  [dim](5-hour window)[/dim]")
            lines.append(f"  [{color}]{bar}  {pct:.0f}% used[/]")
            reset_str = _fmt_reset(fh.resets_at)
            if reset_str:
                lines.append(f"  [dim]  {reset_str}[/dim]".replace("[/dim][dim]", ""))
        else:
            lines.append("  [bold]Session[/bold]  [dim]no data[/dim]")

    def _draw_local_window(self, lines: list[str], data: AggregatedUsage) -> None:
        lines.append("  [bold]5-Hour Window[/bold]  [dim](local estimate)[/dim]")
        win = data.window
        win_total = sum(win.by_model.values())
        active = [(m, win.by_model[m]) for m in DEFAULT_MODELS if win.by_model.get(m, 0) > 0]

        if active:
            max_win = max(v for _, v in active)
            for model, tokens in active:
                color = get_model_color(model)
                bar = make_bar(tokens / max_win, width=14)
                lines.append(f"  [{color}]{model:<12} {bar}  {format_tokens(tokens):>7}[/]")
            lines.append(f"  [dim]Total: [/dim][bold]{format_tokens(win_total)}[/bold]")
        else:
            lines.append("  [dim]No usage in last 5h[/dim]")

        if win.reset_at:
            now = datetime.now(timezone.utc)
            secs = max(int((win.reset_at - now).total_seconds()), 0)
            h, rem = divmod(secs // 60, 60)
            clock = win.reset_at.astimezone().strftime("%H:%M")
            if secs < 60:
                lines.append(f"  [dim]Oldest expires [/dim][#f0a500]< 1m[/] [dim](at {clock})[/dim]")
            else:
                lines.append(f"  [dim]Oldest expires in [/dim][#f0a500]{h}h {rem:02d}m[/] [dim](at {clock})[/dim]")
