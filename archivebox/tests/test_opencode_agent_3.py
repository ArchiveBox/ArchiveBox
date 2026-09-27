import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST


from .test_opencode_agent_1 import (
    pytestmark as pytestmark,
    _free_port as _free_port,
    _reset_runtime_config as _reset_runtime_config,
    _set_archivebox_config as _set_archivebox_config,
    opencode_archive_config as opencode_archive_config,
    installed_opencode as installed_opencode,
    live_opencode as live_opencode,
)


def test_opencode_proxy_blocks_cross_origin_mutation(admin_client, db, live_opencode):
    response = admin_client.post(
        "/admin/agent/opencode/session",
        data=b"{}",
        content_type="application/json",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_ORIGIN="https://evil.example",
    )

    assert response.status_code == 403


def test_opencode_cold_agent_wrapper_returns_before_server_starts(admin_client, installed_opencode):
    import time

    from abx_plugins.plugins.opencode import runtime

    assert not runtime._owned_process_running()
    started = time.monotonic()
    response = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert time.monotonic() - started < 3
    assert not runtime._owned_process_running()
    assert b'id="opencode-agent-welcome"' in response.content
    assert f'<iframe src="{runtime._project_route(installed_opencode.config.data_dir)}"'.encode() in response.content


def test_opencode_proxy_serves_real_project_and_session(admin_client, live_opencode):
    workdir = str(live_opencode.config.data_dir.resolve())
    encoded_workdir = quote(workdir)

    agent = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert agent.status_code == 200
    from abx_plugins.plugins.opencode import runtime

    frame_path = runtime._project_route(live_opencode.config.data_dir)
    frame = admin_client.get(frame_path, HTTP_HOST=ADMIN_TEST_HOST)
    assert frame.status_code == 302
    session_id = frame.headers["Location"].rsplit("/", 1)[-1]

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
    assert any(session["id"] == session_id and session["directory"] == workdir for session in sessions.json())
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


@pytest.mark.parametrize("path", ["event", "global/event"])
def test_opencode_proxy_sse_delivers_first_event_immediately(admin_client, live_opencode, path):
    from abx_plugins.plugins.opencode import runtime

    # The real /event endpoint emits heartbeats indefinitely. A bounded
    # upstream read exposes accidental buffering without hanging the test.
    status, headers, body = runtime.proxy(
        {**live_opencode.settings, "timeout": 1},
        "GET",
        path,
        (),
        {},
        b"",
    )
    assert status == 200
    assert not isinstance(body, bytes)
    assert headers["Content-Type"] == "text/event-stream"
    asyncio.run(body.aclose())
    response = admin_client.get(
        f"/admin/agent/opencode/{path}",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert response.status_code == 200

    async def first_event():
        stream = response.streaming_content
        try:
            async with asyncio.timeout(2):
                return await anext(stream)
        finally:
            await stream.aclose()

    assert b"server.connected" in asyncio.run(first_event())
