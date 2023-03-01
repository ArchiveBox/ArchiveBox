#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox schedule'

import sys
import argparse

from typing import Optional, List, IO

from ..main import schedule
from ..util import docstring
from ..config import OUTPUT_DIR
from ..logging_util import SmartFormatter, reject_stdin


@docstring(schedule.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=schedule.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help=("Don't warn about storage space."),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--add', # '-a',
        action='store_true',
        help='Add a new scheduled ArchiveBox update job to cron',
    )
    parser.add_argument(
        '--every', # '-e',
        type=str,
        default=None,
        help='Run ArchiveBox once every [timeperiod] (hour/day/month/year or cron format e.g. "0 0 * * *")',
    )
    parser.add_argument(
        '--depth', # '-d',
        type=int,
        choices=[0, 1],
        default=0,
        help='Depth to archive to [0] or 1, see "add" command help for more info',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Re-archive any URLs that have been previously archived, overwriting existing Snapshots',
    )
    parser.add_argument(
        "--resnapshot",
        default=False,
        action="store_true",
        help="Re-archive URLs from scratch, creating a new snapshot timestamped with the current time"
    )
    parser.add_argument(
        '--update',
        action='store_true',
        help='Re-pull any URLs that have been previously added, as needed to fill missing ArchiveResults',
    )
    group.add_argument(
        '--clear', # '-c'
        action='store_true',
        help=("Stop all ArchiveBox scheduled runs (remove cron jobs)"),
    )
    group.add_argument(
        '--show', # '-s'
        action='store_true',
        help=("Print a list of currently active ArchiveBox cron jobs"),
    )
    group.add_argument(
        '--foreground', '-f',
        action='store_true',
        help=("Launch ArchiveBox scheduler as a long-running foreground task "
              "instead of using cron."),
    )
    group.add_argument(
        '--run-all', # '-a',
        action='store_true',
        help=("Run all the scheduled jobs once immediately, independent of "
              "their configured schedules, can be used together with --foreground"),
    )
    parser.add_argument(
        'import_path',
        nargs='?',
        type=str,
        default=None,
        help=("Check this path and import any new links on every run "
              "(can be either local file or remote URL)"),
    )
    command = parser.parse_args(args or ())
    reject_stdin(__command__, stdin)

    schedule(
        add=command.add,
        show=command.show,
        clear=command.clear,
        foreground=command.foreground,
        run_all=command.run_all,
        quiet=command.quiet,
        every=command.every,
        depth=command.depth,
        overwrite=command.overwrite,
        resnapshot=command.resnapshot,
        update=command.update,
        import_path=command.import_path,
        out_dir=pwd or OUTPUT_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
