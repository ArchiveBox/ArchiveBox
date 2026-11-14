"""Recovery commands stop abandoned capture processes without taking live ownership."""

import json
import os
import signal
import subprocess

import psutil

from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.tests.conftest import cli_env, resolve_abxpkg_chrome_env, run_archivebox_cmd, wait_for_pid_to_disappear
from abx_plugins.plugins.chrome.tests.chrome_test_helpers import wait_for_chrome_session_state


def test_recovery_preserves_live_and_out_of_scope_browsers(initialized_archive, cached_abxpkg_lib_dir):
    assert get_plugin_catalog().command("chrome", "recover") is not None
    plugin = get_plugin_catalog()["chrome"]
    processes = []
    browsers = []
    env = cli_env(**resolve_abxpkg_chrome_env(cached_abxpkg_lib_dir))
    env.update(ABXPKG_LIB_DIR=str(cached_abxpkg_lib_dir), CHROME_HEADLESS="true", CHROME_SANDBOX="false", CHROME_ISOLATION="crawl")
    roots = [initialized_archive / "archive" / "users" / "recovery-test" / "crawls" / "capture", initialized_archive / "outside-recovery"]
    try:
        for root in roots:
            directory = root / "chrome"
            directory.mkdir(parents=True)
            launch_env = {**env, "CRAWL_DIR": str(root), "SNAP_DIR": str(root), "CHROME_USER_DATA_DIR": str(root / "profile")}
            process = subprocess.Popen(
                [str(plugin.path / "on_CrawlSetup__90_chrome_launch.daemon.bg.js"), "--crawl-id=recovery-test"],
                cwd=directory,
                env=launch_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
            wait_for_chrome_session_state(directory, env=launch_env, require_browser_ready=True)
            assert process.poll() is None
            browsers.append(psutil.Process(int((directory / "chrome.pid").read_text())))

        def recover(expected):
            result = run_archivebox_cmd(
                [
                    "shell",
                    "-c",
                    "import json; from archivebox.core.recovery_util import recover_orchestrator_state; print(json.dumps(recover_orchestrator_state(include_plugins=True)))",
                ],
                cwd=initialized_archive,
                env=env,
                timeout=60,
            )
            assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
            assert result.returncode == 0, result.stdout + result.stderr
            assert json.loads(result.stdout.splitlines()[-1])["plugin_processes_orphaned"] == expected, result.stdout + result.stderr

        recover(0)
        assert all(browser.is_running() for browser in browsers)
        for process in processes:
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        assert all(browser.is_running() for browser in browsers)
        recover(1)
        wait_for_pid_to_disappear(browsers[0].pid)
        assert browsers[1].is_running()
        recover(0)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=15)
        for browser in browsers:
            if browser.is_running():
                browser.terminate()
                browser.wait(timeout=15)
