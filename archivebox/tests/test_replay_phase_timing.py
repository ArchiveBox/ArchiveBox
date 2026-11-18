"""Real Django ASGI exchanges with controlled transport and filesystem waits."""

import asyncio
import json
import logging
import threading
import time
from urllib.parse import urlsplit

import pytest
from asgiref.testing import ApplicationCommunicator
from django.test import override_settings

from django.core.handlers.asgi import ASGIHandler
from archivebox.core.replay_timing import ReplayPhaseObserver
from archivebox.core.routes_util import build_snapshot_url
from archivebox.core.views import _build_snapshot_replay_response

pytestmark = pytest.mark.django_db(transaction=True)


def replay_scope(snapshot):
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    path = snapshot.output_dir / "payload.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("real replay bytes")
    route = urlsplit(build_snapshot_url(str(snapshot.pk), "payload.txt"))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": route.path,
        "raw_path": route.path.encode(),
        "query_string": b"raw=1&private-marker=never-log",
        "headers": [(b"host", route.netloc.encode())],
        "server": ("127.0.0.1", 443),
        "client": ("127.0.0.1", 12345),
    }


async def exchange(observer, scope, body_delay=0):
    client = ApplicationCommunicator(observer, scope)
    assert not client.future.done()
    if body_delay:
        await asyncio.sleep(body_delay)
    await client.send_input({"type": "http.request", "body": b"", "more_body": False})
    messages = []
    while True:
        message = await client.receive_output(timeout=5)
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            break
    await client.wait(timeout=5)
    return messages


def records(caplog):
    return [json.loads(r.getMessage().removeprefix("Replay phases ")) for r in caplog.records if r.name == "archivebox.core.replay_timing"]


def test_real_asgi_receive_wait_and_disabled_response_equivalence(snapshot, caplog):
    scope = replay_scope(snapshot)
    observer = ReplayPhaseObserver(ASGIHandler())
    caplog.set_level(logging.INFO, logger="archivebox.core.replay_timing")
    with override_settings(REPLAY_PHASE_TIMING=False):
        plain = asyncio.run(exchange(observer, scope, body_delay=1.05))
    assert not records(caplog)
    with override_settings(REPLAY_PHASE_TIMING=True):
        measured = asyncio.run(exchange(observer, scope, body_delay=1.05))
    assert plain[0]["status"] == measured[0]["status"] == 200
    # Existing view timing varies naturally, not response semantics/caching.
    headers = lambda messages: {k: v for k, v in messages[0]["headers"] if k.lower() != b"server-timing"}
    assert headers(plain) == headers(measured)
    assert b"".join(m.get("body", b"") for m in plain) == b"".join(m.get("body", b"") for m in measured) == b"real replay bytes"
    record = records(caplog)[0]
    assert record["phase_ms"]["timezone_entry"] >= 1000
    assert record["phase_ms"]["replay_built"] >= record["phase_ms"]["replay_entry"]
    assert record["phase_ms"]["body_sent"] >= record["phase_ms"]["headers_sent"]
    assert "never-log" not in str(record) and str(snapshot.pk) not in str(record)
    with override_settings(REPLAY_PHASE_TIMING=True):
        asyncio.run(exchange(observer, scope, body_delay=1.05))
    assert len(records(caplog)) == 1  # One slow record/minute, not per request.


def test_real_replay_view_wait_attribution(snapshot, caplog):
    scope = replay_scope(snapshot)
    observer = ReplayPhaseObserver(ASGIHandler())
    caplog.set_level(logging.INFO, logger="archivebox.core.replay_timing")

    def delay_real_view(frame, event, arg):
        if event == "call" and frame.f_code is _build_snapshot_replay_response.__code__:
            time.sleep(1.05)

    previous = threading.getprofile()
    threading.setprofile(delay_real_view)
    try:
        with override_settings(REPLAY_PHASE_TIMING=True):
            messages = asyncio.run(exchange(observer, scope))
    finally:
        threading.setprofile(previous)
    assert messages[0]["status"] == 200
    phases = records(caplog)[0]["phase_ms"]
    assert phases["replay_built"] - phases["replay_entry"] >= 1000
    assert phases["replay_entry"] >= phases["timezone_entry"]


def test_real_asgi_disconnect_and_cancel_without_headers(snapshot, caplog):
    scope = replay_scope(snapshot)
    caplog.set_level(logging.INFO, logger="archivebox.core.replay_timing")

    async def disconnect(cancel):
        client = ApplicationCommunicator(ReplayPhaseObserver(ASGIHandler()), scope)
        assert not client.future.done()
        await asyncio.sleep(1.05)
        if cancel:
            client.future.cancel()
        else:
            await client.send_input({"type": "http.disconnect"})
        await client.wait(timeout=5)
        assert client.output_queue.empty()

    with override_settings(REPLAY_PHASE_TIMING=True):
        asyncio.run(disconnect(False))
        asyncio.run(disconnect(True))
    assert [r["outcome"] for r in records(caplog)] == ["no_response", "cancelled"]


def test_real_asgi_error_propagates_without_logging_payload(snapshot, caplog):
    scope = replay_scope(snapshot)
    scope["headers"].append((b"invalid-asgi-private-marker", None))
    caplog.set_level(logging.INFO, logger="archivebox.core.replay_timing")
    with override_settings(REPLAY_PHASE_TIMING=True), pytest.raises(AttributeError):
        asyncio.run(exchange(ReplayPhaseObserver(ASGIHandler()), scope, body_delay=1.05))
    record = records(caplog)[0]
    assert record["outcome"] == "error"
    assert record["status"] is None
    assert "invalid-asgi-private-marker" not in str(record)


def test_disabled_observer_takes_no_phase_clocks(snapshot):
    import sys

    from archivebox.core import replay_timing

    scope = replay_scope(snapshot)
    observer = ReplayPhaseObserver(ASGIHandler())
    clocks = []

    def observe_clock_calls(frame, event, arg):
        if event == "c_call" and arg is replay_timing.perf_counter and frame.f_globals.get("__name__") == replay_timing.__name__:
            clocks.append(frame.f_code.co_name)

    previous = sys.getprofile()
    try:
        sys.setprofile(observe_clock_calls)
        with override_settings(REPLAY_PHASE_TIMING=False):
            messages = asyncio.run(exchange(observer, scope))
    finally:
        sys.setprofile(previous)
    assert messages[0]["status"] == 200
    assert not clocks
