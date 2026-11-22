"""Public pagination must work on both sides of the retired index migration."""

import sqlite3

import pytest

from archivebox.tests.conftest import cli_env, run_archivebox_cmd


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("existing_index", [False, True])
def test_public_page_index_upgrade(tmp_path, existing_index):
    env = cli_env(PERMISSIONS="public")

    def run(*args):
        result = run_archivebox_cmd(list(args), cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr or result.stdout
        return result

    run("init")
    run("snapshot", "create", "https://index-migration.example/")
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        snapshots = db.execute("SELECT id, url, permissions FROM core_snapshot").fetchall()
        assert len(snapshots) == 1
        assert snapshots[0][1:] == ("https://index-migration.example/", "public")
        assert db.execute("SELECT name FROM sqlite_master WHERE name='snapshot_public_page_idx'").fetchall() == []

    run("manage", "migrate", "core", "0064", "--noinput")
    sql = run("manage", "sqlmigrate", "core", "0065").stdout
    assert "CREATE INDEX" not in sql.upper()
    run("manage", "migrate", "core", "0065", "--noinput")
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='snapshot_public_page_idx'").fetchall() == []
        if existing_index:
            # The exact physical index installed by the original 0065. Its
            # migration is already recorded, so upgrades will not rerun it.
            db.execute(
                'CREATE INDEX "snapshot_public_page_idx" ON "core_snapshot" ("permissions", "bookmarked_at" DESC, "created_at" DESC, "id")',
            )

    run("manage", "migrate", "--noinput")
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='snapshot_public_page_idx'").fetchall() == []
        assert db.execute("SELECT id, url, permissions FROM core_snapshot").fetchall() == snapshots
        indexes = {row[1] for row in db.execute("PRAGMA index_list(core_snapshot)")}
        assert "snapshot_public_order_idx" in indexes
        assert "core_snapshot_permissions_37149de9" in indexes
        assert "core_snapshot_bookmarked_at_611211c2" in indexes

    run("manage", "makemigrations", "core", "--check", "--dry-run")
    # Rolling back the cleanup must not resurrect the retired index. Reapplying
    # the migration must also succeed when the physical index is absent.
    run("manage", "migrate", "core", "0065", "--noinput")
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='snapshot_public_page_idx'").fetchall() == []
    run("manage", "migrate", "--noinput")
