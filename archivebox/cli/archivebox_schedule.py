#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox schedule'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.misc.logging_util import SmartFormatter, reject_stdin
from archivebox.config.common import ARCHIVING_CONFIG


# @enforce_types
def schedule(add: bool=False,
             show: bool=False,
             clear: bool=False,
             foreground: bool=False,
             run_all: bool=False,
             quiet: bool=False,
             every: Optional[str]=None,
             tag: str='',
             depth: int=0,
             overwrite: bool=False,
             update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
             import_path: Optional[str]=None,
             out_dir: Path=DATA_DIR):
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
    
    check_data_folder()
    from abx_plugin_pip.binaries import ARCHIVEBOX_BINARY
    from archivebox.config.permissions import USER

    Path(CONSTANTS.LOGS_DIR).mkdir(exist_ok=True)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)

    if clear:
        print(cron.remove_all(comment=CRON_COMMENT))
        cron.write()
        raise SystemExit(0)

    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if every or add:
        every = every or 'day'
        quoted = lambda s: f'"{s}"' if (s and ' ' in str(s)) else str(s)
        cmd = [
            'cd',
            quoted(out_dir),
            '&&',
            quoted(ARCHIVEBOX_BINARY.load().abspath),
            *([
                'add',
                *(['--overwrite'] if overwrite else []),
                *(['--update'] if update else []),
                *([f'--tag={tag}'] if tag else []),
                f'--depth={depth}',
                f'"{import_path}"',
            ] if import_path else ['update']),
            '>>',
            quoted(Path(CONSTANTS.LOGS_DIR) / 'schedule.log'),
            '2>&1',

        ]
        new_job = cron.new(command=' '.join(cmd), comment=CRON_COMMENT)

        if every in ('minute', 'hour', 'day', 'month', 'year'):
            set_every = getattr(new_job.every(), every)
            set_every()
        elif CronSlices.is_valid(every):
            new_job.setall(every)
        else:
            stderr('{red}[X] Got invalid timeperiod for cron task.{reset}'.format(**SHELL_CONFIG.ANSI))
            stderr('    It must be one of minute/hour/day/month')
            stderr('    or a quoted cron-format schedule like:')
            stderr('        archivebox init --every=day --depth=1 https://example.com/some/rss/feed.xml')
            stderr('        archivebox init --every="0/5 * * * *" --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        cron = dedupe_cron_jobs(cron)
        cron.write()

        total_runs = sum(j.frequency_per_year() for j in cron)
        existing_jobs = list(cron.find_comment(CRON_COMMENT))

        print()
        print('{green}[√] Scheduled new ArchiveBox cron job for user: {} ({} jobs are active).{reset}'.format(USER, len(existing_jobs), **SHELL_CONFIG.ANSI))
        print('\n'.join(f'  > {cmd}' if str(cmd) == str(new_job) else f'    {cmd}' for cmd in existing_jobs))
        if total_runs > 60 and not quiet:
            stderr()
            stderr('{lightyellow}[!] With the current cron config, ArchiveBox is estimated to run >{} times per year.{reset}'.format(total_runs, **SHELL_CONFIG.ANSI))
            stderr('    Congrats on being an enthusiastic internet archiver! 👌')
            stderr()
            stderr('    Make sure you have enough storage space available to hold all the data.')
            stderr('    Using a compressed/deduped filesystem like ZFS is recommended if you plan on archiving a lot.')
            stderr('')
    elif show:
        if existing_jobs:
            print('\n'.join(str(cmd) for cmd in existing_jobs))
        else:
            stderr('{red}[X] There are no ArchiveBox cron jobs scheduled for your user ({}).{reset}'.format(USER, **SHELL_CONFIG.ANSI))
            stderr('    To schedule a new job, run:')
            stderr('        archivebox schedule --every=[timeperiod] --depth=1 https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)
    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if foreground or run_all:
        if not existing_jobs:
            stderr('{red}[X] You must schedule some jobs first before running in foreground mode.{reset}'.format(**SHELL_CONFIG.ANSI))
            stderr('    archivebox schedule --every=hour --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        print('{green}[*] Running {} ArchiveBox jobs in foreground task scheduler...{reset}'.format(len(existing_jobs), **SHELL_CONFIG.ANSI))
        if run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command.split("/archivebox ")[0].split(" && ")[0]}\n')
                    sys.stdout.write(f'    > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r    √ {job.command.split("/archivebox ")[-1]}\n')
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**SHELL_CONFIG.ANSI))
                raise SystemExit(1)

        if foreground:
            try:
                for job in existing_jobs:
                    print(f'  > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                for result in cron.run_scheduler():
                    print(result)
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**SHELL_CONFIG.ANSI))
                raise SystemExit(1)

    # if CAN_UPGRADE:
    #     hint(f"There's a new version of ArchiveBox available! Your current version is {VERSION}. You can upgrade to {VERSIONS_AVAILABLE['recommended_version']['tag_name']} ({VERSIONS_AVAILABLE['recommended_version']['html_url']}). For more on how to upgrade: https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives\n")



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
        '--tag', '-t',
        type=str,
        default='',
        help="Tag the added URLs with the provided tags e.g. --tag=tag1,tag2,tag3",
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
        tag=command.tag,
        depth=command.depth,
        overwrite=command.overwrite,
        update=command.update,
        import_path=command.import_path,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
