__package__ = 'archivebox.workers'

import sys
import time
import signal
import socket
import psutil
import shutil
import subprocess

from typing import Dict, cast, Iterator
from pathlib import Path
from functools import cache

from rich import print
from supervisor.xmlrpc import SupervisorTransport
from xmlrpc.client import ServerProxy

from archivebox.config import CONSTANTS
from archivebox.config.paths import get_or_create_working_tmp_dir
from archivebox.config.permissions import ARCHIVEBOX_USER
from archivebox.misc.logging import STDERR
from archivebox.misc.logging_util import pretty_path

LOG_FILE_NAME = "supervisord.log"
CONFIG_FILE_NAME = "supervisord.conf"
PID_FILE_NAME = "supervisord.pid"
WORKERS_DIR_NAME = "workers"

# Global reference to supervisord process for cleanup
_supervisord_proc = None

ORCHESTRATOR_WORKER = {
    "name": "worker_orchestrator",
    "command": "archivebox run",  # runs forever by default
    "autostart": "true",
    "autorestart": "true",
    "stdout_logfile": "logs/worker_orchestrator.log",
    "redirect_stderr": "true",
}

SERVER_WORKER = lambda host, port: {
    "name": "worker_daphne",
    "command": f"daphne --bind={host} --port={port} --application-close-timeout=600 archivebox.core.asgi:application",
    "autostart": "false",
    "autorestart": "true",
    "stdout_logfile": "logs/worker_daphne.log",
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

@cache
def get_sock_file():
    """Get the path to the supervisord socket file, symlinking to a shorter path if needed due to unix path length limits"""
    TMP_DIR = get_or_create_working_tmp_dir(autofix=True, quiet=False)
    assert TMP_DIR, "Failed to find or create a writable TMP_DIR!"
    socket_file = TMP_DIR / "supervisord.sock"

    return socket_file

def follow(file, sleep_sec=0.1) -> Iterator[str]:
    """ Yield each line from a file as they are written.
    `sleep_sec` is the time to sleep after empty reads. """
    line = ''
    while True:
        tmp = file.readline()
        if tmp is not None and tmp != "":
            line += tmp
            if line.endswith("\n"):
                yield line
                line = ''
        elif sleep_sec:
            time.sleep(sleep_sec)


def create_supervisord_config():
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
    LOG_FILE = CONSTANTS.LOGS_DIR / LOG_FILE_NAME
    
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
    
    (WORKERS_DIR / 'initial_startup.conf').write_text('')   # hides error about "no files found to include" when supervisord starts

def create_worker_config(daemon):
    """Create a supervisord worker config file for a given daemon"""
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    
    Path.mkdir(WORKERS_DIR, exist_ok=True, parents=True)
    
    name = daemon['name']
    worker_conf = WORKERS_DIR / f"{name}.conf"

    worker_str = f"[program:{name}]\n"
    for key, value in daemon.items():
        if key == 'name':
            continue
        worker_str += f"{key}={value}\n"
    worker_str += "\n"

    worker_conf.write_text(worker_str)


def get_existing_supervisord_process():
    SOCK_FILE = get_sock_file()
    try:
        transport = SupervisorTransport(None, None, f"unix://{SOCK_FILE}")
        server = ServerProxy("http://localhost", transport=transport)       # user:pass@localhost doesn't work for some reason with unix://.sock, cant seem to silence CRIT no-auth warning
        current_state = cast(Dict[str, int | str], server.supervisor.getState())
        if current_state["statename"] == "RUNNING":
            pid = server.supervisor.getPID()
            print(f"[🦸‍♂️] Supervisord connected (pid={pid}) via unix://{pretty_path(SOCK_FILE)}.")
            return server.supervisor
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error connecting to existing supervisord: {str(e)}")
        return None

def stop_existing_supervisord_process():
    global _supervisord_proc
    SOCK_FILE = get_sock_file()
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME

    try:
        # First try to stop via the global proc reference
        if _supervisord_proc and _supervisord_proc.poll() is None:
            try:
                print(f"[🦸‍♂️] Stopping supervisord process (pid={_supervisord_proc.pid})...")
                _supervisord_proc.terminate()
                try:
                    _supervisord_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _supervisord_proc.kill()
                    _supervisord_proc.wait(timeout=2)
            except (BrokenPipeError, IOError):
                pass
            finally:
                _supervisord_proc = None
            return

        # Fallback: if pid file exists, load PID int and kill that process
        try:
            pid = int(PID_FILE.read_text())
        except (FileNotFoundError, ValueError):
            return

        try:
            print(f"[🦸‍♂️] Stopping supervisord process (pid={pid})...")
            proc = psutil.Process(pid)
            # Kill the entire process group to ensure all children are stopped
            children = proc.children(recursive=True)
            proc.terminate()
            # Also terminate all children
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            proc.wait(timeout=5)
            # Kill any remaining children
            for child in children:
                try:
                    if child.is_running():
                        child.kill()
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
        except (BrokenPipeError, IOError):
            pass
    finally:
        try:
            # clear PID file and socket file
            PID_FILE.unlink(missing_ok=True)
            get_sock_file().unlink(missing_ok=True)
        except BaseException:
            pass

def start_new_supervisord_process(daemonize=False):
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    LOG_FILE = CONSTANTS.LOGS_DIR / LOG_FILE_NAME
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME

    print(f"[🦸‍♂️] Supervisord starting{' in background' if daemonize else ''}...")
    pretty_log_path = pretty_path(LOG_FILE)
    print(f"    > Writing supervisord logs to: {pretty_log_path}")
    print(f"    > Writing task worker logs to: {pretty_log_path.replace('supervisord.log', 'worker_*.log')}")
    print(f'    > Using supervisord config file: {pretty_path(CONFIG_FILE)}')
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
    log_handle = open(LOG_FILE, 'a')

    if daemonize:
        # Start supervisord in background (daemon mode)
        subprocess.Popen(
            f"supervisord --configuration={CONFIG_FILE}",
            stdin=None,
            stdout=log_handle,
            stderr=log_handle,
            shell=True,
            start_new_session=True,
        )
        return wait_for_supervisord_ready()
    else:
        # Start supervisord in FOREGROUND - this will block until supervisord exits
        # supervisord with nodaemon=true will run in foreground and handle signals properly
        # When supervisord gets SIGINT/SIGTERM, it will stop all child processes before exiting
        proc = subprocess.Popen(
            f"supervisord --configuration={CONFIG_FILE}",
            stdin=None,
            stdout=log_handle,
            stderr=log_handle,
            shell=True,
            start_new_session=False,  # Keep in same process group so signals propagate
        )

        # Store the process so we can wait on it later
        global _supervisord_proc
        _supervisord_proc = proc

        return wait_for_supervisord_ready()


def wait_for_supervisord_ready(max_wait_sec: float = 5.0, interval_sec: float = 0.1):
    """Poll for supervisord readiness without a fixed startup sleep."""
    deadline = time.monotonic() + max_wait_sec
    supervisor = None
    while time.monotonic() < deadline:
        supervisor = get_existing_supervisord_process()
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
            sys.stdout.write('.')
            sys.stdout.flush()
            time.sleep(0.1)
            supervisor = get_existing_supervisord_process()
        else:
            print()

    assert supervisor, "Failed to start supervisord or connect to it!"
    supervisor.getPID()  # make sure it doesn't throw an exception

    (WORKERS_DIR / 'initial_startup.conf').unlink(missing_ok=True)
    
    return supervisor

def start_worker(supervisor, daemon, lazy=False):
    assert supervisor.getPID()

    print(f"[🦸‍♂️] Supervisord starting new subprocess worker: {daemon['name']}...")
    create_worker_config(daemon)

    result = supervisor.reloadConfig()
    added, changed, removed = result[0]
    # print(f"Added: {added}, Changed: {changed}, Removed: {removed}")
    for removed in removed:
        supervisor.stopProcessGroup(removed)
        supervisor.removeProcessGroup(removed)
    for changed in changed:
        supervisor.stopProcessGroup(changed)
        supervisor.removeProcessGroup(changed)
        supervisor.addProcessGroup(changed)
    for added in added:
        supervisor.addProcessGroup(added)

    for _ in range(25):
        procs = supervisor.getAllProcessInfo()
        for proc in procs:
            if proc['name'] == daemon["name"]:
                # See process state diagram here: http://supervisord.org/subprocess.html
                if proc['statename'] == 'RUNNING':
                    print(f"     - Worker {daemon['name']}: already {proc['statename']} ({proc['description']})")
                    return proc
                else:
                    if not lazy:
                        supervisor.startProcessGroup(daemon["name"], True)
                    proc = supervisor.getProcessInfo(daemon["name"])
                    print(f"     - Worker {daemon['name']}: started {proc['statename']} ({proc['description']})")
                return proc

        # retry in a moment in case it's slow to launch
        time.sleep(0.2)

    raise Exception(f"Failed to start worker {daemon['name']}! Only found: {procs}")


def get_worker(supervisor, daemon_name):
    try:
        return supervisor.getProcessInfo(daemon_name)
    except Exception:
        pass
    return None

def stop_worker(supervisor, daemon_name):
    proc = get_worker(supervisor, daemon_name)

    for _ in range(10):
        if not proc:
            # worker does not exist (was never running or configured in the first place)
            return True
        
        # See process state diagram here: http://supervisord.org/subprocess.html
        if proc['statename'] == 'STOPPED':
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


def tail_worker_logs(log_path: str):
    get_or_create_supervisord_process(daemonize=False)

    from rich.live import Live
    from rich.table import Table

    table = Table()
    table.add_column("TS")
    table.add_column("URL")

    try:
        with Live(table, refresh_per_second=1) as live:  # update 4 times a second to feel fluid
            with open(log_path, 'r') as f:
                for line in follow(f):
                    if '://' in line:
                        live.console.print(f"Working on: {line.strip()}")
                    # table.add_row("123124234", line.strip())
    except (KeyboardInterrupt, BrokenPipeError, IOError):
        STDERR.print("\n[🛑] Got Ctrl+C, stopping gracefully...")
    except SystemExit:
        pass


def tail_multiple_worker_logs(log_files: list[str], follow=True, proc=None):
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
            f = open(log_path, 'r')
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
            # Check if the monitored process has exited
            if proc is not None and proc.poll() is not None:
                print(f"\n[server process exited with code {proc.returncode}]")
                break

            had_output = False
            # Read ALL available lines from all files (not just one per iteration)
            for log_path, f in file_handles:
                while True:
                    line = f.readline()
                    if not line:
                        break  # No more lines available in this file
                    had_output = True
                    # Strip ANSI codes if present (supervisord does this but just in case)
                    line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line.rstrip())
                    if line_clean:
                        print(line_clean)

            # Small sleep to avoid busy-waiting (only when no output)
            if not had_output:
                time.sleep(0.05)

    except (KeyboardInterrupt, BrokenPipeError, IOError):
        pass  # Let the caller handle the cleanup message
    except SystemExit:
        pass
    finally:
        # Close all file handles
        for _, f in file_handles:
            try:
                f.close()
            except Exception:
                pass

