"""Real IPv6 administration, API ingestion, capture, and saved-file replay."""

import re
import socket
import subprocess
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote, urljoin, urlsplit

import pytest
import requests

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import (
    cli_env,
    create_admin_and_token,
    kill_processes_for_data_dir,
    run_archivebox_cmd,
    stop_archivebox_process,
    wait_for_log,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db


class IPv6FileServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


@pytest.mark.parametrize("trusted_network", ["127.0.0.1/32", "::1/128"])
def test_dual_family_server_preserves_proxy_peer_trust(initialized_archive, trusted_network):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        listener.bind(("::1", 0))
        port = listener.getsockname()[1]
    create_admin_and_token(initialized_archive)
    env = cli_env(
        live=True,
        BASE_URL="http://localhost",
        BIND_ADDR=f"[::]:{port}",
        SERVER_SECURITY_MODE="safe-onedomain-nojsreplay",
        REVERSE_PROXY_WHITELIST=trusted_network,
        REVERSE_PROXY_USER_HEADER="Remote-User",
    )
    with (initialized_archive / "server-proxy-trust.log").open("w") as log:
        process = run_archivebox_cmd(
            ["server"],
            cwd=initialized_archive,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            wait=False,
            start_new_session=True,
        )
    try:
        wait_for_log(initialized_archive / "logs/worker_uvicorn.log", "Uvicorn running on", timeout=30)
        trusted_peer = trusted_network.split("/")[0]
        for host, peer in [("127.0.0.1", "127.0.0.1"), ("[::1]", "::1")]:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    f"http://{host}:{port}/admin/",
                    headers={"Host": "localhost", "Remote-User": "apitestadmin", "X-Forwarded-For": trusted_peer},
                    allow_redirects=False,
                    timeout=5,
                )
            if peer == trusted_peer:
                assert response.status_code == 200, response.text
                assert "Log out" in response.text
            else:
                assert response.status_code == 302, response.text
                assert "/admin/login/" in response.headers["Location"]
    finally:
        stop_archivebox_process(process)
        kill_processes_for_data_dir(initialized_archive)


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(180)
@pytest.mark.parametrize("pinned_base_url", [True, False])
def test_ipv6_admin_api_capture_and_replay(tmp_path, pinned_base_url):
    site = tmp_path / "origin"
    site.mkdir()
    marker = "ArchiveBox IPv6 capture acceptance 1927"
    html = f"<!doctype html><html><head><title>IPv6 origin</title></head><body>{marker}</body></html>"
    (site / "index.html").write_text(html)
    origin = IPv6FileServer(("::1", 0), partial(SimpleHTTPRequestHandler, directory=str(site)))
    origin_thread = Thread(target=origin.serve_forever, daemon=True)
    origin_thread.start()
    target_url = f"http://[::1]:{origin.server_port}/index.html"

    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        listener.bind(("::1", 0))
        port = listener.getsockname()[1]
    server_url = f"http://[::1]:{port}"
    collection = tmp_path / "collection"
    collection.mkdir()
    env = cli_env(
        live=True,
        BIND_ADDR=f"[::1]:{port}",
        BASE_URL=server_url if pinned_base_url else "",
        SERVER_SECURITY_MODE="auto",
        PLUGINS="wget",
        SAVE_WGET="True",
        URL_ALLOWLIST=r"^http://\[::1\]:",
        NO_PROXY="::1,[::1],localhost,127.0.0.1",
        no_proxy="::1,[::1],localhost,127.0.0.1",
    )
    process = None
    session = requests.Session()
    session.trust_env = False
    try:
        initialized = run_archivebox_cmd(["init", "--quick"], cwd=collection, env=env)
        assert initialized.returncode == 0, initialized.stderr or initialized.stdout
        token = create_admin_and_token(collection)

        def start_server(log_name):
            with (collection / log_name).open("w") as log:
                server = run_archivebox_cmd(
                    ["server"],
                    cwd=collection,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    wait=False,
                    start_new_session=True,
                )
            wait_for_log(collection / "logs/worker_uvicorn.log", "Uvicorn running on", timeout=30)
            return server

        process = start_server("server-first.log")
        health = session.get(server_url + "/health/", timeout=10)
        assert health.status_code == 200, health.text
        assert health.headers["X-ArchiveBox-Health"] == "OK"
        login = session.get(server_url + "/admin/login/", timeout=10)
        assert login.status_code == 200, login.text
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.text)
        assert csrf, login.text
        authenticated = session.post(
            server_url + "/admin/login/",
            data={"username": "apitestadmin", "password": "testpass123", "csrfmiddlewaretoken": csrf[1], "next": "/admin/"},
            headers={"Referer": server_url + "/admin/login/", "Origin": server_url},
            allow_redirects=False,
            timeout=10,
        )
        assert authenticated.status_code == 302, authenticated.text
        admin_url = urljoin(server_url, authenticated.headers["Location"])
        assert urlsplit(admin_url).netloc == f"[::1]:{port}"
        admin = session.get(admin_url, timeout=10)
        assert admin.status_code == 200, admin.text
        assert 'name="password"' not in admin.text

        headers = {"X-ArchiveBox-API-Key": token}
        queued = session.post(
            server_url + "/api/v1/cli/add",
            headers=headers,
            json={"urls": [target_url], "plugins": "wget", "parser": "url_list", "index_only": True, "tag": "ipv6"},
            timeout=10,
        )
        assert queued.status_code == 200, queued.text
        assert queued.json()["success"] is True
        crawl_id = queued.json()["result"]["crawl_id"]
        stop_archivebox_process(process)
        process = None
        captured = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=collection, env=env, timeout=90)
        assert captured.returncode == 0, captured.stderr or captured.stdout
        with use_archivebox_db(collection):
            snapshot = Snapshot.objects.get(crawl_id=crawl_id, url=target_url)
            assert snapshot.status == Snapshot.StatusChoices.SEALED
            result = ArchiveResult.objects.get(snapshot=snapshot, plugin="wget")
            assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
            snapshot_id = str(snapshot.id)
            plugin_dir = Path(result.pwd)
            assert plugin_dir.is_relative_to(collection)
            matching_files = [path for path in plugin_dir.rglob("*.html") if marker in path.read_text()]
            assert len(matching_files) == 1
            relative_output = matching_files[0].relative_to(plugin_dir.parent).as_posix()
            saved_bytes = matching_files[0].read_bytes()

        # Starting again must not accept a stale readiness line from the first server.
        (collection / "logs/worker_uvicorn.log").unlink()
        process = start_server("server-second.log")
        found = session.get(server_url + "/api/v1/core/snapshots", headers=headers, params={"crawl_id": crawl_id}, timeout=10)
        assert found.status_code == 200, found.text
        assert found.json()["count"] == 1
        assert found.json()["items"][0]["url"] == target_url
        assert found.json()["items"][0]["status"] == "sealed"
        details = session.get(server_url + f"/archive/{snapshot_id}", allow_redirects=False, timeout=10)
        assert details.status_code == 302, details.text
        detail_url = urljoin(server_url, details.headers["Location"])
        assert urlsplit(detail_url).netloc == f"[::1]:{port}"
        page = session.get(detail_url, timeout=10)
        assert page.status_code == 200, page.text
        assert target_url in page.text
        replay = session.get(server_url + f"/snapshot/{snapshot_id}/{quote(relative_output)}?raw=1", timeout=10)
        assert replay.status_code == 200, replay.text
        assert replay.content == saved_bytes
    finally:
        if process is not None:
            stop_archivebox_process(process)
        session.close()
        kill_processes_for_data_dir(collection)
        origin.shutdown()
        origin.server_close()
        origin_thread.join(timeout=5)
