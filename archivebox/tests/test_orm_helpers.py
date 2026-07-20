from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import asyncio

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import connections


def archivebox_db_path(path: str | Path = ".") -> Path:
    path = Path(path)
    return path if path.name == "index.sqlite3" else path / "index.sqlite3"


def test_archivebox_db_path_accepts_collection_or_database_path(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite3"
    assert archivebox_db_path(tmp_path) == database_path
    assert archivebox_db_path(database_path) == database_path


def _reset_thread_sensitive_default_connection() -> None:
    """Discard the default connection owned by asgiref's thread-sensitive worker."""

    def reset_connection() -> None:
        connections["default"].close()
        del connections._connections.default

    asyncio.run(sync_to_async(reset_connection, thread_sensitive=True)())


def _thread_sensitive_database_path() -> str:
    def database_path() -> str:
        with connections["default"].cursor() as cursor:
            return str(cursor.execute("PRAGMA database_list").fetchone()[2])

    return asyncio.run(sync_to_async(database_path, thread_sensitive=True)())


@pytest.mark.django_db(transaction=True)
def test_use_archivebox_db_restores_thread_sensitive_connection(tmp_path: Path) -> None:
    original_database_path = _thread_sensitive_database_path()

    with use_archivebox_db(tmp_path):
        assert _thread_sensitive_database_path() == str(tmp_path / "index.sqlite3")

    assert _thread_sensitive_database_path() == original_database_path


@contextmanager
def use_archivebox_db(path: str | Path = ".") -> Iterator[None]:
    _reset_thread_sensitive_default_connection()
    connection = connections["default"]
    original_name = connection.settings_dict["NAME"]
    original_database_name = connections.databases["default"]["NAME"]
    original_setting_name = settings.DATABASES["default"]["NAME"]
    original_connection = connections._connections.default
    db_path = str(archivebox_db_path(path))

    connection.close()
    connection.settings_dict["NAME"] = db_path
    connections.databases["default"]["NAME"] = db_path
    settings.DATABASES["default"]["NAME"] = db_path
    del connections._connections.default
    try:
        yield
    finally:
        _reset_thread_sensitive_default_connection()
        connections["default"].close()
        connections.databases["default"]["NAME"] = original_database_name
        settings.DATABASES["default"]["NAME"] = original_setting_name
        del connections._connections.default
        original_connection.settings_dict["NAME"] = original_name
        connections._connections.default = original_connection
