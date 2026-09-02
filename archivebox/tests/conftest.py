"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import json
import re
import secrets
import signal
import select
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import shutil
import ctypes
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any
from collections.abc import Callable

import psutil
import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
PYTEST_BASETEMP_ROOT = (REPO_ROOT / "tests" / "out").resolve()
SESSION_DATA_DIR = Path(
    os.environ.get("ARCHIVEBOX_PYTEST_SESSION_DATA_DIR") or tempfile.mkdtemp(prefix="archivebox-pytest-session-"),
).resolve()

os.environ["ARCHIVEBOX_PYTEST_SESSION_DATA_DIR"] = str(SESSION_DATA_DIR)
os.environ["DATA_DIR"] = str(SESSION_DATA_DIR)
(SESSION_DATA_DIR / "tests").mkdir(parents=True, exist_ok=True)
os.chdir(SESSION_DATA_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
os.environ.pop("ARCHIVE_DIR", None)
os.environ.pop("USERS_DIR", None)
os.environ.pop("CRAWL_DIR", None)
os.environ.pop("SNAP_DIR", None)

_RUNTIME_GUARD_ACTIVE = False


def _is_repo_path(path: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    if resolved == PYTEST_BASETEMP_ROOT or PYTEST_BASETEMP_ROOT in resolved.parents:
        return False
    return resolved == REPO_ROOT or REPO_ROOT in resolved.parents


def _assert_not_repo_path(path: Path, *, label: str) -> None:
    if _is_repo_path(path):
        raise AssertionError(f"{label} must not point inside the repo root during tests: {path}")


def _assert_safe_runtime_paths(*, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    if cwd is not None:
        _assert_not_repo_path(cwd, label="cwd")

    for key in ("CRAWL_DIR", "SNAP_DIR"):
        value = (env or {}).get(key)
        if value:
            _assert_not_repo_path(Path(value), label=key)


def _test_source_pythonpath() -> str:
    entries: list[str] = [str(REPO_ROOT.resolve(strict=False))]
    for repo_name in ("abxpkg", "abx-plugins", "abx-dl"):
        for repo_path in (WORKSPACE_ROOT / repo_name, REPO_ROOT / repo_name):
            if repo_path.exists():
                entries.append(str(repo_path.resolve(strict=False)))
                break
    return os.pathsep.join(entries)


def _set_test_source_pythonpath(env: dict[str, str]) -> None:
    source_pythonpath = _test_source_pythonpath()
    existing_entries = [
        str(Path(entry).expanduser().resolve(strict=False))
        for entry in (env.get("PYTHONPATH") or "").split(os.pathsep)
        if entry and Path(entry).expanduser().is_absolute() and Path(entry).expanduser().exists()
    ]
    entries = [entry for entry in [*source_pythonpath.split(os.pathsep), *existing_entries] if entry]
    if entries:
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entries))
    else:
        env.pop("PYTHONPATH", None)


def _sync_archivebox_test_data_dir(data_dir: Path) -> None:
    from archivebox.config import constants as constants_mod
    from archivebox.config import paths as paths_mod

    data_dir = data_dir.resolve()
    archive_dir = data_dir / constants_mod.CONSTANTS.ARCHIVE_DIR_NAME
    users_dir = archive_dir / constants_mod.CONSTANTS.USERS_DIR_NAME

    paths_mod.DATA_DIR = data_dir
    paths_mod.ARCHIVE_DIR = archive_dir
    paths_mod.USERS_DIR = users_dir
    paths_mod.DATABASE_FILE = data_dir / constants_mod.CONSTANTS.SQL_INDEX_FILENAME

    constants_mod.CONSTANTS.DATA_DIR = data_dir
    constants_mod.CONSTANTS.ARCHIVE_DIR = archive_dir
    constants_mod.CONSTANTS.USERS_DIR = users_dir
    constants_mod.CONSTANTS.COLLECTION_ID = paths_mod.get_collection_id(data_dir)
    constants_mod.CONSTANTS.SOURCES_DIR = data_dir / constants_mod.CONSTANTS.SOURCES_DIR_NAME
    constants_mod.CONSTANTS.PERSONAS_DIR = data_dir / constants_mod.CONSTANTS.PERSONAS_DIR_NAME
    constants_mod.CONSTANTS.LOGS_DIR = data_dir / constants_mod.CONSTANTS.LOGS_DIR_NAME
    constants_mod.CONSTANTS.CACHE_DIR = data_dir / constants_mod.CONSTANTS.CACHE_DIR_NAME
    constants_mod.CONSTANTS.CUSTOM_TEMPLATES_DIR = data_dir / constants_mod.CONSTANTS.CUSTOM_TEMPLATES_DIR_NAME
    constants_mod.CONSTANTS.USER_PLUGINS_DIR = data_dir / constants_mod.CONSTANTS.CUSTOM_PLUGINS_DIR_NAME
    constants_mod.CONSTANTS.CONFIG_FILE = data_dir / constants_mod.CONSTANTS.CONFIG_FILENAME
    constants_mod.CONSTANTS.DATABASE_FILE = data_dir / constants_mod.CONSTANTS.SQL_INDEX_FILENAME
    constants_mod.CONSTANTS.DEFAULT_TMP_DIR = data_dir / constants_mod.CONSTANTS.TMP_DIR_NAME / constants_mod.CONSTANTS.MACHINE_ID

    constants_mod.CONSTANTS_CONFIG.update(
        {key: value for key, value in constants_mod.CONSTANTS.__dict__.items() if key.isupper() and not key.startswith("_")},
    )


def _archivebox_test_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    """Enforce runtime path isolation through Python's native audit surface."""
    if not _RUNTIME_GUARD_ACTIVE:
        return
    if event == "os.chdir":
        path = Path(args[0])
        _assert_not_repo_path(path, label="cwd")
        _sync_archivebox_test_data_dir(path)
    elif event == "subprocess.Popen":
        cwd = args[2]
        env = args[3]
        if cwd is not None:
            _assert_not_repo_path(Path(cwd), label="cwd")
        _assert_safe_runtime_paths(cwd=Path(cwd) if cwd is not None else None, env=env)


sys.addaudithook(_archivebox_test_audit_hook)


# =============================================================================
# CLI Helpers (defined before fixtures that use them)
# =============================================================================


class ArchiveBoxCmdResult:
    """Process-like result for completed and live ArchiveBox CLI commands."""

    def __init__(self, args: list[str], process: subprocess.Popen) -> None:
        self.args = args
        self._process = process
        self._stdout = None
        self._stderr = None

    @property
    def stdout(self):
        if self._stdout is None:
            return self._process.stdout
        return self._stdout

    @property
    def stderr(self):
        if self._stderr is None:
            return self._process.stderr
        return self._stderr

    @property
    def stdin(self):
        return self._process.stdin

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    @property
    def pid(self) -> int | None:
        return self._process.pid

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        return self._process.wait(timeout=timeout)

    def communicate(self, input=None, timeout: float | None = None):
        self._stdout, self._stderr = self._process.communicate(input=input, timeout=timeout)
        return self._stdout, self._stderr

    def terminate(self) -> None:
        self._process.terminate()

    def send_signal(self, sig: int) -> None:
        self._process.send_signal(sig)


def run_archivebox_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    input: str | bytes | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    check: bool = False,
    text: bool = True,
    capture_output: bool = True,
    stdout: Any = None,
    stderr: Any = None,
    stdin: Any = None,
    wait: bool = True,
    start_new_session: bool = False,
    default_cli_env: bool = False,
    disable_extractors: bool = False,
    replace_env: bool = False,
) -> ArchiveBoxCmdResult:
    """Run an ArchiveBox CLI command under test isolation."""
    cwd = cwd or Path.cwd()
    cmd = ["archivebox", *args]

    _assert_not_repo_path(cwd, label="cwd")

    run_env = {} if replace_env else os.environ.copy()
    if default_cli_env or disable_extractors or env is not None:
        if default_cli_env:
            run_env["USE_COLOR"] = "False"
            run_env["SHOW_PROGRESS"] = "False"
        if disable_extractors:
            run_env.update(
                {
                    "SAVE_ARCHIVEDOTORG": "False",
                    "SAVE_TITLE": "False",
                    "SAVE_FAVICON": "False",
                    "SAVE_WGET": "False",
                    "SAVE_WARC": "False",
                    "SAVE_PDF": "False",
                    "SAVE_SCREENSHOT": "False",
                    "SAVE_DOM": "False",
                    "SAVE_SINGLEFILE": "False",
                    "SAVE_READABILITY": "False",
                    "SAVE_MERCURY": "False",
                    "SAVE_GIT": "False",
                    "SAVE_YTDLP": "False",
                    "SAVE_HEADERS": "False",
                    "SAVE_HTMLTOTEXT": "False",
                },
            )
            if args and args[0] == "version":
                run_env["PLUGINS"] = "__archivebox_test_no_plugins__"
        if env:
            run_env.update(env)
    _set_test_source_pythonpath(run_env)

    _assert_safe_runtime_paths(cwd=cwd, env=run_env)

    if stdin is not None:
        assert input is None, "pass either input or stdin, not both"
        if wait:
            input = stdin
    if isinstance(input, str):
        text = True

    if capture_output:
        stdout = subprocess.PIPE if stdout is None else stdout
        stderr = subprocess.PIPE if stderr is None else stderr

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if wait and input is not None else stdin,
        stdout=stdout,
        stderr=stderr,
        text=text,
        cwd=cwd,
        env=run_env,
        start_new_session=start_new_session,
    )
    result = ArchiveBoxCmdResult(cmd, process)

    if wait:
        try:
            result.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            raise
        if check and result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )

    return result


