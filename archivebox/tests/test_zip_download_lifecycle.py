"""Directory ZIPs release their real file handles when HTTP clients leave."""

import os
import time
from pathlib import Path

import psutil
import pytest
import requests
from django.test import RequestFactory

from archivebox.core.models import Snapshot
from archivebox.core.routes_util import get_snapshot_host
from archivebox.crawls.models import Crawl
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
def test_uvicorn_zip_disconnect_releases_source_file(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite", BASE_URL="http://archivebox.localhost")
    state = server.wait_for_workers(("worker_uvicorn",))
    uvicorn = psutil.Process(state["worker_uvicorn"]["pid"])
    with use_archivebox_db(server.data_dir):
        crawl = Crawl.objects.create(urls="https://example.com/zip-download", status="sealed", retry_at=None)
        snapshot = Snapshot.objects.create(
            crawl=crawl,
            url="https://example.com/zip-download",
            status="sealed",
            retry_at=None,
            config={"PERMISSIONS": "public"},
        )
        snapshot_id = str(snapshot.id)
        payload = snapshot.output_dir / "staticfile" / "payload.bin"
    payload.parent.mkdir(parents=True)
    # Exceed socket buffers so the server is still compressing when we close.
    with payload.open("wb") as output:
        for _ in range(32):
            output.write(os.urandom(1024 * 1024))
    host = get_snapshot_host(snapshot_id, overrides={"BASE_URL": "http://archivebox.localhost"})
    url = f"http://127.0.0.1:{server.port}/staticfile/?download=zip"
    for _ in range(3):
        with requests.get(url, headers={"Host": host}, stream=True, timeout=15) as response:
            assert response.status_code == 200
            assert response.headers["Content-Type"] == "application/zip"
            # Keep the generator alive: discarding it closes urllib3's socket
            # immediately, before we can observe the server's open source file.
            chunks = response.iter_content(64 * 1024)
            assert next(chunks).startswith(b"PK")
            assert not response.raw.closed, "ZIP connection closed before the deliberate disconnect"
            assert str(payload) in {entry.path for entry in uvicorn.open_files()}
        chunks.close()
        deadline = time.monotonic() + 5
        while str(payload) in {entry.path for entry in uvicorn.open_files()}:
            assert time.monotonic() < deadline, "Disconnected ZIP download kept its source file open"
            time.sleep(0.05)
    assert requests.get(f"http://127.0.0.1:{server.port}/health/", timeout=5).status_code == 200


@pytest.mark.parametrize("use_async_stream", [False, True])
@pytest.mark.parametrize("read_first_chunk", [False, True])
def test_directory_zip_close_stops_producer(tmp_path: Path, use_async_stream: bool, read_first_chunk: bool):
    import asyncio
    import threading

    root = tmp_path / "cancelled-export"
    root.mkdir()
    # Incompressible real bytes keep the bounded producer queue full when the
    # download is abandoned, including before the first response iteration.
    (root / "payload.bin").write_bytes(os.urandom(2 * 1024 * 1024))
    request = RequestFactory().get("/?download=zip")
    if use_async_stream:
        request.scope = {"type": "http"}
    before = set(threading.enumerate())
    response = serve_static_with_byterange_support(request, "", document_root=root, show_indexes=True)
    producers = [thread for thread in threading.enumerate() if thread not in before and thread.name.startswith("zip-stream-")]
    assert len(producers) == 1
    assert response.is_async is use_async_stream
    try:
        if read_first_chunk:
            if use_async_stream:

                async def read_and_close():
                    iterator = aiter(response.streaming_content)
                    assert (await anext(iterator)).startswith(b"PK")
                    response.close()
                    await iterator.aclose()

                asyncio.run(read_and_close())
            else:
                assert next(iter(response.streaming_content)).startswith(b"PK")
        response.close()
        producers[0].join(timeout=2)
        assert not producers[0].is_alive(), "Closed ZIP response retained its producer thread and queued output"
    finally:
        response.close()


@pytest.mark.parametrize("use_async_stream", [False, True])
def test_directory_zip_complete_stream_preserves_bytes(tmp_path: Path, use_async_stream: bool):
    import asyncio
    import io
    import zipfile

    root = tmp_path / "complete-export"
    root.mkdir()
    content = os.urandom(256 * 1024)
    (root / "payload.bin").write_bytes(content)
    request = RequestFactory().get("/?download=zip")
    if use_async_stream:
        request.scope = {"type": "http"}
    response = serve_static_with_byterange_support(request, "", document_root=root, show_indexes=True)
    try:
        if use_async_stream:

            async def collect():
                return b"".join([chunk async for chunk in response.streaming_content])

            body = asyncio.run(collect())
        else:
            body = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            assert archive.namelist() == ["complete-export/payload.bin"]
            assert archive.read("complete-export/payload.bin") == content
            assert archive.testzip() is None
    finally:
        response.close()
