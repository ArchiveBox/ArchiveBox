#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox remove'

import shutil
from pathlib import Path
from typing import Iterable

import rich_click as click

from django.db.models import QuerySet

from archivebox.config import DATA_DIR
from archivebox.config.django import setup_django
from archivebox.misc.util import enforce_types, docstring
from archivebox.misc.checks import check_data_folder
from archivebox.misc.logging_util import (
    log_list_started,
    log_list_finished,
    log_removal_started,
    log_removal_finished,
    TimedProgress,
)


@enforce_types
def remove(filter_patterns: Iterable[str]=(),
          filter_type: str='exact',
          snapshots: QuerySet | None=None,
          after: float | None=None,
          before: float | None=None,
          yes: bool=False,
          delete: bool=False,
          out_dir: Path=DATA_DIR) -> QuerySet:
    """Remove the specified URLs from the archive"""
    
    setup_django()
    check_data_folder()
    
    from archivebox.cli.archivebox_search import get_snapshots

    log_list_started(filter_patterns, filter_type)
    timer = TimedProgress(360, prefix='      ')
    try:
        snapshots = get_snapshots(
            snapshots=snapshots,
            filter_patterns=list(filter_patterns) if filter_patterns else None,
            filter_type=filter_type,
            after=after,
            before=before,
        )
    finally:
        timer.end()

    if not snapshots.exists():
        log_removal_finished(0, 0)
        raise SystemExit(1)

    log_list_finished(snapshots)
    log_removal_started(snapshots, yes=yes, delete=delete)

    timer = TimedProgress(360, prefix='      ')
    try:
        for snapshot in snapshots:
            if delete:
                shutil.rmtree(snapshot.output_dir, ignore_errors=True)
    finally:
        timer.end()

    to_remove = snapshots.count()

    from archivebox.search import flush_search_index
    from archivebox.core.models import Snapshot

    flush_search_index(snapshots=snapshots)
    snapshots.delete()
    all_snapshots = Snapshot.objects.all()
    log_removal_finished(all_snapshots.count(), to_remove)

    return all_snapshots


@click.command()
@click.option('--yes', is_flag=True, help='Remove links instantly without prompting to confirm')
@click.option('--delete', is_flag=True, help='Delete the archived content and metadata folder in addition to removing from index')
@click.option('--before', type=float, help='Remove only URLs bookmarked before timestamp')
@click.option('--after', type=float, help='Remove only URLs bookmarked after timestamp')
@click.option('--filter-type', '-f', type=click.Choice(('exact', 'substring', 'domain', 'regex', 'tag')), default='exact', help='Type of pattern matching to use when filtering URLs')
@click.argument('filter_patterns', nargs=-1)
@docstring(remove.__doc__)
def main(**kwargs):
    """Remove the specified URLs from the archive"""
    remove(**kwargs)


if __name__ == '__main__':
    main()
