import asyncio

import pytest
from asgiref.testing import ApplicationCommunicator
from django.core.handlers.asgi import ASGIHandler

from archivebox.core.replay_admission import ReplayAdmission
from archivebox.tests.test_replay_phase_timing import exchange, replay_scope

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("ending", ["disconnect", "cancel", "complete"])
def test_replay_overload_leaves_health_reachable_and_releases_slots(snapshot, ending):
    scope = replay_scope(snapshot)

    async def run():
        app = ReplayAdmission(ASGIHandler(), max_active=1)
        occupied = ApplicationCommunicator(app, scope)
        assert not occupied.future.done()
        await asyncio.sleep(0)
        assert app.active == 1

        for path, host in (
            (scope["path"], scope["headers"][0][1]),
            ("/screenshot/screenshot.png", b"SNAP-0123456789ab.localhost"),
            ("/snapshot/0123456789ab/payload.txt", b"localhost"),
            ("/original/example.org/payload.txt", b"localhost"),
            ("/web/20261126/example.org/0123456789ab/payload.txt", b"localhost"),
        ):
            overloaded = await exchange(app, {**scope, "path": path, "headers": [(b"host", host)]})
            assert overloaded[0]["status"] == 503
            assert (b"cache-control", b"no-store") in overloaded[0]["headers"]
            assert overloaded[-1]["body"] == b""
        health_scope = {**scope, "path": "/health/", "raw_path": b"/health/", "query_string": b""}
        health = await exchange(app, health_scope)
        assert health[0]["status"] == 200

        if ending == "cancel":
            occupied.future.cancel()
        elif ending == "disconnect":
            await occupied.send_input({"type": "http.disconnect"})
        else:
            await occupied.send_input({"type": "http.request", "body": b"", "more_body": False})
        await occupied.wait(timeout=5)
        assert app.active == 0
        restored = await exchange(app, scope)
        assert restored[0]["status"] == 200
        assert b"".join(message.get("body", b"") for message in restored) == b"real replay bytes"
        assert app.active == 0

    asyncio.run(run())


def test_replay_slot_stays_taken_until_the_real_file_stream_closes(snapshot):
    scope = replay_scope(snapshot)

    async def run():
        app = ReplayAdmission(ASGIHandler(), max_active=1)
        incoming = asyncio.Queue()
        sending, finish = asyncio.Event(), asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                sending.set()
                await finish.wait()

        task = asyncio.create_task(app(scope, incoming.get, send))
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        try:
            await asyncio.wait_for(sending.wait(), 5)
            assert (await exchange(app, scope))[0]["status"] == 503
        finally:
            finish.set()
            await asyncio.wait_for(task, 5)
        assert (await exchange(app, scope))[0]["status"] == 200

    asyncio.run(run())
