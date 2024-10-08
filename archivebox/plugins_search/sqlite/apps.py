__package__ = 'archivebox.plugins_search.sqlite'

import sys
import codecs
import sqlite3
from typing import List, Iterable, Callable

from django.core.exceptions import ImproperlyConfigured

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field, model_validator

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_hook import BaseHook
from abx.archivebox.base_searchbackend import BaseSearchBackend

# Depends on Other Plugins:
from archivebox.config.common import SEARCH_BACKEND_CONFIG



###################### Config ##########################

class SqliteftsConfig(BaseConfigSet):
    SQLITEFTS_SEPARATE_DATABASE: bool   = Field(default=True, alias='FTS_SEPARATE_DATABASE')
    SQLITEFTS_TOKENIZERS: str           = Field(default='porter unicode61 remove_diacritics 2', alias='FTS_TOKENIZERS')
    SQLITEFTS_MAX_LENGTH: int           = Field(default=int(1e9), alias='FTS_SQLITE_MAX_LENGTH')
    
    # Not really meant to be user-modified, just here as constants
    SQLITEFTS_DB: str                   = Field(default='search.sqlite3')
    SQLITEFTS_TABLE: str                = Field(default='snapshot_fts')
    SQLITEFTS_ID_TABLE: str             = Field(default='snapshot_id_fts')
    SQLITEFTS_COLUMN: str               = Field(default='texts')
    
    @model_validator(mode='after')
    def validate_fts_separate_database(self):
        if SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE == 'sqlite' and self.SQLITEFTS_SEPARATE_DATABASE and not self.SQLITEFTS_DB:
            sys.stderr.write('[X] Error: SQLITEFTS_DB must be set if SQLITEFTS_SEPARATE_DATABASE is True\n')
            SEARCH_BACKEND_CONFIG.update_in_place(SEARCH_BACKEND_ENGINE='ripgrep')
        return self
    
    @property
    def get_connection(self) -> Callable[[], sqlite3.Connection]:
        # Make get_connection callable, because `django.db.connection.cursor()`
        # has to be called to get a context manager, but sqlite3.Connection
        # is a context manager without being called.
        if self.SQLITEFTS_SEPARATE_DATABASE:
            return lambda: sqlite3.connect(self.SQLITEFTS_DB)
        else:
            from django.db import connection as database
            return database.cursor
        
    @property
    def SQLITE_BIND(self) -> str:
        if self.SQLITEFTS_SEPARATE_DATABASE:
            return "?"
        else:
            return "%s"
        
    @property
    def SQLITE_LIMIT_LENGTH(self) -> int:
        from django.db import connection as database
        
        # Only Python >= 3.11 supports sqlite3.Connection.getlimit(),
        # so fall back to the default if the API to get the real value isn't present
        try:
            limit_id = sqlite3.SQLITE_LIMIT_LENGTH
            
            if self.SQLITEFTS_SEPARATE_DATABASE:
                cursor = self.get_connection()
                return cursor.connection.getlimit(limit_id)
            else:
                with database.temporary_connection() as cursor:  # type: ignore[attr-defined]
                    return cursor.connection.getlimit(limit_id)
        except (AttributeError, ImproperlyConfigured):
            return self.SQLITEFTS_MAX_LENGTH

SQLITEFTS_CONFIG = SqliteftsConfig()



def _escape_sqlite3(value: str, *, quote: str, errors='strict') -> str:
    assert isinstance(quote, str), "quote is not a str"
    assert len(quote) == 1, "quote must be a single character"

    encodable = value.encode('utf-8', errors).decode('utf-8')

    nul_index = encodable.find("\x00")
    if nul_index >= 0:
        error = UnicodeEncodeError("NUL-terminated utf-8", encodable, nul_index, nul_index + 1, "NUL not allowed")
        error_handler = codecs.lookup_error(errors)
        replacement, _ = error_handler(error)
        assert isinstance(replacement, str), "handling a UnicodeEncodeError should return a str replacement"
        encodable = encodable.replace("\x00", replacement)

    return quote + encodable.replace(quote, quote * 2) + quote

def _escape_sqlite3_value(value: str, errors='strict') -> str:
    return _escape_sqlite3(value, quote="'", errors=errors)

def _escape_sqlite3_identifier(value: str) -> str:
    return _escape_sqlite3(value, quote='"', errors='strict')

