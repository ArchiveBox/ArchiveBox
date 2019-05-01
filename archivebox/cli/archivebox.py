#!/usr/bin/env python3
# archivebox [command]

__package__ = 'archivebox.cli'
__command__ = 'archivebox'

import sys
import argparse

from typing import Optional, List, IO

from . import list_subcommands, run_subcommand
from ..config import OUTPUT_DIR


def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    subcommands = list_subcommands()
    parser = argparse.ArgumentParser(
        prog=__command__,
        description='ArchiveBox: The self-hosted internet archive',
        add_help=False,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--help', '-h',
        action='store_true',
        help=subcommands['help'],
    )
    group.add_argument(
        '--version',
        action='store_true',
        help=subcommands['version'],
    )
    group.add_argument(
        "subcommand",
        type=str,
        help= "The name of the subcommand to run",
        nargs='?',
        choices=subcommands.keys(),
        default=None,
    )
    parser.add_argument(
        "subcommand_args",
        help="Arguments for the subcommand",
        nargs=argparse.REMAINDER,
    )
    command = parser.parse_args(args or ())

    if command.help or command.subcommand is None:
        command.subcommand = 'help'
    if command.version:
        command.subcommand = 'version'

    run_subcommand(
        subcommand=command.subcommand,
        subcommand_args=command.subcommand_args,
        stdin=stdin,
        pwd=pwd or OUTPUT_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
