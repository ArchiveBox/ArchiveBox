"""Exercise dev reloads against real supervisord workers and CLI ownership."""

import signal
import re
import subprocess
import time

import psutil
import pytest

from archivebox.tests.conftest import (
    assert_no_processes_for_data_dir,
    cli_env,
    get_free_port,
    kill_processes_for_data_dir,
    pid_is_alive,
    run_archivebox_cmd,
    stop_archivebox_process,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("work", ["idle", "server-crawl", "foreground-add", "foreground-run"])
def test_reload_restarts_only_server_runner_once(initialized_archive, recursive_test_site, work):
    """Startup is not a reload; a reload is one supervised stop/start."""
    port = get_free_port()
    env = cli_env(
        live=True,
        server=True,
        port=port,
        SEARCH_BACKEND_ENGINE="ripgrep",
        CHROME_DELAY_AFTER_LOAD="60",
        CHROME_TIMEOUT="120",
        CHROME_HEADLESS="True",
        ARCHIVEBOX_RUNSERVER_BIND_URL=f"http://127.0.0.1:{port}",
    )
    log_path = initialized_archive / "reload-server.log"
    supervisor_log = initialized_archive / "logs" / "supervisord.log"
    server = None
    add = None

    def active_navigation(*, require_foreground=True):
        from archivebox.machine.models import Process
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        with use_archivebox_db(initialized_archive):
            for hook in Process.objects.filter(
                process_type=Process.TypeChoices.HOOK,
                cmd__0__endswith="on_Snapshot__30_chrome_navigate.js",
                status="running",
            ):
                if hook.is_running:
                    process = psutil.Process(hook.pid)
                    ancestors = {parent.pid for parent in process.parents()}
                    if require_foreground and work == "foreground-run" and add.pid not in ancestors:
                        continue
                    if require_foreground and work == "foreground-add":
                        # add borrows the server's supervisor; its one-shot
                        # worker is not an OS child of the add CLI parent.
                        owners = {
                            int(pid)
                            for pid in re.findall(
                                rf"spawned: 'worker_runner_add_{add.pid}' with pid (\d+)",
                                supervisor_log.read_text(),
                            )
                        }
                        if not ancestors.intersection(owners):
                            continue
                    return process
        return None

    def runner_pids():
        text = supervisor_log.read_text() if supervisor_log.exists() else ""
        return set(re.findall(r"spawned: 'worker_runner' with pid (\d+)", text))

    def wait_until(predicate):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if predicate():
                return
            assert server.poll() is None, log_path.read_text()
            time.sleep(0.1)
        raise AssertionError(log_path.read_text()[-16000:])

    try:
        if work != "idle":
            installed = run_archivebox_cmd(["install", "chrome"], cwd=initialized_archive, env=env, timeout=600)
            assert installed.returncode == 0, installed.stderr or installed.stdout
        with log_path.open("w") as log:
            server = run_archivebox_cmd(
                ["server", "--debug", f"127.0.0.1:{port}"],
                cwd=initialized_archive,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                wait=False,
                start_new_session=True,
            )
        wait_until(lambda: len(runner_pids()) >= 1)
        # Run the real watcher under the real supervisor, but replace the web
        # worker explicitly below. Watching shared checkout mtimes here would
        # let another developer's edits trigger unrelated reloads mid-test.
        watch = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                (
                    "from archivebox.workers.supervisord_util import "
                    "get_existing_supervisord_process, start_worker, RUNNER_WATCH_WORKER; "
                    f"start_worker(get_existing_supervisord_process(), RUNNER_WATCH_WORKER('http://127.0.0.1:{port}'))"
                ),
            ],
            cwd=initialized_archive,
            env=env,
            timeout=45,
        )
        assert watch.returncode == 0, watch.stderr or watch.stdout
        # Observe several watcher polls, including runserver's initial DB row.
        time.sleep(4)
        assert len(runner_pids()) == 1, supervisor_log.read_text()
        hook = None
        if work != "idle":
            args = ["add", "--plugins=chrome", recursive_test_site["root_url"]]
            if work == "server-crawl":
                args.insert(1, "--bg")
            elif work == "foreground-run":
                queued = run_archivebox_cmd([*args[:1], "--index-only", *args[1:]], cwd=initialized_archive, env=env)
                assert queued.returncode == 0, queued.stderr or queued.stdout
                args = ["run", "--no-stdin"]
            with (initialized_archive / "reload-add.log").open("w") as log:
                add = run_archivebox_cmd(
                    args,
                    cwd=initialized_archive,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    wait=False,
                    start_new_session=True,
                )
            wait_until(lambda: active_navigation() is not None)
            hook = active_navigation()
            if work.startswith("foreground-"):
                assert add.poll() is None
            # A borrowed foreground runner displaces the daemon; let supervisor
            # replace it with the normal standby worker before testing reload.
            time.sleep(3)
        original = runner_pids()
        # Restart the real web worker through its supervisor. This changes its
        # Process identity just as Django's autoreloader does, without editing
        # shared source files or disturbing other developers' servers.
        restarted = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                (
                    "from archivebox.workers.supervisord_util import get_existing_supervisord_process; "
                    "s = get_existing_supervisord_process(); "
                    "s.stopProcessGroup('worker_runserver'); s.startProcessGroup('worker_runserver')"
                ),
            ],
            cwd=initialized_archive,
            env=env,
            timeout=45,
        )
        assert restarted.returncode == 0, restarted.stderr or restarted.stdout
        wait_until(lambda: len(runner_pids()) > len(original))
        time.sleep(4)
        assert len(runner_pids()) == len(original) + 1, supervisor_log.read_text()
        assert not any(pid_is_alive(int(pid)) for pid in original)
        if work.startswith("foreground-"):
            assert add.poll() is None, (initialized_archive / "reload-add.log").read_text()
            assert hook.is_running(), "Web reload interrupted the foreground add's hook"
            stop_archivebox_process(add, signal.SIGTERM, timeout=45)
            add = None
            # The daemon observes the exited foreground owner on its next
            # standby poll, then waits for that owner's worker before resuming.
            wait_until(lambda: not hook.is_running())
            wait_until(lambda: active_navigation(require_foreground=False) is not None)
            resumed = active_navigation(require_foreground=False)
            assert {parent.pid for parent in resumed.parents()}.intersection(int(pid) for pid in runner_pids())
        elif work == "server-crawl":
            assert not hook.is_running(), "Reload left the old runner's hook orphaned"
            wait_until(lambda: active_navigation() is not None)
    finally:
        if add is not None and add.poll() is None:
            stop_archivebox_process(add, signal.SIGTERM, timeout=45)
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM, timeout=45)
        kill_processes_for_data_dir(initialized_archive)
        assert_no_processes_for_data_dir(initialized_archive, timeout=12)
