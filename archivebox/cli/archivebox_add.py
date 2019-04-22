#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'
__description__ = 'Add a new URL or list of URLs to your archive'

import sys
import argparse

from ..legacy.config import stderr, check_dependencies, check_data_folder
from ..legacy.util import (
    handle_stdin_import,
    handle_file_import,
)
from ..legacy.main import update_archive_data


def main(args=None, stdin=None):
    check_data_folder()
    
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    # parser.add_argument(
    #     '--depth', #'-d',
    #     type=int,
    #     help='Recursively archive all linked pages up to this many hops away',
    #     default=0,
    # )
    parser.add_argument(
        '--only-new', #'-n',
        action='store_true',
        help="Don't attempt to retry previously skipped/failed links when updating",
    )
    # parser.add_argument(
    #     '--mirror', #'-m',
    #     action='store_true',
    #     help='Archive an entire site (finding all linked pages below it on the same domain)',
    # )
    # parser.add_argument(
    #     '--crawler', #'-r',
    #     choices=('depth_first', 'breadth_first'),
    #     help='Controls which crawler to use in order to find outlinks in a given page',
    #     default=None,
    # )
    parser.add_argument(
        'url',
        nargs='?',
        type=str,
        default=None,
        help='URL of page to archive (or path to local file)'
    )
    command = parser.parse_args(args)

    check_dependencies()

    ### Handle ingesting urls piped in through stdin
    # (.e.g if user does cat example_urls.txt | archivebox add)
    import_path = None
    if stdin or not sys.stdin.isatty():
        stdin_raw_text = stdin or sys.stdin.read()
        if stdin_raw_text and command.url:
            stderr(
                '[X] You should pass either a path as an argument, '
                'or pass a list of links via stdin, but not both.\n'
            )
            raise SystemExit(1)

        import_path = handle_stdin_import(stdin_raw_text)

    ### Handle ingesting url from a remote file/feed
    # (e.g. if an RSS feed URL is used as the import path) 
    elif command.url:
        import_path = handle_file_import(command.url)

    update_archive_data(
        import_path=import_path,
        resume=None,
        only_new=command.only_new,
    )


if __name__ == '__main__':
    main()
