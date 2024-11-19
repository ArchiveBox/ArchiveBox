#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox search'

from pathlib import Path
from typing import Optional, List, Iterable

import rich_click as click
from rich import print

from django.db.models import QuerySet

from archivebox.config import DATA_DIR
from archivebox.index import LINK_FILTERS
from archivebox.index.schema import Link
from archivebox.misc.logging import stderr
from archivebox.misc.util import enforce_types, docstring

STATUS_CHOICES = [
    'indexed', 'archived', 'unarchived', 'present', 'valid', 'invalid',
    'duplicate', 'orphaned', 'corrupted', 'unrecognized'
]



def list_links(snapshots: Optional[QuerySet]=None,
               filter_patterns: Optional[List[str]]=None,
               filter_type: str='substring',
               after: Optional[float]=None,
               before: Optional[float]=None,
               out_dir: Path=DATA_DIR) -> Iterable[Link]:
    
    from archivebox.index import load_main_index
    from archivebox.index import snapshot_filter

    if snapshots:
        all_snapshots = snapshots
    else:
        all_snapshots = load_main_index(out_dir=out_dir)

    if after is not None:
        all_snapshots = all_snapshots.filter(timestamp__gte=after)
    if before is not None:
        all_snapshots = all_snapshots.filter(timestamp__lt=before)
    if filter_patterns:
        all_snapshots = snapshot_filter(all_snapshots, filter_patterns, filter_type)

    if not all_snapshots:
        stderr('[!] No Snapshots matched your filters:', filter_patterns, f'({filter_type})', color='lightyellow')

    return all_snapshots


def list_folders(links: list[Link], status: str, out_dir: Path=DATA_DIR) -> dict[str, Link | None]:
    
    from archivebox.misc.checks import check_data_folder
    from archivebox.index import (
        get_indexed_folders,
        get_archived_folders,
        get_unarchived_folders,
        get_present_folders,
        get_valid_folders,
        get_invalid_folders,
        get_duplicate_folders,
        get_orphaned_folders,
        get_corrupted_folders,
        get_unrecognized_folders,
    )
    
    check_data_folder()

    STATUS_FUNCTIONS = {
        "indexed": get_indexed_folders,
        "archived": get_archived_folders,
        "unarchived": get_unarchived_folders,
        "present": get_present_folders,
        "valid": get_valid_folders,
        "invalid": get_invalid_folders,
        "duplicate": get_duplicate_folders,
        "orphaned": get_orphaned_folders,
        "corrupted": get_corrupted_folders,
        "unrecognized": get_unrecognized_folders,
    }

    try:
        return STATUS_FUNCTIONS[status](links, out_dir=out_dir)
    except KeyError:
        raise ValueError('Status not recognized.')




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

    snapshots = list_links(
        filter_patterns=list(filter_patterns) if filter_patterns else None,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    if sort:
        snapshots = snapshots.order_by(sort)

    folders = list_folders(
        links=snapshots,
        status=status,
        out_dir=DATA_DIR,
    )

    if json:
        from archivebox.index.json import generate_json_index_from_links
        output = generate_json_index_from_links(folders.values(), with_headers)
    elif html:
        from archivebox.index.html import generate_index_from_links
        output = generate_index_from_links(folders.values(), with_headers) 
    elif csv:
        from archivebox.index.csv import links_to_csv
        output = links_to_csv(folders.values(), csv.split(','), with_headers)
    else:
        from archivebox.misc.logging_util import printable_folders
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
