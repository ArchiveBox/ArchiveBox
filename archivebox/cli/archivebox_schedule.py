#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import rich_click as click
from rich import print

from archivebox.misc.util import enforce_types, docstring
from archivebox.config.common import ARCHIVING_CONFIG


@enforce_types
def schedule(add: bool = False,
            show: bool = False,
            clear: bool = False,
            foreground: bool = False,
            run_all: bool = False,
            quiet: bool = False,
            every: str | None = None,
            tag: str = '',
            depth: int | str = 0,
            overwrite: bool = False,
            update: bool = not ARCHIVING_CONFIG.ONLY_NEW,
            import_path: str | None = None):
    """Manage database-backed scheduled crawls processed by the crawl runner."""

    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.crawls.schedule_utils import validate_schedule
    from archivebox.services.runner import run_pending_crawls

    depth = int(depth)
    result: dict[str, object] = {
        'created_schedule_ids': [],
        'disabled_count': 0,
        'run_all_enqueued': 0,
        'active_schedule_ids': [],
    }

    def _active_schedules():
        return CrawlSchedule.objects.filter(is_enabled=True).select_related('template').order_by('created_at')

    if clear:
        disabled_count = CrawlSchedule.objects.filter(is_enabled=True).update(
            is_enabled=False,
            modified_at=timezone.now(),
        )
        result['disabled_count'] = disabled_count
        print(f'[green]\\[√] Disabled {disabled_count} scheduled crawl(s).[/green]')

    if every or add:
        schedule_str = (every or 'day').strip()
        validate_schedule(schedule_str)

        created_by_id = get_or_create_system_user_pk()
        is_update_schedule = not import_path
        template_urls = import_path or 'archivebox://update'
        template_label = (
            f'Scheduled import: {template_urls}'
            if import_path else
            'Scheduled ArchiveBox update'
        )[:64]
        template_notes = (
            f'Created by archivebox schedule for {template_urls}'
            if import_path else
            'Created by archivebox schedule to queue recurring archivebox://update maintenance crawls.'
        )

        template = Crawl.objects.create(
            urls=template_urls,
            max_depth=0 if is_update_schedule else depth,
            tags_str='' if is_update_schedule else tag,
            label=template_label,
            notes=template_notes,
            created_by_id=created_by_id,
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
            config={
                'ONLY_NEW': not update,
                'OVERWRITE': overwrite,
                'DEPTH': 0 if is_update_schedule else depth,
                'SCHEDULE_KIND': 'update' if is_update_schedule else 'crawl',
            },
        )
        crawl_schedule = CrawlSchedule.objects.create(
            template=template,
            schedule=schedule_str,
            is_enabled=True,
            label=template_label,
            notes=template_notes,
            created_by_id=created_by_id,
        )
        result['created_schedule_ids'] = [str(crawl_schedule.id)]

        schedule_type = 'maintenance update' if is_update_schedule else 'crawl'
        print(f'[green]\\[√] Created scheduled {schedule_type}.[/green]')
        print(f'    id={crawl_schedule.id}')
        print(f'    every={crawl_schedule.schedule}')
        print(f'    next_run={crawl_schedule.next_run_at.isoformat()}')
        if import_path:
            print(f'    source={import_path}')

    schedules = list(_active_schedules())
    result['active_schedule_ids'] = [str(schedule.id) for schedule in schedules]

    if show:
        if schedules:
            print(f'[green]\\[*] Active scheduled crawls: {len(schedules)}[/green]')
            for scheduled_crawl in schedules:
                template = scheduled_crawl.template
                print(
                    f'  - id={scheduled_crawl.id} every={scheduled_crawl.schedule} '
                    f'next_run={scheduled_crawl.next_run_at.isoformat()} '
                    f'source={template.urls.splitlines()[0] if template.urls else ""}'
                )
        else:
            print('[yellow]\\[*] No scheduled crawls are enabled.[/yellow]')

    if run_all:
        enqueued = 0
        now = timezone.now()
        for scheduled_crawl in schedules:
            scheduled_crawl.enqueue(queued_at=now)
            enqueued += 1
        result['run_all_enqueued'] = enqueued
        print(f'[green]\\[*] Enqueued {enqueued} scheduled crawl(s) immediately.[/green]')
        if enqueued:
            print('[yellow]\\[*] Start `archivebox server`, `archivebox run --daemon`, or `archivebox schedule --foreground` to process the queued crawls.[/yellow]')

    if foreground:
        print('[green]\\[*] Starting global crawl runner in foreground mode. It will materialize scheduled crawls and process queued work.[/green]')
        run_pending_crawls(daemon=True)

    if quiet:
        return result

    if not any((every, add, show, clear, foreground, run_all)):
        if schedules:
            print('[green]\\[*] Active scheduled crawls:[/green]')
            for scheduled_crawl in schedules:
                print(f'  - {scheduled_crawl.id} every={scheduled_crawl.schedule} next_run={scheduled_crawl.next_run_at.isoformat()}')
        else:
            print('[yellow]\\[*] No scheduled crawls are enabled.[/yellow]')

    return result


@click.command()
@click.option('--quiet', '-q', is_flag=True, help="Return structured results without extra summary output")
@click.option('--add', is_flag=True, help='Create a new scheduled crawl')
@click.option('--every', type=str, help='Run on an alias like daily/weekly/monthly or a cron expression such as "0 */6 * * *"')
@click.option('--tag', '-t', default='', help='Comma-separated tags to apply to scheduled crawl snapshots')
@click.option('--depth', type=click.Choice([str(i) for i in range(5)]), default='0', help='Recursively archive linked pages up to N hops away')
@click.option('--overwrite', is_flag=True, help='Overwrite existing data if URLs have been archived previously')
@click.option('--update', is_flag=True, help='Retry previously failed/skipped URLs when scheduled crawls run')
@click.option('--clear', is_flag=True, help='Disable all currently enabled schedules')
@click.option('--show', is_flag=True, help='Print all currently enabled schedules')
@click.option('--foreground', '-f', is_flag=True, help='Run the global crawl runner in the foreground (no crontab required)')
@click.option('--run-all', is_flag=True, help='Enqueue all enabled schedules immediately and process them once')
@click.argument('import_path', required=False)
@docstring(schedule.__doc__)
def main(**kwargs):
    """Manage database-backed scheduled crawls processed by the crawl runner."""
    schedule(**kwargs)


if __name__ == '__main__':
    main()
