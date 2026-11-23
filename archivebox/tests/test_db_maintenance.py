"""Planner maintenance refreshes useful statistics without rescanning idle history."""

import pytest
import sqlite3
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


def test_sqlite_maintenance_refreshes_missing_and_grown_statistics_only():
    from archivebox.misc.db import run_db_optimize

    statements = []
    # Older SQLite accepts unknown optimize bits without doing the newer
    # all-table analysis. That best-effort no-op remains supported.
    analyzes_unqueried_tables = sqlite3.sqlite_version_info >= (3, 46, 0)
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE maintenance_items (id INTEGER PRIMARY KEY, category TEXT, label TEXT)")
        cursor.execute("CREATE INDEX maintenance_category ON maintenance_items(category)")
        cursor.executemany(
            "INSERT INTO maintenance_items(category, label) VALUES (%s, %s)",
            [(f"category-{index % 10}", f"item-{index}") for index in range(200)],
        )
        cursor.execute("PRAGMA analysis_limit")
        original_limit = cursor.fetchone()[0]
        cursor.execute("PRAGMA busy_timeout")
        original_timeout = cursor.fetchone()[0]
    connection.connection.set_trace_callback(statements.append)
    try:
        run_db_optimize()
        with connection.cursor() as cursor:
            cursor.execute("SELECT stat FROM sqlite_stat1 WHERE idx = 'maintenance_category'")
            initial_stat = cursor.fetchone()
        if analyzes_unqueried_tables:
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
            cursor.execute("SELECT stat FROM sqlite_stat1 WHERE idx = 'maintenance_category'")
            grown_stat = cursor.fetchone()
            if analyzes_unqueried_tables:
                assert grown_stat is not None
                assert int(grown_stat[0].split()[0]) > initial_count * 10
            else:
                assert grown_stat is None
            cursor.execute("CREATE INDEX maintenance_label ON maintenance_items(label)")
        run_db_optimize()
        with connection.cursor() as cursor:
            cursor.execute("SELECT stat FROM sqlite_stat1 WHERE idx = 'maintenance_label'")
            new_index_stat = cursor.fetchone()
            if analyzes_unqueried_tables:
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
