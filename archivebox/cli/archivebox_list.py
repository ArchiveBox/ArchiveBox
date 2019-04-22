#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox list'
__description__ = 'List all the URLs currently in the archive.'

import sys
import argparse


from ..legacy.util import reject_stdin, to_json, to_csv
from ..legacy.config import check_data_folder
from ..legacy.main import list_archive_data


def main(args=None):
    check_data_folder()
    
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
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
        help="List only URLs bookmarked before the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--after', #'-a',
        type=float,
        help="List only URLs bookmarked after the given timestamp.",
        default=None,
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


    if command.csv:
        print(to_csv(links, csv_cols=command.csv.split(','), header=True))
    elif command.json:
        print(to_json(list(links), indent=4, sort_keys=True))
    else:
        print('\n'.join(link.url for link in links))
    

if __name__ == '__main__':
    main()