def find_snapshot_dir(data_dir: Path, snapshot_id: str) -> Path | None:
    candidates = {snapshot_id}
    if len(snapshot_id) == 32:
        candidates.add(f"{snapshot_id[:8]}-{snapshot_id[8:12]}-{snapshot_id[12:16]}-{snapshot_id[16:20]}-{snapshot_id[20:]}")
    elif len(snapshot_id) == 36 and "-" in snapshot_id:
        candidates.add(snapshot_id.replace("-", ""))

    for needle in candidates:
        for path in data_dir.rglob(needle):
            if path.is_dir():
                return path
    return None


# =============================================================================
# Fixtures
# =============================================================================


def pytest_configure():
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@pytest.fixture(autouse=True)
def isolate_test_runtime(tmp_path):
    """
    Run each pytest test from an isolated temp cwd and restore env mutations.

    The maintained pytest suite lives under ``archivebox/tests``. Many of those
    CLI tests shell out without passing ``cwd=`` explicitly, so the safest
    contract is that every test starts in its own temp directory and any
    in-process ``os.environ`` edits are rolled back afterwards.

    ArchiveBox derives DATA_DIR from cwd, so subprocess helpers pass the target
    collection as cwd instead of using DATA_DIR as an override.
    """
    global _RUNTIME_GUARD_ACTIVE

    _assert_not_repo_path(tmp_path, label="tmp_path")
    original_cwd = Path.cwd()
    original_env = os.environ.copy()
    os.chdir(tmp_path)
    _sync_archivebox_test_data_dir(tmp_path)
    os.environ.pop("DATA_DIR", None)

    def reset_machine_model_caches() -> None:
        import archivebox.machine.models as machine_models

        machine_models._CURRENT_MACHINE = None
        machine_models._CURRENT_INTERFACE = None
        machine_models._CURRENT_PROCESS = None
        machine_models._CURRENT_BINARIES.clear()

    reset_machine_model_caches()
    _RUNTIME_GUARD_ACTIVE = True
    try:
        _assert_safe_runtime_paths(cwd=Path.cwd(), env=os.environ)
        yield
    finally:
        _RUNTIME_GUARD_ACTIVE = False
        reset_machine_model_caches()
        os.chdir(original_cwd)
        _sync_archivebox_test_data_dir(original_cwd)
        os.environ.clear()
        os.environ.update(original_env)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SESSION_DATA_DIR, ignore_errors=True)


@pytest.fixture
def isolated_data_dir(tmp_path):
    """
    Create isolated DATA_DIR for each test.

    Uses tmp_path for complete isolation.
    """
    data_dir = tmp_path / "archivebox_data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def hermetic_lib_dir(tmp_path):
    """
    Point ABXPKG_LIB_DIR at a temporary directory for isolated abxpkg resolution.

    Opt-in only: most tests should reuse the cached real ABXPKG_LIB_DIR for speed —
    rebuilding from scratch per-test adds ~10× overhead. Use this only when
    validating ABXPKG_LIB_DIR-relative behavior.
    """
    import archivebox.machine.models as machine_models

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    original_lib_dir = os.environ.get("ABXPKG_LIB_DIR")
    os.environ["ABXPKG_LIB_DIR"] = str(lib_dir)
    machine_models._CURRENT_MACHINE = None
    machine_models._CURRENT_PROCESS = None
    try:
        yield lib_dir
    finally:
        if original_lib_dir is None:
            os.environ.pop("ABXPKG_LIB_DIR", None)
        else:
            os.environ["ABXPKG_LIB_DIR"] = original_lib_dir
        machine_models._CURRENT_MACHINE = None
        machine_models._CURRENT_PROCESS = None


@pytest.fixture
def cached_abxpkg_lib_dir():
    """Reuse one real abxpkg installation cache for the current pytest session."""
    lib_dir = SESSION_DATA_DIR / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    original_lib_dir = os.environ.get("ABXPKG_LIB_DIR")
    os.environ["ABXPKG_LIB_DIR"] = str(lib_dir)
    try:
        yield lib_dir
    finally:
        if original_lib_dir is None:
            os.environ.pop("ABXPKG_LIB_DIR", None)
        else:
            os.environ["ABXPKG_LIB_DIR"] = original_lib_dir


