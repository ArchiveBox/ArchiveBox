#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox manage'

import sys
from pathlib import Path
from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR



# @enforce_types
def manage(args: Optional[List[str]]=None, out_dir: Path=DATA_DIR) -> None:
    """Run an ArchiveBox Django management command"""

    check_data_folder()
    from django.core.management import execute_from_command_line

    if (args and "createsuperuser" in args) and (IN_DOCKER and not SHELL_CONFIG.IS_TTY):
        stderr('[!] Warning: you need to pass -it to use interactive commands in docker', color='lightyellow')
        stderr('    docker run -it archivebox manage {}'.format(' '.join(args or ['...'])), color='lightyellow')
        stderr('')
        
    # import ipdb; ipdb.set_trace()

    execute_from_command_line(['manage.py', *(args or ['help'])])





@docstring(manage.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    manage(
        args=args,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
