#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox list'
__description__ = 'List all the URLs currently in the archive.'

import sys
import argparse

from ..legacy.util import SmartFormatter, reject_stdin, to_json, to_csv
from ..legacy.config import check_data_folder, OUTPUT_DIR
from ..legacy.main import (
    list_archive_data,
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

def main(args=None):
    check_data_folder()
    
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--csv', #'-c',
        type=str,
        help="Print the output in CSV format with the given columns, e.g.: timestamp,url,extension",
        default=None,
    )
    group.add_argument(
        '--json', #'-j',
        action='store_true',
        help="Print the output in JSON format with all columns included.",
    )
    parser.add_argument(
        '--sort', #'-s',
        type=str,
        help="List the links sorted using the given key, e.g. timestamp or updated.",
        default=None,
    )
    parser.add_argument(
        '--before', #'-b',
        type=float,
        help="List only links bookmarked before the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--after', #'-a',
        type=float,
        help="List only links bookmarked after the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--status',
        type=str,
        choices=('indexed', 'archived', 'unarchived', 'present', 'valid', 'invalid', 'duplicate', 'orphaned', 'corrupted', 'unrecognized'),
        default='indexed',
        help=(
            'List only links or data directories that have the given status\n'
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
        '--filter-type',
        type=str,
        choices=('exact', 'substring', 'domain', 'regex'),
        default='exact',
        help='Type of pattern matching to use when filtering URLs',
    )
    parser.add_argument(
        'patterns',
        nargs='*',
        type=str,
        default=None,
        help='List only URLs matching these filter patterns.'
    )
    command = parser.parse_args(args)
    reject_stdin(__command__)

    links = list_archive_data(
        filter_patterns=command.patterns,
        filter_type=command.filter_type,
        before=command.before,
        after=command.after,
    )

    if command.sort:
        links = sorted(links, key=lambda link: getattr(link, command.sort))

    if command.status == 'indexed':
        folders = get_indexed_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'archived':
        folders = get_archived_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'unarchived':
        folders = get_unarchived_folders(links, out_dir=OUTPUT_DIR)

    elif command.status == 'present':
        folders = get_present_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'valid':
        folders = get_valid_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'invalid':
        folders = get_invalid_folders(links, out_dir=OUTPUT_DIR)

    elif command.status == 'duplicate':
        folders = get_duplicate_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'orphaned':
        folders = get_orphaned_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'corrupted':
        folders = get_corrupted_folders(links, out_dir=OUTPUT_DIR)
    elif command.status == 'unrecognized':
        folders = get_unrecognized_folders(links, out_dir=OUTPUT_DIR)

    if command.csv:
        print(to_csv(folders.values(), csv_cols=command.csv.split(','), header=True))
    elif command.json:
        print(to_json(folders.values(), indent=4, sort_keys=True))
    else:
        print('\n'.join(f'{folder} {link}' for folder, link in folders.items()))
    raise SystemExit(not folders)

if __name__ == '__main__':
    main()
