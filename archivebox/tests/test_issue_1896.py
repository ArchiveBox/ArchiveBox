"""Regression coverage for collection cookie paths and config edits on upgrade."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from archivebox.config.configset import read_ini_config
from archivebox.tests.conftest import run_archivebox_cmd


@pytest.mark.parametrize("cookie_file_exists", [True, False])
def test_add_with_collection_relative_cookies(initialized_archive, httpserver, cookie_file_exists):
    """Real crawl hooks must read cookies from the collection, not their cwd."""
    if cookie_file_exists:
        (initialized_archive / "cookies.txt").write_text(
            "# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tissue1896\timported\n",
        )
    httpserver.expect_request("/").respond_with_data(
        "<html><title>Issue 1896</title><body><p>Collection cookie import regression: "
        "this page must still be archived when the optional cookie file is absent.</p>"
        '<output id="cookies"></output><script>document.getElementById("cookies").textContent = document.cookie;</script></body></html>',
        content_type="text/html",
    )
    run_archivebox_cmd(
        ["config", "--set", "COOKIES_FILE=cookies.txt"],
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
        assert f"from {initialized_archive / 'cookies.txt'}" in logs
    else:
        assert "Cookies file not found" in logs
        assert "continuing without cookie import" in logs
    with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
        assert db.execute("SELECT status FROM core_snapshot").fetchall() == [("sealed",)]
        assert db.execute("SELECT status FROM core_archiveresult WHERE plugin='dom'").fetchall() == [("succeeded",)]
        hook_rows = db.execute("SELECT env, status, exit_code FROM machine_process WHERE process_type='hook'").fetchall()
        assert hook_rows
        for env, status, exit_code in hook_rows:
            assert json.loads(env)["COOKIES_FILE"] == str(initialized_archive / "cookies.txt")
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
