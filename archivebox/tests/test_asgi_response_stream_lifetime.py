"""The ASGI request lifetime owns upstream cleanup even before the first body part."""

import asyncio
import socket

import pytest
from django.http import StreamingHttpResponse
from django.test import override_settings
from django.urls import path


@pytest.mark.django_db(transaction=True)
def test_asgi_closes_owned_stream_when_sending_headers_fails(initialized_archive):
    from archivebox.core.asgi import ArchiveBoxASGIHandler

    events = []
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
        return StreamingHttpResponse(body())

    async def run():
        messages = asyncio.Queue()
        await messages.put({"type": "http.request", "body": b""})

        async def broken_send(message):
            assert message["type"] == "http.response.start"
            assert message["status"] == 200
            raise OSError("fixture client closed before headers")

        with override_settings(ROOT_URLCONF=(path("upstream/", view),), MIDDLEWARE=[]):
            with pytest.raises(OSError, match="fixture client closed before headers"):
                await ArchiveBoxASGIHandler()(
                    {"type": "http", "path": "/upstream/", "method": "GET", "headers": []},
                    messages.get,
                    broken_send,
                )
        assert events == ["released"]
        assert await asyncio.wait_for(asyncio.get_running_loop().sock_recv(peer, 1), 2) == b""

    try:
        asyncio.run(run())
    finally:
        upstream.close()
        peer.close()
