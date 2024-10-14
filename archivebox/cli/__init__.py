__package__ = 'archivebox.cli'
__command__ = 'archivebox'

import os
import sys
import argparse
import threading

from time import sleep
from collections.abc import Mapping

from rich import print

from typing import Optional, List, IO, Union, Iterable
from pathlib import Path

from importlib import import_module

BUILTIN_LIST = list

CLI_DIR = Path(__file__).resolve().parent

# rewrite setup -> install for backwards compatibility
if len(sys.argv) > 1 and sys.argv[1] == 'setup':
    from rich import print
    print(':warning: [bold red]DEPRECATED[/bold red] `archivebox setup` is deprecated, use `archivebox install` instead')
    sys.argv[1] = 'install'

if '--debug' in sys.argv:
    os.environ['DEBUG'] = 'True'
    sys.argv.remove('--debug')


# def list_subcommands() -> Dict[str, str]:
#     """find and import all valid archivebox_<subcommand>.py files in CLI_DIR"""
#     COMMANDS = []
#     for filename in os.listdir(CLI_DIR):
#         if is_cli_module(filename):
#             subcommand = filename.replace('archivebox_', '').replace('.py', '')
#             module = import_module('.archivebox_{}'.format(subcommand), __package__)
#             assert is_valid_cli_module(module, subcommand)
#             COMMANDS.append((subcommand, module.main.__doc__))
#             globals()[subcommand] = module.main
#     display_order = lambda cmd: (
#         display_first.index(cmd[0])
#         if cmd[0] in display_first else
#         100 + len(cmd[0])
#     )
#     return dict(sorted(COMMANDS, key=display_order))

# just define it statically, it's much faster:
SUBCOMMAND_MODULES = {
    'help': 'archivebox_help',
    'version': 'archivebox_version' ,
    
    'init': 'archivebox_init',
    'install': 'archivebox_install',
    ##############################################
    'config': 'archivebox_config',
    'add': 'archivebox_add',
    'remove': 'archivebox_remove',
    'update': 'archivebox_update',
    'list': 'archivebox_list',
    'status': 'archivebox_status',
    
    'schedule': 'archivebox_schedule',
    'server': 'archivebox_server',
    'shell': 'archivebox_shell',
    'manage': 'archivebox_manage',

    # 'oneshot': 'archivebox_oneshot',
}

# every imported command module must have these properties in order to be valid
required_attrs = ('__package__', '__command__', 'main')

# basic checks to make sure imported files are valid subcommands
is_cli_module = lambda fname: fname.startswith('archivebox_') and fname.endswith('.py')
is_valid_cli_module = lambda module, subcommand: (
    all(hasattr(module, attr) for attr in required_attrs)
    and module.__command__.split(' ')[-1] == subcommand
)

class LazySubcommands(Mapping):
    def keys(self):
        return SUBCOMMAND_MODULES.keys()
    
    def values(self):
        return [self[key] for key in self.keys()]
    
    def items(self):
        return [(key, self[key]) for key in self.keys()]
    
    def __getitem__(self, key):
        module = import_module(f'.{SUBCOMMAND_MODULES[key]}', __package__)
        assert is_valid_cli_module(module, key)
        return module.main
    
    def __iter__(self):
        return iter(SUBCOMMAND_MODULES.keys())
    
    def __len__(self):
        return len(SUBCOMMAND_MODULES)

CLI_SUBCOMMANDS = LazySubcommands()


# these common commands will appear sorted before any others for ease-of-use
meta_cmds = ('help', 'version')                               # dont require valid data folder at all
setup_cmds = ('init', 'setup', 'install')                      # require valid data folder, but dont require DB present in it yet
archive_cmds = ('add', 'remove', 'update', 'list', 'status', 'schedule', 'server', 'shell', 'manage')  # require valid data folder + existing db present
fake_db = ("oneshot",)                                        # use fake in-memory db

display_first = (*meta_cmds, *setup_cmds, *archive_cmds)


IGNORED_BG_THREADS = ('MainThread', 'ThreadPoolExecutor', 'IPythonHistorySavingThread', 'Scheduler')  # threads we dont have to wait for before exiting


