__package__ = "archivebox.workers"

import sys
import time
import socket
import os
import psutil
import shutil
import subprocess
import shlex
import signal

from typing import cast
from pathlib import Path
from functools import cache

from supervisor.xmlrpc import SupervisorTransport
from xmlrpc.client import Fault, ServerProxy

from archivebox.config import CONSTANTS
from archivebox.config.common import rprint as print
from archivebox.config.paths import get_or_create_working_tmp_dir
from archivebox.config.permissions import ARCHIVEBOX_USER
from archivebox.core.shutdown_util import (
    configured_stopwaitsecs,
    foreground_shutdown_signals,
    wait_popen_and_kill_children,
    wait_psutil_and_kill_children,
)
from archivebox.misc.logging import STDERR
from archivebox.misc.logging_util import pretty_path

LOG_FILE_NAME = "supervisord.log"
CONFIG_FILE_NAME = "supervisord.conf"
PID_FILE_NAME = "supervisord.pid"
WORKERS_DIR_NAME = "workers"

# Global reference to supervisord process for cleanup
_supervisord_proc = None
_desired_supervisord_workers: dict[str, dict[str, str]] = {}
_ACTIVE_WORKER_STATES = {"STARTING", "RUNNING", "BACKOFF"}
_RUNTIME_COMPONENT_ORDER = ("orchestrator", "server", "sonic")


def _shell_join(args: list[str]) -> str:
    return shlex.join(args)


def _record_supervisord_process(proc: subprocess.Popen, config_file: Path) -> None:
    try:
        from datetime import datetime
        from django.utils import timezone
        from archivebox.machine.models import Machine, Process

        try:
            started_at = datetime.fromtimestamp(psutil.Process(proc.pid).create_time(), tz=timezone.get_current_timezone())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            started_at = timezone.now()

        Process.objects.create(
            machine=Machine.current(),
            parent=Process.current(),
            process_type=Process.TypeChoices.SUPERVISORD,
            worker_type="supervisord",
            pwd=str(CONSTANTS.DATA_DIR),
            cmd=["supervisord", f"--configuration={config_file}"],
            pid=proc.pid,
            started_at=started_at,
            status=Process.StatusChoices.RUNNING,
            timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS,
        )
    except Exception:
        pass


def _fallback_supervisord_process_from_db():
    try:
        from archivebox.machine.models import Machine, Process

        for process in Process.objects.filter(
            machine=Machine.current(),
            process_type=Process.TypeChoices.SUPERVISORD,
            status=Process.StatusChoices.RUNNING,
            pwd=str(CONSTANTS.DATA_DIR),
        ).order_by("-started_at", "-created_at"):
            proc = process.proc
            if proc is not None:
                return proc
            process.mark_exited(exit_code=0)
    except Exception:
        return None
    return None


def _live_supervisord_processes_from_db():
    """Return live supervisord parents recorded for this DATA_DIR.

    The socket/config files are generated runtime projection and can move when
    TMP_DIR changes or falls back. Process rows are the durable coordination
    state, so takeover/shutdown must stop every live supervisord recorded for
    this collection, not only the one reachable at the current socket path.
    """

    try:
        from archivebox.machine.models import Machine, Process

        Process.cleanup_stale_running(machine=Machine.current())
        rows = Process.objects.filter(
            machine=Machine.current(),
            process_type=Process.TypeChoices.SUPERVISORD,
            status=Process.StatusChoices.RUNNING,
            pwd=str(CONSTANTS.DATA_DIR),
        ).order_by("-started_at", "-created_at")
        live = []
        for process in rows.iterator(chunk_size=20):
            proc = process.proc
            if proc is not None:
                live.append((process, proc))
            else:
                process.mark_exited(exit_code=0)
        return live
    except Exception:
        return []


def _stop_older_supervisord_processes(*, current_pid: int, current_started_at: float, timeout: float) -> None:
    """Stop older supervisord parents for this DATA_DIR after a start race.

    Lazy daemon users such as `archivebox list --search ...` may race to start
    Sonic. The durable Process table is the arbiter: after this parent is
    recorded, kill only live supervisord rows that started before this one.
    If another parent started later, leave it alone so newest healthy owner wins.
    """

    for process, proc in _live_supervisord_processes_from_db():
        if proc.pid == current_pid:
            continue
        try:
            if proc.create_time() >= current_started_at:
                continue
            print(f"[🦸‍♂️] Stopping older supervisord process (pid={proc.pid})...")
            children = proc.children(recursive=True)
            proc.terminate()
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            wait_psutil_and_kill_children(proc, children, timeout=timeout)
            process.mark_exited(exit_code=0)
        except psutil.NoSuchProcess:
            process.mark_exited(exit_code=0)
        except (BrokenPipeError, OSError, psutil.TimeoutExpired):
            pass


RUNNER_WORKER = {
    "name": "worker_runner",
    "command": _shell_join([sys.executable, "-m", "archivebox", "run", "--daemon"]),
    "autostart": "false",
    "autorestart": "true",
    "environment": 'PYTHONUNBUFFERED="1",COLUMNS="200",ARCHIVEBOX_RUNNER_DAEMON="1"',
    "stopasgroup": "true",
    "killasgroup": "true",
    "stopwaitsecs": "30",
    "stdout_logfile": "logs/worker_runner.log",
    "redirect_stderr": "true",
}

