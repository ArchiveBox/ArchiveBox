"""Process cleanup must not trust stale supervisor PID files."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from archivebox.tests.conftest import (
    assert_no_processes_for_data_dir,
    kill_processes_for_data_dir,
    pgrep_data_dir,
)


def _supervisor_config(runtime_dir: Path, data_dir: Path) -> Path:
    runtime_dir.mkdir(parents=True)
    config = runtime_dir / "supervisord.conf"
    config.write_text(
        f"[supervisord]\nnodaemon=true\npidfile=supervisord.pid\nlogfile=supervisord.log\nchildlogdir={data_dir}\n",
    )
    return config


def _start_supervisor(config: Path) -> subprocess.Popen:
    process = subprocess.Popen(
        [str(Path(sys.executable).with_name("supervisord")), "--configuration=supervisord.conf"],
        cwd=config.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        pidfile = config.with_name("supervisord.pid")
        while time.monotonic() < deadline:
            assert process.poll() is None
            if pidfile.exists() and pidfile.read_text().strip() == str(process.pid):
                return process
            time.sleep(0.02)
        raise AssertionError("supervisord did not write its PID file")
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        raise


@pytest.mark.parametrize("unrelated_supervisor", [False, True], ids=["other-process", "other-supervisor"])
def test_cleanup_ignores_reused_supervisor_pid(tmp_path, unrelated_supervisor):
    data_dir = tmp_path / "collection"
    data_dir.mkdir()
    stale_config = _supervisor_config(data_dir / "tmp" / "stale", data_dir)
    unrelated_dir = tmp_path / "unrelated"
    unrelated_dir.mkdir()
    if unrelated_supervisor:
        other_config = _supervisor_config(unrelated_dir / "runtime", unrelated_dir)
        child = _start_supervisor(other_config)
    else:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=unrelated_dir,
            env={key: value for key, value in os.environ.items() if key != "DATA_DIR"},
            start_new_session=True,
        )
    try:
        stale_config.with_name("supervisord.pid").write_text(str(child.pid))
        matched_pids = {int(line.split()[0]) for line in pgrep_data_dir(data_dir)}
        kill_processes_for_data_dir(data_dir)
        assert child.poll() is None, "cleanup terminated an unrelated process via a stale PID file"
        assert child.pid not in matched_pids
        assert_no_processes_for_data_dir(data_dir)
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)


def test_cleanup_finds_supervisor_using_its_matching_config(tmp_path):
    data_dir = tmp_path / "collection"
    data_dir.mkdir()
    config = _supervisor_config(data_dir / "tmp" / "owned", data_dir)
    child = _start_supervisor(config)
    try:
        # Relative config argv and a runtime-subdirectory cwd require the PID
        # fallback; neither directly contains/matches the collection path.
        assert child.pid in {int(line.split()[0]) for line in pgrep_data_dir(data_dir)}
        kill_processes_for_data_dir(data_dir)
        assert child.wait(timeout=10) == 0
        assert_no_processes_for_data_dir(data_dir)
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
