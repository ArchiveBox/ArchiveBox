#!/usr/bin/env python3

"""
archivebox crawl [urls...] [--depth=N] [--tag=TAG]

Create Crawl jobs from URLs. Accepts URLs as arguments, from stdin, or via JSONL.
Does NOT immediately start the crawl - pipe to `archivebox snapshot` to process.

Input formats:
    - Plain URLs (one per line)
    - JSONL: {"url": "...", "depth": 1, "tags": "..."}

Output (JSONL):
    {"type": "Crawl", "id": "...", "urls": "...", "status": "queued", ...}

Examples:
    # Create a crawl job
    archivebox crawl https://example.com

    # Create crawl with depth
    archivebox crawl --depth=1 https://example.com

    # Full pipeline: create crawl, create snapshots, run extractors
    archivebox crawl https://example.com | archivebox snapshot | archivebox extract

    # Process existing Crawl by ID (runs the crawl state machine)
    archivebox crawl 01234567-89ab-cdef-0123-456789abcdef
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox crawl'

import sys
from typing import Optional

import rich_click as click


def create_crawls(
    args: tuple,
    depth: int = 0,
    tag: str = '',
    created_by_id: Optional[int] = None,
) -> int:
    """
    Create a single Crawl job from all input URLs.

    Reads from args or stdin, creates one Crawl with all URLs, outputs JSONL.
    Does NOT start the crawl - just creates the job in QUEUED state.

    Exit codes:
        0: Success
        1: Failure
    """
    from rich import print as rprint

    from archivebox.misc.jsonl import read_args_or_stdin, write_record
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl

    created_by_id = created_by_id or get_or_create_system_user_pk()
    is_tty = sys.stdout.isatty()

    # Collect all input records
    records = list(read_args_or_stdin(args))

    if not records:
        rprint('[yellow]No URLs provided. Pass URLs as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # Collect all URLs into a single newline-separated string
    urls = []
    for record in records:
        url = record.get('url')
        if url:
            urls.append(url)

    if not urls:
        rprint('[red]No valid URLs found[/red]', file=sys.stderr)
        return 1

    try:
        # Build crawl record with all URLs as newline-separated string
        crawl_record = {
            'urls': '\n'.join(urls),
            'max_depth': depth,
            'tags_str': tag,
            'label': '',
        }

        crawl = Crawl.from_jsonl(crawl_record, overrides={'created_by_id': created_by_id})
        if not crawl:
            rprint('[red]Failed to create crawl[/red]', file=sys.stderr)
            return 1

        # Output JSONL record (only when piped)
        if not is_tty:
            write_record(crawl.to_jsonl())

        rprint(f'[green]Created crawl with {len(urls)} URLs[/green]', file=sys.stderr)

        # If TTY, show human-readable output
        if is_tty:
            rprint(f'  [dim]{crawl.id}[/dim]', file=sys.stderr)
            for url in urls[:5]:  # Show first 5 URLs
                rprint(f'    {url[:70]}', file=sys.stderr)
            if len(urls) > 5:
                rprint(f'    ... and {len(urls) - 5} more', file=sys.stderr)

        return 0

    except Exception as e:
        rprint(f'[red]Error creating crawl: {e}[/red]', file=sys.stderr)
        return 1


def process_crawl_by_id(crawl_id: str) -> int:
    """
    Process a single Crawl by ID (used by workers).

    Triggers the Crawl's state machine tick() which will:
    - Transition from queued -> started (creates root snapshot)
    - Transition from started -> sealed (when all snapshots done)
    """
    from rich import print as rprint
    from archivebox.crawls.models import Crawl

    try:
        crawl = Crawl.objects.get(id=crawl_id)
    except Crawl.DoesNotExist:
        rprint(f'[red]Crawl {crawl_id} not found[/red]', file=sys.stderr)
        return 1

    rprint(f'[blue]Processing Crawl {crawl.id} (status={crawl.status})[/blue]', file=sys.stderr)

    try:
        crawl.sm.tick()
        crawl.refresh_from_db()
        rprint(f'[green]Crawl complete (status={crawl.status})[/green]', file=sys.stderr)
        return 0
    except Exception as e:
        rprint(f'[red]Crawl error: {type(e).__name__}: {e}[/red]', file=sys.stderr)
        return 1


def is_crawl_id(value: str) -> bool:
    """Check if value looks like a Crawl UUID."""
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(value):
        return False
    # Verify it's actually a Crawl (not a Snapshot or other object)
    from archivebox.crawls.models import Crawl
    return Crawl.objects.filter(id=value).exists()


@click.command()
@click.option('--depth', '-d', type=int, default=0, help='Max depth for recursive crawling (default: 0, no recursion)')
@click.option('--tag', '-t', default='', help='Comma-separated tags to add to snapshots')
@click.argument('args', nargs=-1)
def main(depth: int, tag: str, args: tuple):
    """Create Crawl jobs from URLs, or process existing Crawls by ID"""
    from archivebox.misc.jsonl import read_args_or_stdin

    # Read all input
    records = list(read_args_or_stdin(args))

    if not records:
        from rich import print as rprint
        rprint('[yellow]No URLs or Crawl IDs provided. Pass as arguments or via stdin.[/yellow]', file=sys.stderr)
        sys.exit(1)

    # Check if input looks like existing Crawl IDs to process
    # If ALL inputs are Crawl UUIDs, process them
    all_are_crawl_ids = all(
        is_crawl_id(r.get('id') or r.get('url', ''))
        for r in records
    )

    if all_are_crawl_ids:
        # Process existing Crawls by ID
        exit_code = 0
        for record in records:
            crawl_id = record.get('id') or record.get('url')
            result = process_crawl_by_id(crawl_id)
            if result != 0:
                exit_code = result
        sys.exit(exit_code)
    else:
        # Default behavior: create Crawl jobs from URLs
        sys.exit(create_crawls(args, depth=depth, tag=tag))


if __name__ == '__main__':
    main()
