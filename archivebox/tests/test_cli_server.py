"""
Tests for archivebox server command.
Verify server can start (basic smoke tests only, no full server testing).
"""

import asyncio
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from archivebox.tests.conftest import (
    _wait_for_archivebox_workers,
    assert_no_processes_for_data_dir,
    assert_port_open,
    cli_env,
    find_process,
    get_free_port,
    kill_processes_for_data_dir,
    pid_is_alive,
    resolve_abxpkg_binary_env,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
    wait_for_log_count,
    wait_for_pid_to_disappear,
)


def _resolve_sonic_env(data_dir: Path) -> dict[str, str]:
    from abx_plugins import get_plugins_dir

    lib_dir = data_dir / "lib"
    install_result = run_archivebox_cmd(
        ["install", "search_backend_sonic"],
        cwd=data_dir,
        env={"ABXPKG_LIB_DIR": str(lib_dir)},
        default_cli_env=True,
    )
    assert install_result.returncode == 0, install_result.stderr or install_result.stdout
    config = Path(get_plugins_dir()) / "search_backend_sonic" / "config.json"
    resolved = resolve_abxpkg_binary_env(lib_dir, deps_from=config)
    assert Path(resolved["SONIC_BINARY"]).is_file()
    return resolved


def test_server_auth_secret_and_cookie_settings_are_restart_stable(tmp_path):
    """Admin sessions must survive `archivebox server` restarts for a collection."""
    from archivebox.config.collection import write_config_file

    (tmp_path / ".archivebox_id").write_text("testcoll")
    first_env = os.environ.copy()
    first_env["BASE_URL"] = "http://archivebox.localhost:9292"

    first = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os;"
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings');"
                "import django;"
                "django.setup();"
                "from django.conf import settings;"
                "print(settings.SECRET_KEY);"
                "print(settings.SESSION_ENGINE);"
                "print(settings.SESSION_COOKIE_NAME);"
                "print(settings.SESSION_COOKIE_DOMAIN);"
                "print(settings.SESSION_COOKIE_SECURE);"
                "print(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
        env=first_env,
    )
    first_lines = first.stdout.strip().splitlines()
    assert first_lines[0], first.stderr

    # Simulate the next `archivebox server` process, reading only persisted
    # collection config. If SECRET_KEY falls back to the random default_factory
    # here, Django will reject existing signed session cookies after restart.
    write_config_file({"BASE_URL": "http://archivebox.localhost:9292"})
    second_env = os.environ.copy()
    second_env.pop("BASE_URL", None)
    second = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os;"
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings');"
                "import django;"
                "django.setup();"
                "from django.conf import settings;"
                "print(settings.SECRET_KEY);"
                "print(settings.SESSION_ENGINE);"
                "print(settings.SESSION_COOKIE_NAME);"
                "print(settings.SESSION_COOKIE_DOMAIN);"
                "print(settings.SESSION_COOKIE_SECURE);"
                "print(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
        env=second_env,
    )

    assert second.stdout.strip().splitlines() == first_lines
    assert first_lines[1] == "django.contrib.sessions.backends.db"
    assert first_lines[2].startswith("archivebox_sessionid_")
    assert first_lines[3:] == ["None", "False", "False"]


def test_https_base_url_enables_proxy_ssl_header_and_secure_cookies(tmp_path):
    (tmp_path / ".archivebox_id").write_text("testcoll")
    env = os.environ.copy()
    env["BASE_URL"] = "https://archive.example.com"
    env["DJANGO_SETTINGS_MODULE"] = "archivebox.core.settings"
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env.get('PYTHONPATH', '')}"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django, json;"
                "django.setup();"
                "from django.conf import settings;"
                "print(json.dumps({"
                "'csrf_secure': settings.CSRF_COOKIE_SECURE,"
                "'session_secure': settings.SESSION_COOKIE_SECURE,"
                "'proxy_ssl_header': settings.SECURE_PROXY_SSL_HEADER,"
                "}))"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=tmp_path,
    )

    assert json.loads(result.stdout) == {
        "csrf_secure": True,
        "session_secure": True,
        "proxy_ssl_header": ["HTTP_X_FORWARDED_PROTO", "https"],
    }


