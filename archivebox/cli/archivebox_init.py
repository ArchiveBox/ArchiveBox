#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox init'
__description__ = 'Initialize a new ArchiveBox collection in the current directory'

import os
import sys
import argparse

from ..legacy.util import reject_stdin
from ..legacy.main import init


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args)
    reject_stdin(__command__)

    init()
    

if __name__ == '__main__':
    main()
