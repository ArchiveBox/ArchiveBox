from __future__ import annotations

import atexit
import os
import sqlite3
import threading
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


# WHY: Django's ASGI handler runs each request's sync code in a brand-new
# thread (asgiref ThreadSensitiveContext), so thread-local connections never
# outlive one request. Opening one costs sqlite3.connect, ~40 function
# registrations and ~10 PRAGMAs: ~15-19% of the CPU of a snap-host file GET on
# the demo host. A cleanly closed autocommit connection is instead parked here
# for the next thread. Idle connections hold no locks, and they are checked out
# exclusively (Django already opens SQLite with check_same_thread=False).
_IDLE_CONNECTIONS: dict[tuple, list[tuple[tuple[int, int], sqlite3.Connection]]] = {}
_IDLE_CONNECTIONS_LOCK = threading.Lock()
_MAX_IDLE_CONNECTIONS = 16


def _database_file_identity(path: str) -> tuple[int, int] | None:
    # A pooled connection keeps its file open, so its inode cannot be reused:
    # a changed (dev, inode) reliably means the database file was replaced.
    try:
        stat = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return (stat.st_dev, stat.st_ino)


def close_idle_connections() -> None:
    with _IDLE_CONNECTIONS_LOCK:
        idle = [conn for pool in _IDLE_CONNECTIONS.values() for _identity, conn in pool]
        _IDLE_CONNECTIONS.clear()
    for conn in idle:
        try:
            conn.close()
        except sqlite3.Error:
            pass


# Callers that close connections before forking expect none to stay open.
os.register_at_fork(before=close_idle_connections)
atexit.register(close_idle_connections)


class DatabaseWrapper(DjangoSQLiteDatabaseWrapper):
    _idle_pool_key: tuple | None = None
    _connection_file_identity: tuple[int, int] | None = None

    def get_new_connection(self, conn_params):
        self._idle_pool_key = None
        self._connection_file_identity = None
        if not self.is_in_memory_db():
            key = (os.getpid(), self.alias, tuple(sorted(conn_params.items())), tuple(self.init_commands))
            identity = _database_file_identity(conn_params["database"])
            stale: list[sqlite3.Connection] = []
            conn = None
            with _IDLE_CONNECTIONS_LOCK:
                pool = _IDLE_CONNECTIONS.get(key) or []
                while pool:
                    pooled_identity, pooled_conn = pool.pop()
                    if identity is not None and pooled_identity == identity:
                        conn = pooled_conn
                        break
                    stale.append(pooled_conn)
            for stale_conn in stale:
                stale_conn.close()
            self._idle_pool_key = key
            if conn is not None:
                self._connection_file_identity = identity
                return conn
        conn = super().get_new_connection(conn_params)
        if self._idle_pool_key is not None:
            self._connection_file_identity = _database_file_identity(conn_params["database"])
        return conn

    def _close(self):
        conn = self.connection
        key = self._idle_pool_key
        if conn is not None and key is not None and key[0] == os.getpid() and not self.in_atomic_block:
            identity = _database_file_identity(self.settings_dict["NAME"])
            try:
                # The pathname may have been replaced while this request held
                # the old file open. Never label that handle with the new inode.
                reusable = identity is not None and identity == self._connection_file_identity and not conn.in_transaction
            except sqlite3.Error:
                reusable = False
            if reusable:
                with _IDLE_CONNECTIONS_LOCK:
                    pool = _IDLE_CONNECTIONS.setdefault(key, [])
                    if len(pool) < _MAX_IDLE_CONNECTIONS:
                        pool.append((identity, conn))
                        return None
        return super()._close()

    def create_cursor(self, name=None):
        cursor = self.connection.cursor(factory=SQLiteCursorWrapper)
        cursor.db_wrapper = self
        return cursor

    def _commit(self):
        return _retry_locked_database(lambda: super(DatabaseWrapper, self)._commit(), "COMMIT", db_wrapper=self)

    def _rollback(self):
        return _retry_locked_database(lambda: super(DatabaseWrapper, self)._rollback(), "ROLLBACK", db_wrapper=self)
