#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox help'
__description__ = 'Print the ArchiveBox help message and usage'

import sys
import argparse

from ..legacy.util import reject_stdin
from . import list_subcommands


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args)
    reject_stdin(__command__)
    

    COMMANDS_HELP_TEXT = '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in list_subcommands().items()
    )

    print(f'''ArchiveBox: The self-hosted internet archive.
Usage:
    archivebox [command] [--help] [--version] [...args]

Comamnds:
    {COMMANDS_HELP_TEXT}

Example Use:
    mkdir my-archive; cd my-archive/
    archivebox init

    echo 'https://example.com/some/page' | archivebox add
    archivebox add https://example.com/some/other/page
    archivebox add --depth=1 ~/Downloads/bookmarks_export.html
    archivebox add --depth=1 https://example.com/feed.rss
    archivebox update --resume=15109948213.123

Documentation:
    https://github.com/pirate/ArchiveBox/wiki
''')


if __name__ == '__main__':
    main()
