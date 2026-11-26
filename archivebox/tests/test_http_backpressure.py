"""Overloaded HTTP workers must reject requests before starting Django work."""

from http.client import HTTPResponse
import re
import signal
import socket
import subprocess
import sys
import time

import psutil
import pytest
import requests

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.routes_util import get_snapshot_host
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import api_auth_headers, cli_env, create_admin_and_token
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
def test_real_http_overload_rejects_without_queueing_and_recovers(initialized_archive, free_tcp_port_factory):
    port = free_tcp_port_factory()
    token = create_admin_and_token(initialized_archive)
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", status="sealed", retry_at=None)
        snapshot = Snapshot.objects.create(
            crawl=crawl,
            url="https://news.ycombinator.com/",
            status="sealed",
            retry_at=None,
            config={"PERMISSIONS": "public"},
        )
        host = get_snapshot_host(str(snapshot.id), overrides={"BASE_URL": "http://archivebox.localhost"})
        payload = snapshot.output_dir / "staticfile" / "payload.bin"
        counts = (Snapshot.objects.count(), Crawl.objects.count(), ArchiveResult.objects.count())
    payload.parent.mkdir(parents=True)
    prefix = b"ArchiveBox streamed archive payload\n"
    with payload.open("wb") as output:
        output.write(prefix)
        # A real sparse file keeps setup cheap while exceeding TCP buffers on
        # every supported platform; stopped readers keep the response active.
        output.truncate(64 * 1024 * 1024)
    payload_stat = payload.stat()
    env = cli_env(
        disable_extractors=True,
        BASE_URL=f"http://archivebox.localhost:{port}",
        ALLOWED_HOSTS="*",
        SEARCH_BACKEND_ENGINE="sqlite",
        WEB_CONCURRENCY="1",
    )
    log_path = initialized_archive / "backpressure-uvicorn.log"
    held = []
    with log_path.open("w") as log:
        # Initialize Django before Uvicorn configures its diagnostic logging;
        # Django's normal startup logging otherwise suppresses Uvicorn TRACE.
        worker = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from archivebox.core.asgi import application; import uvicorn; "
                "uvicorn.run('archivebox.workers.http_server:application', "
                f"host='127.0.0.1', port={port}, lifespan='on', log_level='trace', "
                "proxy_headers=False, reset_contextvars=True)",
            ],
            cwd=initialized_archive,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        process = psutil.Process(worker.pid)
        try:
            deadline = time.monotonic() + 20
            while "Application startup complete" not in log_path.read_text():
                assert worker.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, log_path.read_text()
                time.sleep(0.05)

            def limits():
                values = re.findall(r"HTTP request limit: total=(\d+) workers=1", log_path.read_text())
                assert values, log_path.read_text()
                return [int(value) for value in values]

            def wait_completed(ports):
                # An incomplete upload has no payload FD. Uvicorn's existing
                # completion trace fires only after the outer ASGI gate releases
                # its slot, including Django's disconnect and stream cleanup.
                deadline = time.monotonic() + 5
                while True:
                    completed = {int(port) for port in re.findall(r"127\.0\.0\.1:(\d+) - ASGI \[\d+\] Completed", log_path.read_text())}
                    if ports <= completed:
                        return
                    assert time.monotonic() < deadline, f"Requests did not finish ASGI cleanup: {ports - completed}"
                    time.sleep(0.01)

            def fill_worker():
                # Expect: 100-continue acknowledges admission to Django's real
                # body reader. Follow actual 429s because resource sampling may
                # change the budget while these requests remain active.
                deadline = time.monotonic() + 20
                while True:
                    assert time.monotonic() < deadline, "Worker did not bound active requests"
                    reader = socket.create_connection(("127.0.0.1", port), timeout=5)
                    keep = False
                    try:
                        reader.sendall(
                            (
                                "POST /admin/login/ HTTP/1.1\r\n"
                                f"Host: {admin_host}\r\n"
                                "Content-Type: application/x-www-form-urlencoded\r\n"
                                "Content-Length: 1024\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n"
                            ).encode(),
                        )
                        interim = bytearray()
                        while b"\r\n\r\n" not in interim:
                            chunk = reader.recv(1024)
                            assert chunk
                            interim.extend(chunk)
                        if bytes(interim).startswith(b"HTTP/1.1 429 "):
                            return
                        assert bytes(interim) == b"HTTP/1.1 100 Continue\r\n\r\n"
                        held.append((reader, None))
                        keep = True
                        # Existing requests may outlive a lower resource sample.
                        assert len(held) <= max(limits())
                    finally:
                        if not keep:
                            reader.close()

            url = f"http://127.0.0.1:{port}/staticfile/payload.bin?raw=1"
            with requests.Session() as client:
                client.trust_env = False
                admin_host = f"admin.archivebox.localhost:{port}"
                admin_url = f"http://127.0.0.1:{port}/admin/"
                login = client.get(admin_url + "login/", headers={"Host": admin_host}, timeout=5)
                assert login.status_code == 200
                csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.text)[1]
                logged_in = client.post(
                    admin_url + "login/",
                    headers={"Host": admin_host, "Referer": f"http://{admin_host}/admin/login/"},
                    data={"csrfmiddlewaretoken": csrf, "username": "apitestadmin", "password": "testpass123", "next": "/admin/"},
                    allow_redirects=False,
                    timeout=5,
                )
                assert logged_in.status_code == 302
                assert logged_in.headers["Location"] == "/admin/"
                warm = client.get(url, headers={"Host": host, "Range": f"bytes=0-{len(prefix) - 1}"}, timeout=5)
                assert warm.status_code == 206
                assert warm.content == prefix

                # Real TCP receive windows hold the streams open after headers.
                # A fixed burst based on the observed resource budget exercises
                # shedding without requiring a particular random sequence.
                for _ in range(limits()[-1] + 16):
                    reader = socket.socket()
                    response = None
                    try:
                        reader.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
                        reader.settimeout(5)
                        reader.connect(("127.0.0.1", port))
                        reader.sendall(
                            f"GET /staticfile/payload.bin?raw=1 HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode(),
                        )
                        response = HTTPResponse(reader)
                        response.begin()
                        if response.status == 200:
                            assert int(response.getheader("Content-Length")) == payload_stat.st_size
                            held.append((reader, response))
                            continue
                        assert response.status == 429
                        assert 1 <= int(response.getheader("Retry-After")) <= 3
                        assert "no-store" in response.getheader("Cache-Control")
                        assert response.read()
                    finally:
                        if not held or held[-1][0] is not reader:
                            if response is not None:
                                response.close()
                            reader.close()
                assert 1 <= len(held) <= max(limits())
                assert sum(entry.path == str(payload) for entry in process.open_files()) == len(held)

                fill_worker()
                # Leave one current slot for real admin navigation. A falling
                # budget requires releasing more existing requests; it must not
                # invalidate the test's accounting or kill admitted responses.
                released_ports = set()
                while len(held) >= limits()[-1]:
                    reader, response = held.pop()
                    released_ports.add(reader.getsockname()[1])
                    if response is not None:
                        response.close()
                    reader.close()
                wait_completed(released_ports)
                health = client.get(f"http://127.0.0.1:{port}/health/", timeout=2)
                assert health.status_code == 200
                if limits()[-1] > 2:
                    assert len(held) > limits()[-1] // 2

                admin = client.get(admin_url, headers={"Host": admin_host}, timeout=5)
                assert admin.status_code == 200
                assert "apitestadmin" in admin.text
                with requests.Session() as anonymous:
                    anonymous.trust_env = False
                    denied = anonymous.get(admin_url, headers={"Host": admin_host}, allow_redirects=False, timeout=5)
                    assert denied.status_code == 302
                    assert "/admin/login/" in denied.headers["Location"]
                    login = anonymous.get(admin_url + "login/", headers={"Host": admin_host}, timeout=5)
                    assert login.status_code == 200
                health = client.get(f"http://127.0.0.1:{port}/health/", timeout=5)
                assert health.status_code == 200

                for method in ("GET", "HEAD") * 4:
                    fill_worker()
                    started = time.monotonic()
                    response = client.request(method, url, headers={"Host": host}, timeout=2, stream=True)
                    with response:
                        assert response.status_code == 429
                        assert time.monotonic() - started < 1
                        assert 1 <= int(response.headers["Retry-After"]) <= 3
                        assert "no-store" in response.headers["Cache-Control"]
                        assert response.headers["Content-Type"].startswith("text/plain")
                        assert response.content == (b"Server is under high load. Please try again shortly.\n" if method == "GET" else b"")

                for priority_url in (admin_url, f"http://127.0.0.1:{port}/health/"):
                    fill_worker()
                    blocked = client.get(priority_url, headers={"Host": admin_host}, timeout=2)
                    assert blocked.status_code == 429

                fill_worker()
                rejected = client.post(
                    f"http://127.0.0.1:{port}/api/v1/core/snapshots",
                    headers=api_auth_headers(token, port=port),
                    json={"url": "https://news.ycombinator.com/newest", "status": "sealed"},
                    timeout=2,
                )
                assert rejected.status_code == 429
                assert 1 <= int(rejected.headers["Retry-After"]) <= 3
                assert "no-store" in rejected.headers["Cache-Control"]

                released_ports = {reader.getsockname()[1] for reader, _response in held}
                for reader, response in held:
                    if response is not None:
                        response.close()
                    reader.close()
                held.clear()
                wait_completed(released_ports)
                deadline = time.monotonic() + 5
                while str(payload) in {entry.path for entry in process.open_files()}:
                    assert time.monotonic() < deadline, "Disconnected readers retained their source files"
                    time.sleep(0.05)
                # Cleanup must release admission slots as well as file handles.
                recovered = client.get(url, headers={"Host": host, "Range": f"bytes=0-{len(prefix) - 1}"}, timeout=5)
                assert recovered.status_code == 206
                assert recovered.content == prefix
                health = client.get(f"http://127.0.0.1:{port}/health/", timeout=5)
                assert health.status_code == 200
                assert health.content == b"OK"
                with use_archivebox_db(initialized_archive):
                    assert (Snapshot.objects.count(), Crawl.objects.count(), ArchiveResult.objects.count()) == counts
                assert sorted(payload.parent.iterdir()) == [payload]
                assert (payload.stat().st_size, payload.stat().st_mtime_ns) == (payload_stat.st_size, payload_stat.st_mtime_ns)
        finally:
            for reader, response in held:
                if response is not None:
                    response.close()
                reader.close()
            if worker.poll() is None:
                worker.send_signal(signal.SIGTERM)
                worker.wait(timeout=10)
