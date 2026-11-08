"""Directory ZIPs release their real file handles when HTTP clients leave."""

import hashlib
import os
import time
import zipfile
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
def test_uvicorn_zip_has_bounded_memory_and_releases_source_file(archivebox_daemon_server, tmp_path):
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
    # Incompressible bytes exceed both socket buffers and the memory allowance;
    # compressible input would hide whole-ZIP buffering under ASGI.
    digest = hashlib.sha256()
    with payload.open("wb") as output:
        for _ in range(64):
            chunk = os.urandom(1024 * 1024)
            output.write(chunk)
            digest.update(chunk)
    host = get_snapshot_host(snapshot_id, overrides={"BASE_URL": "http://archivebox.localhost"})
    url = f"http://127.0.0.1:{server.port}/staticfile/?download=zip"
    with requests.Session() as client:
        client.trust_env = False
        warm = client.get(
            f"{url.removesuffix('?download=zip')}payload.bin?raw=1",
            headers={"Host": host, "Range": "bytes=0-65535"},
            timeout=15,
        )
        assert warm.status_code == 206
        with payload.open("rb") as source:
            assert warm.content == source.read(65536)
        baseline = uvicorn.memory_info().rss
        peak_growth = 0
        for _ in range(3):
            with client.get(url, headers={"Host": host}, stream=True, timeout=15) as response:
                assert response.status_code == 200
                assert response.headers["Content-Type"] == "application/zip"
                # Keep the generator alive: discarding it closes urllib3's socket
                # immediately, before we can observe the server's open source file.
                chunks = response.iter_content(64 * 1024)
                assert next(chunks).startswith(b"PK")
                assert not response.raw.closed, "ZIP connection closed before the deliberate disconnect"
                # A stalled real TCP reader must not make Django consume the
                # entire synchronous ZIP iterator. Use the raw-download test's
                # 16 MiB fixed-overhead allowance for this 64 MiB payload.
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    peak_growth = max(peak_growth, uvicorn.memory_info().rss - baseline)
                    assert peak_growth < 16 * 1024 * 1024
                    time.sleep(0.05)
                assert str(payload) in {entry.path for entry in uvicorn.open_files()}
                health = client.get(f"http://127.0.0.1:{server.port}/health/", timeout=5)
                assert health.status_code == 200
                assert health.content == b"OK"
            chunks.close()
            deadline = time.monotonic() + 5
            while str(payload) in {entry.path for entry in uvicorn.open_files()}:
                assert time.monotonic() < deadline, "Disconnected ZIP download kept its source file open"
                time.sleep(0.05)

        saved_zip = tmp_path / "download.zip"
        with client.get(url, headers={"Host": host}, stream=True, timeout=15) as response, saved_zip.open("wb") as output:
            assert response.status_code == 200
            assert response.headers["Content-Type"] == "application/zip"
            for chunk in response.iter_content(64 * 1024):
                output.write(chunk)
                peak_growth = max(peak_growth, uvicorn.memory_info().rss - baseline)
                assert peak_growth < 16 * 1024 * 1024
        with zipfile.ZipFile(saved_zip) as archive:
            assert archive.namelist() == ["staticfile/payload.bin"]
            assert archive.getinfo("staticfile/payload.bin").file_size == payload.stat().st_size
            with archive.open("staticfile/payload.bin") as source:
                assert hashlib.file_digest(source, "sha256").digest() == digest.digest()
            assert archive.testzip() is None
        print(f"ZIP payload={payload.stat().st_size} bytes; peak worker RSS growth={peak_growth} bytes")


@pytest.mark.parametrize("use_async_stream", [False, True])
def test_directory_zip_does_not_start_work_before_body_consumption(tmp_path: Path, use_async_stream: bool):
    import threading

    root = tmp_path / "unconsumed-export"
    root.mkdir()
    (root / "payload.bin").write_bytes(os.urandom(2 * 1024 * 1024))
    request = RequestFactory().get("/?download=zip")
    if use_async_stream:
        request.scope = {"type": "http"}
    before = set(threading.enumerate())
    response = serve_static_with_byterange_support(request, "", document_root=root, show_indexes=True)
    try:
        # A sync view can finish constructing its response after the ASGI
        # caller has disconnected. Its response never reaches send_response or
        # response.close(), so construction must not start an orphan producer.
        producers = [thread for thread in threading.enumerate() if thread not in before and thread.name.startswith("zip-stream-")]
        assert not producers, "Unconsumed ZIP response started background work with no body consumer"
    finally:
        response.close()
        for thread in threading.enumerate():
            if thread not in before and thread.name.startswith("zip-stream-"):
                thread.join(timeout=2)


@pytest.mark.parametrize("use_async_stream", [False, True])
@pytest.mark.parametrize("read_first_chunk", [False, True])
def test_directory_zip_close_stops_producer(tmp_path: Path, use_async_stream: bool, read_first_chunk: bool):
    import asyncio
    import threading

    root = tmp_path / "cancelled-export"
    root.mkdir()
    # Incompressible real bytes keep the bounded producer queue full when an
    # active download is abandoned. Unconsumed responses must start no work.
    (root / "payload.bin").write_bytes(os.urandom(2 * 1024 * 1024))
    request = RequestFactory().get("/?download=zip")
    if use_async_stream:
        request.scope = {"type": "http"}
    before = set(threading.enumerate())
    response = serve_static_with_byterange_support(request, "", document_root=root, show_indexes=True)
    producers = [thread for thread in threading.enumerate() if thread not in before and thread.name.startswith("zip-stream-")]
    assert not producers
    assert response.is_async is use_async_stream
    try:
        if read_first_chunk:
            if use_async_stream:

                async def read_and_close():
                    iterator = aiter(response.streaming_content)
                    assert (await anext(iterator)).startswith(b"PK")
                    producers.extend(
                        thread for thread in threading.enumerate() if thread not in before and thread.name.startswith("zip-stream-")
                    )
                    response.close()
                    await iterator.aclose()

                asyncio.run(read_and_close())
            else:
                assert next(iter(response.streaming_content)).startswith(b"PK")
                producers.extend(
                    thread for thread in threading.enumerate() if thread not in before and thread.name.startswith("zip-stream-")
                )
            assert len(producers) == 1
        response.close()
        for producer in producers:
            producer.join(timeout=2)
            assert not producer.is_alive(), "Closed ZIP response retained its producer thread and queued output"
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
