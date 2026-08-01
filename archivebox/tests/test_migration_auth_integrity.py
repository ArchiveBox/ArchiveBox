import sqlite3

import pytest

from .migrations_helpers import (
    SCHEMA_0_7,
    SCHEMA_0_8,
    create_data_dir_structure,
    run_archivebox_migration_cmd,
    seed_0_7_data,
    seed_0_8_data,
)


AUTH_TABLE_COLUMNS = {
    "django_content_type": ("id", "app_label", "model"),
    "auth_permission": ("id", "name", "content_type_id", "codename"),
    "auth_group": ("id", "name"),
    "auth_group_permissions": ("id", "group_id", "permission_id"),
    "auth_user": (
        "id",
        "password",
        "last_login",
        "is_superuser",
        "username",
        "first_name",
        "last_name",
        "email",
        "is_staff",
        "is_active",
        "date_joined",
    ),
    "auth_user_groups": ("id", "user_id", "group_id"),
    "auth_user_user_permissions": ("id", "user_id", "permission_id"),
}

API_TABLE_COLUMNS = {
    "api_apitoken": ("id", "created_by_id", "created_at", "modified_at", "token", "expires"),
    "api_outboundwebhook": (
        "id",
        "created_by_id",
        "created_at",
        "modified_at",
        "name",
        "signal",
        "ref",
        "endpoint",
        "headers",
        "auth_token",
        "enabled",
        "keep_last_response",
        "last_response",
        "last_success",
        "last_failure",
        "num_uses_failed",
        "num_uses_succeeded",
    ),
}


def _seed_auth_security_metadata(conn: sqlite3.Connection, include_api: bool) -> None:
    admin_id = conn.execute("SELECT id FROM auth_user WHERE username = 'admin'").fetchone()[0]
    conn.execute(
        """
        UPDATE auth_user
        SET password = ?, last_login = ?, is_superuser = ?, first_name = ?, last_name = ?,
            email = ?, is_staff = ?, is_active = ?, date_joined = ?
        WHERE id = ?
        """,
        (
            "pbkdf2_sha256$390000$legacy-admin$sensitive-admin-password-hash",
            "2024-01-02 03:04:05.123456",
            1,
            "Legacy",
            "Administrator",
            "legacy-admin@example.com",
            1,
            1,
            "2019-02-03 04:05:06.654321",
            admin_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO auth_user (
            password, last_login, is_superuser, username, first_name, last_name,
            email, is_staff, is_active, date_joined
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pbkdf2_sha256$390000$legacy-reader$sensitive-reader-password-hash",
            "2023-11-12 13:14:15.111222",
            0,
            "legacy-reader",
            "Legacy",
            "Reader",
            "legacy-reader@example.com",
            0,
            1,
            "2020-06-07 08:09:10.333444",
        ),
    )
    reader_id = conn.execute("SELECT id FROM auth_user WHERE username = 'legacy-reader'").fetchone()[0]

    snapshot_content_type_id = conn.execute(
        "SELECT id FROM django_content_type WHERE app_label = 'core' AND model = 'snapshot'",
    ).fetchone()[0]
    archiveresult_content_type_id = conn.execute(
        "SELECT id FROM django_content_type WHERE app_label = 'core' AND model = 'archiveresult'",
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO auth_permission (name, content_type_id, codename) VALUES (?, ?, ?)",
        ("Can export legacy snapshots", snapshot_content_type_id, "export_legacy_snapshot"),
    )
    export_permission_id = conn.execute(
        "SELECT id FROM auth_permission WHERE codename = 'export_legacy_snapshot'",
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO auth_permission (name, content_type_id, codename) VALUES (?, ?, ?)",
        ("Can audit legacy results", archiveresult_content_type_id, "audit_legacy_archiveresult"),
    )
    audit_permission_id = conn.execute(
        "SELECT id FROM auth_permission WHERE codename = 'audit_legacy_archiveresult'",
    ).fetchone()[0]

    conn.execute("INSERT INTO auth_group (name) VALUES (?)", ("Legacy Operators",))
    operators_group_id = conn.execute("SELECT id FROM auth_group WHERE name = 'Legacy Operators'").fetchone()[0]
    conn.execute("INSERT INTO auth_group (name) VALUES (?)", ("Legacy Auditors",))
    auditors_group_id = conn.execute("SELECT id FROM auth_group WHERE name = 'Legacy Auditors'").fetchone()[0]
    conn.executemany(
        "INSERT INTO auth_group_permissions (group_id, permission_id) VALUES (?, ?)",
        (
            (operators_group_id, export_permission_id),
            (operators_group_id, audit_permission_id),
            (auditors_group_id, audit_permission_id),
        ),
    )
    conn.executemany(
        "INSERT INTO auth_user_groups (user_id, group_id) VALUES (?, ?)",
        ((admin_id, operators_group_id), (reader_id, auditors_group_id)),
    )
    conn.executemany(
        "INSERT INTO auth_user_user_permissions (user_id, permission_id) VALUES (?, ?)",
        ((admin_id, audit_permission_id), (reader_id, export_permission_id)),
    )

    if include_api:
        conn.execute(
            """
            INSERT INTO api_apitoken (id, created_by_id, created_at, modified_at, token, expires)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "12345678123456781234567812345678",
                admin_id,
                "2022-01-02 03:04:05.123456",
                "2023-02-03 04:05:06.234567",
                "0123456789abcdef0123456789abcdef",
                "2032-03-04 05:06:07.345678",
            ),
        )
        conn.execute(
            """
            INSERT INTO api_outboundwebhook (
                id, created_by_id, created_at, modified_at, name, signal, ref, endpoint,
                headers, auth_token, enabled, keep_last_response, last_response,
                last_success, last_failure, num_uses_failed, num_uses_succeeded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "87654321876543218765432187654321",
                reader_id,
                "2021-04-05 06:07:08.456789",
                "2023-05-06 07:08:09.567890",
                "Legacy Snapshot Audit",
                "CREATE_UPDATE_OR_DELETE",
                "core.Snapshot",
                "https://hooks.example.com/archivebox/legacy",
                '{"X-ArchiveBox-Origin":"legacy","X-Webhook-Version":"0.8"}',
                "legacy-webhook-auth-token",
                0,
                1,
                '{"status":"preserved","request_id":"legacy-123"}',
                "2023-06-07 08:09:10.678901",
                "2023-07-08 09:10:11.789012",
                17,
                31,
            ),
        )


def _capture_rows(conn: sqlite3.Connection, tables: dict[str, tuple[str, ...]]) -> dict[str, list[tuple]]:
    return {
        table: conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}",
        ).fetchall()
        for table, columns in tables.items()
    }


