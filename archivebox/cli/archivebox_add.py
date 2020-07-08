#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'

import sys
import argparse

from typing import List, Optional, IO

from ..main import add, docstring
from ..config import OUTPUT_DIR, ONLY_NEW
from .logging import SmartFormatter, accept_stdin


@docstring(add.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=add.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--update-all', #'-n',
        action='store_true',
        default=not ONLY_NEW,  # when ONLY_NEW=True we skip updating old links
        help="Also retry previously skipped/failed links when adding new links",
    )
    parser.add_argument(
        '--index-only', #'-o',
        action='store_true',
        help="Add the links to the main index without archiving them",
    )
    parser.add_argument(
        'import_path',
        nargs='?',
        type=str,
        default=None,
        help=(
            'URL or path to local file to start the archiving process from. e.g.:\n'
            '    https://getpocket.com/users/USERNAME/feed/all\n'
            '    https://example.com/some/rss/feed.xml\n'
            '    https://example.com\n'
            '    ~/Downloads/firefox_bookmarks_export.html\n'
            '    ~/Desktop/sites_list.csv\n'
        )
    )
    parser.add_argument(
        "--depth",
        action="store",
        default=0,
        choices=[0,1],
        type=int,
        help="Recursively archive all linked pages up to this many hops away"
    )
    command = parser.parse_args(args or ())
    import_string = accept_stdin(stdin)
    if import_string and command.import_path:
        stderr(
            '[X] You should pass an import path or a page url as an argument or in stdin but not both\n',
            color='red',
        )
        raise SystemExit(2)
    elif import_string:
        import_path = import_string
    else:
        import_path = command.import_path

    add(
        url=import_path,
        depth=command.depth,
        update_all=command.update_all,
        index_only=command.index_only,
        out_dir=pwd or OUTPUT_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)


# TODO: Implement these
#
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
