__package__ = 'abx_plugin_sqlitefts_search'

import sys
import sqlite3
from typing import Callable

from django.core.exceptions import ImproperlyConfigured

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

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
        
    def validate(self):
        if SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE == 'sqlite' and self.SQLITEFTS_SEPARATE_DATABASE and not self.SQLITEFTS_DB:
            sys.stderr.write('[X] Error: SQLITEFTS_DB must be set if SQLITEFTS_SEPARATE_DATABASE is True\n')
            SEARCH_BACKEND_CONFIG.update_in_place(SEARCH_BACKEND_ENGINE='ripgrep')
        
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
            limit_id = sqlite3.SQLITE_LIMIT_LENGTH              # type: ignore[attr-defined]
            
            if self.SQLITEFTS_SEPARATE_DATABASE:
                cursor = self.get_connection()
                return cursor.connection.getlimit(limit_id)     # type: ignore[attr-defined]
            else:
                with database.temporary_connection() as cursor:  # type: ignore[attr-defined]
                    return cursor.connection.getlimit(limit_id)
        except (AttributeError, ImproperlyConfigured):
            return self.SQLITEFTS_MAX_LENGTH

SQLITEFTS_CONFIG = SqliteftsConfig()
