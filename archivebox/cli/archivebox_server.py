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
from ..logging_util import SmartFormatter, reject_stdin
from ..main import server

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
