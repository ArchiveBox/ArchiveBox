"""Supervisor input: executable resolution, worker commands, and config files."""

import csv
import json
import os
import shlex
import sys
from functools import cache
from pathlib import Path

from archivebox.config import CONSTANTS
from archivebox.config.paths import SUPERVISORD_SOCKET_FILENAME, get_or_create_working_tmp_dir
from archivebox.config.permissions import ARCHIVEBOX_USER

LOG_FILE_NAME = "supervisord.log"


CONFIG_FILE_NAME = "supervisord.conf"


PID_FILE_NAME = "supervisord.pid"


WORKERS_DIR_NAME = "workers"


def archivebox_cmd(*args: str) -> list[str]:
    return [str(resolve_env_binary("archivebox")), *args]


def resolve_env_binary(name: str) -> Path:
    from abxpkg import EnvProvider

    from archivebox.config.common import get_config

    lib_dir = Path(os.environ.get("ABXPKG_LIB_DIR") or get_config().ABXPKG_LIB_DIR)
    env_root = lib_dir / "env"
    runtime_bin_dir = Path(sys.executable).parent
    provider_path = os.pathsep.join(
        str(path)
        for path in (
            str(runtime_bin_dir),
            *os.environ.get("PATH", "").split(os.pathsep),
        )
        if path
    )
    provider = EnvProvider(install_root=env_root, PATH=provider_path)
    if name == "daphne":
        from importlib.metadata import version

        provider = provider.get_provider_with_overrides(overrides={name: {"version": version("daphne")}})
    loaded = provider.load(name)
    if loaded is None or loaded.loaded_abspath is None:
        raise RuntimeError(f"abxpkg could not resolve {name}")
    return Path(loaded.loaded_abspath)


def RUNNER_WORKER():
    return {
        "name": "worker_runner",
        "command": shlex.join(archivebox_cmd("run", "--daemon")),
        "autostart": "false",
        "autorestart": "true",
        # Mark the long-lived runner child so its own SIGINT/SIGTERM path exits
        # with a signal code instead of running foreground server cleanup. That
        # keeps "kill just archivebox run --daemon" as a worker restart event;
        # only killing the parent server or supervisord should stop the stack.
        "environment": 'PYTHONUNBUFFERED="1",COLUMNS="200",ARCHIVEBOX_RUNNER_DAEMON="1"',
        "stopasgroup": "true",
        "killasgroup": "true",
        "stopwaitsecs": "30",
        "stdout_logfile": "logs/worker_runner.log",
        "redirect_stderr": "true",
    }


RUNNER_ONCE_WORKER = lambda args, name="worker_runner_once": {
    **RUNNER_WORKER(),
    "name": name,
    "command": shlex.join(archivebox_cmd("run", "--no-stdin", *args)),
    # One-shot foreground jobs are awaited by the command that launched them,
    # so they keep the normal cooperative shutdown path instead of the daemon
    # marker that tells supervisord to restart an independently killed worker.
    "environment": 'PYTHONUNBUFFERED="1",COLUMNS="200"',
    "autorestart": "false",
    "stopwaitsecs": "1",
    "stdout_logfile": f"logs/{name}.log",
}


RUNNER_WATCH_WORKER = lambda bind_url: {
    "name": "worker_runner_watch",
    "command": shlex.join(archivebox_cmd("manage", "runner_watch", f"--bind-url={bind_url}")),
    "autostart": "false",
    "autorestart": "true",
    "stdout_logfile": "logs/worker_runner_watch.log",
    "redirect_stderr": "true",
}


def SUPERVISORD_PARENT_WATCHDOG_WORKER(
    *,
    owner_pid: int,
    owner_started_at: float,
    supervisord_pid: int,
    supervisord_started_at: float,
):
    watchdog_script = Path(__file__).with_name("supervisord_parent_watchdog.py")
    return {
        "name": "worker_supervisord_parent_watchdog",
        "command": shlex.join(
            [
                sys.executable,
                str(watchdog_script),
                f"--owner-pid={owner_pid}",
                f"--owner-started-at={owner_started_at}",
                f"--supervisord-pid={supervisord_pid}",
                f"--supervisord-started-at={supervisord_started_at}",
            ],
        ),
        "autostart": "false",
        "autorestart": "false",
        "stopasgroup": "true",
        "killasgroup": "true",
        "stopwaitsecs": "1",
        "stdout_logfile": "logs/worker_supervisord_parent_watchdog.log",
        "redirect_stderr": "true",
    }


SERVER_WORKER = lambda host, port: {
    "name": "worker_daphne",
    "command": shlex.join(
        [
            str(resolve_env_binary("daphne")),
            f"--bind={host}",
            f"--port={port}",
            "archivebox.core.asgi:application",
        ],
    ),
    "autostart": "false",
    "autorestart": "true",
    "stopasgroup": "true",
    "killasgroup": "true",
    "stopwaitsecs": "1",
    "stdout_logfile": "logs/worker_daphne.log",
    "redirect_stderr": "true",
}


