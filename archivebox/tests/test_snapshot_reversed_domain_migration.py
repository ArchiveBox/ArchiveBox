"""The indexed domain key is generated for existing collections during upgrade."""

import sqlite3
from contextlib import closing

import pytest

from archivebox.tests.conftest import cli_env, run_archivebox_cmd


@pytest.mark.django_db(transaction=True)
def test_snapshot_reversed_domain_migration(tmp_path):
    env = cli_env(ARCHIVEBOX_DATABASE_ENGINE="sqlite", ARCHIVEBOX_DATABASE_NAME=str(tmp_path / "index.sqlite3"), PERMISSIONS="public")

    def run(*args):
        result = run_archivebox_cmd(list(args), cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr or result.stdout

    def schema(db):
        columns = {row[1]: row[6] for row in db.execute("PRAGMA table_xinfo(core_snapshot)")}
        indexes = {row[1] for row in db.execute("PRAGMA index_list(core_snapshot)")}
        return columns, indexes

    run("init")
    run("snapshot", "create", "https://maps.google.co.uk:8080/search")
    run("manage", "migrate", "core", "0066", "--noinput")
    with closing(sqlite3.connect(tmp_path / "index.sqlite3")) as db:
        columns, indexes = schema(db)
        snapshots = db.execute("SELECT id, url, permissions FROM core_snapshot").fetchall()
        assert len(snapshots) == 1
        assert "reversed_domain" not in columns
        assert "snapshot_reversed_domain_idx" not in indexes

    run("init")
    with closing(sqlite3.connect(tmp_path / "index.sqlite3")) as db:
        assert schema(db) == ({**columns, "reversed_domain": 3}, {*indexes, "snapshot_reversed_domain_idx"})
        assert db.execute("SELECT id, url, permissions, reversed_domain FROM core_snapshot").fetchall() == [
            (*snapshots[0], "8080:uk.co.google.maps"),
        ]
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM core_snapshot WHERE reversed_domain >= ? AND reversed_domain < ?",
            ("8080:uk.co.google.", "8080:uk.co.google/"),
        ).fetchall()
        assert any("SEARCH core_snapshot USING INDEX snapshot_reversed_domain_idx" in row[3] for row in plan)
