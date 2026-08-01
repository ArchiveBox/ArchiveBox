import sqlite3
from uuid import UUID

from .migrations_helpers import (
    SCHEMA_0_7,
    create_data_dir_structure,
    run_archivebox_migration_cmd,
    seed_0_7_data,
)


def test_0029_preserves_duplicate_and_malformed_legacy_uuids(tmp_path):
    """Every 0.7.4 ArchiveResult must survive conversion to a unique UUID PK."""
    db_path = tmp_path / "index.sqlite3"
    create_data_dir_structure(tmp_path)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_0_7)
    conn.close()
    seed_0_7_data(db_path)

    duplicate_uuid = "12345678123456781234567812345678"
    conn = sqlite3.connect(db_path)
    source_rows = conn.execute(
        "SELECT id, snapshot_id, extractor, status, output FROM core_archiveresult ORDER BY id",
    ).fetchall()
    for row_number, (result_id, *_metadata) in enumerate(source_rows, start=1):
        conn.execute(
            "UPDATE core_archiveresult SET uuid = ? WHERE id = ?",
            (f"{row_number:032x}", result_id),
        )
    conn.execute(
        "UPDATE core_archiveresult SET uuid = ? WHERE id IN (?, ?)",
        (duplicate_uuid, source_rows[0][0], source_rows[1][0]),
    )
    conn.execute("UPDATE core_archiveresult SET uuid = ? WHERE id = ?", ("not-a-valid-uuid", source_rows[2][0]))
    conn.commit()

    expected_results = sorted(row[1:] for row in source_rows)
    conn.close()

    result = run_archivebox_migration_cmd(tmp_path, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    conn = sqlite3.connect(db_path)
    migrated_rows = conn.execute(
        "SELECT id, snapshot_id, plugin, status, output_str FROM core_archiveresult ORDER BY snapshot_id, plugin",
    ).fetchall()
    conn.close()

    migrated_ids = [row[0] for row in migrated_rows]
    assert len(migrated_rows) == len(source_rows)
    assert len(set(migrated_ids)) == len(source_rows)
    assert all(UUID(result_id).hex == result_id for result_id in migrated_ids)
    assert sorted(row[1:] for row in migrated_rows) == expected_results
