#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'

import sys
from pathlib import Path

from typing import TYPE_CHECKING

import rich_click as click

from django.utils import timezone
from django.db.models import QuerySet

from archivebox.misc.util import enforce_types, docstring
from archivebox import CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG, SERVER_CONFIG
from archivebox.config.permissions import USER, HOSTNAME


if TYPE_CHECKING:
    from archivebox.core.models import Snapshot


@enforce_types
def add(urls: str | list[str],
        depth: int | str=0,
        tag: str='',
        parser: str="auto",
        plugins: str="",
        persona: str='Default',
        overwrite: bool=False,
        update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
        index_only: bool=False,
        bg: bool=False,
        created_by_id: int | None=None) -> QuerySet['Snapshot']:
    """Add a new URL or list of URLs to your archive.

    The flow is:
    1. Save URLs to sources file
    2. Create Crawl with URLs and max_depth
    3. Orchestrator creates Snapshots from Crawl URLs (depth=0)
    4. Orchestrator runs parser extractors on root snapshots
    5. Parser extractors output to urls.jsonl
    6. URLs are added to Crawl.urls and child Snapshots are created
    7. Repeat until max_depth is reached
    """

    from rich import print

    depth = int(depth)

    assert depth in (0, 1, 2, 3, 4), 'Depth must be 0-4'

    # import models once django is set up
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.workers.orchestrator import Orchestrator
    from archivebox.misc.logging_util import printable_filesize
    from archivebox.misc.system import get_dir_size

    created_by_id = created_by_id or get_or_create_system_user_pk()
    started_at = timezone.now()

    # 1. Save the provided URLs to sources/2024-11-05__23-59-59__cli_add.txt
    sources_file = CONSTANTS.SOURCES_DIR / f'{timezone.now().strftime("%Y-%m-%d__%H-%M-%S")}__cli_add.txt'
    sources_file.parent.mkdir(parents=True, exist_ok=True)
    sources_file.write_text(urls if isinstance(urls, str) else '\n'.join(urls))

    # 2. Create a new Crawl with inline URLs
    cli_args = [*sys.argv]
    if cli_args[0].lower().endswith('archivebox'):
        cli_args[0] = 'archivebox'
    cmd_str = ' '.join(cli_args)

    timestamp = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")

    # Read URLs directly into crawl
    urls_content = sources_file.read_text()

    crawl = Crawl.objects.create(
        urls=urls_content,
        max_depth=depth,
        tags_str=tag,
        label=f'{USER}@{HOSTNAME} $ {cmd_str} [{timestamp}]',
        created_by_id=created_by_id,
        config={
            'ONLY_NEW': not update,
            'INDEX_ONLY': index_only,
            'OVERWRITE': overwrite,
            'PLUGINS': plugins,
            'DEFAULT_PERSONA': persona or 'Default',
            'PARSER': parser,
        }
    )

    print(f'[green]\\[+] Created Crawl {crawl.id} with max_depth={depth}[/green]')
    first_url = crawl.get_urls_list()[0] if crawl.get_urls_list() else ''
    print(f'    [dim]First URL: {first_url}[/dim]')

    # 3. The CrawlMachine will create Snapshots from all URLs when started
    #    Parser extractors run on snapshots and discover more URLs
    #    Discovered URLs become child Snapshots (depth+1)

    if index_only:
        # Just create the crawl but don't start processing
        print('[yellow]\\[*] Index-only mode - crawl created but not started[/yellow]')
        # Create snapshots for all URLs in the crawl
        for url in crawl.get_urls_list():
            Snapshot.objects.update_or_create(
                crawl=crawl, url=url,
                defaults={
                    'status': Snapshot.INITIAL_STATE,
                    'retry_at': timezone.now(),
                    'timestamp': str(timezone.now().timestamp()),
                    'depth': 0,
                },
            )
        return crawl.snapshot_set.all()

    # 5. Start the orchestrator to process the queue
    #    The orchestrator will:
    #    - Process Crawl -> create Snapshots from all URLs
    #    - Process Snapshots -> run extractors
    #    - Parser extractors discover new URLs -> create child Snapshots
    #    - Repeat until max_depth reached

    if bg:
        # Background mode: just queue work and return (orchestrator via server will pick it up)
        print('[yellow]\\[*] URLs queued. Orchestrator will process them (run `archivebox server` if not already running).[/yellow]')
    else:
        # Foreground mode: run full orchestrator until all work is done
        print(f'[green]\\[*] Starting orchestrator to process crawl...[/green]')
        from archivebox.workers.orchestrator import Orchestrator
        orchestrator = Orchestrator(exit_on_idle=True, crawl_id=str(crawl.id))
        orchestrator.runloop()  # Block until complete

        # Print summary for foreground runs
        try:
            crawl.refresh_from_db()
            snapshots_count = crawl.snapshot_set.count()
            try:
                total_bytes = sum(s.archive_size for s in crawl.snapshot_set.all())
            except Exception:
                total_bytes, _, _ = get_dir_size(crawl.output_dir)
            total_size = printable_filesize(total_bytes)
            total_time = timezone.now() - started_at
            total_seconds = int(total_time.total_seconds())
            mins, secs = divmod(total_seconds, 60)
            hours, mins = divmod(mins, 60)
            if hours:
                duration_str = f"{hours}h {mins}m {secs}s"
            elif mins:
                duration_str = f"{mins}m {secs}s"
            else:
                duration_str = f"{secs}s"

            # Output dir relative to DATA_DIR
            try:
                rel_output = Path(crawl.output_dir).relative_to(CONSTANTS.DATA_DIR)
                rel_output_str = f'./{rel_output}'
            except Exception:
                rel_output_str = str(crawl.output_dir)

            # Build admin URL from SERVER_CONFIG
            bind_addr = SERVER_CONFIG.BIND_ADDR
            if bind_addr.startswith('http://') or bind_addr.startswith('https://'):
                base_url = bind_addr
            else:
                base_url = f'http://{bind_addr}'
            admin_url = f'{base_url}/admin/crawls/crawl/{crawl.id}/change/'

            print('\n[bold]crawl output saved to:[/bold]')
            print(f'  {rel_output_str}')
            print(f'  {admin_url}')
            print(f'\n[bold]total urls snapshotted:[/bold] {snapshots_count}')
            print(f'[bold]total size:[/bold] {total_size}')
            print(f'[bold]total time:[/bold] {duration_str}')
        except Exception:
            # Summary is best-effort; avoid failing the command if something goes wrong
            pass

    # 6. Return the list of Snapshots in this crawl
    return crawl.snapshot_set.all()


