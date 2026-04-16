"""Tests for the SwiftBar menu bar plugin generator."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from claude_usage.menubar import (
    WEEKLY_LIMIT,
    _seconds_to_swiftbar_interval,
    check_swiftbar_installed,
    install_menubar,
    uninstall_menubar,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache(tmp_path: Path, by_model: dict[str, int] | None = None) -> Path:
    """Write a minimal stats-cache.json to tmp_path and return its path."""
    today = date.today().isoformat()
    tokens_by_model = by_model or {"claude-opus-4-6": 5_000_000, "claude-sonnet-4-6": 3_000_000}

    data = {
        "lastComputedDate": today,
        "dailyModelTokens": [
            {"date": today, "tokensByModel": tokens_by_model}
        ],
        "modelUsage": {},
        "dailyActivity": [],
    }
    cache_file = tmp_path / "stats-cache.json"
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return cache_file


# ---------------------------------------------------------------------------
# _seconds_to_swiftbar_interval
# ---------------------------------------------------------------------------

class TestSecondsToSwiftbarInterval:
    def test_3600_maps_to_1h(self):
        assert _seconds_to_swiftbar_interval(3600) == "1h"

    def test_7200_maps_to_1h(self):
        assert _seconds_to_swiftbar_interval(7200) == "1h"

    def test_300_maps_to_5m(self):
        assert _seconds_to_swiftbar_interval(300) == "5m"

    def test_600_maps_to_5m(self):
        assert _seconds_to_swiftbar_interval(600) == "5m"

    def test_60_maps_to_1m(self):
        assert _seconds_to_swiftbar_interval(60) == "1m"

    def test_90_maps_to_1m(self):
        assert _seconds_to_swiftbar_interval(90) == "1m"

    def test_30_maps_to_30s(self):
        assert _seconds_to_swiftbar_interval(30) == "30s"

    def test_10_maps_to_30s(self):
        assert _seconds_to_swiftbar_interval(10) == "30s"


# ---------------------------------------------------------------------------
# install_menubar
# ---------------------------------------------------------------------------

class TestInstallMenubar:
    def test_creates_file(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        assert result.exists()

    def test_file_has_correct_name_1m(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        assert result.name == "claude-usage.1m.py"

    def test_file_has_correct_name_5m(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=300,
            plugins_dir=plugins_dir,
        )
        assert result.name == "claude-usage.5m.py"

    def test_file_has_correct_name_1h(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=3600,
            plugins_dir=plugins_dir,
        )
        assert result.name == "claude-usage.1h.py"

    def test_file_is_executable(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        file_stat = result.stat()
        # Check owner execute bit
        assert file_stat.st_mode & stat.S_IXUSR, "File should be executable by owner"
        # Check group and other execute bits (0o755)
        assert file_stat.st_mode & stat.S_IXGRP, "File should be executable by group"
        assert file_stat.st_mode & stat.S_IXOTH, "File should be executable by others"

    def test_file_has_shebang(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        content = result.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env python3"), "Must start with python3 shebang"

    def test_plugins_dir_created_if_missing(self, tmp_path):
        plugins_dir = tmp_path / "deep" / "nested" / "plugins"
        assert not plugins_dir.exists()
        install_menubar(claude_home=tmp_path, plugins_dir=plugins_dir)
        assert plugins_dir.exists()

    def test_overwrite_existing(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result1 = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        original_content = result1.read_text()
        # Reinstall — should overwrite without error
        result2 = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        assert result1 == result2
        assert result2.read_text() == original_content  # same content

    def test_returns_path(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        result = install_menubar(claude_home=tmp_path, plugins_dir=plugins_dir)
        assert isinstance(result, Path)

    def test_raises_on_non_darwin(self, tmp_path, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Linux")
        with pytest.raises(RuntimeError, match="macOS only"):
            install_menubar(claude_home=tmp_path, plugins_dir=tmp_path / "plugins")

    def test_raises_on_windows(self, tmp_path, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Windows")
        with pytest.raises(RuntimeError, match="macOS only"):
            install_menubar(claude_home=tmp_path, plugins_dir=tmp_path / "plugins")


# ---------------------------------------------------------------------------
# Plugin script execution: no data case
# ---------------------------------------------------------------------------

class TestPluginScriptNoData:
    def test_no_data_output(self, tmp_path):
        """Running the plugin with no stats-cache.json should output 'no data'."""
        plugins_dir = tmp_path / "plugins"
        # claude_home points to tmp_path which has no stats-cache.json
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )

        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "no data" in result.stdout.lower(), (
            f"Expected 'no data' in output. Got: {result.stdout!r}"
        )

    def test_no_data_first_line_format(self, tmp_path):
        """First line with no data should have the ⚡️ prefix."""
        plugins_dir = tmp_path / "plugins"
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = result.stdout.strip().split("\n")[0]
        assert "⚡️" in first_line or "no data" in first_line.lower()


# ---------------------------------------------------------------------------
# Plugin script execution: with data
# ---------------------------------------------------------------------------

class TestPluginScriptWithData:
    def test_token_output_format(self, tmp_path):
        """Running the plugin with stats-cache.json should show tokens/45M."""
        plugins_dir = tmp_path / "plugins"
        _make_cache(tmp_path, {"claude-opus-4-6": 24_500_000})
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        output = result.stdout
        # Should show the token/limit format somewhere in first line
        first_line = output.split("\n")[0]
        assert "/45.0M" in first_line or "45M" in first_line, (
            f"Expected limit in first line. Got: {first_line!r}"
        )

    def test_total_tokens_shown(self, tmp_path):
        """Total tokens (24.5M) should appear in menu bar line."""
        plugins_dir = tmp_path / "plugins"
        _make_cache(tmp_path, {"claude-opus-4-6": 24_500_000})
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = result.stdout.split("\n")[0]
        assert "24.5M" in first_line, (
            f"Expected '24.5M' in first line. Got: {first_line!r}"
        )

    def test_separator_line_present(self, tmp_path):
        """Output should include SwiftBar '---' separator."""
        plugins_dir = tmp_path / "plugins"
        _make_cache(tmp_path)
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "---" in result.stdout

    def test_model_breakdown_shown(self, tmp_path):
        """Model names should appear in the output breakdown."""
        plugins_dir = tmp_path / "plugins"
        _make_cache(tmp_path, {"claude-opus-4-6": 10_000_000, "claude-sonnet-4-6": 5_000_000})
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "claude-opus-4-6" in result.stdout or "opus" in result.stdout.lower()

    def test_zero_tokens(self, tmp_path):
        """Zero usage should not crash and show 0.0M."""
        plugins_dir = tmp_path / "plugins"
        _make_cache(tmp_path, {})
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "0.0M" in result.stdout or "0M" in result.stdout or "0" in result.stdout.split("\n")[0]

    def test_high_usage_color_red(self, tmp_path):
        """Usage >= 90% should show red color."""
        plugins_dir = tmp_path / "plugins"
        _make_cache(tmp_path, {"claude-opus-4-6": int(WEEKLY_LIMIT * 0.95)})
        plugin_file = install_menubar(
            claude_home=tmp_path,
            refresh_interval_sec=60,
            plugins_dir=plugins_dir,
        )
        result = subprocess.run(
            [sys.executable, str(plugin_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = result.stdout.split("\n")[0]
        assert "color=red" in first_line


# ---------------------------------------------------------------------------
# uninstall_menubar
# ---------------------------------------------------------------------------

class TestUninstallMenubar:
    def test_uninstall_returns_true_when_file_exists(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        install_menubar(claude_home=tmp_path, plugins_dir=plugins_dir)
        result = uninstall_menubar(plugins_dir=plugins_dir)
        assert result is True

    def test_uninstall_deletes_file(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugin_file = install_menubar(claude_home=tmp_path, plugins_dir=plugins_dir)
        assert plugin_file.exists()
        uninstall_menubar(plugins_dir=plugins_dir)
        assert not plugin_file.exists()

    def test_uninstall_returns_false_when_no_file(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(parents=True)
        result = uninstall_menubar(plugins_dir=plugins_dir)
        assert result is False

    def test_uninstall_returns_false_when_dir_missing(self, tmp_path):
        plugins_dir = tmp_path / "nonexistent"
        result = uninstall_menubar(plugins_dir=plugins_dir)
        assert result is False

    def test_uninstall_removes_any_interval_variant(self, tmp_path):
        """Should remove claude-usage.*.py regardless of interval suffix."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(parents=True)
        # Manually create a 5m variant
        (plugins_dir / "claude-usage.5m.py").write_text("# plugin")
        result = uninstall_menubar(plugins_dir=plugins_dir)
        assert result is True
        assert not any(plugins_dir.glob("claude-usage.*.py"))


# ---------------------------------------------------------------------------
# check_swiftbar_installed
# ---------------------------------------------------------------------------

class TestCheckSwiftbarInstalled:
    def test_returns_bool(self):
        result = check_swiftbar_installed()
        assert isinstance(result, bool)
