#!/usr/bin/env python3
"""
Comprehensive tests for archivebox remove command.
Verify remove deletes snapshots from DB and filesystem.
"""

import json
import subprocess
import time
from pathlib import Path

import requests
from abxpkg import Binary, apt, brew, env as env_provider

from archivebox.tests.conftest import find_snapshot_dir, run_archivebox_cmd, run_queued_crawls, cli_env, get_free_port


def test_remove_verifies_remote_storage_before_deleting_row(initialized_archive, tmp_path):
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(["add", "--index-only", "--depth=0", "https://example.com"], env=env, check=True)
    run_queued_crawls(initialized_archive, env)
    snapshot_id = _snapshot_rows(initialized_archive, env)[0]["id"]
    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None
    remote_root = tmp_path / "remote-archive"
    remote_dir = remote_root / snapshot_dir.relative_to(initialized_archive / "archive")
    remote_dir.mkdir(parents=True)
    (remote_dir / "pending-upload.pid").write_text("12345")
    alias = remote_dir.with_name(remote_dir.name + ".rclonelink")
    alias.write_text(str(snapshot_dir))
    port = get_free_port()
    endpoint = f"http://127.0.0.1:{port}"
    rclone = Binary(name="rclone", binproviders=[env_provider, apt, brew]).install()
    assert rclone.abspath is not None
    server = subprocess.Popen(
        [str(rclone.abspath), "rcd", "--rc-addr", f"127.0.0.1:{port}", "--rc-user", "archivebox", "--rc-pass", "test-storage-password"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            assert server.poll() is None
            try:
                response = requests.post(endpoint + "/rc/noop", auth=("archivebox", "test-storage-password"), timeout=1)
                if response.ok:
                    break
            except requests.ConnectionError:
                pass
            assert time.monotonic() < deadline
            time.sleep(0.05)
        env.update(
            RCLONE_RC_URL=endpoint,
            RCLONE_RC_USER="archivebox",
            RCLONE_RC_PASSWORD="incorrect-password",
            RCLONE_ARCHIVE_REMOTE=str(remote_root),
        )
        denied = run_archivebox_cmd(["remove", "https://example.com", "--yes"], env=env)
        assert denied.returncode != 0
        assert len(_snapshot_rows(initialized_archive, env)) == 1
        assert (remote_dir / "pending-upload.pid").read_text() == "12345"
        env["RCLONE_RC_PASSWORD"] = "test-storage-password"
        removed = run_archivebox_cmd(["remove", "https://example.com", "--yes"], env=env)
        assert removed.returncode == 0, removed.stderr
        assert _snapshot_rows(initialized_archive, env) == []
        assert not snapshot_dir.exists()
        assert not remote_dir.exists()
        assert not alias.exists()
    finally:
        server.terminate()
        server.wait(timeout=10)


def _snapshot_rows(data_dir: Path, env: dict) -> list[dict]:
    script = """
import json
from archivebox.core.models import Snapshot
print(json.dumps([
    {"id": str(snapshot.id), "url": snapshot.url}
    for snapshot in Snapshot.objects.order_by("url")
]))
"""
    result = run_archivebox_cmd(
        ["manage", "shell", "-c", script],
        cwd=data_dir,
        env=env,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_remove_deletes_snapshot_from_db(initialized_archive):
    """Test that remove command deletes snapshot from database."""
    env = cli_env(disable_extractors=True)

    # Add a snapshot
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_id = rows[0]["id"]
    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"

    # Remove it
    run_archivebox_cmd(
        ["remove", "https://example.com", "--yes"],
        env=env,
    )

    assert len(_snapshot_rows(initialized_archive, env)) == 0
    assert not snapshot_dir.exists()


def test_remove_deletes_archive_directory(initialized_archive):
    """Test that remove --yes removes the current snapshot output directory."""
    env = cli_env(disable_extractors=True)

    # Add a snapshot
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_id = rows[0]["id"]

    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"

    run_archivebox_cmd(
        ["remove", "https://example.com", "--yes"],
        env=env,
    )

    assert not snapshot_dir.exists()


def test_remove_yes_flag_skips_confirmation(initialized_archive):
    """Test that --yes flag skips confirmation prompt."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    # Remove with --yes should complete without interaction
    result = run_archivebox_cmd(
        ["remove", "https://example.com", "--yes"],
        env=env,
        timeout=30,
    )

    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "Index now contains 0 links." in output


def test_remove_without_yes_prompts_and_keeps_snapshot(initialized_archive):
    """Test that omitting --yes prompts for confirmation and keeps data when declined."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_dir = find_snapshot_dir(initialized_archive, rows[0]["id"])
    assert snapshot_dir is not None

    result = run_archivebox_cmd(
        ["remove", "https://example.com"],
        input="n\n",
        env=env,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Do you want to proceed" in output or "y/[n]" in output
    assert len(_snapshot_rows(initialized_archive, env)) == 1
    assert snapshot_dir.exists()


def test_remove_multiple_snapshots(initialized_archive):
    """Test removing multiple snapshots at once."""
    env = cli_env(disable_extractors=True)

    # Add multiple snapshots
    for url in ["https://example.com", "https://example.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
        )
    run_queued_crawls(initialized_archive, env)

    assert len(_snapshot_rows(initialized_archive, env)) == 2

    # Remove both
    run_archivebox_cmd(
        ["remove", "https://example.com", "https://example.org", "--yes"],
        env=env,
    )

    assert len(_snapshot_rows(initialized_archive, env)) == 0


def test_remove_with_regex_filter_deletes_all_matches(initialized_archive):
    """Test regex filters remove every matching snapshot."""
    env = cli_env(disable_extractors=True)

    for url in ["https://example.com", "https://iana.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    result = run_archivebox_cmd(
        ["remove", "--filter-type=regex", ".*", "--yes"],
        env=env,
        check=True,
    )

    output = result.stdout + result.stderr
    assert len(_snapshot_rows(initialized_archive, env)) == 0
    assert "Removed" in output or "Found" in output


def test_remove_nonexistent_url_fails_gracefully(initialized_archive):
    """Test that removing non-existent URL fails gracefully."""
    env = cli_env(disable_extractors=True)

    result = run_archivebox_cmd(
        ["remove", "https://nonexistent-url-12345.com", "--yes"],
        env=env,
    )

    # Should fail or show error
    stdout_text = result.stdout.lower()
    assert result.returncode != 0 or "not found" in stdout_text or "no matches" in stdout_text


def test_remove_reports_remaining_link_count_correctly(initialized_archive):
    """Test remove reports the remaining snapshot count after deletion."""
    env = cli_env(disable_extractors=True)

    for url in ["https://example.com", "https://example.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    result = run_archivebox_cmd(
        ["remove", "https://example.org", "--yes"],
        env=env,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "Removed 1 out of 2 links" in output
    assert "Index now contains 1 links." in output


def test_remove_after_flag(initialized_archive):
    """Test remove --after flag removes snapshots after date."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_dir = find_snapshot_dir(initialized_archive, rows[0]["id"])
    assert snapshot_dir is not None, f"Snapshot output directory not found for {rows[0]['id']}"

    result = run_archivebox_cmd(
        ["remove", "--after=1577836800", "--yes"],
        env=env,
        timeout=30,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "Removed 1 out of 1 links" in output
    assert "Index now contains 0 links." in output
    assert len(_snapshot_rows(initialized_archive, env)) == 0
    assert not snapshot_dir.exists()
