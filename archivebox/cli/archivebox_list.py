#!/usr/bin/env python3

__package__ = "archivebox.cli"
__command__ = "archivebox list"

import sys

import rich_click as click

from archivebox.cli.archivebox_snapshot import list_snapshots


@click.command()
@click.option("--status", "-s", help="Filter by status (queued, started, sealed)")
@click.option("--url__icontains", help="Filter by URL contains")
@click.option("--url__istartswith", help="Filter by URL starts with")
@click.option("--tag", "-t", help="Filter by tag name")
@click.option("--crawl-id", help="Filter by crawl ID")
@click.option("--limit", "-n", type=int, help="Limit number of results")
@click.option("--sort", "-o", type=str, help="Field to sort by, e.g. url, created_at, bookmarked_at, downloaded_at")
@click.option("--csv", "-C", type=str, help="Print output as CSV with the provided fields, e.g.: timestamp,url,title")
@click.option("--with-headers", is_flag=True, help="Include column headers in structured output")
@click.option("--search", type=click.Choice(["meta", "content", "contents", "deep"]), help="Search mode to use for the query")
@click.argument("query", nargs=-1)
def main(
    status: str | None,
    url__icontains: str | None,
    url__istartswith: str | None,
    tag: str | None,
    crawl_id: str | None,
    limit: int | None,
    sort: str | None,
    csv: str | None,
    with_headers: bool,
    search: str | None,
    query: tuple[str, ...],
) -> None:
    """List Snapshots."""
    sys.exit(
        list_snapshots(
            status=status,
            url__icontains=url__icontains,
            url__istartswith=url__istartswith,
            tag=tag,
            crawl_id=crawl_id,
            limit=limit,
            sort=sort,
            csv=csv,
            with_headers=with_headers,
            search=search,
            query=" ".join(query),
        ),
    )


if __name__ == "__main__":
    main()
