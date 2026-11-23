"""Planner maintenance refreshes useful statistics without rescanning idle history."""

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def empty_database(tmp_path):
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    with use_archivebox_db(tmp_path):
        yield


def test_sqlite_maintenance_refreshes_missing_and_grown_statistics_only(empty_database):
    from archivebox.misc.db import run_db_optimize

    statements = []
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE maintenance_items (id INTEGER PRIMARY KEY, category TEXT, label TEXT)")
        cursor.execute("CREATE INDEX maintenance_category ON maintenance_items(category)")
        cursor.executemany(
            "INSERT INTO maintenance_items(category, label) VALUES (%s, %s)",
            [(f"category-{index % 10}", f"item-{index}") for index in range(200)],
        )
        # Older SQLite only considers tables this connection has queried.
        cursor.execute("SELECT id FROM maintenance_items WHERE category = %s LIMIT 1", ("category-0",))
        cursor.fetchone()
        cursor.execute("PRAGMA analysis_limit")
        original_limit = cursor.fetchone()[0]
        cursor.execute("PRAGMA busy_timeout")
        original_timeout = cursor.fetchone()[0]
    connection.connection.set_trace_callback(statements.append)
    try:
        run_db_optimize()
        with connection.cursor() as cursor:
            cursor.execute("SELECT stat FROM sqlite_stat1 WHERE idx = 'maintenance_category'")
            initial_count = int(cursor.fetchone()[0].split()[0])
        assert initial_count >= 200

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
            assert int(cursor.fetchone()[0].split()[0]) > initial_count * 10
            cursor.execute("CREATE INDEX maintenance_label ON maintenance_items(label)")
        run_db_optimize()
        with connection.cursor() as cursor:
            cursor.execute("SELECT stat FROM sqlite_stat1 WHERE idx = 'maintenance_label'")
            assert int(cursor.fetchone()[0].split()[0]) >= 20000
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
