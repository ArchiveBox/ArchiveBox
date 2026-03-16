#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox search'

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import rich_click as click

from django.db.models import Q, QuerySet

from archivebox.config import DATA_DIR
from archivebox.misc.logging import stderr
from archivebox.misc.util import enforce_types, docstring

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot

# Filter types for URL matching
LINK_FILTERS: dict[str, Callable[[str], Q]] = {
    'exact': lambda pattern: Q(url=pattern),
    'substring': lambda pattern: Q(url__icontains=pattern),
    'regex': lambda pattern: Q(url__iregex=pattern),
    'domain': lambda pattern: (
        Q(url__istartswith=f'http://{pattern}')
        | Q(url__istartswith=f'https://{pattern}')
        | Q(url__istartswith=f'ftp://{pattern}')
    ),
    'tag': lambda pattern: Q(tags__name=pattern),
    'timestamp': lambda pattern: Q(timestamp=pattern),
}

STATUS_CHOICES = ['indexed', 'archived', 'unarchived']


def _apply_pattern_filters(
    snapshots: QuerySet['Snapshot', 'Snapshot'],
    filter_patterns: list[str],
    filter_type: str,
) -> QuerySet['Snapshot', 'Snapshot']:
    filter_builder = LINK_FILTERS.get(filter_type)
    if filter_builder is None:
        stderr()
        stderr(f'[X] Got invalid pattern for --filter-type={filter_type}', color='red')
        raise SystemExit(2)

    query = Q()
    for pattern in filter_patterns:
        query |= filter_builder(pattern)
    return snapshots.filter(query)


def _snapshots_to_json(
    snapshots: QuerySet['Snapshot', 'Snapshot'],
    *,
    with_headers: bool,
) -> str:
    from datetime import datetime, timezone as tz

    from archivebox.config import VERSION
    from archivebox.config.common import SERVER_CONFIG
    from archivebox.misc.util import to_json

    main_index_header = {
        'info': 'This is an index of site data archived by ArchiveBox: The self-hosted web archive.',
        'schema': 'archivebox.index.json',
        'copyright_info': SERVER_CONFIG.FOOTER_INFO,
        'meta': {
            'project': 'ArchiveBox',
            'version': VERSION,
            'git_sha': VERSION,
            'website': 'https://ArchiveBox.io',
            'docs': 'https://github.com/ArchiveBox/ArchiveBox/wiki',
            'source': 'https://github.com/ArchiveBox/ArchiveBox',
            'issues': 'https://github.com/ArchiveBox/ArchiveBox/issues',
            'dependencies': {},
        },
    } if with_headers else {}

    snapshot_dicts = [snapshot.to_dict(extended=True) for snapshot in snapshots.iterator(chunk_size=500)]
    output: dict[str, object] | list[dict[str, object]]
    if with_headers:
        output = {
            **main_index_header,
            'num_links': len(snapshot_dicts),
            'updated': datetime.now(tz.utc),
            'last_run_cmd': sys.argv,
            'links': snapshot_dicts,
        }
    else:
        output = snapshot_dicts

    return to_json(output, indent=4, sort_keys=True)


def _snapshots_to_csv(
    snapshots: QuerySet['Snapshot', 'Snapshot'],
    *,
    cols: list[str],
    with_headers: bool,
) -> str:
    header = ','.join(cols) if with_headers else ''
    rows = [snapshot.to_csv(cols=cols, separator=',') for snapshot in snapshots.iterator(chunk_size=500)]
    return '\n'.join((header, *rows))


def _snapshots_to_html(
    snapshots: QuerySet['Snapshot', 'Snapshot'],
    *,
    with_headers: bool,
) -> str:
    from datetime import datetime, timezone as tz

    from django.template.loader import render_to_string

    from archivebox.config import VERSION
    from archivebox.config.common import SERVER_CONFIG
    from archivebox.config.version import get_COMMIT_HASH

    template = 'static_index.html' if with_headers else 'minimal_index.html'
    snapshot_list = list(snapshots.iterator(chunk_size=500))

    return render_to_string(template, {
        'version': VERSION,
        'git_sha': get_COMMIT_HASH() or VERSION,
        'num_links': str(len(snapshot_list)),
        'date_updated': datetime.now(tz.utc).strftime('%Y-%m-%d'),
        'time_updated': datetime.now(tz.utc).strftime('%Y-%m-%d %H:%M'),
        'links': snapshot_list,
        'FOOTER_INFO': SERVER_CONFIG.FOOTER_INFO,
    })


def get_snapshots(snapshots: QuerySet['Snapshot', 'Snapshot'] | None=None,
                  filter_patterns: list[str] | None=None,
                  filter_type: str='substring',
                  after: float | None=None,
                  before: float | None=None,
                  out_dir: Path=DATA_DIR) -> QuerySet['Snapshot', 'Snapshot']:
    """Filter and return Snapshots matching the given criteria."""
    from archivebox.core.models import Snapshot

    if snapshots is not None:
        result = snapshots
    else:
        result = Snapshot.objects.all()

    if after is not None:
        result = result.filter(timestamp__gte=after)
    if before is not None:
        result = result.filter(timestamp__lt=before)
    if filter_patterns:
        result = _apply_pattern_filters(result, filter_patterns, filter_type)

    # Prefetch crawl relationship to avoid N+1 queries when accessing output_dir
    result = result.select_related('crawl', 'crawl__created_by')

    if not result.exists():
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
        output = _snapshots_to_json(snapshots, with_headers=with_headers)
    elif html:
        output = _snapshots_to_html(snapshots, with_headers=with_headers)
    elif csv:
        output = _snapshots_to_csv(snapshots, cols=csv.split(','), with_headers=with_headers)
    else:
        from archivebox.misc.logging_util import printable_folders
        # Convert to dict for printable_folders
        folders: dict[str, Snapshot | None] = {str(snapshot.output_dir): snapshot for snapshot in snapshots}
        output = printable_folders(folders, with_headers)

    # Structured exports must be written directly to stdout.
    # rich.print() reflows long lines to console width, which corrupts JSON/CSV/HTML output.
    sys.stdout.write(output)
    if not output.endswith('\n'):
        sys.stdout.write('\n')
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
