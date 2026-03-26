"""CLI entry point for Claude Usage Tracker."""

import argparse

from .app import ClaudeUsageApp


def main():
    parser = argparse.ArgumentParser(description="Claude Code CLI Usage Tracker")
    parser.add_argument("--config", help="Path to config YAML file")
    args = parser.parse_args()

    app = ClaudeUsageApp(config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