def _assert_original_rows_preserved(
    conn: sqlite3.Connection,
    original_rows: dict[str, list[tuple]],
    tables: dict[str, tuple[str, ...]],
) -> None:
    for table, expected_rows in original_rows.items():
        columns = tables[table]
        current_rows = {
            row[0]: row
            for row in conn.execute(
                f"SELECT {', '.join(columns)} FROM {table}",
            ).fetchall()
        }
        for expected_row in expected_rows:
            assert current_rows.get(expected_row[0]) == expected_row, f"{table} row {expected_row[0]!r} changed during migration"


@pytest.mark.parametrize(
    ("schema", "seed_data", "include_api"),
    ((SCHEMA_0_7, seed_0_7_data, False), (SCHEMA_0_8, seed_0_8_data, True)),
    ids=("0.7", "0.8"),
)
def test_auth_security_metadata_survives_two_real_cli_migrations(tmp_path, schema, seed_data, include_api):
    create_data_dir_structure(tmp_path)
    db_path = tmp_path / "index.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.close()
    seed_data(db_path)

    tables = {**AUTH_TABLE_COLUMNS, **(API_TABLE_COLUMNS if include_api else {})}
    conn = sqlite3.connect(db_path)
    _seed_auth_security_metadata(conn, include_api=include_api)
    original_rows = _capture_rows(conn, tables)
    original_group_relations = {
        table: rows
        for table, rows in original_rows.items()
        if table in {"auth_group", "auth_group_permissions", "auth_user_groups", "auth_user_user_permissions"}
    }
    original_api_rows = {table: rows for table, rows in original_rows.items() if table.startswith("api_")}
    original_usernames = {row[4] for row in original_rows["auth_user"]}
    conn.commit()
    conn.close()

    for init_number in (1, 2):
        result = run_archivebox_migration_cmd(tmp_path, ["init"], timeout=90)
        assert result.returncode == 0, f"Init {init_number} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

        conn = sqlite3.connect(db_path)
        _assert_original_rows_preserved(conn, original_rows, tables)
        assert _capture_rows(conn, {table: tables[table] for table in original_group_relations}) == original_group_relations
        assert _capture_rows(conn, {table: tables[table] for table in original_api_rows}) == original_api_rows
        current_usernames = {row[0] for row in conn.execute("SELECT username FROM auth_user")}
        assert current_usernames - original_usernames <= {"system"}
        conn.close()
