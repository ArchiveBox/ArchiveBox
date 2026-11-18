"""Read real RSS and exercise bounded observer lifecycle in small subprocesses."""

import io
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

from archivebox.workers.memory_observer import MemoryObserver


@pytest.mark.parametrize("mode", ["growth", "audit-denial", "transient"])
def test_observer_real_process_growth_and_failure(mode):
    script = Path(__file__).parent / "fixtures" / "test_memory_observer_scenario.py"
    result = subprocess.run([sys.executable, str(script), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["mode"] == mode
    rows = report["logs"].splitlines()
    assert re.fullmatch(r"worker_memory_baseline pid=\d+ rss_bytes=\d+ kernel_peak_bytes=\d+", rows[0])
    if mode == "audit-denial":
        assert rows[1:] == ["worker_memory_unavailable"]
    else:
        assert len(rows) == (2 if mode == "transient" else 3)
        pattern = (
            r"worker_memory_growth pid=\d+ rss_bytes=\d+ sampled_peak_bytes=\d+ kernel_peak_bytes=\d+ growth_bytes=\d+ active_categories="
            r"replay:\d+,search:\d+,export:\d+,render:\d+,database:\d+,view:\d+,plugin:\d+,other:\d+,unobserved:\d+"
            r" outer_families=original_replay:\d+,snapshot_replay:\d+,static:\d+,admin:\d+,search:\d+,opencode:\d+,other:\d+,unobserved:\d+,depth_limited:\d+"
        )
        assert all(re.fullmatch(pattern, row) for row in rows[1:])


@pytest.mark.parametrize("kwargs", [{"interval": 0}, {"growth_bytes": -1}, {"min_report_interval": 0}])
def test_observer_rejects_invalid_bounds(kwargs):
    with pytest.raises(ValueError, match="positive"):
        MemoryObserver(**kwargs)


def test_observer_idle_graceful_stop_and_single_start():
    output = io.StringIO()
    logger = logging.Logger("observer-lifecycle-test")
    logger.addHandler(logging.StreamHandler(output))
    observer = MemoryObserver(logger=logger)
    with observer:
        with pytest.raises(RuntimeError, match="already started"):
            observer.start()
    started = time.monotonic()
    assert observer.stop()
    assert time.monotonic() - started < 0.2
    assert not observer._thread.is_alive()
    assert output.getvalue().count("worker_memory_baseline") == 1
    assert "growth" not in output.getvalue()
    assert "unavailable" not in output.getvalue()
    with pytest.raises(RuntimeError, match="already started"):
        observer.start()


def test_real_uvicorn_observer_http_and_graceful_shutdown(initialized_archive, free_tcp_port_factory):
    import signal
    import psutil
    import requests
    from archivebox.tests.conftest import cli_env

    port = free_tcp_port_factory()
    env = cli_env(
        disable_extractors=True,
        DATA_DIR=str(initialized_archive),
        BASE_URL=f"http://archivebox.localhost:{port}",
        ALLOWED_HOSTS="*",
        PUBLIC_INDEX="True",
        SEARCH_BACKEND_ENGINE="sqlite",
    )
    log_path = initialized_archive / "observer-uvicorn.log"
    with log_path.open("w") as log:
        worker = subprocess.Popen(
            [sys.executable, "-m", "archivebox.workers.http_server", "--host=127.0.0.1", f"--port={port}"],
            cwd=initialized_archive,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        process = psutil.Process(worker.pid)
        try:
            deadline = time.monotonic() + 20
            while "Started server process" not in log_path.read_text():
                assert worker.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, log_path.read_text()
                time.sleep(0.05)
            with requests.Session() as client:
                client.trust_env = False
                headers = {"Host": f"web.archivebox.localhost:{port}"}
                health = client.get(f"http://127.0.0.1:{port}/health/", headers=headers, timeout=5)
                assert health.status_code == 200
                assert health.content == b"OK"
                time.sleep(1.1)  # Default 1 Hz observer runs during ordinary server idle.
                public = client.get(f"http://127.0.0.1:{port}/public/", headers=headers, timeout=10)
                assert public.status_code == 200
                assert b"table-bookmarks" in public.content
            assert process.is_running()
            worker.send_signal(signal.SIGTERM)
            returncode = worker.wait(timeout=10)
            # Uvicorn re-raises the handled signal after orderly server shutdown.
            assert returncode in (0, -signal.SIGTERM)
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=10)
    logs = log_path.read_text()
    assert "Shutting down" in logs
    assert "Finished server process" in logs
    memory_rows = [line for line in logs.splitlines() if "worker_memory_" in line]
    assert len(memory_rows) == 2
    assert re.fullmatch(
        r"worker_memory_baseline pid=\d+ rss_bytes=\d+ kernel_peak_bytes=\d+",
        memory_rows[0][memory_rows[0].index("worker_memory_baseline") :],
    )
    assert memory_rows[1].endswith("worker_memory_stopped")
    assert logs.index("worker_memory_stopped") < logs.index("Finished server process")
    assert "worker_memory_unavailable" not in logs
    assert "worker_memory_growth" not in logs
    assert not psutil.pid_exists(worker.pid)
    print(f"ordinary health and public GET passed; shutdown={returncode}; observer rows={len(memory_rows)}")


def test_occupied_listener_does_not_start_observer(initialized_archive):
    import socket
    from archivebox.tests.conftest import cli_env

    with socket.create_server(("127.0.0.1", 0)) as occupied:
        result = subprocess.run(
            [sys.executable, "-m", "archivebox.workers.http_server", "--host=127.0.0.1", f"--port={occupied.getsockname()[1]}"],
            cwd=initialized_archive,
            env=cli_env(disable_extractors=True, DATA_DIR=str(initialized_archive)),
            capture_output=True,
            text=True,
            timeout=20,
        )
    assert result.returncode != 0
    assert "Address already in use" in result.stderr
    assert "worker_memory_" not in result.stdout + result.stderr
