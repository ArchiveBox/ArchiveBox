from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import close_old_connections


def _run_db_op(func, *args, **kwargs):
    close_old_connections()
    try:
        return func(*args, **kwargs)
    finally:
        close_old_connections()


async def run_db_op(func, *args, **kwargs):
    return await sync_to_async(_run_db_op, thread_sensitive=True)(func, *args, **kwargs)
