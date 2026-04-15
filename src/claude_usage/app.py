"""Main Textual App for Claude Usage Tracker."""

from __future__ import annotations

import logging

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static
from textual.binding import Binding
from textual import work

from .config import AppConfig, load_config
from .models import AggregatedUsage
from .theme import APP_CSS
from .widgets import (
    QuotaPanelWidget,
    CostPanelWidget,
    DailyChartWidget,
    HeaderWidget,
    ProjectChartWidget,
    SessionListWidget,
    UsageGaugePanel,
)

log = logging.getLogger(__name__)


class ClaudeUsageApp(App):
    """Claude Code CLI Usage Tracker TUI."""

    CSS = APP_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "cycle_account", "Account"),
        Binding("1", "period_day", "Day"),
        Binding("5", "period_session", "Session"),
        Binding("7", "period_week", "Week"),
        Binding("3", "period_month", "Month"),
    ]

    def __init__(self, config_path: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config_path = config_path
        self.current_account_index: int = 0
        self.current_period: str = "week"
        self.config: AppConfig = AppConfig()
        self.aggregated_data: AggregatedUsage = AggregatedUsage()

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]q[/] Quit │ [b]r[/] Refresh │ [b]a[/] Account │ "
            "[b]1[/] Day │ [b]5[/] Session │ [b]7[/] Week │ [b]3[/] Month",
            classes="footer-bar",
        )
        with VerticalScroll(id="main-container"):
            yield HeaderWidget()
            yield UsageGaugePanel()
            with Horizontal(id="middle-row"):
                yield ProjectChartWidget()
                yield QuotaPanelWidget()
            with Horizontal(id="bottom-row"):
                yield DailyChartWidget()
                yield CostPanelWidget()
            yield SessionListWidget()

    def on_mount(self) -> None:
        if self._config_path:
            import yaml
            from pathlib import Path
            from .config import _parse_config

            path = Path(self._config_path).expanduser()
            if path.exists():
                raw = yaml.safe_load(path.read_text())
                self.config = _parse_config(raw) if raw else AppConfig()
            else:
                self.config = load_config()
        else:
            self.config = load_config()

        self.current_period = self.config.display.default_period
        self.action_refresh()
        self.set_interval(self.config.display.refresh_interval, lambda: self.refresh_data(force_oauth=False))

    def action_refresh(self) -> None:
        self.refresh_data(force_oauth=True)

    @work(thread=True)
    def refresh_data(self, force_oauth: bool = False) -> None:
        from .data.aggregator import aggregate_usage

        try:
            account = self.config.accounts[self.current_account_index]
            data = aggregate_usage(account, self.current_period, self.config, force_oauth=force_oauth)
            self.call_from_thread(self.update_widgets, data)
        except Exception:
            log.exception("Error refreshing data")

    def update_widgets(self, data: AggregatedUsage) -> None:
        self.aggregated_data = data

        widgets_updates = [
            (HeaderWidget, lambda w: w.update_info(data.account_name, data.period)),
            (UsageGaugePanel, lambda w: w.update_usage(data.models, data.period)),
            (CostPanelWidget, lambda w: w.update_costs(data.models)),
            (DailyChartWidget, lambda w: w.update_daily(data.daily)),
            (ProjectChartWidget, lambda w: w.update_projects(data.projects)),
            (QuotaPanelWidget, lambda w: w.update_activity(data)),
            (SessionListWidget, lambda w: w.update_sessions(data.sessions)),
        ]

        for widget_class, updater in widgets_updates:
            try:
                widget = self.query_one(widget_class)
                updater(widget)
            except Exception:
                log.debug("Error updating %s", widget_class.__name__, exc_info=True)

    def action_cycle_account(self) -> None:
        self.current_account_index = (
            (self.current_account_index + 1) % len(self.config.accounts)
        )
        self.action_refresh()

    def action_period_day(self) -> None:
        self.current_period = "day"
        self.refresh_data(force_oauth=False)

    def action_period_session(self) -> None:
        self.current_period = "session"
        self.refresh_data(force_oauth=False)

    def action_period_week(self) -> None:
        self.current_period = "week"
        self.refresh_data(force_oauth=False)

    def action_period_month(self) -> None:
        self.current_period = "month"
        self.refresh_data(force_oauth=False)
