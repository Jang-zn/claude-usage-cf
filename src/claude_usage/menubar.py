"""SwiftBar menu bar plugin generator for claude-usage."""

from __future__ import annotations

import json
import os
import platform
import stat
from pathlib import Path

# Default weekly token limit for Claude Pro/Max plans
WEEKLY_LIMIT = 45_000_000

# SwiftBar refresh interval mapping (seconds -> SwiftBar suffix)
_INTERVAL_MAP = [
    (3600, "1h"),
    (300, "5m"),
    (60, "1m"),
    (30, "30s"),
    (0, "30s"),  # fallback for anything ≤ 30s
]


def _seconds_to_swiftbar_interval(seconds: int) -> str:
    """Convert refresh interval in seconds to SwiftBar filename suffix."""
    for threshold, suffix in _INTERVAL_MAP:
        if seconds >= threshold:
            return suffix
    return "30s"


def _default_plugins_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "SwiftBar" / "Plugins"


def _generate_plugin_script(claude_home: Path) -> str:
    """Generate the standalone Python plugin script content."""
    cache_path = claude_home / "stats-cache.json"
    # Use string representation so the embedded path is resolved at install time
    cache_path_str = str(cache_path)

    script = f'''#!/usr/bin/env python3
# <swiftbar.title>Claude Usage</swiftbar.title>
# <swiftbar.version>v1.0.0</swiftbar.version>
# <swiftbar.author>claude-usage</swiftbar.author>
# <swiftbar.author.github>jang</swiftbar.author.github>
# <swiftbar.desc>Monitor Claude Code token usage and quota status.</swiftbar.desc>
# <swiftbar.abouturl>https://github.com/jang/claude-usage-cf</swiftbar.abouturl>

import json
import sys
from pathlib import Path

CACHE_PATH = Path({cache_path_str!r})
WEEKLY_LIMIT = {WEEKLY_LIMIT}


def fmt_tokens(n: int) -> str:
    """Format token count as e.g. 24.5M or 850K."""
    if n >= 1_000_000:
        return f"{{n / 1_000_000:.1f}}M"
    if n >= 1_000:
        return f"{{n / 1_000:.1f}}K"
    return str(n)


def load_cache() -> dict | None:
    try:
        if not CACHE_PATH.exists():
            return None
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_weekly_tokens(data: dict) -> tuple[int, dict[str, int]]:
    """
    Return (total_weekly_tokens, by_model_dict).

    stats-cache.json schema (relevant fields):
      dailyModelTokens: [{{date, tokensByModel: {{<model>: <int>, ...}}}}, ...]
      lastComputedDate: "YYYY-MM-DD"

    We sum all days within the current ISO week (Mon-Sun).
    """
    from datetime import date, timedelta

    today = date.today()
    # ISO week: Monday is weekday 0
    week_start = today - timedelta(days=today.weekday())
    week_dates = {{(week_start + timedelta(days=i)).isoformat() for i in range(7)}}

    total = 0
    by_model: dict[str, int] = {{}}

    for entry in data.get("dailyModelTokens", []):
        if entry.get("date", "") not in week_dates:
            continue
        for model, count in entry.get("tokensByModel", {{}}).items():
            # Normalize to short name: take last segment after '/'
            short = model.split("/")[-1]
            by_model[short] = by_model.get(short, 0) + count
            total += count

    return total, by_model


def usage_color(ratio: float) -> str:
    """Return SwiftBar color based on usage ratio."""
    if ratio >= 0.90:
        return "red"
    if ratio >= 0.75:
        return "orange"
    return "green"


def main() -> None:
    data = load_cache()
    if data is None:
        print("⚡️ claude: no data")
        print("---")
        print(f"Cache file not found: {{CACHE_PATH}}")
        return

    total, by_model = get_weekly_tokens(data)
    ratio = total / WEEKLY_LIMIT if WEEKLY_LIMIT > 0 else 0.0
    color = usage_color(ratio)

    total_fmt = fmt_tokens(total)
    limit_fmt = fmt_tokens(WEEKLY_LIMIT)
    pct = f"{{ratio * 100:.0f}}%"

    # Menu bar title line
    print(f"⚡️ {{total_fmt}}/{{limit_fmt}} ({{pct}}) | color={{color}}")
    print("---")

    # Section header
    print(f"Claude Weekly Usage | size=13")
    print(f"{{total_fmt}} / {{limit_fmt}} tokens used | size=12")

    # Progress bar (ASCII, 20 chars)
    filled = min(int(ratio * 20), 20)
    bar = "█" * filled + "░" * (20 - filled)
    print(f"{{bar}} | font=Menlo size=11")
    print("---")

    if by_model:
        print("Model Breakdown | size=12")
        # Sort by usage descending
        for model, tokens in sorted(by_model.items(), key=lambda x: x[1], reverse=True):
            model_pct = tokens / WEEKLY_LIMIT * 100 if WEEKLY_LIMIT > 0 else 0
            print(f"  {{model:<28}} {{fmt_tokens(tokens):>7}}  ({{model_pct:.1f}}%) | font=Menlo size=11")
        print("---")

    last_date = data.get("lastComputedDate", "unknown")
    print(f"Last updated: {{last_date}} | size=10 color=gray")
    print("Refresh | refresh=true")


if __name__ == "__main__":
    main()
'''
    return script


def install_menubar(
    claude_home: Path | None = None,
    refresh_interval_sec: int = 60,
    plugins_dir: Path | None = None,
) -> Path:
    """Install the SwiftBar plugin script.

    Args:
        claude_home: Path to the Claude home directory (~/.claude by default).
        refresh_interval_sec: How often SwiftBar should refresh the plugin.
            Mapped to SwiftBar naming convention (30s / 1m / 5m / 1h).
        plugins_dir: Override the SwiftBar Plugins directory (mainly for testing).

    Returns:
        Path to the installed plugin script.

    Raises:
        RuntimeError: If running on a non-macOS platform.
    """
    if platform.system() != "Darwin":
        raise RuntimeError("SwiftBar is macOS only")

    if claude_home is None:
        claude_home = Path.home() / ".claude"

    interval = _seconds_to_swiftbar_interval(refresh_interval_sec)

    if plugins_dir is None:
        plugins_dir = _default_plugins_dir()

    plugins_dir.mkdir(parents=True, exist_ok=True)

    plugin_file = plugins_dir / f"claude-usage.{interval}.py"

    script_content = _generate_plugin_script(claude_home)
    plugin_file.write_text(script_content, encoding="utf-8")

    # Make executable (rwxr-xr-x)
    plugin_file.chmod(0o755)

    return plugin_file


def uninstall_menubar(plugins_dir: Path | None = None) -> bool:
    """Remove the SwiftBar plugin script if it exists.

    Args:
        plugins_dir: Override the SwiftBar Plugins directory (mainly for testing).

    Returns:
        True if the file was deleted, False if it did not exist.
    """
    if plugins_dir is None:
        plugins_dir = _default_plugins_dir()

    # Find any installed claude-usage plugin (regardless of interval suffix)
    removed = False
    for candidate in plugins_dir.glob("claude-usage.*.py"):
        candidate.unlink()
        removed = True

    return removed


def check_swiftbar_installed() -> bool:
    """Check if SwiftBar.app is installed on this machine."""
    return Path("/Applications/SwiftBar.app").exists()
