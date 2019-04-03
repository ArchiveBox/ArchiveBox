#!/usr/bin/env python3
# archivebox [command]

__package__ = 'archivebox.cli'
__command__ = 'archivebox'
__description__ = 'ArchiveBox: The self-hosted internet archive.'

import sys
import argparse

from . import list_subcommands, run_subcommand


def parse_args(args=None):
    args = sys.argv[1:] if args is None else args

    subcommands = list_subcommands()

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
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
        "args",
        help="Arguments for the subcommand",
        nargs=argparse.REMAINDER,
    )
    
    command = parser.parse_args(args)

    if command.help:
        command.subcommand = 'help'
    if command.version:
        command.subcommand = 'version'

    # print('--------------------------------------------')
    # print('Command:     ', sys.argv[0])
    # print('Subcommand:  ', command.subcommand)
    # print('Args to pass:', args[1:])
    # print('--------------------------------------------')

    return command.subcommand, command.args


def main(args=None):
    subcommand, subcommand_args = parse_args(args)
    run_subcommand(subcommand, subcommand_args)
    

if __name__ == '__main__':
    main()
