#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox server'
__description__ = 'Run the ArchiveBox HTTP server'

import sys
import argparse

from ..legacy.config import setup_django
from ..legacy.util import reject_stdin


def main(args=None):
    args = sys.argv[1:] if args is None else args

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
    command = parser.parse_args(args)
    reject_stdin(__command__)
    
    setup_django()
    from django.core.management import call_command
    call_command("runserver", *command.runserver_args)


if __name__ == '__main__':
    main()
