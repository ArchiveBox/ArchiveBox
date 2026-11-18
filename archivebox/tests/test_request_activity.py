"""Aggregate lifetimes through real Django replay and ASGI transport waits."""

import asyncio
import json
import time
import threading

import pytest
from asgiref.testing import ApplicationCommunicator
from django.core.handlers.asgi import ASGIHandler

from archivebox.tests.test_replay_phase_timing import exchange, replay_scope
from archivebox.workers.request_activity import RequestActivityObserver, request_activity

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("ending", ["disconnect", "cancel", "complete", "error"])
def test_real_request_lifetime(snapshot, ending, caplog):
    scope = replay_scope(snapshot)
    if ending == "error":
        scope["headers"].append((b"invalid-private-marker", None))

    async def run():
        client = ApplicationCommunicator(RequestActivityObserver(ASGIHandler()), scope)
        assert not client.future.done()
        # The real handler waits for the first HTTP body message.
        await asyncio.sleep(0)
        assert sum(request_activity().values()) == 1
        assert sum(v for k, v in request_activity().items() if k.endswith(".pending")) == 1
        if ending == "cancel":
            client.future.cancel()
        elif ending == "disconnect":
            await client.send_input({"type": "http.disconnect"})
        else:
            await client.send_input({"type": "http.request", "body": b"", "more_body": False})
        if ending == "error":
            with pytest.raises(AttributeError):
                await client.wait(timeout=5)
        else:
            await client.wait(timeout=5)
        assert sum(request_activity().values()) == 0

    asyncio.run(run())
    assert "pending_asgi" not in caplog.text  # No new per-request logging.
    assert "private-marker" not in json.dumps(request_activity())


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_real_response_bytes_and_headers_unchanged(snapshot, method):
    scope = replay_scope(snapshot)
    scope["method"] = method
    plain = asyncio.run(exchange(ASGIHandler(), scope))
    observed = asyncio.run(exchange(RequestActivityObserver(ASGIHandler()), scope))
    # Existing replay Server-Timing measures separate executions.
    for messages in (plain, observed):
        messages[0]["headers"] = [(k, v) for k, v in messages[0]["headers"] if k.lower() != b"server-timing"]
    assert plain == observed
    assert sum(request_activity().values()) == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_real_stream_send_backpressure_and_cleanup(snapshot, cancel):
    scope = replay_scope(snapshot)

    async def run():
        incoming = asyncio.Queue()
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []

        async def send(message):
            if message["type"] == "http.response.body":
                entered.set()
                await release.wait()
            messages.append(message)

        task = asyncio.create_task(RequestActivityObserver(ASGIHandler())(scope, incoming.get, send))
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        try:
            await asyncio.wait_for(entered.wait(), 5)
            counters = request_activity()
            assert counters["snapshot_replay.body_started"] == 1
            assert sum(counters.values()) == 1
        finally:
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            else:
                release.set()
                await asyncio.wait_for(task, 5)
        assert sum(request_activity().values()) == 0
        if not cancel:
            assert b"".join(m.get("body", b"") for m in messages) == b"real replay bytes"

    closed = []

    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "close" and frame.f_globals.get("__name__") == "django.http.response":
            closed.append(request_activity())

    previous = threading.getprofile()
    threading.setprofile(profile)
    try:
        asyncio.run(run())
    finally:
        threading.setprofile(previous)
    if not cancel:
        assert closed and any(row["snapshot_replay.finishing"] == 1 for row in closed)


def test_real_health_exchange_overhead(caplog):
    scope = {"type": "http", "method": "GET", "path": "/health/", "headers": [], "query_string": b""}

    async def measure(app):
        start = time.perf_counter()
        for _ in range(100):
            result = await exchange(app, scope)
            assert result[0]["status"] == 200
        return time.perf_counter() - start

    plain = asyncio.run(measure(ASGIHandler()))
    observed = asyncio.run(measure(RequestActivityObserver(ASGIHandler())))
    print(f"Real health ASGI 100 exchanges: plain={plain:.6f}s observed={observed:.6f}s")
    assert sum(request_activity().values()) == 0
    assert "pending_asgi" not in caplog.text


def test_real_progress_exact_route_activity(admin_client):
    async def run():
        incoming = asyncio.Queue()
        observations = []
        messages = []

        async def send(message):
            observations.append(request_activity())
            messages.append(message)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/progress.json",
            "query_string": b"",
            "headers": [
                (b"host", b"admin.archivebox.localhost"),
                (b"cookie", admin_client.cookies.output(header="", sep=";").strip().encode()),
            ],
        }
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        await RequestActivityObserver(ASGIHandler())(scope, incoming.get, send)
        assert messages[0]["status"] == 200
        assert all(sum(row.values()) == 1 for row in observations)
        assert observations[0]["progress.response_started"] == 1
        assert observations[-1]["progress.body_started"] == 1
        assert sum(request_activity().values()) == 0

    asyncio.run(run())
