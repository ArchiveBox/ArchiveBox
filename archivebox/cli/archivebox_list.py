#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox list'

import sys
from typing import Optional

import rich_click as click

from archivebox.cli.archivebox_snapshot import list_snapshots


@click.command()
@click.option('--status', '-s', help='Filter by status (queued, started, sealed)')
@click.option('--url__icontains', help='Filter by URL contains')
@click.option('--url__istartswith', help='Filter by URL starts with')
@click.option('--tag', '-t', help='Filter by tag name')
@click.option('--crawl-id', help='Filter by crawl ID')
@click.option('--limit', '-n', type=int, help='Limit number of results')
@click.option('--sort', '-o', type=str, help='Field to sort by, e.g. url, created_at, bookmarked_at, downloaded_at')
@click.option('--csv', '-C', type=str, help='Print output as CSV with the provided fields, e.g.: timestamp,url,title')
@click.option('--with-headers', is_flag=True, help='Include column headers in structured output')
def main(status: Optional[str], url__icontains: Optional[str], url__istartswith: Optional[str],
         tag: Optional[str], crawl_id: Optional[str], limit: Optional[int],
         sort: Optional[str], csv: Optional[str], with_headers: bool) -> None:
    """List Snapshots."""
    sys.exit(list_snapshots(
        status=status,
        url__icontains=url__icontains,
        url__istartswith=url__istartswith,
        tag=tag,
        crawl_id=crawl_id,
        limit=limit,
        sort=sort,
        csv=csv,
        with_headers=with_headers,
    ))


if __name__ == '__main__':
    main()
