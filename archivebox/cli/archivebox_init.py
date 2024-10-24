#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox init'

import sys
import argparse

from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from ..logging_util import SmartFormatter, reject_stdin
from ..main import init


@docstring(init.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=init.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--force', # '-f',
        action='store_true',
        help='Ignore unrecognized files in current directory and initialize anyway',
    )
    parser.add_argument(
        '--quick', '-q',
        action='store_true',
        help='Run any updates or migrations without rechecking all snapshot dirs',
    )
    parser.add_argument(
        '--install', #'-s',
        action='store_true',
        help='Automatically install dependencies and extras used for archiving',
    )
    parser.add_argument(
        '--setup', #'-s',
        action='store_true',
        help='DEPRECATED: equivalent to --install',
    )
    command = parser.parse_args(args or ())
    reject_stdin(__command__, stdin)

    init(
        force=command.force,
        quick=command.quick,
        install=command.install or command.setup,
        out_dir=pwd or DATA_DIR,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
