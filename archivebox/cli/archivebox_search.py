#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox search'

from pathlib import Path
from typing import Optional, List, Any

import rich_click as click
from rich import print

from django.db.models import QuerySet

from archivebox.config import DATA_DIR
from archivebox.misc.logging import stderr
from archivebox.misc.util import enforce_types, docstring

# Filter types for URL matching
LINK_FILTERS = {
    'exact': lambda pattern: {'url': pattern},
    'substring': lambda pattern: {'url__icontains': pattern},
    'regex': lambda pattern: {'url__iregex': pattern},
    'domain': lambda pattern: {'url__istartswith': f'http://{pattern}'},
    'tag': lambda pattern: {'tags__name': pattern},
    'timestamp': lambda pattern: {'timestamp': pattern},
}

STATUS_CHOICES = ['indexed', 'archived', 'unarchived']



def get_snapshots(snapshots: Optional[QuerySet]=None,
                  filter_patterns: Optional[List[str]]=None,
                  filter_type: str='substring',
                  after: Optional[float]=None,
                  before: Optional[float]=None,
                  out_dir: Path=DATA_DIR) -> QuerySet:
    """Filter and return Snapshots matching the given criteria."""
    from archivebox.core.models import Snapshot

    if snapshots:
        result = snapshots
    else:
        result = Snapshot.objects.all()

    if after is not None:
        result = result.filter(timestamp__gte=after)
    if before is not None:
        result = result.filter(timestamp__lt=before)
    if filter_patterns:
        result = Snapshot.objects.filter_by_patterns(filter_patterns, filter_type)

    # Prefetch crawl relationship to avoid N+1 queries when accessing output_dir
    result = result.select_related('crawl', 'crawl__created_by')

    if not result:
        stderr('[!] No Snapshots matched your filters:', filter_patterns, f'({filter_type})', color='lightyellow')

    return result


@enforce_types
def search(filter_patterns: list[str] | None=None,
           filter_type: str='substring',
           status: str='indexed',
           before: float | None=None,
           after: float | None=None,
           sort: str | None=None,
           json: bool=False,
           html: bool=False,
           csv: str | None=None,
           with_headers: bool=False):
    """List, filter, and export information about archive entries"""
    from archivebox.core.models import Snapshot

    if with_headers and not (json or html or csv):
        stderr('[X] --with-headers requires --json, --html or --csv\n', color='red')
        raise SystemExit(2)

    # Query DB directly - no filesystem scanning
    snapshots = get_snapshots(
        filter_patterns=list(filter_patterns) if filter_patterns else None,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    # Apply status filter
    if status == 'archived':
        snapshots = snapshots.filter(downloaded_at__isnull=False)
    elif status == 'unarchived':
        snapshots = snapshots.filter(downloaded_at__isnull=True)
    # 'indexed' = all snapshots (no filter)

    if sort:
        snapshots = snapshots.order_by(sort)

    # Export to requested format
    if json:
        output = snapshots.to_json(with_headers=with_headers)
    elif html:
        output = snapshots.to_html(with_headers=with_headers)
    elif csv:
        output = snapshots.to_csv(cols=csv.split(','), header=with_headers)
    else:
        from archivebox.misc.logging_util import printable_folders
        # Convert to dict for printable_folders
        folders = {s.output_dir: s for s in snapshots}
        output = printable_folders(folders, with_headers)

    print(output)
    return output


@click.command()
@click.option('--filter-type', '-f', type=click.Choice(['search', *LINK_FILTERS.keys()]), default='substring', help='Pattern matching type for filtering URLs')
@click.option('--status', '-s', type=click.Choice(STATUS_CHOICES), default='indexed', help='List snapshots with the given status')
@click.option('--before', '-b', type=float, help='List snapshots bookmarked before the given UNIX timestamp')
@click.option('--after', '-a', type=float, help='List snapshots bookmarked after the given UNIX timestamp')
@click.option('--sort', '-o', type=str, help='Field to sort by, e.g. url, created_at, bookmarked_at, downloaded_at')
@click.option('--json', '-J', is_flag=True, help='Print output in JSON format')
@click.option('--html', '-M', is_flag=True, help='Print output in HTML format (suitable for viewing statically without a server)')
@click.option('--csv', '-C', type=str, help='Print output as CSV with the provided fields, e.g.: created_at,url,title')
@click.option('--with-headers', '-H', is_flag=True, help='Include extra CSV/HTML headers in the output')
@click.help_option('--help', '-h')
@click.argument('filter_patterns', nargs=-1)
@docstring(search.__doc__)
def main(**kwargs):
    return search(**kwargs)



if __name__ == '__main__':
    main()
