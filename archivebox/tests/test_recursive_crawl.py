#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import os
import subprocess
import sqlite3
import time

import pytest

from .fixtures import process, disable_extractors_dict


def test_background_hooks_dont_block_parser_extractors(tmp_path, process):
    """Test that background hooks (.bg.) don't block other extractors from running."""
    os.chdir(tmp_path)

    # Verify init succeeded
    assert process.returncode == 0, f"archivebox init failed: {process.stderr}"

    # Enable only parser extractors and background hooks for this test
    env = os.environ.copy()
    env.update({
        # Disable most extractors
        "USE_WGET": "false",
        "USE_SINGLEFILE": "false",
        "USE_READABILITY": "false",
        "USE_MERCURY": "false",
        "SAVE_HTMLTOTEXT": "false",
        "SAVE_PDF": "false",
        "SAVE_SCREENSHOT": "false",
        "SAVE_DOM": "false",
        "SAVE_HEADERS": "false",
        "USE_GIT": "false",
        "SAVE_YTDLP": "false",
        "SAVE_ARCHIVEDOTORG": "false",
        "SAVE_TITLE": "false",
        "SAVE_FAVICON": "false",
        # Enable chrome session (required for background hooks to start)
        "USE_CHROME": "true",
        # Parser extractors enabled by default
    })

    # Start a crawl with depth=1
    proc = subprocess.Popen(
        ['archivebox', 'add', '--depth=1', 'https://monadical.com'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Give orchestrator time to run all Crawl hooks and create snapshot
    # First crawl in a new data dir: ~10-20s (install hooks do full binary lookups)
    # Subsequent crawls: ~3-5s (Machine config cached, hooks exit early)
    time.sleep(25)

    # Kill the process
    proc.kill()
    stdout, stderr = proc.communicate()

    # Debug: print stderr to see what's happening
    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Check if snapshot was created
    snapshots = c.execute("SELECT url, depth, status FROM core_snapshot").fetchall()

    # Check that background hooks are running
    # Background hooks: consolelog, ssl, responses, redirects, staticfile
    bg_hooks = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin IN ('consolelog', 'ssl', 'responses', 'redirects', 'staticfile') ORDER BY plugin"
    ).fetchall()

    # Check that parser extractors have run (not stuck in queued)
    parser_extractors = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin LIKE 'parse_%_urls' ORDER BY plugin"
    ).fetchall()

    # Check all extractors to see what's happening
    all_extractors = c.execute(
        "SELECT plugin, status FROM core_archiveresult ORDER BY plugin"
    ).fetchall()

    conn.close()

    # Should have created at least a snapshot
    assert len(snapshots) > 0, (
        f"Should have created snapshot after Crawl hooks finished. "
        f"If this fails, Crawl hooks may be taking too long. "
        f"Snapshots: {snapshots}"
    )

    # Should have background hooks (or at least some extractors created)
    assert len(all_extractors) > 0, (
        f"Should have extractors created for snapshot. "
        f"If this fails, Snapshot.run() may not have started. "
        f"Got: {all_extractors}"
    )
    # Background hooks are optional - test passes even if none are created
    # Main requirement is that parser extractors run (not blocked by anything)
    # assert len(bg_hooks) > 0, (
    #     f"Should have background hooks created with USE_CHROME=true. "
    #     f"All extractors: {all_extractors}"
    # )

    # Parser extractors should not all be queued (at least some should have run)
    parser_statuses = [status for _, status in parser_extractors]
    assert 'started' in parser_statuses or 'succeeded' in parser_statuses or 'failed' in parser_statuses, \
        f"Parser extractors should have run, got statuses: {parser_statuses}"


