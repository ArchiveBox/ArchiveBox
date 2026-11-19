"""Exercise the browser target lifecycle through a real multi-page CLI crawl."""

import os
import sqlite3
import subprocess

import pytest

from archivebox.tests.conftest import resolve_abxpkg_chrome_env


# Provision the real browser before measuring the multi-page capture lifecycle.
@pytest.mark.timeout(180, func_only=True)
def test_cli_crawl_captures_background_screenshots(tmp_path, browser_runtime):
    env = {**os.environ, "ABXPKG_LIB_DIR": str(browser_runtime["lib_dir"]), "SCREENSHOT_TIMEOUT": "5"}
    env.update(resolve_abxpkg_chrome_env(browser_runtime["lib_dir"], env))
    initialized = subprocess.run(
        ["archivebox", "init", "--quick"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert initialized.returncode == 0, initialized.stderr
    captured = subprocess.run(
        ["archivebox", "add", "--plugins=title,wget,screenshot", "https://example.com", "https://example.org"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert captured.returncode == 0, captured.stderr
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        results = db.execute("SELECT status, output_str FROM core_archiveresult WHERE plugin='screenshot'").fetchall()
    assert len(results) == 2, captured.stdout
    if any(status != "succeeded" for status, _ in results):
        print(captured.stdout, captured.stderr)
    assert all(status == "succeeded" for status, _ in results), (results, captured.stdout, captured.stderr)
    images = list((tmp_path / "archive" / "users").glob("*/snapshots/**/screenshot/screenshot.png"))
    assert len(images) == 2
    assert all(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and image.stat().st_size > 1000 for image in images)
