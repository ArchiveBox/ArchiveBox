#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'

import sys
import argparse

from typing import List, Optional, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.config.common import ARCHIVING_CONFIG

from ..main import add
from ..parsers import PARSERS
from ..logging_util import SmartFormatter, accept_stdin, stderr


@docstring(add.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=add.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--tag', '-t',
        type=str,
        default='',
        help="Tag the added URLs with the provided tags e.g. --tag=tag1,tag2,tag3",
    )
    parser.add_argument(
        '--update', #'-u',
        action='store_true',
        default=not ARCHIVING_CONFIG.ONLY_NEW,  # when ONLY_NEW=True we skip updating old links
        help="Also retry previously skipped/failed links when adding new links",
    )
    parser.add_argument(
        '--update-all', #'-n',
        action='store_true',
        default=False, 
        help="Also update ALL links in index when finished adding new links",
    )
    parser.add_argument(
        '--index-only', #'-o',
        action='store_true',
        help="Add the links to the main index without archiving them",
    )
    parser.add_argument(
        'urls',
        nargs='*',
        type=str,
        default=None,
        help=(
            'URLs or paths to archive e.g.:\n'
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
        choices=[0, 1],
        type=int,
        help="Recursively archive all linked pages up to this many hops away"
    )
    parser.add_argument(
        "--overwrite",
        default=False,
        action="store_true",
        help="Re-archive URLs from scratch, overwriting any existing files"
    )
    parser.add_argument(
        "--init", #'-i',
        action='store_true',
        help="Init/upgrade the curent data directory before adding",
    )
    parser.add_argument(
        "--extract",
        type=str,
        help="Pass a list of the extractors to be used. If the method name is not correct, it will be ignored. \
              This does not take precedence over the configuration",
        default=""
    )
    parser.add_argument(
        "--parser",
        type=str,
        help="Parser used to read inputted URLs.",
        default="auto",
        choices=["auto", *PARSERS.keys()],
    )
    command = parser.parse_args(args or ())
    urls = command.urls

    stdin_urls = ''
    if not urls:
        stdin_urls = accept_stdin(stdin)

    if (stdin_urls and urls) or (not stdin and not urls):
        stderr(
            '[X] You must pass URLs/paths to add via stdin or CLI arguments.\n',
            color='red',
        )
        raise SystemExit(2)
    add(
        urls=stdin_urls or urls,
        depth=command.depth,
        tag=command.tag,
        update=command.update,
        update_all=command.update_all,
        index_only=command.index_only,
        overwrite=command.overwrite,
        init=command.init,
        extractors=command.extract,
        parser=command.parser,
        out_dir=pwd or DATA_DIR,
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
