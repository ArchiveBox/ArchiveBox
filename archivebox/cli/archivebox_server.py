#!/usr/bin/env python3

__package__ = "archivebox.cli"

from collections.abc import Iterable
import sys

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types
from archivebox.config.common import SERVER_CONFIG


def stop_existing_background_runner(*, machine, process_model, supervisor=None, stop_worker_fn=None, log=print) -> int:
    """Stop any existing orchestrator process so the server can take ownership."""
    process_model.cleanup_stale_running(machine=machine)
    process_model.cleanup_orphaned_workers()

    running_runners = list(
        process_model.objects.filter(
            machine=machine,
            status=process_model.StatusChoices.RUNNING,
            process_type=process_model.TypeChoices.ORCHESTRATOR,
        ).order_by("created_at"),
    )

    if not running_runners:
        return 0

    log("[yellow][*] Stopping existing ArchiveBox background runner...[/yellow]")

    if supervisor is not None and stop_worker_fn is not None:
        for worker_name in ("worker_runner", "worker_runner_watch"):
            try:
                stop_worker_fn(supervisor, worker_name)
            except Exception:
                pass

    for proc in running_runners:
        try:
            proc.kill_tree(graceful_timeout=2.0)
        except Exception:
            try:
                proc.terminate(graceful_timeout=2.0)
            except Exception:
                pass

    process_model.cleanup_stale_running(machine=machine)
    return len(running_runners)


def _read_supervisor_worker_command(worker_name: str) -> str:
    from archivebox.workers.supervisord_util import WORKERS_DIR_NAME, get_sock_file

    worker_conf = get_sock_file().parent / WORKERS_DIR_NAME / f"{worker_name}.conf"
    if not worker_conf.exists():
        return ""

    for line in worker_conf.read_text().splitlines():
        if line.startswith("command="):
            return line.removeprefix("command=").strip()
    return ""


def _worker_command_matches_bind(command: str, host: str, port: str) -> bool:
    if not command:
        return False
    return f"{host}:{port}" in command or (f"--bind={host}" in command and f"--port={port}" in command)


def stop_existing_server_workers(*, supervisor, stop_worker_fn, host: str, port: str, log=print) -> int:
    """Stop existing ArchiveBox web workers if they already own the requested bind."""
    stopped = 0

    for worker_name in ("worker_runserver", "worker_daphne"):
        try:
            proc = supervisor.getProcessInfo(worker_name) if supervisor else None
        except Exception:
            proc = None
        if not isinstance(proc, dict) or proc.get("statename") != "RUNNING":
            continue

        command = _read_supervisor_worker_command(worker_name)
        if not _worker_command_matches_bind(command, host, port):
            continue

        if stopped == 0:
            log("[yellow][*] Taking over existing ArchiveBox web server on same port...[/yellow]")
        stop_worker_fn(supervisor, worker_name)
        stopped += 1

    return stopped


