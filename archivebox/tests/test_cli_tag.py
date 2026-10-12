#!/usr/bin/env python3
"""
Tests for archivebox tag command.
"""

import json

from archivebox.tests.conftest import run_archivebox_cmd


def test_tag_help_runs_successfully(tmp_path):
    """The tag command should be registered and expose help."""

    result = run_archivebox_cmd(["tag", "--help"])

    assert result.returncode == 0
    assert "tag" in result.stdout.lower()
    assert "list" in result.stdout


def _tags_by_url(data_dir):
    # WHY list --json: its tags are a JSON list, so a bogus "," tag stays visible
    # instead of disappearing into a comma-joined tags string.
    result = run_archivebox_cmd(["list", "--json"], cwd=data_dir, timeout=60)
    assert result.returncode == 0, result.stderr
    return {record["url"]: set(record["tags"]) for record in json.loads(result.stdout)}


def _tag_names(data_dir):
    result = run_archivebox_cmd(["tag", "list"], cwd=data_dir, timeout=60)
    assert result.returncode == 0, result.stderr
    return {json.loads(line)["name"] for line in result.stdout.splitlines() if line.strip()}


def test_tag_repair_removes_tags_exploded_into_characters(initialized_archive):
    """`archivebox tag repair` removes per-character tags and keeps deliberate short tags."""
    data_dir = initialized_archive
    real = ["abc5", "confirmed-good", "test"]
    # Production rows carry their real tags plus one tag per character of the
    # comma-joined tag string, including the "," separator itself.
    exploded = sorted(set(",".join(real)))
    records = [
        {"url": "https://example.com/exploded", "tags": [*real, *exploded]},
        # A deliberate one-character tag on its own is not part of a split string.
        {"url": "https://example.com/short", "tags": ["x", "a"]},
        # One short tag that happens to be a character of another tag stays: the bug
        # always produced every character of a tag, never just one of them.
        {"url": "https://example.com/version", "tags": ["5", "abc5"]},
    ]
    created = run_archivebox_cmd(
        ["snapshot", "create"],
        input="\n".join(json.dumps(record) for record in records) + "\n",
        cwd=data_dir,
        timeout=60,
    )
    assert created.returncode == 0, created.stderr
    before = _tags_by_url(data_dir)
    assert before["https://example.com/exploded"] == {*real, *exploded}

    dry_run = run_archivebox_cmd(["tag", "repair", "--dry-run"], cwd=data_dir, timeout=60)
    assert dry_run.returncode == 0, dry_run.stderr
    assert "https://example.com/exploded" in dry_run.stderr
    assert _tags_by_url(data_dir) == before

    unconfirmed = run_archivebox_cmd(["tag", "repair"], cwd=data_dir, timeout=60)
    assert unconfirmed.returncode == 1
    assert _tags_by_url(data_dir) == before

    repaired = run_archivebox_cmd(["tag", "repair", "--yes"], cwd=data_dir, timeout=60)
    assert repaired.returncode == 0, repaired.stderr
    after = _tags_by_url(data_dir)
    assert after == {
        "https://example.com/exploded": set(real),
        "https://example.com/short": {"x", "a"},
        "https://example.com/version": {"5", "abc5"},
    }
    # Orphaned character tags are deleted; ones still used deliberately are kept.
    remaining = _tag_names(data_dir)
    assert remaining == {*real, "x", "a", "5"}

    again = run_archivebox_cmd(["tag", "repair", "--yes"], cwd=data_dir, timeout=60)
    assert again.returncode == 0, again.stderr
    assert _tags_by_url(data_dir) == after
    assert _tag_names(data_dir) == remaining
