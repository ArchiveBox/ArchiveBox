__package__ = 'archivebox.cli'
__command__ = 'archivebox'

import os
import sys
import argparse

from typing import Optional, Dict, List, IO, Union
from pathlib import Path

from ..config import OUTPUT_DIR, check_data_folder, check_migrations

from importlib import import_module

CLI_DIR = Path(__file__).resolve().parent

# these common commands will appear sorted before any others for ease-of-use
meta_cmds = ('help', 'version')                               # dont require valid data folder at all
main_cmds = ('init', 'config', 'setup')                       # dont require existing db present
archive_cmds = ('add', 'remove', 'update', 'list', 'status')  # require existing db present
fake_db = ("oneshot",)                                        # use fake in-memory db

display_first = (*meta_cmds, *main_cmds, *archive_cmds)

# every imported command module must have these properties in order to be valid
required_attrs = ('__package__', '__command__', 'main')

# basic checks to make sure imported files are valid subcommands
is_cli_module = lambda fname: fname.startswith('archivebox_') and fname.endswith('.py')
is_valid_cli_module = lambda module, subcommand: (
    all(hasattr(module, attr) for attr in required_attrs)
    and module.__command__.split(' ')[-1] == subcommand
)


def list_subcommands() -> Dict[str, str]:
    """find and import all valid archivebox_<subcommand>.py files in CLI_DIR"""

    COMMANDS = []
    for filename in os.listdir(CLI_DIR):
        if is_cli_module(filename):
            subcommand = filename.replace('archivebox_', '').replace('.py', '')
            module = import_module('.archivebox_{}'.format(subcommand), __package__)
            assert is_valid_cli_module(module, subcommand)
            COMMANDS.append((subcommand, module.main.__doc__))
            globals()[subcommand] = module.main

    display_order = lambda cmd: (
        display_first.index(cmd[0])
        if cmd[0] in display_first else
        100 + len(cmd[0])
    )

    return dict(sorted(COMMANDS, key=display_order))


def run_subcommand(subcommand: str,
                   subcommand_args: List[str]=None,
                   stdin: Optional[IO]=None,
                   pwd: Union[Path, str, None]=None) -> None:
    """Run a given ArchiveBox subcommand with the given list of args"""

    subcommand_args = subcommand_args or []

    if subcommand not in meta_cmds:
        from ..config import setup_django

        cmd_requires_db = subcommand in archive_cmds
        init_pending = '--init' in subcommand_args or '--quick-init' in subcommand_args

        if cmd_requires_db:
            check_data_folder(pwd)

        setup_django(in_memory_db=subcommand in fake_db, check_db=cmd_requires_db and not init_pending)

        if cmd_requires_db:
            check_migrations()

    module = import_module('.archivebox_{}'.format(subcommand), __package__)
    module.main(args=subcommand_args, stdin=stdin, pwd=pwd)    # type: ignore


SUBCOMMANDS = list_subcommands()

class NotProvided:
    pass


def main(args: Optional[List[str]]=NotProvided, stdin: Optional[IO]=NotProvided, pwd: Optional[str]=None) -> None:
    args = sys.argv[1:] if args is NotProvided else args
    stdin = sys.stdin if stdin is NotProvided else stdin

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

    if command.version:
        command.subcommand = 'version'
    elif command.help or command.subcommand is None:
        command.subcommand = 'help'

    if command.subcommand not in ('help', 'version', 'status'):
        from ..logging_util import log_cli_command

        log_cli_command(
            subcommand=command.subcommand,
            subcommand_args=command.subcommand_args,
            stdin=stdin,
            pwd=pwd or OUTPUT_DIR
        )

    run_subcommand(
        subcommand=command.subcommand,
        subcommand_args=command.subcommand_args,
        stdin=stdin,
        pwd=pwd or OUTPUT_DIR,
    )


__all__ = (
    'SUBCOMMANDS',
    'list_subcommands',
    'run_subcommand',
    *SUBCOMMANDS.keys(),
)


