import asyncio
import os
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import requests
from asgiref.testing import ApplicationCommunicator

from archivebox.tests.conftest import ADMIN_TEST_HOST, run_archivebox_cmd
from archivebox.config.common import get_config


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
    from abx_plugins.plugins.opencode import runtime

    install = run_archivebox_cmd(
        ["install", "opencode", "--binproviders=env,pnpm"],
        cwd=opencode_archive_config.data_dir,
        env=opencode_archive_config.env,
        timeout=1200,
    )
    assert install.returncode == 0, install.stderr or install.stdout
    _reset_runtime_config()

    config = get_config().model_dump(mode="json")
    settings = runtime._settings(config, opencode_archive_config.data_dir)
    settings["archivebox_base_url"] = "http://admin.archivebox.localhost:8000"
    settings["archivebox_admin_url"] = "http://admin.archivebox.localhost:8000/admin"
    settings["archivebox_api_url"] = "http://admin.archivebox.localhost:8000/api/"
    binary, binary_env = runtime._resolve_binary(settings["binary"], settings["config"])
    version = binary.exec(
        cmd=("--version",),
        env={**os.environ, **binary_env},
        timeout=120,
    )
    assert version.returncode == 0, version.stderr or version.stdout
    ok, error = runtime._ensure_opencode(settings)
    assert ok, error

    process = runtime._PROCESS
    assert process is not None
    try:
        yield SimpleNamespace(config=opencode_archive_config, settings=settings, process=process)
    finally:
        runtime._stop_owned_process()


def test_opencode_disabled_route_does_not_start_server(client, initialized_archive):
    from archivebox.machine.models import Machine
    from abx_plugins.plugins.opencode import runtime

    os.chdir(initialized_archive)
    Machine.from_json({"config": {"OPENCODE_ENABLED": False}})
    _reset_runtime_config()
    assert get_config().model_dump(mode="json")["OPENCODE_ENABLED"] is False

    response = client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 404
    assert runtime._PROCESS is None or runtime._PROCESS.poll() is not None


def test_opencode_disabled_via_cli_stays_disabled(admin_client, initialized_archive):
    _set_archivebox_config(initialized_archive, "OPENCODE_ENABLED=False")

    assert get_config().OPENCODE_ENABLED is False
    assert admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST).status_code == 404
    for path in ("/add/", "/admin/core/snapshot/"):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert b'href="/admin/agent"' not in response.content


