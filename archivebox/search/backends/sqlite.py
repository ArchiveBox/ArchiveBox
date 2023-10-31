import codecs
from typing import List, Generator
import sqlite3

from archivebox.util import enforce_types
from archivebox.config import (
    FTS_SEPARATE_DATABASE,
    FTS_TOKENIZERS,
    FTS_SQLITE_MAX_LENGTH
)

FTS_TABLE = "snapshot_fts"
FTS_ID_TABLE = "snapshot_id_fts"
FTS_COLUMN = "texts"

if FTS_SEPARATE_DATABASE:
    database = sqlite3.connect("search.sqlite3")
    # Make get_connection callable, because `django.db.connection.cursor()`
    # has to be called to get a context manager, but sqlite3.Connection
    # is a context manager without being called.
    def get_connection():
        return database
    SQLITE_BIND = "?"
else:
    from django.db import connection as database  # type: ignore[no-redef, assignment]
    get_connection = database.cursor
    SQLITE_BIND = "%s"

# Only Python >= 3.11 supports sqlite3.Connection.getlimit(),
# so fall back to the default if the API to get the real value isn't present
try:
    limit_id = sqlite3.SQLITE_LIMIT_LENGTH
    try:
        with database.temporary_connection() as cursor:  # type: ignore[attr-defined]
            SQLITE_LIMIT_LENGTH = cursor.connection.getlimit(limit_id)
    except AttributeError:
        SQLITE_LIMIT_LENGTH = database.getlimit(limit_id)
except AttributeError:
    SQLITE_LIMIT_LENGTH = FTS_SQLITE_MAX_LENGTH


def _escape_sqlite3(value: str, *, quote: str, errors='strict') -> str:
    assert isinstance(quote, str), "quote is not a str"
    assert len(quote) == 1, "quote must be a single character"

    encodable = value.encode('utf-8', errors).decode('utf-8')

    nul_index = encodable.find("\x00")
    if nul_index >= 0:
        error = UnicodeEncodeError("NUL-terminated utf-8", encodable,
                                   nul_index, nul_index + 1, "NUL not allowed")
        error_handler = codecs.lookup_error(errors)
        replacement, _ = error_handler(error)
        assert isinstance(replacement, str), "handling a UnicodeEncodeError should return a str replacement"
        encodable = encodable.replace("\x00", replacement)

    return quote + encodable.replace(quote, quote * 2) + quote

def _escape_sqlite3_value(value: str, errors='strict') -> str:
    return _escape_sqlite3(value, quote="'", errors=errors)

def _escape_sqlite3_identifier(value: str) -> str:
    return _escape_sqlite3(value, quote='"', errors='strict')

@enforce_types
def _create_tables():
    table = _escape_sqlite3_identifier(FTS_TABLE)
    # Escape as value, because fts5() expects
    # string literal column names
    column = _escape_sqlite3_value(FTS_COLUMN)
    id_table = _escape_sqlite3_identifier(FTS_ID_TABLE)
    tokenizers = _escape_sqlite3_value(FTS_TOKENIZERS)
    trigger_name = _escape_sqlite3_identifier(f"{FTS_ID_TABLE}_ad")

    with get_connection() as cursor:
        # Create a contentless-delete FTS5 table that indexes
        # but does not store the texts of snapshots
        try:
            cursor.execute(
                f"CREATE VIRTUAL TABLE {table}"
                f" USING fts5({column},"
                f" tokenize={tokenizers},"
                " content='', contentless_delete=1);"
                )
        except Exception as e:
            msg = str(e)
            if 'unrecognized option: "contentlessdelete"' in msg:
                sqlite_version = getattr(sqlite3, "sqlite_version", "Unknown")
                raise RuntimeError(
                    "SQLite full-text search requires SQLite >= 3.43.0;"
                    f" the running version is {sqlite_version}"
                ) from e
            else:
                raise
        # Create a one-to-one mapping between ArchiveBox snapshot_id
        # and FTS5 rowid, because the column type of rowid can't be
        # customized.
        cursor.execute(
            f"CREATE TABLE {id_table}("
            " rowid INTEGER PRIMARY KEY AUTOINCREMENT,"
            " snapshot_id char(32) NOT NULL UNIQUE"
            ");"
            )
        # Create a trigger to delete items from the FTS5 index when
        # the snapshot_id is deleted from the mapping, to maintain
        # consistency and make the `flush()` query simpler.
        cursor.execute(
            f"CREATE TRIGGER {trigger_name}"
            f" AFTER DELETE ON {id_table} BEGIN"
            f" DELETE FROM {table} WHERE rowid=old.rowid;"
            " END;"
            )

def _handle_query_exception(exc: Exception):
    message = str(exc)
    if message.startswith("no such table:"):
        raise RuntimeError(
            "SQLite full-text search index has not yet"
            " been created; run `archivebox update --index-only`."
        )
    else:
        raise exc

@enforce_types
def index(snapshot_id: str, texts: List[str]):
    text = ' '.join(texts)[:SQLITE_LIMIT_LENGTH]

    table = _escape_sqlite3_identifier(FTS_TABLE)
    column = _escape_sqlite3_identifier(FTS_COLUMN)
    id_table = _escape_sqlite3_identifier(FTS_ID_TABLE)

    with get_connection() as cursor:
        retries = 2
        while retries > 0:
            retries -= 1
            try:
                # If there is already an FTS index rowid to snapshot_id mapping,
                # then don't insert a new one, silently ignoring the operation.
                # {id_table}.rowid is AUTOINCREMENT, so will generate an unused
                # rowid for the index if it is an unindexed snapshot_id.
                cursor.execute(
                    f"INSERT OR IGNORE INTO {id_table}(snapshot_id) VALUES({SQLITE_BIND})",
                    [snapshot_id])
                # Fetch the FTS index rowid for the given snapshot_id
                id_res = cursor.execute(
                    f"SELECT rowid FROM {id_table} WHERE snapshot_id = {SQLITE_BIND}",
                    [snapshot_id])
                rowid = id_res.fetchone()[0]
                # (Re-)index the content
                cursor.execute(
                    "INSERT OR REPLACE INTO"
                    f" {table}(rowid, {column}) VALUES ({SQLITE_BIND}, {SQLITE_BIND})",
                    [rowid, text])
                # All statements succeeded; return
                return
            except Exception as e:
                if str(e).startswith("no such table:") and retries > 0:
                    _create_tables()
                else:
                    raise

    raise RuntimeError("Failed to create tables for SQLite FTS5 search")

@enforce_types
def search(text: str) -> List[str]:
    table = _escape_sqlite3_identifier(FTS_TABLE)
    id_table = _escape_sqlite3_identifier(FTS_ID_TABLE)

    with get_connection() as cursor:
        try:
            res = cursor.execute(
                f"SELECT snapshot_id FROM {table}"
                f" INNER JOIN {id_table}"
                f" ON {id_table}.rowid = {table}.rowid"
                f" WHERE {table} MATCH {SQLITE_BIND}",
                [text])
        except Exception as e:
            _handle_query_exception(e)

        snap_ids = [row[0] for row in res.fetchall()]
    return snap_ids

@enforce_types
def flush(snapshot_ids: Generator[str, None, None]):
    snapshot_ids = list(snapshot_ids)  # type: ignore[assignment]

    id_table = _escape_sqlite3_identifier(FTS_ID_TABLE)

    with get_connection() as cursor:
        try:
            cursor.executemany(
                f"DELETE FROM {id_table} WHERE snapshot_id={SQLITE_BIND}",
                [snapshot_ids])
        except Exception as e:
            _handle_query_exception(e)
