#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import json
import os
import subprocess
import sqlite3
import time
from pathlib import Path

import pytest


def wait_for_db_condition(timeout, condition, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists("index.sqlite3"):
            conn = sqlite3.connect("index.sqlite3")
            try:
                if condition(conn.cursor()):
                    return True
            finally:
                conn.close()
        time.sleep(interval)
    return False


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.communicate()


def run_add_until(args, env, condition, timeout=120):
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert wait_for_db_condition(timeout=timeout, condition=condition), f"Timed out waiting for condition while running: {' '.join(args)}"
    return stop_process(proc)


def test_background_hooks_dont_block_parser_extractors(tmp_path, process, recursive_test_site):
    """Test that background hooks (.bg.) don't block other extractors from running."""
    os.chdir(tmp_path)

    # Verify init succeeded
    assert process.returncode == 0, f"archivebox init failed: {process.stderr}"

    # Enable only parser extractors and background hooks for this test
    env = os.environ.copy()
    env.update(
        {
            # Disable most extractors
            "SAVE_WGET": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_MERCURY": "false",
            "SAVE_HTMLTOTEXT": "false",
            "SAVE_PDF": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_DOM": "false",
            "SAVE_HEADERS": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_TITLE": "false",
            "SAVE_FAVICON": "true",
        },
    )

    proc = subprocess.Popen(
        ["archivebox", "add", "--depth=1", "--plugins=favicon,parse_html_urls", recursive_test_site["root_url"]],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert wait_for_db_condition(
        timeout=120,
        condition=lambda c: (
            c.execute(
                "SELECT COUNT(*) FROM core_archiveresult WHERE plugin LIKE 'parse_%_urls' AND status IN ('started', 'succeeded', 'failed')",
            ).fetchone()[0]
            > 0
        ),
    ), "Parser extractors never progressed beyond queued status"
    stdout, stderr = stop_process(proc)

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    snapshots = c.execute("SELECT url, depth, status FROM core_snapshot").fetchall()
    bg_hooks = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin IN ('favicon', 'consolelog', 'ssl', 'responses', 'redirects', 'staticfile') ORDER BY plugin",
    ).fetchall()
    parser_extractors = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin LIKE 'parse_%_urls' ORDER BY plugin",
    ).fetchall()
    all_extractors = c.execute(
        "SELECT plugin, status FROM core_archiveresult ORDER BY plugin",
    ).fetchall()

    conn.close()

    assert len(snapshots) > 0, (
        f"Should have created snapshot after Crawl hooks finished. "
        f"If this fails, Crawl hooks may be taking too long. "
        f"Snapshots: {snapshots}"
    )

    assert len(all_extractors) > 0, (
        f"Should have extractors created for snapshot. If this fails, Snapshot.run() may not have started. Got: {all_extractors}"
    )

    parser_statuses = [status for _, status in parser_extractors]
    assert "started" in parser_statuses or "succeeded" in parser_statuses or "failed" in parser_statuses, (
        f"Parser extractors should have run, got statuses: {parser_statuses}. Background hooks: {bg_hooks}"
    )


def test_parser_extractors_emit_snapshot_jsonl(tmp_path, process, recursive_test_site):
    """Test that parser extractors emit Snapshot JSONL to stdout."""
    os.chdir(tmp_path)

    env = os.environ.copy()
    env.update(
        {
            "SAVE_WGET": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_MERCURY": "false",
            "SAVE_HTMLTOTEXT": "false",
            "SAVE_PDF": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_DOM": "false",
            "SAVE_HEADERS": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_TITLE": "false",
            "SAVE_FAVICON": "false",
            "USE_CHROME": "false",
        },
    )

    result = subprocess.run(
        ["archivebox", "add", "--depth=0", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    parse_html = c.execute(
        "SELECT id, status, output_str FROM core_archiveresult WHERE plugin LIKE '%parse_html_urls' ORDER BY id LIMIT 1",
    ).fetchone()

    conn.close()

    if parse_html:
        status = parse_html[1]
        output = parse_html[2] or ""

        assert status in ["started", "succeeded", "failed"], f"60_parse_html_urls should have run, got status: {status}"

        if status == "succeeded" and output:
            assert "parsed" in output.lower(), "Parser summary should report parsed URLs"

    urls_jsonl_files = list(Path("users/system/snapshots").rglob("parse_html_urls/**/urls.jsonl"))
    assert urls_jsonl_files, "parse_html_urls should write urls.jsonl output"

    records = []
    for line in urls_jsonl_files[0].read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))

    assert records, "urls.jsonl should contain parsed Snapshot records"
    assert all(record.get("type") == "Snapshot" for record in records), f"Expected Snapshot JSONL records, got: {records}"


