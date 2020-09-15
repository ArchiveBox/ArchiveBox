#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox oneshot'

import sys
import argparse

from pathlib import Path
from typing import List, Optional, IO

from ..main import oneshot
from ..util import docstring
from ..config import OUTPUT_DIR
from ..logging_util import SmartFormatter, accept_stdin, stderr


@docstring(oneshot.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=oneshot.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        'url',
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
        '--out-dir',
        type=str,
        default=OUTPUT_DIR,
        help= "Path to save the single archive folder to, e.g. ./example.com_archive"
    )
    command = parser.parse_args(args or ())
    url = command.url
    stdin_url = accept_stdin(stdin)
    if (stdin_url and url) or (not stdin and not url):
        stderr(
            '[X] You must pass a URL/path to add via stdin or CLI arguments.\n',
            color='red',
        )
        raise SystemExit(2)
    
    oneshot(
        url=stdin_url or url,
        out_dir=Path(command.out_dir).resolve(),
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
