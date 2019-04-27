#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox info'
__description__ = 'Print out some info and statistics about the archive collection'

import sys
import argparse

from typing import Optional, List, IO

from ..main import info
from ..config import OUTPUT_DIR
from ..util import reject_stdin


def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args or ())
    reject_stdin(__command__, stdin)

    info(out_dir=pwd or OUTPUT_DIR)


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
