"""Regression coverage for collection cookie paths and config edits on upgrade."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from archivebox.config.configset import read_ini_config
from archivebox.tests.conftest import run_archivebox_cmd


@pytest.mark.parametrize("persona_name", ["Default", "default"])
def test_add_preserves_case_distinct_personas(initialized_archive, httpserver, persona_name):
    """Both names from the follow-up report remain usable without deleting either."""
    run_archivebox_cmd(["persona", "create", "Default", "default"], cwd=initialized_archive, check=True)
    persona_dir = initialized_archive / "personas" / persona_name
    (persona_dir / "auth.json").touch()
    (persona_dir / "cookies.txt").touch()
    httpserver.expect_request("/").respond_with_data(
        "<html><head><title>Existing persona capture</title></head><body>"
        "Both personas retained. This saved page verifies that choosing either existing "
        "persona still captures the full document without deleting browser state.</body></html>",
        content_type="text/html",
    )
    result = run_archivebox_cmd(
        ["add", "--persona", persona_name, "--plugins=dom", httpserver.url_for("/")],
        cwd=initialized_archive,
        timeout=180,
        env={"CHROME_SANDBOX": "false"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = list((initialized_archive / "archive" / "users").glob("*/snapshots/**/dom/output.html"))
    assert len(outputs) == 1, result.stdout + result.stderr
    assert "Both personas retained" in outputs[0].read_text()
    with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
        assert db.execute("SELECT name FROM personas_persona ORDER BY name").fetchall() == [("Default",), ("default",)]
        assert db.execute("SELECT status FROM core_archiveresult WHERE plugin='dom'").fetchall() == [("succeeded",)]
        hook_envs = db.execute("SELECT env FROM machine_process WHERE process_type='hook'").fetchall()
        assert hook_envs
        assert all(json.loads(row[0])["ACTIVE_PERSONA"] == persona_name for row in hook_envs)


@pytest.mark.parametrize("contents,explicit", [("", True), ("not JSON", True), ("not JSON", False)])
def test_add_rejects_invalid_persona_auth_with_file_path(initialized_archive, httpserver, contents, explicit):
    persona_dir = initialized_archive / "personas" / "Default"
    persona_dir.mkdir(parents=True, exist_ok=True)
    auth_file = persona_dir / "auth.json"
    auth_file.write_text(contents)
    if explicit:
        run_archivebox_cmd(
            ["config", "--set", "AUTH_STORAGE_FILE=personas/Default/auth.json"],
            cwd=initialized_archive,
            check=True,
        )
    result = run_archivebox_cmd(
        ["add", "--plugins=dom", httpserver.url_for("/")],
        cwd=initialized_archive,
        timeout=180,
        env={"CHROME_SANDBOX": "false"},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    logs = list((initialized_archive / "archive" / "users").glob("*/crawls/**/chrome/*.stderr.log"))
    assert logs
    assert f"Invalid JSON cookie export: {auth_file}" in "\n".join(log.read_text() for log in logs)
    assert not list((initialized_archive / "archive" / "users").glob("*/snapshots/**/dom/output.html"))
    assert auth_file.read_text() == contents


@pytest.mark.parametrize("cookie_file_exists", [True, False])
@pytest.mark.parametrize("isolation", ["crawl", "snapshot"])
def test_add_with_empty_autodiscovered_persona_auth(initialized_archive, httpserver, cookie_file_exists, isolation):
    """An empty auth placeholder must not block a crawl or hide Netscape cookies."""
    persona_dir = initialized_archive / "personas" / "Default"
    persona_dir.mkdir(parents=True, exist_ok=True)
    auth_file = persona_dir / "auth.json"
    auth_file.touch()
    cookies_file = persona_dir / "cookies.txt"
    cookies_file.write_text(
        "# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tissue1896\timported\n" if cookie_file_exists else "",
    )
    httpserver.expect_request("/").respond_with_data(
        '<html><title>Empty persona auth</title><body><output id="cookies"></output>'
        '<script>document.getElementById("cookies").textContent = document.cookie;</script></body></html>',
        content_type="text/html",
    )
    result = run_archivebox_cmd(
        ["add", "--plugins=dom", httpserver.url_for("/").replace("localhost", "127.0.0.1")],
        cwd=initialized_archive,
        timeout=180,
        env={"CHROME_SANDBOX": "false", "CHROME_ISOLATION": isolation},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = list((initialized_archive / "archive" / "users").glob("*/snapshots/**/dom/output.html"))
    assert len(outputs) == 1, result.stdout + result.stderr
    assert ("issue1896=imported" in outputs[0].read_text()) == cookie_file_exists
    assert auth_file.read_bytes() == b""
    with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
        assert db.execute("SELECT status FROM core_snapshot").fetchall() == [("sealed",)]
        assert db.execute("SELECT status FROM core_archiveresult WHERE plugin='dom'").fetchall() == [("succeeded",)]
        hook_rows = db.execute("SELECT cmd, env, exit_code FROM machine_process WHERE process_type='hook'").fetchall()
        assert hook_rows
        for cmd, env, exit_code in hook_rows:
            hook_env = json.loads(env)
            assert not hook_env.get("AUTH_STORAGE_FILE")
            expected_cookies = cookies_file if isolation == "crawl" else Path(hook_env["PERSONAS_DIR"]) / "Default" / "cookies.txt"
            assert hook_env["COOKIES_FILE"] == str(expected_cookies)
            hook_name = Path(json.loads(cmd)[0]).name
            # The crawl wait hook explicitly skips when each snapshot owns Chrome.
            assert exit_code == (10 if isolation == "snapshot" and hook_name == "on_CrawlSetup__91_chrome_wait.js" else 0)


@pytest.mark.parametrize("cookie_file_exists", [True, False])
@pytest.mark.parametrize("absolute_path", [False, True], ids=["collection-relative", "absolute"])
def test_add_with_collection_relative_cookies(initialized_archive, httpserver, cookie_file_exists, absolute_path):
    """Real hooks resolve relative paths against DATA_DIR and preserve absolute paths."""
    cookies_file = (
        initialized_archive.parent / f"{initialized_archive.name}-cookies.txt" if absolute_path else initialized_archive / "cookies.txt"
    )
    configured_path = str(cookies_file) if absolute_path else "cookies.txt"
    if cookie_file_exists:
        cookies_file.write_text(
            "# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tissue1896\timported\n",
        )
    httpserver.expect_request("/").respond_with_data(
        "<html><title>Issue 1896</title><body><p>Collection cookie import regression: "
        "this page must still be archived when the optional cookie file is absent.</p>"
        '<output id="cookies"></output><script>document.getElementById("cookies").textContent = document.cookie;</script></body></html>',
        content_type="text/html",
    )
    run_archivebox_cmd(
        ["config", "--set", f"COOKIES_FILE={configured_path}"],
        cwd=initialized_archive,
        check=True,
    )
    result = run_archivebox_cmd(
        ["add", "--plugins=dom", httpserver.url_for("/").replace("localhost", "127.0.0.1")],
        cwd=initialized_archive,
        timeout=180,
        env={"CHROME_SANDBOX": "false"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = list((initialized_archive / "archive" / "users").glob("*/snapshots/**/dom/output.html"))
    assert len(outputs) == 1, result.stdout + result.stderr
    html = outputs[0].read_text()
    assert ("issue1896=imported" in html) == cookie_file_exists
    launch_logs = list((initialized_archive / "archive" / "users").glob("*/crawls/**/chrome/*.stderr.log"))
    logs = "\n".join(log.read_text() for log in launch_logs)
    if cookie_file_exists:
        assert f"from {cookies_file}" in logs
    else:
        assert "Cookies file not found" in logs
        assert "continuing without cookie import" in logs
    with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
        assert db.execute("SELECT status FROM core_snapshot").fetchall() == [("sealed",)]
        assert db.execute("SELECT status FROM core_archiveresult WHERE plugin='dom'").fetchall() == [("succeeded",)]
        hook_rows = db.execute("SELECT env, status, exit_code FROM machine_process WHERE process_type='hook'").fetchall()
        assert hook_rows
        for env, status, exit_code in hook_rows:
            assert json.loads(env)["COOKIES_FILE"] == str(cookies_file)
            assert (status, exit_code) == ("exited", 0)


@pytest.mark.parametrize("enabled_key", ["USE_CHROME", "CHROME_ENABLED"])
@pytest.mark.parametrize("startup_save", ["binary_sanitation", "host_refresh"])
def test_init_preserves_edited_use_chrome_before_startup_save(initialized_archive, enabled_key, startup_save):
    """Startup saves must not overwrite a newer file before config sync."""
    config_path = initialized_archive / "ArchiveBox.conf"
    config_path.write_text(config_path.read_text() + f"\n[SERVER_CONFIG]\n{enabled_key} = True\n")
    run_archivebox_cmd(
        ["config", "--set", f"WGET_BINARY={initialized_archive / 'removed-wget'}"]
        if startup_save == "binary_sanitation"
        else ["config", "--set", "TIMEOUT=37"],
        cwd=initialized_archive,
        check=True,
    )
    if startup_save == "host_refresh":
        with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
            db.execute("UPDATE machine_machine SET modified_at=?", [(datetime.now(timezone.utc) - timedelta(days=8)).isoformat()])
            db.commit()
    config_path.write_text(config_path.read_text().replace(f"{enabled_key} = True", f"{enabled_key} = False"))
    assert read_ini_config(config_path)[enabled_key] == "False"
    run_archivebox_cmd(["init"], cwd=initialized_archive, timeout=120, check=True)
    assert read_ini_config(config_path)[enabled_key] == "False"
    result = run_archivebox_cmd(["config", "--get", "CHROME_ENABLED"], cwd=initialized_archive)
    assert result.returncode == 0, result.stderr
    assert "CHROME_ENABLED = false" in result.stdout