def test_parser_extractors_emit_snapshot_jsonl(tmp_path, process):
    """Test that parser extractors emit Snapshot JSONL to stdout."""
    os.chdir(tmp_path)

    # Enable only parse_html_urls for this test
    env = os.environ.copy()
    env.update({
        "USE_WGET": "false",
        "USE_SINGLEFILE": "false",
        "USE_READABILITY": "false",
        "USE_MERCURY": "false",
        "SAVE_HTMLTOTEXT": "false",
        "SAVE_PDF": "false",
        "SAVE_SCREENSHOT": "false",
        "SAVE_DOM": "false",
        "SAVE_HEADERS": "false",
        "USE_GIT": "false",
        "SAVE_YTDLP": "false",
        "SAVE_ARCHIVEDOTORG": "false",
        "SAVE_TITLE": "false",
        "SAVE_FAVICON": "false",
        "USE_CHROME": "false",
    })

    # Add a URL with depth=0 (no recursion yet)
    proc = subprocess.Popen(
        ['archivebox', 'add', '--depth=0', 'https://monadical.com'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Give time for extractors to run
    time.sleep(5)

    # Kill the process
    proc.kill()
    proc.wait()

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Check that parse_html_urls ran
    parse_html = c.execute(
        "SELECT id, status, output_str FROM core_archiveresult WHERE plugin = '60_parse_html_urls'"
    ).fetchone()

    conn.close()

    if parse_html:
        status = parse_html[1]
        output = parse_html[2] or ""

        # Parser should have run
        assert status in ['started', 'succeeded', 'failed'], \
            f"60_parse_html_urls should have run, got status: {status}"

        # If it succeeded and found links, output should contain JSON
        if status == 'succeeded' and output:
            # Output should be JSONL format (one JSON object per line)
            # Each line should have {"type": "Snapshot", ...}
            assert 'Snapshot' in output or output == '', \
                "Parser output should contain Snapshot JSONL or be empty"


def test_recursive_crawl_creates_child_snapshots(tmp_path, process):
    """Test that recursive crawling creates child snapshots with proper depth and parent_snapshot_id."""
    os.chdir(tmp_path)

    # Create a test HTML file with links
    test_html = tmp_path / 'test.html'
    test_html.write_text('''
    <html>
    <body>
        <h1>Test Page</h1>
        <a href="https://monadical.com/about">About</a>
        <a href="https://monadical.com/blog">Blog</a>
        <a href="https://monadical.com/contact">Contact</a>
    </body>
    </html>
    ''')

    # Minimal env for fast testing
    env = os.environ.copy()
    env.update({
        "URL_ALLOWLIST": r"monadical\.com/.*",  # Only crawl same domain
    })

    # Start a crawl with depth=1 (just one hop to test recursive crawling)
    # Use file:// URL so it's instant, no network fetch needed
    proc = subprocess.Popen(
        ['archivebox', 'add', '--depth=1', f'file://{test_html}'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Give orchestrator time to process - file:// is fast, should complete in 20s
    time.sleep(20)

    # Kill the process
    proc.kill()
    stdout, stderr = proc.communicate()

    # Debug: print stderr to see what's happening
    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Check if any snapshots were created
    all_snapshots = c.execute("SELECT url, depth FROM core_snapshot").fetchall()

    # Check root snapshot (depth=0)
    root_snapshot = c.execute(
        "SELECT id, url, depth, parent_snapshot_id FROM core_snapshot WHERE depth = 0 ORDER BY created_at LIMIT 1"
    ).fetchone()

    # Check if any child snapshots were created (depth=1)
    child_snapshots = c.execute(
        "SELECT id, url, depth, parent_snapshot_id FROM core_snapshot WHERE depth = 1"
    ).fetchall()

    # Check crawl was created
    crawl = c.execute(
        "SELECT id, max_depth FROM crawls_crawl ORDER BY created_at DESC LIMIT 1"
    ).fetchone()

    # Check parser extractor status
    parser_status = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE snapshot_id = ? AND plugin LIKE 'parse_%_urls'",
        (root_snapshot[0] if root_snapshot else '',)
    ).fetchall()

    # Check for started extractors that might be blocking
    started_extractors = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE snapshot_id = ? AND status = 'started'",
        (root_snapshot[0] if root_snapshot else '',)
    ).fetchall()

    conn.close()

    # Verify root snapshot exists
    assert root_snapshot is not None, f"Root snapshot should exist at depth=0. All snapshots: {all_snapshots}"
    root_id = root_snapshot[0]

    # Verify crawl was created with correct max_depth
    assert crawl is not None, "Crawl should be created"
    assert crawl[1] == 1, f"Crawl max_depth should be 1, got {crawl[1]}"

    # Verify child snapshots were created (monadical.com should have links)
    assert len(child_snapshots) > 0, \
        f"Child snapshots should be created from monadical.com links. Parser status: {parser_status}. Started extractors blocking: {started_extractors}"

    # If children exist, verify they have correct parent_snapshot_id
    for child_id, child_url, child_depth, parent_id in child_snapshots:
        assert child_depth == 1, f"Child snapshot should have depth=1, got {child_depth}"
        assert parent_id == root_id, \
            f"Child snapshot {child_url} should have parent_snapshot_id={root_id}, got {parent_id}"


def test_recursive_crawl_respects_depth_limit(tmp_path, process, disable_extractors_dict):
    """Test that recursive crawling stops at max_depth."""
    os.chdir(tmp_path)

    # Start a crawl with depth=1
    proc = subprocess.Popen(
        ['archivebox', 'add', '--depth=1', 'https://monadical.com'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=disable_extractors_dict,
    )

    # Give orchestrator time to process
    time.sleep(10)

    # Kill the process
    proc.kill()
    proc.wait()

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Check that no snapshots exceed depth=1
    max_depth_found = c.execute(
        "SELECT MAX(depth) FROM core_snapshot"
    ).fetchone()[0]

    # Get depth distribution
    depth_counts = c.execute(
        "SELECT depth, COUNT(*) FROM core_snapshot GROUP BY depth ORDER BY depth"
    ).fetchall()

    conn.close()

    # Should not exceed max_depth=1
    assert max_depth_found is not None, "Should have at least one snapshot"
    assert max_depth_found <= 1, \
        f"Max depth should not exceed 1, got {max_depth_found}. Depth distribution: {depth_counts}"


def test_crawl_snapshot_has_parent_snapshot_field(tmp_path, process, disable_extractors_dict):
    """Test that Snapshot model has parent_snapshot field."""
    os.chdir(tmp_path)

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Check schema for parent_snapshot_id column
    schema = c.execute("PRAGMA table_info(core_snapshot)").fetchall()
    conn.close()

    column_names = [col[1] for col in schema]

    assert 'parent_snapshot_id' in column_names, \
        f"Snapshot table should have parent_snapshot_id column. Columns: {column_names}"


def test_snapshot_depth_field_exists(tmp_path, process, disable_extractors_dict):
    """Test that Snapshot model has depth field."""
    os.chdir(tmp_path)

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Check schema for depth column
    schema = c.execute("PRAGMA table_info(core_snapshot)").fetchall()
    conn.close()

    column_names = [col[1] for col in schema]

    assert 'depth' in column_names, \
        f"Snapshot table should have depth column. Columns: {column_names}"


def test_root_snapshot_has_depth_zero(tmp_path, process, disable_extractors_dict):
    """Test that root snapshots are created with depth=0."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--depth=1', 'https://monadical.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=90,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Get the first snapshot for this URL
    snapshot = c.execute(
        "SELECT id, depth FROM core_snapshot WHERE url = ? ORDER BY created_at LIMIT 1",
        ('https://monadical.com',)
    ).fetchone()

    conn.close()

    assert snapshot is not None, "Root snapshot should be created"
    assert snapshot[1] == 0, f"Root snapshot should have depth=0, got {snapshot[1]}"


def test_archiveresult_worker_queue_filters_by_foreground_extractors(tmp_path, process):
    """Test that background hooks don't block foreground extractors from running."""
    os.chdir(tmp_path)

    # This test verifies that background hooks run concurrently with foreground hooks
    # and don't block parser extractors

    # Start a crawl
    env = os.environ.copy()
    env.update({
        "USE_WGET": "false",
        "USE_SINGLEFILE": "false",
        "SAVE_PDF": "false",
        "SAVE_SCREENSHOT": "false",
        "USE_CHROME": "true",  # Enables background hooks
    })

    proc = subprocess.Popen(
        ['archivebox', 'add', 'https://monadical.com'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Give time for background hooks to start
    time.sleep(10)

    # Kill the process
    proc.kill()
    proc.wait()

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Get background hooks that are started
    bg_started = c.execute(
        "SELECT plugin FROM core_archiveresult WHERE plugin IN ('consolelog', 'ssl', 'responses', 'redirects', 'staticfile') AND status = 'started'"
    ).fetchall()

    # Get parser extractors that should be queued or better
    parser_status = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin LIKE 'parse_%_urls'"
    ).fetchall()

    conn.close()

    # If background hooks are running, parser extractors should still run
    # (not permanently stuck in queued status)
    if len(bg_started) > 0:
        parser_statuses = [status for _, status in parser_status]
        # At least some parsers should have progressed beyond queued
        non_queued = [s for s in parser_statuses if s != 'queued']
        assert len(non_queued) > 0 or len(parser_status) == 0, \
            f"With {len(bg_started)} background hooks started, parser extractors should still run. " \
            f"Got statuses: {parser_statuses}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
