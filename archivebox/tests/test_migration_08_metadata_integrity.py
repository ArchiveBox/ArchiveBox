import json
import sqlite3
import uuid

import pytest

from .migrations_helpers import SCHEMA_0_8, create_data_dir_structure, run_archivebox_migration_cmd, seed_0_8_data


SNAPSHOT_METADATA = {
    "depth": 7,
    "config": '{"USER_AGENT": "legacy-agent", "SAVE_SCREENSHOT": false}',
    "notes": "legacy snapshot notes",
    "num_uses_failed": 11,
    "num_uses_succeeded": 23,
    "current_step": 6,
    "fs_version": "0.8.5",
}
ARCHIVERESULT_METADATA = {
    "notes": "legacy archive result notes",
}
TAG_METADATA = {
    "created_at": "2020-01-02 03:04:05",
    "modified_at": "2021-06-07 08:09:10",
}


def _convert_tags_to_uuid(conn: sqlite3.Connection) -> None:
    tags = conn.execute("SELECT id, name, slug, created_at, modified_at, created_by_id FROM core_tag ORDER BY id").fetchall()
    snapshot_tags = conn.execute("SELECT id, snapshot_id, tag_id FROM core_snapshot_tags ORDER BY id").fetchall()
    id_map = {tag[0]: uuid.uuid4().hex for tag in tags}

    conn.executescript(
        """
        ALTER TABLE core_tag RENAME TO core_tag_integer;
        ALTER TABLE core_snapshot_tags RENAME TO core_snapshot_tags_integer;
        CREATE TABLE core_tag (
            id CHAR(36) PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            slug VARCHAR(100) NOT NULL UNIQUE,
            created_at DATETIME,
            modified_at DATETIME,
            created_by_id INTEGER REFERENCES auth_user(id)
        );
        CREATE TABLE core_snapshot_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id CHAR(36) NOT NULL REFERENCES core_snapshot(id),
            tag_id CHAR(36) NOT NULL REFERENCES core_tag(id),
            UNIQUE(snapshot_id, tag_id)
        );
        """,
    )
    conn.executemany(
        "INSERT INTO core_tag (id, name, slug, created_at, modified_at, created_by_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (id_map[tag_id], name, slug, created_at, modified_at, created_by_id)
            for tag_id, name, slug, created_at, modified_at, created_by_id in tags
        ],
    )
    conn.executemany(
        "INSERT INTO core_snapshot_tags (id, snapshot_id, tag_id) VALUES (?, ?, ?)",
        [(row_id, snapshot_id, id_map[tag_id]) for row_id, snapshot_id, tag_id in snapshot_tags],
    )
    conn.executescript("DROP TABLE core_snapshot_tags_integer; DROP TABLE core_tag_integer;")


@pytest.fixture(params=["integer_tags", "uuid_tags"])
def legacy_08_metadata_db(tmp_path, request):
    create_data_dir_structure(tmp_path)
    db_path = tmp_path / "index.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_0_8)
    conn.close()
    seeded = seed_0_8_data(db_path)

    snapshot = seeded["snapshots"][1]
    parent = seeded["snapshots"][0]
    archiveresult = next(result for result in seeded["archiveresults"] if result["snapshot_id"] == snapshot["id"])
    tag = seeded["tags"][0]
    user_id = seeded["users"][0]["id"]

    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE core_snapshot ADD COLUMN parent_snapshot_id CHAR(36) REFERENCES core_snapshot(id)")
    conn.execute("ALTER TABLE core_snapshot ADD COLUMN current_step INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE core_snapshot ADD COLUMN fs_version VARCHAR(10) NOT NULL DEFAULT '0.8.0'")
    conn.execute(
        """
        UPDATE core_snapshot
        SET depth = ?, config = ?, notes = ?, num_uses_failed = ?, num_uses_succeeded = ?,
            parent_snapshot_id = ?, current_step = ?, fs_version = ?
        WHERE id = ?
        """,
        (
            SNAPSHOT_METADATA["depth"],
            SNAPSHOT_METADATA["config"],
            SNAPSHOT_METADATA["notes"],
            SNAPSHOT_METADATA["num_uses_failed"],
            SNAPSHOT_METADATA["num_uses_succeeded"],
            parent["id"],
            SNAPSHOT_METADATA["current_step"],
            SNAPSHOT_METADATA["fs_version"],
            snapshot["id"],
        ),
    )
    conn.execute(
        """
        UPDATE core_archiveresult
        SET notes = ?
        WHERE uuid = ?
        """,
        (
            ARCHIVERESULT_METADATA["notes"],
            archiveresult["uuid"],
        ),
    )
    conn.execute(
        "UPDATE core_tag SET created_at = ?, modified_at = ?, created_by_id = ? WHERE id = ?",
        (TAG_METADATA["created_at"], TAG_METADATA["modified_at"], user_id, tag["id"]),
    )
    if request.param == "uuid_tags":
        _convert_tags_to_uuid(conn)
    expected_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("core_snapshot", "core_archiveresult", "core_tag", "core_snapshot_tags")
    }
    conn.commit()
    conn.close()

    return tmp_path, db_path, snapshot, parent, archiveresult, tag, user_id, expected_counts


def test_08_metadata_survives_complete_migration(legacy_08_metadata_db):
    work_dir, db_path, snapshot, parent, archiveresult, tag, user_id, expected_counts = legacy_08_metadata_db

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=90)
    assert result.returncode == 0, f"Init failed:\nstdout={result.stdout}\nstderr={result.stderr}"

    conn = sqlite3.connect(db_path)
    snapshot_row = conn.execute(
        """
        SELECT s.depth, s.config, s.notes, s.num_uses_failed, s.num_uses_succeeded,
               s.parent_snapshot_id, s.current_step, s.fs_version
        FROM core_snapshot s
        WHERE s.id = ?
        """,
        (snapshot["id"],),
    ).fetchone()
    archiveresult_row = conn.execute(
        """
        SELECT ar.notes
        FROM core_archiveresult ar
        WHERE ar.id = REPLACE(?, '-', '')
        """,
        (archiveresult["uuid"],),
    ).fetchone()
    tag_row = conn.execute(
        "SELECT created_at, modified_at, created_by_id FROM core_tag WHERE name = ?",
        (tag["name"],),
    ).fetchone()
    migrated_counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in expected_counts}
    parent_url = conn.execute("SELECT url FROM core_snapshot WHERE id = ?", (parent["id"],)).fetchone()
    conn.close()

    assert snapshot_row is not None
    migrated_config = json.loads(snapshot_row[1])
    legacy_config = json.loads(SNAPSHOT_METADATA["config"])
    assert all(migrated_config.get(key) == value for key, value in legacy_config.items())
    assert (snapshot_row[0], *snapshot_row[2:]) == (
        SNAPSHOT_METADATA["depth"],
        SNAPSHOT_METADATA["notes"],
        SNAPSHOT_METADATA["num_uses_failed"],
        SNAPSHOT_METADATA["num_uses_succeeded"],
        parent["id"],
        SNAPSHOT_METADATA["current_step"],
        SNAPSHOT_METADATA["fs_version"],
    )
    assert archiveresult_row == (ARCHIVERESULT_METADATA["notes"],)
    assert tag_row == (TAG_METADATA["created_at"], TAG_METADATA["modified_at"], user_id)
    assert migrated_counts == expected_counts
    assert parent_url == (parent["url"],)
