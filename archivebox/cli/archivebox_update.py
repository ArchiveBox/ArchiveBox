#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox update'
__description__ = 'Import any new links from subscriptions and retry any previously failed/skipped links.'

import sys
import argparse


from ..legacy.util import reject_stdin
from ..legacy.main import update_archive_data


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.add_argument(
        '--only-new', #'-n',
        action='store_true',
        help="Don't attempt to retry previously skipped/failed links when updating",
    )
    parser.add_argument(
        '--resume', #'-r',
        type=float,
        help='Resume the update process from a given timestamp',
        default=None,
    )
    command = parser.parse_args(args)
    reject_stdin(__command__)

    update_archive_data(
        import_path=None,
        resume=command.resume,
        only_new=command.only_new,
    )
    

if __name__ == '__main__':
    main()
