"""Installed service declarations are lazy and keep supervisor metadata separate."""

import json
import shlex
from pathlib import Path

import pytest


@pytest.mark.django_db
def test_plugin_services_are_discovered_without_preparing_files(tmp_path):
    from archivebox.plugins.services import get_plugin_services

    config = {
        "DATA_DIR": str(tmp_path),
        "SEARCH_BACKEND_SONIC_ENABLED": True,
        "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.1",
        "SEARCH_BACKEND_SONIC_PORT": 1491,
    }
    services = get_plugin_services(config, context="command", plugin_names={"search_backend_sonic"})
    assert list(services) == ["worker_sonic"]
    service = services["worker_sonic"]
    assert service["bind"] == ("127.0.0.1", 1491)
    assert callable(service["ready"]) and callable(service["prepare"])
    assert not list(Path(tmp_path).iterdir())
    config["SEARCH_BACKEND_SONIC_ENABLED"] = False
    assert not get_plugin_services(config, context="command", plugin_names={"search_backend_sonic"})


@pytest.mark.django_db(transaction=True)
def test_browser_service_is_only_selected_for_server_startup(initialized_archive):
    from archivebox.tests.conftest import run_archivebox_cmd

    unrelated_auth = initialized_archive / "unrelated-auth.json"
    unrelated_auth.write_text('{"cookies": [], "origins": []}')
    unrelated_cookies = initialized_archive / "unrelated-cookies.txt"
    unrelated_cookies.write_text("# Netscape HTTP Cookie File\n")
    result = run_archivebox_cmd(
        [
            "shell",
            "-c",
            "import json; from archivebox.config.common import get_config; "
            "from archivebox.plugins.services import get_plugin_services, prepare_service_worker; "
            "config=get_config(); "
            "assert get_plugin_services(config,context='command',plugin_names={'chrome'}) == {}; "
            "assert get_plugin_services(config,context='runner',plugin_names={'chrome'}) == {}; "
            "service=get_plugin_services(config,context='server',plugin_names={'chrome'})['worker_vnc_browser']; "
            "print(json.dumps(prepare_service_worker(service)))",
        ],
        cwd=initialized_archive,
        env={
            "DISPLAY": ":99",
            "ARCHIVEBOX_VNC_PERSONA": "ServiceTest",
            "AUTH_STORAGE_FILE": str(unrelated_auth),
            "COOKIES_FILE": str(unrelated_cookies),
        },
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    worker = json.loads(result.stdout.splitlines()[-1])
    assert worker["name"] == "worker_vnc_browser"
    command = shlex.split(worker["command"])
    assert Path(command[1]).name == "browser.py"
    assert command[2] == "open" and command[-2:] == ["--persona-name", "ServiceTest"]
    assert "archivebox" not in command
    assert (Path(command[command.index("--persona-dir") + 1]) / "chrome_profile").is_dir()
    assert 'ABX_RUNTIME="archivebox"' in worker["environment"]
    assert 'AUTH_STORAGE_FILE=""' in worker["environment"]
    assert 'COOKIES_FILE=""' in worker["environment"]
    assert worker["service"] == {"label": "browser"}
    assert worker["autorestart"] == "false"