def test_unconfigured_base_url_enables_proxy_ssl_header_without_secure_cookies(tmp_path):
    (tmp_path / ".archivebox_id").write_text("testcoll")
    env = os.environ.copy()
    env["BASE_URL"] = ""
    env["DJANGO_SETTINGS_MODULE"] = "archivebox.core.settings"
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env.get('PYTHONPATH', '')}"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django, json;"
                "django.setup();"
                "from django.conf import settings;"
                "print(json.dumps({"
                "'csrf_secure': settings.CSRF_COOKIE_SECURE,"
                "'session_secure': settings.SESSION_COOKIE_SECURE,"
                "'proxy_ssl_header': settings.SECURE_PROXY_SSL_HEADER,"
                "}))"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=tmp_path,
    )

    assert json.loads(result.stdout) == {
        "csrf_secure": False,
        "session_secure": False,
        "proxy_ssl_header": ["HTTP_X_FORWARDED_PROTO", "https"],
    }


def test_sqlite_connections_use_explicit_busy_timeout():
    from archivebox.core.settings import SQLITE_CONNECTION_OPTIONS

    assert SQLITE_CONNECTION_OPTIONS["OPTIONS"]["timeout"] == 30.0
    assert "PRAGMA busy_timeout = 30000;" in SQLITE_CONNECTION_OPTIONS["OPTIONS"]["init_command"]
    assert "PRAGMA journal_mode = WAL;" in SQLITE_CONNECTION_OPTIONS["OPTIONS"]["init_command"]


def test_docker_sqlite_never_uses_wal_on_host_shared_collection(tmp_path):
    """Docker collections must not expose a WAL database through /data.

    Docker Desktop/OrbStack bind mounts cross the Linux VM/host locking
    boundary. A container WAL writer plus a host-side sqlite reader can make
    the writer SIGBUS and leave index.sqlite3 malformed; the reader does not
    need to write. Run a fresh real settings process with Docker identity so a
    host test cannot accidentally pass by reusing this process's non-Docker
    config imports.
    """
    env = os.environ.copy()
    env["IN_DOCKER"] = "True"
    env["DJANGO_SETTINGS_MODULE"] = "archivebox.core.settings"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django;"
                "django.setup();"
                "from django.db import connection;"
                "cursor=connection.cursor();"
                "cursor.execute('CREATE TABLE journal_probe (value INTEGER)');"
                "cursor.execute('INSERT INTO journal_probe VALUES (1)');"
                "cursor.execute('PRAGMA journal_mode');"
                "print(cursor.fetchone()[0]);"
                "cursor.close();"
                "connection.close()"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().lower() == "delete"
    assert not tmp_path.joinpath("index.sqlite3-wal").exists()
    assert not tmp_path.joinpath("index.sqlite3-shm").exists()


