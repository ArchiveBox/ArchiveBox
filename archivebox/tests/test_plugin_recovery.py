"""Recovery commands stop abandoned capture processes without taking live ownership."""

import json
import os
import signal
import subprocess

import psutil

from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.tests.conftest import cli_env, resolve_abxpkg_chrome_env, run_archivebox_cmd, wait_for_pid_to_disappear


def test_recovery_logs_real_plugin_failure_with_traceback(initialized_archive):
    script = """
import json
import logging
import os
from archivebox.config.constants import CONSTANTS
from archivebox.core.recovery_util import recover_orchestrator_state

(CONSTANTS.USERS_DIR / 'recovery-test' / 'crawls').mkdir(parents=True, exist_ok=True)
# Invalid provider selection fails in the real abxpkg CLI on every platform.
# A missing/broken package library can instead produce a successful no-op
# recovery when Chrome has no available Node runtime.
os.environ['ABXPKG_BINPROVIDERS'] = 'unsupported-recovery-provider'
records = []
class Capture(logging.Handler):
    def emit(self, record):
        records.append(record)
handler = Capture()
logger = logging.getLogger('archivebox.core.recovery_util')
logger.addHandler(handler)
try:
    result = recover_orchestrator_state(include_plugins=True)
finally:
    logger.removeHandler(handler)
assert result['plugin_processes_orphaned'] == 0, result
assert len(records) == 1, [(record.name, record.getMessage()) for record in records]
record = records[0]
assert record.levelno == logging.ERROR
assert record.getMessage().startswith('Plugin chrome recovery failed: ')
assert 'unknown provider name(s): unsupported-recovery-provider' in record.getMessage()
assert record.exc_info is not None and record.exc_info[2] is not None
assert record.exc_info[0].__name__ == 'CalledProcessError'
assert record.exc_info[1].returncode == 2
assert 'unknown provider name(s): unsupported-recovery-provider' in record.exc_info[1].stderr, record.exc_info[1].stderr
print(json.dumps(result))
"""
    result = run_archivebox_cmd(
        ["shell", "-c", script],
        cwd=initialized_archive,
        env=cli_env(),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["plugin_processes_orphaned"] == 0


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
            ready = subprocess.run(
                [str(plugin.path / "on_CrawlSetup__91_chrome_wait.js"), "--url=about:blank"],
                cwd=directory,
                env=launch_env,
                capture_output=True,
                text=True,
                timeout=70,
            )
            assert ready.returncode == 0, ready.stdout + ready.stderr
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
            assert "Plugin chrome recovery failed" not in result.stderr
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
