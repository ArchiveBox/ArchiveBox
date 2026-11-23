#!/usr/bin/env python3
"""
Tests for archivebox machine command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_machine_identity_is_stable_across_cli_processes(initialized_archive):
    """Minimal containers without /etc/machine-id must still share one identity."""
    import platform
    import sqlite3

    import machineid

    from archivebox.config.paths import get_machine_id, get_native_machine_guid
    from archivebox.machine.detect import get_host_guid, get_vm_info

    guid = get_host_guid()
    assert len(guid) == 64
    assert all(char in "0123456789abcdef" for char in guid)
    assert get_machine_id() == guid[:8]
    assert isinstance(get_vm_info()["hw_uuid"], str)
    native_guid = get_native_machine_guid()
    if native_guid:
        assert native_guid == machineid.hashed_id("archivebox")
        assert guid != native_guid

    identities = []
    for _ in range(2):
        result = run_archivebox_cmd(["status"], cwd=initialized_archive)
        assert result.returncode == 0, result.stdout + result.stderr
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            rows = db.execute("SELECT id, guid FROM machine_machine WHERE guid=?", (guid,)).fetchall()
        assert len(rows) == 1
        identities.append(rows)
    assert identities[0] == identities[1]

    if native_guid:
        # A pre-upgrade Machine keeps its row if it describes this architecture.
        [(machine_pk, _)] = identities[0]
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            db.execute("UPDATE machine_machine SET guid=? WHERE id=?", (native_guid, machine_pk))
        result = run_archivebox_cmd(["status"], cwd=initialized_archive)
        assert result.returncode == 0, result.stdout + result.stderr
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            assert db.execute("SELECT id, guid FROM machine_machine WHERE guid IN (?, ?)", (native_guid, guid)).fetchall() == [
                (machine_pk, native_guid),
            ]
            other_arch = "aarch64" if platform.machine().lower() == "x86_64" else "x86_64"
            db.execute("UPDATE machine_machine SET os_arch=? WHERE id=?", (other_arch, machine_pk))

        result = run_archivebox_cmd(["status"], cwd=initialized_archive)
        assert result.returncode == 0, result.stdout + result.stderr
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            assert db.execute("SELECT os_arch FROM machine_machine WHERE id=?", (machine_pk,)).fetchone() == (other_arch,)
            new_pk, new_arch = db.execute("SELECT id, os_arch FROM machine_machine WHERE guid=?", (guid,)).fetchone()
        assert new_pk != machine_pk
        assert new_arch == platform.machine()


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