@click.command()
@click.option('--depth', '-d', type=click.Choice([str(i) for i in range(5)]), default='0', help='Recursively archive linked pages up to N hops away')
@click.option('--tag', '-t', default='', help='Comma-separated list of tags to add to each snapshot e.g. tag1,tag2,tag3')
@click.option('--parser', default='auto', help='Parser for reading input URLs (auto, txt, html, rss, json, jsonl, netscape, ...)')
@click.option('--plugins', '-p', default='', help='Comma-separated list of plugins to run e.g. title,favicon,screenshot,singlefile,...')
@click.option('--persona', default='Default', help='Authentication profile to use when archiving')
@click.option('--overwrite', '-F', is_flag=True, help='Overwrite existing data if URLs have been archived previously')
@click.option('--update', is_flag=True, default=ARCHIVING_CONFIG.ONLY_NEW, help='Retry any previously skipped/failed URLs when re-adding them')
@click.option('--index-only', is_flag=True, help='Just add the URLs to the index without archiving them now')
@click.option('--bg', is_flag=True, help='Run archiving in background (start orchestrator and return immediately)')
@click.argument('urls', nargs=-1, type=click.Path())
@docstring(add.__doc__)
def main(**kwargs):
    """Add a new URL or list of URLs to your archive"""

    add(**kwargs)


if __name__ == '__main__':
    main()
