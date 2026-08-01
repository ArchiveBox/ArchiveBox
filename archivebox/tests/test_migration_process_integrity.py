import json
import os
import sqlite3
import subprocess


MIGRATION_0026 = "0026_add_process_to_archiveresult"
MIGRATION_0027 = "0027_copy_archiveresult_to_process"
NOW = "2024-01-01 12:00:00"
USER_ID = 42
CRAWL_ID = "10000000000000000000000000000000"
SNAPSHOT_ID = "20000000000000000000000000000000"


def run_migration(data_dir, target):
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(data_dir),
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            "PLUGINS": "__archivebox_test_no_plugins__",
        },
    )
    return subprocess.run(
        ["archivebox", "manage", "migrate", "core", target, "--noinput"],
        cwd=data_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def prepare_0026_database(tmp_path):
    for dirname in ("archive", "sources", "logs"):
        (tmp_path / dirname).mkdir()

    result = run_migration(tmp_path, MIGRATION_0026)
    assert result.returncode == 0, result.stdout + result.stderr

    db_path = tmp_path / "index.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            """
            INSERT INTO auth_user (
                id, password, is_superuser, username, first_name, last_name,
                email, is_staff, is_active, date_joined
            ) VALUES (?, '', 1, 'admin', '', '', '', 1, 1, ?)
            """,
            [USER_ID, NOW],
        )
        db.execute(
            """
            INSERT INTO crawls_crawl (
                id, created_at, modified_at, urls, created_by_id
            ) VALUES (?, ?, ?, '[]', ?)
            """,
            [CRAWL_ID, NOW, NOW, USER_ID],
        )
        db.execute(
            """
            INSERT INTO core_snapshot (
                id, url, timestamp, bookmarked_at, created_at, modified_at,
                fs_version, crawl_id, config, current_step, depth, notes,
                num_uses_failed, num_uses_succeeded, status
            ) VALUES (?, 'https://example.com', '20240101120000.000000', ?, ?, ?,
                      '0.8.5', ?, '{}', 0, 0, '', 0, 0, 'succeeded')
            """,
            [SNAPSHOT_ID, NOW, NOW, NOW, CRAWL_ID],
        )

    return db_path


def insert_archiveresult(db, *, result_id, command, pwd, version, status="succeeded"):
    db.execute(
        """
        INSERT INTO core_archiveresult (
            id, cmd, pwd, cmd_version, status, start_ts, end_ts, snapshot_id,
            uuid, created_at, modified_at, config, hook_name, notes,
            output_files, output_mimetypes, output_size, output_str, plugin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '', '', '{}', '', 0, '', 'wget')
        """,
        [
            result_id,
            json.dumps(command),
            pwd,
            version,
            status,
            NOW,
            NOW,
            SNAPSHOT_ID,
            f"{result_id:032d}",
            NOW,
            NOW,
        ],
    )


def table_columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def test_process_migration_rolls_back_all_rows_and_preserves_legacy_metadata_on_error(tmp_path):
    db_path = prepare_0026_database(tmp_path)
    with sqlite3.connect(db_path) as db:
        insert_archiveresult(
            db,
            result_id=1,
            command=["/usr/bin/wget", "--page-requisites", "https://example.com"],
            pwd="/data/archive/valid",
            version="1.21.4",
        )
        insert_archiveresult(
            db,
            result_id=2,
            command=[],
            pwd="/data/archive/malformed",
            version="broken-version",
            status="failed",
        )

    result = run_migration(tmp_path, MIGRATION_0027)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "has cmd_version metadata but no command" in result.stdout + result.stderr

    with sqlite3.connect(db_path) as db:
        assert {"cmd", "cmd_version", "pwd"} <= table_columns(db, "core_archiveresult")
        rows = db.execute(
            "SELECT id, cmd, pwd, cmd_version, process_id FROM core_archiveresult ORDER BY id",
        ).fetchall()
        assert rows == [
            (
                1,
                json.dumps(["/usr/bin/wget", "--page-requisites", "https://example.com"]),
                "/data/archive/valid",
                "1.21.4",
                None,
            ),
            (
                2,
                json.dumps([]),
                "/data/archive/malformed",
                "broken-version",
                None,
            ),
        ]
        assert db.execute("SELECT COUNT(*) FROM machine_process").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM machine_binary").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = 'core' AND name = ?",
                [MIGRATION_0027],
            ).fetchone()[0]
            == 0
        )


def test_process_migration_links_every_row_and_preserves_execution_metadata(tmp_path):
    db_path = prepare_0026_database(tmp_path)
    command = ["/usr/bin/wget", "--page-requisites", "https://example.com"]
    with sqlite3.connect(db_path) as db:
        insert_archiveresult(
            db,
            result_id=1,
            command=command,
            pwd="/data/archive/valid",
            version="1.21.4",
        )

    result = run_migration(tmp_path, MIGRATION_0027)
    assert result.returncode == 0, result.stdout + result.stderr

    with sqlite3.connect(db_path) as db:
        assert not ({"cmd", "cmd_version", "pwd"} & table_columns(db, "core_archiveresult"))
        row = db.execute(
            """
            SELECT process.cmd, process.pwd, binary.version, process.status,
                   process.exit_code, result.process_id
            FROM core_archiveresult AS result
            JOIN machine_process AS process ON process.id = result.process_id
            JOIN machine_binary AS binary ON binary.id = process.binary_id
            """,
        ).fetchone()
        assert row == (json.dumps(command), "/data/archive/valid", "1.21.4", "exited", 0, row[-1])
        assert row[-1]
        assert db.execute("SELECT COUNT(*) FROM core_archiveresult WHERE process_id IS NULL").fetchone()[0] == 0
