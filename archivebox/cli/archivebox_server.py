#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox server'

import sys
import argparse

from typing import Optional, List, IO

from ..main import server, docstring
from ..config import OUTPUT_DIR
from .logging import SmartFormatter, reject_stdin


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
        default=None,
        help='Arguments to pass to Django runserver'
    )
    parser.add_argument(
        '--reload',
        action='store_true',
        help='Enable auto-reloading when code or templates change',
    )
    command = parser.parse_args(args or ())
    reject_stdin(__command__, stdin)
    
    server(
        runserver_args=command.runserver_args,
        reload=command.reload,
        out_dir=pwd or OUTPUT_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
