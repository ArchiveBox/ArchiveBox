#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'

import sys

from typing import TYPE_CHECKING

import rich_click as click

from django.utils import timezone
from django.db.models import QuerySet

from archivebox.misc.util import enforce_types, docstring
from archivebox import CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG
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

    created_by_id = created_by_id or get_or_create_system_user_pk()

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

    # 3. The CrawlMachine will create the root Snapshot when started
    #    If URLs are from a file: first URL = file:///path/to/sources/...txt
    #    Parser extractors will run on it and discover more URLs
    #    Those URLs become child Snapshots (depth=1)

    if index_only:
        # Just create the crawl but don't start processing
        print('[yellow]\\[*] Index-only mode - crawl created but not started[/yellow]')
        # Create root snapshot manually
        crawl.create_root_snapshot()
        return crawl.snapshot_set.all()

    # 5. Start the orchestrator to process the queue
    #    The orchestrator will:
    #    - Process Crawl -> create root Snapshot
    #    - Process root Snapshot -> run parser extractors -> discover URLs
    #    - Create child Snapshots from discovered URLs
    #    - Process child Snapshots -> run extractors
    #    - Repeat until max_depth reached

    if bg:
        # Background mode: just queue work and return (orchestrator via server will pick it up)
        print('[yellow]\\[*] URLs queued. Orchestrator will process them (run `archivebox server` if not already running).[/yellow]')
    else:
        # Foreground mode: run orchestrator inline until all work is done
        print(f'[green]\\[*] Starting orchestrator to process crawl...[/green]')
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.runloop()  # Block until complete

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
