"""SQLite connection reuse across short-lived request threads.

Django's ASGI handler gives every request a new thread, so per-thread
connections were opened and closed on every request. These tests drive real
DatabaseWrapper instances against real SQLite files, one wrapper per thread,
exactly like Django's thread-local connection handler does under ASGI.
"""

import os
import sqlite3
import threading

import pytest
from django.db import connection

from archivebox.core.sqlite_backend.base import DatabaseWrapper, close_idle_connections

# pytest-django blocks all connections unless the test opts in.
pytestmark = pytest.mark.django_db


def _run_in_new_thread(fn):
    result = {}

    def target():
        try:
            result["value"] = fn()
        except BaseException as err:  # surfaced in the test thread below
            result["error"] = err

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


def _request(db_path, *statements):
    """One request: a fresh thread-local wrapper that runs SQL and then closes."""

    def run():
        db = DatabaseWrapper({**connection.settings_dict, "NAME": str(db_path)}, alias="sqlite-reuse-test")
        rows = []
        with db.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
                rows = cursor.fetchall()
        raw = db.connection
        db.close()
        return raw, rows

    return _run_in_new_thread(run)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "reuse.sqlite3"
    sqlite3.connect(path).close()
    yield path
    close_idle_connections()


def test_closed_connection_is_reused_by_next_request_thread(db_path):
    first, _rows = _request(db_path, "CREATE TABLE item (name TEXT)", "INSERT INTO item VALUES ('saved')")
    second, rows = _request(db_path, "SELECT name FROM item")
    assert second is first
    assert rows == [("saved",)]
    # Connection setup still applies to the reused connection.
    _third, pragma_rows = _request(db_path, "PRAGMA foreign_keys")
    assert pragma_rows == [(1,)]


def test_connection_closed_inside_transaction_is_really_closed(db_path):
    first, _rows = _request(db_path, "BEGIN", "CREATE TABLE pending (name TEXT)")
    second, rows = _request(db_path, "SELECT name FROM sqlite_master WHERE name = 'pending'")
    assert second is not first
    assert rows == []
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")


def test_replaced_database_file_is_not_reused(db_path):
    first, _rows = _request(db_path, "CREATE TABLE old_file (name TEXT)")
    replacement = db_path.with_name("replacement.sqlite3")
    sqlite3.connect(replacement).close()
    os.replace(replacement, db_path)

    second, rows = _request(db_path, "SELECT name FROM sqlite_master WHERE name = 'old_file'")
    assert second is not first
    assert rows == []
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")
