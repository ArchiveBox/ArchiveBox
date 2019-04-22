#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox remove'
__description__ = 'Remove the specified URLs from the archive.'

import sys
import argparse


from ..legacy.main import remove_archive_links
from ..legacy.util import reject_stdin


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.add_argument(
        '--yes', # '-y',
        action='store_true',
        help='Remove links instantly without prompting to confirm.',
    )
    parser.add_argument(
        '--delete', # '-r',
        action='store_true',
        help=(
            "In addition to removing the link from the index, "
            "also delete its archived content and metadata folder."
        ),
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
        'pattern',
        nargs='*',
        type=str,
        default=None,
        help='URLs matching this filter pattern will be removed from the index.'
    )
    command = parser.parse_args(args)

    if not sys.stdin.isatty():
        stdin_raw_text = sys.stdin.read()
        if stdin_raw_text and command.url:
            print(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin, but not both.\n'
            )
            raise SystemExit(1)

        patterns = [pattern.strip() for pattern in stdin_raw_text.split('\n')]
    else:
        patterns = command.pattern

    remove_archive_links(
        filter_patterns=patterns, filter_type=command.filter_type,
        before=command.before, after=command.after,
        yes=command.yes, delete=command.delete,
    )
    

if __name__ == '__main__':
    main()
