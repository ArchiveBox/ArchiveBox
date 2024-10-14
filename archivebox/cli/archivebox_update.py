#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox update'

import sys
import argparse
from pathlib import Path
from typing import List, Optional, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from ..index import (
    LINK_FILTERS,
    get_indexed_folders,
    get_archived_folders,
    get_unarchived_folders,
    get_present_folders,
    get_valid_folders,
    get_invalid_folders,
    get_duplicate_folders,
    get_orphaned_folders,
    get_corrupted_folders,
    get_unrecognized_folders,
)
from ..logging_util import SmartFormatter, accept_stdin
from ..main import update


@docstring(update.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=update.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--only-new', #'-n',
        action='store_true',
        help="Don't attempt to retry previously skipped/failed links when updating",
    )
    parser.add_argument(
        '--index-only', #'-o',
        action='store_true',
        help="Update the main index without archiving any content",
    )
    parser.add_argument(
        '--resume', #'-r',
        type=float,
        help='Resume the update process from a given timestamp',
        default=None,
    )
    parser.add_argument(
        '--overwrite', #'-x',
        action='store_true',
        help='Ignore existing archived content and overwrite with new versions (DANGEROUS)',
    )
    parser.add_argument(
        '--before', #'-b',
        type=float,
        help="Update only links bookmarked before the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--after', #'-a',
        type=float,
        help="Update only links bookmarked after the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--status',
        type=str,
        choices=('indexed', 'archived', 'unarchived', 'present', 'valid', 'invalid', 'duplicate', 'orphaned', 'corrupted', 'unrecognized'),
        default='indexed',
        help=(
            'Update only links or data directories that have the given status\n'
            f'    indexed       {get_indexed_folders.__doc__} (the default)\n'
            f'    archived      {get_archived_folders.__doc__}\n'
            f'    unarchived    {get_unarchived_folders.__doc__}\n'
            '\n'
            f'    present       {get_present_folders.__doc__}\n'
            f'    valid         {get_valid_folders.__doc__}\n'
            f'    invalid       {get_invalid_folders.__doc__}\n'
            '\n'
            f'    duplicate     {get_duplicate_folders.__doc__}\n'
            f'    orphaned      {get_orphaned_folders.__doc__}\n'
            f'    corrupted     {get_corrupted_folders.__doc__}\n'
            f'    unrecognized  {get_unrecognized_folders.__doc__}\n'
        )
    )
    parser.add_argument(
        '--filter-type', '-t',
        type=str,
        choices=(*LINK_FILTERS.keys(), 'search'),
        default='exact',
        help='Type of pattern matching to use when filtering URLs',
    )
    parser.add_argument(
        'filter_patterns',
        nargs='*',
        type=str,
        default=None,
        help='Update only URLs matching these filter patterns.'
    )
    parser.add_argument(
        "--extract",
        type=str,
        help="Pass a list of the extractors to be used. If the method name is not correct, it will be ignored. \
              This does not take precedence over the configuration",
        default=""
    )
    command = parser.parse_args(args or ())

    filter_patterns_str = None
    if not command.filter_patterns:
        filter_patterns_str = accept_stdin(stdin)

    update(
        resume=command.resume,
        only_new=command.only_new,
        index_only=command.index_only,
        overwrite=command.overwrite,
        filter_patterns_str=filter_patterns_str,
        filter_patterns=command.filter_patterns,
        filter_type=command.filter_type,
        status=command.status,
        after=command.after,
        before=command.before,
        out_dir=Path(pwd) if pwd else DATA_DIR,
        extractors=command.extract,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