def test_recursive_crawl_creates_child_snapshots(tmp_path, process, recursive_test_site):
    """Test that recursive crawling creates child snapshots with proper depth and parent_snapshot_id."""
    os.chdir(tmp_path)

    env = os.environ.copy()
    env.update(
        {
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_HEADERS": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_TITLE": "false",
        },
    )

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda c: (
            c.execute("SELECT COUNT(*) FROM core_snapshot WHERE depth = 0").fetchone()[0] >= 1
            and c.execute("SELECT COUNT(*) FROM core_snapshot WHERE depth = 1").fetchone()[0] >= len(recursive_test_site["child_urls"])
        ),
    )

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    all_snapshots = c.execute("SELECT url, depth FROM core_snapshot").fetchall()
    root_snapshot = c.execute(
        "SELECT id, url, depth, parent_snapshot_id FROM core_snapshot WHERE depth = 0 ORDER BY created_at LIMIT 1",
    ).fetchone()
    child_snapshots = c.execute(
        "SELECT id, url, depth, parent_snapshot_id FROM core_snapshot WHERE depth = 1",
    ).fetchall()
    crawl = c.execute(
        "SELECT id, max_depth FROM crawls_crawl ORDER BY created_at DESC LIMIT 1",
    ).fetchone()
    parser_status = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE snapshot_id = ? AND plugin LIKE 'parse_%_urls'",
        (root_snapshot[0] if root_snapshot else "",),
    ).fetchall()
    started_extractors = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE snapshot_id = ? AND status = 'started'",
        (root_snapshot[0] if root_snapshot else "",),
    ).fetchall()

    conn.close()

    assert root_snapshot is not None, f"Root snapshot should exist at depth=0. All snapshots: {all_snapshots}"
    root_id = root_snapshot[0]

    assert crawl is not None, "Crawl should be created"
    assert crawl[1] == 1, f"Crawl max_depth should be 1, got {crawl[1]}"

    assert len(child_snapshots) > 0, (
        f"Child snapshots should be created from monadical.com links. Parser status: {parser_status}. Started extractors blocking: {started_extractors}"
    )

    for child_id, child_url, child_depth, parent_id in child_snapshots:
        assert child_depth == 1, f"Child snapshot should have depth=1, got {child_depth}"
        assert parent_id == root_id, f"Child snapshot {child_url} should have parent_snapshot_id={root_id}, got {parent_id}"


def test_recursive_crawl_respects_depth_limit(tmp_path, process, disable_extractors_dict, recursive_test_site):
    """Test that recursive crawling stops at max_depth."""
    os.chdir(tmp_path)

    env = disable_extractors_dict.copy()
    env["URL_ALLOWLIST"] = r"127\.0\.0\.1[:/].*"

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda c: (
            c.execute("SELECT COUNT(*) FROM core_snapshot WHERE depth = 0").fetchone()[0] >= 1
            and c.execute("SELECT COUNT(*) FROM core_snapshot WHERE depth = 1").fetchone()[0] >= len(recursive_test_site["child_urls"])
            and c.execute(
                "SELECT COUNT(DISTINCT ar.snapshot_id) "
                "FROM core_archiveresult ar "
                "JOIN core_snapshot s ON s.id = ar.snapshot_id "
                "WHERE s.depth = 1 "
                "AND ar.plugin LIKE 'parse_%_urls' "
                "AND ar.status IN ('started', 'succeeded', 'failed')",
            ).fetchone()[0]
            >= len(recursive_test_site["child_urls"])
        ),
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    max_depth_found = c.execute(
        "SELECT MAX(depth) FROM core_snapshot",
    ).fetchone()[0]
    depth_counts = c.execute(
        "SELECT depth, COUNT(*) FROM core_snapshot GROUP BY depth ORDER BY depth",
    ).fetchall()

    conn.close()

    assert max_depth_found is not None, "Should have at least one snapshot"
    assert max_depth_found <= 1, f"Max depth should not exceed 1, got {max_depth_found}. Depth distribution: {depth_counts}"


