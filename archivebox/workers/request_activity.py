"""Bounded aggregate ASGI activity, not attribution of process allocations."""

import threading

_FAMILIES = ("other", "progress", "admin", "search", "opencode", "export", "static", "snapshot_replay", "original_replay")
_STAGES = ("pending", "response_started", "body_started", "finishing")
_KEY = "archivebox.request_activity"
_LOCK = threading.Lock()
_COUNTS = {(family, stage): 0 for family in _FAMILIES for stage in _STAGES}


def request_activity():
    with _LOCK:
        return {f"{family}.{stage}": count for (family, stage), count in _COUNTS.items()}


class _Activity:
    """Only fixed labels; never retain a scope, request, task or body."""

    def __init__(self, family):
        self.family = family
        self.stage = "pending"
        self.active = True
        with _LOCK:
            _COUNTS[self.family, self.stage] += 1

    def change(self, *, family=None, stage=None):
        with _LOCK:
            if not self.active:
                return
            _COUNTS[self.family, self.stage] -= 1
            if family in _FAMILIES and self.family != "original_replay":
                self.family = family
            if stage in _STAGES:
                self.stage = stage
            _COUNTS[self.family, self.stage] += 1

    def close(self):
        with _LOCK:
            if self.active:
                _COUNTS[self.family, self.stage] -= 1
                self.active = False


def mark_request_family(request, family):
    activity = getattr(request, "scope", {}).get(_KEY)
    if isinstance(activity, _Activity):
        activity.change(family=family)


def _family(scope):
    path = scope.get("path", "")
    if path == "/progress.json":
        return "progress"
    if path.startswith("/admin/agent/"):
        return "opencode"
    if "/search-stream/" in path:
        return "search"
    if path.startswith("/admin/"):
        return "admin"
    if path.startswith("/static/"):
        return "static"
    if path.startswith("/web/"):
        return "snapshot_replay"
    return "other"


class RequestActivityObserver:
    """Observe until application cleanup finishes, including suspended streams.

    No per-request logs, registry, body inspection or extra receive calls. The
    memory observer reads fixed counters only when it already reports growth.
    Stages describe ASGI messages, not proof that bytes reached a client.
    """

    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.application(scope, receive, send)
        activity = _Activity(_family(scope))
        scope = {**scope, _KEY: activity}

        async def observed_send(message):
            kind = message["type"]
            if kind in {"http.response.start", "websocket.accept"}:
                activity.change(stage="response_started")
            elif kind in {"http.response.body", "websocket.send"}:
                if activity.stage != "body_started":
                    activity.change(stage="body_started")
            await send(message)
            if kind == "websocket.close" or (kind == "http.response.body" and not message.get("more_body", False)):
                activity.change(stage="finishing")

        try:
            return await self.application(scope, receive, observed_send)
        finally:
            activity.close()
