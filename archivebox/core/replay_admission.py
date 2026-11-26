"""Keep queued replay I/O from exhausting the shared web worker."""

import re

from archivebox.core.routes_util import is_snapshot_subdomain

_DATED_REPLAY = re.compile(r"^/[^/]+/\d{4}(?:\d{2})?(?:\d{2})?/")
_REPLAY_PREFIXES = ("/archive/", "/original/", "/snapshot/", "/web/")


def _is_replay(scope):
    if scope["type"] != "http" or scope.get("method") not in {"GET", "HEAD"}:
        return False
    path = scope.get("path", "")
    if path in {"/health", "/health/", "/robots.txt", "/favicon.ico", "/progress.json"} or path.startswith("/static/"):
        return False
    if path.startswith(_REPLAY_PREFIXES) or _DATED_REPLAY.match(path):
        return True
    host = next((value for name, value in scope.get("headers", ()) if name == b"host"), b"")
    return is_snapshot_subdomain(host.split(b".", 1)[0].split(b":", 1)[0].decode("ascii", errors="replace").lower())


class ReplayAdmission:
    """Reject excess replay work before Django creates a request thread.

    Keep the slot through body delivery and cleanup: reads can stay blocked on
    archive storage even after headers have gone out or the client disconnects.
    Each Uvicorn worker runs on one event loop, so check and reserve before any
    await. Admin, API, and liveness requests need no replay slot.
    """

    def __init__(self, application, max_active=32):
        self.application = application
        self.max_active = max_active
        self.active = 0

    async def __call__(self, scope, receive, send):
        if not _is_replay(scope):
            return await self.application(scope, receive, send)
        if self.active >= self.max_active:
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"cache-control", b"no-store"), (b"retry-after", b"1")],
                },
            )
            await send({"type": "http.response.body", "body": b""})
            return
        self.active += 1
        try:
            return await self.application(scope, receive, send)
        finally:
            self.active -= 1
