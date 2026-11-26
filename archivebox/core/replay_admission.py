"""Keep replay bursts from exhausting the shared web worker."""

import logging
import os
import random


class ReplayAdmission:
    """Reject excess HTTP work before Django creates a request thread.

    Keep the slot through body delivery and cleanup: reads can stay blocked on
    archive storage even after headers have gone out or the client disconnects.
    Each Uvicorn worker runs on one event loop, so check and reserve before any
    await. Admin and health requests bypass early shedding, not the hard limit.
    """

    def __init__(self, application, max_active=None):
        self.application = application
        self.active = 0
        if max_active is None:
            from archivebox.workers.resource_admission import resource_admission

            workers = max(1, int(os.environ.get("WEB_CONCURRENCY", "1")))
            max_active = resource_admission.http_limit(workers, self.active)
            logging.getLogger("uvicorn.error").info("HTTP request limit: total=%d workers=%d", max_active, workers)
        self.max_active = max_active

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.application(scope, receive, send)
        priority = scope["path"].startswith("/admin/") or (scope["path"] == "/health/" and scope["method"] in {"GET", "HEAD"})
        soft_limit = self.max_active // 2
        # Slow storage must not create hundreds of request threads. Shed public
        # work gradually above half the resource budget; admin/login and health
        # only face the hard ceiling. This gives priority without reserving a
        # fixed share or adding session queries. Django still authenticates.
        overloaded = self.active >= self.max_active or (
            not priority and self.active > soft_limit and random.random() < (self.active - soft_limit) / (self.max_active - soft_limit)
        )
        if overloaded:
            body = b"Server is under high load. Please try again shortly.\n"
            headers = [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"retry-after", str(random.randint(1, 3)).encode("ascii")),
            ]
            # Do not read rejected uploads or retain their keepalive socket.
            # Closing HTTP/1 also prevents queued pipelined work from entering.
            if scope.get("http_version", "1.1").startswith("1."):
                headers.append((b"connection", b"close"))
            await send({"type": "http.response.start", "status": 429, "headers": headers})
            await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})
            return
        self.active += 1
        try:
            return await self.application(scope, receive, send)
        finally:
            # Disconnecting cannot free a slot while a file read still owns a
            # thread: wait for the application's complete request cleanup.
            self.active -= 1