def test_docker_rejects_explicit_wal_override(tmp_path):
    """An old config or environment override must not bypass the invariant."""
    env = os.environ.copy()
    env["IN_DOCKER"] = "True"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("from archivebox.config.common import DatabaseConfig;DatabaseConfig(SQLITE_JOURNAL_MODE='WAL')"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "WAL is unsafe for Docker collections" in result.stderr


def test_docker_postgres_ignores_irrelevant_sqlite_wal_override(tmp_path):
    """The Docker SQLite safety invariant must not reject PostgreSQL.

    Operators can switch an existing deployment to PostgreSQL while an old
    SQLITE_JOURNAL_MODE setting remains in ArchiveBox.conf or the environment.
    PostgreSQL never consumes that SQLite pragma, so rejecting the otherwise
    valid configuration would prevent ArchiveBox from starting without making
    any database safer.
    """
    env = os.environ.copy()
    env["IN_DOCKER"] = "True"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from archivebox.config.common import DatabaseConfig;"
                "config=DatabaseConfig(DATABASE_ENGINE='postgres',SQLITE_JOURNAL_MODE='WAL');"
                "print(config.DATABASE_ENGINE)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "postgres"


def test_server_shows_usage_info(initialized_archive):
    """Test that server command shows usage or starts."""

    # Just check that the command is recognized
    # We won't actually start a full server in tests
    result = run_archivebox_cmd(
        ["server", "--help"],
        timeout=10,
    )

    assert result.returncode == 0
    assert "server" in result.stdout.lower() or "http" in result.stdout.lower()


def test_server_help_lists_runtime_options(initialized_archive):
    """Test that server help exposes the current runtime options."""

    # Check init flag is recognized
    result = run_archivebox_cmd(
        ["server", "--help"],
        timeout=10,
    )

    assert result.returncode == 0
    assert "--daemonize" in result.stdout
    assert "--reload" in result.stdout


@pytest.mark.timeout(120)
def test_server_starts_with_legacy_ipv6_listen_host(initialized_archive):
    """IPv6 brackets in a legacy LISTEN_HOST must not break the startup banner."""

    port = get_free_port()
    env = cli_env(live=True, BASE_URL="", LISTEN_HOST=f"[::]:{port}")
    server = None
    try:
        server = start_archivebox_server(
            initialized_archive,
            port=port,
            log_name="server-legacy-ipv6-listen-host.log",
            env=env,
        )
        log_text = server.log_path.read_text(encoding="utf-8", errors="replace")
        assert f"http://[::]:{port}/admin/" in log_text
        assert "MarkupError" not in log_text
    finally:
        if server is not None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(initialized_archive)


def test_runner_worker_uses_active_archivebox_module():
    from archivebox.workers.supervisord_util import RUNNER_WORKER, archivebox_cmd

    worker = RUNNER_WORKER()
    assert shlex.split(worker["command"]) == archivebox_cmd("run", "--daemon")
    assert worker["autorestart"] == "true"
    assert 'ARCHIVEBOX_RUNNER_DAEMON="1"' in worker["environment"]


def test_runtime_binary_wins_over_ambient_system_path(tmp_path):
    env = os.environ.copy()
    env["ABXPKG_LIB_DIR"] = str(tmp_path / "lib")
    env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from archivebox.workers.supervisord_util import resolve_env_binary; print(resolve_env_binary('python3').resolve())",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert Path(result.stdout.strip().splitlines()[-1]) == Path(sys.executable).resolve()


def test_daphne_worker_uses_default_application_close_timeout():
    from archivebox.workers.supervisord_util import SERVER_WORKER

    command = SERVER_WORKER("127.0.0.1", "8000")["command"]

    assert "daphne" in command
    assert "--application-close-timeout=0" not in command


def test_supervisord_parent_watchdog_does_not_start_another_archivebox_runtime():
    from archivebox.workers import supervisord_util

    worker = supervisord_util.SUPERVISORD_PARENT_WATCHDOG_WORKER(
        owner_pid=101,
        owner_started_at=1001.5,
        supervisord_pid=202,
        supervisord_started_at=2002.5,
    )
    command = shlex.split(worker["command"])
    watchdog_script = Path(supervisord_util.__file__).with_name("supervisord_parent_watchdog.py")

    assert command == [
        sys.executable,
        str(watchdog_script),
        "--owner-pid=101",
        "--owner-started-at=1001.5",
        "--supervisord-pid=202",
        "--supervisord-started-at=2002.5",
    ]
    assert Path(command[1]).name == "supervisord_parent_watchdog.py"
    assert "archivebox" not in Path(command[0]).name
    assert "manage" not in command


def test_server_worker_memory_preflight_fails_before_starting_supervisord(capsys):
    from archivebox.workers.supervisord_util import (
        MIN_SERVER_WORKER_AVAILABLE_MEMORY_BYTES,
        require_server_worker_memory,
    )

    require_server_worker_memory(MIN_SERVER_WORKER_AVAILABLE_MEMORY_BYTES)
    with pytest.raises(SystemExit) as err:
        require_server_worker_memory(MIN_SERVER_WORKER_AVAILABLE_MEMORY_BYTES - 1)

    assert err.value.code == 1
    output = capsys.readouterr().err
    assert "Not enough available memory" in output
    assert "No server, runner, or Sonic workers were started" in output


def test_reload_workers_use_active_archivebox_module():
    from archivebox.workers.supervisord_util import RUNNER_WATCH_WORKER, RUNSERVER_WORKER, archivebox_cmd

    runserver = RUNSERVER_WORKER("127.0.0.1", "8000", reload=True)
    watcher = RUNNER_WATCH_WORKER("http://127.0.0.1:8000")

    assert runserver["name"] == "worker_runserver"
    assert shlex.split(runserver["command"]) == archivebox_cmd("manage", "runserver", "127.0.0.1:8000")
    assert 'ARCHIVEBOX_RUNSERVER="1"' in runserver["environment"]
    assert 'ARCHIVEBOX_AUTORELOAD="1"' in runserver["environment"]
    assert 'ARCHIVEBOX_RUNSERVER_BIND_URL="http://127.0.0.1:8000"' in runserver["environment"]

    assert watcher["name"] == "worker_runner_watch"
    assert shlex.split(watcher["command"]) == archivebox_cmd("manage", "runner_watch", "--bind-url=http://127.0.0.1:8000")


def test_server_daemon_starts_real_plugin_owned_sonic_worker(initialized_archive, archivebox_daemon_server):
    sonic_env = _resolve_sonic_env(initialized_archive)
    server = archivebox_daemon_server(
        SEARCH_BACKEND_ENGINE="sonic",
        **sonic_env,
    )
    state = server.wait_for_workers(("worker_daphne", "worker_sonic", "worker_runner"))

    assert state["worker_daphne"]["statename"] == "RUNNING", state
    assert state["worker_runner"]["statename"] == "RUNNING", state
    assert state["worker_sonic"]["statename"] == "RUNNING", state
    assert "sonic" in state["worker_sonic"]["name"]


@pytest.mark.timeout(300)
@pytest.mark.django_db(transaction=True)
def test_foreground_runner_starts_enabled_plugin_daemon_before_snapshot_hooks(initialized_archive, recursive_test_site):
    from archivebox.core.models import ArchiveResult
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(
        PLUGINS="wget",
        SEARCH_BACKEND_SONIC_HOST_NAME="127.0.0.1",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
        ABXPKG_LIB_DIR=str(initialized_archive / "lib"),
    )
    result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=wget,search_backend_sonic", recursive_test_site["root_url"]],
        cwd=initialized_archive,
        env=env,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    with use_archivebox_db(initialized_archive):
        sonic_result = ArchiveResult.objects.get(plugin="search_backend_sonic")
    assert sonic_result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert sonic_result.output_str.endswith("kb text indexed")
    supervisord_log = (initialized_archive / "logs" / "supervisord.log").read_text(encoding="utf-8", errors="replace")
    assert "spawned: 'worker_sonic' with pid" in supervisord_log


def test_server_daemon_restarts_runner_killed_by_signal(archivebox_daemon_server):
    server = archivebox_daemon_server(
        SEARCH_BACKEND_ENGINE="sqlite",
    )
    state = server.wait_for_workers(("worker_daphne", "worker_runner"))
    old_runner_pid = state["worker_runner"]["pid"]
    supervisord_log = server.data_dir / "logs" / "supervisord.log"
    spawn_text = "spawned: 'worker_runner' with pid"
    spawn_count = supervisord_log.read_text(encoding="utf-8", errors="replace").count(spawn_text)

    os.kill(old_runner_pid, signal.SIGTERM)

    wait_for_log_count(supervisord_log, spawn_text, spawn_count + 1, timeout=30)
    state = server.worker_state()
    runner = state["worker_runner"]
    assert runner["statename"] == "RUNNING", state
    assert runner["pid"] != old_runner_pid, state

    assert state["worker_daphne"]["statename"] == "RUNNING", state


def test_live_server_machine_search_engine_update_reaches_subsequent_snapshot_runtime(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="ripgrep")
    server.wait_for_workers(("worker_daphne", "worker_runner"))

    setup_result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django;"
                "django.setup();"
                "from archivebox.base_models.models import get_or_create_system_user_pk;"
                "from archivebox.crawls.models import Crawl;"
                "from archivebox.core.models import Snapshot;"
                "from archivebox.machine.models import Machine;"
                "machine = Machine.current(refresh=True);"
                "machine.config = {**dict(machine.config or {}), 'SEARCH_BACKEND_ENGINE': 'sqlite'};"
                "machine.save(update_fields=['config', 'modified_at']);"
                "crawl = Crawl.objects.create("
                "urls='https://example.com/live-machine-search-config',"
                "created_by_id=get_or_create_system_user_pk(),"
                "config={},"
                ");"
                "snapshot = Snapshot.objects.create("
                "url='https://example.com/live-machine-search-config',"
                "crawl=crawl,"
                ");"
                "print(snapshot.id)"
            ),
        ],
        cwd=server.data_dir,
        env=server.env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert setup_result.returncode == 0, setup_result.stderr or setup_result.stdout
    snapshot_id = setup_result.stdout.strip().splitlines()[-1]

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django,json;"
                "django.setup();"
                "from archivebox.core.models import Snapshot;"
                "from archivebox.config.common import get_config;"
                f"snapshot = Snapshot.objects.select_related('crawl').get(id='{snapshot_id}');"
                "runtime = get_config(snapshot=snapshot).for_crawl_runtime("
                "crawl=snapshot.crawl,"
                "snapshot=snapshot,"
                "extra_context={'snapshot_id': str(snapshot.id)},"
                ");"
                "print(json.dumps({"
                "'sqlite_enabled': runtime.get('SEARCH_BACKEND_SQLITE_ENABLED'),"
                "'engine_in_runtime': 'SEARCH_BACKEND_ENGINE' in runtime,"
                "}))"
            ),
        ],
        cwd=server.data_dir,
        env=server.env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    resolved = json.loads(result.stdout.strip().splitlines()[-1])
    assert resolved == {"sqlite_enabled": True, "engine_in_runtime": False}