@pytest.fixture
def initialized_archive(tmp_path):
    """
    Initialize ArchiveBox archive in isolated directory.

    Runs `archivebox init` via subprocess to set up database and directories.
    """
    _cmd_result = run_archivebox_cmd(
        ["init", "--quick"],
        cwd=tmp_path,
        timeout=60,
        default_cli_env=True,
        disable_extractors=True,
    )
    stderr, returncode = _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"archivebox init failed: {stderr}"
    return tmp_path


@pytest.fixture
def recursive_test_site():
    pages = {
        "/": """
            <html>
              <head>
                <title>Root</title>
                <link rel="icon" href="/favicon.ico">
              </head>
              <body>
                <a href="/about">About</a>
                <a href="/blog">Blog</a>
                <a href="/contact">Contact</a>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/about": """
            <html>
              <body>
                <main>
                  <article>
                    <h1>About</h1>
                    <p>This local article describes the ArchiveBox recursive crawl fixture with enough semantic content for real article extractors.</p>
                    <a href="/deep/about">Deep About</a>
                  </article>
                </main>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/blog": """
            <html>
              <body>
                <main>
                  <article>
                    <h1>Blog</h1>
                    <p>This local article exercises real browser, text extraction, and recursive discovery behavior without depending on a public website.</p>
                    <a href="/deep/blog">Deep Blog</a>
                  </article>
                </main>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/contact": """
            <html>
              <body>
                <main>
                  <article>
                    <h1>Contact</h1>
                    <p>This local article keeps the deterministic crawl graph content-rich while preserving the original contact and deep-contact URLs.</p>
                    <a href="/deep/contact">Deep Contact</a>
                  </article>
                </main>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/deep/about": b"<html><body><main><article><h1>Deep About</h1><p>This depth-two article verifies that recursive snapshots retain extractable semantic content and their exact parent relationship.</p></article></main></body></html>",
        "/deep/blog": b"<html><body><main><article><h1>Deep Blog</h1><p>This depth-two article provides deterministic local content for every real extraction plugin in the recursive crawl.</p></article></main></body></html>",
        "/deep/contact": b"<html><body><main><article><h1>Deep Contact</h1><p>This depth-two article completes the fixed local graph without relying on mutable third-party pages or network policy.</p></article></main></body></html>",
        "/favicon.ico": b"test-icon",
    }

    class RecursiveHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            if self.path.endswith(".ico"):
                self.send_header("Content-Type", "image/x-icon")
            else:
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RecursiveHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        yield {
            "base_url": base_url,
            "root_url": f"{base_url}/",
            "child_urls": [f"{base_url}/about", f"{base_url}/blog", f"{base_url}/contact"],
            "deep_urls": [f"{base_url}/deep/about", f"{base_url}/deep/blog", f"{base_url}/deep/contact"],
        }
    finally:
        server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def blocking_http_server():
    """Serve one real request behind explicit start/release synchronization."""

    request_started = Event()
    release_response = Event()

    class BlockingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            request_started.set()
            release_response.wait()
            body = b"<html><head><title>Barrier</title></head><body>released</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), BlockingHandler)
    thread = Thread(target=server.serve_forever, name="archivebox-test-http-barrier")
    thread.start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_port}/",
        request_started=request_started,
        release_response=release_response,
    )
    release_response.set()
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def archivebox_daemon_server(initialized_archive, free_tcp_port_factory):
    """
    Start a real daemonized ArchiveBox server in this test's DATA_DIR and
    always stop its supervisord before the test exits.
    """
    started: list[tuple[Path, dict[str, str]]] = []

    def start(**env_overrides: str):
        env_config = {
            "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.1",
            "SEARCH_BACKEND_SONIC_PORT": str(free_tcp_port_factory()),
            **{key: str(value) for key, value in env_overrides.items()},
        }
        env = cli_env(
            live=True,
            **env_config,
        )
        port = free_tcp_port_factory()
        result = run_archivebox_cmd(
            ["server", "--daemonize", f"127.0.0.1:{port}"],
            cwd=initialized_archive,
            env=env,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        started.append((initialized_archive, env))
        return SimpleNamespace(
            data_dir=initialized_archive,
            env=env,
            port=port,
            worker_state=lambda: _archivebox_worker_state(initialized_archive, env),
            wait_for_workers=lambda names, timeout=45: _wait_for_archivebox_workers(initialized_archive, env, names, timeout=timeout),
        )

    try:
        yield start
    finally:
        for cwd, env in reversed(started):
            _stop_archivebox_supervisord(cwd, env)


def find_process(predicate: Callable[[psutil.Process, str], bool]) -> psutil.Process:
    """Locate a process after its native readiness signal has fired."""
    last_seen: list[str] = []
    for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            command = " ".join(cmdline)
            last_seen.append(f"{proc.info.get('pid')} {proc.info.get('ppid')} {command}")
            if predicate(proc, command):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    raise AssertionError("No matching live process found. Last seen:\n" + "\n".join(last_seen[-50:]))


def pid_is_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        return True


def wait_for_pid_to_disappear(pid: int, *, timeout: float = 20.0) -> None:
    try:
        psutil.Process(pid).wait(timeout=timeout)
    except psutil.NoSuchProcess:
        return
    except psutil.TimeoutExpired as exc:
        raise AssertionError(f"PID {pid} is still running") from exc


def cleanup_process_group(group_pid: int | None, *child_pids: int | None) -> None:
    processes: list[psutil.Process] = []
    if group_pid and pid_is_alive(group_pid):
        try:
            os.killpg(group_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            try:
                os.kill(group_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        processes.append(psutil.Process(group_pid))
    for pid in child_pids:
        if pid and pid_is_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            else:
                processes.append(psutil.Process(pid))
    _gone, alive = psutil.wait_procs(processes, timeout=10)
    assert not alive, f"processes did not stop after SIGTERM: {[proc.pid for proc in alive]}"


def cli_env(
    *,
    port: int | None = None,
    plugins_root: Path | None = None,
    replace: bool = False,
    disable_extractors: bool = False,
    live: bool = False,
    server: bool = False,
    wget: bool = False,
    **extra: str,
) -> dict[str, str]:
    env = {} if replace else os.environ.copy()
    _set_test_source_pythonpath(env)
    env.update({"USE_COLOR": "False", "SHOW_PROGRESS": "False"})

    if disable_extractors or live or server:
        env.update(
            {
                "PLUGINS": "__archivebox_test_no_plugins__",
                "SAVE_ARCHIVEDOTORG": "False",
                "SAVE_TITLE": "False",
                "SAVE_FAVICON": "False",
                "SAVE_WGET": "False",
                "SAVE_WARC": "False",
                "SAVE_PDF": "False",
                "SAVE_SCREENSHOT": "False",
                "SAVE_DOM": "False",
                "SAVE_SINGLEFILE": "False",
                "SAVE_READABILITY": "False",
                "SAVE_MERCURY": "False",
                "SAVE_GIT": "False",
                "SAVE_YTDLP": "False",
                "SAVE_HEADERS": "False",
                "SAVE_HTMLTOTEXT": "False",
            },
        )

    if live:
        env.update(
            {
                "TIMEOUT": "60",
                "WGET_TIMEOUT": "45",
                "CRAWL_MAX_CONCURRENT_SNAPSHOTS": "1",
                "PARSE_HTML_URLS_ENABLED": "True",
                "PARSE_DOM_OUTLINKS_ENABLED": "False",
                "SEARCH_BACKEND_ENGINE": "sqlite",
            },
        )

    if server:
        assert port is not None, "port is required when server=True"
        env.update(
            {
                "PLUGINS": "wget",
                "BIND_ADDR": f"127.0.0.1:{port}",
                "BASE_URL": f"http://archivebox.localhost:{port}",
                "ALLOWED_HOSTS": "*",
                "PUBLIC_ADD_VIEW": "True",
                "TIMEOUT": "30",
                "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*|example\.com",
                "SAVE_WGET": "True",
                "USE_CHROME": "False",
                "SEARCH_BACKEND_SONIC_ENABLED": "False",
            },
        )

    if wget:
        env.update({"PLUGINS": "wget", "SAVE_WGET": "True"})

    if plugins_root is not None:
        env["ABX_PLUGINS_DIR"] = str(plugins_root)

    env.update(extra)
    return env


def assert_port_open(host: str, port: int, *, timeout: float = 30.0) -> None:
    """Verify a listening socket after the server emitted its readiness event."""
    with socket.create_connection((host, port), timeout=timeout) as connection:
        assert connection.getpeername() == (host, port)


def _wait_for_log_match(log_path: Path, pattern: str, *, fixed: bool, count: int, timeout: float) -> str:
    """Block on native filesystem notifications until the requested log event exists."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout

    if sys.platform == "darwin":
        parent_fd = os.open(log_path.parent, os.O_RDONLY)
        watched_fd: int | None = None
        event_queue = select.kqueue()
        event_queue.control(
            [
                select.kevent(
                    parent_fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE,
                ),
            ],
            0,
            0,
        )

        def refresh_file_watcher() -> None:
            nonlocal watched_fd
            if watched_fd is not None:
                try:
                    same_file = os.fstat(watched_fd).st_ino == log_path.stat().st_ino
                except (FileNotFoundError, OSError):
                    same_file = False
                if same_file:
                    return
                try:
                    event_queue.control(
                        [
                            select.kevent(
                                watched_fd,
                                filter=select.KQ_FILTER_VNODE,
                                flags=select.KQ_EV_DELETE,
                            ),
                        ],
                        0,
                        0,
                    )
                except OSError:
                    pass
                os.close(watched_fd)
                watched_fd = None
            if log_path.exists():
                try:
                    watched_fd = os.open(log_path, os.O_RDONLY)
                except FileNotFoundError:
                    return
                event_queue.control(
                    [
                        select.kevent(
                            watched_fd,
                            filter=select.KQ_FILTER_VNODE,
                            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                            fflags=(
                                select.KQ_NOTE_WRITE
                                | select.KQ_NOTE_EXTEND
                                | select.KQ_NOTE_ATTRIB
                                | select.KQ_NOTE_RENAME
                                | select.KQ_NOTE_DELETE
                            ),
                        ),
                    ],
                    0,
                    0,
                )

        def wait_for_change(remaining: float) -> None:
            events = event_queue.control(None, 1, remaining)
            assert events, f"timed out waiting for filesystem event on {log_path}"
            refresh_file_watcher()

        def close_watcher() -> None:
            event_queue.close()
            if watched_fd is not None:
                os.close(watched_fd)
            os.close(parent_fd)

        refresh_file_watcher()

    else:
        libc = ctypes.CDLL(None, use_errno=True)
        inotify_fd = libc.inotify_init1(os.O_CLOEXEC)
        assert inotify_fd >= 0, os.strerror(ctypes.get_errno())
        watch_mask = 0x00000002 | 0x00000008 | 0x00000080 | 0x00000100
        watch_descriptor = libc.inotify_add_watch(inotify_fd, os.fsencode(log_path.parent), watch_mask)
        assert watch_descriptor >= 0, os.strerror(ctypes.get_errno())

        def wait_for_change(remaining: float) -> None:
            readable, _writable, _errors = select.select([inotify_fd], [], [], remaining)
            assert readable, f"timed out waiting for filesystem event on {log_path}"
            os.read(inotify_fd, 65536)

        def close_watcher() -> None:
            os.close(inotify_fd)

    try:
        while True:
            content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            matches = content.count(pattern) if fixed else len(re.findall(pattern, content))
            if matches >= count:
                return content
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"timed out waiting for {pattern!r} in {log_path}:\n{content}"
            wait_for_change(remaining)
    finally:
        close_watcher()


def wait_for_log(log_path: Path, text: str, *, timeout: float = 30.0) -> str:
    content = _wait_for_log_match(log_path, text, fixed=True, count=1, timeout=timeout)
    assert text in content, content
    return content


def wait_for_log_count(log_path: Path, text: str, count: int, *, timeout: float = 30.0) -> str:
    content = _wait_for_log_match(log_path, text, fixed=True, count=count, timeout=timeout)
    assert content.count(text) >= count, content
    return content


def wait_for_log_pattern(log_path: Path, pattern: str, *, timeout: float = 30.0) -> re.Match[str]:
    content = _wait_for_log_match(log_path, pattern, fixed=False, count=1, timeout=timeout)
    match = re.search(pattern, content)
    assert match is not None, content
    return match


def supervisor_pid_from_log(log_path: Path) -> int:
    content = log_path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"Supervisord connected \(pid=(\d+)\)", content)
    assert matches, content
    return int(matches[-1])


def worker_pid_from_log(log_path: Path, worker_name: str) -> int:
    content = log_path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(rf"Worker {re.escape(worker_name)}: started RUNNING \(pid (\d+),", content)
    assert matches, content
    return int(matches[-1])


def wait_for_worker_pid_from_log(log_path: Path, worker_name: str, *, timeout: float = 45.0) -> int:
    wait_for_log_pattern(
        log_path,
        rf"Worker {re.escape(worker_name)}: started RUNNING \(pid [0-9]+,",
        timeout=timeout,
    )
    return worker_pid_from_log(log_path, worker_name)


def pgrep_data_dir(data_dir: Path) -> list[str]:
    lines: list[str] = []
    seen_pids: set[int] = set()
    resolved_data_dir = data_dir.resolve()
    for process in psutil.process_iter(["pid", "ppid", "cmdline", "cwd"]):
        try:
            if process.pid == os.getpid():
                continue
            command = " ".join(process.info.get("cmdline") or [])
            process_cwd = process.info.get("cwd")
            cwd_matches = bool(process_cwd and Path(process_cwd).resolve() == resolved_data_dir)
            env_data_dir = None if cwd_matches else process.environ().get("DATA_DIR")
            env_matches = bool(env_data_dir and Path(env_data_dir).resolve() == resolved_data_dir)
            if str(data_dir) not in command and not cwd_matches and not env_matches:
                continue
            pid = int(process.info["pid"])
            seen_pids.add(pid)
            lines.append(f"{pid} {process.info.get('ppid') or 0} {command}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    for runtime_root in (Path("/tmp/archivebox"), data_dir / "tmp"):
        for config_path in runtime_root.glob("*/supervisord.conf"):
            try:
                config_text = config_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if str(data_dir) not in config_text:
                continue
            pid_path = config_path.with_name("supervisord.pid")
            try:
                pid = int(pid_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            if not pid_is_alive(pid):
                continue
            if pid in seen_pids:
                continue
            try:
                process = psutil.Process(pid)
                lines.append(f"{pid} {process.ppid()} {' '.join(process.cmdline())}")
                seen_pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    return sorted(set(lines))


def assert_no_processes_for_data_dir(data_dir: Path, *, timeout: float = 10.0) -> None:
    remaining = pgrep_data_dir(data_dir)
    processes = []
    for line in remaining:
        pid = int(line.split(None, 1)[0])
        try:
            processes.append(psutil.Process(pid))
        except psutil.NoSuchProcess:
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=timeout)
    final_remaining = pgrep_data_dir(data_dir)
    assert not alive and not final_remaining, "processes still reference test DATA_DIR:\n" + "\n".join(final_remaining)


def kill_processes_for_data_dir(data_dir: Path) -> None:
    processes: list[psutil.Process] = []
    for line in pgrep_data_dir(data_dir):
        try:
            pid = int(line.split(None, 1)[0])
        except (IndexError, ValueError):
            continue
        if pid != os.getpid():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            else:
                processes.append(psutil.Process(pid))
    _gone, alive = psutil.wait_procs(processes, timeout=10)
    assert not alive, f"processes did not stop after SIGTERM: {[proc.pid for proc in alive]}"


def start_archivebox_server(
    cwd: Path,
    *,
    port: int,
    env: dict[str, str] | None = None,
    daemonize: bool | None = None,
    log_name: str | None = None,
):
    if daemonize is None:
        daemonize = log_name is None

    args = ["server", f"127.0.0.1:{port}"]
    if daemonize:
        args.insert(1, "--daemonize")

    log_path = cwd / log_name if log_name else None
    log = log_path.open("w", encoding="utf-8") if log_path else None
    proc = run_archivebox_cmd(
        args,
        cwd=cwd,
        env=env or cli_env(live=True),
        stdout=log if log else None,
        stderr=subprocess.STDOUT if log else None,
        text=daemonize,
        start_new_session=not daemonize,
        wait=daemonize,
    )
    if log is not None:
        log.close()
    proc.log_path = log_path
    if daemonize:
        server_log_path = cwd / "logs" / "server.log"
        server_log = server_log_path.read_text(encoding="utf-8", errors="replace") if server_log_path.exists() else ""
        assert proc.returncode == 0, f"{proc.stderr or proc.stdout}\n\nSERVER LOG:\n{server_log[-12000:]}"
        return proc

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = log_path.read_text(encoding="utf-8", errors="replace") if log_path else ""
            raise AssertionError(f"ArchiveBox server exited before opening port {port}:\n{output}")
        output = log_path.read_text(encoding="utf-8", errors="replace") if log_path else ""
        if not re.search(r"Worker worker_daphne: started RUNNING \(pid \d+,", output):
            time.sleep(0.1)
            continue
        try:
            assert_port_open("127.0.0.1", port, timeout=0.25)
            break
        except OSError:
            time.sleep(0.1)
    else:
        output = log_path.read_text(encoding="utf-8", errors="replace") if log_path else ""
        raise AssertionError(f"ArchiveBox server did not open port {port} within 30 seconds:\n{output}")
    return proc


def stop_archivebox_process(proc: subprocess.Popen[str], sig=signal.SIGTERM, *, timeout: float = 15.0) -> str:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, OSError):
        try:
            os.kill(proc.pid, sig)
        except ProcessLookupError:
            pass
    stdout, _stderr = proc.communicate(timeout=timeout)
    return stdout or ""


def run_queued_crawls(cwd: Path, env: dict[str, str] | None = None, timeout: int = 180) -> None:
    script = """
import json
from archivebox.crawls.models import Crawl
print(json.dumps([str(crawl_id) for crawl_id in Crawl.objects.order_by("created_at").values_list("id", flat=True)]))
"""
    _cmd_result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=cwd, timeout=60, env=env)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout
    crawl_ids = json.loads(stdout.strip().splitlines()[-1])
    for crawl_id in crawl_ids:
        _cmd_result = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=cwd, timeout=timeout, env=env)
        stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert returncode == 0, f"archivebox run --crawl-id={crawl_id} failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"


def _run_archivebox_manage_shell(cwd: Path, env: dict[str, str], script: str, timeout: int = 60) -> str:
    result = run_archivebox_cmd(
        ["manage", "shell", "-c", script],
        cwd=cwd,
        env=env,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _archivebox_worker_state(cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    stdout = _run_archivebox_manage_shell(
        cwd,
        env,
        """
import json
from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker
supervisor = get_existing_supervisord_process(quiet=True)
workers = {}
if supervisor:
    for name in ("worker_daphne", "worker_sonic", "worker_runner"):
        workers[name] = get_worker(supervisor, name)
print(json.dumps(workers, default=str))
""",
    )
    return json.loads(stdout.strip().splitlines()[-1])


def _stop_archivebox_supervisord(cwd: Path, env: dict[str, str]) -> None:
    _run_archivebox_manage_shell(
        cwd,
        env,
        "from archivebox.workers.supervisord_util import stop_existing_supervisord_process; stop_existing_supervisord_process()",
        timeout=30,
    )


def _wait_for_archivebox_workers(cwd: Path, env: dict[str, str], names: tuple[str, ...] | list[str], timeout: int = 45) -> dict[str, Any]:
    supervisord_log = cwd / "logs" / "supervisord.log"
    deadline = time.monotonic() + timeout
    for name in names:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"timed out waiting for workers {names} in {supervisord_log}"
        wait_for_log_pattern(
            supervisord_log,
            rf"success: {re.escape(name)} entered RUNNING state,",
            timeout=remaining,
        )
    state = _archivebox_worker_state(cwd, env)
    assert all(isinstance(state.get(name), dict) and state[name].get("statename") == "RUNNING" for name in names), state
    return state


def stop_process(proc: subprocess.Popen[str]) -> tuple[str, str]:
    proc.terminate()
    return proc.communicate(timeout=5)


def run_python_cwd(
    script: str,
    cwd: Path,
    timeout: int = 60,
) -> tuple[str, str, int]:
    _assert_not_repo_path(cwd, label="cwd")
    base_env = os.environ.copy()
    _assert_safe_runtime_paths(cwd=cwd, env=base_env)
    result = subprocess.run(
        [sys.executable, "-"],
        input=script,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base_env,
        timeout=timeout,
    )
    return result.stdout, result.stderr, result.returncode


# =============================================================================
# Server/API Integration Helpers
# =============================================================================

API_TEST_HOST = "api.archivebox.localhost:8000"
ADMIN_TEST_HOST = "admin.archivebox.localhost:8000"
WEB_TEST_HOST = "web.archivebox.localhost:8000"


@pytest.fixture
def admin_user(request):
    from django.contrib.auth import get_user_model

    username = f"admin_{abs(hash(request.node.nodeid))}"
    return get_user_model().objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="testpassword",
    )


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def crawl(admin_user, db):
    from archivebox.crawls.models import Crawl

    return Crawl.objects.create(
        urls="https://example.com\nhttps://example.org",
        tags_str="alpha,beta",
        created_by=admin_user,
    )


@pytest.fixture
def snapshot(crawl, db):
    from archivebox.core.models import Snapshot

    return Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )


@pytest.fixture
def tagged_data(crawl, admin_user):
    from archivebox.core.models import Snapshot, Tag

    tag = Tag.objects.create(name="Alpha Research", created_by=admin_user)
    first = Snapshot.objects.create(
        url="https://example.com/one",
        title="Example One",
        crawl=crawl,
    )
    second = Snapshot.objects.create(
        url="https://example.com/two",
        title="Example Two",
        crawl=crawl,
    )
    first.tags.add(tag)
    second.tags.add(tag)
    return tag, [first, second]


@pytest.fixture
def api_admin_user(request):
    from django.contrib.auth import get_user_model

    username = f"apiadmin_{abs(hash(request.node.nodeid))}"
    return get_user_model().objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
    )


@pytest.fixture
def api_token(api_admin_user):
    from archivebox.api.auth import get_or_create_api_token

    token = get_or_create_api_token(api_admin_user)
    assert token is not None
    return token


@pytest.fixture
def api_headers(api_token) -> dict[str, str]:
    return api_auth_headers(api_token.token, django_client=True)


def api_auth_headers(api_token: str, *, django_client: bool = False, port: int | None = None) -> dict[str, str]:
    host = f"api.archivebox.localhost:{port}" if port is not None else API_TEST_HOST
    if django_client:
        return {
            "HTTP_HOST": host,
            "HTTP_X_ARCHIVEBOX_API_KEY": api_token,
        }
    return {
        "Host": host,
        "X-ArchiveBox-API-Key": api_token,
    }


def wait_for_live_api(port: int, *, path: str = "/api/v1/docs"):
    return get_http_response(port, host=f"api.archivebox.localhost:{port}", path=path)


def live_api_request(port: int, method: str, path: str, *, api_token: str, timeout: int = 30, **kwargs):
    return requests.request(
        method,
        f"http://127.0.0.1:{port}{path}",
        headers=api_auth_headers(api_token, port=port),
        timeout=timeout,
        **kwargs,
    )


def api_client_request(
    client,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    api_token: str | None = None,
    headers: dict[str, str] | None = None,
    **kwargs,
):
    request_kwargs = dict(kwargs)
    if payload is not None:
        request_kwargs["data"] = json.dumps(payload)
        request_kwargs["content_type"] = "application/json"
    if headers is None:
        assert api_token is not None
        headers = api_auth_headers(api_token, django_client=True)
    request_kwargs.update(headers)
    return getattr(client, method.lower())(path, **request_kwargs)


def init_archive(cwd: Path) -> None:
    result = run_archivebox_cmd(
        ["init", "--quick"],
        cwd=cwd,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop_server(cwd: Path) -> None:
    script = textwrap.dedent(
        """
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
        import django
        django.setup()
        from archivebox.workers.supervisord_util import stop_existing_supervisord_process
        stop_existing_supervisord_process()
        print('stopped')
        """,
    )
    run_python_cwd(script, cwd=cwd, timeout=30)


def get_http_response(
    port: int,
    host: str,
    path: str = "/",
    timeout: float = 30.0,
    process: subprocess.Popen[str] | None = None,
) -> requests.Response:
    """Perform one blocking HTTP exchange after native server readiness."""
    if process is not None:
        returncode = process.poll()
        assert returncode is None, f"Server exited before becoming ready with code {returncode}"
    response = requests.get(
        f"http://127.0.0.1:{port}{path}",
        headers={"Host": host},
        timeout=timeout,
        allow_redirects=False,
    )
    assert response.status_code < 500, f"HTTP {response.status_code} from {host}{path}"
    return response


def make_latest_schedule_due(cwd: Path) -> None:
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from django.utils import timezone

    with use_archivebox_db(cwd):
        schedule = CrawlSchedule.objects.order_by("-created_at").select_related("template").first()
        assert schedule is not None
        Crawl.objects.filter(pk=schedule.template_id).update(
            created_at=timezone.now() - timedelta(days=2),
            modified_at=timezone.now() - timedelta(days=2),
        )


def get_snapshot_file_text(cwd: Path, url: str) -> str:
    script = textwrap.dedent(
        f"""
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
        import django
        django.setup()

        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(url={url!r}).order_by('-created_at').first()
        assert snapshot is not None, 'missing snapshot'
        assert snapshot.status == 'sealed', snapshot.status

        snapshot_dir = Path(snapshot.output_dir)
        candidates = []
        preferred_patterns = (
            'wget/**/index.html',
            'wget/**/*.html',
            'trafilatura/content.html',
            'trafilatura/content.txt',
            'defuddle/content.html',
            'defuddle/content.txt',
        )
        for pattern in preferred_patterns:
            for candidate in snapshot_dir.glob(pattern):
                if candidate.is_file():
                    candidates.append(candidate)

        if not candidates:
            for candidate in snapshot_dir.rglob('*'):
                if not candidate.is_file():
                    continue
                rel = candidate.relative_to(snapshot_dir)
                if rel.parts and rel.parts[0] == 'responses':
                    continue
                if len(rel.parts) == 1 and rel.name == 'index.html':
                    continue
                if candidate.suffix not in ('.html', '.htm', '.txt'):
                    continue
                if candidate.name in ('stdout.log', 'stderr.log'):
                    continue
                candidates.append(candidate)

        assert candidates, f'no captured html/txt files found in {{snapshot_dir}}'
        print(candidates[0].read_text(errors='ignore'))
        """,
    )
    stdout, stderr, code = run_python_cwd(script, cwd=cwd, timeout=60)
    assert code == 0, stderr
    return stdout


def wait_for_snapshot_capture(cwd: Path, url: str, timeout: int = 180) -> str:
    script = textwrap.dedent(
        f"""
        from pathlib import Path

        from archivebox.core.models import Snapshot
        snapshot = Snapshot.objects.filter(url={url!r}).order_by('-created_at').first()
        assert snapshot is not None
        index_path = snapshot.output_dir / 'index.jsonl'
        assert Path(index_path).exists()
        print(index_path)
        """,
    )
    deadline = time.monotonic() + timeout
    last_error = ""
    while True:
        result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=cwd, timeout=30)
        if result.returncode == 0:
            index_path = Path(result.stdout.strip().splitlines()[-1])
            break
        last_error = result.stderr or result.stdout
        remaining = deadline - time.monotonic()
        assert remaining > 0, last_error
        time.sleep(min(0.25, remaining))

    _wait_for_log_match(index_path, ".", fixed=False, count=1, timeout=timeout)
    while True:
        try:
            return get_snapshot_file_text(cwd, url)
        except AssertionError as err:
            last_error = str(err)
            remaining = deadline - time.monotonic()
            assert remaining > 0, last_error
            time.sleep(min(0.25, remaining))


def get_counts(cwd: Path, scheduled_url: str, one_shot_url: str) -> tuple[int, int, int]:
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    with use_archivebox_db(cwd):
        scheduled_snapshots = Snapshot.objects.filter(url=scheduled_url).count()
        one_shot_snapshots = Snapshot.objects.filter(url=one_shot_url).count()
        scheduled_crawls = Crawl.objects.filter(schedule__isnull=False, urls=scheduled_url).count()
    return scheduled_snapshots, one_shot_snapshots, scheduled_crawls


def get_depth_counts(cwd: Path) -> dict[int, int]:
    from archivebox.core.models import Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    with use_archivebox_db(cwd):
        return {depth: Snapshot.objects.filter(depth=depth).count() for depth in set(Snapshot.objects.values_list("depth", flat=True))}


def get_crawl_runtime_state(cwd: Path, crawl_id: str) -> dict[str, object]:
    from archivebox.core.models import ArchiveResult
    from archivebox.crawls.models import Crawl
    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from archivebox.workers.models import RETRY_AT_MAX

    with use_archivebox_db(cwd):
        crawl = Crawl.objects.get(id=crawl_id)
        snapshots = list(
            crawl.snapshot_set.order_by("created_at").values(
                "id",
                "url",
                "status",
                "retry_at",
            ),
        )
        results = list(
            ArchiveResult.objects.filter(snapshot__crawl=crawl)
            .order_by("snapshot_id", "plugin", "hook_name")
            .values(
                "snapshot_id",
                "plugin",
                "hook_name",
                "status",
                "retry_at",
                "output_files",
                "output_size",
            ),
        )

    return {
        "retry_at_max": RETRY_AT_MAX,
        "crawl_status": crawl.status,
        "crawl_retry_at": crawl.retry_at,
        "snapshots": snapshots,
        "results": results,
    }


def create_admin_and_token(cwd: Path) -> str:
    script = textwrap.dedent(
        """
        import os
        from datetime import timedelta
        from django.utils import timezone

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
        import django
        django.setup()

        from django.contrib.auth import get_user_model
        from archivebox.api.models import APIToken

        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username='apitestadmin',
            defaults={
                'email': 'apitestadmin@example.com',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password('testpass123')
        user.save()

        token = APIToken.objects.create(
            created_by=user,
            expires=timezone.now() + timedelta(days=1),
        )
        print(token.token)
        """,
    )
    stdout, stderr, code = run_python_cwd(script, cwd=cwd, timeout=60)
    assert code == 0, stderr
    return stdout.strip().splitlines()[-1]


def assert_archive_outputs(
    cwd: Path,
    url: str,
) -> None:
    script = textwrap.dedent(
        f"""\
        from pathlib import Path

        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(url={url!r}).order_by('-created_at').first()
        if snapshot is None:
            raise SystemExit('snapshot missing')
        if snapshot.status != 'sealed':
            raise SystemExit(f'snapshot status={{snapshot.status!r}}')

        output_rel = None
        for output in snapshot.discover_outputs():
            candidate = output.get('path')
            if not candidate or candidate.startswith('responses/'):
                continue
            if Path(snapshot.output_dir, candidate).is_file():
                output_rel = candidate
                break
        if output_rel is None:
            fallback = Path(snapshot.output_dir, 'index.jsonl')
            if fallback.exists():
                output_rel = 'index.jsonl'
        if output_rel is None:
            snapshot_dir = Path(snapshot.output_dir)
            for candidate in snapshot_dir.rglob('*'):
                if not candidate.is_file():
                    continue
                rel_path = candidate.relative_to(snapshot_dir)
                if rel_path.parts and rel_path.parts[0] == 'responses':
                    continue
                if rel_path.name in {"stdout.log", "stderr.log"}:
                    continue
                output_rel = str(rel_path)
                break
        if output_rel is None:
            raise SystemExit('snapshot output missing')

        responses_root = Path(snapshot.output_dir) / 'responses'
        if not responses_root.exists():
            raise SystemExit('responses directory missing')
        if not any(candidate.is_file() and snapshot.domain in candidate.relative_to(responses_root).parts for candidate in responses_root.rglob('*')):
            raise SystemExit(f'response file missing for domain={{snapshot.domain!r}}')

        print('READY')
        """,
    )

    stdout, stderr, returncode = run_python_cwd(script, cwd=cwd, timeout=30)
    assert returncode == 0 and "READY" in stdout, (stderr or stdout).strip()


def _get_machine_type() -> str:
    import platform

    os_name = platform.system().lower()
    arch = platform.machine().lower()
    in_docker = os.environ.get("IN_DOCKER", "").lower() in ("1", "true", "yes")
    suffix = "-docker" if in_docker else ""
    return f"{arch}-{os_name}{suffix}"


def resolve_abxpkg_binary_env(
    lib_dir: Path,
    *binary_names: str,
    env: dict[str, str] | None = None,
    deps_from: Path | list[Path] | tuple[Path, ...] | None = None,
) -> dict[str, str]:
    """Resolve required test dependencies through abxpkg's normal install path."""
    command_env = dict(env) if env is not None else os.environ.copy()
    command_env["ABXPKG_LIB_DIR"] = str(lib_dir)
    command = [
        str(Path(sys.executable).with_name("abxpkg")),
        "env",
        "--install",
        "--json",
        f"--lib={lib_dir}",
    ]
    deps_configs = [deps_from] if isinstance(deps_from, Path) else list(deps_from or ())
    command.extend(f"--deps-from={config}:required_binaries" for config in deps_configs)
    command.extend(binary_names)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=command_env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    return {str(key): str(value) for key, value in payload.items()}


def run_test_hook(
    script: Path,
    output_dir: Path,
    config: dict[str, Any] | None = None,
    timeout: int = 60,
    **arguments: Any,
):
    """Execute a shipped finite hook through abx-dl and ArchiveBox's real DB projector."""
    import asyncio

    from abx_dl.execution import execute_hook
    from abx_dl.orchestrator import create_bus
    from archivebox.machine.models import Process
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.services.process_service import ProcessService, parse_event_datetime

    resolved_script = script.resolve()
    hook = next(
        (hook for plugin in get_plugin_catalog().values() for hook in plugin.hooks if hook.path.resolve() == resolved_script),
        None,
    )
    assert hook is not None, f"shipped hook is not in the plugin catalog: {script}"
    assert not hook.is_background, f"run_test_hook only supports finite hooks: {hook.full_name}"

    env = os.environ.copy()
    for key, value in (config or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            env[key] = "true" if value else "false"
        elif isinstance(value, (dict, list, tuple)):
            env[key] = json.dumps(value)
        else:
            env[key] = str(value)
    if env.get("NODE_MODULES_DIR"):
        env.setdefault("NODE_MODULE_DIR", env["NODE_MODULES_DIR"])

    bus = create_bus(name=f"test_hook_{hook.plugin_name}", total_timeout=float(timeout) + 30.0)
    ProcessService(bus)

    async def execute_and_close():
        try:
            return await execute_hook(
                hook,
                output_dir=output_dir,
                env=env,
                arguments=arguments,
                timeout=timeout,
                bus=bus,
                process_type=Process.TypeChoices.HOOK,
            )
        finally:
            await bus.wait_until_idle()
            await bus.destroy(clear=False)

    completed = asyncio.run(execute_and_close())
    process = (
        Process.objects.filter(
            pid=completed.pid or None,
            started_at=parse_event_datetime(completed.start_ts),
        )
        .order_by("-modified_at")
        .first()
    )
    assert process is not None, f"hook completed without an ArchiveBox Process projection: {hook.full_name}"
    return process


def resolve_abxpkg_chrome_env(lib_dir: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    from abx_plugins import get_plugins_dir

    chrome_config = Path(get_plugins_dir()) / "chrome" / "config.json"
    payload = resolve_abxpkg_binary_env(
        lib_dir,
        env=env,
        deps_from=chrome_config,
    )
    chrome_binary = Path(payload["CHROME_BINARY"])
    node_binary = Path(payload["NODE_BINARY"])
    assert chrome_binary.is_file()
    assert node_binary.is_file()
    return payload


def install_real_binary(
    name: str,
    *,
    machine=None,
    binproviders: str = "env",
    overrides: dict[str, dict[str, Any]] | None = None,
):
    """Install and persist a real binary through the normal Binary lifecycle."""
    from archivebox.machine.models import Binary, Machine

    binary = Binary.objects.create(
        machine=machine or Machine.current(refresh=True),
        name=name,
        binproviders=binproviders,
        overrides=overrides or {},
        status=Binary.StatusChoices.QUEUED,
    )
    assert binary.install_claimed(lock_seconds=600)
    binary.refresh_from_db()
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.retry_at is None
    assert binary.binprovider in binary.binproviders.split(",")
    assert binary.version
    assert binary.abspath
    assert Path(binary.abspath).exists()
    return binary


@pytest.fixture(scope="class")
def real_archive_with_example(tmp_path_factory, request):
    """
    Initialize archive and add https://example.com using responses only.
    Uses cwd for DATA_DIR.
    """
    tmp_path = tmp_path_factory.mktemp("archivebox_data")
    if request.cls is not None:
        request.cls.data_dir = tmp_path

    _cmd_result = run_archivebox_cmd(
        ["init", "--quick"],
        cwd=tmp_path,
        timeout=120,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"archivebox init failed: {stderr}"

    _cmd_result = run_archivebox_cmd(
        [
            "config",
            "--set",
            "BIND_ADDR=127.0.0.1:8000",
            "BASE_URL=http://archivebox.localhost:8000",
            "PUBLIC_INDEX=True",
            "PUBLIC_ADD_VIEW=True",
        ],
        cwd=tmp_path,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"archivebox config failed: {stderr}"

    add_env = {
        "RESPONSES_ENABLED": "True",
        "SHOW_PROGRESS": "False",
        "USE_COLOR": "False",
        "RESPONSES_TIMEOUT": "30",
    }
    _cmd_result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=responses", "https://example.com"],
        cwd=tmp_path,
        timeout=600,
        env=add_env,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"archivebox add failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    assert_archive_outputs(tmp_path, "https://example.com")

    return tmp_path


# =============================================================================
# Output Assertions
# =============================================================================


def parse_jsonl_output(stdout: str) -> list[dict[str, Any]]:
    """Parse JSONL output into list of dicts via Process parser."""
    from archivebox.machine.models import Process

    return Process.parse_records_from_text(stdout or "")


def stdout_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.strip()]


def assert_jsonl_only(stdout: str) -> None:
    lines = stdout_lines(stdout)
    assert lines, "Expected stdout to contain JSONL records"
    assert all(line.lstrip().startswith("{") for line in lines), stdout


def assert_jsonl_contains_type(stdout: str, record_type: str, min_count: int = 1):
    """Assert output contains at least min_count records of type."""
    records = parse_jsonl_output(stdout)
    matching = [r for r in records if r.get("type") == record_type]
    assert len(matching) >= min_count, f"Expected >= {min_count} {record_type}, got {len(matching)}"
    return matching


def assert_jsonl_pass_through(stdout: str, input_records: list[dict[str, Any]]):
    """Assert that input records appear in output (pass-through behavior)."""
    output_records = parse_jsonl_output(stdout)
    output_ids = {r.get("id") for r in output_records if r.get("id")}

    for input_rec in input_records:
        input_id = input_rec.get("id")
        if input_id:
            assert input_id in output_ids, f"Input record {input_id} not found in output (pass-through failed)"


def assert_record_has_fields(record: dict[str, Any], required_fields: list[str]):
    """Assert record has all required fields with non-None values."""
    for field in required_fields:
        assert field in record, f"Record missing field: {field}"
        assert record[field] is not None, f"Record field is None: {field}"


# =============================================================================
# Test Data Factories
# =============================================================================


def create_test_url(domain: str = "example.com", path: str | None = None) -> str:
    """Generate unique test URL."""
    path = path or secrets.token_hex(4)
    return f"https://{domain}/{path}"


def create_test_crawl_json(urls: list[str] | None = None, **kwargs) -> dict[str, Any]:
    """Create Crawl JSONL record for testing."""
    urls = urls or [create_test_url()]
    return {
        "type": "Crawl",
        "urls": "\n".join(urls),
        "max_depth": kwargs.get("max_depth", 0),
        "tags_str": kwargs.get("tags_str", ""),
        "status": kwargs.get("status", "queued"),
        **{k: v for k, v in kwargs.items() if k not in ("max_depth", "tags_str", "status")},
    }


def create_test_snapshot_json(url: str | None = None, **kwargs) -> dict[str, Any]:
    """Create Snapshot JSONL record for testing."""
    return {
        "type": "Snapshot",
        "url": url or create_test_url(),
        "tags_str": kwargs.get("tags_str", ""),
        "status": kwargs.get("status", "queued"),
        **{k: v for k, v in kwargs.items() if k not in ("tags_str", "status")},
    }
