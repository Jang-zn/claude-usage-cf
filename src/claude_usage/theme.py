"""Anthropic-inspired color theme and Textual CSS."""

# Color palette
COLORS = {
    "bg": "#1a1a2e",
    "bg_surface": "#16213e",
    "bg_panel": "#0f3460",
    "opus": "#e8725c",
    "sonnet": "#f0a500",
    "haiku": "#48c9b0",
    "text": "#f5f0eb",
    "text_dim": "#8b8b8b",
    "border": "#8b7355",
    "accent": "#e94560",
    "warning": "#ff6b6b",
    "success": "#48c9b0",
    "coral": "#e8725c",
    "amber": "#f0a500",
}

MODEL_COLORS = {
    "opus": COLORS["opus"],
    "sonnet": COLORS["sonnet"],
    "haiku": COLORS["haiku"],
}


def get_model_color(model_short: str) -> str:
    """Get color for a model short name."""
    low = model_short.lower()
    for family, color in MODEL_COLORS.items():
        if family in low:
            return color
    return COLORS["text"]


APP_CSS = """
Screen {
    background: #1a1a2e;
    overflow-y: auto;
}

#main-container {
    width: 100%;
    height: auto;
}

HeaderWidget {
    width: 100%;
    height: 1;
    background: #16213e;
    padding: 0 2;
    color: #f5f0eb;
}

UsageGaugePanel {
    width: 100%;
    height: auto;
    min-height: 5;
    background: #1a1a2e;
    border: solid #8b7355;
    padding: 0 1;
}

#middle-row {
    width: 100%;
    height: auto;
    min-height: 12;
}

#bottom-row {
    width: 100%;
    height: auto;
    min-height: 10;
}

DailyChartWidget {
    width: 1fr;
    height: auto;
    min-height: 10;
    background: #1a1a2e;
    border: solid #8b7355;
    padding: 0 1;
}

CostPanelWidget {
    width: 1fr;
    height: auto;
    min-height: 10;
    background: #1a1a2e;
    border: solid #8b7355;
    padding: 0 1;
}

ProjectChartWidget {
    width: 1fr;
    height: auto;
    min-height: 12;
    background: #1a1a2e;
    border: solid #8b7355;
    padding: 0 1;
}

QuotaPanelWidget {
    width: 1fr;
    height: auto;
    min-height: 12;
    background: #1a1a2e;
    border: solid #8b7355;
    padding: 0 1;
}

SessionListWidget {
    width: 100%;
    height: auto;
    min-height: 5;
    background: #1a1a2e;
    border: solid #8b7355;
    padding: 0 1;
}

.footer-bar {
    dock: bottom;
    width: 100%;
    height: 1;
    background: #16213e;
    color: #8b8b8b;
}
"""