def test_sonic_worker_is_disabled_when_sonic_disabled(archivebox_daemon_server):
    server = archivebox_daemon_server(
        SEARCH_BACKEND_ENGINE="sonic",
        SEARCH_BACKEND_SONIC_ENABLED="False",
    )
    state = server.worker_state()

    assert state["worker_sonic"] is None, state


def test_sonic_daemon_event_handler_accepts_real_running_worker(initialized_archive, archivebox_daemon_server):
    from abx_dl.events import ProcessStdoutEvent
    from abx_dl.orchestrator import create_bus
    from abx_plugins.plugins.search_backend_sonic.daemon import prepare_sonic_daemon

    from archivebox.search.sonic_daemon import register_sonic_daemon_event_handler

    sonic_port = get_free_port()
    sonic_env = _resolve_sonic_env(initialized_archive)
    server = archivebox_daemon_server(
        SEARCH_BACKEND_ENGINE="sonic",
        SEARCH_BACKEND_SONIC_PORT=str(sonic_port),
        **sonic_env,
    )
    state = server.wait_for_workers(("worker_sonic",))
    assert state["worker_sonic"]["statename"] == "RUNNING", state

    daemon_event = prepare_sonic_daemon(
        SimpleNamespace(
            DATA_DIR=str(server.data_dir),
            SEARCH_BACKEND_SONIC_ENABLED=True,
            SEARCH_BACKEND_SONIC_HOST_NAME="127.0.0.1",
            SEARCH_BACKEND_SONIC_PORT=sonic_port,
            SEARCH_BACKEND_SONIC_PASSWORD="SecretPassword",
            SONIC_BINARY=sonic_env["SONIC_BINARY"],
        ),
    )

    async def run_test():
        bus = create_bus(name="test_sonic_daemon_event_handler_accepts_real_running_worker")
        try:
            register_sonic_daemon_event_handler(bus)
            event = await bus.emit(
                ProcessStdoutEvent(
                    line=json.dumps(daemon_event.to_record()),
                ),
            ).now()
            await event.event_results_list()
        finally:
            await bus.destroy()

    asyncio.run(run_test())


