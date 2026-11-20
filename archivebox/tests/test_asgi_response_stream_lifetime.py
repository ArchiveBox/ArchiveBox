"""The ASGI request lifetime owns upstream cleanup even before the first body part."""

import asyncio
import socket

import pytest
from django.http import StreamingHttpResponse
from django.test import override_settings
from django.urls import path


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("ending", ["preheader-disconnect", "header-send-failure"])
def test_asgi_closes_owned_stream_before_body(initialized_archive, ending):
    from archivebox.core.asgi import ArchiveBoxASGIHandler

    events = []
    registered = asyncio.Event()
    upstream, peer = socket.socketpair()
    peer.setblocking(False)

    async def release():
        await asyncio.sleep(0)
        upstream.close()
        events.append("released")

    async def body():
        events.append("body-read")
        yield b"ordinary upstream bytes"

    async def view(request):
        request.scope["archivebox.own_response_stream"](release)
        registered.set()
        if ending == "preheader-disconnect":
            # A real client may close while the view still awaits upstream
            # headers, before Django ever gets a response object to close.
            await asyncio.Event().wait()
        return StreamingHttpResponse(body())

    async def run():
        messages = asyncio.Queue()
        await messages.put({"type": "http.request", "body": b""})

        async def broken_send(message):
            assert message["type"] == "http.response.start"
            assert message["status"] == 200
            events.append("headers")
            raise OSError("fixture client closed before headers")

        with override_settings(ROOT_URLCONF=(path("upstream/", view),), MIDDLEWARE=[]):
            handler = ArchiveBoxASGIHandler()(
                {"type": "http", "path": "/upstream/", "method": "GET", "headers": []},
                messages.get,
                broken_send,
            )
            if ending == "preheader-disconnect":
                task = asyncio.create_task(handler)
                try:
                    await asyncio.wait_for(registered.wait(), 2)
                    await messages.put({"type": "http.disconnect"})
                    await asyncio.wait_for(task, 2)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            else:
                with pytest.raises(OSError, match="fixture client closed before headers"):
                    await handler
        assert events == (["released"] if ending == "preheader-disconnect" else ["headers", "released"])
        assert await asyncio.wait_for(asyncio.get_running_loop().sock_recv(peer, 1), 2) == b""

    try:
        asyncio.run(run())
    finally:
        upstream.close()
        peer.close()
