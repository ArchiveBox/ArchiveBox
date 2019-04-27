#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox server'
__description__ = 'Run the ArchiveBox HTTP server'

import sys
import argparse

from typing import Optional, List, IO

from ..main import server
from ..util import reject_stdin
from ..config import OUTPUT_DIR


def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
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