def test_supervisord_sync_does_not_start_duplicate_sonic_listener(initialized_archive, db):
    from abx_plugins.plugins.search_backend_sonic.daemon import get_sonic_supervisord_worker

    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from archivebox.workers.supervisord_util import (
        get_or_create_supervisord_process,
        get_worker,
        stop_existing_supervisord_process,
        sync_supervisord_workers,
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    sonic_port = listener.getsockname()[1]
    worker = get_sonic_supervisord_worker(
        SimpleNamespace(
            DATA_DIR=str(initialized_archive),
            SEARCH_BACKEND_ENGINE="sonic",
            SEARCH_BACKEND_SONIC_HOST_NAME="127.0.0.1",
            SEARCH_BACKEND_SONIC_PORT=sonic_port,
            SEARCH_BACKEND_SONIC_PASSWORD="SecretPassword",
            SONIC_BINARY="sonic",
        ),
    )
    assert worker is not None

    try:
        with use_archivebox_db(initialized_archive):
            supervisor = get_or_create_supervisord_process(daemonize=False)
            state = sync_supervisord_workers(supervisor, [(worker, False)], prune=True)
            sonic_state = state["worker_sonic"]
            assert sonic_state["statename"] != "RUNNING", sonic_state
            assert get_worker(supervisor, "worker_sonic")["statename"] != "RUNNING"
    finally:
        listener.close()
        with use_archivebox_db(initialized_archive):
            stop_existing_supervisord_process()


def test_supervisord_takeover_stops_all_live_process_rows(initialized_archive, db):
    import psutil
    from django.utils import timezone

    from archivebox.config import CONSTANTS
    from archivebox.machine.models import Machine, Process
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env()
    procs = []
    try:
        for _index in range(2):
            proc = run_archivebox_cmd(
                ["run", "--daemon"],
                cwd=initialized_archive,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                wait=False,
            )
            procs.append(proc)
            started_at = datetime.fromtimestamp(psutil.Process(proc.pid).create_time(), tz=timezone.get_current_timezone())
            with use_archivebox_db(initialized_archive):
                Process.objects.create(
                    machine=Machine.current(),
                    process_type=Process.TypeChoices.SUPERVISORD,
                    worker_type="supervisord",
                    pwd=str(CONSTANTS.DATA_DIR),
                    cmd=[],
                    pid=proc.pid,
                    started_at=started_at,
                    status=Process.StatusChoices.RUNNING,
                )

        with use_archivebox_db(initialized_archive):
            from archivebox.workers.supervisord_util import stop_existing_supervisord_process

            stop_existing_supervisord_process()

        for proc in procs:
            proc.wait(timeout=10)
        with use_archivebox_db(initialized_archive):
            assert not Process.objects.filter(
                process_type=Process.TypeChoices.SUPERVISORD,
                status=Process.StatusChoices.RUNNING,
                pwd=str(CONSTANTS.DATA_DIR),
            ).exists()
    finally:
        for proc in procs:
            stop_archivebox_process(proc, signal.SIGTERM)


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    ("stop_signal", "expected_notice"),
    [
        (signal.SIGHUP, "Got SIGHUP"),
        (signal.SIGINT, "Got SIGINT"),
        (signal.SIGTERM, "Got SIGTERM"),
        (signal.SIGKILL, None),
    ],
)
def test_live_server_signal_exit_and_resume_uses_existing_supervisor_state(initialized_archive, stop_signal, expected_notice):

    env = cli_env(live=True)
    port = get_free_port()
    server = None
    resumed = None
    try:
        server = start_archivebox_server(initialized_archive, port=port, log_name=f"server-{stop_signal.name}.log", env=env)
        server_log = server.log_path

        os.kill(server.pid, stop_signal)
        server.wait(timeout=20)

        if expected_notice:
            log_text = server_log.read_text(encoding="utf-8", errors="replace")
            assert expected_notice in log_text
            assert "ArchiveBox server shut down gracefully" in log_text
            assert_no_processes_for_data_dir(initialized_archive, timeout=12)

        resumed = start_archivebox_server(initialized_archive, port=port, log_name=f"server-{stop_signal.name}-resumed.log", env=env)
        resumed_log = resumed.log_path
        _cmd_result = run_archivebox_cmd(["status"], cwd=initialized_archive, env=env, timeout=60)
        stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert returncode == 0, stderr or stdout

        os.kill(resumed.pid, signal.SIGTERM)
        resumed.wait(timeout=20)
        resumed_text = resumed_log.read_text(encoding="utf-8", errors="replace")
        assert "Got SIGTERM" in resumed_text
        assert "ArchiveBox server shut down gracefully" in resumed_text
        assert_no_processes_for_data_dir(initialized_archive, timeout=12)
    finally:
        for proc in (server, resumed):
            if proc is not None:
                stop_archivebox_process(proc, signal.SIGTERM)
        kill_processes_for_data_dir(initialized_archive)


