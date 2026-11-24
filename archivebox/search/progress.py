"""Activity sampled by the existing HTTP stream. Only the search worker writes it."""

import time
from contextlib import contextmanager


class SearchProgress:
    def __init__(self):
        self.activity = ("planning", "", time.monotonic(), None, None)
        self.checked = 0
        self.total = None

    @contextmanager
    def phase(self, name, provider="", *, timeout=None, idle_since=None):
        previous = self.activity
        self.activity = (name, provider, time.monotonic(), timeout, idle_since)
        try:
            yield
        finally:
            self.activity = previous

    def reading(self, iterable, name, provider="", *, timeout=None, per_read=False, idle_since=None):
        # A generator can spend most of its lifetime suspended while Django or
        # Python checks a row. Attribute only the wait for its next output to it.
        iterator = iter(iterable)
        activity = (name, provider, time.monotonic(), timeout, idle_since)
        try:
            while True:
                if per_read:
                    activity = (name, provider, time.monotonic(), timeout, idle_since)
                previous = self.activity
                self.activity = activity
                try:
                    item = next(iterator)
                except StopIteration:
                    return
                finally:
                    self.activity = previous
                yield item
        finally:
            if close := getattr(iterator, "close", None):
                close()

    def sql(self, execute, sql, params, many, context):
        with self.phase("sql"):
            return execute(sql, params, many, context)

    def sample(self):
        phase, provider, started, limit, idle_since = self.activity
        now = time.monotonic()
        data = {"phase": phase, "ms": round((now - started) * 1000), "checked": self.checked}
        if provider:
            data["provider"] = provider.removeprefix("search_backend_")
        if self.total is not None:
            data["total"] = self.total
        if limit is not None:
            data["limit"] = limit
        since = None
        if idle_since:
            since, seconds = idle_since()
            data.update(idle=round((now - since) * 1000), stall=seconds)
        # Compare actual transitions, never elapsed seconds, to decide whether to send.
        return (phase, provider, started, since, data["checked"], data.get("total")), data
