#!/usr/bin/env python3
# archivebox [command]

__package__ = 'archivebox.cli'
__command__ = 'archivebox'
__description__ = 'ArchiveBox: The self-hosted internet archive.'

import os
import sys
import argparse

from . import list_subcommands, run_subcommand
from ..legacy.config import OUTPUT_DIR


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


def print_import_tutorial():
    print('Welcome to ArchiveBox!')
    print()
    print('To import an existing archive (from a previous version of ArchiveBox):')
    print('    1. cd into your data dir OUTPUT_DIR (usually ArchiveBox/output) and run:')
    print('    2. archivebox init')
    print()
    print('To start a new archive:')
    print('    1. Create an emptry directory, then cd into it and run:')
    print('    2. archivebox init')
    print()
    print('For more information, see the migration docs here:')
    print('    https://github.com/pirate/ArchiveBox/wiki/Migration')

def main(args=None):
    subcommand, subcommand_args = parse_args(args)
    existing_index = os.path.exists(os.path.join(OUTPUT_DIR, 'index.json'))

    if subcommand is None:
        if existing_index:
            run_subcommand('help', subcommand_args)
        else:
            print_import_tutorial()
        raise SystemExit(0)

    run_subcommand(subcommand, subcommand_args)
    

if __name__ == '__main__':
    main()
