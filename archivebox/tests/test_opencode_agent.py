import asyncio
import os
import signal
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import requests
from asgiref.testing import ApplicationCommunicator

from archivebox.tests.conftest import ADMIN_TEST_HOST, run_archivebox_cmd


pytestmark = pytest.mark.django_db(transaction=True)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _reset_runtime_config() -> None:
    from archivebox.config import common
    from archivebox.machine.models import Machine

    for value in vars(common).values():
        cache_clear = getattr(value, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()
    Machine.current(refresh=True)


def _set_archivebox_config(data_dir: Path, *values: str, env: dict[str, str] | None = None) -> None:
    os.chdir(data_dir)
    result = run_archivebox_cmd(
        ["config", "--set", *values],
        cwd=data_dir,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    _reset_runtime_config()


@pytest.fixture
def opencode_archive_config(initialized_archive):
    port = _free_port()
    state_dir = initialized_archive / "opencode"
    env = os.environ.copy()
    env.update(
        {
            "ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS": "true",
            "OPENCODE_ENABLED": "True",
            "OPENCODE_HOST": "127.0.0.1",
            "OPENCODE_PORT": str(port),
            "OPENCODE_WORKDIR": str(initialized_archive),
            "OPENCODE_STATE_DIR": str(state_dir),
            "OPENCODE_TIMEOUT": "60",
        },
    )
    _set_archivebox_config(
        initialized_archive,
        "OPENCODE_ENABLED=True",
        "OPENCODE_HOST=127.0.0.1",
        f"OPENCODE_PORT={port}",
        f"OPENCODE_WORKDIR={initialized_archive}",
        f"OPENCODE_STATE_DIR={state_dir}",
        "OPENCODE_TIMEOUT=60",
        env=env,
    )
    return SimpleNamespace(data_dir=initialized_archive, port=port, state_dir=state_dir, env=env)


@pytest.fixture
def live_opencode(opencode_archive_config):
    from archivebox.opencode import views

    install = run_archivebox_cmd(
        ["install", "opencode", "--binproviders=env,pnpm"],
        cwd=opencode_archive_config.data_dir,
        env=opencode_archive_config.env,
        timeout=1200,
    )
    assert install.returncode == 0, install.stderr or install.stdout
    _reset_runtime_config()

    config = views._machine_config()
    settings = views._settings(config)
    settings["archivebox_base_url"] = "http://admin.archivebox.localhost:8000"
    settings["archivebox_admin_url"] = "http://admin.archivebox.localhost:8000/admin"
    settings["archivebox_api_url"] = "http://admin.archivebox.localhost:8000/api/"
    binary, _, binary_env = views._resolve_binary(settings["binary"], settings["config"])
    version = binary.exec(
        cmd=("--version",),
        env={**os.environ, **binary_env},
        timeout=120,
    )
    assert version.returncode == 0, version.stderr or version.stdout
    ok, error = views._ensure_opencode(settings)
    assert ok, error

    process = views._PROCESS
    assert process is not None
    try:
        yield SimpleNamespace(config=opencode_archive_config, settings=settings, process=process)
    finally:
        views._stop_owned_process()


def test_opencode_disabled_route_does_not_start_server(client, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.opencode import views

    os.chdir(initialized_archive)
    Machine.from_json({"config": {"OPENCODE_ENABLED": False}})
    _reset_runtime_config()
    assert views._machine_config()["OPENCODE_ENABLED"] is False

    response = client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 404
    assert views._PROCESS is None or views._PROCESS.poll() is not None


def test_stop_owned_process_falls_back_for_stopped_process_without_dedicated_group():
    from archivebox.opencode import views

    process = subprocess.Popen(["sleep", "60"])
    try:
        process.send_signal(signal.SIGSTOP)
        views._stop_owned_process(process)
        assert process.returncode == -signal.SIGTERM
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_opencode_agent_requires_superuser_when_enabled(client, db, django_user_model, live_opencode):
    response = client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert "/admin/login/" in response.headers["Location"]

    user = django_user_model.objects.create_user(username="regular", password="testpassword")
    client.force_login(user)
    response = client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


def test_opencode_proxy_blocks_cross_origin_mutation(admin_client, db, live_opencode):
    response = admin_client.post(
        "/admin/agent/opencode/session",
        data=b"{}",
        content_type="application/json",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_ORIGIN="https://evil.example",
    )

    assert response.status_code == 403


def test_opencode_proxy_blocks_cross_site_fetch_metadata(admin_client, db, live_opencode):
    response = admin_client.post(
        "/admin/agent/opencode/session",
        data=b"{}",
        content_type="application/json",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="cross-site",
    )

    assert response.status_code == 403


def test_opencode_agent_superuser_gets_admin_wrapper(admin_client, live_opencode):
    from archivebox.opencode import views

    response = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    recent_session_id = response.context["recent_session_id"]
    session_path = views._project_route(live_opencode.config.data_dir, recent_session_id)

    assert response.status_code == 200
    assert recent_session_id
    assert f'<iframe src="{session_path}"'.encode() in response.content
    assert b'id="header"' in response.content
    assert b'id="progress-monitor"' in response.content
    assert response.context["proxy_prefix"] == views._PROXY_PREFIX
    assert response.context["opencode_version"]
    assert b"const healthUrl" in response.content
    assert b"/admin/agent/opencode/global/health" in response.content
    assert b"/admin/agent/opencode/_archivebox/health" in response.content
    assert b'redirect: "manual"' in response.content
    assert b"let waking = false" in response.content
    assert b"wake();" in response.content
    assert b"frame.contentWindow.location.reload()" in response.content
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"

    session = admin_client.get(
        session_path,
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert session.status_code == 200
    assert session.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert session.headers["Content-Security-Policy"] == "frame-ancestors 'self'"


def test_opencode_health_monitor_does_not_start_server(admin_client, live_opencode):
    from archivebox.opencode import views

    views._stop_owned_process()
    response = admin_client.get(
        "/admin/agent/opencode/_archivebox/health",
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 503
    assert response.json() == {"healthy": False, "version": ""}
    assert response.headers["Cache-Control"] == "no-store"
    assert views._PROCESS is None


def test_opencode_proxy_serves_real_project_and_session(admin_client, live_opencode):
    workdir = str(live_opencode.config.data_dir.resolve())
    encoded_workdir = quote(workdir)

    agent = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert agent.status_code == 200

    project = admin_client.get(
        f"/admin/agent/opencode/project/current?directory={encoded_workdir}",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert project.status_code == 200
    assert workdir.encode() in project.content

    path = admin_client.get(
        f"/admin/agent/opencode/path?directory={encoded_workdir}",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert path.status_code == 200
    assert workdir.encode() in path.content

    sessions = admin_client.get(
        f"/admin/agent/opencode/session?directory={encoded_workdir}&roots=true&limit=55",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert sessions.status_code == 200
    assert b"id" in sessions.content


def test_opencode_proxy_restarts_server_for_an_existing_agent_page(admin_client, live_opencode):
    from archivebox.opencode import views

    old_process = views._PROCESS
    views._stop_owned_process()

    response = admin_client.get(
        "/admin/agent/opencode/global/health",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )

    assert response.status_code == 200
    assert views._PROCESS is not None
    assert views._PROCESS is not old_process
    assert views._PROCESS.poll() is None


def test_concurrent_opencode_startup_waits_until_server_is_ready(live_opencode):
    from archivebox.opencode import views

    views._stop_owned_process()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(views._ensure_opencode, [live_opencode.settings] * 2))

    assert results == [(True, ""), (True, "")]
    assert views._health(live_opencode.settings)


def test_opencode_does_not_probe_or_replace_a_ready_owned_process(live_opencode):
    from archivebox.opencode import views

    process = views._PROCESS
    settings = {**live_opencode.settings, "port": _free_port()}
    settings["origin"] = f"http://{settings['host']}:{settings['port']}"

    ok, error = views._ensure_opencode(settings)

    assert ok, error
    assert process is not None
    assert views._PROCESS is process
    assert process.poll() is None


def test_opencode_proxy_does_not_wait_for_recovery_lock(admin_client, live_opencode):
    from archivebox.opencode import views

    workdir = quote(str(live_opencode.config.data_dir.resolve()))
    assert views._owned_process_ready()
    executor = ThreadPoolExecutor(max_workers=1)
    views._PROCESS_LOCK.acquire()
    try:
        request = executor.submit(
            admin_client.get,
            f"/admin/agent/opencode/path?directory={workdir}",
            HTTP_HOST=ADMIN_TEST_HOST,
            HTTP_SEC_FETCH_SITE="same-origin",
        )
        response = request.result(timeout=5)
    finally:
        views._PROCESS_LOCK.release()
        executor.shutdown(wait=True)

    assert response.status_code == 200
    assert str(live_opencode.config.data_dir.resolve()).encode() in response.content


def test_opencode_proxy_waits_for_owned_process_readiness(admin_client, live_opencode):
    from archivebox.opencode import views

    process = views._PROCESS
    assert process is not None
    views._PROCESS_READY = None
    workdir = quote(str(live_opencode.config.data_dir.resolve()))

    response = admin_client.get(
        f"/admin/agent/opencode/path?directory={workdir}",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )

    assert response.status_code == 200
    assert views._PROCESS is process
    assert views._PROCESS_READY is process


def test_opencode_proxy_sse_response_is_unbuffered(admin_client, live_opencode):
    response = admin_client.get(
        "/admin/agent/opencode/global/event",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )

    assert response.status_code == 200
    assert response.streaming
    assert response.is_async
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["Cache-Control"] == "no-store"


def test_opencode_proxy_sse_returns_headers_before_restart_finishes(admin_client, live_opencode):
    from archivebox.core.asgi import application
    from archivebox.opencode import views
    from django.conf import settings as django_settings

    owned_process = views._PROCESS
    assert owned_process is not None
    session_cookie_name = django_settings.SESSION_COOKIE_NAME
    session_cookie = admin_client.cookies[session_cookie_name].value
    path = "/admin/agent/opencode/global/event"

    async def request_event_stream():
        communicator = ApplicationCommunicator(
            application,
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [
                    (b"host", ADMIN_TEST_HOST.encode()),
                    (b"cookie", f"{session_cookie_name}={session_cookie}".encode()),
                    (b"sec-fetch-site", b"same-origin"),
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 8000),
            },
        )
        views._PROCESS_LOCK.acquire()
        views._PROCESS = None
        try:
            await communicator.send_input({"type": "http.request", "body": b"", "more_body": False})
            response_start = await communicator.receive_output(timeout=2)
            assert response_start["type"] == "http.response.start"
            assert response_start["status"] == 200
        finally:
            try:
                await communicator.send_input({"type": "http.disconnect"})
                await communicator.wait(timeout=5)
            finally:
                views._PROCESS = owned_process
                views._PROCESS_LOCK.release()
                await asyncio.get_running_loop().shutdown_default_executor()

    asyncio.run(request_event_stream())
    assert views._PROCESS is owned_process
    assert owned_process.poll() is None


def test_opencode_starts_with_isolated_state(live_opencode):
    workdir = str(live_opencode.config.data_dir.resolve())
    state_dir = live_opencode.config.state_dir

    project = requests.get(
        f"{live_opencode.settings['origin']}/project/current",
        params={"directory": workdir},
        timeout=live_opencode.settings["timeout"],
    )
    project.raise_for_status()

    assert Path(live_opencode.settings["workdir"]).resolve() == Path(workdir)
    assert Path(str(project.json()["worktree"])).resolve() == Path(workdir)
    assert live_opencode.process.poll() is None
    assert (live_opencode.config.data_dir / ".git").is_dir()
    assert (state_dir / "data" / "opencode" / "opencode.db").is_file()
    assert (state_dir / "SKILL.md").is_file()
    assert (state_dir / "config" / "opencode" / "skills" / "archivebox" / "SKILL.md").resolve() == state_dir / "SKILL.md"


def test_opencode_state_dir_is_separate_from_workdir(tmp_path):
    from archivebox.opencode import views

    workdir = tmp_path / "workdir"
    state_dir = tmp_path / "state"
    settings = views._settings(
        {
            "OPENCODE_WORKDIR": str(workdir),
            "OPENCODE_STATE_DIR": str(state_dir),
        },
    )
    views._ensure_project_files(settings)

    assert settings["workdir"] == workdir
    assert settings["opencode_dir"] == state_dir
    assert settings["config_home"] == state_dir / "config"
    assert settings["data_home"] == state_dir / "data"
    assert settings["state_home"] == state_dir / "state"
    editable_skill = state_dir / "SKILL.md"
    loaded_skill = state_dir / "config" / "opencode" / "skills" / "archivebox" / "SKILL.md"
    assert editable_skill.exists()
    assert loaded_skill.is_symlink()
    assert loaded_skill.resolve() == editable_skill.resolve()
    assert f"ArchiveBox collection directory: {settings['archivebox_data_dir']}" in editable_skill.read_text()


def test_opencode_default_workdir_does_not_scan_the_collection():
    from archivebox.opencode import views

    settings = views._settings({})

    assert settings["opencode_dir"] == settings["archivebox_data_dir"] / "opencode"
    assert settings["workdir"] == settings["opencode_dir"] / "workdir"
    assert settings["timeout"] == 120


def test_opencode_rewrites_vite_preload_assets():
    from archivebox.opencode import views

    body = b'const BL="modulepreload",UL=function(t){return"/"+t};const icon="/assets/sprite.svg#anthropic"'
    rewritten = views._rewrite_text(body, {"origin": "http://127.0.0.1:4096"}).decode()

    assert 'return"/"+t' not in rewritten
    assert 'return"/admin/agent/opencode/"+t' in rewritten
    assert '"/admin/agent/opencode/assets/sprite.svg#anthropic"' in rewritten
