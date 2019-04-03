#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox list'
__description__ = 'List all the URLs currently in the archive.'

import sys
import json
import argparse


from ..legacy.util import reject_stdin, ExtendedEncoder
from ..legacy.main import list_archive_data, csv_format


def main(args=None):
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
        '--filter', #'-f',
        type=str,
        help="List only URLs matching the given regex pattern.",
        default=None,
    )
    parser.add_argument(
        '--sort', #'-s',
        type=str,
        help="List the links sorted using the given key, e.g. timestamp or updated",
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
    command = parser.parse_args(args)
    reject_stdin(__command__)

    links = list_archive_data(
        filter_regex=command.filter,
        before=command.before,
        after=command.after,
    )
    if command.sort:
        links = sorted(links, key=lambda link: getattr(link, command.sort))

    if command.csv:
        print(command.csv)
        print('\n'.join(csv_format(link, command.csv) for link in links))
    elif command.json:
        print(json.dumps(list(links), indent=4, cls=ExtendedEncoder))
    else:
        print('\n'.join(link.url for link in links))
    

if __name__ == '__main__':
    main()
