"""Slow HTTP readers must not turn archived files into server-sized buffers."""

import hashlib
import asyncio
import os
import time

import psutil
import pytest
import requests

from archivebox.core.models import Snapshot
from archivebox.core.routes_util import get_snapshot_host
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db


def test_server_accepts_authenticated_chunked_output_upload(archivebox_daemon_server):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
    from archivebox.tests.conftest import api_auth_headers, create_admin_and_token, live_api_request

    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite", BASE_URL="http://archivebox.localhost")
    token = create_admin_and_token(server.data_dir)
    snapshot = live_api_request(
        server.port,
        "post",
        "/api/v1/core/snapshots",
        api_token=token,
        json={"url": "https://example.com/chunked", "status": "sealed"},
    )
    assert snapshot.status_code == 200
    payload = b"<html>Real streamed upload</html>"
    body = encode_multipart(
        BOUNDARY,
        {
            "files": SimpleUploadedFile("output.html", payload, content_type="text/html"),
            "output_paths": "output.html",
            "status": "succeeded",
            "snapshot_id": snapshot.json()["id"],
            "plugin": "dom",
        },
    )
    response = requests.post(
        f"http://127.0.0.1:{server.port}/api/v1/core/archiveresults",
        data=iter([body[:100], body[100:]]),
        headers={**api_auth_headers(token, port=server.port), "Content-Type": MULTIPART_CONTENT},
        timeout=15,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    files = list((server.data_dir / "archive").glob("users/*/snapshots/*/*/*/dom/output.html"))
    assert len(files) == 1
    assert files[0].read_bytes() == payload


def test_server_does_not_expand_proxy_trust(archivebox_daemon_server):
    from archivebox.tests.conftest import create_admin_and_token

    server = archivebox_daemon_server(
        SEARCH_BACKEND_ENGINE="sqlite",
        BASE_URL="http://localhost",
        SERVER_SECURITY_MODE="safe-onedomain-nojsreplay",
        REVERSE_PROXY_WHITELIST="192.0.2.0/24",
        REVERSE_PROXY_USER_HEADER="Remote-User",
    )
    create_admin_and_token(server.data_dir)
    response = requests.get(
        f"http://127.0.0.1:{server.port}/admin/",
        headers={"Host": "localhost", "Remote-User": "apitestadmin", "X-Forwarded-For": "192.0.2.10"},
        allow_redirects=False,
        timeout=15,
    )
    assert response.status_code == 302
    assert "/admin/login/" in response.headers["Location"]


@pytest.mark.django_db(transaction=True)
def test_server_rejects_oversized_websocket_message(agent_server, live_opencode):
    from abx_plugins.plugins.opencode import runtime
    from abx_plugins.plugins.opencode.archivebox.conftest import _login_cookie
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosedError

    server_url, _, _ = agent_server
    cookie = _login_cookie(server_url)
    created = requests.post(
        server_url + "/admin/agent/opencode/pty",
        headers={"Cookie": cookie, "Origin": server_url},
        json={"command": "/bin/sh", "args": []},
        timeout=10,
    )
    assert created.status_code == 200
    pty_id = created.json()["id"]

    async def check_socket():
        async with (
            connect(
                server_url.replace("http", "ws", 1) + f"/admin/agent/opencode/pty/{pty_id}/connect",
                origin=server_url,
                additional_headers={"Cookie": cookie},
                proxy=None,
            ) as socket,
            asyncio.timeout(10),
        ):
            await socket.send("printf 'ABX_%s\\n' BOUND_OK\n")
            output = ""
            while "ABX_BOUND_OK" not in output:
                chunk = await socket.recv()
                output += chunk.decode() if isinstance(chunk, bytes) else chunk
            await socket.send("x" * (1024 * 1024 + 1))
            with pytest.raises(ConnectionClosedError) as error:
                while True:
                    await socket.recv()
            assert error.value.rcvd.code == 1009

    try:
        asyncio.run(check_socket())
        assert requests.get(server_url + "/health/", timeout=10).content == b"OK"
    finally:
        deleted = requests.delete(
            live_opencode.settings["origin"] + f"/pty/{pty_id}",
            auth=runtime._server_auth(live_opencode.settings),
            timeout=10,
        )
        assert deleted.status_code == 200


def test_uvicorn_access_log_preserves_query_redaction(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite", BASE_URL="http://archivebox.localhost")
    server.wait_for_workers(("worker_uvicorn",))
    response = requests.get(
        f"http://127.0.0.1:{server.port}/api/v1/docs?token=transport-log-secret&limit=1",
        headers={"Host": "api.archivebox.localhost"},
        timeout=15,
    )
    assert response.status_code == 200
    output = (server.data_dir / "logs" / "worker_uvicorn.log").read_text()
    assert "transport-log-secret" not in output
    assert "/api/v1/docs?token=[REDACTED]&limit=1" in output


@pytest.mark.django_db(transaction=True)
def test_slow_archive_download_has_bounded_memory_and_releases_file(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite", BASE_URL="http://archivebox.localhost")
    state = server.wait_for_workers(("worker_uvicorn",))
    process = psutil.Process(state["worker_uvicorn"]["pid"])
    with use_archivebox_db(server.data_dir):
        crawl = Crawl.objects.create(urls="https://example.com/download", status="sealed", retry_at=None)
        snapshot = Snapshot.objects.create(
            crawl=crawl,
            url="https://example.com/download",
            status="sealed",
            retry_at=None,
            config={"PERMISSIONS": "public"},
        )
        snapshot_id = str(snapshot.id)
        payload = snapshot.output_dir / "staticfile" / "payload.bin"
    payload.parent.mkdir(parents=True)
    digest = hashlib.sha256()
    with payload.open("wb") as output:
        for _ in range(64):
            chunk = os.urandom(1024 * 1024)
            output.write(chunk)
            digest.update(chunk)
    host = get_snapshot_host(snapshot_id, overrides={"BASE_URL": "http://archivebox.localhost"})
    url = f"http://127.0.0.1:{server.port}/staticfile/payload.bin?raw=1"
    with requests.Session() as client:
        client.trust_env = False
        warm = client.get(url, headers={"Host": host, "Range": "bytes=0-65535"}, timeout=15)
        assert warm.status_code == 206
        with payload.open("rb") as source:
            assert warm.content == source.read(65536)
        for _ in range(2):
            baseline = process.memory_info().rss
            with client.get(url, headers={"Host": host}, stream=True, timeout=15) as response:
                assert response.status_code == 200
                assert int(response.headers["Content-Length"]) == payload.stat().st_size
                # Hold a real TCP reader still. A transport with backpressure
                # leaves the file open instead of eagerly buffering all bytes.
                # After warming the route, 16 MiB allows fixed overhead but
                # rejects buffering even one quarter of this 64 MiB payload.
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    assert process.memory_info().rss - baseline < 16 * 1024 * 1024
                    time.sleep(0.05)
                assert str(payload) in {entry.path for entry in process.open_files()}
                health = client.get(f"http://127.0.0.1:{server.port}/health/", timeout=5)
                assert health.status_code == 200
                assert health.content == b"OK"
            deadline = time.monotonic() + 5
            while str(payload) in {entry.path for entry in process.open_files()}:
                assert time.monotonic() < deadline, "Disconnected reader retained the source file"
                time.sleep(0.05)
        actual = hashlib.sha256()
        with client.get(url, headers={"Host": host}, stream=True, timeout=15) as response:
            assert response.status_code == 200
            for chunk in response.iter_content(64 * 1024):
                actual.update(chunk)
        assert actual.digest() == digest.digest()
        tail = client.get(url, headers={"Host": host, "Range": "bytes=-65536"}, timeout=15)
        assert tail.status_code == 206
        with payload.open("rb") as source:
            source.seek(-65536, 2)
            assert tail.content == source.read()
