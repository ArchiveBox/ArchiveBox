import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def _run(cmd, data_dir: Path, env: dict, timeout: int = 120):
    return subprocess.run(
        cmd,
        cwd=data_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _make_env(data_dir: Path) -> dict:
    env = os.environ.copy()
    env["DATA_DIR"] = str(data_dir)
    env["USE_COLOR"] = "False"
    env["SHOW_PROGRESS"] = "False"
    env["ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS"] = "true"
    env["PLUGINS"] = "title,favicon"
    # Keep it fast but still real hooks
    env["SAVE_TITLE"] = "True"
    env["SAVE_FAVICON"] = "True"
    env["SAVE_WGET"] = "False"
    env["SAVE_WARC"] = "False"
    env["SAVE_PDF"] = "False"
    env["SAVE_SCREENSHOT"] = "False"
    env["SAVE_DOM"] = "False"
    env["SAVE_SINGLEFILE"] = "False"
    env["SAVE_READABILITY"] = "False"
    env["SAVE_MERCURY"] = "False"
    env["SAVE_GIT"] = "False"
    env["SAVE_YTDLP"] = "False"
    env["SAVE_HEADERS"] = "False"
    env["SAVE_HTMLTOTEXT"] = "False"
    return env


def _count_running_processes(db_path: Path, where: str) -> int:
    for _ in range(50):
        try:
            conn = sqlite3.connect(db_path, timeout=1)
            cur = conn.cursor()
            count = cur.execute(
                f"SELECT COUNT(*) FROM machine_process WHERE status = 'running' AND {where}"
            ).fetchone()[0]
            conn.close()
            return count
        except sqlite3.OperationalError:
            time.sleep(0.1)
    return 0


def _wait_for_count(db_path: Path, where: str, target: int, timeout: int = 20) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if _count_running_processes(db_path, where) >= target:
            return True
        time.sleep(0.1)
    return False


def test_add_parents_workers_to_orchestrator(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = _make_env(data_dir)

    init = _run([sys.executable, "-m", "archivebox", "init", "--quick"], data_dir, env)
    assert init.returncode == 0, init.stderr

    add = _run([sys.executable, "-m", "archivebox", "add", "https://example.com"], data_dir, env, timeout=120)
    assert add.returncode == 0, add.stderr

    conn = sqlite3.connect(data_dir / "index.sqlite3")
    cur = conn.cursor()
    orchestrator = cur.execute(
        "SELECT id FROM machine_process WHERE process_type = 'orchestrator' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert orchestrator is not None
    orchestrator_id = orchestrator[0]

    worker_count = cur.execute(
        "SELECT COUNT(*) FROM machine_process WHERE process_type = 'worker' AND worker_type = 'crawl' "
        "AND parent_id = ?",
        (orchestrator_id,),
    ).fetchone()[0]
    conn.close()

    assert worker_count >= 1, "Expected crawl worker to be parented to orchestrator"


def test_add_interrupt_cleans_orphaned_processes(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = _make_env(data_dir)

    init = _run([sys.executable, "-m", "archivebox", "init", "--quick"], data_dir, env)
    assert init.returncode == 0, init.stderr

    proc = subprocess.Popen(
        [sys.executable, "-m", "archivebox", "add", "https://example.com"],
        cwd=data_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    db_path = data_dir / "index.sqlite3"
    saw_worker = _wait_for_count(db_path, "process_type = 'worker'", 1, timeout=20)
    assert saw_worker, "Expected at least one worker to start before interrupt"

    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=30)

    # Wait for workers/hooks to be cleaned up
    start = time.time()
    while time.time() - start < 30:
        running = _count_running_processes(db_path, "process_type IN ('worker','hook')")
        if running == 0:
            break
        time.sleep(0.2)

    assert _count_running_processes(db_path, "process_type IN ('worker','hook')") == 0, (
        "Expected no running worker/hook processes after interrupt"
    )
