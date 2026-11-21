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


def test_real_admin_activity_samples_resolved_route_and_account_without_request_values(snapshot, admin_user, client, initialized_archive):
    from django.conf import settings
    from django.urls import reverse

    from archivebox.core.asgi import application
    from archivebox.tests.conftest import ADMIN_TEST_HOST
    from archivebox.workers.request_activity import sampled_requests

    client.force_login(admin_user)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].output(header="").strip()
    private_path = reverse("admin:core_snapshot_change", args=[snapshot.pk])
    scope = {
        **replay_scope(snapshot),
        "path": private_path,
        "raw_path": private_path.encode(),
        "query_string": b"api_key=sensitive-test-query",
        "headers": [(b"host", ADMIN_TEST_HOST.encode()), (b"cookie", cookie.encode()), (b"authorization", b"Bearer sensitive-test-header")],
    }

    async def run():
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})

        async def send(message):
            if message["type"] == "http.response.start":
                assert message["status"] == 200
                rows = sampled_requests()
                assert rows == [
                    {"route": "admin:core_snapshot_change", "method": "GET", "stage": "response_started", "actor": admin_user.pk},
                ]
                serialized = json.dumps(rows)
                assert str(snapshot.pk) not in serialized
                assert "sensitive-test" not in serialized
                assert cookie not in serialized

        await application(scope, incoming.get, send)
        assert sampled_requests() == []

    asyncio.run(run())


def test_bounded_request_sample_keeps_oldest_pending_and_releases_on_close(snapshot):
    from io import BytesIO
    from weakref import ref

    from archivebox.workers.request_activity import _Activity, _KEY, bind_request_activity, sampled_requests

    scope = replay_scope(snapshot)
    handler = ASGIHandler()
    active = []
    requests = []

    def enter(family, method="GET"):
        activity = _Activity(family)
        active.append(activity)
        request, error = handler.create_request({**scope, _KEY: activity, "method": method}, BytesIO())
        assert error is None
        requests.append(request)
        bind_request_activity(request)
        return activity

    try:
        enter("export", "POST")
        for _ in range(62):
            enter("admin")
        finishing = enter("snapshot_replay")
        finishing.change(stage="response_started")
        enter("search")
        for _ in range(4):
            enter("opencode")

        rows = sampled_requests()
        assert len(rows) == 64
        assert rows[0] == {"route": "export", "method": "POST", "stage": "pending", "actor": None}
        assert rows[-1] == {"route": "search", "method": "GET", "stage": "pending", "actor": None}
        assert {row["route"] for row in rows} == {"export", "admin", "search"}
        assert sum(request_activity().values()) == 69

        # This is a weak sample, even while an activity is still pending.
        oldest_request = ref(requests.pop(0))
        assert oldest_request() is None
        assert all(row["route"] != "export" for row in sampled_requests())
    finally:
        for activity in active:
            activity.close()
    assert not sampled_requests()
    assert sum(request_activity().values()) == 0
