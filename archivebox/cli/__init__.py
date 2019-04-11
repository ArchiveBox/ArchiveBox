__package__ = 'archivebox.cli'

import os
from importlib import import_module

CLI_DIR = os.path.dirname(os.path.abspath(__file__))

required_attrs = ('__package__', '__command__', '__description__', 'main')


order = ('help', 'version', 'init', 'list', 'update', 'add', 'remove')


def list_subcommands():
    COMMANDS = []
    for filename in os.listdir(CLI_DIR):
        if filename.startswith('archivebox_') and filename.endswith('.py'):
            subcommand = filename.replace('archivebox_', '').replace('.py', '')
            module = import_module('.archivebox_{}'.format(subcommand), __package__)

            assert all(hasattr(module, attr) for attr in required_attrs)
            assert module.__command__.split(' ')[-1] == subcommand
            COMMANDS.append((subcommand, module.__description__))

    return dict(sorted(COMMANDS, key=lambda cmd: order.index(cmd[0]) if cmd[0] in order else 10 + len(cmd[0]))) 


def run_subcommand(subcommand: str, args=None):
    module = import_module('.archivebox_{}'.format(subcommand), __package__)
    return module.main(args)    # type: ignore
