#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox install'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from ..logging_util import SmartFormatter, reject_stdin
from ..main import install


@docstring(install.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=install.__doc__,
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

    install(
        # force=command.force,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
