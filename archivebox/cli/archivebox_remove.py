#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox remove'
__description__ = 'Remove the specified URLs from the archive.'

import sys
import argparse

from typing import Optional, List, IO

from ..main import remove
from ..util import accept_stdin
from ..config import OUTPUT_DIR


def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
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
        'filter_patterns',
        nargs='*',
        type=str,
        help='URLs matching this filter pattern will be removed from the index.'
    )
    command = parser.parse_args(args or ())
    filter_str = accept_stdin(stdin)

    remove(
        filter_str=filter_str,
        filter_patterns=command.filter_patterns,
        filter_type=command.filter_type,
        before=command.before,
        after=command.after,
        yes=command.yes,
        delete=command.delete,
        out_dir=pwd or OUTPUT_DIR,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
