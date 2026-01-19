#!/usr/bin/env python3

__package__ = 'archivebox.cli'

from typing import Iterable

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types
from archivebox.config.common import SERVER_CONFIG


@enforce_types
def server(runserver_args: Iterable[str]=(SERVER_CONFIG.BIND_ADDR,),
          reload: bool=False,
          init: bool=False,
          debug: bool=False,
          daemonize: bool=False,
          nothreading: bool=False) -> None:
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
    
    if not User.objects.filter(is_superuser=True).exclude(username='system').exists():
        print()
        print('[violet]Hint:[/violet] To create an [bold]admin username & password[/bold] for the [deep_sky_blue3][underline][link=http://{host}:{port}/admin]Admin UI[/link][/underline][/deep_sky_blue3], run:')
        print('      [green]archivebox manage createsuperuser[/green]')
        print()

    host = '127.0.0.1'
    port = '8000'
    
    try:
        host_and_port = [arg for arg in runserver_args if arg.replace('.', '').replace(':', '').isdigit()][0]
        if ':' in host_and_port:
            host, port = host_and_port.split(':')
        else:
            if '.' in host_and_port:
                host = host_and_port
            else:
                port = host_and_port
    except IndexError:
        pass

    if run_in_debug:
        from django.core.management import call_command
        print('[green][+] Starting ArchiveBox webserver in DEBUG mode...[/green]')
        print(f'    [blink][green]>[/green][/blink] Starting ArchiveBox webserver on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]')
        print(f'    [green]>[/green] Log in to ArchiveBox Admin UI on [deep_sky_blue3][link=http://{host}:{port}/admin]http://{host}:{port}/admin[/link][/deep_sky_blue3]')
        print('    > Writing ArchiveBox error log to ./logs/errors.log')
        if not reload:
            runserver_args.append('--noreload')  # '--insecure'
        if nothreading:
            runserver_args.append('--nothreading')
        call_command("runserver", *runserver_args)
    else:
        from archivebox.workers.supervisord_util import (
            get_existing_supervisord_process,
            get_worker,
            start_server_workers,
            tail_multiple_worker_logs,
            is_port_in_use,
        )
        from archivebox.workers.orchestrator import Orchestrator
        import sys

        # Check if port is already in use
        if is_port_in_use(host, int(port)):
            print(f'[red][X] Error: Port {port} is already in use[/red]')
            print(f'    Another process (possibly daphne) is already listening on {host}:{port}')
            print(f'    Stop the conflicting process or choose a different port')
            sys.exit(1)

        # Check if orchestrator is already running for this data directory
        if Orchestrator.is_running():
            print(f'[red][X] Error: ArchiveBox orchestrator is already running for this data directory[/red]')
            print(f'    Stop the existing orchestrator before starting a new server')
            print(f'    To stop: pkill -f "archivebox manage orchestrator"')
            sys.exit(1)

        # Check if supervisord is already running
        supervisor = get_existing_supervisord_process()
        if supervisor:
            daphne_proc = get_worker(supervisor, 'worker_daphne')

            # If daphne is already running, error out
            if daphne_proc and daphne_proc.get('statename') == 'RUNNING':
                orchestrator_proc = get_worker(supervisor, 'worker_orchestrator')
                print('[red][X] Error: ArchiveBox server is already running[/red]')
                print(f'    [green]√[/green] Web server (worker_daphne) is RUNNING on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]')
                if orchestrator_proc and orchestrator_proc.get('statename') == 'RUNNING':
                    print(f'    [green]√[/green] Background worker (worker_orchestrator) is RUNNING')
                print()
                print('[yellow]To stop the existing server, run:[/yellow]')
                print('    pkill -f "archivebox server"')
                print('    pkill -f supervisord')
                sys.exit(1)
            # Otherwise, daphne is not running - fall through to start it

        # No existing workers found - start new ones
        print('[green][+] Starting ArchiveBox webserver...[/green]')
        print(f'    [blink][green]>[/green][/blink] Starting ArchiveBox webserver on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]')
        print(f'    [green]>[/green] Log in to ArchiveBox Admin UI on [deep_sky_blue3][link=http://{host}:{port}/admin]http://{host}:{port}/admin[/link][/deep_sky_blue3]')
        print('    > Writing ArchiveBox error log to ./logs/errors.log')
        print()
        start_server_workers(host=host, port=port, daemonize=daemonize)
        print("\n[i][green][🟩] ArchiveBox server shut down gracefully.[/green][/i]")


@click.command()
@click.argument('runserver_args', nargs=-1)
@click.option('--reload', is_flag=True, help='Enable auto-reloading when code or templates change')
@click.option('--debug', is_flag=True, help='Enable DEBUG=True mode with more verbose errors')
@click.option('--nothreading', is_flag=True, help='Force runserver to run in single-threaded mode')
@click.option('--init', is_flag=True, help='Run a full archivebox init/upgrade before starting the server')
@click.option('--daemonize', is_flag=True, help='Run the server in the background as a daemon')
@docstring(server.__doc__)
def main(**kwargs):
    server(**kwargs)


if __name__ == '__main__':
    main()
