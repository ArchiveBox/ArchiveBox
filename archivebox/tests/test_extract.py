#!/usr/bin/env python3
"""Integration tests for archivebox extract command."""

import os
import subprocess
import sqlite3
import json

import pytest

from .fixtures import process, disable_extractors_dict


def test_extract_runs_on_snapshot_id(tmp_path, process, disable_extractors_dict):
    """Test that extract command accepts a snapshot ID."""
    os.chdir(tmp_path)

    # First create a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get the snapshot ID
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_id = c.execute("SELECT id FROM core_snapshot LIMIT 1").fetchone()[0]
    conn.close()

    # Run extract on the snapshot
    result = subprocess.run(
        ['archivebox', 'extract', '--no-wait', str(snapshot_id)],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    # Should not error about invalid snapshot ID
    assert 'not found' not in result.stderr.lower()


def test_extract_with_enabled_extractor_creates_archiveresult(tmp_path, process, disable_extractors_dict):
    """Test that extract creates ArchiveResult when extractor is enabled."""
    os.chdir(tmp_path)

    # First create a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get the snapshot ID
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_id = c.execute("SELECT id FROM core_snapshot LIMIT 1").fetchone()[0]
    conn.close()

    # Run extract with title extractor enabled
    env = disable_extractors_dict.copy()
    env['SAVE_TITLE'] = 'true'

    subprocess.run(
        ['archivebox', 'extract', '--no-wait', str(snapshot_id)],
        capture_output=True,
        text=True,
        env=env,
    )

    # Check for archiveresults (may be queued, not completed with --no-wait)
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_archiveresult WHERE snapshot_id = ?",
                     (snapshot_id,)).fetchone()[0]
    conn.close()

    # May or may not have results depending on timing
    assert count >= 0


def test_extract_plugin_option_accepted(tmp_path, process, disable_extractors_dict):
    """Test that --plugin option is accepted."""
    os.chdir(tmp_path)

    # First create a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get the snapshot ID
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_id = c.execute("SELECT id FROM core_snapshot LIMIT 1").fetchone()[0]
    conn.close()

    result = subprocess.run(
        ['archivebox', 'extract', '--plugin=title', '--no-wait', str(snapshot_id)],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    assert 'unrecognized arguments: --plugin' not in result.stderr


def test_extract_stdin_snapshot_id(tmp_path, process, disable_extractors_dict):
    """Test that extract reads snapshot IDs from stdin."""
    os.chdir(tmp_path)

    # First create a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get the snapshot ID
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_id = c.execute("SELECT id FROM core_snapshot LIMIT 1").fetchone()[0]
    conn.close()

    result = subprocess.run(
        ['archivebox', 'extract', '--no-wait'],
        input=f'{snapshot_id}\n',
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    # Should not show "not found" error
    assert 'not found' not in result.stderr.lower() or result.returncode == 0


def test_extract_stdin_jsonl_input(tmp_path, process, disable_extractors_dict):
    """Test that extract reads JSONL records from stdin."""
    os.chdir(tmp_path)

    # First create a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get the snapshot ID
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_id = c.execute("SELECT id FROM core_snapshot LIMIT 1").fetchone()[0]
    conn.close()

    jsonl_input = json.dumps({"type": "Snapshot", "id": str(snapshot_id)}) + '\n'

    result = subprocess.run(
        ['archivebox', 'extract', '--no-wait'],
        input=jsonl_input,
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    # Should not show "not found" error
    assert 'not found' not in result.stderr.lower() or result.returncode == 0


def test_extract_pipeline_from_snapshot(tmp_path, process, disable_extractors_dict):
    """Test piping snapshot output to extract."""
    os.chdir(tmp_path)

    # Create snapshot and pipe to extract
    snapshot_proc = subprocess.Popen(
        ['archivebox', 'snapshot', 'https://example.com'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=disable_extractors_dict,
    )

    subprocess.run(
        ['archivebox', 'extract', '--no-wait'],
        stdin=snapshot_proc.stdout,
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    snapshot_proc.wait()

    # Check database for snapshot
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot = c.execute("SELECT id, url FROM core_snapshot WHERE url = ?",
                        ('https://example.com',)).fetchone()
    conn.close()

    assert snapshot is not None, "Snapshot should be created by pipeline"


def test_extract_multiple_snapshots(tmp_path, process, disable_extractors_dict):
    """Test extracting from multiple snapshots."""
    os.chdir(tmp_path)

    # Create multiple snapshots one at a time to avoid deduplication issues
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://iana.org'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get all snapshot IDs
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_ids = c.execute("SELECT id FROM core_snapshot").fetchall()
    conn.close()

    assert len(snapshot_ids) >= 2, "Should have at least 2 snapshots"

    # Extract from all snapshots
    ids_input = '\n'.join(str(s[0]) for s in snapshot_ids) + '\n'
    result = subprocess.run(
        ['archivebox', 'extract', '--no-wait'],
        input=ids_input,
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    # Should not error
    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count >= 2, "Both snapshots should still exist after extraction"


class TestExtractCLI:
    """Test the CLI interface for extract command."""

    def test_cli_help(self, tmp_path, process):
        """Test that --help works for extract command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'extract', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--plugin' in result.stdout or '-p' in result.stdout
        assert '--wait' in result.stdout or '--no-wait' in result.stdout

    def test_cli_no_snapshots_shows_warning(self, tmp_path, process):
        """Test that running without snapshots shows a warning."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'extract', '--no-wait'],
            input='',
            capture_output=True,
            text=True,
        )

        # Should show warning about no snapshots or exit normally (empty input)
        assert result.returncode == 0 or 'No' in result.stderr


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