def wait_for_bg_threads_to_exit(thread_names: Iterable[str]=(), ignore_names: Iterable[str]=IGNORED_BG_THREADS, timeout: int=60) -> int:
    """
    Block until the specified threads exit. e.g. pass thread_names=('default_hook_handler',) to wait for webhooks.
    Useful for waiting for signal handlers, webhooks, etc. to finish running after a mgmt command completes.
    """

    wait_for_all: bool = thread_names == ()

    thread_matches = lambda thread, ptns: any(ptn in repr(thread) for ptn in ptns)

    should_wait = lambda thread: (
        not thread_matches(thread, ignore_names)
        and (wait_for_all or thread_matches(thread, thread_names)))

    for tries in range(timeout):
        all_threads = [*threading.enumerate()]
        blocking_threads = [*filter(should_wait, all_threads)]
        threads_summary = ', '.join(repr(t) for t in blocking_threads)
        if blocking_threads:
            sleep(1)
            if tries == 5:                            # only show stderr message if we need to wait more than 5s
                print(
                    f'[…] Waiting up to {timeout}s for background jobs (e.g. webhooks) to finish...',
                    threads_summary,
                    file=sys.stderr,
                )
        else:
            return tries

    raise Exception(f'Background threads failed to exit after {tries}s: {threads_summary}')



def run_subcommand(subcommand: str,
                   subcommand_args: List[str] | None = None,
                   stdin: Optional[IO]=None,
                   pwd: Union[Path, str, None]=None) -> None:
    """Run a given ArchiveBox subcommand with the given list of args"""

    subcommand_args = subcommand_args or []

    from archivebox.misc.checks import check_migrations
    from archivebox.config.legacy import setup_django
    
    # print('DATA_DIR is', DATA_DIR)
    # print('pwd is', os.getcwd())    

    cmd_requires_db = subcommand in archive_cmds
    init_pending = '--init' in subcommand_args or '--quick-init' in subcommand_args

    check_db = cmd_requires_db and not init_pending

    setup_django(in_memory_db=subcommand in fake_db, check_db=check_db)

    if subcommand in archive_cmds:
        if cmd_requires_db:
            check_migrations()

    module = import_module('.archivebox_{}'.format(subcommand), __package__)
    module.main(args=subcommand_args, stdin=stdin, pwd=pwd)    # type: ignore

    # wait for webhooks, signals, and other background jobs to finish before exit
    wait_for_bg_threads_to_exit(timeout=60)





class NotProvided:
    def __len__(self):
        return 0
    def __bool__(self):
        return False
    def __repr__(self):
        return '<not provided>'

Omitted = Union[None, NotProvided]

OMITTED = NotProvided()


def main(args: List[str] | Omitted=OMITTED, stdin: IO | Omitted=OMITTED, pwd: str | None=None) -> None:
    # print('STARTING CLI MAIN ENTRYPOINT')
    
    args = sys.argv[1:] if args is OMITTED else args
    stdin = sys.stdin if stdin is OMITTED else stdin

    parser = argparse.ArgumentParser(
        prog=__command__,
        description='ArchiveBox: The self-hosted internet archive',
        add_help=False,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--help', '-h',
        action='store_true',
        help=CLI_SUBCOMMANDS['help'].__doc__,
    )
    group.add_argument(
        '--version',
        action='store_true',
        help=CLI_SUBCOMMANDS['version'].__doc__,
    )
    group.add_argument(
        "subcommand",
        type=str,
        help= "The name of the subcommand to run",
        nargs='?',
        choices=CLI_SUBCOMMANDS.keys(),
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

    if command.subcommand not in ('version',):
        from ..logging_util import log_cli_command

        log_cli_command(
            subcommand=command.subcommand,
            subcommand_args=command.subcommand_args,
            stdin=stdin or None,
        )

    try:
        run_subcommand(
            subcommand=command.subcommand,
            subcommand_args=command.subcommand_args,
            stdin=stdin or None,
        )
    except KeyboardInterrupt:
        print('\n\n[red][X] Got CTRL+C. Exiting...[/red]')