@pytest.mark.timeout(180)
def test_live_daemonized_server_keeps_supervisord_owned_by_archivebox_parent(initialized_archive):

    env = cli_env(live=True)
    port = get_free_port()
    bind_url = f"http://127.0.0.1:{port}"
    try:
        _cmd_result = run_archivebox_cmd(
            ["server", "--daemonize", f"127.0.0.1:{port}"],
            cwd=initialized_archive,
            env=env,
            timeout=90,
        )
        stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert returncode == 0, stderr or stdout
        _wait_for_archivebox_workers(initialized_archive, env, ("worker_daphne", "worker_runner"), timeout=30)
        assert_port_open("127.0.0.1", port, timeout=30)

        server_process = find_process(
            lambda _proc, command: "archivebox" in command and " server " in f" {command} " and bind_url.replace("http://", "") in command,
        )
        supervisord = find_process(
            lambda proc, command: proc.ppid() == server_process.pid and "supervisord" in command,
        )
        find_process(
            lambda proc, command: proc.ppid() == supervisord.pid and "supervisord_parent_watchdog.py" in command,
        )

        os.kill(server_process.pid, signal.SIGTERM)
        wait_for_pid_to_disappear(server_process.pid, timeout=10)
        wait_for_pid_to_disappear(supervisord.pid, timeout=20)
        assert_no_processes_for_data_dir(initialized_archive, timeout=12)
    finally:
        kill_processes_for_data_dir(initialized_archive)
        assert_no_processes_for_data_dir(initialized_archive, timeout=12)


