__package__ = 'archivebox.workers'

import sys
import time
import signal
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

SCHEDULER_WORKER = {
    "name": "worker_scheduler",
    "command": "archivebox manage djangohuey --queue system_tasks -w 4 -k thread --disable-health-check --flush-locks",
    "autostart": "true",
    "autorestart": "true",
    "stdout_logfile": "logs/worker_scheduler.log",
    "redirect_stderr": "true",
}
COMMAND_WORKER = {
    "name": "worker_commands",
    "command": "archivebox manage djangohuey --queue commands -w 4 -k thread --no-periodic --disable-health-check",
    "autostart": "true",
    "autorestart": "true",
    "stdout_logfile": "logs/worker_commands.log",
    "redirect_stderr": "true",
}
ORCHESTRATOR_WORKER = {
    "name": "worker_orchestrator",
    "command": "archivebox manage orchestrator",
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
environment = IS_SUPERVISORD_PARENT="true"
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
    SOCK_FILE = get_sock_file()
    PID_FILE = SOCK_FILE.parent / PID_FILE_NAME
    
    try:
        # if pid file exists, load PID int
        try:
            pid = int(PID_FILE.read_text())
        except (FileNotFoundError, ValueError):
            return

        try:
            print(f"[🦸‍♂️] Stopping supervisord process (pid={pid})...")
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
        except (BaseException, BrokenPipeError, IOError, KeyboardInterrupt):
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

    # Start supervisord
    # panel = Panel(f"Starting supervisord with config: {SUPERVISORD_CONFIG_FILE}")
    # with Live(panel, refresh_per_second=1) as live:
    
    subprocess.Popen(
        f"supervisord --configuration={CONFIG_FILE}",
        stdin=None,
        shell=True,
        start_new_session=daemonize,
    )

    def exit_signal_handler(signum, frame):
        if signum == 2:
            STDERR.print("\n[🛑] Got Ctrl+C. Terminating child processes...")
        elif signum != 13:
            STDERR.print(f"\n[🦸‍♂️] Supervisord got stop signal ({signal.strsignal(signum)}). Terminating child processes...")
        stop_existing_supervisord_process()
        raise SystemExit(0)

    # Monitor for termination signals and cleanup child processes
    if not daemonize:
        try:
            signal.signal(signal.SIGINT, exit_signal_handler)
            signal.signal(signal.SIGHUP, exit_signal_handler)
            signal.signal(signal.SIGPIPE, exit_signal_handler)
            signal.signal(signal.SIGTERM, exit_signal_handler)
        except Exception:
            # signal handlers only work in main thread
            pass
    # otherwise supervisord will containue in background even if parent proc is ends (aka daemon mode)

    time.sleep(2)

    return get_existing_supervisord_process()

def get_or_create_supervisord_process(daemonize=False):
    SOCK_FILE = get_sock_file()
    WORKERS_DIR = SOCK_FILE.parent / WORKERS_DIR_NAME
    
    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        stop_existing_supervisord_process()
        supervisor = start_new_supervisord_process(daemonize=daemonize)
        time.sleep(0.5)

    # wait up to 5s in case supervisord is slow to start
    if not supervisor:
        for _ in range(10):
            if supervisor is not None:
                print()
                break
            sys.stdout.write('.')
            sys.stdout.flush()
            time.sleep(0.5)
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

    time.sleep(1)

    for _ in range(10):
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

        # retry in a second in case it's slow to launch
        time.sleep(0.5)

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
    supervisor = get_or_create_supervisord_process(daemonize=daemonize)
    
    bg_workers = [
        SCHEDULER_WORKER,
        COMMAND_WORKER,
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
            watch_worker(supervisor, "worker_daphne")
        except (KeyboardInterrupt, BrokenPipeError, IOError):
            STDERR.print("\n[🛑] Got Ctrl+C, stopping gracefully...")
        except SystemExit:
            pass
        except BaseException as e:
            STDERR.print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping web server gracefully...")
            raise
        finally:
            stop_worker(supervisor, "worker_daphne")
            time.sleep(0.5)


def start_cli_workers(watch=False):
    supervisor = get_or_create_supervisord_process(daemonize=False)
    
    start_worker(supervisor, COMMAND_WORKER)
    start_worker(supervisor, ORCHESTRATOR_WORKER)

    if watch:
        try:
            watch_worker(supervisor, ORCHESTRATOR_WORKER['name'])
        except (KeyboardInterrupt, BrokenPipeError, IOError):
            STDERR.print("\n[🛑] Got Ctrl+C, stopping gracefully...")
        except SystemExit:
            pass
        except BaseException as e:
            STDERR.print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping web server gracefully...")
            raise
        finally:
            stop_worker(supervisor, COMMAND_WORKER['name'])
            stop_worker(supervisor, ORCHESTRATOR_WORKER['name'])
            time.sleep(0.5)
    return [COMMAND_WORKER, ORCHESTRATOR_WORKER]


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
