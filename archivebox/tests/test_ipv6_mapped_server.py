"""Mapped IPv6 bind literals retain ordinary IPv4 listener semantics."""

import socket
import subprocess

import pytest
import requests

from archivebox.tests.conftest import (
    cli_env,
    kill_processes_for_data_dir,
    run_archivebox_cmd,
    stop_archivebox_process,
    wait_for_log,
)


@pytest.mark.timeout(90)
@pytest.mark.parametrize("bind_host", ["::ffff:127.0.0.1", "::ffff:7f00:1"])
def test_server_normalizes_mapped_ipv6_bind_to_ipv4(initialized_archive, bind_host):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = cli_env(live=True, BASE_URL="", BIND_ADDR=f"[{bind_host}]:{port}")
    log_path = initialized_archive / "server-mapped-ipv6.log"
    with log_path.open("w") as log:
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
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(f"http://127.0.0.1:{port}/health/", timeout=5)
        assert response.status_code == 200, response.text
        assert response.headers["X-ArchiveBox-Health"] == "OK"
        assert response.content.strip() == b"OK"
        assert f"http://127.0.0.1:{port}" in log_path.read_text()
        assert process.poll() is None
    finally:
        stop_archivebox_process(process)
        kill_processes_for_data_dir(initialized_archive)
