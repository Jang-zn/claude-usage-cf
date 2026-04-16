"""Tests for src/claude_usage/cli.py argparse setup."""

from __future__ import annotations

import subprocess
import sys

import pytest

from claude_usage.cli import _build_parser, _interval_to_seconds


# ── _interval_to_seconds ──────────────────────────────────────────────────────

class TestIntervalToSeconds:
    def test_seconds(self):
        assert _interval_to_seconds("30s") == 30

    def test_minutes(self):
        assert _interval_to_seconds("1m") == 60
        assert _interval_to_seconds("5m") == 300

    def test_hours(self):
        assert _interval_to_seconds("1h") == 3600

    def test_case_insensitive(self):
        assert _interval_to_seconds("1M") == 60
        assert _interval_to_seconds("1H") == 3600

    def test_invalid(self):
        with pytest.raises(ValueError):
            _interval_to_seconds("invalid")


# ── parser structure ──────────────────────────────────────────────────────────

class TestParserStructure:
    def setup_method(self):
        self.parser = _build_parser()

    def test_default_no_subcommand(self):
        args = self.parser.parse_args([])
        assert args.command is None
        assert args.config is None

    def test_config_option(self):
        args = self.parser.parse_args(["--config", "/some/path.yaml"])
        assert args.config == "/some/path.yaml"

    def test_export_subcommand_defaults(self):
        args = self.parser.parse_args(["export"])
        assert args.command == "export"
        assert args.format == "csv"
        assert args.out is None
        assert args.period == "week"

    def test_export_format_json(self):
        args = self.parser.parse_args(["export", "--format", "json"])
        assert args.format == "json"

    def test_export_format_csv(self):
        args = self.parser.parse_args(["export", "--format", "csv"])
        assert args.format == "csv"

    def test_export_out_path(self, tmp_path):
        out = str(tmp_path / "output.csv")
        args = self.parser.parse_args(["export", "--out", out])
        assert args.out == out

    def test_export_period(self):
        for period in ("day", "week", "month"):
            args = self.parser.parse_args(["export", "--period", period])
            assert args.period == period

    def test_export_invalid_format(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["export", "--format", "xml"])

    def test_menubar_install_defaults(self):
        args = self.parser.parse_args(["menubar", "install"])
        assert args.command == "menubar"
        assert args.menubar_command == "install"
        assert args.interval == "1m"

    def test_menubar_install_interval(self):
        args = self.parser.parse_args(["menubar", "install", "--interval", "5m"])
        assert args.interval == "5m"

    def test_menubar_uninstall(self):
        args = self.parser.parse_args(["menubar", "uninstall"])
        assert args.command == "menubar"
        assert args.menubar_command == "uninstall"

    def test_config_with_export(self):
        args = self.parser.parse_args(["--config", "cfg.yaml", "export", "--format", "json"])
        assert args.config == "cfg.yaml"
        assert args.command == "export"
        assert args.format == "json"


# ── help flags (no crash) ─────────────────────────────────────────────────────

class TestHelpFlags:
    """Verify --help flags exit 0 and produce output."""

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "claude_usage.cli"] + list(extra_args),
            capture_output=True,
            text=True,
        )

    def test_root_help(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "export" in result.stdout

    def test_export_help(self):
        result = self._run("export", "--help")
        assert result.returncode == 0
        assert "--format" in result.stdout
        assert "--period" in result.stdout

    def test_menubar_help(self):
        result = self._run("menubar", "--help")
        assert result.returncode == 0

    def test_menubar_install_help(self):
        result = self._run("menubar", "install", "--help")
        assert result.returncode == 0
        assert "--interval" in result.stdout
