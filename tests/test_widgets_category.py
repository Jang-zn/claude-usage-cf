"""Tests for CategoryPanelWidget."""

from __future__ import annotations

from claude_usage.models import (
    AggregatedUsage,
    ActivitySummary,
    CategoryStats,
    TokenUsage,
)
from claude_usage.widgets.category_panel import CategoryPanelWidget


def test_category_panel_import():
    """CategoryPanelWidget can be imported from the widgets package."""
    from claude_usage.widgets import CategoryPanelWidget as _CPW
    assert _CPW is CategoryPanelWidget


def _render(widget: CategoryPanelWidget, data: AggregatedUsage) -> str:
    """Call update_categories and return the rendered text string."""
    widget.update_categories(data)
    # Static.render() returns the current Content object; str() gives plain text.
    return str(widget.render())


def test_category_panel_empty_shows_placeholder():
    """With empty AggregatedUsage, panel shows 'No activity yet'."""
    widget = CategoryPanelWidget()
    rendered = _render(widget, AggregatedUsage())
    assert "No activity yet" in rendered


def test_category_panel_renders_category_names():
    """Panel renders category names when data is present."""
    widget = CategoryPanelWidget()

    categories = {
        "Coding": CategoryStats(
            category="Coding",
            tokens=TokenUsage(input_tokens=5000, output_tokens=2000),
            turn_count=10,
            cost_usd=0.05,
        ),
        "Debugging": CategoryStats(
            category="Debugging",
            tokens=TokenUsage(input_tokens=1000, output_tokens=500),
            turn_count=3,
            cost_usd=0.01,
        ),
    }
    data = AggregatedUsage(categories=categories)
    rendered = _render(widget, data)

    assert "Coding" in rendered
    assert "Debugging" in rendered


def test_category_panel_shows_top_tools():
    """Panel shows top tools section when by_tool data is present."""
    widget = CategoryPanelWidget()

    categories = {
        "Coding": CategoryStats(
            category="Coding",
            tokens=TokenUsage(input_tokens=5000, output_tokens=2000),
            turn_count=5,
        ),
    }
    activity = ActivitySummary(
        by_tool={"Edit": 3000, "Read": 1500, "Bash": 800, "Write": 400, "Glob": 200}
    )
    data = AggregatedUsage(categories=categories, activity=activity)
    rendered = _render(widget, data)

    assert "TOP TOOLS" in rendered
    assert "Edit" in rendered


def test_category_panel_zero_token_categories_hidden():
    """Categories with zero tokens are not shown."""
    widget = CategoryPanelWidget()

    categories = {
        "Coding": CategoryStats(
            category="Coding",
            tokens=TokenUsage(input_tokens=5000, output_tokens=2000),
            turn_count=5,
        ),
        "General": CategoryStats(
            category="General",
            tokens=TokenUsage(),  # zero tokens, zero turns
            turn_count=0,
        ),
    }
    data = AggregatedUsage(categories=categories)
    rendered = _render(widget, data)

    # Coding should appear, General with zero tokens+turns should not
    assert "Coding" in rendered
    # General has both zero tokens and zero turns → filtered out
    assert "General" not in rendered


def test_category_panel_no_tools_no_section():
    """When by_tool is empty, no TOP TOOLS section is rendered."""
    widget = CategoryPanelWidget()

    categories = {
        "Coding": CategoryStats(
            category="Coding",
            tokens=TokenUsage(input_tokens=1000, output_tokens=500),
            turn_count=2,
        ),
    }
    data = AggregatedUsage(categories=categories, activity=ActivitySummary())
    rendered = _render(widget, data)

    assert "TOP TOOLS" not in rendered
