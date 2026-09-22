from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from itertools import tee
import re

from django.db.backends.sqlite3.base import DatabaseWrapper as DjangoSQLiteDatabaseWrapper
from django.db.backends.sqlite3.base import SQLiteCursorWrapper as DjangoSQLiteCursorWrapper


def _sqlite_lock_retry_timeout() -> float:
    from django.conf import settings

    return settings.CONFIG.SQLITE_LOCK_RETRY_TIMEOUT


def _sqlite_lock_retry_interval() -> float:
    from django.conf import settings

    return settings.CONFIG.SQLITE_LOCK_RETRY_INTERVAL


def _format_sql(query: str, params=None) -> str:
    compact = " ".join(str(query).split())
    match = re.match(r'^(INSERT INTO|UPDATE|DELETE FROM|SELECT) "?([A-Za-z0-9_]+)"?', compact, flags=re.IGNORECASE)
    if match:
        compact = f"{match.group(1).upper()} {match.group(2)}"
    if params is not None:
        if isinstance(params, str):
            params_summary = params
        elif isinstance(params, (tuple, list)):
            preview = ", ".join(repr(param)[:60] for param in params[:4])
            params_summary = f"{len(params)} params: {preview}"
        elif isinstance(params, Mapping):
            preview = ", ".join(f"{key}={repr(value)[:60]}" for key, value in list(params.items())[:4])
            params_summary = f"{len(params)} params: {preview}"
        else:
            params_summary = repr(params)[:120]
        compact = f"{compact} ({params_summary})"
    return compact[:260]


def _log_locked_database(query: str, params=None, *, attempt: int, elapsed: float, retry_interval: float) -> None:
    from rich.console import Console

    from archivebox.misc.db import log_sqlite_lock_holders

    console = Console(stderr=True)
    console.print(
        f"[yellow][*] SQLite database is locked for {elapsed:.0f}s; retrying in {retry_interval:g}s... attempt={attempt}[/yellow]",
    )
    console.print(f"[yellow]    Query: {_format_sql(query, params)}[/yellow]")
    log_sqlite_lock_holders(console)


def _connection_in_transaction(connection) -> bool:
    try:
        return bool(connection and connection.in_transaction)
    except (AttributeError, sqlite3.Error):
        return False


def _recover_non_atomic_connection(db_wrapper, query: str) -> None:
    if db_wrapper is None or getattr(db_wrapper, "in_atomic_block", False):
        return
    connection = getattr(db_wrapper, "connection", None)
    if not _connection_in_transaction(connection):
        return
    try:
        connection.rollback()
    except sqlite3.Error:
        return


def _is_inside_atomic(db_wrapper) -> bool:
    return bool(db_wrapper is not None and getattr(db_wrapper, "in_atomic_block", False))


def _abort_locked_database(query: str, params=None, *, elapsed: float, db_wrapper=None) -> None:
    _recover_non_atomic_connection(db_wrapper, query)
    raise sqlite3.OperationalError(
        f"SQLite database remained locked for {elapsed:.0f}s while running {_format_sql(query, params)}; "
        "aborting instead of retrying indefinitely",
    )


def _retry_locked_database(action, query: str, params=None, *, db_wrapper=None):
    attempt = 0
    started_at = time.monotonic()
    while True:
        try:
            return action()
        except (sqlite3.OperationalError, Exception) as err:
            from archivebox.misc.db import sqlite_lock_error

            if not sqlite_lock_error(err):
                raise
            attempt += 1
            elapsed = time.monotonic() - started_at
            retry_timeout = _sqlite_lock_retry_timeout()
            retry_interval = _sqlite_lock_retry_interval()
            _log_locked_database(query, params, attempt=attempt, elapsed=elapsed, retry_interval=retry_interval)
            # If SQLite raised while Django is in autocommit mode, do not keep a
            # partially-open sqlite transaction around while waiting. Explicit
            # transaction.atomic() callers keep their normal transaction boundary.
            _recover_non_atomic_connection(db_wrapper, query)
            if _is_inside_atomic(db_wrapper):
                raise
            if retry_timeout and elapsed >= retry_timeout:
                _abort_locked_database(query, params, elapsed=elapsed, db_wrapper=db_wrapper)
            time.sleep(retry_interval)


class SQLiteCursorWrapper(DjangoSQLiteCursorWrapper):
    def execute(self, query, params=None):
        if params is None:
            return _retry_locked_database(
                lambda: super(SQLiteCursorWrapper, self).execute(query),
                query,
                db_wrapper=getattr(self, "db_wrapper", None),
            )
        param_names = list(params) if isinstance(params, Mapping) else None
        converted_query = self.convert_query(query, param_names=param_names)
        return _retry_locked_database(
            lambda: super(DjangoSQLiteCursorWrapper, self).execute(converted_query, params),
            converted_query,
            params,
            db_wrapper=getattr(self, "db_wrapper", None),
        )

    def executemany(self, query, param_list):
        peekable, param_list = tee(iter(param_list))
        if (params := next(peekable, None)) and isinstance(params, Mapping):
            param_names = list(params)
        else:
            param_names = None
        converted_query = self.convert_query(query, param_names=param_names)
        param_list = tuple(param_list)
        return _retry_locked_database(
            lambda: super(DjangoSQLiteCursorWrapper, self).executemany(converted_query, param_list),
            converted_query,
            f"{len(param_list)} parameter sets",
            db_wrapper=getattr(self, "db_wrapper", None),
        )


class DatabaseWrapper(DjangoSQLiteDatabaseWrapper):
    def create_cursor(self, name=None):
        cursor = self.connection.cursor(factory=SQLiteCursorWrapper)
        cursor.db_wrapper = self
        return cursor

    def _commit(self):
        return _retry_locked_database(lambda: super(DatabaseWrapper, self)._commit(), "COMMIT", db_wrapper=self)

    def _rollback(self):
        return _retry_locked_database(lambda: super(DatabaseWrapper, self)._rollback(), "ROLLBACK", db_wrapper=self)
