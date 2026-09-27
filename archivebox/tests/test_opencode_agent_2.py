import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from asgiref.testing import ApplicationCommunicator

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.config.common import get_config


from .test_opencode_agent_1 import (
    pytestmark as pytestmark,
    _free_port as _free_port,
    _reset_runtime_config as _reset_runtime_config,
    _set_archivebox_config as _set_archivebox_config,
    opencode_archive_config as opencode_archive_config,
    installed_opencode as installed_opencode,
    live_opencode as live_opencode,
)


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


def test_opencode_agent_superuser_gets_admin_wrapper(admin_client, live_opencode):
    from abx_plugins.plugins.opencode import runtime

    response = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    frame_path = runtime._project_route(live_opencode.config.data_dir)

    assert response.status_code == 200
    assert f'<iframe src="{frame_path}"'.encode() in response.content
    assert b'id="opencode-agent-welcome"' in response.content
    assert b'id="header"' in response.content
    assert b'id="progress-monitor"' in response.content
    assert b'<a href="/admin/agent" class="navbar-item navbar-ai">' in response.content
    add_page = admin_client.get("/add/", HTTP_HOST=ADMIN_TEST_HOST)
    assert add_page.status_code == 200
    assert '<a href="/admin/agent">💬 Crawl with AI</a>'.encode() in add_page.content
    assert response.context["proxy_prefix"] == runtime._PROXY_PREFIX
    assert b"/_archivebox/health" not in response.content
    assert b"window.setInterval(check, 3000)" not in response.content
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"

    frame = admin_client.get(
        frame_path,
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert frame.status_code == 302
    assert frame.headers["Location"].startswith(frame_path + "/")
    session = admin_client.get(
        frame.headers["Location"],
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )
    assert session.status_code == 200
    assert session.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert session.headers["Content-Security-Policy"] == "frame-ancestors 'self'"


def test_opencode_oauth_callback_waits_for_user_and_preserves_cancellation(live_opencode):
    from abx_plugins.plugins.opencode import runtime

    settings = {**live_opencode.settings, "timeout": 1}
    headers = {"Content-Type": "application/json"}
    status, _, body = runtime.proxy(settings, "POST", "provider/openai/oauth/authorize", (), headers, b'{"method":0}')
    assert status == 200
    authorization = json.loads(body)
    assert urlsplit(authorization["url"]).hostname == "auth.openai.com"
    redirect = parse_qs(urlsplit(authorization["url"]).query)["redirect_uri"][0]
    callback_origin = urlsplit(redirect)
    assert callback_origin.hostname == "localhost"

    with ThreadPoolExecutor(max_workers=1) as executor:
        callback = executor.submit(runtime.proxy, settings, "POST", "provider/openai/oauth/callback", (), headers, b'{"method":0}')
        try:
            # A real pending authorization must outlive the ordinary API read
            # timeout. No tokens or substituted provider responses are used.
            with pytest.raises(FutureTimeoutError):
                callback.result(timeout=2)
        finally:
            cancelled = requests.get(f"{callback_origin.scheme}://{callback_origin.netloc}/cancel", timeout=5)
            assert cancelled.status_code == 200
            assert cancelled.text == "Login cancelled"
        status, response_headers, body = callback.result(timeout=5)
    assert status == 500
    assert response_headers["Content-Type"].startswith("application/json")
    error = json.loads(body)
    assert error["name"] == "UnknownError"
    assert error["data"]["ref"].startswith("err_")
    runtime._stop_owned_process()
    # The pnpm launcher can exit before its server child. Stopping the owned
    # process must release both listeners so another collection can authorize.
    with pytest.raises(requests.ConnectionError):
        requests.get(settings["origin"] + "/global/health", timeout=2)
    with pytest.raises(requests.ConnectionError):
        requests.get(f"{callback_origin.scheme}://{callback_origin.netloc}/cancel", timeout=2)


def test_opencode_static_assets_cache_privately_and_revalidate(admin_client, live_opencode):
    headers = {"HTTP_HOST": ADMIN_TEST_HOST, "HTTP_SEC_FETCH_SITE": "same-origin"}
    page = admin_client.get("/admin/agent/opencode/", **headers)
    assert page.status_code == 200
    asset = re.search(rb'src="(/admin/agent/opencode/assets/[^\"]+\.js)"', page.content)
    assert asset is not None
    path = asset[1].decode()
    response = admin_client.get(path, **headers)
    assert response.status_code == 200
    assert "private" in response.headers["Cache-Control"]
    assert "max-age=" in response.headers["Cache-Control"]
    assert b"/admin/agent/opencode" in response.content
    repeated = admin_client.get(path, HTTP_IF_NONE_MATCH=response.headers["ETag"], **headers)
    assert repeated.status_code == 304
    assert repeated.content == b""
    assert repeated.headers["ETag"] == response.headers["ETag"]
    assert admin_client.get("/admin/agent/opencode/path", **headers).headers["Cache-Control"] == "no-store"


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
                "server": ("127.0.0.1", 5797),
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


def test_opencode_invalid_state_does_not_break_archivebox(admin_client, live_opencode):
    from abx_plugins.plugins.opencode import runtime

    runtime._stop_owned_process()
    invalid_state = live_opencode.config.state_dir / "config"
    invalid_state.rename(live_opencode.config.state_dir / "saved-config")
    invalid_state.write_text("Preserve this file.")

    wrapper = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert wrapper.status_code == 200
    for url in (
        runtime._project_route(live_opencode.config.data_dir),
        "/admin/agent/opencode/global/health",
    ):
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
