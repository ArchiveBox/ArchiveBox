import os
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import requests

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
    Machine.current()


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
def installed_opencode(opencode_archive_config):
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
    settings["archivebox_base_url"] = "http://admin.archivebox.localhost:5797"
    settings["archivebox_admin_url"] = "http://admin.archivebox.localhost:5797/admin"
    settings["archivebox_api_url"] = "http://admin.archivebox.localhost:5797/api/"
    binary, binary_env = runtime._resolve_binary(settings["binary"], settings["config"])
    version = binary.exec(
        cmd=("--version",),
        env={**os.environ, **binary_env},
        timeout=120,
    )
    assert version.returncode == 0, version.stderr or version.stdout
    return SimpleNamespace(config=opencode_archive_config, settings=settings)


@pytest.fixture
def live_opencode(installed_opencode):
    from abx_plugins.plugins.opencode import runtime

    settings = installed_opencode.settings
    ok, error = runtime._ensure_opencode(settings)
    assert ok, error

    process = runtime._PROCESS
    assert process is not None
    try:
        yield SimpleNamespace(config=installed_opencode.config, settings=settings, process=process)
    finally:
        runtime._stop_owned_process()


def test_opencode_disabled_via_cli_stays_disabled(admin_client, initialized_archive):
    _set_archivebox_config(initialized_archive, "OPENCODE_ENABLED=False")

    assert get_config().OPENCODE_ENABLED is False
    assert admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST).status_code == 404
    for path in ("/add/", "/admin/core/snapshot/"):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert b'href="/admin/agent"' not in response.content


def test_opencode_proxy_blocks_cross_site_fetch_metadata(admin_client, db, live_opencode):
    response = admin_client.post(
        "/admin/agent/opencode/session",
        data=b"{}",
        content_type="application/json",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="cross-site",
    )

    assert response.status_code == 403


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


def test_opencode_proxy_preserves_protocol_headers(admin_client, live_opencode):
    headers = {"HTTP_HOST": ADMIN_TEST_HOST, "HTTP_SEC_FETCH_SITE": "same-origin"}
    created = admin_client.post(
        "/admin/agent/opencode/pty",
        data={"command": "/bin/sh", "args": []},
        content_type="application/json",
        **headers,
    )
    assert created.status_code == 200
    path = f"/admin/agent/opencode/pty/{created.json()['id']}"
    try:
        response = admin_client.post(path + "/connect-token", HTTP_X_OPENCODE_TICKET="1", **headers)
        assert response.status_code == 200, response.content
        assert response.json()["ticket"]
    finally:
        deleted = admin_client.delete(path, **headers)
    assert deleted.status_code == 200, deleted.content


def test_opencode_starts_with_isolated_state(admin_client, live_opencode):
    workdir = str(live_opencode.config.data_dir.resolve())
    state_dir = live_opencode.config.state_dir

    assert not (Path(workdir) / ".git").exists()
    agent = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)
    assert agent.status_code == 200

    frame = admin_client.get(
        agent.context["proxy_url"],
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert frame.status_code == 302
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
    assert not config.json().get("model")
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
def test_opencode_incomplete_install_does_not_break_archivebox(installed_opencode, tmp_path, damaged_file, missing):
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
if {damaged_file != "runtime.py"!r}:
    from abx_plugins.plugins.opencode import runtime
    assert runtime._PROCESS is None
for path in ('/health/', '/add/', '/admin/core/snapshot/'):
    assert client.get(path).status_code == 200, path
print('OPTIONAL_SERVICE_FAILURE_ISOLATED')
"""
    result = run_archivebox_cmd(
        ["shell", "-c", script],
        cwd=installed_opencode.config.data_dir,
        env={**installed_opencode.config.env, "PYTHONPATH": str(site)},
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "OPTIONAL_SERVICE_FAILURE_ISOLATED" in result.stdout
