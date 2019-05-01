__package__ = 'archivebox.cli'

import os

from typing import Dict, List, Optional, IO
from importlib import import_module

CLI_DIR = os.path.dirname(os.path.abspath(__file__))

# these common commands will appear sorted before any others for ease-of-use
meta_cmds = ('help', 'version')
main_cmds = ('init', 'info', 'config')
archive_cmds = ('add', 'remove', 'update', 'list')

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
                   pwd: Optional[str]=None) -> None:
    """Run a given ArchiveBox subcommand with the given list of args"""

    module = import_module('.archivebox_{}'.format(subcommand), __package__)
    module.main(args=subcommand_args, stdin=stdin, pwd=pwd)    # type: ignore


SUBCOMMANDS = list_subcommands()

__all__ = (
    'SUBCOMMANDS',
    'list_subcommands',
    'run_subcommand',
    *SUBCOMMANDS.keys(),
)