def _create_tables():
    table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_TABLE)
    # Escape as value, because fts5() expects
    # string literal column names
    column = _escape_sqlite3_value(SQLITEFTS_CONFIG.SQLITEFTS_COLUMN)
    id_table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_ID_TABLE)
    tokenizers = _escape_sqlite3_value(SQLITEFTS_CONFIG.SQLITEFTS_TOKENIZERS)
    trigger_name = _escape_sqlite3_identifier(f"{SQLITEFTS_CONFIG.SQLITEFTS_ID_TABLE}_ad")

    with SQLITEFTS_CONFIG.get_connection() as cursor:
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




class SqliteftsSearchBackend(BaseSearchBackend):
    name: str = 'sqlite'
    docs_url: str = 'https://www.sqlite.org/fts5.html'
    
    @staticmethod
    def index(snapshot_id: str, texts: List[str]):
        text = ' '.join(texts)[:SQLITEFTS_CONFIG.SQLITE_LIMIT_LENGTH]

        table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_TABLE)
        column = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_COLUMN)
        id_table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_ID_TABLE)

        with SQLITEFTS_CONFIG.get_connection() as cursor:
            retries = 2
            while retries > 0:
                retries -= 1
                try:
                    # If there is already an FTS index rowid to snapshot_id mapping,
                    # then don't insert a new one, silently ignoring the operation.
                    # {id_table}.rowid is AUTOINCREMENT, so will generate an unused
                    # rowid for the index if it is an unindexed snapshot_id.
                    cursor.execute(
                        f"INSERT OR IGNORE INTO {id_table}(snapshot_id) VALUES({SQLITEFTS_CONFIG.SQLITE_BIND})",
                        [snapshot_id])
                    # Fetch the FTS index rowid for the given snapshot_id
                    id_res = cursor.execute(
                        f"SELECT rowid FROM {id_table} WHERE snapshot_id = {SQLITEFTS_CONFIG.SQLITE_BIND}",
                        [snapshot_id])
                    rowid = id_res.fetchone()[0]
                    # (Re-)index the content
                    cursor.execute(
                        "INSERT OR REPLACE INTO"
                        f" {table}(rowid, {column}) VALUES ({SQLITEFTS_CONFIG.SQLITE_BIND}, {SQLITEFTS_CONFIG.SQLITE_BIND})",
                        [rowid, text])
                    # All statements succeeded; return
                    return
                except Exception as e:
                    if str(e).startswith("no such table:") and retries > 0:
                        _create_tables()
                    else:
                        raise

        raise RuntimeError("Failed to create tables for SQLite FTS5 search")

    @staticmethod
    def search(text: str) -> List[str]:
        table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_TABLE)
        id_table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_ID_TABLE)

        with SQLITEFTS_CONFIG.get_connection() as cursor:
            try:
                res = cursor.execute(
                    f"SELECT snapshot_id FROM {table}"
                    f" INNER JOIN {id_table}"
                    f" ON {id_table}.rowid = {table}.rowid"
                    f" WHERE {table} MATCH {SQLITEFTS_CONFIG.SQLITE_BIND}",
                    [text])
            except Exception as e:
                _handle_query_exception(e)

            snap_ids = [row[0] for row in res.fetchall()]
        return snap_ids

    @staticmethod
    def flush(snapshot_ids: Iterable[str]):
        snapshot_ids = list(snapshot_ids)  # type: ignore[assignment]

        id_table = _escape_sqlite3_identifier(SQLITEFTS_CONFIG.SQLITEFTS_ID_TABLE)

        with SQLITEFTS_CONFIG.get_connection() as cursor:
            try:
                cursor.executemany(
                    f"DELETE FROM {id_table} WHERE snapshot_id={SQLITEFTS_CONFIG.SQLITE_BIND}",
                    [snapshot_ids])
            except Exception as e:
                _handle_query_exception(e)
    
SQLITEFTS_SEARCH_BACKEND = SqliteftsSearchBackend()



class SqliteftsSearchPlugin(BasePlugin):
    app_label: str ='sqlitefts'
    verbose_name: str = 'SQLite FTS5 Search'

    hooks: List[InstanceOf[BaseHook]] = [
        SQLITEFTS_CONFIG,
        SQLITEFTS_SEARCH_BACKEND,
    ]



PLUGIN = SqliteftsSearchPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
