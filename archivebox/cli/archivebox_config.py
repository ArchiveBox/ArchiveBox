#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox config'

import sys
import argparse
from pathlib import Path

from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from ..main import config
from ..logging_util import SmartFormatter, accept_stdin


@docstring(config.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=config.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--get', #'-g',
        action='store_true',
        help="Get the value for the given config KEYs",
    )
    group.add_argument(
        '--set', #'-s',
        action='store_true',
        help="Set the given KEY=VALUE config values",
    )
    group.add_argument(
        '--reset', #'-s',
        action='store_true',
        help="Reset the given KEY config values to their defaults",
    )
    parser.add_argument(
        'config_options',
        nargs='*',
        type=str,
        help='KEY or KEY=VALUE formatted config values to get or set',
    )
    command = parser.parse_args(args or ())

    config_options_str = ''
    if not command.config_options:
        config_options_str = accept_stdin(stdin)

    config(
        config_options_str=config_options_str,
        config_options=command.config_options,
        get=command.get,
        set=command.set,
        reset=command.reset,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
