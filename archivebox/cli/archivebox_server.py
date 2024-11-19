#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox server'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.logging_util import SmartFormatter, reject_stdin



# @enforce_types
def server(runserver_args: Optional[List[str]]=None,
           reload: bool=False,
           debug: bool=False,
           init: bool=False,
           quick_init: bool=False,
           createsuperuser: bool=False,
           daemonize: bool=False,
           out_dir: Path=DATA_DIR) -> None:
    """Run the ArchiveBox HTTP server"""

    from rich import print

    runserver_args = runserver_args or []
    
    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)
        print()
    elif quick_init:
        run_subcommand('init', subcommand_args=['--quick'], stdin=None, pwd=out_dir)
        print()

    if createsuperuser:
        run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)
        print()


    check_data_folder()

    from django.core.management import call_command
    from django.contrib.auth.models import User
    
    if not User.objects.filter(is_superuser=True).exclude(username='system').exists():
        print()
        # print('[yellow][!] No admin accounts exist, you must create one to be able to log in to the Admin UI![/yellow]')
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
        call_command("runserver", *runserver_args)
    else:
        from workers.supervisord_util import start_server_workers

        print()
        start_server_workers(host=host, port=port, daemonize=False)
        print("\n[i][green][🟩] ArchiveBox server shut down gracefully.[/green][/i]")



@docstring(server.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=server.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        'runserver_args',
        nargs='*',
        type=str,
        default=[SERVER_CONFIG.BIND_ADDR],
        help='Arguments to pass to Django runserver'
    )
    parser.add_argument(
        '--reload',
        action='store_true',
        help='Enable auto-reloading when code or templates change',
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable DEBUG=True mode with more verbose errors',
    )
    parser.add_argument(
        '--nothreading',
        action='store_true',
        help='Force runserver to run in single-threaded mode',
    )
    parser.add_argument(
        '--init',
        action='store_true',
        help='Run a full archivebox init/upgrade before starting the server',
    )
    parser.add_argument(
        '--quick-init', '-i',
        action='store_true',
        help='Run quick archivebox init/upgrade before starting the server',
    )
    parser.add_argument(
        '--createsuperuser',
        action='store_true',
        help='Run archivebox manage createsuperuser before starting the server',
    )
    parser.add_argument(
        '--daemonize',
        action='store_true',
        help='Run the server in the background as a daemon',
    )
    command = parser.parse_args(args or ())
    reject_stdin(__command__, stdin)
    
    server(
        runserver_args=command.runserver_args + (['--nothreading'] if command.nothreading else []),
        reload=command.reload,
        debug=command.debug,
        init=command.init,
        quick_init=command.quick_init,
        createsuperuser=command.createsuperuser,
        daemonize=command.daemonize,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
