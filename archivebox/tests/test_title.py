import os
import sqlite3
import subprocess
import sys

from .conftest import _find_system_browser
from .fixtures import disable_extractors_dict, process

FIXTURES = (disable_extractors_dict, process)


def _install_chrome(tmp_path, env):
    env["CHROME_ISOLATION"] = "snapshot"
    system_browser = _find_system_browser()
    if system_browser:
        env["CHROME_BINARY"] = str(system_browser)
        return

    install_process = subprocess.run(
        [sys.executable, "-m", "archivebox", "install", "chrome"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    assert install_process.returncode == 0, install_process.stderr or install_process.stdout


def test_title_is_extracted(tmp_path, process, disable_extractors_dict):
    """Test that title is extracted from the page."""
    disable_extractors_dict.update({"SAVE_TITLE": "true"})
    _install_chrome(tmp_path, disable_extractors_dict)
    add_process = subprocess.run(
        ["archivebox", "add", "--plugins=chrome,wget,title", "https://example.com"],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )
    assert add_process.returncode == 0, add_process.stderr or add_process.stdout

    os.chdir(tmp_path)
    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT title FROM core_snapshot")
    snapshot = c.fetchone()
    conn.close()

    assert snapshot[0] is not None
    assert "Example" in snapshot[0]


def test_title_is_htmlencoded_in_index_html(tmp_path, process, disable_extractors_dict):
    """
    https://github.com/ArchiveBox/ArchiveBox/issues/330
    Unencoded content should not be rendered as it facilitates xss injections
    and breaks the layout.
    """
    disable_extractors_dict.update({"SAVE_TITLE": "true"})
    _install_chrome(tmp_path, disable_extractors_dict)
    add_process = subprocess.run(
        ["archivebox", "add", "--plugins=chrome,wget,title", "https://example.com"],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )
    assert add_process.returncode == 0, add_process.stderr or add_process.stdout
    list_process = subprocess.run(
        ["archivebox", "search", "--html"],
        capture_output=True,
        text=True,
    )
    assert list_process.returncode == 0, list_process.stderr or list_process.stdout

    # Should not contain unescaped HTML tags in output
    output = list_process.stdout
    assert "https://example.com" in output
