"""Scoped IPv6 listeners must survive Supervisor and Django's autoreloader."""

import socket
import subprocess

import psutil
import pytest
import requests

from archivebox.tests.conftest import (
    cli_env,
    kill_processes_for_data_dir,
    run_archivebox_cmd,
    stop_archivebox_process,
    wait_for_log,
)


def test_named_scope_is_normalized_to_local_interface_index():
    from archivebox.cli.archivebox_server import _parse_and_validate_bind_spec

    index, name = socket.if_nameindex()[0]
    # Linux getaddrinfo rejects named zones on loopback/global addresses;
    # numeric scope IDs work consistently for all scoped IPv6 literals.
    assert _parse_and_validate_bind_spec(f"[::1%{name}]:5797") == (f"[::1%{index}]", "5797")


@pytest.mark.timeout(120)
@pytest.mark.parametrize("flags", [[], ["--debug"], ["--reload"]])
@pytest.mark.parametrize("numeric_scope", [False, True])
def test_server_binds_scoped_ipv6(initialized_archive, flags, numeric_scope):
    addresses = psutil.net_if_addrs()
    interface_index, interface_name = next(
        (index, name)
        for index, name in socket.if_nameindex()
        if any(address.family == socket.AF_INET6 and address.address.split("%", 1)[0] == "::1" for address in addresses.get(name, []))
    )
    scope = str(interface_index) if numeric_scope else interface_name
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        listener.bind(("::1", 0))
        port = listener.getsockname()[1]
    bind_addr = f"[::1%{scope}]:{port}"
    env = cli_env(live=True, BASE_URL="", BIND_ADDR=bind_addr)
    log_path = initialized_archive / "server-scoped-ipv6.log"
    with log_path.open("w") as log:
        process = run_archivebox_cmd(
            ["server", *flags],
            cwd=initialized_archive,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            wait=False,
            start_new_session=True,
        )
    try:
        if flags:
            worker_log = initialized_archive / "logs/worker_runserver.log"
            wait_for_log(worker_log, "Listening on TCP", timeout=30)
            assert f"[::1%{interface_index}]:{port}" in worker_log.read_text()
            if "--reload" in flags:
                reloaded_workers = [
                    child
                    for child in psutil.Process(process.pid).children(recursive=True)
                    if "runserver" in child.cmdline() and child.environ().get("RUN_MAIN") == "true"
                ]
                assert len(reloaded_workers) == 1
                assert reloaded_workers[0].environ()["ARCHIVEBOX_RUNSERVER_BIND_URL"] == f"http://[::1%{interface_index}]:{port}"
        else:
            wait_for_log(initialized_archive / "logs/worker_uvicorn.log", "Uvicorn running on", timeout=30)
        with requests.Session() as session:
            session.trust_env = False
            # The scope selects the listener's interface. A remote HTTP Host
            # never needs the server's local interface identifier.
            response = session.get(f"http://[::1]:{port}/health/", timeout=5)
        assert response.status_code == 200, response.text
        assert response.headers["X-ArchiveBox-Health"] == "OK"
        assert process.poll() is None, log_path.read_text()
    finally:
        stop_archivebox_process(process)
        kill_processes_for_data_dir(initialized_archive)
