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

    from django.core.management import call_command
    from django.contrib.auth.models import User
    
    from archivebox.config.common import SHELL_CONFIG
    
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

    print('[green][+] Starting ArchiveBox webserver...[/green]')
    print(f'    [blink][green]>[/green][/blink] Starting ArchiveBox webserver on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]')
    print(f'    [green]>[/green] Log in to ArchiveBox Admin UI on [deep_sky_blue3][link=http://{host}:{port}/admin]http://{host}:{port}/admin[/link][/deep_sky_blue3]')
    print('    > Writing ArchiveBox error log to ./logs/errors.log')

    if SHELL_CONFIG.DEBUG:
        if not reload:
            runserver_args.append('--noreload')  # '--insecure'
        if nothreading:
            runserver_args.append('--nothreading')
        call_command("runserver", *runserver_args)
    else:
        from workers.supervisord_util import start_server_workers

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
