#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox version'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

# from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR, VERSION
from ..logging_util import SmartFormatter, reject_stdin


# @docstring(version.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    """Print the ArchiveBox version and dependency information"""
    parser = argparse.ArgumentParser(
        prog=__command__,
        description="Print the ArchiveBox version and dependency information",   # version.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Only print ArchiveBox version number and nothing else.',
    )
    command = parser.parse_args(args or ())
    reject_stdin(__command__, stdin)
    
    # for speed reasons, check if quiet flag was set and just return simple version immediately if so
    if command.quiet:
        print(VERSION)
        return
    
    # otherwise do big expensive import to get the full version
    from ..main import version
    version(
        quiet=command.quiet,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
