#!/usr/bin/env python3
"""
Tests for archivebox search command.
"""

import json

from archivebox.tests.conftest import cli_env, run_archivebox_cmd


def test_search_help_runs_successfully(tmp_path):
    """The search alias should be registered and expose list/search filters."""

    result = run_archivebox_cmd(["search", "--help"])

    assert result.returncode == 0
    assert "search" in result.stdout.lower()
    assert "--csv" in result.stdout


def test_cli_search_status_filters_snapshot_status_column(tmp_path, initialized_archive):
    env = cli_env(disable_extractors=True)
    for url in (
        "https://example.com/search-status-queued",
        "https://example.com/search-status-paused",
        "https://example.com/search-status-sealed",
    ):
        result = run_archivebox_cmd(
            ["snapshot", "create", url],
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    for status, needle in (
        ("paused", "search-status-paused"),
        ("sealed", "search-status-sealed"),
    ):
        listed = run_archivebox_cmd(
            ["snapshot", "list", "--url__icontains", needle],
            env=env,
            timeout=30,
        )
        assert listed.returncode == 0, listed.stderr
        updated = run_archivebox_cmd(
            ["snapshot", "update", "--status", status],
            input=listed.stdout,
            env=env,
            timeout=30,
        )
        assert updated.returncode == 0, updated.stderr

    result = run_archivebox_cmd(
        ["search", "--status", "sealed", "search-status"],
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
    assert [row["status"] for row in rows] == ["sealed"]
    assert [row["url"] for row in rows] == ["https://example.com/search-status-sealed"]
