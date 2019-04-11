#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox help'
__description__ = 'Print the ArchiveBox help message and usage'

import sys
import argparse

from ..legacy.util import reject_stdin
from ..legacy.config import ANSI
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

    print('''{green}ArchiveBox: The self-hosted internet archive.{reset}
        
{lightblue}Usage:{reset}
    archivebox [command] [--help] [--version] [...args]

{lightblue}Comamnds:{reset}
    {}

{lightblue}Example Use:{reset}
    mkdir my-archive; cd my-archive/
    archivebox init

    archivebox add https://example.com/some/page
    archivebox add --depth=1 ~/Downloads/bookmarks_export.html
    
    archivebox subscribe https://example.com/some/feed.rss
    archivebox update --resume=15109948213.123
    archivebox list --sort=timestamp --csv=timestamp,url,is_archived

{lightblue}Documentation:{reset}
    https://github.com/pirate/ArchiveBox/wiki
'''.format(COMMANDS_HELP_TEXT, **ANSI))


if __name__ == '__main__':
    main()
