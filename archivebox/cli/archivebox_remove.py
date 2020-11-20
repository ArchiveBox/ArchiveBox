#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox remove'

import sys
import argparse

from typing import Optional, List, IO

from ..main import remove
from ..util import docstring
from ..config import OUTPUT_DIR
from ..logging_util import SmartFormatter, accept_stdin


@docstring(remove.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=remove.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
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
        choices=('exact', 'substring', 'domain', 'regex','tag'),
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