def RUNSERVER_WORKER(host: str, port: str, *, reload: bool, nothreading: bool = False):
    command = archivebox_cmd("manage", "runserver", f"{host}:{port}")
    if not reload:
        command.append("--noreload")
    if nothreading:
        command.append("--nothreading")

    environment = ['ARCHIVEBOX_RUNSERVER="1"']
    if reload:
        environment.extend(
            [
                'ARCHIVEBOX_AUTORELOAD="1"',
                f'ARCHIVEBOX_RUNSERVER_BIND_URL="http://{host}:{port}"',
            ],
        )

    return {
        "name": "worker_runserver",
        "command": shlex.join(command),
        "environment": ",".join(environment),
        "autostart": "false",
        "autorestart": "true",
        "stopasgroup": "true",
        "killasgroup": "true",
        "stopwaitsecs": "1",
        "stdout_logfile": "logs/worker_runserver.log",
        "redirect_stderr": "true",
    }


@cache
def get_sock_file():
    """Get the path to the supervisord socket file.

    Supervisord-managed workers inherit SUPERVISOR_SERVER_URL from their parent
    supervisord. They must keep using that socket so worker code cannot
    accidentally start a nested supervisord.
    """
    server_url = os.environ.get("SUPERVISOR_SERVER_URL", "")
    if server_url.startswith("unix://"):
        return Path(server_url.removeprefix("unix://"))

    TMP_DIR = get_or_create_working_tmp_dir(autofix=True, quiet=False)
    assert TMP_DIR, "Failed to find or create a writable TMP_DIR!"
    return TMP_DIR / SUPERVISORD_SOCKET_FILENAME


def create_supervisord_config():
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
    LOG_FILE = CONSTANTS.LOGS_DIR / LOG_FILE_NAME
    user_config = f"user = {ARCHIVEBOX_USER}" if os.geteuid() == 0 and ARCHIVEBOX_USER != 0 else ""
    environment = ",".join(
        f"{key}={json.dumps(str(value))}"
        for key, value in {
            "IS_SUPERVISORD_PARENT": "true",
            "COLUMNS": "200",
            "DATA_DIR": CONSTANTS.DATA_DIR,
            "TMP_DIR": SOCK_FILE.parent,
        }.items()
    )

    CONSTANTS.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config_content = f"""
[supervisord]
nodaemon = true
environment = {environment}
pidfile = {PID_FILE}
logfile = {LOG_FILE}
childlogdir = {CONSTANTS.LOGS_DIR}
directory = {CONSTANTS.DATA_DIR}
strip_ansi = true
nocleanup = true
{user_config}

[unix_http_server]
file = {SOCK_FILE}
chmod = 0700

[supervisorctl]
serverurl = unix://{SOCK_FILE}

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[include]
files = {WORKERS_DIR}/*.conf

"""
    CONFIG_FILE.write_text(config_content)
    Path.mkdir(WORKERS_DIR, exist_ok=True, parents=True)
    for worker_conf in WORKERS_DIR.glob("*.conf"):
        worker_conf.unlink(missing_ok=True)

    (WORKERS_DIR / "initial_startup.conf").write_text("")  # hides error about "no files found to include" when supervisord starts


def _worker_environment_value(daemon: dict[str, str], key: str) -> str | None:
    environment = daemon.get("environment")
    if not environment:
        return None

    try:
        fields = next(csv.reader([environment], skipinitialspace=True))
    except csv.Error:
        fields = str(environment).split(",")

    for field in fields:
        name, separator, value = field.partition("=")
        if separator and name == key:
            try:
                return str(json.loads(value))
            except json.JSONDecodeError:
                return value.strip('"')
    return None


def _worker_log_base_dir(daemon: dict[str, str]) -> Path:
    data_dir = _worker_environment_value(daemon, "DATA_DIR")
    return Path(data_dir) if data_dir else CONSTANTS.DATA_DIR


def create_worker_config(daemon):
    """Create a supervisord worker config file for a given daemon"""
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    log_base_dir = _worker_log_base_dir(daemon)

    Path.mkdir(WORKERS_DIR, exist_ok=True, parents=True)
    for logfile_key in ("stdout_logfile", "stderr_logfile"):
        logfile = daemon.get(logfile_key)
        if not logfile:
            continue
        logfile_path = Path(logfile)
        if not logfile_path.is_absolute():
            logfile_path = log_base_dir / logfile_path
        logfile_path.parent.mkdir(parents=True, exist_ok=True)

    name = daemon["name"]
    worker_conf = WORKERS_DIR / f"{name}.conf"

    worker_str = f"[program:{name}]\n"
    if "startsecs" not in daemon:
        worker_str += "startsecs=0\n"
    for key, value in daemon.items():
        if key == "name":
            continue
        if key in ("stdout_logfile", "stderr_logfile"):
            logfile_path = Path(value)
            if not logfile_path.is_absolute():
                value = str(log_base_dir / logfile_path)
        worker_str += f"{key}={value}\n"
    worker_str += "\n"

    worker_conf.write_text(worker_str)
