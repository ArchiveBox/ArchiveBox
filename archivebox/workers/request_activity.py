"""Bounded aggregate ASGI activity, not attribution of process allocations."""

import re
import threading
from weakref import ref

_FAMILIES = ("other", "progress", "admin", "search", "opencode", "export", "static", "snapshot_replay", "original_replay")
_STAGES = ("pending", "response_started", "body_started", "finishing")
_REQUEST_SAMPLE_LIMIT = 64
_REQUESTS = {}
_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
_VIEW_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_KEY = "archivebox.request_activity"
_LOCK = threading.Lock()
_COUNTS = {(family, stage): 0 for family in _FAMILIES for stage in _STAGES}


def request_activity():
    with _LOCK:
        return {f"{family}.{stage}": count for (family, stage), count in _COUNTS.items()}


def bind_request_activity(request):
    """Track a weak reference only; don't keep Django requests alive."""
    activity = request.scope.get(_KEY)
    if not isinstance(activity, _Activity):
        return
    with _LOCK:
        if not activity.active or activity.family in {"static", "progress"}:
            return
        if len(_REQUESTS) >= _REQUEST_SAMPLE_LIMIT:
            # Keep older pre-header requests when a burst arrives. A younger
            # request may replace one that has already started its response.
            replace = next((entry for entry in reversed(_REQUESTS) if entry.stage != "pending"), None)
            if replace is None:
                return
            del _REQUESTS[replace]
        _REQUESTS[activity] = ref(request)


def _known_actor(attributes):
    for key in ("_cached_user", "_acached_user", "user"):
        user = attributes.get(key)
        if user is None:
            continue
        # Reading through SimpleLazyObject would trigger session auth. Inspect
        # only concrete in-memory values; no lazy attributes, sessions or tokens.
        try:
            value = object.__getattribute__(user, "__dict__").get("id")
        except AttributeError:
            continue
        if type(value) is int and 0 < value < 2**63:
            return value
    return None


def sampled_requests():
    """Return bounded scalar route information for existing RSS warnings only."""
    with _LOCK:
        entries = [(weak_request, activity.family, activity.stage) for activity, weak_request in _REQUESTS.items()]
    result = []
    for weak_request, family, stage in entries:
        request = weak_request()
        if request is None:
            continue
        attrs = vars(request)
        view = attrs.get("resolver_match")
        name = view.view_name if view is not None else ""
        method = attrs.get("method")
        result.append(
            {
                "route": name if isinstance(name, str) and _VIEW_NAME.fullmatch(name) else family,
                "method": method if method in _METHODS else "other",
                "stage": stage,
                "actor": _known_actor(attrs),
            },
        )
    return result


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
                _REQUESTS.pop(self, None)


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

    No per-request logs, body inspection or extra receive calls. The memory
    observer reads counters and a capped weak sample only when reporting growth.
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
