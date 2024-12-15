#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import sys
from pathlib import Path

import rich_click as click
from rich import print

from archivebox.misc.util import enforce_types, docstring
from archivebox.config import DATA_DIR, CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG
from archivebox.config.permissions import USER


CRON_COMMENT = 'ArchiveBox'


@enforce_types
def schedule(add: bool=False,
            show: bool=False,
            clear: bool=False,
            foreground: bool=False,
            run_all: bool=False,
            quiet: bool=False,
            every: str | None=None,
            tag: str='',
            depth: int | str=0,
            overwrite: bool=False,
            update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
            import_path: str | None=None,
            out_dir: Path=DATA_DIR) -> None:
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
 
    depth = int(depth)
    
    from crontab import CronTab, CronSlices
    from archivebox.misc.system import dedupe_cron_jobs
    from abx_plugin_pip.binaries import ARCHIVEBOX_BINARY

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
            print('[red]\\[X] Got invalid timeperiod for cron task.[/red]')
            print('    It must be one of minute/hour/day/month')
            print('    or a quoted cron-format schedule like:')
            print('        archivebox init --every=day --depth=1 https://example.com/some/rss/feed.xml')
            print('        archivebox init --every="0/5 * * * *" --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        cron = dedupe_cron_jobs(cron)
        print(cron)
        cron.write()

        total_runs = sum(j.frequency_per_year() for j in cron)
        existing_jobs = list(cron.find_command('archivebox'))

        print()
        print('[green]\\[√] Scheduled new ArchiveBox cron job for user: {} ({} jobs are active).[/green]'.format(USER, len(existing_jobs)))
        print('\n'.join(f'  > {cmd}' if str(cmd) == str(new_job) else f'    {cmd}' for cmd in existing_jobs))
        if total_runs > 60 and not quiet:
            print()
            print('[yellow]\\[!] With the current cron config, ArchiveBox is estimated to run >{} times per year.[/yellow]'.format(total_runs))
            print('    Congrats on being an enthusiastic internet archiver! 👌')
            print()
            print('    [violet]Make sure you have enough storage space available to hold all the data.[/violet]')
            print('    Using a compressed/deduped filesystem like ZFS is recommended if you plan on archiving a lot.')
            print()
    elif show:
        if existing_jobs:
            print('\n'.join(str(cmd) for cmd in existing_jobs))
        else:
            print('[red]\\[X] There are no ArchiveBox cron jobs scheduled for your user ({}).[/red]'.format(USER))
            print('    To schedule a new job, run:')
            print('        archivebox schedule --every=[timeperiod] --depth=1 https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    if foreground or run_all:
        if not existing_jobs:
            print('[red]\\[X] You must schedule some jobs first before running in foreground mode.[/red]')
            print('    archivebox schedule --every=hour --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        print('[green]\\[*] Running {} ArchiveBox jobs in foreground task scheduler...[/green]'.format(len(existing_jobs)))
        if run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command.split("/archivebox ")[0].split(" && ")[0]}\n')
                    sys.stdout.write(f'    > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r    √ {job.command.split("/archivebox ")[-1]}\n')
            except KeyboardInterrupt:
                print('\n[green]\\[√] Stopped.[/green] (Ctrl+C)')
                raise SystemExit(1)

        if foreground:
            try:
                for job in existing_jobs:
                    print(f'  > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                for result in cron.run_scheduler():
                    print(result)
            except KeyboardInterrupt:
                print('\n[green]\\[√] Stopped.[/green] (Ctrl+C)')
                raise SystemExit(1)


@click.command()
@click.option('--quiet', '-q', is_flag=True, help="Don't warn about storage space")
@click.option('--add', is_flag=True, help='Add a new scheduled ArchiveBox update job to cron')
@click.option('--every', type=str, help='Run ArchiveBox once every [timeperiod] (hour/day/month/year or cron format e.g. "0 0 * * *")')
@click.option('--tag', '-t', default='', help='Tag the added URLs with the provided tags e.g. --tag=tag1,tag2,tag3')
@click.option('--depth', type=click.Choice(['0', '1']), default='0', help='Depth to archive to [0] or 1')
@click.option('--overwrite', is_flag=True, help='Re-archive any URLs that have been previously archived, overwriting existing Snapshots')
@click.option('--update', is_flag=True, help='Re-pull any URLs that have been previously added, as needed to fill missing ArchiveResults')
@click.option('--clear', is_flag=True, help='Stop all ArchiveBox scheduled runs (remove cron jobs)')
@click.option('--show', is_flag=True, help='Print a list of currently active ArchiveBox cron jobs')
@click.option('--foreground', '-f', is_flag=True, help='Launch ArchiveBox scheduler as a long-running foreground task instead of using cron')
@click.option('--run-all', is_flag=True, help='Run all the scheduled jobs once immediately, independent of their configured schedules')
@click.argument('import_path', required=False)
@docstring(schedule.__doc__)
def main(**kwargs):
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
    schedule(**kwargs)


if __name__ == '__main__':
    main()
