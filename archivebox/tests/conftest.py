"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import json
import secrets
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import shutil
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from collections.abc import Callable

import psutil
import pytest
import requests
from django.utils import timezone

pytest_plugins = ["archivebox.tests.fixtures"]

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_BASETEMP_ROOT = (REPO_ROOT / "tests" / "out").resolve()
SESSION_DATA_DIR = Path(
    os.environ.get("ARCHIVEBOX_PYTEST_SESSION_DATA_DIR") or tempfile.mkdtemp(prefix="archivebox-pytest-session-"),
).resolve()
# Force ArchiveBox imports to see a temp DATA_DIR during test collection.
os.environ["ARCHIVEBOX_PYTEST_SESSION_DATA_DIR"] = str(SESSION_DATA_DIR)
os.environ["DATA_DIR"] = str(SESSION_DATA_DIR)
(SESSION_DATA_DIR / "tests").mkdir(parents=True, exist_ok=True)
os.chdir(SESSION_DATA_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
os.environ.pop("ARCHIVE_DIR", None)
os.environ.pop("USERS_DIR", None)
os.environ.pop("CRAWL_DIR", None)
os.environ.pop("SNAP_DIR", None)


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

    for key in ("DATA_DIR", "ARCHIVE_DIR", "USERS_DIR", "CRAWL_DIR", "SNAP_DIR"):
        value = (env or {}).get(key)
        if value:
            _assert_not_repo_path(Path(value), label=key)


# =============================================================================
# CLI Helpers (defined before fixtures that use them)
# =============================================================================


def run_archivebox_cmd(
    args: list[str],
    data_dir: Path,
    stdin: str | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """
    Run archivebox command via subprocess, return (stdout, stderr, returncode).

    Args:
        args: Command arguments (e.g., ['crawl', 'create', 'https://example.com'])
        data_dir: The DATA_DIR to use
        stdin: Optional string to pipe to stdin
        timeout: Command timeout in seconds
        env: Additional environment variables

    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    cmd = [sys.executable, "-m", "archivebox"] + args

    _assert_not_repo_path(data_dir, label="DATA_DIR")
    base_env = os.environ.copy()
    base_env["DATA_DIR"] = str(data_dir)
    base_env["USE_COLOR"] = "False"
    base_env["SHOW_PROGRESS"] = "False"
    # Disable slow extractors for faster tests
    base_env["SAVE_ARCHIVEDOTORG"] = "False"
    base_env["SAVE_TITLE"] = "False"
    base_env["SAVE_FAVICON"] = "False"
    base_env["SAVE_WGET"] = "False"
    base_env["SAVE_WARC"] = "False"
    base_env["SAVE_PDF"] = "False"
    base_env["SAVE_SCREENSHOT"] = "False"
    base_env["SAVE_DOM"] = "False"
    base_env["SAVE_SINGLEFILE"] = "False"
    base_env["SAVE_READABILITY"] = "False"
    base_env["SAVE_MERCURY"] = "False"
    base_env["SAVE_GIT"] = "False"
    base_env["SAVE_YTDLP"] = "False"
    base_env["SAVE_HEADERS"] = "False"
    base_env["SAVE_HTMLTOTEXT"] = "False"

    if env:
        base_env.update(env)

    _assert_safe_runtime_paths(cwd=data_dir, env=base_env)
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=data_dir,
        env=base_env,
        timeout=timeout,
    )

    return result.stdout, result.stderr, result.returncode


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def isolate_test_runtime(tmp_path, monkeypatch):
    """
    Run each pytest test from an isolated temp cwd and restore env mutations.

    The maintained pytest suite lives under ``archivebox/tests``. Many of those
    CLI tests shell out without passing ``cwd=`` explicitly, so the safest
    contract is that every test starts in its own temp directory and any
    in-process ``os.environ`` edits are rolled back afterwards.

    Each in-process test gets an explicit temp ``DATA_DIR`` so ArchiveBox code
    never falls back to the repo cwd. Subprocess helpers that intentionally test
    cwd-based behavior remove ``DATA_DIR`` for the child process themselves.
    """
    _assert_not_repo_path(tmp_path, label="tmp_path")
    original_cwd = Path.cwd()
    original_env = os.environ.copy()
    original_chdir = os.chdir
    original_popen = subprocess.Popen
    os.chdir(tmp_path)

    def reset_machine_model_caches() -> None:
        import archivebox.machine.models as machine_models

        machine_models._CURRENT_MACHINE = None
        machine_models._CURRENT_INTERFACE = None
        machine_models._CURRENT_PROCESS = None
        machine_models._CURRENT_BINARIES.clear()

    def guarded_chdir(path: os.PathLike[str] | str) -> None:
        _assert_not_repo_path(Path(path), label="cwd")
        original_chdir(path)

    def guarded_popen(*args: Any, **kwargs: Any):
        cwd = kwargs.get("cwd")
        env = kwargs.get("env")
        if cwd is not None:
            _assert_not_repo_path(Path(cwd), label="cwd")
        _assert_safe_runtime_paths(cwd=Path(cwd) if cwd is not None else None, env=env)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(os, "chdir", guarded_chdir)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    os.environ["DATA_DIR"] = str(tmp_path)
    os.environ.pop("ARCHIVE_DIR", None)
    os.environ.pop("USERS_DIR", None)
    os.environ.pop("CRAWL_DIR", None)
    os.environ.pop("SNAP_DIR", None)
    reset_machine_model_caches()
    try:
        _assert_safe_runtime_paths(cwd=Path.cwd(), env=os.environ)
        yield
    finally:
        reset_machine_model_caches()
        original_chdir(original_cwd)
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
def hermetic_lib_dir(tmp_path, monkeypatch):
    """
    Point LIB_DIR at a tmp directory so the test can write fake binaries
    without touching the real ``~/Library/Application Support/abx/lib`` (which
    can contain symlinks to SIP-protected system binaries on macOS).

    Opt-in only: most tests should reuse the cached real LIB_DIR for speed —
    rebuilding from scratch per-test adds ~10× overhead. Use this only when
    the test synthesizes binary paths or validates LIB_DIR-relative behavior.
    """
    import archivebox.machine.models as machine_models

    lib_dir = tmp_path / "lib"
    (lib_dir / "bin").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIB_DIR", str(lib_dir))
    monkeypatch.setenv("ABXPKG_LIB_DIR", str(lib_dir))
    machine_models._CURRENT_MACHINE = None
    machine_models._CURRENT_PROCESS = None
    return lib_dir


@pytest.fixture
def initialized_archive(isolated_data_dir):
    """
    Initialize ArchiveBox archive in isolated directory.

    Runs `archivebox init` via subprocess to set up database and directories.
    """
    stdout, stderr, returncode = run_archivebox_cmd(
        ["init", "--quick"],
        data_dir=isolated_data_dir,
        timeout=60,
    )
    assert returncode == 0, f"archivebox init failed: {stderr}"
    return isolated_data_dir


@pytest.fixture
def archivebox_daemon_server(tmp_path, process, unused_tcp_port_factory):
    """
    Start a real daemonized ArchiveBox server in this test's DATA_DIR and
    always stop its supervisord before the test exits.
    """
    assert process.returncode == 0, process.stderr
    started: list[tuple[Path, dict[str, str]]] = []

    def start(**env_overrides: str):
        env = os.environ.copy()
        env.update(
            {
                "USE_COLOR": "False",
                "SHOW_PROGRESS": "False",
                "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.1",
                "SEARCH_BACKEND_SONIC_PORT": str(unused_tcp_port_factory()),
                **{key: str(value) for key, value in env_overrides.items()},
            },
        )
        port = unused_tcp_port_factory()
        result = subprocess.run(
            [sys.executable, "-m", "archivebox", "server", "--daemonize", f"127.0.0.1:{port}"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        started.append((tmp_path, env))
        return SimpleNamespace(
            data_dir=tmp_path,
            env=env,
            port=port,
            worker_state=lambda: _archivebox_worker_state(tmp_path, env),
            wait_for_workers=lambda names, timeout=45: _wait_for_archivebox_workers(tmp_path, env, names, timeout=timeout),
        )

    try:
        yield start
    finally:
        for cwd, env in reversed(started):
            _stop_archivebox_supervisord(cwd, env)


def wait_for_process(predicate: Callable[[psutil.Process, str], bool], *, timeout: float = 20.0) -> psutil.Process:
    deadline = time.time() + timeout
    last_seen: list[str] = []
    while time.time() < deadline:
        last_seen = []
        for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                command = " ".join(cmdline)
                last_seen.append(f"{proc.info.get('pid')} {proc.info.get('ppid')} {command}")
                if predicate(proc, command):
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        time.sleep(0.2)
    raise AssertionError("No matching live process found. Last seen:\n" + "\n".join(last_seen[-50:]))


# =============================================================================
# CWD-based CLI Helpers (no DATA_DIR env)
# =============================================================================


def run_archivebox_cmd_cwd(
    args: list[str],
    cwd: Path,
    stdin: str | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """
    Run archivebox command via subprocess using cwd as DATA_DIR (no DATA_DIR env).
    Returns (stdout, stderr, returncode).
    """
    cmd = [sys.executable, "-m", "archivebox"] + args

    _assert_not_repo_path(cwd, label="cwd")
    base_env = os.environ.copy()
    base_env.pop("DATA_DIR", None)
    base_env.pop("ARCHIVE_DIR", None)
    base_env.pop("USERS_DIR", None)
    base_env.pop("CRAWL_DIR", None)
    base_env.pop("SNAP_DIR", None)
    base_env["USE_COLOR"] = "False"
    base_env["SHOW_PROGRESS"] = "False"

    if env:
        base_env.update(env)

    _assert_safe_runtime_paths(cwd=cwd, env=base_env)
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base_env,
        timeout=timeout,
    )

    return result.stdout, result.stderr, result.returncode


def run_queued_crawls(cwd: Path, env: dict[str, str] | None = None, timeout: int = 180) -> None:
    script = """
import json
from archivebox.crawls.models import Crawl
print(json.dumps([str(crawl_id) for crawl_id in Crawl.objects.order_by("created_at").values_list("id", flat=True)]))
"""
    stdout, stderr, returncode = run_archivebox_cmd_cwd(["manage", "shell", "-c", script], cwd=cwd, timeout=60, env=env)
    assert returncode == 0, stderr or stdout
    crawl_ids = json.loads(stdout.strip().splitlines()[-1])
    for crawl_id in crawl_ids:
        stdout, stderr, returncode = run_archivebox_cmd_cwd(["run", f"--crawl-id={crawl_id}"], cwd=cwd, timeout=timeout, env=env)
        assert returncode == 0, f"archivebox run --crawl-id={crawl_id} failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"


def _run_archivebox_manage_shell(cwd: Path, env: dict[str, str], script: str, timeout: int = 60) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "archivebox", "manage", "shell", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
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
    deadline = time.time() + timeout
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = _archivebox_worker_state(cwd, env)
        if all(state.get(name, {}).get("statename") == "RUNNING" for name in names):
            return state
        time.sleep(1)
    return state


def stop_process(proc: subprocess.Popen[str]) -> tuple[str, str]:
    if proc.poll() is None:
        proc.terminate()
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.communicate()


def run_python_cwd(
    script: str,
    cwd: Path,
    timeout: int = 60,
) -> tuple[str, str, int]:
    _assert_not_repo_path(cwd, label="cwd")
    base_env = os.environ.copy()
    base_env.pop("DATA_DIR", None)
    base_env.pop("ARCHIVE_DIR", None)
    base_env.pop("USERS_DIR", None)
    base_env.pop("CRAWL_DIR", None)
    base_env.pop("SNAP_DIR", None)
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


def init_archive(cwd: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "archivebox", "init", "--quick"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def build_test_env(port: int, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DATA_DIR", None)
    env.update(
        {
            "PLUGINS": "wget",
            "BIND_ADDR": f"127.0.0.1:{port}",
            "BASE_URL": f"http://archivebox.localhost:{port}",
            "ALLOWED_HOSTS": "*",
            "PUBLIC_ADD_VIEW": "True",
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            "TIMEOUT": "30",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*|example\.com",
            "SAVE_ARCHIVEDOTORG": "False",
            "SAVE_TITLE": "False",
            "SAVE_FAVICON": "False",
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
            "SAVE_WGET": "True",
            "USE_CHROME": "False",
        },
    )
    env.update(extra)
    return env


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(cwd: Path, env: dict[str, str], port: int) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "archivebox", "server", "--daemonize", f"127.0.0.1:{port}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


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


def wait_for_http(port: int, host: str, path: str = "/", timeout: int = 30) -> requests.Response:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            response = requests.get(
                f"http://127.0.0.1:{port}{path}",
                headers={"Host": host},
                timeout=2,
                allow_redirects=False,
            )
            if response.status_code < 500:
                return response
        except requests.RequestException as exc:
            last_exc = exc
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for HTTP on {host}: {last_exc}")


def make_latest_schedule_due(cwd: Path) -> None:
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.tests.test_orm_helpers import use_archivebox_db

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
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            return get_snapshot_file_text(cwd, url)
        except AssertionError as err:
            last_error = err
            time.sleep(2)
    raise AssertionError(f"timed out waiting for captured content for {url}: {last_error}")


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


def wait_for_archive_outputs(
    cwd: Path,
    url: str,
    timeout: int = 120,
    interval: float = 1.0,
) -> bool:
    script = textwrap.dedent(
        f"""\
        from pathlib import Path

        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(url={url!r}).order_by('-created_at').first()
        if snapshot is None or snapshot.status != 'sealed':
            raise SystemExit(1)

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
            raise SystemExit(1)

        responses_root = Path(snapshot.output_dir) / 'responses' / snapshot.domain
        if not responses_root.exists():
            raise SystemExit(1)
        if not any(candidate.is_file() for candidate in responses_root.rglob('*')):
            raise SystemExit(1)

        print('READY')
        """,
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        stdout, _stderr, returncode = run_python_cwd(script, cwd=cwd, timeout=30)
        if returncode == 0 and "READY" in stdout:
            return True
        time.sleep(interval)
    return False


def _get_machine_type() -> str:
    import platform

    os_name = platform.system().lower()
    arch = platform.machine().lower()
    in_docker = os.environ.get("IN_DOCKER", "").lower() in ("1", "true", "yes")
    suffix = "-docker" if in_docker else ""
    return f"{arch}-{os_name}{suffix}"


def _find_cached_chrome(lib_dir: Path) -> Path | None:
    candidates = [
        lib_dir / "puppeteer" / "chromium",
        lib_dir / "puppeteer",
        lib_dir / "ms-playwright",
        lib_dir / "npm" / "node_modules" / "puppeteer" / ".local-chromium",
    ]
    for base in candidates:
        if not base.exists():
            continue
        for path in base.rglob("Chromium.app/Contents/MacOS/Chromium"):
            return path
        for path in base.rglob("chrome-linux/chrome"):
            return path
        for path in base.rglob("chrome-linux64/chrome"):
            return path
    return None


def _find_system_browser() -> Path | None:
    candidates = [
        Path("/usr/bin/chromium"),
        Path("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ensure_puppeteer(shared_lib: Path) -> None:
    npm_prefix = shared_lib / "npm"
    node_modules = npm_prefix / "node_modules"
    puppeteer_dir = node_modules / "puppeteer"
    if puppeteer_dir.exists():
        return
    npm_prefix.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PUPPETEER_SKIP_DOWNLOAD"] = "1"
    subprocess.run(
        ["npm", "install", "puppeteer"],
        cwd=str(npm_prefix),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.fixture(scope="class")
def real_archive_with_example(tmp_path_factory, request):
    """
    Initialize archive and add https://example.com using responses only.
    Uses cwd for DATA_DIR.
    """
    tmp_path = tmp_path_factory.mktemp("archivebox_data")
    if getattr(request, "cls", None) is not None:
        request.cls.data_dir = tmp_path

    stdout, stderr, returncode = run_archivebox_cmd_cwd(
        ["init", "--quick"],
        cwd=tmp_path,
        timeout=120,
    )
    assert returncode == 0, f"archivebox init failed: {stderr}"

    stdout, stderr, returncode = run_archivebox_cmd_cwd(
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
    assert returncode == 0, f"archivebox config failed: {stderr}"

    add_env = {
        "RESPONSES_ENABLED": "True",
        "SHOW_PROGRESS": "False",
        "USE_COLOR": "False",
        "RESPONSES_TIMEOUT": "30",
    }
    system_browser = _find_system_browser()
    if system_browser:
        add_env["CHROME_BINARY"] = str(system_browser)
    stdout, stderr, returncode = run_archivebox_cmd_cwd(
        ["add", "--depth=0", "--plugins=responses", "https://example.com"],
        cwd=tmp_path,
        timeout=600,
        env=add_env,
    )
    assert returncode == 0, f"archivebox add failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    ready = wait_for_archive_outputs(tmp_path, "https://example.com", timeout=60)
    assert ready, f"archivebox add did not produce required outputs within timeout:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    return tmp_path


# =============================================================================
# Output Assertions
# =============================================================================


def parse_jsonl_output(stdout: str) -> list[dict[str, Any]]:
    """Parse JSONL output into list of dicts via Process parser."""
    from archivebox.machine.models import Process

    return Process.parse_records_from_text(stdout or "")


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
