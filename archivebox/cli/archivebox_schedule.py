#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox schedule'
__description__ = 'Set ArchiveBox to run regularly at a specific time'

import os
import sys
import argparse

from datetime import datetime
from crontab import CronTab, CronSlices


from ..legacy.util import reject_stdin
from ..legacy.config import (
    OUTPUT_DIR,
    LOGS_DIR,
    ARCHIVEBOX_BINARY,
    USER,
    ANSI,
    stderr,
)


CRON_COMMENT = 'archivebox_schedule'


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
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
        default='daily',
        help='Run ArchiveBox once every [timeperiod] (hour/day/week/month/year or cron format e.g. "0 0 * * *")',
    )
    group.add_argument(
        '--clear', # '-c'
        action='store_true',
        help=("Stop all ArchiveBox scheduled runs, clear it completely from cron"),
    )
    group.add_argument(
        '--show', # '-s'
        action='store_true',
        help=("Print a list of currently active ArchiveBox cron jobs"),
    )
    group.add_argument(
        '--foreground', '-f',
        action='store_true',
        help=("Launch ArchiveBox as a long-running foreground task "
              "instead of using cron."),
    )
    group.add_argument(
        '--run-all', # '-a',
        action='store_true',
        help='Run all the scheduled jobs once immediately, independent of their configured schedules',
    )
    parser.add_argument(
        'import_path',
        nargs='?',
        type=str,
        default=None,
        help=("Check this path and import any new links on every run "
              "(can be either local file or remote URL)"),
    )
    command = parser.parse_args(args)
    reject_stdin(__command__)

    os.makedirs(LOGS_DIR, exist_ok=True)

    cron = CronTab(user=True)
    cron = dedupe_jobs(cron)

    existing_jobs = list(cron.find_comment(CRON_COMMENT))
    if command.foreground or command.run_all:
        if command.import_path or (not existing_jobs):
            stderr('{red}[X] You must schedule some jobs first before running in foreground mode.{reset}'.format(**ANSI))
            stderr('    archivebox schedule --every=hour https://example.com/some/rss/feed.xml')
            raise SystemExit(1)
        print('{green}[*] Running {} ArchiveBox jobs in foreground task scheduler...{reset}'.format(len(existing_jobs), **ANSI))
        if command.run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r  √ {job.command}\n')
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)
        if command.foreground:
            try:
                for result in cron.run_scheduler():
                    print(result)
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)

    elif command.show:
        if existing_jobs:
            print('\n'.join(str(cmd) for cmd in existing_jobs))
        else:
            stderr('{red}[X] There are no ArchiveBox cron jobs scheduled for your user ({}).{reset}'.format(USER, **ANSI))
            stderr('    To schedule a new job, run:')
            stderr('        archivebox schedule --every=[timeperiod] https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    elif command.clear:
        print(cron.remove_all(comment=CRON_COMMENT))
        cron.write()
        raise SystemExit(0)

    elif command.every:
        quoted = lambda s: f'"{s}"' if s and ' ' in s else s
        cmd = [
            'cd',
            quoted(OUTPUT_DIR),
            '&&',
            quoted(ARCHIVEBOX_BINARY),
            *(('add', f'"{command.import_path}"',) if command.import_path else ('update',)),
            '2>&1',
            '>',
            quoted(os.path.join(LOGS_DIR, 'archivebox.log')),

        ]
        new_job = cron.new(command=' '.join(cmd), comment=CRON_COMMENT)

        if command.every in ('minute', 'hour', 'day', 'week', 'month', 'year'):
            set_every = getattr(new_job.every(), command.every)
            set_every()
        elif CronSlices.is_valid(command.every):
            new_job.setall(command.every)
        else:
            stderr('{red}[X] Got invalid timeperiod for cron task.{reset}'.format(**ANSI))
            stderr('    It must be one of minute/hour/day/week/month')
            stderr('    or a quoted cron-format schedule like:')
            stderr('        archivebox init --every=day https://example.com/some/rss/feed.xml')
            stderr('        archivebox init --every="0/5 * * * *" https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        cron = dedupe_jobs(cron)
        cron.write()

        total_runs = sum(j.frequency_per_year() for j in cron)
        existing_jobs = list(cron.find_comment(CRON_COMMENT))

        print()
        print('{green}[√] Scheduled new ArchiveBox cron job for user: {} ({} jobs are active).{reset}'.format(USER, len(existing_jobs), **ANSI))
        print('\n'.join(f'  > {cmd}' if str(cmd) == str(new_job) else f'    {cmd}' for cmd in existing_jobs))
        if total_runs > 60 and not command.quiet:
            stderr()
            stderr('{lightyellow}[!] With the current cron config, ArchiveBox is estimated to run >{} times per year.{reset}'.format(total_runs, **ANSI))
            stderr(f'    Congrats on being an enthusiastic internet archiver! 👌')
            stderr()
            stderr('    Make sure you have enough storage space available to hold all the data.')
            stderr('    Using a compressed/deduped filesystem like ZFS is recommended if you plan on archiving a lot.')
        raise SystemExit(0)


def dedupe_jobs(cron: CronTab) -> CronTab:
    deduped = set()
    for job in list(cron):
        unique_tuple = (str(job.slices), job.command)
        if unique_tuple not in deduped:
            deduped.add(unique_tuple)
        cron.remove(job)

    for schedule, command in deduped:
        job = cron.new(command=command, comment=CRON_COMMENT)
        job.setall(schedule)
        job.enable()

    return cron


if __name__ == '__main__':
    main()
