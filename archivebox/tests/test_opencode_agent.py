import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import psutil
import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST, run_archivebox_cmd


pytestmark = pytest.mark.django_db(transaction=True)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _reset_runtime_config() -> None:
    from archivebox.config import common
    from archivebox.config.configset import _INI_CACHE
    from archivebox.machine.models import Machine

    _INI_CACHE.clear()
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
            "ABXPKG_INSTALL_TIMEOUT": "900",
            "ABXPKG_MIN_RELEASE_AGE": "0",
            "ABX_RUNTIME": "archivebox",
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
    from abx_plugins.plugins.opencode import views

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
    binary, binary_env = views._resolve_binary(settings["binary"], settings["config"])
    version = subprocess.run(
        [binary, "--version"],
        env={**os.environ, **binary_env},
        text=True,
        capture_output=True,
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
        if views._PROCESS and views._PROCESS.poll() is None:
            views._PROCESS.terminate()
            try:
                views._PROCESS.wait(timeout=10)
            except Exception:
                views._PROCESS.kill()
        views._PROCESS = None


def test_opencode_disabled_route_does_not_start_server(client, initialized_archive):
    from archivebox.machine.models import Machine
    from abx_plugins.plugins.opencode import views

    os.chdir(initialized_archive)
    Machine.from_json({"config": {"OPENCODE_ENABLED": False}})
    _reset_runtime_config()
    assert views._machine_config()["OPENCODE_ENABLED"] is False

    response = client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 404
    assert views._PROCESS is None or views._PROCESS.poll() is not None


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
    from abx_plugins.plugins.opencode import views

    response = admin_client.get("/admin/agent", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert f'<iframe src="{views._project_route(live_opencode.config.data_dir)}'.encode() in response.content
    assert b'/session"' in response.content
    assert b'id="header"' in response.content
    assert b'id="progress-monitor"' in response.content


def test_opencode_proxy_serves_real_project_and_session(admin_client, live_opencode):
    workdir = str(live_opencode.config.data_dir.resolve())
    encoded_workdir = quote(workdir)

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


def test_opencode_proxy_sse_response_is_unbuffered(admin_client, live_opencode):
    response = admin_client.get(
        "/admin/agent/opencode/global/event",
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_SEC_FETCH_SITE="same-origin",
    )

    assert response.status_code == 200
    assert response.streaming
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["Cache-Control"] == "no-store"


def test_opencode_starts_with_data_dir_cwd_and_isolated_state(live_opencode):
    process = psutil.Process(live_opencode.process.pid)
    env = process.environ()
    workdir = str(live_opencode.config.data_dir.resolve())

    assert Path(process.cwd()).resolve() == live_opencode.config.data_dir.resolve()
    assert env["BROWSER"] == "false"
    assert env["HOME"] == str(live_opencode.config.state_dir / "home")
    assert env["XDG_CONFIG_HOME"] == str(live_opencode.config.state_dir / "config")
    assert env["XDG_DATA_HOME"] == str(live_opencode.config.state_dir / "data")
    assert env["XDG_STATE_HOME"] == str(live_opencode.config.state_dir / "state")
    assert env["XDG_CACHE_HOME"] == str(live_opencode.config.state_dir / "cache")
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
    assert env["GIT_CEILING_DIRECTORIES"] == workdir


def test_opencode_state_dir_is_separate_from_workdir(tmp_path):
    from abx_plugins.plugins.opencode import views

    workdir = tmp_path / "data"
    settings = views._settings({"OPENCODE_WORKDIR": str(workdir)})
    views._ensure_project_files(settings)

    assert settings["workdir"] == workdir
    assert settings["opencode_dir"] == workdir / "opencode"
    assert settings["config_home"] == workdir / "opencode" / "config"
    assert settings["data_home"] == workdir / "opencode" / "data"
    assert settings["state_home"] == workdir / "opencode" / "state"
    editable_skill = workdir / "opencode" / "SKILL.md"
    loaded_skill = workdir / "opencode" / "config" / "opencode" / "skills" / "archivebox" / "SKILL.md"
    assert editable_skill.exists()
    assert loaded_skill.is_symlink()
    assert loaded_skill.resolve() == editable_skill.resolve()
    assert f"ArchiveBox collection directory: {workdir.resolve()}" in editable_skill.read_text()


def test_opencode_rewrites_vite_preload_assets():
    from abx_plugins.plugins.opencode import views

    body = b'const BL="modulepreload",UL=function(t){return"/"+t};const icon="/assets/sprite.svg#anthropic"'
    rewritten = views._rewrite_text(body, {"origin": "http://127.0.0.1:4096"}).decode()

    assert 'return"/"+t' not in rewritten
    assert 'return"/admin/agent/opencode/"+t' in rewritten
    assert '"/admin/agent/opencode/assets/sprite.svg#anthropic"' in rewritten
