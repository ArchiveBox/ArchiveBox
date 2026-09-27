"""Exercise the real agent wrapper with Chromium's native storage failures."""

import asyncio

import pytest
import requests

from .conftest import start_archivebox_server, stop_archivebox_process
from .test_opencode_agent_1 import _set_archivebox_config
from .test_opencode_agent_1 import installed_opencode as installed_opencode
from .test_opencode_agent_1 import live_opencode as live_opencode
from .test_opencode_agent_1 import opencode_archive_config as opencode_archive_config
from .test_server_security_browser import browser_runtime as browser_runtime


from .test_opencode_browser_1 import (
    pytestmark as pytestmark,
    agent_server as agent_server,
    _login_cookie as _login_cookie,
)


@pytest.mark.parametrize(
    "mode,proxy_whitelist,use_cookie,http_status",
    [
        ("unsafe-onedomain-noadmin", "", True, 403),
        ("safe-onedomain-nojsreplay", "127.0.0.1/32", False, 200),
        ("safe-onedomain-nojsreplay", "192.0.2.0/24", False, 302),
    ],
)
def test_agent_websocket_matches_http_security_policy(agent_server, live_opencode, mode, proxy_whitelist, use_cookie, http_status):
    from urllib.parse import urlsplit
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    server_url, data_dir, process = agent_server
    cookie = _login_cookie(server_url)
    created = requests.post(
        server_url + "/admin/agent/opencode/pty",
        headers={"Cookie": cookie, "Origin": server_url},
        json={"command": "/bin/sh", "args": []},
        timeout=10,
    )
    assert created.status_code == 200
    pty_id = created.json()["id"]
    stop_archivebox_process(process)
    _set_archivebox_config(
        data_dir,
        f"SERVER_SECURITY_MODE={mode}",
        f"REVERSE_PROXY_WHITELIST={proxy_whitelist}",
        "REVERSE_PROXY_USER_HEADER=Remote-User",
    )
    restarted = start_archivebox_server(
        data_dir,
        port=urlsplit(server_url).port,
        env=live_opencode.config.env,
        log_name="agent-security-server.log",
    )
    headers = {"Cookie": cookie} if use_cookie else {"Remote-User": "agent-browser-test"}
    try:
        response = requests.get(server_url + "/admin/agent/opencode/global/health", headers=headers, allow_redirects=False, timeout=10)
        assert response.status_code == http_status

        async def check_socket():
            connection = connect(
                server_url.replace("http", "ws", 1) + f"/admin/agent/opencode/pty/{pty_id}/connect",
                origin=server_url,
                additional_headers=headers,
                proxy=None,
            )
            if http_status != 200:
                with pytest.raises(InvalidStatus) as error:
                    async with connection:
                        pytest.fail("Disabled control plane or untrusted proxy accepted a WebSocket")
                assert error.value.response.status_code == 403
                return
            async with connection as socket, asyncio.timeout(10):
                await socket.send("printf 'ABX_%s\\n' PROXY_OK\n")
                output = ""
                while "ABX_PROXY_OK" not in output:
                    chunk = await socket.recv()
                    output += chunk.decode() if isinstance(chunk, bytes) else chunk
                assert "ABX_PROXY_OK" in output

        asyncio.run(check_socket())
        assert requests.get(server_url + "/health/", timeout=10).status_code == 200
    finally:
        deleted = requests.delete(live_opencode.settings["origin"] + f"/pty/{pty_id}", timeout=10)
        assert deleted.status_code == 200
        stop_archivebox_process(restarted)