@enforce_types
def server(
    runserver_args: Iterable[str] = (SERVER_CONFIG.BIND_ADDR,),
    reload: bool = False,
    init: bool = False,
    debug: bool = False,
    daemonize: bool = False,
    nothreading: bool = False,
) -> None:
    """Run the ArchiveBox HTTP server"""

    runserver_args = list(runserver_args)

    if init:
        from archivebox.cli.archivebox_init import init as archivebox_init

        archivebox_init(quick=True)
        print()

    from archivebox.misc.checks import check_data_folder

    check_data_folder()

    from archivebox.config.common import SHELL_CONFIG

    run_in_debug = SHELL_CONFIG.DEBUG or debug or reload
    if debug or reload:
        SHELL_CONFIG.DEBUG = True

    from django.contrib.auth.models import User

    if not User.objects.filter(is_superuser=True).exclude(username="system").exists():
        print()
        print(
            "[violet]Hint:[/violet] To create an [bold]admin username & password[/bold] for the [deep_sky_blue3][underline][link=http://{host}:{port}/admin]Admin UI[/link][/underline][/deep_sky_blue3], run:",
        )
        print("      [green]archivebox manage createsuperuser[/green]")
        print()

    host = "127.0.0.1"
    port = "8000"

    try:
        host_and_port = [arg for arg in runserver_args if arg.replace(".", "").replace(":", "").isdigit()][0]
        if ":" in host_and_port:
            host, port = host_and_port.split(":")
        else:
            if "." in host_and_port:
                host = host_and_port
            else:
                port = host_and_port
    except IndexError:
        pass

    from archivebox.workers.supervisord_util import (
        get_existing_supervisord_process,
        get_worker,
        stop_worker,
        start_server_workers,
        is_port_in_use,
    )
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    supervisor = get_existing_supervisord_process()
    stop_existing_background_runner(
        machine=machine,
        process_model=Process,
        supervisor=supervisor,
        stop_worker_fn=stop_worker,
    )
    if supervisor:
        stop_existing_server_workers(
            supervisor=supervisor,
            stop_worker_fn=stop_worker,
            host=host,
            port=port,
        )

    # Check if port is already in use
    if is_port_in_use(host, int(port)):
        print(f"[red][X] Error: Port {port} is already in use[/red]")
        print(f"    Another process (possibly daphne or runserver) is already listening on {host}:{port}")
        print("    Stop the conflicting process or choose a different port")
        sys.exit(1)

    supervisor = get_existing_supervisord_process()
    if supervisor:
        server_worker_name = "worker_runserver" if run_in_debug else "worker_daphne"
        server_proc = get_worker(supervisor, server_worker_name)
        server_state = server_proc.get("statename") if isinstance(server_proc, dict) else None
        if server_state == "RUNNING":
            runner_proc = get_worker(supervisor, "worker_runner")
            runner_watch_proc = get_worker(supervisor, "worker_runner_watch")
            runner_state = runner_proc.get("statename") if isinstance(runner_proc, dict) else None
            runner_watch_state = runner_watch_proc.get("statename") if isinstance(runner_watch_proc, dict) else None
            print("[red][X] Error: ArchiveBox server is already running[/red]")
            print(
                f"    [green]√[/green] Web server ({server_worker_name}) is RUNNING on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]",
            )
            if runner_state == "RUNNING":
                print("    [green]√[/green] Background runner (worker_runner) is RUNNING")
            if runner_watch_state == "RUNNING":
                print("    [green]√[/green] Reload watcher (worker_runner_watch) is RUNNING")
            print()
            print("[yellow]To stop the existing server, run:[/yellow]")
            print('    pkill -f "archivebox server"')
            print("    pkill -f supervisord")
            sys.exit(1)

    if run_in_debug:
        print("[green][+] Starting ArchiveBox webserver in DEBUG mode...[/green]")
    else:
        print("[green][+] Starting ArchiveBox webserver...[/green]")
    print(
        f"    [blink][green]>[/green][/blink] Starting ArchiveBox webserver on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]",
    )
    print(
        f"    [green]>[/green] Log in to ArchiveBox Admin UI on [deep_sky_blue3][link=http://{host}:{port}/admin]http://{host}:{port}/admin[/link][/deep_sky_blue3]",
    )
    print("    > Writing ArchiveBox error log to ./logs/errors.log")
    print()
    start_server_workers(host=host, port=port, daemonize=daemonize, debug=run_in_debug, reload=reload, nothreading=nothreading)
    print("\n[i][green][🟩] ArchiveBox server shut down gracefully.[/green][/i]")


@click.command()
@click.argument("runserver_args", nargs=-1)
@click.option("--reload", is_flag=True, help="Enable auto-reloading when code or templates change")
@click.option("--debug", is_flag=True, help="Enable DEBUG=True mode with more verbose errors")
@click.option("--nothreading", is_flag=True, help="Force runserver to run in single-threaded mode")
@click.option("--init", is_flag=True, help="Run a full archivebox init/upgrade before starting the server")
@click.option("--daemonize", is_flag=True, help="Run the server in the background as a daemon")
@docstring(server.__doc__)
def main(**kwargs):
    server(**kwargs)


if __name__ == "__main__":
    main()
