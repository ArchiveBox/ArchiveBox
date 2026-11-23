"""Exercise automatic server addressing through real HTTP login pages."""

import re
import socket
from pathlib import Path

import requests

from .conftest import PORT_ALLOCATION_DIR, cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


def test_allocated_server_ports_avoid_kernel_ephemeral_ports():
    kernel_range = Path("/proc/sys/net/ipv4/ip_local_port_range")
    lower, upper = map(int, kernel_range.read_text().split()) if kernel_range.exists() else (49152, 65535)
    port = get_free_port()
    assert 16384 <= port <= 65535
    assert not lower <= port <= upper
    assert (PORT_ALLOCATION_DIR / str(port)).is_file()
    assert get_free_port() != port  # The session keeps a claim after closing its bind probe.

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen()
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            assert lower <= client.getsockname()[1] <= upper


def test_safe_single_domain_login_does_not_require_base_url(tmp_path):
    port = get_free_port()
    env = cli_env(
        disable_extractors=True,
        BASE_URL="",
        SERVER_SECURITY_MODE="safe-onedomain-nojsreplay",
        ADMIN_USERNAME="automatic-url-test",
        ADMIN_PASSWORD="Automatic-url-test-password-93!",
        ALLOWED_HOSTS="*",
    )
    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env, timeout=60)
    assert result.returncode == 0, result.stderr or result.stdout
    process = start_archivebox_server(tmp_path, port=port, env=env, daemonize=False, log_name="server.log")
    try:
        for hostname in ("localhost", "archivebox.localhost", "admin.archivebox.localhost", "192.168.1.20", "100.100.10.20"):
            session = requests.Session()
            response = session.get(
                f"http://127.0.0.1:{port}/admin/login/",
                headers={"Host": f"{hostname}:{port}"},
                timeout=15,
                allow_redirects=False,
            )
            assert response.status_code == 200, (hostname, response.status_code)
            assert 'name="password"' in response.text, hostname
            assert "base_url not set" not in response.text.lower(), hostname
            assert "archivebox-setup-wizard" not in response.text, hostname
            csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text)
            assert csrf, hostname
            login = session.post(
                f"http://127.0.0.1:{port}/admin/login/",
                headers={"Host": f"{hostname}:{port}"},
                data={
                    "username": env["ADMIN_USERNAME"],
                    "password": env["ADMIN_PASSWORD"],
                    "csrfmiddlewaretoken": csrf[1],
                    "next": "/admin/",
                },
                timeout=15,
                allow_redirects=False,
            )
            assert login.status_code == 302, (hostname, login.status_code)
            admin = session.get(
                f"http://127.0.0.1:{port}/admin/",
                headers={"Host": f"{hostname}:{port}"},
                timeout=15,
                allow_redirects=False,
            )
            assert admin.status_code == 200, (hostname, admin.status_code)
            assert "base_url not set" not in admin.text.lower(), hostname
            assert "archivebox-setup-wizard" not in admin.text, hostname
    finally:
        stop_archivebox_process(process)
