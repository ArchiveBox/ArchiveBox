"""Exercise real pytest workers against the maintained suite and fixtures."""

import os
import subprocess
import sys
from pathlib import Path


def test_xdist_preserves_relative_test_selection_and_runtime_isolation(tmp_path):
    target = Path(__file__).with_name("test_sqlite_backend.py")
    relative_target = os.path.relpath(target, tmp_path)
    env = os.environ.copy()
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        env.pop(key, None)
    session_dir = tmp_path / "nested-session"
    env["ARCHIVEBOX_PYTEST_SESSION_DATA_DIR"] = str(session_dir)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-n",
            "2",
            "-q",
            f"{relative_target}::test_closed_connection_is_reused_by_next_request_thread",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert not session_dir.exists()