def test_opencode_agent_requires_superuser_when_enabled(client, db, django_user_model, live_opencode):
    response = client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert "/admin/login/" in response.headers["Location"]

    next_path = "/admin/agent?x=1&next=https://example.com"
    response = client.get(next_path, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.headers["Location"]).query) == {"next": [next_path]}

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
    from abx_plugins.plugins.opencode import runtime

    response = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    recent_session_id = response.context["recent_session_id"]
    session_path = runtime._project_route(live_opencode.config.data_dir, recent_session_id)

    assert response.status_code == 200
    assert recent_session_id
    assert f'<iframe src="{session_path}"'.encode() in response.content
    assert b'id="header"' in response.content
    assert b'id="progress-monitor"' in response.content
    assert response.context["proxy_prefix"] == runtime._PROXY_PREFIX
    assert b"/_archivebox/health" not in response.content
    assert b"window.setInterval(check, 3000)" not in response.content
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
    assert project.json()["id"] == "global"
    assert not project.json().get("vcs")

    path = admin_client.get(
        f"/admin/agent/opencode/path?directory={encoded_workdir}",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert path.status_code == 200
    assert path.json()["directory"] == workdir

    sessions = admin_client.get(
        f"/admin/agent/opencode/session?directory={encoded_workdir}&roots=true&limit=55",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert sessions.status_code == 200
    assert any(session["id"] == agent.context["recent_session_id"] and session["directory"] == workdir for session in sessions.json())
    assert not (Path(workdir) / ".git").exists()


def test_opencode_proxy_restarts_server_for_an_existing_agent_page(admin_client, live_opencode):
    from abx_plugins.plugins.opencode import runtime

    old_process = runtime._PROCESS
    runtime._stop_owned_process()

    response = admin_client.get(
        "/admin/agent/opencode/global/health",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )

    assert response.status_code == 200
    assert runtime._PROCESS is not None
    assert runtime._PROCESS is not old_process
    assert runtime._PROCESS.poll() is None


def test_concurrent_opencode_startup_waits_until_server_is_ready(live_opencode):
    from abx_plugins.plugins.opencode import runtime

    runtime._stop_owned_process()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(runtime._ensure_opencode, [live_opencode.settings] * 2))

    assert results == [(True, ""), (True, "")]
    assert runtime._health(live_opencode.settings)


def test_opencode_does_not_probe_or_replace_a_ready_owned_process(live_opencode):
    from abx_plugins.plugins.opencode import runtime

    process = runtime._PROCESS
    settings = {**live_opencode.settings, "port": _free_port()}
    settings["origin"] = f"http://{settings['host']}:{settings['port']}"

    ok, error = runtime._ensure_opencode(settings)

    assert ok, error
    assert process is not None
    assert runtime._PROCESS is process
    assert process.poll() is None


def test_opencode_proxy_does_not_wait_for_recovery_lock(admin_client, live_opencode):
    from abx_plugins.plugins.opencode import runtime

    workdir = quote(str(live_opencode.config.data_dir.resolve()))
    assert runtime._owned_process_ready()
    executor = ThreadPoolExecutor(max_workers=1)
    runtime._PROCESS_LOCK.acquire()
    try:
        request = executor.submit(
            admin_client.get,
            f"/admin/agent/opencode/path?directory={workdir}",
            HTTP_HOST=ADMIN_TEST_HOST,
            HTTP_SEC_FETCH_SITE="same-origin",
        )
        response = request.result(timeout=5)
    finally:
        runtime._PROCESS_LOCK.release()
        executor.shutdown(wait=True)

    assert response.status_code == 200
    assert str(live_opencode.config.data_dir.resolve()).encode() in response.content


def test_opencode_proxy_waits_for_owned_process_readiness(admin_client, live_opencode):
    from abx_plugins.plugins.opencode import runtime

    process = runtime._PROCESS
    assert process is not None
    runtime._PROCESS_READY = None
    workdir = quote(str(live_opencode.config.data_dir.resolve()))

    response = admin_client.get(
        f"/admin/agent/opencode/path?directory={workdir}",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )

    assert response.status_code == 200
    assert runtime._PROCESS is process
    assert runtime._PROCESS_READY is process


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
    from abx_plugins.plugins.opencode import runtime
    from django.conf import settings as django_settings

    owned_process = runtime._PROCESS
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
        runtime._PROCESS_LOCK.acquire()
        runtime._PROCESS = None
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
                runtime._PROCESS = owned_process
                runtime._PROCESS_LOCK.release()
                await asyncio.get_running_loop().shutdown_default_executor()

    asyncio.run(request_event_stream())
    assert runtime._PROCESS is owned_process
    assert owned_process.poll() is None


def test_opencode_starts_with_isolated_state(admin_client, live_opencode):
    workdir = str(live_opencode.config.data_dir.resolve())
    state_dir = live_opencode.config.state_dir

    assert not (Path(workdir) / ".git").exists()
    agent = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert agent.status_code == 200
    assert agent.context["recent_session_id"]
    assert not (Path(workdir) / ".git").exists()

    project = requests.get(
        f"{live_opencode.settings['origin']}/project/current",
        params={"directory": workdir},
        timeout=live_opencode.settings["timeout"],
    )
    project.raise_for_status()

    config = requests.get(
        f"{live_opencode.settings['origin']}/global/config",
        timeout=live_opencode.settings["timeout"],
    )
    config.raise_for_status()

    assert Path(live_opencode.settings["workdir"]).resolve() == Path(workdir)
    assert project.json()["id"] == "global"
    assert not project.json().get("vcs")
    assert config.json()["model"] == "opencode/big-pickle"
    assert config.json()["snapshot"] is False
    assert live_opencode.process.poll() is None
    path = requests.get(
        f"{live_opencode.settings['origin']}/path",
        params={"directory": workdir},
        timeout=live_opencode.settings["timeout"],
    )
    path.raise_for_status()
    assert Path(path.json()["directory"]).resolve() == Path(workdir)

    diff = requests.get(
        f"{live_opencode.settings['origin']}/vcs/diff",
        params={"directory": workdir, "mode": "git"},
        timeout=5,
    )
    diff.raise_for_status()
    assert diff.json() == []
    assert (state_dir / "data" / "opencode" / "opencode.db").is_file()
    assert (state_dir / "SKILL.md").is_file()
    assert (state_dir / "config" / "opencode" / "skills" / "archivebox" / "SKILL.md").resolve() == state_dir / "SKILL.md"


def test_opencode_invalid_state_does_not_break_archivebox(admin_client, live_opencode):
    from abx_plugins.plugins.opencode import runtime

    runtime._stop_owned_process()
    invalid_state = live_opencode.config.state_dir / "config"
    invalid_state.rename(live_opencode.config.state_dir / "saved-config")
    invalid_state.write_text("Preserve this file.")

    for url in ("/admin/agent", "/admin/agent/opencode/global/health"):
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 503
        assert str(invalid_state).encode() not in response.content

    stream = admin_client.get("/admin/agent/opencode/global/event", HTTP_HOST=ADMIN_TEST_HOST)
    assert stream.status_code == 200

    async def read_failure():
        return b"".join([chunk async for chunk in stream.streaming_content])

    assert asyncio.run(read_failure()) == b'event: error\ndata: {"error":"OpenCode unavailable"}\n\n'

    for url in ("/health/", "/add/", "/admin/core/snapshot/"):
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
    assert invalid_state.read_text() == "Preserve this file."


@pytest.mark.parametrize(
    ("damaged_file", "missing"),
    [
        ("runtime.py", True),
        ("templates/agent.html", True),
        ("templates/agent.html", False),
        ("templates/navigation.html", False),
        ("templates/add.html", False),
    ],
)
def test_opencode_incomplete_install_does_not_break_archivebox(live_opencode, tmp_path, damaged_file, missing):
    import abx_plugins

    # Exercise a genuinely incomplete installation in a separate process;
    # never alter the shared package or intercept Python imports.
    site = tmp_path / "site"
    installed = site / "abx_plugins"
    shutil.copytree(Path(abx_plugins.__file__).parent, installed, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    damaged_path = installed / "plugins" / "opencode" / damaged_file
    if missing:
        damaged_path.unlink()
    else:
        damaged_path.write_text("{% invalid_template_tag %}")
    expected_status = 200 if damaged_file in {"templates/navigation.html", "templates/add.html"} else 503
    script = f"""
import sys
from pathlib import Path
import abx_plugins
from django.test import Client
from django.contrib.auth import get_user_model
assert Path(abx_plugins.__file__).is_relative_to({str(site)!r})
user = get_user_model().objects.create_superuser(username='optional-service-test')
client = Client(HTTP_HOST={ADMIN_TEST_HOST!r})
client.force_login(user)
for path in ('/health/', '/add/', '/admin/core/snapshot/'):
    assert client.get(path).status_code == 200, path
assert 'abx_plugins.plugins.opencode.runtime' not in sys.modules
response = client.get('/admin/agent')
assert response.status_code == {expected_status}, response.status_code
if response.status_code == 503:
    assert response.content == b'AI service unavailable. See server logs.'
for path in ('/health/', '/add/', '/admin/core/snapshot/'):
    assert client.get(path).status_code == 200, path
print('OPTIONAL_SERVICE_FAILURE_ISOLATED')
"""
    result = run_archivebox_cmd(
        ["shell", "-c", script],
        cwd=live_opencode.config.data_dir,
        env={**live_opencode.config.env, "PYTHONPATH": str(site)},
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "OPTIONAL_SERVICE_FAILURE_ISOLATED" in result.stdout
