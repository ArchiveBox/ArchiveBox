"""Private diagnostic files remain backpressured through real ASGI requests."""

import hashlib
import os
import re
import time
from pathlib import Path

import psutil
import pytest
import requests
from django.contrib.auth import get_user_model

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.importers.catalog import get_importer
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.tests.conftest import create_admin_and_token
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
def test_private_file_routes_stream_without_buffering(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite", BASE_URL="http://archivebox.localhost")
    state = server.wait_for_workers(("worker_uvicorn",))
    process = psutil.Process(state["worker_uvicorn"]["pid"])
    # Startup may choose a shorter local path for its supervisor socket. Match
    # the actual worker's TMP_DIR, as the screencast hook does in that process.
    live_tmp = Path(process.environ()["TMP_DIR"])
    create_admin_and_token(server.data_dir)
    with use_archivebox_db(server.data_dir):
        user = get_user_model().objects.get(username="apitestadmin")
        source = ImporterSource.objects.create(created_by=user, name="Diagnostic files", plugin="importer_rss", feed="feed", enabled=False)
        run = ImporterRun.objects.create(source=source, status="failed")
        run_id = str(run.pk)
        run_dir = server.data_dir / "importers" / str(source.pk) / run_id
        crawl = Crawl.objects.create(urls="https://example.com/private-frame", status="sealed", retry_at=None, created_by=user)
        snapshot = Snapshot.objects.create(crawl=crawl, url=crawl.urls, status="sealed", retry_at=None, config={"PERMISSIONS": "private"})
        snapshot_id = str(snapshot.pk)
        frame_key = hashlib.sha256(os.path.abspath(snapshot.get_storage_path_for_version(snapshot.fs_version)).encode()).hexdigest()
    run_dir.mkdir(parents=True)
    payload = run_dir / "harness.log"
    digest = hashlib.sha256()
    # Real text bytes, not compressible zeros: the log is larger than the
    # raw-download regression's 16 MiB allowance for fixed server overhead.
    with payload.open("wb") as output:
        for _ in range(64):
            chunk = os.urandom(512 * 1024).hex().encode()[:-1] + b"\n"
            output.write(chunk)
            digest.update(chunk)
    (run_dir / "failure.log").write_text("Warm diagnostic route\n")
    root = f"http://127.0.0.1:{server.port}"
    headers = {"Host": f"admin.archivebox.localhost:{server.port}"}
    log_url = f"{root}/admin/importers/runs/{run_id}/logs/"
    denied = requests.get(log_url + "harness.log/", headers=headers, allow_redirects=False, timeout=15)
    assert denied.status_code == 302
    assert "/admin/login/" in denied.headers["Location"]
    with requests.Session() as client:
        client.trust_env = False
        login_page = client.get(root + "/admin/login/", headers=headers, timeout=15)
        assert login_page.status_code == 200
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
        assert csrf
        login = client.post(
            root + "/admin/login/",
            headers=headers,
            data={"username": "apitestadmin", "password": "testpass123", "csrfmiddlewaretoken": csrf[1], "next": "/admin/"},
            allow_redirects=False,
            timeout=15,
        )
        assert login.status_code == 302
        warm = client.get(log_url + "failure.log/", headers=headers, timeout=15)
        assert warm.status_code == 200
        assert warm.content == b"Warm diagnostic route\n"
        baseline = process.memory_info().rss
        peak_growth = 0
        for _ in range(2):
            with client.get(log_url + "harness.log/", headers=headers, stream=True, timeout=15) as response:
                assert response.status_code == 200
                assert int(response.headers["Content-Length"]) == payload.stat().st_size
                assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
                assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                assert "no-store" in response.headers["Cache-Control"]
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    peak_growth = max(peak_growth, process.memory_info().rss - baseline)
                    assert peak_growth < 16 * 1024 * 1024
                    time.sleep(0.05)
                assert str(payload) in {entry.path for entry in process.open_files()}
                health = client.get(root + "/health/", timeout=5)
                assert health.status_code == 200 and health.content == b"OK"
            deadline = time.monotonic() + 5
            while str(payload) in {entry.path for entry in process.open_files()}:
                assert time.monotonic() < deadline, "Disconnected importer log retained its source file"
                time.sleep(0.05)
        actual = hashlib.sha256()
        with client.get(log_url + "harness.log/", headers=headers, stream=True, timeout=15) as response:
            assert response.status_code == 200
            for chunk in response.iter_content(64 * 1024):
                actual.update(chunk)
        assert actual.digest() == digest.digest()

        # The same real authenticated routes also serve screenshots and plugin
        # assets. Preserve their bytes, privacy and media types under ASGI.
        png = (Path(__file__).parents[1] / "templates/static/chrome_extension_icon.png").read_bytes()
        (run_dir / "failure-1.png").write_bytes(png)
        definition = get_importer("importer_rss", "feed")
        plugin_root = get_plugin_catalog()[definition.plugin].path
        step, guide = next((index, entry["image"]) for index, entry in enumerate(definition.setup) if entry.get("image"))
        images = [
            (f"/admin/importers/runs/{run_id}/screenshots/failure-1.png", png, "image/png"),
            ("/admin/importers/icon/importer_rss/feed/", (plugin_root / definition.icon).read_bytes(), "image/svg+xml"),
            (f"/admin/importers/guide/importer_rss/feed/{step}/", (plugin_root / guide).read_bytes(), "image/jpeg"),
        ]
        frame = live_tmp / "chrome_screencast" / frame_key / "latest.jpg"
        frame.parent.mkdir(parents=True)
        jpeg = (Path(__file__).parent / "fixtures/bablosoft-lazy-image/pic.jpg").read_bytes()
        frame.write_bytes(jpeg)
        images.append((f"/api/v1/core/snapshot/{snapshot_id}/screencast.jpg", jpeg, "image/jpeg"))
        try:
            for route, content, content_type in images:
                response = client.get(root + route, headers=headers, timeout=15)
                assert response.status_code == 200, (route, response.text)
                assert response.content == content, route
                assert response.headers["Content-Type"] == content_type
                assert "no-store" in response.headers["Cache-Control"]
                denied = requests.get(root + route, headers=headers, allow_redirects=False, timeout=15)
                assert denied.status_code == (404 if route.startswith("/api/") else 302)
        finally:
            frame.unlink()
            frame.parent.rmdir()
        print(f"Importer log bytes={payload.stat().st_size}; peak worker RSS growth={peak_growth}")
    logs = (server.data_dir / "logs/worker_uvicorn.log").read_text()
    assert "must consume synchronous iterators" not in logs