@pytest.mark.timeout(240)
def test_live_servers_in_different_data_dirs_do_not_interfere(initialized_archive):

    first_data_dir = initialized_archive
    second_data_dir = initialized_archive.parent / f"{initialized_archive.name}-second"
    second_data_dir.mkdir()
    second_env = cli_env(live=True)
    _cmd_result = run_archivebox_cmd(["init"], cwd=second_data_dir, env=second_env, timeout=90)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout

    first_port = get_free_port()
    second_port = get_free_port()
    first = None
    second = None
    first_resumed = None
    try:
        first = start_archivebox_server(
            first_data_dir,
            port=first_port,
            log_name="server-first-data-dir.log",
            env=cli_env(live=True),
        )
        second = start_archivebox_server(second_data_dir, port=second_port, log_name="server-second-data-dir.log", env=second_env)

        _cmd_result = run_archivebox_cmd(
            ["status"],
            cwd=first_data_dir,
            env=cli_env(live=True),
            timeout=60,
        )
        first_stdout, first_stderr, first_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        _cmd_result = run_archivebox_cmd(
            ["status"],
            cwd=second_data_dir,
            env=second_env,
            timeout=60,
        )
        second_stdout, second_stderr, second_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert first_returncode == 0, first_stderr or first_stdout
        assert second_returncode == 0, second_stderr or second_stdout

        stop_archivebox_process(first, signal.SIGTERM)
        first = None
        assert pid_is_alive(second.pid), "stopping one DATA_DIR server must not stop another DATA_DIR server"

        first_resumed = start_archivebox_server(
            first_data_dir,
            port=first_port,
            log_name="server-first-data-dir-resumed.log",
            env=cli_env(live=True),
        )
        assert pid_is_alive(second.pid), "restarting one DATA_DIR server must not take over another DATA_DIR supervisor"
    finally:
        for proc in (first, first_resumed, second):
            if proc is not None:
                stop_archivebox_process(proc, signal.SIGTERM)
        kill_processes_for_data_dir(first_data_dir)
        kill_processes_for_data_dir(second_data_dir)
        assert_no_processes_for_data_dir(first_data_dir, timeout=12)
        assert_no_processes_for_data_dir(second_data_dir, timeout=12)
