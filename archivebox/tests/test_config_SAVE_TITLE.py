import time
from pathlib import Path

from archivebox.tests.conftest import run_archivebox_cmd, cli_env

import pytest

from archivebox.core.models import Snapshot
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import _find_cached_chrome, _find_system_browser

pytestmark = pytest.mark.django_db(transaction=True)


def _install_chrome(tmp_path, env):
    env["CHROME_ISOLATION"] = "snapshot"
    env["ABXPKG_LIB_DIR"] = str(tmp_path / "lib")
    install_process = run_archivebox_cmd(
        ["install", "chrome"],
        cwd=tmp_path,
        env=env,
        timeout=600,
    )
    assert install_process.returncode == 0, install_process.stderr or install_process.stdout
    cached_browser = _find_cached_chrome(Path(env["ABXPKG_LIB_DIR"]))
    if cached_browser is not None:
        env["CHROME_BINARY"] = str(cached_browser)
        return
    system_browser = _find_system_browser()
    if system_browser:
        env["CHROME_BINARY"] = str(system_browser)
        return
    raise AssertionError(install_process.stderr or install_process.stdout)


def _wait_for_snapshot_title(data_dir, *, timeout=60):
    deadline = time.time() + timeout
    title = None
    while time.time() < deadline:
        with use_archivebox_db(data_dir):
            title = Snapshot.objects.exclude(url="archivebox://internal").get().resolved_title
        if title:
            return title
        time.sleep(0.5)
    return title


def test_title_is_extracted(tmp_path, initialized_archive, recursive_test_site):
    """Test that title is extracted from the page."""
    env = cli_env(disable_extractors=True)
    env.update({"SAVE_TITLE": "true"})
    _install_chrome(tmp_path, env)
    add_process = run_archivebox_cmd(
        ["add", "--plugins=chrome,wget,title", recursive_test_site["root_url"]],
        cwd=tmp_path,
        env=env,
    )
    assert add_process.returncode == 0, add_process.stderr or add_process.stdout

    title = _wait_for_snapshot_title(tmp_path)
    assert title is not None
    assert "Root" in title


def test_title_is_listed_by_search_alias(tmp_path, initialized_archive, recursive_test_site):
    """
    https://github.com/ArchiveBox/ArchiveBox/issues/330
    Unencoded content should not be rendered as it facilitates xss injections
    and breaks the layout.
    """
    env = cli_env(disable_extractors=True)
    env.update({"SAVE_TITLE": "true"})
    _install_chrome(tmp_path, env)
    add_process = run_archivebox_cmd(
        ["add", "--plugins=chrome,wget,title", recursive_test_site["root_url"]],
        cwd=tmp_path,
        env=env,
    )
    assert add_process.returncode == 0, add_process.stderr or add_process.stdout
    list_process = run_archivebox_cmd(
        ["search"],
        cwd=tmp_path,
        env=env,
    )
    assert list_process.returncode == 0, list_process.stderr or list_process.stdout

    output = list_process.stdout
    assert recursive_test_site["root_url"] in output
