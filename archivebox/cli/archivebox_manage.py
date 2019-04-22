#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox manage'
__description__ = 'Run an ArchiveBox Django management command'

import sys

from ..legacy.config import OUTPUT_DIR, setup_django, check_data_folder


def main(args=None):
    check_data_folder()

    setup_django(OUTPUT_DIR)
    from django.core.management import execute_from_command_line

    args = sys.argv if args is None else ['archivebox', *args]

    args[0] = f'{sys.argv[0]} manage'

    if args[1:] == []:
        args.append('help')
    
    execute_from_command_line(args)


if __name__ == '__main__':
    main()
