"""Upgrade the physical SQLite tag association column left by UUID-era collections."""

import sqlite3
from contextlib import closing

import pytest

from archivebox.tests.conftest import cli_env, run_archivebox_cmd


TABLE = "core_snapshot_tags"


def catalog(db):
    return db.execute("SELECT type, name, rootpage, sql FROM sqlite_schema WHERE tbl_name = ? ORDER BY name", (TABLE,)).fetchall()


def memberships(db):
    return db.execute(f"SELECT id, snapshot_id, tag_id FROM {TABLE} ORDER BY id").fetchall()


def sequence(db):
    return db.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (TABLE,)).fetchone()[0]


def tag_id_type(db):
    return next(row[2] for row in db.execute(f"PRAGMA table_info({TABLE})") if row[1] == "tag_id")


@pytest.fixture
def tag_migration_collection(tmp_path):
    path = tmp_path / "index.sqlite3"
    env = cli_env(disable_extractors=True, ARCHIVEBOX_DATABASE_ENGINE="sqlite", ARCHIVEBOX_DATABASE_NAME=str(path))

    def run(*args, expected_exit=0):
        result = run_archivebox_cmd(list(args), cwd=tmp_path, env=env)
        assert result.returncode == expected_exit, result.stderr or result.stdout
        return result

    run("init", "--quick")
    run("snapshot", "create", "https://www.sqlite.org/datatype3.html", "--tag", "sqlite,types")
    run("snapshot", "create", "https://www.sqlite.org/foreignkeys.html", "--tag", "sqlite")
    run("manage", "migrate", "core", "0067", "--noinput")
    return path, run


def use_legacy_tag_affinity(db):
    # The old UUID association table stayed in place after core_tag switched
    # to integer IDs. Preserve its foreign keys and indexes in the fixture.
    schema = catalog(db)
    ddl = next(sql for kind, name, _, sql in schema if kind == "table")
    legacy_ddl = ddl.replace('"tag_id" integer', '"tag_id" char(32)').replace(f'"{TABLE}"', '"legacy_snapshot_tags"', 1)
    assert legacy_ddl != ddl
    db.execute(legacy_ddl)
    db.execute(f"INSERT INTO legacy_snapshot_tags (id, snapshot_id, tag_id) SELECT id, snapshot_id, tag_id FROM {TABLE}")
    db.execute(f"DROP TABLE {TABLE}")
    db.execute(f"ALTER TABLE legacy_snapshot_tags RENAME TO {TABLE}")
    for kind, name, _, sql in schema:
        if kind == "index" and sql is not None:
            db.execute(sql)
    assert tag_id_type(db) == "char(32)"


@pytest.mark.parametrize(
    ("legacy", "empty"),
    [(False, False), (True, False), (True, True)],
    ids=["integer-schema-no-op", "uuid-era-text-affinity", "empty-legacy-table"],
)
def test_snapshot_tag_id_migration(tag_migration_collection, legacy, empty):
    path, run = tag_migration_collection
    with closing(sqlite3.connect(path)) as db, db:
        original = memberships(db)
        assert len(original) == 3
        assert tag_id_type(db).lower() == "integer"
        if legacy:
            use_legacy_tag_affinity(db)
            assert memberships(db) == [(id_, snapshot_id, str(tag_id)) for id_, snapshot_id, tag_id in original]
        if empty:
            db.execute(f"DELETE FROM {TABLE}")
            original = []
        # Deleted memberships may leave the high-water mark ahead of MAX(id).
        db.execute("UPDATE sqlite_sequence SET seq = seq + 10 WHERE name = ?", (TABLE,))
        original_sequence = sequence(db)
        original_schema = catalog(db)
        original_indexes = [row for row in original_schema if row[0] == "index"]
        assert len(original_indexes) == 3
        original_fks = db.execute(f"PRAGMA foreign_key_list({TABLE})").fetchall()
        assert {row[2:5] for row in original_fks} == {("core_snapshot", "snapshot_id", "id"), ("core_tag", "tag_id", "id")}
        assert db.execute(f"PRAGMA foreign_key_check({TABLE})").fetchall() == []

    run("manage", "migrate", "core", "--noinput")
    with closing(sqlite3.connect(path)) as db:
        assert tag_id_type(db).lower() == "integer"
        assert memberships(db) == original
        assert sequence(db) == original_sequence
        assert db.execute(f"PRAGMA foreign_key_list({TABLE})").fetchall() == original_fks
        assert db.execute(f"PRAGMA foreign_key_check({TABLE})").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        updated_schema = catalog(db)
        updated_table = next(sql for kind, _, _, sql in updated_schema if kind == "table")
        assert updated_table.count("DEFERRABLE INITIALLY DEFERRED") == 2
        assert [(kind, name, sql) for kind, name, _, sql in updated_schema if kind == "index"] == [
            (kind, name, sql) for kind, name, _, sql in original_indexes
        ]
        if not legacy:
            assert updated_schema == original_schema

    # Exercise a normal write and verify the repair did not reset AUTOINCREMENT.
    run("snapshot", "create", "https://www.sqlite.org/withoutrowid.html", "--tag", "sqlite")
    with closing(sqlite3.connect(path)) as db:
        assert memberships(db)[:-1] == original
        assert memberships(db)[-1][0] > original_sequence
        assert db.execute(f"PRAGMA foreign_key_check({TABLE})").fetchall() == []


@pytest.mark.parametrize("orphaned_snapshot", [False, True], ids=["duplicate-tag-id", "orphaned-snapshot"])
def test_snapshot_tag_id_migration_rejects_invalid_memberships(tag_migration_collection, orphaned_snapshot):
    path, run = tag_migration_collection
    with closing(sqlite3.connect(path)) as db, db:
        use_legacy_tag_affinity(db)
        _, snapshot_id, tag_id = memberships(db)[0]
        if orphaned_snapshot:
            # A valid tag and stale snapshot ID reach the post-copy FK check.
            db.execute(f"INSERT INTO {TABLE} (snapshot_id, tag_id) VALUES (?, ?)", ("0" * 32, tag_id))
        else:
            # Both tag spellings pass the old FK but cannot both survive
            # the uniqueness constraint.
            db.execute(f"INSERT INTO {TABLE} (snapshot_id, tag_id) VALUES (?, ?)", (snapshot_id, "0" + tag_id))
        original_fk_violations = db.execute(f"PRAGMA foreign_key_check({TABLE})").fetchall()
        assert len(original_fk_violations) == int(orphaned_snapshot)
        original_schema = catalog(db)
        original = memberships(db)
        original_sequence = sequence(db)
        migrations = db.execute("SELECT app, name FROM django_migrations ORDER BY id").fetchall()

    result = run("manage", "migrate", "core", "--noinput", expected_exit=1)
    assert "Applying core.0068_repair_snapshot_tag_id" in result.stdout
    assert ("Foreign key violation" if orphaned_snapshot else "Invalid tag_id") in result.stderr
    with closing(sqlite3.connect(path)) as db:
        assert catalog(db) == original_schema
        assert memberships(db) == original
        assert sequence(db) == original_sequence
        assert db.execute("SELECT app, name FROM django_migrations ORDER BY id").fetchall() == migrations
        assert db.execute(f"PRAGMA foreign_key_check({TABLE})").fetchall() == original_fk_violations
