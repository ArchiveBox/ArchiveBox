#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox setup'

import sys
import argparse

from typing import Optional, List, IO

from ..main import setup
from ..util import docstring
from ..config import OUTPUT_DIR
from ..logging_util import SmartFormatter, reject_stdin


@docstring(setup.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=setup.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    # parser.add_argument(
    #     '--force', # '-f',
    #     action='store_true',
    #     help='Overwrite any existing packages that conflict with the ones ArchiveBox is trying to install',
    # )
    command = parser.parse_args(args or ())   # noqa
    reject_stdin(__command__, stdin)

    setup(
        # force=command.force,
        out_dir=pwd or OUTPUT_DIR,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