def test_crawl_snapshot_has_parent_snapshot_field(tmp_path, process, disable_extractors_dict):
    """Test that Snapshot model has parent_snapshot field."""
    os.chdir(tmp_path)

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check schema for parent_snapshot_id column
    schema = c.execute("PRAGMA table_info(core_snapshot)").fetchall()
    conn.close()

    column_names = [col[1] for col in schema]

    assert "parent_snapshot_id" in column_names, f"Snapshot table should have parent_snapshot_id column. Columns: {column_names}"


def test_snapshot_depth_field_exists(tmp_path, process, disable_extractors_dict):
    """Test that Snapshot model has depth field."""
    os.chdir(tmp_path)

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check schema for depth column
    schema = c.execute("PRAGMA table_info(core_snapshot)").fetchall()
    conn.close()

    column_names = [col[1] for col in schema]

    assert "depth" in column_names, f"Snapshot table should have depth column. Columns: {column_names}"


def test_root_snapshot_has_depth_zero(tmp_path, process, disable_extractors_dict, recursive_test_site):
    """Test that root snapshots are created with depth=0."""
    os.chdir(tmp_path)

    env = disable_extractors_dict.copy()
    env["URL_ALLOWLIST"] = r"127\.0\.0\.1[:/].*"

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda c: (
            c.execute(
                "SELECT COUNT(*) FROM core_snapshot WHERE url = ?",
                (recursive_test_site["root_url"],),
            ).fetchone()[0]
            >= 1
        ),
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    snapshot = c.execute(
        "SELECT id, depth FROM core_snapshot WHERE url = ? ORDER BY created_at LIMIT 1",
        (recursive_test_site["root_url"],),
    ).fetchone()

    conn.close()

    assert snapshot is not None, "Root snapshot should be created"
    assert snapshot[1] == 0, f"Root snapshot should have depth=0, got {snapshot[1]}"


def test_archiveresult_worker_queue_filters_by_foreground_extractors(tmp_path, process, recursive_test_site):
    """Test that background hooks don't block foreground extractors from running."""
    os.chdir(tmp_path)

    env = os.environ.copy()
    env.update(
        {
            "SAVE_WGET": "true",
            "SAVE_SINGLEFILE": "false",
            "SAVE_PDF": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_FAVICON": "true",
        },
    )

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--plugins=favicon,wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda c: (
            c.execute(
                "SELECT COUNT(*) FROM core_archiveresult WHERE plugin LIKE 'parse_%_urls' AND status IN ('started', 'succeeded', 'failed')",
            ).fetchone()[0]
            > 0
        ),
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    bg_results = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin IN ('favicon', 'consolelog', 'ssl', 'responses', 'redirects', 'staticfile') AND status IN ('started', 'succeeded', 'failed')",
    ).fetchall()
    parser_status = c.execute(
        "SELECT plugin, status FROM core_archiveresult WHERE plugin LIKE 'parse_%_urls'",
    ).fetchall()

    conn.close()

    if len(bg_results) > 0:
        parser_statuses = [status for _, status in parser_status]
        non_queued = [s for s in parser_statuses if s != "queued"]
        assert len(non_queued) > 0 or len(parser_status) == 0, (
            f"With {len(bg_results)} background hooks started, parser extractors should still run. Got statuses: {parser_statuses}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