RUNNER_ONCE_WORKER = lambda args, name="worker_runner_once": {
    **RUNNER_WORKER,
    "name": name,
    "command": _shell_join([sys.executable, "-m", "archivebox", "run", "--no-stdin", *args]),
    "environment": 'PYTHONUNBUFFERED="1",COLUMNS="200"',
    "autorestart": "false",
    "stopwaitsecs": "1",
    "stdout_logfile": f"logs/{name}.log",
}

RUNNER_WATCH_WORKER = lambda bind_url: {
    "name": "worker_runner_watch",
    "command": _shell_join([sys.executable, "-m", "archivebox", "manage", "runner_watch", f"--bind-url={bind_url}"]),
    "autostart": "false",
    "autorestart": "true",
    "stdout_logfile": "logs/worker_runner_watch.log",
    "redirect_stderr": "true",
}

SUPERVISORD_PARENT_WATCHDOG_WORKER = lambda supervisord_process_id: {
    "name": "worker_supervisord_parent_watchdog",
    "command": _shell_join(
        [
            sys.executable,
            "-m",
            "archivebox",
            "manage",
            "supervisord_watchdog",
            f"--supervisord-process-id={supervisord_process_id}",
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
    "command": _shell_join(
        [
            sys.executable,
            "-m",
            "daphne",
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
    command = [sys.executable, "-m", "archivebox", "manage", "runserver", f"{host}:{port}"]
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
        "command": _shell_join(command),
        "environment": ",".join(environment),
        "autostart": "false",
        "autorestart": "true",
        "stopasgroup": "true",
        "killasgroup": "true",
        "stopwaitsecs": "1",
        "stdout_logfile": "logs/worker_runserver.log",
        "redirect_stderr": "true",
    }


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is already in use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return False
    except OSError:
        return True


def _sonic_worker_bind_target(worker: dict[str, str]) -> tuple[str, int] | None:
    """Read the plugin-owned Sonic config before starting its supervisord worker."""
    command = shlex.split(worker.get("command") or "")
    if not command or Path(command[0]).name != "sonic" or "-c" not in command:
        return None
    config_index = command.index("-c") + 1
    if config_index >= len(command):
        return None
    try:
        for line in Path(command[config_index]).read_text(encoding="utf-8", errors="replace").splitlines():
            key, _separator, value = line.partition("=")
            if key.strip() != "inet":
                continue
            host_port = value.strip().strip('"')
            host, port = host_port.rsplit(":", 1)
            host = "127.0.0.1" if host.strip().lower() == "localhost" else host.strip()
            return host, int(port)
    except (OSError, ValueError):
        return None
    return None


@cache
def get_sock_file():
    """Get the path to the supervisord socket file, symlinking to a shorter path if needed due to unix path length limits"""
    TMP_DIR = get_or_create_working_tmp_dir(autofix=True, quiet=False)
    assert TMP_DIR, "Failed to find or create a writable TMP_DIR!"
    socket_file = TMP_DIR / "supervisord.sock"

    return socket_file


def create_supervisord_config():
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
    LOG_FILE = CONSTANTS.LOGS_DIR / LOG_FILE_NAME

    CONSTANTS.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config_content = f"""
[supervisord]
nodaemon = true
environment = IS_SUPERVISORD_PARENT="true",COLUMNS="200"
pidfile = {PID_FILE}
logfile = {LOG_FILE}
childlogdir = {CONSTANTS.LOGS_DIR}
directory = {CONSTANTS.DATA_DIR}
strip_ansi = true
nocleanup = true
user = {ARCHIVEBOX_USER}

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


def create_worker_config(daemon):
    """Create a supervisord worker config file for a given daemon"""
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME

    Path.mkdir(WORKERS_DIR, exist_ok=True, parents=True)
    for logfile_key in ("stdout_logfile", "stderr_logfile"):
        logfile = daemon.get(logfile_key)
        if not logfile:
            continue
        logfile_path = Path(logfile)
        if not logfile_path.is_absolute():
            logfile_path = CONSTANTS.DATA_DIR / logfile_path
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
                value = str(CONSTANTS.DATA_DIR / logfile_path)
        worker_str += f"{key}={value}\n"
    worker_str += "\n"

    worker_conf.write_text(worker_str)


def _current_foreground_supervisord_process_id():
    if not _supervisord_proc or _supervisord_proc.poll() is not None:
        return None

    try:
        from archivebox.machine.models import Machine, Process

        current = Process.current()
        for process in Process.objects.filter(
            machine=Machine.current(),
            process_type=Process.TypeChoices.SUPERVISORD,
            status=Process.StatusChoices.RUNNING,
            pwd=str(CONSTANTS.DATA_DIR),
            pid=_supervisord_proc.pid,
            parent=current,
        ).iterator(chunk_size=10):
            if process.is_running:
                return process.id
    except Exception:
        return None
    return None


def sync_supervisord_workers(supervisor, workers: list[tuple[dict[str, str], bool]], *, prune: bool = True):
    """Project desired workers into supervisord from ArchiveBox-owned state.

    The worker conf files are generated supervisor input only. They are never
    treated as durable ArchiveBox state; callers either pass a complete worker
    set with prune=True or add one explicit worker with prune=False.
    """
    assert supervisor.getPID()

    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    Path.mkdir(WORKERS_DIR, exist_ok=True, parents=True)

    global _desired_supervisord_workers

    supervisord_process_id = _current_foreground_supervisord_process_id()
    if supervisord_process_id is not None:
        watchdog = SUPERVISORD_PARENT_WATCHDOG_WORKER(supervisord_process_id)
        if all(worker["name"] != watchdog["name"] for worker, _lazy in workers):
            workers = [*workers, (watchdog, False)]

    desired = {worker["name"]: (worker, lazy) for worker, lazy in workers}
    if prune:
        _desired_supervisord_workers = {name: worker for name, (worker, _lazy) in desired.items()}
    else:
        _desired_supervisord_workers.update({name: worker for name, (worker, _lazy) in desired.items()})
    if prune:
        for worker_conf in WORKERS_DIR.glob("*.conf"):
            worker_conf.unlink(missing_ok=True)

    for worker, _lazy in desired.values():
        create_worker_config(worker)

    added, changed, removed = supervisor.reloadConfig()[0]
    for group in removed:
        try:
            supervisor.stopProcessGroup(group)
        except Exception:
            pass
        supervisor.removeProcessGroup(group)
    for group in changed:
        try:
            supervisor.stopProcessGroup(group)
        except Exception:
            pass
        supervisor.removeProcessGroup(group)
        supervisor.addProcessGroup(group)
    for group in added:
        supervisor.addProcessGroup(group)

    procs_by_name = {}
    for worker_name, (_worker, lazy) in desired.items():
        print(f"[🦸‍♂️] Supervisord syncing subprocess worker: {worker_name}...")
        for _ in range(25):
            proc = get_worker(supervisor, worker_name)
            if proc is None:
                time.sleep(0.2)
                continue
            if proc["statename"] == "RUNNING":
                print(f"     - Worker {worker_name}: already {proc['statename']} ({proc['description']})")
                procs_by_name[worker_name] = proc
                break
            if not lazy:
                sonic_target = _sonic_worker_bind_target(_worker)
                if sonic_target is not None:
                    sonic_host, sonic_port = sonic_target
                    stop_stale_sonic_processes(_worker, supervisor_pid=supervisor.getPID(), host=sonic_host, port=sonic_port)
                    if is_port_in_use(sonic_host, sonic_port):
                        print(
                            f"[yellow][*] Sonic is already listening on {sonic_host}:{sonic_port}; "
                            f"not starting duplicate {worker_name}.[/yellow]",
                        )
                        procs_by_name[worker_name] = proc
                        break
                supervisor.startProcessGroup(worker_name, True)
                proc = supervisor.getProcessInfo(worker_name)
                print(f"     - Worker {worker_name}: started {proc['statename']} ({proc['description']})")
            else:
                print(f"     - Worker {worker_name}: configured {proc['statename']} ({proc['description']})")
            procs_by_name[worker_name] = proc
            break
        else:
            raise Exception(f"Failed to sync worker {worker_name}! Only found: {supervisor.getAllProcessInfo()}")

    return procs_by_name


def get_existing_supervisord_process(*, quiet: bool = False):
    SOCK_FILE = get_sock_file()
    try:
        transport = SupervisorTransport(None, None, f"unix://{SOCK_FILE}")
        server = ServerProxy(
            "http://localhost",
            transport=transport,
        )  # user:pass@localhost doesn't work for some reason with unix://.sock, cant seem to silence CRIT no-auth warning
        current_state = cast(dict[str, int | str], server.supervisor.getState())
        if current_state["statename"] == "RUNNING":
            pid = server.supervisor.getPID()
            if not quiet:
                print(f"[🦸‍♂️] Supervisord connected (pid={pid}) via unix://{pretty_path(SOCK_FILE)}.")
            return server.supervisor
    except FileNotFoundError:
        return None
    except Fault as err:
        if err.faultCode == 6 and "SHUTDOWN_STATE" in str(err):
            if not quiet:
                print(f"[🦸‍♂️] Supervisord is already shutting down via unix://{pretty_path(SOCK_FILE)}.")
            return None
        if not quiet:
            print(f"Error connecting to existing supervisord: {str(err)}")
        return None
    except Exception as e:
        if not quiet:
            print(f"Error connecting to existing supervisord: {str(e)}")
        return None


class SupervisordConnectionCache:
    """Reuse one XML-RPC proxy until it fails, avoiding hot-loop reconnects."""

    def __init__(self, *, quiet: bool = False):
        self.quiet = quiet
        self.supervisor = None

    def clear(self) -> None:
        self.supervisor = None

    def get(self):
        if self.supervisor is not None:
            try:
                self.supervisor.getPID()
                return self.supervisor
            except Exception:
                self.supervisor = None

        supervisor = get_existing_supervisord_process(quiet=self.quiet)
        if supervisor is None:
            return None

        self.supervisor = supervisor
        return supervisor


def stop_existing_supervisord_process():
    global _supervisord_proc
    SOCK_FILE = get_sock_file()
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
    stop_grace_seconds = configured_stopwaitsecs(tuple(_desired_supervisord_workers.values()))
    live_supervisord = _live_supervisord_processes_from_db()

    for process, _proc in live_supervisord:
        if process is None or process.parent_id is None:
            continue
        owner = process.parent
        if owner.pid == os.getpid() or not owner.is_running:
            continue
        owner_proc = owner.proc
        if owner_proc is None:
            owner.mark_exited(exit_code=0)
            continue
        if owner_proc.ppid() > 1:
            continue
        try:
            print(f"[🦸‍♂️] Stopping older ArchiveBox runtime owner (pid={owner_proc.pid})...")
            owner_proc.terminate()
            try:
                owner_proc.wait(timeout=min(stop_grace_seconds, 5))
            except psutil.TimeoutExpired:
                owner_proc.kill()
                owner_proc.wait(timeout=2)
            owner.mark_exited(exit_code=0)
        except psutil.NoSuchProcess:
            owner.mark_exited(exit_code=0)
        except (BrokenPipeError, OSError, psutil.TimeoutExpired):
            pass

    supervisor = get_existing_supervisord_process(quiet=True)
    supervisor_pid = None
    supervisor_shutdown_requested = False
    if supervisor is not None:
        try:
            supervisor_pid = supervisor.getPID()
        except Exception:
            supervisor_pid = None
        # Ask supervisord to stop each worker first so child shutdown follows
        # each worker's own stopasgroup/killasgroup/stopwaitsecs settings. The
        # direct psutil kill path below is only the final cleanup bound.
        try:
            final_states = {"STOPPED", "EXITED", "FATAL", "UNKNOWN"}
            if any(proc["statename"] not in final_states for proc in supervisor.getAllProcessInfo()):
                supervisor.stopAllProcesses(False)
                deadline = time.monotonic() + stop_grace_seconds
                while time.monotonic() < deadline:
                    if all(proc["statename"] in final_states for proc in supervisor.getAllProcessInfo()):
                        break
                    time.sleep(0.2)
        except Fault as err:
            if err.faultCode != 6 or "SHUTDOWN_STATE" not in str(err):
                print(f"Error stopping supervisord workers: {str(err)}")
        except Exception as err:
            print(f"Error stopping supervisord workers: {str(err)}")

        try:
            supervisor.shutdown()
            supervisor_shutdown_requested = True
        except Fault as err:
            if err.faultCode == 6 and "SHUTDOWN_STATE" in str(err):
                supervisor_shutdown_requested = True
            else:
                print(f"Error shutting down supervisord: {str(err)}")
        except Exception:
            supervisor_shutdown_requested = True

    try:
        # First try to stop via the global proc reference
        if _supervisord_proc and _supervisord_proc.poll() is None:
            try:
                print(f"[🦸‍♂️] Stopping supervisord process (pid={_supervisord_proc.pid})...")
                try:
                    psutil_proc = psutil.Process(_supervisord_proc.pid)
                    children = psutil_proc.children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
                if not supervisor_shutdown_requested:
                    _supervisord_proc.terminate()
                wait_popen_and_kill_children(_supervisord_proc, children, timeout=stop_grace_seconds)
            except (BrokenPipeError, OSError):
                pass
            finally:
                stopped_pid = _supervisord_proc.pid
                _supervisord_proc = None
        else:
            stopped_pid = None

        live_supervisord = _live_supervisord_processes_from_db()
        if stopped_pid is not None:
            live_supervisord = [(process, proc) for process, proc in live_supervisord if proc.pid != stopped_pid]
        if not live_supervisord:
            proc = _fallback_supervisord_process_from_db()
            live_supervisord = [] if proc is None else [(None, proc)]
        if not live_supervisord:
            return

        for process, proc in live_supervisord:
            try:
                print(f"[🦸‍♂️] Stopping older supervisord process (pid={proc.pid})...")
                children = proc.children(recursive=True)
                if not supervisor_shutdown_requested or supervisor is None or proc.pid != supervisor_pid:
                    proc.terminate()
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                wait_psutil_and_kill_children(proc, children, timeout=stop_grace_seconds)
                if process is not None:
                    process.mark_exited(exit_code=0)
            except psutil.NoSuchProcess:
                if process is not None:
                    process.mark_exited(exit_code=0)
            except (BrokenPipeError, OSError, psutil.TimeoutExpired, Fault):
                pass
    finally:
        try:
            # clear PID file and socket file
            PID_FILE.unlink(missing_ok=True)
            get_sock_file().unlink(missing_ok=True)
        except BaseException:
            pass


def stop_own_supervisord_process(*, record_exit: bool = True):
    """Stop only the supervisord child started by this Python process."""

    global _supervisord_proc

    if not _supervisord_proc or _supervisord_proc.poll() is not None:
        reap_foreground_supervisord_process()
        return False

    stopped_pid = _supervisord_proc.pid
    try:
        print(f"[🦸‍♂️] Stopping supervisord process (pid={stopped_pid})...")
        try:
            psutil_proc = psutil.Process(stopped_pid)
            children = psutil_proc.children(recursive=True)
        except psutil.NoSuchProcess:
            children = []

        # Foreground server shutdown should be fast and power-loss tolerant.
        # ArchiveBox state is durable enough to recover interrupted crawls, so
        # do not let supervisord spend worker stopwaitsecs draining the runner.
        try:
            os.killpg(stopped_pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            _supervisord_proc.terminate()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        wait_popen_and_kill_children(_supervisord_proc, children, timeout=2.0, kill_timeout=1.0)
        if record_exit:
            try:
                from archivebox.machine.models import Machine, Process

                for process in Process.objects.filter(
                    machine=Machine.current(),
                    process_type=Process.TypeChoices.SUPERVISORD,
                    status=Process.StatusChoices.RUNNING,
                    pwd=str(CONSTANTS.DATA_DIR),
                    pid=stopped_pid,
                ).iterator(chunk_size=10):
                    process.mark_exited(exit_code=0)
            except Exception:
                pass
    except (BrokenPipeError, OSError, psutil.TimeoutExpired):
        pass
    finally:
        try:
            SOCK_FILE = get_sock_file()
            PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
            if PID_FILE.exists() and PID_FILE.read_text().strip() == str(stopped_pid):
                PID_FILE.unlink(missing_ok=True)
                SOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        _supervisord_proc = None
    return True


def reap_foreground_supervisord_process() -> None:
    """Reap the supervisord child owned by this foreground parent if it exited."""

    global _supervisord_proc
    if _supervisord_proc and _supervisord_proc.poll() is not None:
        _supervisord_proc = None


def start_new_supervisord_process(daemonize=False):
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    LOG_FILE = CONSTANTS.LOGS_DIR / LOG_FILE_NAME
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
    stop_grace_seconds = configured_stopwaitsecs(tuple(_desired_supervisord_workers.values()))

    print(f"[🦸‍♂️] Supervisord starting{' in background' if daemonize else ''}...")
    pretty_log_path = pretty_path(LOG_FILE)
    print(f"    > Writing supervisord logs to: {pretty_log_path}")
    print(f"    > Writing task worker logs to: {pretty_log_path.replace('supervisord.log', 'worker_*.log')}")
    print(f"    > Using supervisord config file: {pretty_path(CONFIG_FILE)}")
    print(f"    > Using supervisord UNIX socket: {pretty_path(SOCK_FILE)}")
    print()

    # clear out existing stale state files
    shutil.rmtree(WORKERS_DIR, ignore_errors=True)
    PID_FILE.unlink(missing_ok=True)
    get_sock_file().unlink(missing_ok=True)
    CONFIG_FILE.unlink(missing_ok=True)

    # create the supervisord config file
    create_supervisord_config()

    # Open log file for supervisord output
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "a")

    if daemonize:
        # Start supervisord in background (daemon mode)
        proc = subprocess.Popen(
            ["supervisord", f"--configuration={CONFIG_FILE}"],
            stdin=None,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
        current_started_at = psutil.Process(proc.pid).create_time()
        _record_supervisord_process(proc, CONFIG_FILE)
        supervisor = wait_for_supervisord_ready()
        _stop_older_supervisord_processes(current_pid=proc.pid, current_started_at=current_started_at, timeout=stop_grace_seconds)
        return supervisor
    else:
        # Keep supervisord foreground-owned by this process, but isolate it
        # from terminal Ctrl+C. The ArchiveBox parent owns user-facing server
        # signals and stops supervisord explicitly, so Ctrl+C does not also
        # hit crawl workers and trigger the crawl-interactive abort flow.
        proc = subprocess.Popen(
            ["supervisord", f"--configuration={CONFIG_FILE}"],
            stdin=None,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )

        # Store the process so we can wait on it later
        global _supervisord_proc
        _supervisord_proc = proc
        current_started_at = psutil.Process(proc.pid).create_time()
        _record_supervisord_process(proc, CONFIG_FILE)

        supervisor = wait_for_supervisord_ready()
        _stop_older_supervisord_processes(current_pid=proc.pid, current_started_at=current_started_at, timeout=stop_grace_seconds)
        return supervisor


def wait_for_supervisord_ready(max_wait_sec: float = 5.0, interval_sec: float = 0.1, *, quiet: bool = False):
    """Poll for supervisord readiness without a fixed startup sleep."""
    deadline = time.monotonic() + max_wait_sec
    supervisor = None
    while time.monotonic() < deadline:
        supervisor = get_existing_supervisord_process(quiet=quiet)
        if supervisor is not None:
            return supervisor
        time.sleep(interval_sec)
    return supervisor


def get_or_create_supervisord_process(daemonize=False):
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        stop_existing_supervisord_process()
        supervisor = start_new_supervisord_process(daemonize=daemonize)

    # wait up to 5s in case supervisord is slow to start
    if not supervisor:
        for _ in range(50):
            if supervisor is not None:
                print()
                break
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(0.1)
            supervisor = get_existing_supervisord_process()
        else:
            print()

    assert supervisor, "Failed to start supervisord or connect to it!"
    supervisor.getPID()  # make sure it doesn't throw an exception

    (WORKERS_DIR / "initial_startup.conf").unlink(missing_ok=True)

    return supervisor


def start_worker(supervisor, daemon, lazy=False):
    return sync_supervisord_workers(supervisor, [(daemon, lazy)], prune=False).get(daemon["name"])


def run_runner_worker(args: list[str], *, name: str = "worker_runner_once", interactive_interrupts: bool = False) -> int:
    supervisor = get_or_create_supervisord_process(daemonize=False)
    worker = RUNNER_ONCE_WORKER(args, name=name)
    log_path = Path(worker["stdout_logfile"])
    if not log_path.is_absolute():
        log_path = CONSTANTS.DATA_DIR / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch()
    log_handle = log_path.open()
    log_handle.seek(0, 2)
    sync_supervisord_workers(supervisor, [(worker, False)], prune=False)
    final_states = {"STOPPED", "EXITED", "FATAL", "UNKNOWN"}
    forwarded_interrupt = False
    try:
        while True:
            try:
                while True:
                    line = log_handle.readline()
                    if not line:
                        break
                    sys.stdout.write(line)
                    sys.stdout.flush()
                proc = get_worker(supervisor, name)
                if proc is None:
                    return 1
                if proc["statename"] in final_states:
                    while True:
                        line = log_handle.readline()
                        if not line:
                            break
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    if proc["statename"] in {"EXITED", "STOPPED"}:
                        return int(proc.get("exitstatus") or 0)
                    return 1
                time.sleep(0.5)
            except KeyboardInterrupt:
                if not interactive_interrupts or forwarded_interrupt:
                    raise
                # Route the signal through supervisord by worker name rather than
                # raw os.kill on a cached PID. The cached proc["pid"] can be
                # stale: if the worker exited between supervisord's last status
                # poll and the user's Ctrl+C, the OS may have already reused
                # that pid for an unrelated process (e.g. another shell the
                # user has open) and raw os.kill would target it instead of the
                # crawl hook. signalProcess goes through supervisord, which
                # only signals workers it still owns.
                proc = get_worker(supervisor, name)
                if proc is None or proc.get("statename") != "RUNNING":
                    raise
                supervisor.signalProcess(name, "SIGINT")
                forwarded_interrupt = True
                print("[yellow][*] Forwarding Ctrl+C to the active crawl hook...[/yellow]")
    finally:
        log_handle.close()


def get_worker(supervisor, daemon_name):
    try:
        return supervisor.getProcessInfo(daemon_name)
    except Exception:
        pass
    return None


def format_runtime_components(components: list[str] | tuple[str, ...]) -> str:
    return ", ".join(component for component in components if component)


def worker_runtime_component(worker_name: str, *, config=None) -> str | None:
    if worker_name in {RUNNER_WORKER["name"], RUNNER_WATCH_WORKER("")["name"]} or worker_name.startswith("worker_runner_"):
        return "orchestrator"
    if worker_name in {SERVER_WORKER("", "")["name"], RUNSERVER_WORKER("", "", reload=False)["name"]}:
        return "server"
    if config is not None:
        sonic_worker = get_sonic_supervisord_worker_from_plugin(config)
        if sonic_worker and worker_name == sonic_worker.get("name"):
            return "sonic"
    return None


def runtime_components_for_worker_names(worker_names: set[str] | list[str] | tuple[str, ...], *, config=None) -> list[str]:
    components = {worker_runtime_component(worker_name, config=config) for worker_name in worker_names}
    return [component for component in _RUNTIME_COMPONENT_ORDER if component in components]


def active_supervisord_runtime_components(*, config=None, supervisor=None) -> list[str]:
    supervisor = supervisor or get_existing_supervisord_process(quiet=True)
    if supervisor is None:
        return []
    try:
        worker_names = {proc.get("name") for proc in supervisor.getAllProcessInfo() if proc.get("statename") in _ACTIVE_WORKER_STATES}
    except Exception:
        return []
    return runtime_components_for_worker_names({str(name) for name in worker_names if name}, config=config)


def build_server_worker_plan(*, config, host: str, port: str, debug: bool, reload: bool, nothreading: bool, supervisor=None):
    bind_url = f"http://{host}:{port}"

    if debug:
        server_worker = RUNSERVER_WORKER(host=host, port=port, reload=reload, nothreading=nothreading)
        bg_workers: list[tuple[dict[str, str], bool]] = (
            [(RUNNER_WORKER, True), (RUNNER_WATCH_WORKER(bind_url), False)] if reload else [(RUNNER_WORKER, False)]
        )
        log_files = ["logs/worker_runserver.log", "logs/worker_runner.log"]
        if reload:
            log_files.insert(1, "logs/worker_runner_watch.log")
    else:
        server_worker = SERVER_WORKER(host=host, port=port)
        bg_workers = [(RUNNER_WORKER, False)]
        log_files = ["logs/worker_daphne.log", "logs/worker_runner.log"]

    sonic_worker = get_sonic_supervisord_worker_from_plugin(config)
    if sonic_worker is not None:
        try:
            current_sonic = get_worker(supervisor, sonic_worker["name"]) if supervisor is not None else None
            supervisor_pid = supervisor.getPID() if supervisor is not None else None
        except Exception:
            current_sonic = None
            supervisor_pid = None
        sonic_host = str(config.SEARCH_BACKEND_SONIC_HOST_NAME or "127.0.0.1")
        if sonic_host.strip().lower() == "localhost":
            sonic_host = "127.0.0.1"
        sonic_port = int(config.SEARCH_BACKEND_SONIC_PORT)
        if not (isinstance(current_sonic, dict) and current_sonic.get("statename") in ("STARTING", "RUNNING")):
            stop_stale_sonic_processes(sonic_worker, supervisor_pid=supervisor_pid, host=sonic_host, port=sonic_port)
        if not (isinstance(current_sonic, dict) and current_sonic.get("statename") in ("STARTING", "RUNNING")) and is_port_in_use(
            sonic_host,
            sonic_port,
        ):
            print(f"[yellow][*] Sonic is already listening on {sonic_host}:{sonic_port}; not starting a duplicate worker.[/yellow]")
        else:
            bg_workers.insert(0, (sonic_worker, False))
            log_files.append(str(sonic_worker["stdout_logfile"]))

    workers = [(server_worker, False), *bg_workers]
    components = runtime_components_for_worker_names([worker["name"] for worker, _lazy in workers], config=config)
    return workers, log_files, components


def stop_worker(supervisor, daemon_name):
    proc = get_worker(supervisor, daemon_name)

    for _ in range(10):
        if not proc:
            # worker does not exist (was never running or configured in the first place)
            return True

        # See process state diagram here: http://supervisord.org/subprocess.html
        if proc["statename"] == "STOPPED":
            # worker was configured but has already stopped for some reason
            supervisor.removeProcessGroup(daemon_name)
            return True
        else:
            # worker was configured and is running, stop it now
            supervisor.stopProcessGroup(daemon_name)

        # wait 500ms and then re-check to make sure it's really stopped
        time.sleep(0.5)
        proc = get_worker(supervisor, daemon_name)

    raise Exception(f"Failed to stop worker {daemon_name}!")


def tail_multiple_worker_logs(log_files: list[str], follow=True, proc=None, keep_running=None):
    """Tail multiple log files simultaneously, interleaving their output.

    Args:
        log_files: List of log file paths to tail
        follow: Whether to keep following (True) or just read existing content (False)
        proc: Optional subprocess.Popen object - stop tailing when this process exits
    """
    import re
    from pathlib import Path

    # Convert relative paths to absolute paths
    log_paths = []
    for log_file in log_files:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = CONSTANTS.DATA_DIR / log_path

        # Create log file if it doesn't exist
        if not log_path.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch()

        log_paths.append(log_path)

    # Open all log files
    file_handles = []
    for log_path in log_paths:
        try:
            f = open(log_path)
            # Seek to end - only show NEW logs from now on, not old logs
            f.seek(0, 2)  # Go to end

            file_handles.append((log_path, f))
            print(f"    [tailing {log_path.name}]")
        except Exception as e:
            sys.stderr.write(f"Warning: Could not open {log_path}: {e}\n")

    if not file_handles:
        sys.stderr.write("No log files could be opened\n")
        return

    print()

    try:
        while follow:
            if keep_running is not None and not keep_running():
                print("\n[newer ArchiveBox process is now running the orchestrator and server]")
                return "transferred"

            # Check if the monitored process has exited
            if proc is not None and proc.poll() is not None:
                print(f"\n[server process exited with code {proc.returncode}]")
                return "exited"

            had_output = False
            # Read ALL available lines from all files (not just one per iteration)
            for log_path, f in file_handles:
                while True:
                    line = f.readline()
                    if not line:
                        break  # No more lines available in this file
                    had_output = True
                    # Strip ANSI codes if present (supervisord does this but just in case)
                    line_clean = re.sub(r"\x1b\[[0-9;]*m", "", line.rstrip())
                    if line_clean:
                        print(line_clean)

            # Small sleep to avoid busy-waiting (only when no output)
            if not had_output:
                time.sleep(0.05)

    except (KeyboardInterrupt, BrokenPipeError, OSError):
        return "interrupted"  # Let the caller handle the cleanup message
    except SystemExit:
        return "interrupted"
    finally:
        # Close all file handles
        for _, f in file_handles:
            try:
                f.close()
            except Exception:
                pass
    return "stopped"


def get_sonic_supervisord_worker_from_plugin(config) -> dict[str, str] | None:
    try:
        from abx_plugins.plugins.search_backend_sonic.daemon import get_sonic_supervisord_worker
    except ModuleNotFoundError as err:
        if err.name != "abx_plugins.plugins.search_backend_sonic.daemon":
            raise
        return None

    worker = get_sonic_supervisord_worker(config)
    return cast(dict[str, str] | None, worker)


def _proc_cmdline(proc: psutil.Process) -> list[str]:
    try:
        return proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return []


def _is_sonic_process(proc: psutil.Process) -> bool:
    cmdline = _proc_cmdline(proc)
    return bool(cmdline and Path(cmdline[0]).name == "sonic")


def _is_supervisord_process(proc: psutil.Process | None) -> bool:
    if proc is None:
        return False
    cmdline = _proc_cmdline(proc)
    return any(Path(part).name == "supervisord" for part in cmdline)


def _has_live_archivebox_parent(proc: psutil.Process | None) -> bool:
    try:
        parent = proc.parent() if proc else None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    if parent is None or parent.pid <= 1:
        return False
    cmdline = _proc_cmdline(parent)
    return any("archivebox" in part for part in cmdline)


def _terminate_process_tree(root: psutil.Process, *, timeout: float = 2.0) -> None:
    try:
        children = root.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    try:
        root.terminate()
    except psutil.NoSuchProcess:
        return
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _gone, alive = psutil.wait_procs([root, *children], timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=timeout)


def _sonic_listeners(host: str, port: int) -> list[psutil.Process]:
    listeners = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if not _is_sonic_process(proc):
            continue
        try:
            connections = proc.net_connections(kind="tcp")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        for conn in connections:
            if conn.status != psutil.CONN_LISTEN or not conn.laddr or conn.laddr.port != port:
                continue
            addr = str(conn.laddr.ip)
            if host in {"0.0.0.0", "::", addr} or addr in {"0.0.0.0", "::"}:
                listeners.append(proc)
                break
    return listeners


def stop_stale_sonic_processes(
    sonic_worker: dict[str, str],
    *,
    supervisor_pid: int | None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    command = shlex.split(sonic_worker.get("command") or "")
    config_path = Path(command[command.index("-c") + 1]).resolve() if "-c" in command and command.index("-c") + 1 < len(command) else None

    stale = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if proc.info["pid"] == os.getpid() or proc.info["ppid"] == supervisor_pid:
                continue
            if config_path is None or Path(cmdline[0]).name != "sonic" or str(config_path) not in cmdline:
                continue
            stale.append(proc)
        except (IndexError, psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if host is not None and port is not None:
        for proc in _sonic_listeners(host, port):
            try:
                proc_ppid = proc.ppid()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if proc.pid == os.getpid() or proc_ppid == supervisor_pid:
                continue
            try:
                supervisor = proc.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                supervisor = None
            if _is_supervisord_process(supervisor) and not _has_live_archivebox_parent(supervisor):
                stale.append(supervisor)
            elif proc_ppid <= 1:
                stale.append(proc)

    if not stale:
        return

    unique_stale = {proc.pid: proc for proc in stale}.values()
    target = f"{host}:{port}" if host and port else pretty_path(config_path) if config_path else "unknown Sonic target"
    print(f"[yellow][*] Taking over stale Sonic daemon(s) using {target}...[/yellow]")
    for proc in unique_stale:
        _terminate_process_tree(proc)


def start_server_workers(
    host="0.0.0.0",
    port="8000",
    daemonize=False,
    debug=False,
    reload=False,
    nothreading=False,
    keep_running=None,
    should_stop_supervisord=None,
    resumed_from_pid=None,
):
    from archivebox.config.common import get_config

    config = get_config()
    shutdown_state = None
    tail_result = "stopped"
    try:
        supervisor = get_or_create_supervisord_process(daemonize=daemonize)
        workers, log_files, components = build_server_worker_plan(
            config=config,
            host=host,
            port=port,
            debug=debug,
            reload=reload,
            nothreading=nothreading,
            supervisor=supervisor,
        )
        component_list = format_runtime_components(components)
        if resumed_from_pid:
            print(
                "[yellow][*] Other newer archivebox process "
                f"(pid={resumed_from_pid}) exited, taking over {component_list} in this process again...[/yellow]",
            )
        else:
            print(f"[*] Starting {component_list} in this process (pid={os.getpid()})...")

        print()
        sync_supervisord_workers(supervisor, workers, prune=True)
        print()

        if daemonize:
            return None

        from django.db import connections

        connections.close_all()
        try:
            with foreground_shutdown_signals() as shutdown_state:
                # Tail worker logs while supervisord runs.
                sys.stdout.write("Tailing worker logs (Ctrl+C to stop)...\n\n")
                sys.stdout.flush()
                tail_result = tail_multiple_worker_logs(
                    log_files=log_files,
                    follow=True,
                    proc=_supervisord_proc,  # Stop tailing when supervisord exits
                    keep_running=keep_running,
                )
        except (KeyboardInterrupt, BrokenPipeError, OSError):
            if daemonize:
                raise
            if not shutdown_state or not shutdown_state.signal_name:
                print("\n[🛑] Got CTRL+C, stopping gracefully...")
        except SystemExit:
            if daemonize:
                raise
            pass
        except BaseException as e:
            if daemonize:
                raise
            STDERR.print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping gracefully...")
    finally:
        signal_shutdown_requested = bool(shutdown_state and shutdown_state.signal_name)
        if not daemonize and (signal_shutdown_requested or should_stop_supervisord is None or should_stop_supervisord()):
            # Ensure supervisord and all children are stopped only while this
            # foreground parent is still the active server parent. Standby
            # parents must not tear down a newer leader's services. If this
            # foreground parent itself received an OS shutdown signal, always
            # stop the supervisord child it owns; stop_own_supervisord_process()
            # does not target supervisord processes owned by other parents.
            stop_own_supervisord_process(record_exit=not signal_shutdown_requested)
    return tail_result


# def main(daemons):
#     supervisor = get_or_create_supervisord_process(daemonize=False)

#     worker = start_worker(supervisor, daemons["webworker"])
#     pprint(worker)

#     print("All processes started in background.")

# Optionally you can block the main thread until an exit signal is received:
# try:
#     signal.pause()
# except KeyboardInterrupt:
#     pass
# finally:
#     stop_existing_supervisord_process()

# if __name__ == "__main__":

#     DAEMONS = {
#         "webworker": {
#             "name": "webworker",
#             "command": "python3 -m http.server 9000",
#             "directory": str(cwd),
#             "autostart": "true",
#             "autorestart": "true",
#             "stdout_logfile": cwd / "webworker.log",
#             "stderr_logfile": cwd / "webworker_error.log",
#         },
#     }
#     main(DAEMONS, cwd)
