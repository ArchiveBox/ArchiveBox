#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox init'
__description__ = 'Initialize a new ArchiveBox collection in the current directory'

import sys
import argparse

from typing import Optional, List, IO

from ..main import init
from ..util import reject_stdin
from ..config import OUTPUT_DIR


def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args or ())
    reject_stdin(__command__, stdin)

    init(out_dir=pwd or OUTPUT_DIR)
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
