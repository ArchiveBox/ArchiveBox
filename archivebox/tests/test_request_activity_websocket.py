"""Real integrated ASGI websocket dispatch retains bounded lifetime counters."""

import asyncio

import pytest

from archivebox.workers.request_activity import request_activity

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("route", ["/private-marker-not-a-route", "/admin/agent/opencode/server/private-fixture/session"])
@pytest.mark.parametrize("cancel", [False, True])
def test_integrated_websocket_lifetime(initialized_archive, route, cancel):
    from archivebox.core.asgi import application
    import uvicorn

    config = uvicorn.Config(application, interface="auto", lifespan="off")
    config.load()
    assert config.interface == "asgi3"

    async def run():
        incoming = asyncio.Queue()
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []

        async def send(message):
            assert message == {"type": "websocket.close", "code": 1008}
            entered.set()
            await release.wait()
            messages.append(message)

        scope = {
            "type": "websocket",
            "path": route,
            "query_string": b"private-marker",
            "headers": [(b"host", b"admin.archivebox.localhost")],
            "scheme": "ws",
            "server": ("127.0.0.1", 80),
            "client": ("127.0.0.1", 12345),
        }
        task = asyncio.create_task(application(scope, incoming.get, send))
        await incoming.put({"type": "websocket.connect"})
        try:
            await asyncio.wait_for(entered.wait(), 5)
            family = "opencode" if route.startswith("/admin/agent/") else "other"
            assert request_activity()[family + ".pending"] == 1
            assert sum(request_activity().values()) == 1
        finally:
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            else:
                release.set()
                await asyncio.wait_for(task, 5)
        assert sum(request_activity().values()) == 0
        assert messages == ([] if cancel else [{"type": "websocket.close", "code": 1008}])

    asyncio.run(run())
