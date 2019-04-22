#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox info'
__description__ = 'Print out some info and statistics about the archive collection'

import sys
import argparse

from ..legacy.config import check_data_folder
from ..legacy.util import reject_stdin
from ..legacy.main import info


def main(args=None):
    check_data_folder()
    
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args)
    reject_stdin(__command__)

    info()

if __name__ == '__main__':
    main()
