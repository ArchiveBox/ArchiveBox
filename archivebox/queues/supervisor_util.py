__package__ = 'archivebox.queues'

import time
import signal
import psutil
import shutil
import subprocess
from pathlib import Path
from rich import print

from typing import Dict, cast

from supervisor.xmlrpc import SupervisorTransport
from xmlrpc.client import ServerProxy

from archivebox.config.permissions import ARCHIVEBOX_USER

from .settings import SUPERVISORD_CONFIG_FILE, DATA_DIR, PID_FILE, get_sock_file, LOG_FILE, WORKERS_DIR, TMP_DIR, LOGS_DIR

from typing import Iterator

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
    config_content = f"""
[supervisord]
nodaemon = true
environment = IS_SUPERVISORD_PARENT="true"
pidfile = {TMP_DIR}/{PID_FILE.name}
logfile = {LOGS_DIR}/{LOG_FILE.name}
childlogdir = {LOGS_DIR}
directory = {DATA_DIR}
strip_ansi = true
nocleanup = true
user = {ARCHIVEBOX_USER}

[unix_http_server]
file = {get_sock_file()}
chmod = 0700

[supervisorctl]
serverurl = unix://{get_sock_file()}

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[include]
files = {WORKERS_DIR}/*.conf

"""
    SUPERVISORD_CONFIG_FILE.write_text(config_content)

def create_worker_config(daemon):
    Path.mkdir(WORKERS_DIR, exist_ok=True)
    
    name = daemon['name']
    configfile = WORKERS_DIR / f"{name}.conf"

    config_content = f"[program:{name}]\n"
    for key, value in daemon.items():
        if key == 'name':
            continue
        config_content += f"{key}={value}\n"
    config_content += "\n"

    configfile.write_text(config_content)


def get_existing_supervisord_process():
    try:
        transport = SupervisorTransport(None, None, f"unix://{get_sock_file()}")
        server = ServerProxy("http://localhost", transport=transport)
        current_state = cast(Dict[str, int | str], server.supervisor.getState())
        if current_state["statename"] == "RUNNING":
            pid = server.supervisor.getPID()
            print(f"[🦸‍♂️] Supervisord connected (pid={pid}) via unix://{str(get_sock_file()).replace(str(DATA_DIR), '.')}.")
            return server.supervisor
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error connecting to existing supervisord: {str(e)}")
        return None

def stop_existing_supervisord_process():
    try:
        pid = int(PID_FILE.read_text())
    except FileNotFoundError:
        return
    except ValueError:
        PID_FILE.unlink()
        return

    try:
        print(f"[🦸‍♂️] Stopping supervisord process (pid={pid})...")
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait()
    except Exception:
        pass
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass

def start_new_supervisord_process(daemonize=False):
    print(f"[🦸‍♂️] Supervisord starting{' in background' if daemonize else ''}...")
    # Create a config file in the current working directory
    
    # clear out existing stale state files
    shutil.rmtree(WORKERS_DIR, ignore_errors=True)
    PID_FILE.unlink(missing_ok=True)
    get_sock_file().unlink(missing_ok=True)
    SUPERVISORD_CONFIG_FILE.unlink(missing_ok=True)
    
    create_supervisord_config()

    # Start supervisord
    subprocess.Popen(
        f"supervisord --configuration={SUPERVISORD_CONFIG_FILE}",
        stdin=None,
        shell=True,
        start_new_session=daemonize,
    )

    def exit_signal_handler(signum, frame):
        if signum != 13:
            print(f"\n[🦸‍♂️] Supervisord got stop signal ({signal.strsignal(signum)}). Terminating child processes...")
        stop_existing_supervisord_process()
        raise SystemExit(0)

    # Monitor for termination signals and cleanup child processes
    if not daemonize:
        signal.signal(signal.SIGINT, exit_signal_handler)
        signal.signal(signal.SIGHUP, exit_signal_handler)
        signal.signal(signal.SIGPIPE, exit_signal_handler)
        signal.signal(signal.SIGTERM, exit_signal_handler)
    # otherwise supervisord will containue in background even if parent proc is ends (aka daemon mode)

    time.sleep(2)

    return get_existing_supervisord_process()

def get_or_create_supervisord_process(daemonize=False):
    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        stop_existing_supervisord_process()
        supervisor = start_new_supervisord_process(daemonize=daemonize)
        time.sleep(0.5)

    assert supervisor, "Failed to start supervisord or connect to it!"
    supervisor.getPID()  # make sure it doesn't throw an exception
    
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
                    table.add_row("123124234", line.strip())
    except KeyboardInterrupt:
        print("\n[🛑] Got Ctrl+C, stopping gracefully...")
    except SystemExit:
        pass

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




def start_server_workers(host='0.0.0.0', port='8000', daemonize=False):
    supervisor = get_or_create_supervisord_process(daemonize=daemonize)
    
    bg_workers = [
        {
            "name": "worker_scheduler",
            "command": "archivebox manage djangohuey --queue system_tasks -w 4 -k thread --disable-health-check --flush-locks",
            "autostart": "true",
            "autorestart": "true",
            "stdout_logfile": "logs/worker_scheduler.log",
            "redirect_stderr": "true",
        },
        {
            "name": "worker_system_tasks",
            "command": "archivebox manage djangohuey --queue system_tasks -w 4 -k thread --no-periodic --disable-health-check",
            "autostart": "true",
            "autorestart": "true",
            "stdout_logfile": "logs/worker_system_tasks.log",
            "redirect_stderr": "true",
        },
    ]
    fg_worker = {
        "name": "worker_daphne",
        "command": f"daphne --bind={host} --port={port} --application-close-timeout=600 archivebox.core.asgi:application",
        "autostart": "false",
        "autorestart": "true",
        "stdout_logfile": "logs/worker_daphne.log",
        "redirect_stderr": "true",
    }

    print()
    start_worker(supervisor, fg_worker)
    print()
    for worker in bg_workers:
        start_worker(supervisor, worker)
    print()

    if not daemonize:
        try:
            watch_worker(supervisor, "worker_daphne")
        except KeyboardInterrupt:
            print("\n[🛑] Got Ctrl+C, stopping gracefully...")
        except SystemExit:
            pass
        except BaseException as e:
            print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping web server gracefully...")
            raise
        finally:
            stop_worker(supervisor, "worker_daphne")
            time.sleep(0.5)


def start_cli_workers(watch=False):
    supervisor = get_or_create_supervisord_process(daemonize=False)
    
    fg_worker = {
        "name": "worker_system_tasks",
        "command": "archivebox manage djangohuey --queue system_tasks",
        "autostart": "true",
        "autorestart": "true",
        "stdout_logfile": "logs/worker_system_tasks.log",
        "redirect_stderr": "true",
    }

    start_worker(supervisor, fg_worker)

    if watch:
        try:
            watch_worker(supervisor, "worker_system_tasks")
        except KeyboardInterrupt:
            print("\n[🛑] Got Ctrl+C, stopping gracefully...")
        except SystemExit:
            pass
        except BaseException as e:
            print(f"\n[🛑] Got {e.__class__.__name__} exception, stopping web server gracefully...")
            raise
        finally:
            stop_worker(supervisor, "worker_system_tasks")
            stop_worker(supervisor, "worker_scheduler")
            time.sleep(0.5)
    return fg_worker


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
