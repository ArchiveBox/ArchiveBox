"""
ASGI config for archivebox project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

from django.core.asgi import get_asgi_application

from archivebox.config.django import setup_django

setup_django(check_db=True)


def _patch_thread_sensitive_context_shutdown() -> None:
    """Stop ``ThreadSensitiveContext.__aexit__`` from blocking the daphne loop.

    Django 6.0's ASGIHandler wraps every request in ``async with
    ThreadSensitiveContext():`` (django/core/handlers/asgi.py:169). On exit
    asgiref calls ``executor.shutdown()`` with the default ``wait=True``
    (asgiref/sync.py:148), which is a *synchronous* ``Thread.join()`` inside
    an async function — so it blocks the daphne event loop until the
    executor's worker thread exits.

    That's normally fine because the request handler has already awaited
    every ``sync_to_async`` it submitted, so the worker is idle and dies as
    soon as the shutdown sentinel reaches it. The blocking turns into a
    problem when a client disconnects mid-request:

    * ``SyncToAsync.__call__`` shields the executor work with
      ``await asyncio.shield(exec_coro)`` (asgiref/sync.py:506) so that the
      sync DB call doesn't get torn down halfway through.
    * On cancellation it calls ``exec_coro.cancel()`` (line 522) which only
      flips the asyncio ``Future`` to cancelled — the underlying thread
      keeps running the SQL query.
    * Control unwinds to ``__aexit__`` while the orphaned thread is still
      mid-query. ``shutdown(wait=True)`` then blocks the event loop until
      that orphan finishes.

    Under heavy SQLite contention (the load-test scenario that surfaced
    this on cabbage) those orphan threads can take 30 seconds each waiting
    for write locks, and the daphne loop is single-threaded — so every
    such orphan stalls every other in-flight request, healthchecks time
    out, and the container goes ``unhealthy``.

    Switching to ``shutdown(wait=False)`` queues the sentinel and returns
    immediately; the worker thread still exits cleanly once its current
    task finishes, and asgiref's ``WeakKeyDictionary`` releases the
    executor as soon as the request's context is GC'd. No per-request
    teardown guarantee is lost — there was no caller relying on it.
    """
    from asgiref import sync as _asgiref_sync

    original_aexit = _asgiref_sync.ThreadSensitiveContext.__aexit__

    async def __aexit__(self, exc, value, tb):  # type: ignore[no-redef]
        if not self.token:
            return
        executor = _asgiref_sync.SyncToAsync.context_to_thread_executor.pop(self, None)
        if executor is not None:
            executor.shutdown(wait=False)
        _asgiref_sync.SyncToAsync.thread_sensitive_context.reset(self.token)

    # Idempotent: only patch once even if asgi.py is reloaded.
    if getattr(original_aexit, "_archivebox_patched", False):
        return
    __aexit__._archivebox_patched = True  # type: ignore[attr-defined]
    _asgiref_sync.ThreadSensitiveContext.__aexit__ = __aexit__


_patch_thread_sensitive_context_shutdown()

# Standard Django ASGI application (no websockets/channels needed)
application = get_asgi_application()
