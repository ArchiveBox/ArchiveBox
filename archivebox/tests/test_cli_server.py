#!/usr/bin/env python3
"""
Tests for archivebox server command.
Verify server can start (basic smoke tests only, no full server testing).
"""

import os
import subprocess
import sys
from unittest.mock import Mock


def test_sqlite_connections_use_explicit_30_second_busy_timeout():
    from archivebox.core.settings import SQLITE_CONNECTION_OPTIONS

    assert SQLITE_CONNECTION_OPTIONS["OPTIONS"]["timeout"] == 30
    assert "PRAGMA busy_timeout = 30000;" in SQLITE_CONNECTION_OPTIONS["OPTIONS"]["init_command"]


def test_server_shows_usage_info(tmp_path, process):
    """Test that server command shows usage or starts."""
    os.chdir(tmp_path)

    # Just check that the command is recognized
    # We won't actually start a full server in tests
    result = subprocess.run(
        ['archivebox', 'server', '--help'],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert 'server' in result.stdout.lower() or 'http' in result.stdout.lower()


def test_server_init_flag(tmp_path, process):
    """Test that --init flag runs init before starting server."""
    os.chdir(tmp_path)

    # Check init flag is recognized
    result = subprocess.run(
        ['archivebox', 'server', '--help'],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert '--init' in result.stdout or 'init' in result.stdout.lower()


def test_runner_worker_uses_current_interpreter():
    """The supervised runner should use the active Python environment, not PATH."""
    from archivebox.workers.supervisord_util import RUNNER_WORKER

    assert RUNNER_WORKER["command"] == f"{sys.executable} -m archivebox run --daemon"


def test_reload_workers_use_current_interpreter_and_supervisord_managed_runner():
    from archivebox.workers.supervisord_util import RUNNER_WATCH_WORKER, RUNSERVER_WORKER

    runserver = RUNSERVER_WORKER("127.0.0.1", "8000", reload=True, pidfile="/tmp/runserver.pid")
    watcher = RUNNER_WATCH_WORKER("/tmp/runserver.pid")

    assert runserver["name"] == "worker_runserver"
    assert runserver["command"] == f"{sys.executable} -m archivebox manage runserver 127.0.0.1:8000"
    assert 'ARCHIVEBOX_RUNSERVER="1"' in runserver["environment"]
    assert 'ARCHIVEBOX_AUTORELOAD="1"' in runserver["environment"]
    assert 'ARCHIVEBOX_RUNSERVER_PIDFILE="/tmp/runserver.pid"' in runserver["environment"]

    assert watcher["name"] == "worker_runner_watch"
    assert watcher["command"] == f"{sys.executable} -m archivebox manage runner_watch --pidfile=/tmp/runserver.pid"


def test_stop_existing_background_runner_cleans_up_and_stops_orchestrators():
    from archivebox.cli.archivebox_server import stop_existing_background_runner

    runner_a = Mock()
    runner_a.kill_tree = Mock()
    runner_a.terminate = Mock()
    runner_b = Mock()
    runner_b.kill_tree = Mock(side_effect=RuntimeError("boom"))
    runner_b.terminate = Mock()

    process_model = Mock()
    process_model.StatusChoices.RUNNING = "running"
    process_model.TypeChoices.ORCHESTRATOR = "orchestrator"
    queryset = Mock()
    queryset.order_by.return_value = [runner_a, runner_b]
    process_model.objects.filter.return_value = queryset

    supervisor = Mock()
    stop_worker = Mock()
    log = Mock()

    stopped = stop_existing_background_runner(
        machine=Mock(),
        process_model=process_model,
        supervisor=supervisor,
        stop_worker_fn=stop_worker,
        log=log,
    )

    assert stopped == 2
    assert process_model.cleanup_stale_running.call_count == 2
    stop_worker.assert_any_call(supervisor, "worker_runner")
    stop_worker.assert_any_call(supervisor, "worker_runner_watch")
    runner_a.kill_tree.assert_called_once_with(graceful_timeout=2.0)
    runner_b.terminate.assert_called_once_with(graceful_timeout=2.0)
    log.assert_called_once()
