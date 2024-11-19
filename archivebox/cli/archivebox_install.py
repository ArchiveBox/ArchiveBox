#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox install'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.misc.logging_util import SmartFormatter, reject_stdin
from ..main import install


@docstring(install.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=install.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--binproviders', '-p',
        type=str,
        help='Select binproviders to use DEFAULT=env,apt,brew,sys_pip,venv_pip,lib_pip,pipx,sys_npm,lib_npm,puppeteer,playwright (all)',
        default=None,
    )
    parser.add_argument(
        '--binaries', '-b',
        type=str,
        help='Select binaries to install DEFAULT=curl,wget,git,yt-dlp,chrome,single-file,readability-extractor,postlight-parser,... (all)',
        default=None,
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Show what would be installed without actually installing anything',
        default=False,
    )
    command = parser.parse_args(args or ())   # noqa
    reject_stdin(__command__, stdin)

    install(
        # force=command.force,
        out_dir=Path(pwd) if pwd else DATA_DIR,
        binaries=command.binaries.split(',') if command.binaries else None,
        binproviders=command.binproviders.split(',') if command.binproviders else None,
        dry_run=command.dry_run,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
