"""Unified CLI entry point for claude-usage.

Sub-commands
------------
(default)               Launch the Textual TUI dashboard.
export                  Export usage data to CSV or JSON.
menubar install         Install SwiftBar plugin (macOS only).
menubar uninstall       Remove SwiftBar plugin.

Global options
--------------
--config PATH           Path to config YAML file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _interval_to_seconds(interval: str) -> int:
    """Convert SwiftBar-style interval string to seconds.

    Accepts: 30s, 1m, 5m, 1h  (case-insensitive).
    Raises ValueError on unrecognised format.
    """
    interval = interval.strip().lower()
    if interval.endswith("h"):
        return int(interval[:-1]) * 3600
    if interval.endswith("m"):
        return int(interval[:-1]) * 60
    if interval.endswith("s"):
        return int(interval[:-1])
    raise ValueError(
        f"Unrecognised interval '{interval}'. "
        "Use formats like 30s, 1m, 5m, 1h."
    )


# ── sub-command handlers ──────────────────────────────────────────────────────

def _cmd_tui(args: argparse.Namespace) -> None:
    """Launch the Textual TUI dashboard."""
    from .app import ClaudeUsageApp

    app = ClaudeUsageApp(config_path=args.config)
    app.run()


def _cmd_export(args: argparse.Namespace) -> None:
    """Aggregate usage and export to file."""
    from .config import load_config, _parse_config
    import yaml

    # Load config
    if args.config:
        path = Path(args.config).expanduser()
        if path.exists():
            raw = yaml.safe_load(path.read_text())
            config = _parse_config(raw) if raw else load_config()
        else:
            print(f"Warning: config file '{args.config}' not found, using defaults.", file=sys.stderr)
            config = load_config()
    else:
        config = load_config()

    from .data.aggregator import aggregate_usage
    from .export import export_usage

    account = config.accounts[0]
    period = getattr(args, "period", "week") or "week"

    print(f"Aggregating {period} usage for account '{account.name}'…", file=sys.stderr)
    agg = aggregate_usage(account, period, config, force_oauth=False)

    out_path = Path(args.out).expanduser() if args.out else None
    fmt = args.format or "csv"

    result = export_usage(agg, fmt=fmt, out=out_path)
    print(f"Exported to: {result}")


def _cmd_menubar_install(args: argparse.Namespace) -> None:
    """Install SwiftBar plugin."""
    import platform

    if platform.system() != "Darwin":
        print("Error: SwiftBar is macOS only.", file=sys.stderr)
        sys.exit(1)

    from .menubar import install_menubar, check_swiftbar_installed
    from .config import load_config, _parse_config
    import yaml

    # Resolve interval
    interval_str = getattr(args, "interval", None) or "1m"
    try:
        interval_sec = _interval_to_seconds(interval_str)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Determine claude_home from config
    if args.config:
        path = Path(args.config).expanduser()
        raw = yaml.safe_load(path.read_text()) if path.exists() else None
        config = _parse_config(raw) if raw else load_config()
    else:
        config = load_config()

    claude_home = config.accounts[0].claude_home_path

    if not check_swiftbar_installed():
        print(
            "Warning: SwiftBar.app not found in /Applications. "
            "Install SwiftBar from https://swiftbar.app first.",
            file=sys.stderr,
        )

    plugin_path = install_menubar(claude_home=claude_home, refresh_interval_sec=interval_sec)
    print(f"Installed SwiftBar plugin: {plugin_path}")


def _cmd_menubar_uninstall(args: argparse.Namespace) -> None:
    """Uninstall SwiftBar plugin."""
    import platform

    if platform.system() != "Darwin":
        print("Error: SwiftBar is macOS only.", file=sys.stderr)
        sys.exit(1)

    from .menubar import uninstall_menubar

    removed = uninstall_menubar()
    if removed:
        print("SwiftBar plugin removed.")
    else:
        print("No SwiftBar plugin found.")


# ── argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-usage",
        description="Claude Code CLI Usage Tracker",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to config YAML file",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # ── export ────────────────────────────────────────────────────────────────
    export_parser = subparsers.add_parser(
        "export",
        help="Export usage data to CSV or JSON",
    )
    export_parser.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        metavar="FORMAT",
        help="Output format: csv (default) or json",
    )
    export_parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help=(
            "Output file path. "
            "Defaults to ~/.claude-usage/exports/{YYYYMMDD-HHMMSS}.{format}"
        ),
    )
    export_parser.add_argument(
        "--period",
        choices=["day", "week", "month"],
        default="week",
        metavar="PERIOD",
        help="Aggregation period: day, week (default), or month",
    )

    # ── menubar ───────────────────────────────────────────────────────────────
    menubar_parser = subparsers.add_parser(
        "menubar",
        help="Manage the macOS SwiftBar menu bar widget",
    )
    menubar_sub = menubar_parser.add_subparsers(dest="menubar_command", metavar="<action>")

    install_parser = menubar_sub.add_parser(
        "install",
        help="Install SwiftBar plugin (macOS only)",
    )
    install_parser.add_argument(
        "--interval",
        metavar="INTERVAL",
        default="1m",
        help="SwiftBar refresh interval: 30s, 1m (default), 5m, 1h",
    )

    menubar_sub.add_parser(
        "uninstall",
        help="Remove SwiftBar plugin",
    )

    return parser


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        # Default: launch TUI
        _cmd_tui(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "menubar":
        if not hasattr(args, "menubar_command") or args.menubar_command is None:
            parser.parse_args(["menubar", "--help"])
            sys.exit(0)
        if args.menubar_command == "install":
            _cmd_menubar_install(args)
        elif args.menubar_command == "uninstall":
            _cmd_menubar_uninstall(args)
        else:
            parser.parse_args(["menubar", "--help"])
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
