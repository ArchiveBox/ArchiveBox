"""Opt-in, rate-limited replay phase measurements without request identifiers."""

import asyncio
import json
import logging
import threading
from time import perf_counter

from django.conf import settings

_SCOPE_KEY = "archivebox.replay_timing"
logger = logging.getLogger(__name__)


def mark_replay_phase(request, phase):
    phases = getattr(request, "scope", {}).get(_SCOPE_KEY)
    if phases is not None:
        phases.setdefault(phase, perf_counter())


class ReplayPhaseObserver:
    """Observe the real ASGI exchange; never consume, buffer or alter messages.

    At most one slow record per minute per worker. The switch is server-side,
    not a request header, and has no effect on response headers or caching.
    Offsets begin at ASGI entry, not socket acceptance. timezone_entry marks
    the existing sync middleware boundary, after Security/Health middleware;
    replay_entry follows URL/host resolution and authorization. Body offsets
    separate first-chunk preparation from awaiting the actual ASGI send.
    """

    def __init__(self, application):
        self.application = application
        self.last_report = float("-inf")
        self.report_lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if not settings.REPLAY_PHASE_TIMING or scope["type"] != "http" or scope.get("method") not in {"GET", "HEAD"}:
            return await self.application(scope, receive, send)
        host = next((value for name, value in scope.get("headers", ()) if name == b"host"), b"")
        family = "snapshot" if scope.get("path", "").startswith("/web/") else "replay" if host.startswith(b"snap-") else None
        if family is None:
            return await self.application(scope, receive, send)
        phases = {"ingress": perf_counter()}
        scope = {**scope, _SCOPE_KEY: phases}
        status = None
        outcome = "complete"
        response_complete = False

        async def observed_send(message):
            nonlocal status, response_complete
            kind = message["type"]
            first_body = kind == "http.response.body" and bool(message.get("body")) and "body_ready" not in phases
            if kind == "http.response.start":
                status = message["status"]
                phases["headers_ready"] = perf_counter()
            if first_body:
                phases["body_ready"] = perf_counter()
            await send(message)
            if kind == "http.response.start":
                phases["headers_sent"] = perf_counter()
            if first_body:
                phases["body_sent"] = perf_counter()
            if kind == "http.response.body" and not message.get("more_body", False):
                response_complete = True

        try:
            return await self.application(scope, receive, observed_send)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            finished = perf_counter()
            boundary = phases.get("body_sent", finished)
            if scope["method"] == "HEAD":
                boundary = phases.get("headers_sent", finished)
            if outcome == "complete" and not response_complete:
                outcome = "incomplete" if "headers_sent" in phases else "no_response"
            if boundary - phases["ingress"] >= 1.0:
                with self.report_lock:
                    report = finished - self.last_report >= 60.0
                    if report:
                        self.last_report = finished
                if report:
                    logger.info(
                        "Replay phases %s",
                        json.dumps(
                            {
                                "family": family,
                                "status": status,
                                "outcome": outcome,
                                "phase_ms": {name: round((value - phases["ingress"]) * 1000, 1) for name, value in phases.items()},
                            },
                            sort_keys=True,
                        ),
                    )
