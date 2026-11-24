"""Planner maintenance refreshes useful statistics without rescanning idle history."""

import pytest
import sqlite3
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def empty_database(tmp_path):
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    with use_archivebox_db(tmp_path):
        yield


@pytest.mark.parametrize("queried", [False, True], ids=["unqueried", "queried"])
def test_sqlite_maintenance_refreshes_missing_and_grown_statistics_only(empty_database, queried):
    from archivebox.misc.db import run_db_optimize

    statements = []
    # Before 3.46, optimize considers only tables used by this connection.
    # The newer all-tables bit also covers unqueried tables; older SQLite
    # ignores that bit while retaining its useful queried-table maintenance.
    expects_analysis = queried or sqlite3.sqlite_version_info >= (3, 46, 0)
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE maintenance_items (id INTEGER PRIMARY KEY, category TEXT, label TEXT)")
        cursor.execute("CREATE INDEX maintenance_category ON maintenance_items(category)")
        cursor.executemany(
            "INSERT INTO maintenance_items(category, label) VALUES (%s, %s)",
            [(f"category-{index % 10}", f"item-{index}") for index in range(200)],
        )
        if queried:
            cursor.execute("SELECT id FROM maintenance_items WHERE category = %s LIMIT 1", ("category-0",))
            assert cursor.fetchone() is not None
        cursor.execute("PRAGMA analysis_limit")
        original_limit = cursor.fetchone()[0]
        cursor.execute("PRAGMA busy_timeout")
        original_timeout = cursor.fetchone()[0]

    def read_index_stat(cursor, index):
        # Older SQLite may not create sqlite_stat1 until the first analysis.
        cursor.execute("SELECT 1 FROM sqlite_schema WHERE name = 'sqlite_stat1' AND type = 'table'")
        if cursor.fetchone() is None:
            return None
        cursor.execute("SELECT stat FROM sqlite_stat1 WHERE idx = %s", (index,))
        return cursor.fetchone()

    connection.connection.set_trace_callback(statements.append)
    try:
        run_db_optimize()
        with connection.cursor() as cursor:
            initial_stat = read_index_stat(cursor, "maintenance_category")
        if expects_analysis:
            assert initial_stat is not None
            initial_count = int(initial_stat[0].split()[0])
            assert initial_count >= 200
        else:
            assert initial_stat is None

        statements.clear()
        run_db_optimize()
        assert not any("ANALYZE" in sql.upper() for sql in statements), statements

        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO maintenance_items(category, label) VALUES (%s, %s)",
                [(f"category-{index % 10}", f"item-{index}") for index in range(200, 20000)],
            )
        run_db_optimize()
        with connection.cursor() as cursor:
            grown_stat = read_index_stat(cursor, "maintenance_category")
            if expects_analysis:
                assert grown_stat is not None
                assert int(grown_stat[0].split()[0]) > initial_count * 10
            else:
                assert grown_stat is None
            cursor.execute("CREATE INDEX maintenance_label ON maintenance_items(label)")
        run_db_optimize()
        with connection.cursor() as cursor:
            new_index_stat = read_index_stat(cursor, "maintenance_label")
            if expects_analysis:
                assert new_index_stat is not None
                assert int(new_index_stat[0].split()[0]) >= 20000
            else:
                assert new_index_stat is None
            cursor.execute("SELECT COUNT(*) FROM maintenance_items")
            assert cursor.fetchone()[0] == 20000
            cursor.execute("PRAGMA analysis_limit")
            assert cursor.fetchone()[0] == original_limit
            cursor.execute("PRAGMA busy_timeout")
            assert cursor.fetchone()[0] == original_timeout
    finally:
        connection.connection.set_trace_callback(None)
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE maintenance_items")
