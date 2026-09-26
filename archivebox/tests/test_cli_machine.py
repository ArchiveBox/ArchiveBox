#!/usr/bin/env python3
"""
Tests for archivebox machine command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_machine_identity_is_stable_across_cli_processes(initialized_archive):
    """Minimal containers without /etc/machine-id must still share one identity."""
    import sqlite3

    import machineid

    from archivebox.config.paths import get_machine_id
    from archivebox.machine.detect import get_host_guid, get_vm_info

    guid = get_host_guid()
    assert len(guid) == 64
    assert all(char in "0123456789abcdef" for char in guid)
    assert get_machine_id() == guid[:8]
    assert isinstance(get_vm_info()["hw_uuid"], str)
    try:
        native_guid = machineid.hashed_id("archivebox")
    except machineid.MachineIdNotFound:
        pass
    else:
        assert guid == native_guid

    identities = []
    for _ in range(2):
        result = run_archivebox_cmd(["status"], cwd=initialized_archive)
        assert result.returncode == 0, result.stdout + result.stderr
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            rows = db.execute("SELECT id, guid FROM machine_machine WHERE guid=?", (guid,)).fetchall()
        assert len(rows) == 1
        identities.append(rows)
    assert identities[0] == identities[1]


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
