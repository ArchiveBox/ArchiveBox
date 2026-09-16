#!/usr/bin/env python3
"""
Tests for archivebox machine command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_status_refreshes_week_old_machine(initialized_archive):
    """A saved host refresh must not invalidate the instance still in use."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    from archivebox.machine.detect import get_host_guid

    # Age real rows instead of mocking time or save(): the failure happens
    # when normal CLI startup refreshes a persisted host after seven days.
    expired = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
        before = db.execute("SELECT id, guid FROM machine_machine ORDER BY id").fetchall()
        assert before
        db.execute("UPDATE machine_machine SET modified_at=?", (expired,))

    result = run_archivebox_cmd(["status"], cwd=initialized_archive)
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
        after = db.execute("SELECT id, guid FROM machine_machine ORDER BY id").fetchall()
        assert after == before
        refreshed = db.execute("SELECT modified_at FROM machine_machine WHERE guid=?", (get_host_guid(),)).fetchone()
        assert refreshed is not None
        assert datetime.fromisoformat(refreshed[0]).replace(tzinfo=timezone.utc) > datetime.fromisoformat(expired)
        assert all(row[0] == expired for row in db.execute("SELECT modified_at FROM machine_machine WHERE guid!=?", (get_host_guid(),)))


def test_machine_help_runs_successfully(tmp_path):
    """The machine command should be registered and expose help."""

    result = run_archivebox_cmd(["machine", "--help"])

    assert result.returncode == 0
    assert "machine" in result.stdout.lower()
    assert "list" in result.stdout