def watch_worker(supervisor, daemon_name, interval=5):
    """loop continuously and monitor worker's health"""
    while True:
        proc = get_worker(supervisor, daemon_name)
        if not proc:
            raise Exception("Worker dissapeared while running! " + daemon_name)

        if proc['statename'] == 'STOPPED':
            return proc

        if proc['statename'] == 'RUNNING':
            time.sleep(1)
            continue

        if proc['statename'] in ('STARTING', 'BACKOFF', 'FATAL', 'EXITED', 'STOPPING'):
            print(f'[🦸‍♂️] WARNING: Worker {daemon_name} {proc["statename"]} {proc["description"]}')
            time.sleep(interval)
            continue



def start_server_workers(host='0.0.0.0', port='8000', daemonize=False):
    global _supervisord_proc

    supervisor = get_or_create_supervisord_process(daemonize=daemonize)

    bg_workers = [
        ORCHESTRATOR_WORKER,
    ]

    print()
    start_worker(supervisor, SERVER_WORKER(host=host, port=port))
    print()
    for worker in bg_workers:
        start_worker(supervisor, worker)
    print()

    if not daemonize:
        try:
            # Tail worker logs while supervisord runs
            sys.stdout.write('Tailing worker logs (Ctrl+C to stop)...\n\n')
            sys.stdout.flush()
            tail_multiple_worker_logs(
                log_files=['logs/worker_daphne.log', 'logs/worker_orchestrator.log'],
                follow=True,
                proc=_supervisord_proc,  # Stop tailing when supervisord exits
            )
        except (KeyboardInterrupt, BrokenPipeError, IOError):
            STDERR.print("\n[🛑] Got Ctrl+C, stopping gracefully...")
        except SystemExit:
            pass
        except BaseException as e:
            STDERR.print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping gracefully...")
        finally:
            # Ensure supervisord and all children are stopped
            stop_existing_supervisord_process()
            time.sleep(1.0)  # Give processes time to fully terminate


def start_cli_workers(watch=False):
    global _supervisord_proc

    supervisor = get_or_create_supervisord_process(daemonize=False)

    start_worker(supervisor, ORCHESTRATOR_WORKER)

    if watch:
        try:
            # Block on supervisord process - it will handle signals and stop children
            if _supervisord_proc:
                _supervisord_proc.wait()
            else:
                # Fallback to watching worker if no proc reference
                watch_worker(supervisor, ORCHESTRATOR_WORKER['name'])
        except (KeyboardInterrupt, BrokenPipeError, IOError):
            STDERR.print("\n[🛑] Got Ctrl+C, stopping gracefully...")
        except SystemExit:
            pass
        except BaseException as e:
            STDERR.print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping gracefully...")
        finally:
            # Ensure supervisord and all children are stopped
            stop_existing_supervisord_process()
            time.sleep(1.0)  # Give processes time to fully terminate
    return [ORCHESTRATOR_WORKER]


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
